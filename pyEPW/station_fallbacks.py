"""Gap-only fallbacks using original NOAA ISD and published IEM METAR reports.

No humidity/cloud-cover ceiling formula, no temporal interpolation and no
unlimited-ceiling assumption from CAVOK, NSC, CLR or missing cloud layers.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import math
import re
from urllib.parse import urlencode

from .exceptions import APIError, DataError
from .observations import distance_km

UTC = timezone.utc
HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
ISD_URL = "https://www.ncei.noaa.gov/pub/data/noaa/{year}/{station}-{year}.gz"
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
FIELD_NAMES = ("visibility_km", "ceiling_height_m")


def history_catalog(text, location, first, final, max_distance_km):
    reader = csv.DictReader(io.StringIO(text))
    if not {"USAF", "WBAN", "STATION NAME", "LAT", "LON", "BEGIN", "END", "ICAO"} <= set(reader.fieldnames or ()):
        raise DataError("NOAA ISD station history has an unexpected schema.")
    stations = []
    for row in reader:
        try:
            lat, lon = float(row["LAT"]), float(row["LON"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            distance = distance_km(location.latitude, location.longitude, lat, lon)
            if (
                distance > max_distance_km
                or row["BEGIN"] > final.strftime("%Y%m%d")
                or row["END"] < first.strftime("%Y%m%d")
            ):
                continue
            station = row["USAF"] + "-" + row["WBAN"]
            if not re.fullmatch(r"\d{6}-\d{5}", station):
                continue
            stations.append(
                {
                    "station_id": station,
                    "name": row["STATION NAME"],
                    "latitude": lat,
                    "longitude": lon,
                    "distance_km": distance,
                    "icao": row["ICAO"].strip(),
                    "begin": row["BEGIN"],
                    "end": row["END"],
                }
            )
        except (ValueError, TypeError):
            continue
    return sorted(stations, key=lambda s: (s["distance_km"], s["station_id"]))


def target_endpoint(stamp, offset_seconds, tolerance_seconds):
    end = math.floor((stamp + offset_seconds + 1800) / 3600) * 3600 - offset_seconds
    delta = stamp - end
    return (int(end), delta) if abs(delta) <= tolerance_seconds else (None, None)


def record(value, site, delta, **extra):
    return {
        "value": value,
        "station_id": site["station_id"],
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        "distance_km": site["distance_km"],
        "position_source": "station_history_reference",
        "time_delta_seconds": delta,
        "qualifier": None,
        "source_code": "",
        "quality_code": "",
        "measurement_code": "",
        "report_type": "",
        **extra,
    }


def put_nearest(result, endpoint, field, candidate):
    target = result.setdefault(endpoint, {})
    previous = target.get(field)

    def rank(r):
        return abs(r["time_delta_seconds"]), 0 if r["report_type"] in {"FM-12", "FM12"} else 1

    if previous is None or rank(candidate) < rank(previous):
        target[field] = candidate


def parse_isd(text, site, location, offset_seconds, tolerance_seconds=900, max_distance_km=30):
    result = {}
    for line in text.splitlines():
        if len(line) < 105:
            continue
        if line[4:15] != site["station_id"].replace("-", ""):
            raise DataError("NOAA ISD report identity does not match its station file.")
        try:
            stamp = datetime.strptime(line[15:27], "%Y%m%d%H%M").replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        endpoint, delta = target_endpoint(stamp, offset_seconds, tolerance_seconds)
        if endpoint is None:
            continue
        actual = dict(site)
        try:
            lat, lon = int(line[28:34]) / 1000, int(line[34:41]) / 1000
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                actual.update(
                    latitude=lat,
                    longitude=lon,
                    distance_km=distance_km(location.latitude, location.longitude, lat, lon),
                )
                if actual["distance_km"] > max_distance_km:
                    continue
        except ValueError:
            pass
        for field, lo, hi, qc in [("visibility_km", 78, 84, 84), ("ceiling_height_m", 70, 75, 75)]:
            if line[qc] not in {"1", "5"}:
                continue
            try:
                value = int(line[lo:hi])
            except ValueError:
                continue
            qualifier = None
            if field == "visibility_km":
                if not 0 <= value < 999999:
                    continue
                if value == 9999:
                    value, qualifier = 10.0, "lower_bound_10_km"
                else:
                    value /= 1000
            else:
                if not 0 <= value <= 22000:
                    continue
                if value == 22000:
                    value, qualifier = 77777, "unlimited_ceiling"
                if line[76] == "D":
                    value, qualifier = 88888, "cirroform_ceiling"
            candidate = record(
                value,
                actual,
                delta,
                provider="NOAA ISD",
                source_code="ISD",
                quality_code=line[qc],
                measurement_code=line[76] if field == "ceiling_height_m" else line[85],
                report_type=line[41:46].strip(),
                qualifier=qualifier,
                position_source="reported_observation_position" if actual != site else "station_history_reference",
            )
            put_nearest(result, endpoint, field, candidate)
    return result


def metar_values(raw):
    """Decode only observed cloud layers and visibility before forecast/remark groups."""
    current = re.split(r"\b(?:TEMPO|BECMG|NOSIG|RMK)\b", raw, maxsplit=1)[0]
    result = {}
    layers = re.findall(r"(?<!\S)(?:BKN|OVC|VV)(\d{3}|///)(?:CB|TCU)?(?=\s|=|$)", current)
    if layers and "///" not in layers:
        result["ceiling_height_m"] = (min(int(height) for height in layers) * 100 * 0.3048, None)
    # Visibility in metres (ICAO) or statute miles (US METAR). No use of the
    # rounded IEM vsby column when an exact original report is available.
    tail = re.sub(r"^.*?\b\d{6}Z\b", "", current, count=1)
    visibility = re.search(r"(?<!\S)(\d{4})(?:[NSEW]{1,2})?(?!\S)", tail)
    if visibility:
        value = int(visibility[1])
        result["visibility_km"] = (
            10.0 if value == 9999 else value / 1000,
            "lower_bound_10_km" if value == 9999 else None,
        )
    else:
        miles = re.search(r"(?<!\S)([PM]?)(?:(\d+)\s+)?(\d+/\d+|\d+(?:\.\d+)?)SM\b", tail)
        if miles:
            number = miles[3]
            if "/" in number:
                numerator, denominator = map(int, number.split("/"))
                if denominator == 0:
                    return result
                value = numerator / denominator
            else:
                value = float(number)
            value += int(miles[2] or 0)
            qualifier = (
                "reported_lower_bound" if miles[1] == "P" else "reported_upper_bound" if miles[1] == "M" else None
            )
            result["visibility_km"] = (value * 1.609344, qualifier)
    return result


def parse_iem(text, site, location, offset_seconds, tolerance_seconds=900, max_distance_km=30):
    reader = csv.DictReader(io.StringIO(text))
    if not {"station", "valid", "lon", "lat", "metar"} <= set(reader.fieldnames or ()):
        raise DataError("IEM METAR response has an unexpected schema.")
    result = {}
    for row in reader:
        raw = (row.get("metar") or "").strip()
        if row["station"] != site["icao"]:
            raise DataError("IEM station identity does not match the requested airport.")
        try:
            instant = datetime.fromisoformat(row["valid"]).replace(tzinfo=UTC)
            lat, lon = float(row["lat"]), float(row["lon"])
        except (ValueError, TypeError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        distance = distance_km(location.latitude, location.longitude, lat, lon)
        if distance > max_distance_km:
            continue
        if not re.match(
            r"^(?:(?:METAR|SPECI)\s+)?" + re.escape(site["icao"]) + r"\s+" + instant.strftime("%d%H%M") + r"Z\b", raw
        ):
            continue
        if re.search(r"\bNIL\b", raw):
            continue
        endpoint, delta = target_endpoint(instant.timestamp(), offset_seconds, tolerance_seconds)
        if endpoint is None:
            continue
        actual = {**site, "latitude": lat, "longitude": lon, "distance_km": distance}
        for field, (value, qualifier) in metar_values(raw).items():
            candidate = record(
                value,
                actual,
                delta,
                provider="Iowa Environmental Mesonet METAR",
                source_code="IEM_METAR",
                quality_code="not_supplied",
                qc_policy="Published METAR; archive has very little additional QC; syntax/station/position/time checked only.",
                report_type="METAR",
                qualifier=qualifier,
                position_source="reported_observation_position",
                raw_metar_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            )
            put_nearest(result, endpoint, field, candidate)
    return result


def fill_station_gaps(
    client,
    location,
    first,
    final,
    offset,
    combined,
    *,
    max_distance_km=30,
    tolerance_seconds=900,
    explicit_station=None,
    allow_metar=True,
):
    metadata = {
        "providers": [],
        "gap_only": True,
        "allow_published_metar": allow_metar,
        "policy": "NOAA QC 1/5 first; then published METAR if enabled, with minimal archive QC clearly distinguished. No temporal filling or CAVOK ceiling inference.",
    }
    warnings = []
    count = int((final - first).total_seconds() / 3600) + 1

    def complete():
        return all(sum(field in values for values in combined.values()) == count for field in FIELD_NAMES)

    if complete():
        return combined, metadata, warnings
    try:
        sites = history_catalog(client.get_text(HISTORY_URL), location, first, final, max_distance_km)
    except (APIError, DataError) as error:
        return combined, metadata, [f"NOAA historical-station fallback unavailable: {error}"]
    if explicit_station is not None:
        sites = [
            s
            for s in sites
            if distance_km(s["latitude"], s["longitude"], explicit_station.latitude, explicit_station.longitude) <= 1
        ]
    sites = sites[:3]

    def merge(records):
        additions = 0
        for stamp, fields in records.items():
            if first.timestamp() <= stamp <= final.timestamp():
                target = combined.setdefault(stamp, {})
                for field, value in fields.items():
                    if field not in target:
                        target[field] = value
                        additions += 1
        return additions

    for site in sites:
        additions = 0
        for year in range(first.year, final.year + 1):
            if site["end"] < f"{year}0101" or site["begin"] > f"{year}1231":
                continue
            try:
                records = parse_isd(
                    client.get_text(ISD_URL.format(year=year, station=site["station_id"])),
                    site,
                    location,
                    offset,
                    tolerance_seconds,
                    max_distance_km,
                )
                additions += merge(records)
            except (APIError, DataError) as error:
                warnings.append(f"ISD fallback {site['station_id']} {year} unavailable: {error}")
        if additions:
            metadata["providers"].append({"provider": "NOAA ISD", "station": site, "filled_values": additions})
        if complete():
            break
    if allow_metar and not complete():
        for site in [s for s in sites if re.fullmatch(r"[A-Z0-9]{4}", s["icao"])]:
            start_date = (first - timedelta(minutes=30)).date()
            end_date = (final + timedelta(days=1)).date()
            parameters = [
                ("station", site["icao"]),
                ("data", "all"),
                ("year1", start_date.year),
                ("month1", start_date.month),
                ("day1", start_date.day),
                ("year2", end_date.year),
                ("month2", end_date.month),
                ("day2", end_date.day),
                ("tz", "Etc/UTC"),
                ("format", "onlycomma"),
                ("latlon", "yes"),
                ("elev", "yes"),
                ("missing", "M"),
                ("trace", "T"),
                ("direct", "no"),
                ("report_type", "3"),
                ("report_type", "4"),
            ]
            try:
                records = parse_iem(
                    client.get_text(IEM_URL + "?" + urlencode(parameters), expected_start="station,valid,"),
                    site,
                    location,
                    offset,
                    tolerance_seconds,
                    max_distance_km,
                )
                additions = merge(records)
                if additions:
                    metadata["providers"].append(
                        {
                            "provider": "IEM published METAR",
                            "station": site,
                            "filled_values": additions,
                            "qc": "Very little archive QC; original reports and parser validity checks retained; not NOAA QC-certified.",
                        }
                    )
            except (APIError, DataError) as error:
                warnings.append(f"Published METAR fallback {site['icao']} unavailable: {error}")
            if complete():
                break
    return combined, metadata, warnings
