"""Source-backed snow history and NASA POWER hourly albedo.

No climatological substitution, nighttime zero fill or carry-forward of albedo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import hashlib
from pathlib import Path
from urllib.parse import urlencode

from .exceptions import APIError, DataError

UTC = timezone.utc
HOUR = timedelta(hours=1)
POWER_HOURLY = "https://power.larc.nasa.gov/api/temporal/hourly/point"
ALBEDO_PARAMETER = "ALLSKY_SRF_ALB"


def load_power_albedo(client, location, first_end, final_end):
    """Fetch hourly means in UTC, keyed by the end of each source hour.

    POWER hour 00 is the hour starting 00:00; EPW hour 1 ends 01:00.
    Provider fill codes and out-of-range values remain unknown.
    """
    begin = (first_end - HOUR).astimezone(UTC).date()
    finish = (final_end.astimezone(UTC) - timedelta(microseconds=1)).date()
    result, responses, warnings = {}, [], []
    cursor = begin
    while cursor <= finish:
        end = min(finish, cursor.replace(month=12, day=31))
        parameters = {
            "parameters": ALBEDO_PARAMETER,
            "community": "SB",
            "longitude": location.longitude,
            "latitude": location.latitude,
            "start": cursor.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }
        try:
            raw = client.get(POWER_HOURLY, parameters)
            header = raw.get("header", {})
            if header.get("time_standard") != "UTC":
                raise DataError("NASA POWER must return UTC timestamps.")
            if any(header.get(key, parameters[key]) != parameters[key] for key in ("start", "end")):
                raise DataError("NASA POWER response dates do not match the requested actual period.")
            if raw.get("parameters", {}).get(ALBEDO_PARAMETER, {}).get("units") != "dimensionless":
                raise DataError("NASA POWER albedo is not dimensionless.")
            values = raw.get("properties", {}).get("parameter", {}).get(ALBEDO_PARAMETER)
            if not isinstance(values, dict):
                raise DataError("NASA POWER did not supply an hourly albedo series.")
            fill = header.get("fill_value", -999)
            first_allowed = datetime.combine(cursor, datetime.min.time(), UTC)
            final_allowed = datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
            accepted = {}
            for key, value in values.items():
                try:
                    start = datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=UTC)
                except (ValueError, TypeError) as error:
                    raise DataError("Invalid NASA POWER hourly timestamp.") from error
                if not first_allowed <= start < final_allowed:
                    raise DataError("NASA POWER returned an hour outside the requested source period.")
                stamp = int((start + HOUR).timestamp())
                valid = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    and value != fill
                    and 0 <= value <= 1
                )
                accepted[stamp] = float(value) if valid else None
            url = POWER_HOURLY + "?" + urlencode(parameters)
            cache_dir = getattr(client, "cache_dir", None)
            cached = (
                Path(cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + ".json")
                if cache_dir is not None
                else None
            )
            responses.append(
                {
                    "header": header,
                    "geometry": raw.get("geometry"),
                    "parameter": raw["parameters"][ALBEDO_PARAMETER],
                    "url": url,
                    "expected_hours": int((final_allowed - first_allowed).total_seconds() / 3600),
                    "returned_hours": len(values),
                    "cached_file": cached.name if cached else None,
                    "sha256": hashlib.sha256(cached.read_bytes()).hexdigest() if cached and cached.exists() else None,
                }
            )
            result.update(accepted)
        except (APIError, DataError) as error:
            warnings.append(f"NASA POWER albedo {cursor} to {end} unavailable: {error}")
        cursor = end + timedelta(days=1)
    metadata = {
        "provider": "NASA POWER",
        "parameter": ALBEDO_PARAMETER,
        "units": "dimensionless",
        "source": "https://power.larc.nasa.gov/docs/methodology/energy-fluxes/derived-parameters/",
        "time_convention": "UTC hourly means; source start-of-hour moved to EPW end-of-hour",
        "gap_policy": "Provider fill codes, nighttime/undefined ratios and missing hours stay missing; no zero fill or carry-forward.",
        "responses": responses,
    }
    return result, metadata, warnings


def interval_albedo(rows, end_utc):
    """Overlap-weight hourly means for a fixed-standard-time EPW interval."""
    stamp = end_utc.timestamp()
    lower = math.floor(stamp / 3600) * 3600
    fraction = (stamp - lower) / 3600
    left = rows.get(lower)
    if not fraction:
        return left
    right = rows.get(lower + 3600)
    return None if left is None or right is None else left * (1 - fraction) + right * fraction


class SnowHistory:
    """Elapsed whole days since positive reported ERA5 hourly snowfall.

    A complete 88-day zero-snow interval establishes the documented >=88 code.
    Missing history stays unknown until a later event or 88 complete known days.
    """

    def __init__(self):
        self.last_event = None
        self.known_since = None
        self.previous_end = None

    def advance(self, end, amount_cm):
        if self.previous_end is not None and end != self.previous_end + HOUR:
            self.last_event = self.known_since = None
        self.previous_end = end
        if amount_cm is None or not math.isfinite(amount_cm) or amount_cm < 0:
            self.last_event = self.known_since = None
            return None
        if self.known_since is None:
            self.known_since = end - HOUR
        if amount_cm > 0:
            self.last_event = end
        if self.last_event is not None:
            return min(88, int((end - self.last_event).total_seconds() // 86400))
        if end - self.known_since >= timedelta(days=88):
            return 88
        return None
