"""Free NOAA GHCNh visibility/ceiling supplementation with explicit site/QC lineage.

No gap interpolation, no humidity-to-visibility heuristic, and no inference of
unlimited ceiling merely from missing cloud layers. Nearby sites are proxies
for the requested coordinates, never relabelled as on-site measurements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import io
import math
import re
from typing import Any

from .client import APIClient
from .exceptions import APIError, DataError, ValidationError
from .models import Location

STATION_LIST = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt"
YEAR_URL = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{year}/psv/GHCNh_{station}_{year}.psv"
FIELDS = {"visibility": "visibility_km", "ceiling_height": "ceiling_height_m"}
ISD_SOURCES = {"313", "314", "315", "322", "335", "343", "344", "346"}
AVIATION_SOURCES = {"220", "221", "222", "223", "347", "348"}


@dataclass(frozen=True)
class ObservationStation:
    """A GHCNh station reference position (historical positions may differ)."""

    station_id: str
    name: str
    latitude: float
    longitude: float
    elevation: float
    country_code: str
    distance_km: float


def distance_km(lat1, lon1, lat2, lon2):
    a, b, c, d = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 12742.0176 * math.asin(min(1, math.sqrt(h)))


def station_catalog(text: str, location: Location) -> list[ObservationStation]:
    stations = []
    for line in text.splitlines():
        if len(line) < 87:
            continue
        try:
            station = ObservationStation(
                line[:11].strip(),
                line[41:71].strip(),
                float(line[12:20]),
                float(line[21:30]),
                float(line[31:37]),
                line[86:88].strip(),
                0,
            )
            if not (-90 <= station.latitude <= 90 and -180 <= station.longitude <= 180):
                continue
            station = ObservationStation(
                **{
                    **asdict(station),
                    "distance_km": distance_km(
                        location.latitude, location.longitude, station.latitude, station.longitude
                    ),
                }
            )
            stations.append(station)
        except ValueError:
            continue
    if not stations:
        raise DataError("NOAA's station list could not be parsed.")
    return sorted(stations, key=lambda s: (s.distance_km, s.station_id))


def search_stations(
    location: Location, *, max_distance_km: float = 30, limit: int = 10, cache_dir=None, refresh: bool = False
) -> list[ObservationStation]:
    """Find nearby station references; a result does not guarantee field/year coverage.

    Pass a Location from search_cities(). No network request occurs on import.
    """
    if not isinstance(location, Location):
        raise ValidationError("search_stations() requires a Location from search_cities().")
    if (
        isinstance(max_distance_km, bool)
        or not isinstance(max_distance_km, (int, float))
        or not math.isfinite(max_distance_km)
        or max_distance_km <= 0
    ):
        raise ValidationError("max_distance_km must be a positive finite number.")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValidationError("limit must be a positive integer.")
    client = APIClient(cache_dir, refresh)
    return [s for s in station_catalog(client.get_text(STATION_LIST), location) if s.distance_km <= max_distance_km][
        :limit
    ]


def qc_accepted(source: str, quality: str) -> bool:
    """Source-aware strict acceptance; blank QC is not silently assumed good."""
    return (source in ISD_SOURCES and quality in {"1", "5"}) or (source in AVIATION_SOURCES and quality == "1")


def parse_observations(
    text: str,
    station: ObservationStation,
    offset_seconds: float,
    tolerance_seconds: float = 900,
    *,
    location: Location | None = None,
    max_distance_km: float = 30,
) -> dict[int, dict[str, dict[str, Any]]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    required = {"STATION", "DATE", *FIELDS}
    for raw in FIELDS:
        required.update((raw + "_Quality_Code", raw + "_Source_Code"))
    if not required.issubset(reader.fieldnames or ()):
        raise DataError("GHCNh station file lacks the required visibility/ceiling columns.")
    observations = {}
    for row in reader:
        if row.get("STATION") != station.station_id:
            raise DataError("GHCNh station identity does not match the requested station.")
        try:
            stamp = datetime.fromisoformat(row["DATE"]).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
        endpoint = math.floor((stamp + offset_seconds + 1800) / 3600) * 3600 - offset_seconds
        delta = stamp - endpoint
        if abs(delta) > tolerance_seconds:
            continue
        actual_position = {
            "latitude": station.latitude,
            "longitude": station.longitude,
            "distance_km": station.distance_km,
            "position_source": "station_catalog_reference",
        }
        if location is not None:
            try:
                lat, lon = float(row.get("LATITUDE", "")), float(row.get("LONGITUDE", ""))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                distance = distance_km(location.latitude, location.longitude, lat, lon)
                if distance > max_distance_km:
                    continue
                actual_position = {
                    "latitude": lat,
                    "longitude": lon,
                    "distance_km": distance,
                    "position_source": "reported_observation_position",
                }
            except (ValueError, TypeError):
                pass
        for raw, field in FIELDS.items():
            quality = (row.get(raw + "_Quality_Code") or "").strip()
            source = (row.get(raw + "_Source_Code") or "").strip()
            if not qc_accepted(source, quality):
                continue
            try:
                value = float(row[raw])
            except (ValueError, TypeError):
                continue
            if not math.isfinite(value) or value < 0:
                continue
            qualifier = None
            if raw == "visibility":
                if value >= 9999:
                    continue
                # Aviation code 9999 m means >=10 km, not an exact 9.999 km.
                if abs(value - 9.999) < 1e-6:
                    value = 10.0
                    qualifier = "lower_bound_10_km"
            else:
                if value == 22000:
                    value = 77777.0
                    qualifier = "unlimited_ceiling"
                elif value > 22000:
                    continue
            measurement = (row.get(raw + "_Measurement_Code") or "").strip()
            report = (row.get(raw + "_Report_Type") or "").strip()
            # Preserve source-specific cirroform ceiling when explicitly given.
            if raw == "ceiling_height" and source in ISD_SOURCES and measurement.split(";")[0] == "D":
                value = 88888.0
                qualifier = "cirroform_ceiling"
            candidate = {
                "value": value,
                "station_id": station.station_id,
                "source_code": source,
                "quality_code": quality,
                "measurement_code": measurement,
                "report_type": report,
                "time_delta_seconds": delta,
                "qualifier": qualifier,
                **actual_position,
            }
            rank = (abs(delta), 0 if report in {"FM12", "FM-12"} else 1)
            target = observations.setdefault(int(endpoint), {})
            previous = target.get(field)
            previous_rank = (
                (abs(previous["time_delta_seconds"]), 0 if previous["report_type"] in {"FM12", "FM-12"} else 1)
                if previous
                else (math.inf, math.inf)
            )
            if rank < previous_rank:
                target[field] = candidate
    return observations


def load_observations(
    client: APIClient,
    location: Location,
    first_utc: datetime,
    final_utc: datetime,
    offset_seconds: float,
    *,
    station: str | None = "auto",
    max_distance_km: float = 30,
    tolerance_minutes: float = 15,
    use_free_fallbacks: bool = True,
    allow_metar_fallback: bool = True,
) -> tuple[dict, dict, list[str]]:
    metadata = {
        "dataset": "NOAA NCEI GHCNh",
        "stations": [],
        "quality_rule": "Source-aware strict QC; ISD sources 1/5; aviation sources 1; other sources rejected.",
        "matching": "Nearest valid report per field within tolerance, then nearest station; no temporal interpolation or carry-forward.",
        "tolerance_minutes": tolerance_minutes,
        "max_station_distance_km": max_distance_km,
        "source_url": "https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly",
    }
    if station is None:
        return {}, metadata, ["Station supplementation disabled; visibility/ceiling use missing codes."]
    warnings = []
    try:
        catalog = station_catalog(client.get_text(STATION_LIST), location)
    except (APIError, DataError) as exc:
        catalog = []
        warnings.append(f"GHCNh station supplement unavailable: {exc}")
    nearby = [s for s in catalog if s.distance_km <= max_distance_km]
    if station != "auto":
        nearby = [s for s in nearby if s.station_id == station]
        if not nearby:
            return (
                {},
                metadata,
                [f"Station {station} is absent or exceeds {max_distance_km:g} km; no distant station is substituted."],
            )
    else:
        # Aviation identities and explicitly named airports are much more likely
        # to report these fields than the numerous temperature/rain-only sites.
        airports = [
            s
            for s in nearby
            if re.search(r"I0000[A-Z0-9]{4}$", s.station_id)
            or any(word in s.name.upper() for word in ("AIRPORT", "INTL", "INTERNATIONAL", "AERODROME"))
        ]
        # Failed/obsolete airport references must not exclude usable SYNOP or
        # non-airport sites such as Roches Point. Keep requests bounded.
        airport_ids = {s.station_id for s in airports}
        nearby = (airports + [s for s in nearby if s.station_id not in airport_ids])[:10]
        metadata["candidate_policy"] = (
            "Up to 10 nearby references, aviation first, then other nearby sites; failed airport references do not exclude alternatives."
        )
    combined = {}
    years = range(first_utc.year, final_utc.year + 1)
    for site in nearby:
        site_data = {}
        for year in years:
            url = YEAR_URL.format(year=year, station=site.station_id)
            try:
                data = parse_observations(
                    client.get_text(url, expected_start="STATION|"),
                    site,
                    offset_seconds,
                    tolerance_minutes * 60,
                    location=location,
                    max_distance_km=max_distance_km,
                )
            except (APIError, DataError) as exc:
                warnings.append(f"Station {site.station_id} {year} unavailable: {exc}")
                continue
            for stamp, fields in data.items():
                if first_utc.timestamp() <= stamp <= final_utc.timestamp():
                    site_data.setdefault(stamp, {}).update(fields)
        if not site_data:
            continue
        metadata["stations"].append(asdict(site))
        for stamp, fields in site_data.items():
            for field, record in fields.items():
                # Prefer the nearest actual reported position among tested
                # stations; use report time to break equal-distance ties.
                target = combined.setdefault(stamp, {})
                previous = target.get(field)
                if previous is None or (record["distance_km"], abs(record["time_delta_seconds"])) < (
                    previous["distance_km"],
                    abs(previous["time_delta_seconds"]),
                ):
                    target[field] = record
        count = int((final_utc - first_utc).total_seconds() / 3600) + 1
        if all(sum(field in r for r in combined.values()) == count for field in FIELDS.values()):
            break
    if not metadata["stations"]:
        warnings.append(
            "No acceptable nearby GHCNh visibility/ceiling observations were available; other enabled archives may still supply them."
        )
    if use_free_fallbacks:
        from .station_fallbacks import fill_station_gaps

        combined, fallback_meta, fallback_warnings = fill_station_gaps(
            client,
            location,
            first_utc,
            final_utc,
            offset_seconds,
            combined,
            max_distance_km=max_distance_km,
            tolerance_seconds=tolerance_minutes * 60,
            explicit_station=next((s for s in nearby if s.station_id == station), None) if station != "auto" else None,
            allow_metar=allow_metar_fallback,
        )
        metadata["fallbacks"] = fallback_meta
        warnings.extend(fallback_warnings)
    return combined, metadata, warnings


def lineage_runs(records: list[dict | None]) -> list[dict]:
    """Lossless run-length metadata for station/QC/timing attached to each EPW row."""
    runs = []
    for index, record in enumerate(records):
        lineage = {k: v for k, v in record.items() if k != "value"} if record else None
        if runs and runs[-1]["source"] == lineage:
            runs[-1]["count"] += 1
        else:
            runs.append({"start_row": index, "count": 1, "source": lineage})
    return runs
