"""Reproducible, resumable 200-city-year study using free public endpoints.

Run from any directory: python validation/run_global_study.py
Network requests obey conservative Open-Meteo weighted call limits.
Observation downloads use the original NOAA ISD gzip archive, not model data.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlencode

import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from pyEPW import EPW  # noqa: E402
from pyEPW.client import APIClient, ARCHIVE_URL  # noqa: E402

ROOT = PROJECT / "output" / "validation_10cities_20years"
CACHE = PROJECT / ".openmeteo_cache"
YEARS = range(2005, 2025)
# Station identities verified against NOAA's isd-history.csv, including ICAO.
CITIES = [
    {
        "city": "Dublin",
        "country": "IE",
        "station": "039690-99999",
        "icao": "EIDW",
        "provider": "Met Éireann / Irish aviation observations",
    },
    {
        "city": "Frankfurt am Main",
        "country": "DE",
        "station": "106370-99999",
        "icao": "EDDF",
        "provider": "German surface / aviation observing network",
    },
    {
        "city": "Madrid",
        "country": "ES",
        "station": "082210-99999",
        "icao": "LEMD",
        "provider": "Spanish surface / aviation observing network",
    },
    {
        "city": "New York City",
        "country": "US",
        "station": "744860-94789",
        "icao": "KJFK",
        "provider": "US surface / aviation observing network",
    },
    {
        "city": "Toronto",
        "country": "CA",
        "station": "716240-99999",
        "icao": "CYYZ",
        "provider": "Canadian surface / aviation observing network",
    },
    {
        "city": "Tokyo",
        "country": "JP",
        "station": "476710-99999",
        "icao": "RJTT",
        "provider": "Japanese surface / aviation observing network",
    },
    {
        "city": "New Delhi",
        "country": "IN",
        "station": "421810-99999",
        "icao": "VIDP",
        "provider": "Indian surface / aviation observing network",
    },
    {
        "city": "Singapore",
        "country": "SG",
        "station": "486980-99999",
        "icao": "WSSS",
        "provider": "Singapore surface / aviation observing network",
    },
    {
        "city": "Sydney",
        "country": "AU",
        "station": "947670-99999",
        "icao": "YSSY",
        "provider": "Australian surface / aviation observing network",
    },
    {
        "city": "Cape Town",
        "country": "ZA",
        "station": "688160-99999",
        "icao": "FACT",
        "provider": "South African surface / aviation observing network",
    },
]
for folder in (ROOT, ROOT / "epw", ROOT / "observations", ROOT / "checkpoints"):
    folder.mkdir(parents=True, exist_ok=True)


def emit(event, **kwargs):
    print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}), flush=True)


class FreeRateGate:
    """Conservative accounting, including time and variable weighting.

    Persists reservations so a resumed run does not reset its quota history.
    The public library is unchanged; this gate is study instrumentation only.
    """

    def __init__(self):
        self.path = ROOT / "request_ledger.json"
        self.lock = threading.Lock()
        self.events = json.loads(self.path.read_text()) if self.path.exists() else []
        self.last_notice = 0

    def reserve(self, cost):
        while True:
            with self.lock:
                now = time.time()
                self.events = [e for e in self.events if e[0] > now - 86400]
                # Official RateLimiter.swift resets the hour during its first
                # minute (now % 3600 < 60). Allow a full minute for that callback.
                # Minute/day limits remain rolling and below published limits.
                hour_start = (int((now - 60) // 3600)) * 3600
                allowed = (
                    sum(e[1] for e in self.events if e[0] > now - 60) + cost <= 400
                    and sum(e[1] for e in self.events if e[0] >= hour_start) + cost <= 4750
                    and sum(e[1] for e in self.events) + cost <= 9000
                )
                if allowed:
                    self.events.append([now, cost])
                    temporary = self.path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(self.events), encoding="utf-8")
                    temporary.replace(self.path)
                    return
                if now - self.last_notice > 60:
                    emit(
                        "free_rate_limit_wait",
                        weighted_calls_this_utc_hour=round(sum(e[1] for e in self.events if e[0] >= hour_start), 2),
                    )
                    self.last_notice = now
            time.sleep(5)


def instrument_client():
    gate = FreeRateGate()
    original = APIClient.get

    def get(self, endpoint, parameters):
        url = endpoint + "?" + urlencode(parameters)
        cache = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if not cache.exists() or self.refresh:
            cost = 1.0
            if endpoint == ARCHIVE_URL:
                days = (
                    date.fromisoformat(parameters["end_date"]) - date.fromisoformat(parameters["start_date"])
                ).days + 1
                cost = max(1, len(parameters["hourly"].split(",")) / 10) * max(1, days / 14)
            gate.reserve(cost)
        return original(self, endpoint, parameters)

    APIClient.get = get


def weather(city):
    for year in YEARS:
        checkpoint = ROOT / "checkpoints" / f"{city['country']}_{year}.json"
        if checkpoint.exists() and json.loads(checkpoint.read_text()).get("success"):
            continue
        started = time.time()
        try:
            # Snow is optional and not measured by our benchmark. Omitting it
            # avoids a second 200-year model download. Missing code 999 is explicit.
            obj = EPW(
                city["city"],
                year,
                ".epw",
                country=city["country"],
                output_dir=ROOT / "epw",
                cache_dir=CACHE,
                include_snow=False,
                include_additional_fields=False,  # Reproduce the v0.1.0 core-weather benchmark.
                overwrite=True,
            )
            if year == 2024:
                obj.to_csv(overwrite=True)
                obj.to_txt(overwrite=True)
            result = {
                "success": True,
                "city": city["city"],
                "country": city["country"],
                "year": year,
                "hours": obj.hours,
                "path": str(obj.path),
                "seconds": round(time.time() - started, 2),
            }
            checkpoint.write_text(json.dumps(result, indent=2), encoding="utf-8")
            emit("epw_complete", **result)
        except Exception as exc:
            result = {
                "success": False,
                "city": city["city"],
                "country": city["country"],
                "year": year,
                "error": f"{type(exc).__name__}: {exc}",
            }
            checkpoint.write_text(json.dumps(result, indent=2), encoding="utf-8")
            emit("epw_error", **result)


def download_observation(city, year):
    if city["country"] == "CA" and year == 2005:
        emit(
            "observation_external_source",
            country="CA",
            year=2005,
            note="NOAA file unavailable; use the direct ECCC station-5097 downloads.",
        )
        return
    target = ROOT / "observations" / f"{city['station']}-{year}.gz"
    sidecar = target.with_suffix(".metadata.json")
    if target.exists() and sidecar.exists():
        return
    url = f"https://www.ncei.noaa.gov/pub/data/noaa/{year}/{city['station']}-{year}.gz"
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": "pyEPW-validation/0.1"})
            r.raise_for_status()
            if not r.content.startswith(b"\x1f\x8b"):
                raise ValueError("Download is not gzip (possible archive redirect to HTML)")
            content = gzip.decompress(r.content)
            lines = content.splitlines()
            if not lines or not all(line[15:19] == str(year).encode() for line in lines):
                raise ValueError("ISD station-year identity check failed")
            target.write_bytes(r.content)
            sidecar.write_text(
                json.dumps(
                    {
                        "url": url,
                        "city": city,
                        "year": year,
                        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
                        "bytes": len(r.content),
                        "records": len(lines),
                        "sha256": hashlib.sha256(r.content).hexdigest(),
                        "source_last_modified": r.headers.get("Last-Modified"),
                        "product": "NOAA NCEI Integrated Surface Database (original station reports, QC flags retained)",
                        "modification": "None; original compressed archive",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            emit("observation_complete", country=city["country"], year=year, records=len(lines))
            return
        except Exception as exc:
            if attempt == 3:
                emit("observation_error", country=city["country"], year=year, error=str(exc))
            else:
                time.sleep(2**attempt)


def main():
    sources = {
        "isd-history.csv": "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv",
        "isd-format.pdf": "https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf",
    }
    for name, url in sources.items():
        path = ROOT / name
        if not path.exists():
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            path.write_bytes(response.content)
    (ROOT / "archive_metadata_sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    (ROOT / "study_config.json").write_text(
        json.dumps(
            {
                "years": list(YEARS),
                "cities": CITIES,
                "include_snow": False,
                "paid_endpoints": False,
                "note": "Comparisons use local station measurements archived by NOAA. Direct national-service checks are reported separately.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    instrument_client()
    # Four concurrent model locations; observations use two separate workers.
    with ThreadPoolExecutor(max_workers=2) as obs, ThreadPoolExecutor(max_workers=4) as wx:
        tasks = [obs.submit(download_observation, city, year) for city in CITIES for year in YEARS]
        tasks += [wx.submit(weather, city) for city in CITIES]
        for task in as_completed(tasks):
            task.result()
    checkpoints = [json.loads(p.read_text()) for p in (ROOT / "checkpoints").glob("*.json")]
    emit(
        "run_complete",
        weather_success=sum(x["success"] for x in checkpoints),
        observations=len(list((ROOT / "observations").glob("*.gz"))),
    )


if __name__ == "__main__":
    main()
