"""Exercise default snow downloads and verify all three serializers in ten cities."""

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from run_global_study import CITIES, ROOT, CACHE, instrument_client
from pyEPW import EPW


def run(city):
    obj = EPW(
        city["city"],
        2024,
        ".epw",
        country=city["country"],
        output_dir=ROOT / "default_snow_2024",
        cache_dir=CACHE,
        include_additional_fields=False,  # Reproduce the v0.1.0 snow/serializer comparison.
        overwrite=True,
    )
    cp = json.loads((ROOT / "checkpoints" / f"{city['country']}_2024.json").read_text())
    main = Path(cp["path"])
    with main.open(newline="") as f:
        reference = list(csv.reader(f))[8:]
    with obj.path.open(newline="") as f:
        default = list(csv.reader(f))[8:]
    unchanged = all(
        all(x == y for i, (x, y) in enumerate(zip(a, b)) if i not in (5, 30)) for a, b in zip(reference, default)
    )
    serializers = {}
    for suffix in ("csv", "txt"):
        path = main.with_suffix("." + suffix)
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(
                csv.reader((line for line in f if not line.startswith("#")), delimiter="\t" if suffix == "txt" else ",")
            )
        meta = json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text(encoding="utf-8"))
        serializers[suffix] = {
            "matches_epw": rows[1:] == reference,
            "sha256_pass": hashlib.sha256(path.read_bytes()).hexdigest() == meta["output_sha256"],
        }
    snow_parts = []
    for url in obj.metadata["request_urls"]:
        if parse_qs(urlparse(url).query).get("hourly") == ["snow_depth"]:
            raw = json.loads((CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")).read_text(encoding="utf-8"))
            assert raw["hourly_units"]["snow_depth"] == "m"
            snow_parts.append(pd.DataFrame(raw["hourly"]))
    snow = pd.concat(snow_parts).drop_duplicates("time").sort_values("time")
    ends = pd.date_range(obj.metadata["first_hour_ending_local"], periods=obj.hours, freq="h").as_unit("s").asi8
    expected = np.interp(ends, snow.time, snow.snow_depth) * 100
    actual = np.array([r[30] for r in default], dtype=float)
    valid = np.isfinite(expected)
    snow_error = float(np.max(np.abs(expected[valid] - actual[valid])))
    result = {
        "city": city["city"],
        "country": city["country"],
        "year": 2024,
        "default_snow_hours": obj.hours - obj.metadata["missing_snow_hours"],
        "non_snow_columns_identical": unchanged,
        "serializers": serializers,
        "warnings": obj.metadata["warnings"],
        "snow_source_conversion_pass": snow_error <= 0.05001,
        "snow_max_rounding_error_cm": snow_error,
    }
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    instrument_client()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, CITIES))
    (ROOT / "default_and_format_checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
