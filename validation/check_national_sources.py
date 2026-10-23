"""Additional direct national-service checks, with actual coverage retained."""

import calendar
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from analyze_global_study import ROOT, metrics, read_epw

NATIONAL = ROOT / "national_sources"


def exports(country):
    frames = []
    for year in range(2005, 2025):
        cp = json.loads((ROOT / "checkpoints" / f"{country}_{year}.json").read_text())
        frame, meta, raw, headers = read_epw(Path(cp["path"]))
        frame["infrared_wh_m2"] = raw[:, 12].astype(float)
        frame["year"] = year
        frame["month"] = (frame.index + pd.Timedelta(hours=meta["utc_offset_hours"] - 1)).month
        frames.append(frame)
    return pd.concat(frames)


def main():
    rows = []
    # Direct national hourly temperature/RH/wind/rain for Dublin.
    f = NATIONAL / "dublin_hly532.csv"
    with f.open() as stream:
        skip = next(i for i, line in enumerate(stream) if line.startswith("date,"))
    d = pd.read_csv(f, skiprows=skip, low_memory=False)
    d.columns = d.columns.str.strip()
    d.index = pd.to_datetime(d.pop("date"), format="%d-%b-%Y %H:%M", utc=True)
    d = d.loc["2005":"2025"].apply(pd.to_numeric, errors="coerce")
    d.loc[~d["ind.1"].isin([0, 1]), "temp"] = np.nan
    d.loc[~d["ind.2"].isin([0, 1]), ["dewpt", "rhum"]] = np.nan
    d.loc[~d["ind.3"].isin([1, 2]), "wdsp"] = np.nan
    d.loc[~d["ind"].isin([0, 1, 2, 3]), "rain"] = np.nan
    d.loc[d["ind"].isin([1, 3]), "rain"] = 0
    d["wdsp"] *= 1852 / 3600
    model = exports("IE")
    for year, group in model.groupby("year"):
        obs = d.reindex(group.index)
        for key, col in {
            "temperature_c": "temp",
            "dewpoint_c": "dewpt",
            "rh_percent": "rhum",
            "wind_ms": "wdsp",
            "rain_mm": "rain",
        }.items():
            observation = obs[col].copy()
            if key == "rain_mm":
                observation = observation.where(obs.temp >= 3)
            rows.append(
                {
                    "country": "IE",
                    "source": "Met Éireann direct: Dublin Airport",
                    "year": year,
                    "variable": key,
                    "aggregation": "hourly",
                    **metrics(group[key], observation, len(group)),
                }
            )
    # Every Dublin Airport flag in this period is 111 (investigation required).
    # Keep its zero eligible counts above, and use a separate nearby station
    # with valid provider quality indicators for a direct Irish check.
    f = NATIONAL / "phoenix_hly175.csv"
    with f.open() as stream:
        skip = next(i for i, line in enumerate(stream) if line.startswith("date,"))
    d = pd.read_csv(f, skiprows=skip, low_memory=False)
    d.columns = d.columns.str.strip()
    d.index = pd.to_datetime(d.pop("date"), format="%d-%b-%Y %H:%M", utc=True)
    d = d.loc["2005":"2025"].apply(pd.to_numeric, errors="coerce")
    d.loc[~d["ind.1"].isin([0, 1]), "temp"] = np.nan
    d.loc[~d["ind.2"].isin([0, 1]), ["dewpt", "rhum"]] = np.nan
    d.loc[~d["ind"].isin([0, 1, 2, 3]), "rain"] = np.nan
    d.loc[d["ind"].isin([1, 3]), "rain"] = 0
    for year, group in model.groupby("year"):
        obs = d.reindex(group.index)
        for key, col in {
            "temperature_c": "temp",
            "dewpoint_c": "dewpt",
            "rh_percent": "rhum",
            "rain_mm": "rain",
        }.items():
            observation = obs[col].where(obs.temp >= 3) if key == "rain_mm" else obs[col]
            rows.append(
                {
                    "country": "IE",
                    "source": "Met Éireann direct: Phoenix Park (separate station)",
                    "year": year,
                    "variable": key,
                    "aggregation": "hourly",
                    **metrics(group[key], observation, len(group)),
                }
            )
    # DWD's independently maintained hourly temperature and measured humidity.
    with zipfile.ZipFile(NATIONAL / "frankfurt_temperature.zip") as z:
        n = next(n for n in z.namelist() if n.startswith("produkt"))
        d = pd.read_csv(z.open(n), sep=";")
    d.columns = d.columns.str.strip()
    d.index = pd.to_datetime(d.MESS_DATUM.astype(str), format="%Y%m%d%H", utc=True)
    d.loc[~d.QN_9.isin([3, 5, 7, 8, 10]), ["TT_TU", "RF_TU"]] = np.nan
    d[["TT_TU", "RF_TU"]] = d[["TT_TU", "RF_TU"]].replace(-999, np.nan)
    model = exports("DE")
    for year, group in model.groupby("year"):
        obs = d.reindex(group.index)
        for key, col in {"temperature_c": "TT_TU", "rh_percent": "RF_TU"}.items():
            rows.append(
                {
                    "country": "DE",
                    "source": "DWD direct: Frankfurt/Main 01420",
                    "year": year,
                    "variable": key,
                    "aggregation": "hourly",
                    **metrics(group[key], obs[col], len(group)),
                }
            )
    # Radiation instruments at 01420 began in 2022. Earlier archives contain
    # sunshine duration, with radiation marked -999. Never convert that to zero.
    parts = []
    for f in sorted(NATIONAL.glob("frankfurt_solar10_*.zip")):
        with zipfile.ZipFile(f) as z:
            d = pd.read_csv(z.open(z.namelist()[0]), sep=";")
        d.columns = d.columns.str.strip()
        d.index = pd.to_datetime(d.MESS_DATUM.astype(str), format="%Y%m%d%H%M", utc=True)
        parts.append(d)
    d = pd.concat(parts).sort_index()
    d = d[~d.index.duplicated(keep="last")]
    d = d.loc["2005":"2025"]
    r = d[["GS_10", "DS_10", "LS_10"]].replace(-999, np.nan)
    r.loc[~d.QN.isin([3, 5, 7, 8, 10]), :] = np.nan
    # All three fields are energies during the previous ten minutes, J/cm2.
    # 1 J/cm2 = 10000/3600 Wh/m2. Require all six constituent measurements.
    hourly = r.resample("h", closed="right", label="right").sum(min_count=6) * (10000 / 3600)
    radiation_pairs = []
    for year, group in model.groupby("year"):
        obs = hourly.reindex(group.index)
        for key, col in {"ghi_wh_m2": "GS_10", "dhi_wh_m2": "DS_10", "infrared_wh_m2": "LS_10"}.items():
            m = metrics(group[key], obs[col], len(group))
            rows.append(
                {
                    "country": "DE",
                    "source": "DWD direct: Frankfurt/Main 01420",
                    "year": year,
                    "variable": key,
                    "aggregation": "hourly",
                    **m,
                }
            )
        joined = group[["ghi_wh_m2", "dhi_wh_m2", "infrared_wh_m2"]].add_prefix("model_").join(obs.add_prefix("obs_"))
        radiation_pairs.append(joined)
    pd.concat(radiation_pairs).to_csv(
        ROOT / "paired" / "DE_radiation_pairs.csv.gz",
        compression="gzip",
        float_format="%.4f",
        index_label="hour_ending_utc",
    )
    # JMA Tokyo annual values: twenty individual actual years, not normals.
    # Annual GHI is reported as mean daily MJ/m2, rounded to 0.1 MJ/m2/day.
    jma = pd.read_html(NATIONAL / "jma_tokyo_annual.html")[0]
    jma = jma[jma.iloc[:, 0].between(2005, 2024)]
    model = exports("JP")
    annual_values = []
    for row in jma.itertuples(index=False, name=None):
        year = int(row[0])
        group = model[model.year == year]
        annual_values.append(
            {
                "year": year,
                "model_temperature_c": group.temperature_c.mean(),
                "observed_temperature_c": float(row[7]),
                "model_ghi_mj_m2_day": group.ghi_wh_m2.sum() * 0.0036 / (366 if calendar.isleap(year) else 365),
                "observed_ghi_mj_m2_day": float(row[20]),
                "model_rain_mm": group.rain_mm.sum(),
                "observed_precip_mm": float(row[3]),
                "model_rh_percent": group.rh_percent.mean(),
                "observed_rh_percent": float(row[12]),
            }
        )
    j = pd.DataFrame(annual_values)
    j.to_csv(ROOT / "jma_tokyo_annual_comparison.csv", index=False)
    for key in ["temperature_c", "ghi_mj_m2_day", "rh_percent"]:
        rows.append(
            {
                "country": "JP",
                "source": "JMA direct: Tokyo city observatory 47662 (different site from Haneda)",
                "year": "2005-2024",
                "variable": key,
                "aggregation": "20 annual values",
                **metrics(j["model_" + key], j["observed_" + key], 20),
            }
        )
    # Singapore NEA publishes complete Changi actual-month totals freely.
    obs = pd.read_csv(NATIONAL / "singapore_monthly_rain.csv")
    obs = obs[obs.month.between("2005-01", "2024-12")].copy()
    obs["year"] = obs.month.str[:4].astype(int)
    obs["month_number"] = obs.month.str[-2:].astype(int)
    obs["total_rainfall"] = pd.to_numeric(obs.total_rainfall, errors="coerce")
    model = exports("SG")
    m = model.groupby(["year", "month"]).rain_mm.sum().rename("model_rain_mm").reset_index()
    m = m.merge(obs, left_on=["year", "month"], right_on=["year", "month_number"], suffixes=("_number", "_text"))
    m.to_csv(ROOT / "singapore_monthly_rain_comparison.csv", index=False)
    rows.append(
        {
            "country": "SG",
            "source": "NEA direct: Changi Climate Station",
            "year": "2005-2024",
            "variable": "rain_mm",
            "aggregation": "240 monthly totals",
            **metrics(m.model_rain_mm, m.total_rainfall, 240),
        }
    )
    results = pd.DataFrame(rows)
    results.to_csv(ROOT / "national_source_metrics.csv", index=False)
    print(
        results[
            (results.n > 0)
            & results.variable.isin(["ghi_wh_m2", "dhi_wh_m2", "infrared_wh_m2", "ghi_mj_m2_day", "rain_mm"])
        ][["country", "year", "variable", "n", "bias", "mae", "correlation"]]
        .tail(15)
        .to_string(index=False)
    )
    print("National-service metric rows", len(results), flush=True)


if __name__ == "__main__":
    main()
