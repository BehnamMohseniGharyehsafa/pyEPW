"""Independent EPW/source audit and local-station comparisons (no network)."""

from __future__ import annotations

import argparse
import csv
import gzip
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "output" / "validation_10cities_20years"
CACHE = PROJECT / ".openmeteo_cache"
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib"))

FIELDS = {
    "temperature_c": 6,
    "dewpoint_c": 7,
    "rh_percent": 8,
    "pressure_hpa": 9,
    "ghi_wh_m2": 13,
    "dni_wh_m2": 14,
    "dhi_wh_m2": 15,
    "wind_direction_deg": 20,
    "wind_ms": 21,
    "rain_mm": 33,
}
QC_STRICT = {"1", "5"}
QC_BROAD = {"0", "1", "4", "5", "9"}
PRECIP = re.compile(r"AA[1-4](\d{2})(\d{4})(.)(.)")
PRESSURE = re.compile(r"MA1(\d{5})(.)(\d{5})(.)")


def distance(lat1, lon1, lat2, lon2):
    a, b, c, d = np.radians([lat1, lon1, lat2, lon2])
    h = np.sin((c - a) / 2) ** 2 + np.cos(a) * np.cos(c) * np.sin((d - b) / 2) ** 2
    return float(6371.0088 * 2 * np.arcsin(np.sqrt(h)))


