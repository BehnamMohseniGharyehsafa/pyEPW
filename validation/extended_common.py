"""Shared configuration and bulk-input adapter for the v0.2.0 field study."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from run_global_study import CITIES, YEARS, FreeRateGate
from pyEPW.client import APIClient, ARCHIVE_URL
from pyEPW.exceptions import APIError

PROJECT = Path(__file__).resolve().parents[1]
BASE = PROJECT / "output/validation_10cities_20years"
ROOT = PROJECT / "output/validation_10cities_20years_v0_2"
CACHE = PROJECT / ".openmeteo_cache"
WATER = "total_column_integrated_water_vapour"
for folder in (ROOT, ROOT / "epw", ROOT / "checkpoints", ROOT / "audits"):
    folder.mkdir(parents=True, exist_ok=True)


def baseline(country, year):
    cp = json.loads((BASE / "checkpoints" / f"{country}_{year}.json").read_text(encoding="utf-8"))
    path = Path(cp["path"])
    metadata = json.loads(Path(str(path) + ".metadata.json").read_text(encoding="utf-8"))
    return path, metadata


def bulk_parameters(country):
    _, meta = baseline(country, 2024)
    city = meta["city"]
    return {
        "latitude": city["latitude"],
        "longitude": city["longitude"],
        "start_date": "2004-12-31",
        "end_date": "2025-01-02",
        "hourly": WATER,
        "models": "era5",
        "timezone": "GMT",
        "timeformat": "unixtime",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "cell_selection": "land",
        "elevation": city["elevation"],
    }


def bulk_url(country):
    return ARCHIVE_URL + "?" + urlencode(bulk_parameters(country))


@lru_cache(maxsize=2)
def bulk_water(country):
    url = bulk_url(country)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    return json.loads(path.read_text(encoding="utf-8"))


_TEXT_FAILURES = {}


class StudyClient(APIClient):
    """Keep real bulk URL provenance while slicing its hourly arrays for the engine.

    This validation-only adapter reduces 2,600 one-variable HTTP requests to ten
    exact original responses. No modeled values, conversion helpers or production
    library code are replaced. Standard APIClient remains the transport/cache.
    """

    country = None

    def get(self, endpoint, parameters):
        if parameters.get("hourly") != WATER:
            return super().get(endpoint, parameters)
        from datetime import datetime, timezone

        raw = bulk_water(self.country)
        self.urls.append(bulk_url(self.country))
        start = int(datetime.fromisoformat(parameters["start_date"]).replace(tzinfo=timezone.utc).timestamp())
        end = int(datetime.fromisoformat(parameters["end_date"]).replace(tzinfo=timezone.utc).timestamp()) + 86400
        first = raw["hourly"]["time"][0]
        lo, hi = (start - first) // 3600, (end - first) // 3600
        assert lo >= 0 and hi <= len(raw["hourly"]["time"])
        return {**raw, "hourly": {k: values[lo:hi] for k, values in raw["hourly"].items()}}

    def get_text(self, url, *, expected_start=None):
        if url in _TEXT_FAILURES:
            self.urls.append(url)
            raise APIError(_TEXT_FAILURES[url])
        try:
            return super().get_text(url, expected_start=expected_start)
        except APIError as error:
            # Avoid re-requesting a confirmed absent file in adjacent local years.
            # The actual absence remains a warning, never a synthetic observation.
            if "HTTP 404" in str(error):
                _TEXT_FAILURES[url] = str(error)
            raise


__all__ = [
    "CITIES",
    "YEARS",
    "FreeRateGate",
    "PROJECT",
    "BASE",
    "ROOT",
    "CACHE",
    "WATER",
    "baseline",
    "bulk_parameters",
    "bulk_url",
    "bulk_water",
    "StudyClient",
]
