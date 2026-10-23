"""Compare every city/year with an independent NREL SPA reference implementation."""

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyEPW._solar import solar_cosine
from extended_common import ROOT, PROJECT, CITIES, YEARS, baseline

REFERENCE = ROOT / "reference/pvlib_spa.py"
UTC = timezone.utc


def prepare_reference():
    REFERENCE.parent.mkdir(exist_ok=True)
    sources = {
        "pvlib_spa.py": "https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/spa.py",
        "pvlib_LICENSE": "https://raw.githubusercontent.com/pvlib/pvlib-python/main/LICENSE",
    }
    for name, url in sources.items():
        path = REFERENCE.parent / name
        if not path.exists():
            previous = PROJECT / ".verification/enrichment/pvlib_spa_reference.py"
            if name == "pvlib_spa.py" and previous.exists():
                shutil.copy2(previous, path)
            else:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                path.write_bytes(response.content)
    manifest = [
        {"file": name, "url": url, "sha256": hashlib.sha256((REFERENCE.parent / name).read_bytes()).hexdigest()}
        for name, url in sources.items()
    ]
    (REFERENCE.parent / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run(city):
    spec = importlib.util.spec_from_file_location("spa_reference", REFERENCE)
    spa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spa)
    rows = []
    country = city["country"]
    for year in YEARS:
        cp = json.loads((ROOT / "checkpoints" / f"{country}_{year}.json").read_text(encoding="utf-8"))
        path = Path(cp["path"])
        _, old_meta = baseline(country, year)
        latitude, longitude = old_meta["city"]["latitude"], old_meta["city"]["longitude"]
        offset = old_meta["utc_offset_hours"]
        local_start = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
        endpoints = ((local_start + pd.Timedelta(hours=1 - offset)).astype("int64") // 10**9).to_numpy()
        midpoint = endpoints - 1800
        delta_t = spa.calculate_deltat(year, 7)
        reference = spa.solar_position(
            midpoint.astype(float), latitude, longitude, 0, 1013.25, 15, delta_t, 0.5667, numthreads=1
        )[1]
        ours = np.array(
            [np.degrees(np.arccos(solar_cosine(datetime.fromtimestamp(t, UTC), latitude, longitude))) for t in midpoint]
        )
        error = np.abs(ours - reference)
        assert error.max() < 0.05, (country, year, error.max())
        # Independently integrate four complete seasonal days at one-minute
        # resolution using SPA's geometric zenith. The comparison uses the same
        # explicitly specified solar constant/Spencer distance convention.
        times = []
        indices = []
        for month, day in ((3, 20), (6, 21), (9, 22), (12, 21)):
            start_local = datetime(year, month, day, tzinfo=UTC)
            start_utc = start_local - timedelta(hours=offset)
            times.extend(start_utc.timestamp() + np.arange(1440) * 60 + 30)
            indices.extend(np.flatnonzero((local_start.month == month) & (local_start.day == day)))
        times = np.array(times)
        z = spa.solar_position(times, latitude, longitude, 0, 1013.25, 15, delta_t, 0.5667, numthreads=1)[1]
        day = pd.to_datetime(times, unit="s", utc=True).dayofyear.to_numpy()
        angle = 2 * np.pi * (day - 1) / 365
        factor = (
            1.00011
            + 0.034221 * np.cos(angle)
            + 0.00128 * np.sin(angle)
            + 0.000719 * np.cos(2 * angle)
            + 0.000077 * np.sin(2 * angle)
        )
        expected_horizontal = (1361 * factor * np.maximum(np.cos(np.radians(z)), 0)).reshape(96, 60).mean(axis=1)
        raw = pd.read_csv(path, skiprows=8, header=None)
        horizontal_error = np.abs(raw.iloc[indices, 10].to_numpy(dtype=float) - expected_horizontal)
        assert horizontal_error.max() < 0.6, (country, year, horizontal_error.max())
        # Earth-distance harmonic approximation is also compared with SPA's
        # orbital calculation. This is distinct from weather observation error.
        distance = spa.solar_position(
            times[::60], latitude, longitude, 0, 1013.25, 15, delta_t, 0.5667, numthreads=1, esd=True
        )[0]
        orbit_relative = np.abs(factor[::60] - 1 / distance**2) / (1 / distance**2)
        assert orbit_relative.max() < 0.01
        rows.append(
            {
                "country": country,
                "year": year,
                "midpoint_samples": len(midpoint),
                "max_zenith_error_degrees": float(error.max()),
                "mean_zenith_error_degrees": float(error.mean()),
                "hourly_energy_samples": 96,
                "max_horizontal_energy_error_wh_m2": float(horizontal_error.max()),
                "max_earth_distance_factor_relative_error_percent": float(100 * orbit_relative.max()),
            }
        )
    print(country, "20-year solar reference checks passed", flush=True)
    return rows


if __name__ == "__main__":
    prepare_reference()
    with ProcessPoolExecutor(max_workers=4) as pool:
        records = [record for city_records in pool.map(run, CITIES) for record in city_records]
    assert len(records) == 200
    pd.DataFrame(records).to_csv(ROOT / "solar_reference_checks.csv", index=False)
    print(
        "Compared",
        sum(r["midpoint_samples"] for r in records),
        "hourly midpoints and",
        sum(r["hourly_energy_samples"] for r in records),
        "integrated hours against NREL SPA.",
        flush=True,
    )