def read_epw(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    headers, values = rows[:8], rows[8:]
    a = np.array(values, dtype=str)
    year = int(a[0, 0])
    offset = float(headers[0][8])
    local_start = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    expected = np.stack(
        [local_start.year, local_start.month, local_start.day, local_start.hour + 1, np.full(len(local_start), 60)],
        axis=1,
    )
    if a.shape != (len(expected), 35) or not np.array_equal(a[:, :5].astype(int), expected):
        raise ValueError(f"Calendar/column failure: {path}")
    if not np.all(np.char.str_len(a[:, 5]) == 44):
        raise ValueError("Data-source flag width is not 44")
    index = (local_start + pd.Timedelta(hours=1 - offset)).tz_localize("UTC")
    out = pd.DataFrame({k: a[:, v].astype(float) for k, v in FIELDS.items()}, index=index)
    out["pressure_hpa"] /= 100
    if not np.isfinite(out.to_numpy()).all():
        raise ValueError("Nonfinite EPW meteorology")
    metadata = json.loads(path.with_suffix(".epw.metadata.json").read_text(encoding="utf-8"))
    if metadata["year"] != year or metadata["rows"] != len(out) or metadata["tmy"]:
        raise ValueError("Provenance calendar mismatch")
    return out, metadata, a, headers


def source_audit(epw, meta, a):
    """Independent vectorized reconstruction from cached *raw API* arrays.

    Does not call any conversion, interpolation, or validation library helper.
    It tests transcription, units and calendar; it is not observation validation.
    """
    parts = []
    for url in meta["request_urls"]:
        q = parse_qs(urlparse(url).query)
        if "era5" not in q.get("models", []) or "hourly" not in q:
            continue
        raw = json.loads((CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")).read_text(encoding="utf-8"))
        part = pd.DataFrame(raw["hourly"])
        parts.append(part)
    raw = pd.concat(parts).drop_duplicates("time").sort_values("time").set_index("time")
    t = epw.index.as_unit("s").asi8.astype(float)
    x = raw.index.to_numpy(dtype=float)
    expected = {}
    mapping = {
        "temperature_c": "temperature_2m",
        "dewpoint_c": "dew_point_2m",
        "rh_percent": "relative_humidity_2m",
        "pressure_hpa": "surface_pressure",
        "ghi_wh_m2": "shortwave_radiation",
        "dni_wh_m2": "direct_normal_irradiance",
        "dhi_wh_m2": "diffuse_radiation",
        "wind_ms": "wind_speed_10m",
        "wind_direction_deg": "wind_direction_10m",
        "rain_mm": "rain",
    }
    for key, var in mapping.items():
        expected[key] = np.interp(t, x, raw[var].to_numpy(dtype=float))
    if meta["utc_offset_hours"] % 1:
        angle = np.radians(raw["wind_direction_10m"].to_numpy(dtype=float))
        speed = raw["wind_speed_10m"].to_numpy(dtype=float)
        u, v = np.interp(t, x, speed * np.sin(angle)), np.interp(t, x, speed * np.cos(angle))
        expected["wind_ms"] = np.hypot(u, v)
        expected["wind_direction_deg"] = np.where(np.hypot(u, v) > 1e-9, np.degrees(np.arctan2(u, v)) % 360, 0)
    tolerances = {
        "temperature_c": 0.00501,
        "dewpoint_c": 0.00501,
        "rh_percent": 0.05001,
        "pressure_hpa": 0.00501,
        "wind_direction_deg": 0.05001,
    }
    errors = {}
    for key, value in expected.items():
        error = np.abs(epw[key].to_numpy() - value)
        if key == "wind_direction_deg":
            error = np.abs((epw[key].to_numpy() - value + 180) % 360 - 180)
        errors[key] = float(error.max())
        if errors[key] > tolerances.get(key, 0.00501):
            raise ValueError(f"Source conversion mismatch: {key}, max error {errors[key]}")
    cloud = np.interp(t, x, raw["cloud_cover"].to_numpy(dtype=float)) / 10
    if not np.array_equal(a[:, 22].astype(float), np.rint(cloud)):
        raise ValueError("Cloud percent-to-tenths mismatch")
    tk = expected["temperature_c"] + 273.15
    emissivity = (0.787 + 0.764 * np.log((expected["dewpoint_c"] + 273.15) / 273)) * (
        1 + 0.0224 * cloud - 0.0035 * cloud**2 + 0.00028 * cloud**3
    )
    ir = np.clip(emissivity, 0, 1) * 5.6697e-8 * tk**4
    if np.max(np.abs(ir - a[:, 12].astype(float))) > 0.00501:
        raise ValueError("Infrared estimate transcription mismatch")
    return {
        "source_conversion_pass": True,
        "calendar_pass": True,
        "hours": len(epw),
        "max_rounding_errors": errors,
        "missing_snow_hours": int((a[:, 30] == "999").sum()),
    }


@lru_cache(maxsize=4)
def parse_isd(path, offset, broad=False):
    accepted = QC_BROAD if broad else QC_STRICT
    rows = []
    for line in gzip.decompress(path.read_bytes()).decode("ascii", errors="replace").splitlines():
        if len(line) < 105:
            continue
        dt = line[15:27]
        if not dt.isdigit() or dt[8:10] == "24":
            continue

        def number(begin, end, qc, missing, scale):
            text = line[begin:end]
            return int(text) / scale if line[qc] in accepted and text != missing else np.nan

        t = number(87, 92, 92, "+9999", 10)
        dew = number(93, 98, 98, "+9999", 10)
        wind = number(65, 69, 69, "9999", 10)
        direction = number(60, 63, 63, "999", 1)
        pressure = np.nan
        if m := PRESSURE.search(line, 105):
            if m[4] in accepted and m[3] != "99999":
                pressure = int(m[3]) / 10
        rain = np.nan
        for m in PRECIP.finditer(line, 105):
            if m[1] == "01" and m[2] != "9999" and m[4] in accepted and m[3] in {"2", "9"}:
                rain = int(m[2]) / 10
                break
        rows.append([dt, t, dew, wind, direction, pressure, rain, 0 if line[41:46] == "FM-12" else 1])
    df = pd.DataFrame(
        rows,
        columns=[
            "time",
            "temperature_c",
            "dewpoint_c",
            "wind_ms",
            "wind_direction_deg",
            "pressure_hpa",
            "rain_mm",
            "priority",
        ],
    )
    times = pd.to_datetime(df.pop("time"), format="%Y%m%d%H%M", utc=True)
    # Nearest hour ending in fixed local standard time; no daylight saving.
    end = (times + pd.Timedelta(hours=offset)).dt.round("h") - pd.Timedelta(hours=offset)
    df["delta"] = (times - end).dt.total_seconds().abs()
    df["end_utc"] = end
    df = df[df.delta <= 900].copy()
    # Hour totals are compared only with reports within 60 seconds of the
    # target endpoint; do not shift :51 or multi-hour accumulations to :00.
    df.loc[df.delta > 60, "rain_mm"] = np.nan
    # Choose the nearest valid value per field, with SYNOP before METAR at ties.
    df = df.sort_values(["delta", "priority"]).groupby("end_utc").first()
    df["rh_percent"] = np.clip(
        100
        * np.exp(
            17.625 * df.dewpoint_c / (243.04 + df.dewpoint_c) - 17.625 * df.temperature_c / (243.04 + df.temperature_c)
        ),
        0,
        100,
    )
    return df.drop(columns=["delta", "priority"])


def toronto_2005():
    frames = []
    for month in range(1, 13):
        f = ROOT / "national_sources" / f"toronto_5097_2005_{month:02d}.csv"
        frames.append(pd.read_csv(f, encoding="utf-8-sig"))
    d = pd.concat(frames)
    if not d["Station Name"].str.contains("PEARSON", case=False).all():
        raise ValueError("Unexpected ECCC station")
    result = pd.DataFrame(index=(pd.to_datetime(d["Date/Time (LST)"]) + pd.Timedelta(hours=5)).dt.tz_localize("UTC"))
    names = {
        "temperature_c": "Temp (°C)",
        "dewpoint_c": "Dew Point Temp (°C)",
        "rh_percent": "Rel Hum (%)",
        "wind_ms": "Wind Spd (km/h)",
        "wind_direction_deg": "Wind Dir (10s deg)",
        "pressure_hpa": "Stn Press (kPa)",
    }
    for key, col in names.items():
        flag = {
            "temperature_c": "Temp Flag",
            "dewpoint_c": "Dew Point Temp Flag",
            "rh_percent": "Rel Hum Flag",
            "wind_ms": "Wind Spd Flag",
            "wind_direction_deg": "Wind Dir Flag",
            "pressure_hpa": "Stn Press Flag",
        }[key]
        value = pd.to_numeric(d[col], errors="coerce").where(d[flag].isna() | d[flag].astype(str).str.strip().eq(""))
        result[key] = value.to_numpy()
    result["wind_ms"] /= 3.6
    result["wind_direction_deg"] *= 10
    result["pressure_hpa"] *= 10
    result["rain_mm"] = np.nan
    return result


def metrics(model, obs, expected):
    model, obs = np.asarray(model, dtype=float), np.asarray(obs, dtype=float)
    mask = np.isfinite(model) & np.isfinite(obs)
    m, o = model[mask], obs[mask]
    n = len(m)
    base = {"n": n, "coverage_percent": 100 * n / expected}
    if n < 2:
        return base
    e = m - o
    return {
        **base,
        "model_mean": float(m.mean()),
        "observed_mean": float(o.mean()),
        "bias": float(e.mean()),
        "mae": float(np.abs(e).mean()),
        "rmse": float(np.sqrt(np.mean(e**2))),
        "correlation": float(np.corrcoef(m, o)[0, 1]) if np.std(m) and np.std(o) else np.nan,
        "model_sum": float(m.sum()),
        "observed_sum": float(o.sum()),
    }


def direction_metrics(frame, expected):
    m, o = frame.model_wind_direction_deg, frame.obs_wind_direction_deg
    mask = m.notna() & o.notna() & (frame.model_wind_ms >= 1) & (frame.obs_wind_ms >= 1)
    e = ((m[mask] - o[mask] + 180) % 360 - 180).to_numpy()
    if not len(e):
        return {"n": 0, "coverage_percent": 0.0}
    return {
        "n": len(e),
        "coverage_percent": 100 * len(e) / expected,
        "bias": float(np.degrees(np.arctan2(np.sin(np.radians(e)).mean(), np.cos(np.radians(e)).mean()))),
        "mae": float(np.abs(e).mean()),
        "rmse": float(np.sqrt(np.mean(e**2))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="Recompute one country's results and retain all other completed countries.")
    args = parser.parse_args()
    config = json.loads((ROOT / "study_config.json").read_text(encoding="utf-8"))
    if args.country:
        config["cities"] = [c for c in config["cities"] if c["country"] == args.country.upper()]
        if not config["cities"]:
            parser.error("Country is not part of this study")
        args.country = args.country.upper()
    history = pd.read_csv(ROOT / "isd-history.csv", dtype={"USAF": str, "WBAN": str})
    annual, pooled, audit, stations, monthly, tails, lags, broad_results = [], [], [], [], [], [], [], []
    (ROOT / "paired").mkdir(exist_ok=True)
    for city in config["cities"]:
        country = city["country"]
        pairs = []
        for year in config["years"]:
            cp = ROOT / "checkpoints" / f"{country}_{year}.json"
            if not cp.exists() or not (status := json.loads(cp.read_text())).get("success"):
                continue
            epw, meta, a, headers = read_epw(Path(status["path"]))
            check = source_audit(epw, meta, a)
            audit.append({"country": country, "city": city["city"], "year": year, **check})
            obs_path = ROOT / "observations" / f"{city['station']}-{year}.gz"
            if not obs_path.exists() and not (country == "CA" and year == 2005):
                continue
            obs = toronto_2005() if country == "CA" and year == 2005 else parse_isd(obs_path, meta["utc_offset_hours"])
            # Join adjacent calendar-year reports, when already downloaded,
            # to cover fixed-local-year boundary hours without invented values.
            boundaries = []
            for adjacent in (year - 1, year + 1):
                f = ROOT / "observations" / f"{city['station']}-{adjacent}.gz"
                if f.exists():
                    # Parse only when local year extends outside UTC year.
                    if (adjacent == year - 1 and meta["utc_offset_hours"] > 1) or (
                        adjacent == year + 1 and meta["utc_offset_hours"] < 1
                    ):
                        extra = parse_isd(f, meta["utc_offset_hours"])
                        boundaries.append(extra[extra.index.isin(epw.index)])
            if boundaries:
                obs = pd.concat([obs, *boundaries]).sort_index()
                obs = obs[~obs.index.duplicated(keep="first")]
            joined = epw.add_prefix("model_").join(obs.add_prefix("obs_"))
            joined["local_year"] = year
            joined["local_month"] = (
                joined.index + pd.Timedelta(hours=meta["utc_offset_hours"]) - pd.Timedelta(hours=1)
            ).month
            # ISD is liquid-equivalent total precipitation; exclude potential
            # snow hours before comparing the library's rain-only field.
            joined.loc[joined.obs_temperature_c < 3, "obs_rain_mm"] = np.nan
            for key in obs.columns:
                if key == "wind_direction_deg":
                    annual.append(
                        {
                            "city": city["city"],
                            "country": country,
                            "year": year,
                            "variable": key,
                            **direction_metrics(joined, len(epw)),
                        }
                    )
                    continue
                row = metrics(joined["model_" + key], joined["obs_" + key], len(epw))
                annual.append({"city": city["city"], "country": country, "year": year, "variable": key, **row})
            for month, group in joined.groupby("local_month"):
                for key in ["temperature_c", "wind_ms", "rain_mm"]:
                    monthly.append(
                        {
                            "city": city["city"],
                            "country": country,
                            "year": year,
                            "month": int(month),
                            "variable": key,
                            **metrics(group["model_" + key], group["obs_" + key], len(group)),
                        }
                    )
            if year in (2005, 2024) and obs_path.exists():
                broad = parse_isd(obs_path, meta["utc_offset_hours"], broad=True).reindex(epw.index)
                broad_results.append(
                    {"country": country, "year": year, **metrics(epw.temperature_c, broad.temperature_c, len(epw))}
                )
            pairs.append(joined)
            if year == config["years"][0]:
                usaf, wban = city["station"].split("-")
                station = history[(history.USAF == usaf) & (history.WBAN == wban)].iloc[0]
                c = meta["city"]
                g = meta["source_grids"][0]
                stations.append(
                    {
                        **city,
                        "resolved_city": c["name"],
                        "city_latitude": c["latitude"],
                        "city_longitude": c["longitude"],
                        "city_elevation_m": c["elevation"],
                        "timezone": c["timezone"],
                        "utc_offset_hours": meta["utc_offset_hours"],
                        "station_name": station["STATION NAME"],
                        "station_latitude": station.LAT,
                        "station_longitude": station.LON,
                        "station_elevation_m": station["ELEV(M)"],
                        "city_to_station_km": distance(c["latitude"], c["longitude"], station.LAT, station.LON),
                        "city_to_model_grid_km": distance(c["latitude"], c["longitude"], g["latitude"], g["longitude"]),
                        "grid_latitude": g["latitude"],
                        "grid_longitude": g["longitude"],
                    }
                )
        if not pairs:
            continue
        all_pairs = pd.concat(pairs).sort_index()
        all_pairs.to_csv(
            ROOT / "paired" / f"{country}_hourly_pairs.csv.gz",
            compression="gzip",
            float_format="%.5f",
            index_label="hour_ending_utc",
        )
        for key in ["temperature_c", "dewpoint_c", "rh_percent", "wind_ms", "pressure_hpa", "rain_mm"]:
            pooled.append(
                {
                    "city": city["city"],
                    "country": country,
                    "variable": key,
                    **metrics(all_pairs["model_" + key], all_pairs["obs_" + key], len(all_pairs)),
                }
            )
        pooled.append(
            {
                "city": city["city"],
                "country": country,
                "variable": "wind_direction_deg",
                **direction_metrics(all_pairs, len(all_pairs)),
            }
        )
        for name, mask in [
            ("coldest_5_percent", all_pairs.obs_temperature_c <= all_pairs.obs_temperature_c.quantile(0.05)),
            ("hottest_5_percent", all_pairs.obs_temperature_c >= all_pairs.obs_temperature_c.quantile(0.95)),
        ]:
            sub = all_pairs.loc[mask]
            tails.append(
                {
                    "country": country,
                    "subset": name,
                    **metrics(sub.model_temperature_c, sub.obs_temperature_c, len(all_pairs)),
                }
            )
        for lag in range(-3, 4):
            shifted = all_pairs.obs_temperature_c.shift(lag)
            lags.append(
                {
                    "country": country,
                    "observation_shift_hours": lag,
                    **metrics(all_pairs.model_temperature_c, shifted, len(all_pairs)),
                }
            )
        print(country, "analyzed", len(pairs), "years", flush=True)
    for name, items in [
        ("annual_metrics", annual),
        ("pooled_metrics", pooled),
        ("stations", stations),
        ("monthly_metrics", monthly),
        ("temperature_tails", tails),
        ("temperature_lags", lags),
        ("qc_sensitivity", broad_results),
    ]:
        frame = pd.DataFrame(items)
        path = ROOT / (name + ".csv")
        if args.country and path.exists():
            previous = pd.read_csv(path)
            frame = pd.concat([previous[previous.country != args.country], frame], ignore_index=True)
        frame.to_csv(path, index=False)
    audit_path = ROOT / "conversion_audit.json"
    if args.country and audit_path.exists():
        previous = json.loads(audit_path.read_text(encoding="utf-8"))
        audit = [x for x in previous if x["country"] != args.country] + audit
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print("Audited", len(audit), "EPWs;", sum(x["hours"] for x in audit), "hourly records", flush=True)


if __name__ == "__main__":
    main()
