"""Audit all enriched outputs and compare station fields with original ISD reports."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyEPW import ADDITIONAL_FIELDS
from analyze_global_study import read_epw, source_audit, metrics
from extended_common import CITIES, YEARS, BASE, ROOT, CACHE, WATER, baseline, bulk_water

UTC = timezone.utc
EXTRA = (10, 11, 16, 17, 18, 19, 24, 25, 28)


def station_reference(country, year, offset):
    city = next(c for c in CITIES if c["country"] == country)
    records = []
    for source_year in (year - 1, year, year + 1):
        path = BASE / "observations" / f"{city['station']}-{source_year}.gz"
        if not path.exists():
            continue
        for line in gzip.decompress(path.read_bytes()).decode("ascii", errors="replace").splitlines():
            if len(line) < 105 or not line[15:27].isdigit() or line[23:25] == "24":
                continue
            vis = float(line[78:84]) / 1000 if line[84] in {"1", "5"} and line[78:84] != "999999" else np.nan
            ceil = float(line[70:75]) if line[75] in {"1", "5"} and line[70:75] != "99999" else np.nan
            if ceil == 22000:
                ceil = 77777.0
            if np.isfinite(ceil) and line[76] == "D":
                ceil = 88888.0
            # Preserve known right-censoring; it is not an exact-distance pair.
            if vis == 9.999:
                vis = np.nan
            records.append((line[15:27], vis, ceil, 0 if line[41:46] == "FM-12" else 1))
    if not records:
        return pd.DataFrame(columns=["visibility_km", "ceiling_height_m"])
    frame = pd.DataFrame(records, columns=["stamp", "visibility_km", "ceiling_height_m", "priority"])
    stamps = pd.to_datetime(frame.pop("stamp"), format="%Y%m%d%H%M", utc=True)
    # Explicit arithmetic avoids round-to-even at a half-hour timezone boundary.
    seconds = stamps.array.as_unit("s").asi8
    ends = np.floor((seconds + offset * 3600 + 1800) / 3600) * 3600 - offset * 3600
    frame["delta"] = np.abs(seconds - ends)
    frame["end"] = pd.to_datetime(ends, unit="s", utc=True)
    return (
        frame[frame.delta <= 900]
        .sort_values(["delta", "priority"])
        .groupby("end")
        .first()[["visibility_km", "ceiling_height_m"]]
    )


def station_lineage_audit(meta, raw, endpoints):
    """Check every accepted field against original PSV, without the library parser."""
    wanted = {}
    indices = {}
    censored = np.zeros(len(raw), dtype=bool)
    station_counts = {}
    for field, col in [("visibility_km", 24), ("ceiling_height_m", 25)]:
        covered = set()
        count = 0
        for run in meta["observation_lineage_runs"][field]:
            source = run["source"]
            for index in range(run["start_row"], run["start_row"] + run["count"]):
                assert index not in covered
                covered.add(index)
                if source is None:
                    assert float(raw[index, col]) >= (9999 if col == 24 else 99999)
                    continue
                assert abs(source["time_delta_seconds"]) <= 900 and source["distance_km"] <= 30
                assert (
                    source["source_code"] in {"313", "314", "315", "322", "335", "343", "344", "346"}
                    and source["quality_code"] in {"1", "5"}
                ) or (
                    source["source_code"] in {"220", "221", "222", "223", "347", "348"}
                    and source["quality_code"] == "1"
                )
                stamp = datetime.fromtimestamp(endpoints[index] + source["time_delta_seconds"], UTC).isoformat()[:19]
                key = (
                    field,
                    source["station_id"],
                    stamp,
                    source["source_code"],
                    source["quality_code"],
                    source["report_type"],
                )
                wanted.setdefault(key, set()).add(raw[index, col])
                count += 1
                station_counts[source["station_id"]] = station_counts.get(source["station_id"], 0) + 1
                if field == "visibility_km" and source.get("qualifier"):
                    censored[index] = True
        assert len(covered) == len(raw)
        assert count == meta["field_coverage"][field]["valid_hours"]
        indices[field] = count
    seen = {}
    referenced_stations = {key[1] for key in wanted}
    for source in meta["station_text_sources"]:
        url = source["url"]
        if "GHCNh_" not in url or not any(f"GHCNh_{site}_" in url for site in referenced_stations):
            continue
        path = CACHE / source["cached_file"]
        # APIClient's source hash is over decoded UTF-8 text with normalized newlines.
        with path.open(encoding="utf-8") as stream:
            text = stream.read()
        assert hashlib.sha256(text.encode()).hexdigest() == source["sha256_utf8"]
        for report in csv.DictReader(text.splitlines(), delimiter="|"):
            station, stamp = report["STATION"], report["DATE"].replace(" ", "T")[:19]
            for field, source_name in [("visibility_km", "visibility"), ("ceiling_height_m", "ceiling_height")]:
                key = (
                    field,
                    station,
                    stamp,
                    report[source_name + "_Source_Code"],
                    report[source_name + "_Quality_Code"],
                    report[source_name + "_Report_Type"],
                )
                if key not in wanted:
                    continue
                value = float(report[source_name])
                if field == "visibility_km":
                    if abs(value - 9.999) < 1e-6:
                        value = 10.0
                    rendered = f"{value:.3f}"
                else:
                    if value == 22000:
                        value = 77777.0
                    if (
                        report[source_name + "_Source_Code"] in {"313", "314", "315", "322", "335", "343", "344", "346"}
                        and report[source_name + "_Measurement_Code"].split(";")[0] == "D"
                    ):
                        value = 88888.0
                    rendered = f"{value:.0f}"
                seen.setdefault(key, set()).add(rendered)
    assert all(values <= seen.get(key, set()) for key, values in wanted.items()), (
        "A station value lacks raw-source support"
    )
    return indices, censored, station_counts


def analyze_city(city):
    country = city["country"]
    audits, comparisons, coverage = [], [], []
    pairs = []
    bulk = bulk_water(country)
    bulk_t = np.array(bulk["hourly"]["time"])
    bulk_v = np.array(bulk["hourly"][WATER], dtype=float)
    unchanged = [i for i in range(35) if i not in (5, *EXTRA)]
    for year in YEARS:
        cp = json.loads((ROOT / "checkpoints" / f"{country}_{year}.json").read_text(encoding="utf-8"))
        assert cp["success"], cp
        path = Path(cp["path"])
        frame, meta, raw, headers = read_epw(path)
        old_path, old_meta = baseline(country, year)
        with old_path.open(newline="", encoding="utf-8") as stream:
            old_raw = np.array(list(csv.reader(stream))[8:])
        assert np.array_equal(raw[:, unchanged], old_raw[:, unchanged]), "Core weather changed"
        # Exclude supplemental bulk responses from the independent core reconstruction.
        core_meta = {**meta, "request_urls": [u for u in meta["request_urls"] if "temperature_2m" in u]}
        check = source_audit(frame, core_meta, raw)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["output_sha256"]
        endpoints = frame.index.as_unit("s").asi8
        expected_water = np.interp(endpoints, bulk_t, bulk_v)
        water_valid = np.isfinite(expected_water)
        exported_water = raw[:, 28].astype(float)
        assert np.all(exported_water[~water_valid] == 999), (country, year, "Unreported column water was filled")
        assert np.max(np.abs(exported_water[water_valid] - expected_water[water_valid]), initial=0) <= 0.00501, (
            country,
            year,
        )
        for col in EXTRA:
            assert np.isfinite(raw[:, col].astype(float)).all() and (raw[:, col].astype(float) >= 0).all()
        checked, censored, stations = station_lineage_audit(meta, raw, endpoints)
        for name in ADDITIONAL_FIELDS:
            coverage.append(
                {"country": country, "city": city["city"], "year": year, "column": name, **meta["field_coverage"][name]}
            )
        zenith = meta["zenith_luminance_outside_epw_range"]
        assert len(zenith) == meta["daylight_model"]["zenith_outside_epw_range_hours"]
        for item in zenith:
            assert raw[item["row"], 19] == "9999" and item["zenith_luminance_cd_m2"] >= 9998.95
        obs = station_reference(country, year, meta["utc_offset_hours"]).reindex(frame.index)
        model_vis, model_ceil = raw[:, 24].astype(float), raw[:, 25].astype(float)
        model_vis[(model_vis >= 9999) | censored] = np.nan
        model_ceil[model_ceil >= 99999] = np.nan
        pair = pd.DataFrame(
            {
                "model_visibility_km": model_vis,
                "obs_visibility_km": obs.visibility_km,
                "model_ceiling_height_m": model_ceil,
                "obs_ceiling_height_m": obs.ceiling_height_m,
                "year": year,
            },
            index=frame.index,
        )
        pairs.append(pair)
        comparisons.append(
            {
                "country": country,
                "city": city["city"],
                "year": year,
                "variable": "visibility_km",
                **metrics(model_vis, obs.visibility_km, len(frame)),
            }
        )
        finite_m = np.where(model_ceil < 22000, model_ceil, np.nan)
        finite_o = obs.ceiling_height_m.where(obs.ceiling_height_m < 22000)
        comparisons.append(
            {
                "country": country,
                "city": city["city"],
                "year": year,
                "variable": "finite_ceiling_m",
                **metrics(finite_m, finite_o, len(frame)),
            }
        )
        eligible = np.isfinite(model_ceil) & obs.ceiling_height_m.notna().to_numpy()
        status = np.where(model_ceil == 77777, 1, np.where(model_ceil == 88888, 2, 0))
        ref = np.where(obs.ceiling_height_m == 77777, 1, np.where(obs.ceiling_height_m == 88888, 2, 0))
        category_agreement = float(np.mean(status[eligible] == ref[eligible])) if eligible.any() else None
        audit = {
            "country": country,
            "city": city["city"],
            "year": year,
            "package_version": meta["package_version"],
            **check,
            "core_columns_identical_to_original_study": True,
            "column_water_source_pass": True,
            "station_source_pass": True,
            "station_values_checked": checked,
            "zenith_values_preserved_outside_epw_range": len(zenith),
            "ceiling_category_pairs": int(eligible.sum()),
            "ceiling_category_agreement": category_agreement,
            "source_stations": stations,
            "output_sha256": meta["output_sha256"],
            "warnings": meta["warnings"],
        }
        audits.append(audit)
        (ROOT / "audits" / f"{country}_{year}.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        print(
            country,
            year,
            "audit passed",
            "visibility",
            checked["visibility_km"],
            "ceiling",
            checked["ceiling_height_m"],
            flush=True,
        )
    all_pairs = pd.concat(pairs)
    all_pairs.to_csv(ROOT / f"{country}_supplemental_pairs.csv.gz", compression="gzip", index_label="hour_ending_utc")
    pooled = []
    for name in ("visibility_km", "ceiling_height_m"):
        m, o = all_pairs["model_" + name], all_pairs["obs_" + name]
        if name == "ceiling_height_m":
            m, o = m.where(m < 22000), o.where(o < 22000)
        pooled.append({"country": country, "city": city["city"], "variable": name, **metrics(m, o, len(all_pairs))})
    return audits, comparisons, coverage, pooled


def cached_city(city):
    path = ROOT / "audits" / f"{city['country']}_results.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    result = analyze_city(city)
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


def main():
    audits, comparisons, coverage, pooled = [], [], [], []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(cached_city, city) for city in CITIES]):
            a, c, f, p = future.result()
            audits.extend(a)
            comparisons.extend(c)
            coverage.extend(f)
            pooled.extend(p)
    assert len(audits) == 200 and sum(a["hours"] for a in audits) == 1753200
    (ROOT / "conversion_audit.json").write_text(json.dumps(audits, indent=2), encoding="utf-8")
    pd.DataFrame(comparisons).to_csv(ROOT / "supplemental_annual_metrics.csv", index=False)
    pd.DataFrame(coverage).to_csv(ROOT / "field_coverage.csv", index=False)
    pd.DataFrame(pooled).to_csv(ROOT / "supplemental_pooled_metrics.csv", index=False)
    # Existing observational comparisons are mathematically reusable only after
    # every measured core column has been proven identical in all 200 files.
    reused = []
    for name in (
        "city_summary.csv",
        "annual_metrics.csv",
        "pooled_metrics.csv",
        "monthly_metrics.csv",
        "national_source_metrics.csv",
        "temperature_tails.csv",
        "temperature_lags.csv",
        "stations.csv",
        "singapore_monthly_rain_comparison.csv",
        "jma_tokyo_annual_comparison.csv",
    ):
        path = BASE / name
        shutil.copy2(path, ROOT / name)
        reused.append(
            {
                "file": name,
                "source": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "basis": "All 25 non-supplemental/non-flag columns match the previous actual-year files exactly for all 200 files.",
            }
        )
    (ROOT / "reused_observational_metrics.json").write_text(json.dumps(reused, indent=2), encoding="utf-8")
    print(
        "Audited 200 files, 1,753,200 records. Core station metrics retained after exact-value identity checks.",
        flush=True,
    )


if __name__ == "__main__":
    main()
