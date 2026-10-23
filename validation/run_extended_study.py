"""Generate all 200 current-version enriched EPWs, with free cached inputs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyEPW import EPW, Location, __version__, api
from pyEPW.client import APIClient, ARCHIVE_URL
from extended_common import (
    CITIES,
    YEARS,
    FreeRateGate,
    ROOT,
    CACHE,
    WATER,
    baseline,
    bulk_parameters,
    bulk_url,
    StudyClient,
)


def emit(event, **kwargs):
    print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}), flush=True)


def prefetch():
    gate = FreeRateGate()  # Shares conservative earlier-run daily reservations.

    def fetch(city):
        country = city["country"]
        parameters = bulk_parameters(country)
        url = bulk_url(country)
        path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if not path.exists():
            days = (date.fromisoformat(parameters["end_date"]) - date.fromisoformat(parameters["start_date"])).days + 1
            # Current official ForecastApiResult.calculateQueryWeight():
            # max(1, variables/10, variables/10 * days/14), per location.
            # The earlier harness overestimated single-variable requests.
            gate.reserve(max(1, 0.1 * days / 14))
        response = APIClient(CACHE).get(ARCHIVE_URL, parameters)
        hours = len(response["hourly"]["time"])
        assert response["hourly_units"][WATER] == "kg/m²"
        assert len(response["hourly"][WATER]) == hours and hours > 175200
        result = {
            "country": country,
            "url": url,
            "cached_file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "hours": hours,
        }
        emit("bulk_water_ready", **result)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        manifest = list(pool.map(fetch, CITIES))
    (ROOT / "bulk_water_sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def generate_city(city):
    logging.basicConfig(level=logging.ERROR)
    StudyClient.country = city["country"]
    api.APIClient = StudyClient
    _, ref = baseline(city["country"], 2024)
    location = Location(**ref["city"])
    for year in YEARS:
        cp = ROOT / "checkpoints" / f"{city['country']}_{year}.json"
        if cp.exists():
            previous = json.loads(cp.read_text(encoding="utf-8"))
            if previous.get("success") and previous.get("package_version") == __version__:
                continue
        started = time.time()
        try:
            w = EPW(
                location,
                year,
                output_dir=ROOT / "epw",
                cache_dir=CACHE,
                overwrite=True,
                include_snow=False,
                include_additional_fields=True,
            )
            if year == 2024:
                w.to_csv(overwrite=True)
                w.to_txt(overwrite=True)
                w.to_analysis_csv(overwrite=True)
            result = {
                "success": True,
                "country": city["country"],
                "city": city["city"],
                "year": year,
                "path": str(w.path),
                "hours": w.hours,
                "package_version": __version__,
                "seconds": round(time.time() - started, 2),
                "coverage": {
                    k: v for k, v in w.field_coverage.items() if k in __import__("pyEPW").ADDITIONAL_FIELDS
                },
            }
            cp.write_text(json.dumps(result, indent=2), encoding="utf-8")
            emit(
                "epw_complete",
                country=city["country"],
                year=year,
                hours=w.hours,
                seconds=result["seconds"],
                visibility_hours=w.field_coverage["visibility_km"]["valid_hours"],
                ceiling_hours=w.field_coverage["ceiling_height_m"]["valid_hours"],
            )
        except Exception as error:
            result = {
                "success": False,
                "country": city["country"],
                "year": year,
                "error": f"{type(error).__name__}: {error}",
            }
            cp.write_text(json.dumps(result, indent=2), encoding="utf-8")
            emit("epw_error", **result)
    return city["country"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefetch-only", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    prefetch()
    config = {
        "package_version": __version__,
        "years": list(YEARS),
        "cities": CITIES,
        "include_additional_fields": True,
        "include_snow": False,
        "station": "auto",
        "max_station_distance_km": 30,
        "station_tolerance_minutes": 15,
        "paid_endpoints": False,
        "baseline": "../validation_10cities_20years",
        "bulk_adapter": "Exact hourly slices of ten original ERA5 column-water responses; actual bulk URLs retained in EPW provenance.",
        "rate_weight_reference": "https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Helper/Writer/ForecastApiResult.swift",
    }
    (ROOT / "study_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    if not args.prefetch_only:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(generate_city, city) for city in CITIES]):
                emit("city_complete", country=future.result())
        cp = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "checkpoints").glob("*.json")]
        emit("generation_complete", successes=sum(r["success"] for r in cp), attempted=len(cp))


if __name__ == "__main__":
    main()
