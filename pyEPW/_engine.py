"""Internal ERA5 conversion engine; public entry points are in :mod:`api`."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import calendar
import csv
import logging
import math
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import APIClient, ARCHIVE_URL
from .exceptions import APIError, DataError as WeatherError
from .models import Location, WeatherDataset
from ._daylight import perez_daylight
from ._solar import solar_interval
from .observations import load_observations, lineage_runs
from .quality import field_coverage
from .supplements import SnowHistory, load_power_albedo, interval_albedo

UTC = timezone.utc
HOUR = timedelta(hours=1)
logger = logging.getLogger(__name__)

CORE_UNITS = {
    "temperature_2m": "°C",
    "dew_point_2m": "°C",
    "relative_humidity_2m": "%",
    "surface_pressure": "hPa",
    "wind_speed_10m": "m/s",
    "wind_direction_10m": "°",
    "shortwave_radiation": "W/m²",
    "direct_normal_irradiance": "W/m²",
    "diffuse_radiation": "W/m²",
    "cloud_cover": "%",
    "rain": "mm",
}


RADIATION = ("shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation")
WATER_UNITS = {"total_column_integrated_water_vapour": "kg/m²"}


def standard_utc_offset(timezone_name: str, year: int, override: float | None = None) -> timedelta:
    if override is not None:
        if not math.isfinite(override) or not -12 <= override <= 14:
            raise WeatherError("--utc-offset must be between -12 and +14 hours.")
        return timedelta(minutes=round(override * 60))
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise WeatherError(
            "Timezone database is missing. Run: python -m pip install tzdata\n"
            "Alternatively supply --utc-offset with your fixed standard UTC offset."
        ) from exc
    # IANA describes Irish winter time as *negative* DST. Conventional Irish
    # weather files use GMT all year, not IANA's +01 'standard' base offset.
    if timezone_name in ("Europe/Dublin", "Eire"):
        return timedelta(0)
    reference = datetime(year, 1, 15, 12, tzinfo=zone)
    offset = reference.utcoffset() - (reference.dst() or timedelta(0))
    # EPW uses one fixed offset even if the jurisdiction changed its base time.
    # Round pre-1970 historical offsets that include seconds to the nearest minute.
    return timedelta(minutes=round(offset.total_seconds() / 60))


def year_boundaries(year: int, offset: timedelta) -> tuple[datetime, datetime]:
    local_zone = timezone(offset)
    first_end = datetime(year, 1, 1, 1, tzinfo=local_zone)
    final_end = datetime(year + 1, 1, 1, tzinfo=local_zone)
    return first_end, final_end


def source_date_range(year: int, offset: timedelta) -> tuple[date, date]:
    first_end, final_end = year_boundaries(year, offset)
    first_utc = first_end.astimezone(UTC)
    final_utc = final_end.astimezone(UTC)
    floor_final = final_utc.replace(minute=0, second=0, microsecond=0)
    ceiling_final = floor_final + HOUR if final_utc != floor_final else floor_final
    return first_utc.date(), ceiling_final.date()


def month_chunks(start: date, end: date):
    while start <= end:
        last_day = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        chunk_end = min(last_day, end)
        yield start, chunk_end
        start = chunk_end + timedelta(days=1)


def download_hourly(
    client: APIClient, location: Location, model: str, units: dict[str, str], start: date, end: date
) -> tuple[dict, list]:
    rows: dict[int, dict[str, float | None]] = {}
    grids = []
    for begin, finish in month_chunks(start, end):
        logger.info("Reading %s: %s to %s", model, begin, finish)
        parameters = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "start_date": begin.isoformat(),
            "end_date": finish.isoformat(),
            "hourly": ",".join(units),
            "models": model,
            "timezone": "GMT",
            "timeformat": "unixtime",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        }
        if location.elevation is not None:
            parameters["elevation"] = location.elevation
        response = client.get(ARCHIVE_URL, parameters)
        if response.get("utc_offset_seconds") != 0:
            raise WeatherError("Expected UTC data from the API.")
        hourly = response.get("hourly", {})
        timestamps = hourly.get("time", [])
        expected_count = ((finish - begin).days + 1) * 24
        if len(timestamps) != expected_count:
            raise WeatherError(f"Incomplete {model} response for {begin}: expected {expected_count} hours.")
        for variable, unit in units.items():
            actual_unit = response.get("hourly_units", {}).get(variable)
            if actual_unit != unit:
                raise WeatherError(f"Unexpected unit for {variable}: {actual_unit!r}; expected {unit!r}.")
            if len(hourly.get(variable, [])) != expected_count:
                raise WeatherError(f"Incomplete hourly array: {variable} ({begin}).")
        first_timestamp = int(datetime.combine(begin, datetime.min.time(), UTC).timestamp())
        for index, stamp in enumerate(timestamps):
            expected_stamp = first_timestamp + index * 3600
            if stamp != expected_stamp:
                raise WeatherError(f"Missing, duplicated, or misaligned UTC hour in {model}: {stamp}.")
            values = {}
            for variable in units:
                value = hourly[variable][index]
                values[variable] = (
                    float(value)
                    if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
                    else None
                )
            rows[expected_stamp] = values
        grids.append({key: response.get(key) for key in ("latitude", "longitude", "elevation")})
    return rows, grids


def sample_hour(
    rows: dict, end_utc: datetime, variables: tuple[str, ...], required: bool = True
) -> dict[str, float | None]:
    stamp = end_utc.timestamp()
    lower = math.floor(stamp / 3600) * 3600
    fraction = (stamp - lower) / 3600
    upper = lower + 3600 if fraction else lower
    result = {}
    for variable in variables:
        left = rows.get(lower, {}).get(variable)
        right = rows.get(upper, {}).get(variable)
        if left is None or right is None:
            if required:
                raise WeatherError(
                    f"Missing {variable} around {end_utc.isoformat()}. "
                    "No EPW was published; missing core data are never replaced with zeros."
                )
            result[variable] = None
        else:
            # For instantaneous fields this is linear interpolation. For previous-
            # hour means/sums it is overlap-weighted integration over the target
            # hour, assuming a uniform distribution within each source hour.
            result[variable] = left * (1 - fraction) + right * fraction
    if fraction and "wind_direction_10m" in variables:
        first, second = rows[lower], rows[upper]
        x = y = 0.0
        for weight, record in ((1 - fraction, first), (fraction, second)):
            angle = math.radians(record["wind_direction_10m"])
            speed = record["wind_speed_10m"]
            x += weight * speed * math.sin(angle)
            y += weight * speed * math.cos(angle)
        result["wind_speed_10m"] = math.hypot(x, y)
        result["wind_direction_10m"] = math.degrees(math.atan2(x, y)) % 360 if math.hypot(x, y) > 1e-9 else 0.0
    return result


def checked_values(values: dict, end_utc: datetime) -> dict:
    ranges = {
        "temperature_2m": (-90, 70),
        "dew_point_2m": (-100, 70),
        "relative_humidity_2m": (0, 100),
        "surface_pressure": (100, 1200),
        "wind_speed_10m": (0, 150),
        "wind_direction_10m": (0, 360),
        "cloud_cover": (0, 100),
        "rain": (0, 998),
        **{variable: (0, 2000) for variable in RADIATION},
    }
    for variable, (minimum, maximum) in ranges.items():
        value = values[variable]
        if value is None or not math.isfinite(value) or not minimum <= value <= maximum:
            raise WeatherError(f"Invalid {variable}={value!r} at {end_utc.isoformat()}.")
    return values


def horizontal_infrared(temperature: float, dewpoint: float, cloud_tenths: float) -> float:
    """Clark-Allen/Walton sky estimate; total cover is an opaque-cover proxy.

    This is an estimate, NOT API longwave radiation. Emissivity is bounded to
    [0, 1]. Output W/m2 equals Wh/m2 for the one-hour EPW record.
    """
    emissivity = 0.787 + 0.764 * math.log((dewpoint + 273.15) / 273.0)
    emissivity *= 1 + 0.0224 * cloud_tenths - 0.0035 * cloud_tenths**2 + 0.00028 * cloud_tenths**3
    return min(1.0, max(0.0, emissivity)) * 5.6697e-8 * (temperature + 273.15) ** 4


def epw_row(local_end: datetime, values: dict, snow_metres: float | None, additional: dict | None = None) -> list:
    start = local_end - HOUR
    temperature = values["temperature_2m"]
    dewpoint = values["dew_point_2m"]
    cloud = values["cloud_cover"] / 10
    infrared = horizontal_infrared(temperature, dewpoint, cloud)
    # The 22 flag pairs describe meteorology, radiation, illuminance, wind,
    # clouds, visibility, ceiling, water, aerosol, snow, and days since snow.
    # E9 = modeled/estimated meteorology with unknown uncertainty. ?9 denotes
    # missing data or a radiation source outside the legacy TMY categories.
    flags = "E9" * 4 + "?9" * 8 + "E9" * 4 + "?9" * 4
    flags += ("E9" if snow_metres is not None else "?9") + "?9"
    snow_cm = "999" if snow_metres is None else f"{snow_metres * 100:.1f}"
    row = [
        start.year,
        start.month,
        start.day,
        start.hour + 1,
        60,
        flags,
        f"{temperature:.2f}",
        f"{dewpoint:.2f}",
        f"{values['relative_humidity_2m']:.1f}",
        f"{values['surface_pressure'] * 100:.0f}",
        9999,
        9999,
        f"{infrared:.2f}",
        *[f"{values[variable]:.2f}" for variable in RADIATION],
        999999,
        999999,
        999999,
        9999,
        f"{values['wind_direction_10m']:.1f}",
        f"{values['wind_speed_10m']:.2f}",
        round(cloud),
        round(cloud),
        9999,
        99999,
        9,
        "999999999",
        999,
        ".999",
        snow_cm,
        99,
        999,
        f"{values['rain']:.2f}",
        1,
    ]
    if len(row) != 35:
        raise WeatherError("Internal error: EPW record does not have 35 columns.")
    for index, value in (additional or {}).items():
        if value is not None:
            row[index] = value
    if additional:
        flags = list(row[5])
        for index, pair in [(16, 8), (17, 9), (18, 10), (19, 11)]:
            if index in additional and float(additional[index]) < (9999 if index == 19 else 999900):
                flags[2 * pair : 2 * pair + 2] = list("E9")
        row[5] = "".join(flags)
    if additional and additional.get(28) is not None:
        row[5] = row[5][:36] + "E9" + row[5][38:]
    if additional and additional.get(31) is not None:
        row[5] = row[5][:42] + "E9" + row[5][44:]
    return row


def header_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[\r\n,]+", "; ", value).strip()


def epw_headers(location: Location, year: int, offset: timedelta, elevation: float) -> list[list]:
    return [
        [
            "LOCATION",
            header_text(location.name),
            header_text(location.admin1),
            header_text(location.country),
            "Open-Meteo ERA5",
            "000000",
            f"{location.latitude:.5f}",
            f"{location.longitude:.5f}",
            f"{offset.total_seconds() / 3600:.6f}",
            f"{elevation:.1f}",
        ],
        ["DESIGN CONDITIONS", 0],
        ["TYPICAL/EXTREME PERIODS", 0],
        ["GROUND TEMPERATURES", 0],
        ["HOLIDAYS/DAYLIGHT SAVINGS", "Yes" if calendar.isleap(year) else "No", 0, 0, 0],
        [
            "COMMENTS 1",
            f"Actual year {year}; weather by https://open-meteo.com/; "
            "CC BY 4.0 https://creativecommons.org/licenses/by/4.0/; "
            "ERA5/ERA5-Land: Copernicus C3S/ECMWF; location: GeoNames; "
            "modified into EPW; modeled weather not station measurements.",
        ],
        [
            "COMMENTS 2",
            "Fixed standard time; hour-ending records; "
            "infrared estimated by Clark-Allen/Walton using total cloud as opaque proxy; "
            "opaque cover estimated as total cover; optional solar/Perez daylight/ERA5 water/snow history/NASA albedo/station supplements; "
            "unavailable fields use missing codes; "
            "see companion metadata JSON.",
        ],
        ["DATA PERIODS", 1, 1, f"Actual year {year}", date(year, 1, 1).strftime("%A"), f"1/1/{year}", f"12/31/{year}"],
    ]


def validate_epw(path: Path, year: int) -> int:
    """Check file structure and the entire ordered calendar independently."""
    expected = (366 if calendar.isleap(year) else 365) * 24
    beginning = datetime(year, 1, 1)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        header_names = [
            "LOCATION",
            "DESIGN CONDITIONS",
            "TYPICAL/EXTREME PERIODS",
            "GROUND TEMPERATURES",
            "HOLIDAYS/DAYLIGHT SAVINGS",
            "COMMENTS 1",
            "COMMENTS 2",
            "DATA PERIODS",
        ]
        for name in header_names:
            row = next(reader, [])
            if not row or row[0] != name:
                raise WeatherError(f"Invalid EPW header: expected {name}.")
            if name == "DATA PERIODS" and row[-2:] != [f"1/1/{year}", f"12/31/{year}"]:
                raise WeatherError("Actual-weather EPW DATA PERIODS dates must include the requested year.")
        count = 0
        for index, row in enumerate(reader):
            start = beginning + index * HOUR
            target = [start.year, start.month, start.day, start.hour + 1, 60]
            if len(row) != 35 or [int(item) for item in row[:5]] != target:
                raise WeatherError(f"Invalid EPW record at data line {index + 1}.")
            if any(not math.isfinite(float(item)) for item in row[6:]):
                raise WeatherError(f"Non-finite EPW value at data line {index + 1}.")
            count += 1
    if count != expected:
        raise WeatherError(f"Expected {expected} EPW rows; found {count}.")
    return count


def load_dataset(
    client: APIClient,
    location: Location,
    year: int,
    offset: timedelta,
    include_snow: bool = True,
    *,
    include_additional_fields: bool = True,
    station: str | None = "auto",
    max_station_distance_km: float = 30,
    station_tolerance_minutes: float = 15,
    require_fields: tuple[str, ...] = (),
    use_free_fallbacks: bool = True,
    allow_metar_fallback: bool = True,
) -> WeatherDataset:
    """Fetch, check, and assemble the complete year once for all three writers."""
    today = datetime.now(UTC).date()
    if not 1940 <= year < today.year:
        raise WeatherError(f"Choose a completed calendar year from 1940 to {today.year - 1}.")
    begin, finish = source_date_range(year, offset)
    if begin < date(1940, 1, 1):
        raise WeatherError("This full local year needs UTC data before ERA5 starts in 1940. Choose a later year.")
    if finish > today - timedelta(days=5):
        raise WeatherError("The end of this year is not yet available in ERA5 (about a five-day delay).")
    core, grids = download_hourly(client, location, "era5", CORE_UNITS, begin, finish)
    snow = {}
    warnings = []
    if include_snow and year >= 1950:
        try:
            snow, _ = download_hourly(
                client,
                location,
                "era5_land",
                {"snow_depth": "m"},
                max(begin, date(1950, 1, 1)),
                finish,
            )
        except (WeatherError, APIError) as exc:
            warnings.append(f"Snow depth unavailable; missing code 999 is used. {exc}")
    else:
        warnings.append("Snow depth omitted or predates ERA5-Land; missing code 999 is used.")
    elevation = location.elevation if location.elevation is not None else grids[0].get("elevation")
    if elevation is None or not math.isfinite(float(elevation)):
        raise WeatherError("No valid site elevation was returned.")
    first_end, final_end = year_boundaries(year, offset)
    water = {}
    observations = {}
    station_metadata = {}
    snowfall = {}
    snowfall_grids = []
    albedo = {}
    albedo_metadata = {}
    history = SnowHistory()
    if include_additional_fields:
        try:
            water, _ = download_hourly(client, location, "era5", WATER_UNITS, begin, finish)
        except (WeatherError, APIError) as exc:
            warnings.append(f"ERA5 precipitable water unavailable; missing code 999 is used. {exc}")
        observations, station_metadata, station_warnings = load_observations(
            client,
            location,
            first_end.astimezone(UTC),
            final_end.astimezone(UTC),
            offset.total_seconds(),
            station=station,
            max_distance_km=max_station_distance_km,
            tolerance_minutes=station_tolerance_minutes,
            use_free_fallbacks=use_free_fallbacks,
            allow_metar_fallback=allow_metar_fallback,
        )
        warnings.extend(station_warnings)
        if use_free_fallbacks:
            history_begin = max(date(1940, 1, 1), (first_end.astimezone(UTC) - timedelta(days=89)).date())
            try:
                snowfall, snowfall_grids = download_hourly(
                    client, location, "era5", {"snowfall": "cm"}, history_begin, finish
                )
            except (WeatherError, APIError) as exc:
                warnings.append(f"Snowfall history unavailable; days since last snowfall stays missing. {exc}")
            albedo, albedo_metadata, albedo_warnings = load_power_albedo(client, location, first_end, final_end)
            warnings.extend(albedo_warnings)
            history_end = max(
                first_end - timedelta(days=89), datetime(1940, 1, 1, 1, tzinfo=UTC).astimezone(first_end.tzinfo)
            )
            while history_end < first_end:
                amount = sample_hour(snowfall, history_end.astimezone(UTC), ("snowfall",), required=False)["snowfall"]
                history.advance(history_end, amount)
                history_end += HOUR
    missing_snow = 0
    low_sun = 0
    zenith_rejected = 0
    unbounded_zenith = []
    lineage = {"visibility_km": [], "ceiling_height_m": []}
    rows = []
    local_end = first_end
    while local_end <= final_end:
        end_utc = local_end.astimezone(UTC)
        values = checked_values(sample_hour(core, end_utc, tuple(CORE_UNITS)), end_utc)
        snow_value = sample_hour(snow, end_utc, ("snow_depth",), required=False)["snow_depth"]
        if snow_value is not None and not 0 <= snow_value * 100 < 999:
            snow_value = None
        missing_snow += snow_value is None
        additional = {}
        if include_additional_fields:
            if use_free_fallbacks:
                amount = sample_hour(snowfall, end_utc, ("snowfall",), required=False)["snowfall"]
                days_since_snow = history.advance(local_end, amount)
                if days_since_snow is not None:
                    additional[31] = str(days_since_snow)
                surface_albedo = interval_albedo(albedo, end_utc)
                if surface_albedo is not None:
                    additional[32] = f"{surface_albedo:.4f}"
            solar = solar_interval(end_utc, location.latitude, location.longitude)
            light = perez_daylight(
                solar,
                values["shortwave_radiation"],
                values["direct_normal_irradiance"],
                values["diffuse_radiation"],
                values["dew_point_2m"],
            )
            additional.update(
                {
                    10: f"{solar.horizontal_wh_m2:.2f}",
                    11: f"{solar.direct_normal_wh_m2:.2f}",
                    16: f"{light.global_lux:.0f}",
                    17: f"{light.direct_normal_lux:.0f}",
                    18: f"{light.diffuse_lux:.0f}",
                    19: f"{light.zenith_cd_m2:.1f}" if light.zenith_cd_m2 < 9998.95 else "9999",
                }
            )
            zenith_rejected += light.zenith_cd_m2 >= 9998.95
            if light.zenith_cd_m2 >= 9998.95:
                unbounded_zenith.append({"row": len(rows), "zenith_luminance_cd_m2": light.zenith_cd_m2})
            low_sun += light.low_sun_extrapolation
            pw = sample_hour(water, end_utc, tuple(WATER_UNITS), required=False)["total_column_integrated_water_vapour"]
            if pw is not None and 0 <= pw < 999:
                additional[28] = f"{pw:.2f}"
            obs = observations.get(int(end_utc.timestamp()), {})
            for field, index in [("visibility_km", 24), ("ceiling_height_m", 25)]:
                record = obs.get(field)
                lineage[field].append(record)
                if record:
                    additional[index] = f"{record['value']:.3f}" if index == 24 else f"{record['value']:.0f}"
        rows.append(tuple(str(value) for value in epw_row(local_end, values, snow_value, additional)))
        local_end += HOUR
    count = len(rows)
    if count != (366 if calendar.isleap(year) else 365) * 24:
        raise WeatherError("The assembled calendar year is incomplete.")
    if missing_snow:
        warnings.append(f"Snow depth is missing for {missing_snow} of {count} hours.")
    coverage = field_coverage(rows)
    for field, records in lineage.items():
        qualifiers = {}
        station_counts = {}
        provider_counts = {}
        distances = []
        for record in records:
            if record:
                station_id = record["station_id"]
                station_counts[station_id] = station_counts.get(station_id, 0) + 1
                provider = record.get("provider", "NOAA GHCNh")
                provider_counts[provider] = provider_counts.get(provider, 0) + 1
                if record["qualifier"]:
                    q = record["qualifier"]
                    qualifiers[q] = qualifiers.get(q, 0) + 1
                distances.append(record["distance_km"])
        coverage[field]["qualifier_hours"] = qualifiers
        coverage[field]["station_hours"] = station_counts
        coverage[field]["provider_hours"] = provider_counts
        coverage[field]["actual_station_distance_range_km"] = [min(distances), max(distances)] if distances else None
    missing_required = [field for field in require_fields if coverage[field]["missing_hours"]]
    if missing_required:
        detail = "; ".join(
            f"Required field {field} is missing for {coverage[field]['missing_hours']} hours"
            for field in missing_required
        )
        raise WeatherError(detail + "; no output was written.")
    if include_additional_fields:
        for field in (
            "visibility_km",
            "ceiling_height_m",
            "precipitable_water_mm",
            "days_since_last_snowfall",
            "albedo",
        ):
            if coverage[field]["missing_hours"]:
                warnings.append(f"{field} is missing for {coverage[field]['missing_hours']} hours; see field_coverage.")
        if zenith_rejected:
            warnings.append(
                f"{zenith_rejected} modeled zenith-luminance values exceed EPW's representable non-missing range; missing code 9999 is used without clipping."
            )
    metadata = {
        "city": asdict(location),
        "year": year,
        "weather_type": "actual calendar year reanalysis",
        "tmy": False,
        "model": "ERA5",
        "snow_model": "ERA5-Land" if snow else None,
        "rows": count,
        "columns": 35,
        "utc_offset_hours": offset.total_seconds() / 3600,
        "timezone_convention": "Fixed standard offset; no daylight saving",
        "first_hour_ending_local": first_end.isoformat(),
        "last_hour_ending_local": final_end.isoformat(),
        "source_utc_dates": [begin.isoformat(), finish.isoformat()],
        "source_grids": [dict(items) for items in sorted({tuple(sorted(grid.items())) for grid in grids})],
        "site_elevation_metres": elevation,
        "missing_snow_hours": missing_snow,
        "include_additional_fields": include_additional_fields,
        "use_free_fallbacks": use_free_fallbacks,
        "allow_metar_fallback": allow_metar_fallback,
        "is_complete": all(info["missing_hours"] == 0 for info in coverage.values()),
        "missing_fields": {name: info["missing_hours"] for name, info in coverage.items() if info["missing_hours"]},
        "albedo_source": albedo_metadata,
        "snowfall_history": {
            "provider": "ERA5 snowfall via Open-Meteo",
            "source_grids": snowfall_grids,
            "lookback_days": 89,
            "derivation": "Elapsed whole 24-hour days since the end of a positive reported snowfall interval; positive means >0 in source cm, with no invented threshold.",
            "code_88": "88 or more days, established only by known event history or 88 complete consecutive zero-snow days.",
            "gap_policy": "Unknown source intervals invalidate history until a later known event or 88 complete known days; no snow-depth-to-snowfall inference.",
            "reference": "https://www.nrel.gov/docs/fy08osti/43388.pdf",
        }
        if include_additional_fields and use_free_fallbacks
        else None,
        "missing_data_policy": "Try supported source-backed supplements; preserve remaining EPW missing codes. No interpolation/carry-forward of station observations or albedo; use require_complete=True to reject any remaining missing field.",
        "field_coverage": coverage,
        "zenith_luminance_outside_epw_range": unbounded_zenith,
        "station_supplement": station_metadata,
        "observation_lineage_runs": {field: lineage_runs(records) for field, records in lineage.items()}
        if include_additional_fields
        else {},
        "daylight_model": {
            "name": "Perez et al. 1990, equations 1–3,6–8,10, original Table 4",
            "reference": "https://doi.org/10.1016/0038-092X(90)90055-H",
            "inputs": "ERA5 GHI, DNI, DHI, dew point; daylight-average geometric zenith; Kasten–Young relative air mass",
            "partial_daylight": "Whole-hour radiation converted to daylight-only means for model parameters; outputs remain whole-hour means.",
            "water_proxy": "exp(0.07*dewpoint_C - 0.075) cm is internal to the published daylight fit; EPW column water is independently obtained from ERA5.",
            "low_sun_extrapolation_hours": low_sun,
            "zenith_outside_epw_range_hours": zenith_rejected,
            "accuracy": "Empirical model, no local photometer validation. Low-sun and zenith-angle extrapolations require caution.",
        }
        if include_additional_fields
        else None,
        "solar_geometry": {
            "method": "NOAA/Meeus geometric zenith; Spencer Earth-distance correction; horizon roots and Simpson integration over previous hour",
            "solar_constant_w_m2": 1361.0,
            "refraction": False,
            "reference": "https://gml.noaa.gov/grad/solcalc/calcdetails.html",
        }
        if include_additional_fields
        else None,
        "modifications": [
            "UTC timestamps aligned to hour-ending local standard time.",
            "Fractional UTC offsets: instantaneous fields and wind vectors interpolated; radiation/rain integrated by interval overlap assuming uniform values within each source hour.",
            "Pressure hPa to Pa; cloud percent to tenths; snow metres to centimetres.",
            "Hourly mean radiation W/m2 converted to Wh/m2; numerical values unchanged for one-hour intervals.",
            "Opaque cover estimated as total cloud cover; infrared estimated by Clark-Allen/Walton with emissivity limited to [0,1].",
            "Additional fields: astronomical extraterrestrial energy; Perez modeled photometry; ERA5 column water (kg/m2 equals mm); quality-filtered nearby NOAA visibility and ceiling where available. See field_coverage and station lineage.",
            "Snow history is derived from actual-year ERA5 snowfall with a prior-year lookback; NASA POWER supplies valid hourly albedo; NOAA ISD and optionally published METAR fill station gaps. Provider QC differences and remaining gaps are explicit.",
            "Unsupported weather codes and aerosol, undefined nighttime albedo, and other unavailable fields retain EPW missing codes; no generic numeric fill values are invented.",
            "No station observations, ground temperatures, or design-day statistics are invented.",
        ],
        "data_credit": "Weather by Open-Meteo; ERA5/ERA5-Land: Copernicus C3S/ECMWF; geocoding: GeoNames; station supplements: NOAA NCEI GHCNh/ISD and originating networks; optional published METAR: Iowa Environmental Mesonet; albedo: NASA POWER/CERES SYN1deg.",
        "station_text_sources": getattr(client, "text_sources", []),
        "data_licence": "https://creativecommons.org/licenses/by/4.0/",
        "service_terms": "https://open-meteo.com/en/terms",
        "api_use": "Public non-commercial endpoints only; no key or billing integration.",
        "request_urls": list(client.urls),
        "generated_utc": datetime.now(UTC).isoformat(),
        "warnings": warnings,
    }
    for warning in warnings:
        logger.warning(warning)
    headers = tuple(tuple(str(value) for value in row) for row in epw_headers(location, year, offset, float(elevation)))
    return WeatherDataset(location, year, headers, tuple(rows), metadata)


def create_epw(
    client: APIClient,
    location: Location,
    year: int,
    offset: timedelta,
    output: Path,
    include_snow: bool = True,
    overwrite: bool = False,
) -> dict:
    """Internal compatibility adapter for the original conversion tests."""
    from .writers import check_destination, write_weather
    from .models import OutputFormat

    check_destination(output, overwrite)
    dataset = load_dataset(client, location, year, offset, include_snow)
    return write_weather(dataset, OutputFormat.EPW, output, overwrite)[1]
