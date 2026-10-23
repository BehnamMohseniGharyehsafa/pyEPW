"""Publish the completed local validation report and scientific figures."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "output" / "validation_10cities_20years"
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib"))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(map(str, row)) + " |" for row in rows],
        ]
    )


def main():
    audit = json.loads((ROOT / "conversion_audit.json").read_text())
    energy = json.loads((ROOT / "energyplus_checks.json").read_text())
    defaults = json.loads((ROOT / "default_and_format_checks.json").read_text())
    assert len(audit) == 200 and all(x["source_conversion_pass"] and x["calendar_pass"] for x in audit)
    assert len(energy) == 200 and all(x["pass"] and x["severe_errors"] == 0 for x in energy)
    assert len(defaults) == 10 and all(
        x["snow_source_conversion_pass"] and x["non_snow_columns_identical"] for x in defaults
    )
    assert all(all(v["matches_epw"] and v["sha256_pass"] for v in x["serializers"].values()) for x in defaults)
    p = pd.read_csv(ROOT / "pooled_metrics.csv")
    annual = pd.read_csv(ROOT / "annual_metrics.csv")
    stations = pd.read_csv(ROOT / "stations.csv")
    n = pd.read_csv(ROOT / "national_source_metrics.csv")
    tails = pd.read_csv(ROOT / "temperature_tails.csv")
    lags = pd.read_csv(ROOT / "temperature_lags.csv")
    countries = ["IE", "DE", "ES", "US", "CA", "JP", "IN", "SG", "AU", "ZA"]
    names = dict(zip(stations.country, stations.city))
    country_names = {
        "IE": "Ireland",
        "DE": "Germany",
        "ES": "Spain",
        "US": "USA",
        "CA": "Canada",
        "JP": "Japan",
        "IN": "India",
        "SG": "Singapore",
        "AU": "Australia",
        "ZA": "South Africa",
    }
    temp = p[p.variable == "temperature_c"].set_index("country").loc[countries]
    wind = p[p.variable == "wind_ms"].set_index("country").loc[countries]
    wind["relative_bias_percent"] = 100 * wind.bias / wind.observed_mean
    station = stations.set_index("country").loc[countries]
    assert annual[annual.variable == "temperature_c"].groupby("country").size().eq(20).all()
    # Audit the actual delivered files against every writer's provenance hash.
    integrity = []
    for folder in [ROOT / "epw", ROOT / "default_snow_2024", ROOT / "collocated_2024"]:
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix not in (".epw", ".csv", ".txt"):
                continue
            metadata = json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text(encoding="utf-8"))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            integrity.append(
                {"file": str(path.relative_to(ROOT)), "sha256": digest, "pass": digest == metadata["output_sha256"]}
            )
    assert integrity and all(x["pass"] for x in integrity)
    (ROOT / "file_integrity_audit.json").write_text(json.dumps(integrity, indent=2), encoding="utf-8")
    # Compact companion data for users who want the main result as a CSV.
    overview = pd.DataFrame(
        {
            "city": [names[c] for c in countries],
            "country": [country_names[c] for c in countries],
            "years": 20,
            "station_distance_km": station.city_to_station_km.to_numpy(),
            "temperature_coverage_percent": temp.coverage_percent.to_numpy(),
            "temperature_bias_c": temp.bias.to_numpy(),
            "temperature_mae_c": temp.mae.to_numpy(),
            "temperature_rmse_c": temp.rmse.to_numpy(),
            "temperature_correlation": temp.correlation.to_numpy(),
            "wind_bias_ms": wind.bias.to_numpy(),
            "wind_mae_ms": wind.mae.to_numpy(),
            "wind_bias_percent": wind.relative_bias_percent.to_numpy(),
        }
    )
    overview.to_csv(ROOT / "city_summary.csv", index=False)
    plt.rcParams.update(
        {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white"}
    )
    labels = [names[c] for c in countries]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.8), gridspec_kw={"width_ratios": [1.2, 1.2, 1.1]})
    y = np.arange(10)
    axes[0].barh(y, temp.mae, color="#167c80")
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Hourly temperature MAE (°C)")
    for i, value in enumerate(temp.mae):
        axes[0].text(value + 0.02, i, f"{value:.2f}", va="center", fontsize=9)
    axes[0].set_xlim(0, 2.1)
    axes[1].barh(y, wind.relative_bias_percent, color="#cf7736")
    axes[1].set_yticks(y, [])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Mean wind bias (%)")
    axes[1].axvline(0, color="#555", lw=0.8)
    for i, value in enumerate(wind.relative_bias_percent):
        axes[1].text(
            value - 1 if value < 0 else value + 1,
            i,
            f"{value:+.1f}",
            va="center",
            ha="right" if value < 0 else "left",
            fontsize=9,
        )
    axes[1].set_xlim(-62, 12)
    axes[2].scatter(temp.coverage_percent, y, color="#536f9b", s=55)
    axes[2].set_yticks(y, [])
    axes[2].invert_yaxis()
    axes[2].set_xlabel("Temperature observation coverage (%)")
    axes[2].set_xlim(85, 102)
    axes[2].grid(axis="x", alpha=0.15)
    for i, value in enumerate(temp.coverage_percent):
        axes[2].text(value + 0.15, i, f"{value:.1f}", va="center", fontsize=9)
    fig.suptitle(
        "2005–2024 · City-point ERA5 EPWs versus nearby local station measurements", fontsize=14, weight="bold"
    )
    fig.text(
        0.02,
        0.02,
        "200 actual city-years. Errors include model and site differences. Wind bias = model minus station. No TMY data.",
        fontsize=9,
        color="#444",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    fig.savefig(ROOT / "comparison_overview.png", dpi=180)
    plt.close(fig)
    # Year-by-year heatmap prevents pooled statistics concealing a bad year.
    heat = (
        annual[annual.variable == "temperature_c"].pivot(index="country", columns="year", values="mae").loc[countries]
    )
    fig, ax = plt.subplots(figsize=(13, 5.5))
    im = ax.imshow(heat, aspect="auto", vmin=0, vmax=max(2.5, float(heat.max().max())), cmap="YlOrRd")
    ax.set_yticks(range(10), labels)
    ax.set_xticks(range(20), heat.columns, rotation=60)
    fig.colorbar(im, ax=ax, label="Hourly temperature MAE (°C)")
    ax.set_title("Temperature error for every city and actual year (200 cells)")
    fig.tight_layout()
    fig.savefig(ROOT / "temperature_by_year.png", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(5, 2, figsize=(12, 13), sharex=True)
    for ax, c in zip(axes.flat, countries):
        d = annual[(annual.country == c) & (annual.variable == "temperature_c")].sort_values("year")
        ax.plot(d.year, d.model_mean, label="ERA5 city EPW", color="#167c80")
        ax.plot(d.year, d.observed_mean, label="Local station", color="#cf7736")
        ax.set_title(names[c])
        ax.set_ylabel("Mean temperature (°C)")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
        ax.grid(alpha=0.18)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("Annual means over matched valid observation hours", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(ROOT / "annual_temperature.png", dpi=150)
    plt.close(fig)
    sg = pd.read_csv(ROOT / "singapore_monthly_rain_comparison.csv")
    sg_annual = sg.groupby("year")[["model_rain_mm", "total_rainfall"]].sum()
    rain_bias = 100 * (sg.model_rain_mm.sum() / sg.total_rainfall.sum() - 1)
    jma = pd.read_csv(ROOT / "jma_tokyo_annual_comparison.csv")
    solar_bias = 100 * (jma.model_ghi_mj_m2_day.mean() / jma.observed_ghi_mj_m2_day.mean() - 1)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].plot(sg_annual.index, sg_annual.model_rain_mm, label="ERA5 Singapore city", color="#167c80")
    axes[0].plot(sg_annual.index, sg_annual.total_rainfall, label="NEA Changi station", color="#cf7736")
    axes[0].set_ylabel("Annual rain (mm)")
    axes[0].set_title(f"Singapore rain: {rain_bias:+.1f}% over 20 years")
    axes[0].legend(fontsize=8)
    axes[1].plot(jma.year, jma.model_ghi_mj_m2_day, label="ERA5 Tokyo city", color="#167c80")
    axes[1].plot(jma.year, jma.observed_ghi_mj_m2_day, label="JMA Tokyo observatory", color="#cf7736")
    axes[1].set_ylabel("Mean daily GHI (MJ/m²/day)")
    axes[1].set_title(f"Tokyo solar: {solar_bias:+.1f}% mean bias")
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=0.2)
        ax.ticklabel_format(useOffset=False, axis="x")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    fig.tight_layout()
    fig.savefig(ROOT / "national_rain_and_solar.png", dpi=180)
    plt.close(fig)
    # Report narrative and tables.
    main_rows = []
    for c in countries:
        t, w, s = temp.loc[c], wind.loc[c], station.loc[c]
        main_rows.append(
            [
                names[c],
                country_names[c],
                f"{s.city_to_station_km:.1f}",
                f"{t.coverage_percent:.1f}%",
                f"{t.bias:+.2f}",
                f"{t.mae:.2f}",
                f"{t.rmse:.2f}",
                f"{t.correlation:.3f}",
                f"{w.relative_bias_percent:+.1f}%",
            ]
        )
    main_table = table(
        [
            "City",
            "Country",
            "Station distance km",
            "T coverage",
            "T bias °C",
            "T MAE °C",
            "T RMSE °C",
            "T r",
            "Wind mean bias",
        ],
        main_rows,
    )
    field_rows = []
    for c in countries:
        values = []
        for variable in ["temperature_c", "dewpoint_c", "rh_percent", "wind_ms", "pressure_hpa", "rain_mm"]:
            row = p[(p.country == c) & (p.variable == variable)].iloc[0]
            values.append(f"{row.coverage_percent:.1f}%" if row.coverage_percent >= 5 else "insufficient")
        field_rows.append([names[c], *values])
    coverage_table = table(
        ["City", "Temperature", "Dew point", "RH*", "Wind speed", "Station pressure", "1-hour warm rain"], field_rows
    )
    station_table = table(
        ["City", "Station", "ICAO", "Station elevation m", "City elevation m"],
        [
            [
                names[c],
                station.loc[c, "station_name"],
                station.loc[c, "icao"],
                f"{station.loc[c, 'station_elevation_m']:.1f}",
                f"{station.loc[c, 'city_elevation_m']:.1f}",
            ]
            for c in countries
        ],
    )
    national_rows = []
    for (source, var), g in n[(n.n > 1) & (n.aggregation == "hourly")].groupby(["source", "variable"]):
        if var not in ["temperature_c", "rh_percent", "ghi_wh_m2", "dhi_wh_m2", "infrared_wh_m2"]:
            continue
        count = g.n.sum()
        mae = (g.mae * g.n).sum() / count
        bias = (g.bias * g.n).sum() / count
        national_rows.append([source, var, int(count), f"{bias:+.3f}", f"{mae:.3f}"])
    national_table = table(
        ["Direct source", "Variable (native units below)", "Valid pairs", "Bias", "MAE"], national_rows
    )
    warning_count = sum(x["warning_messages"] > 0 for x in energy)
    cold = tails[tails.subset == "coldest_5_percent"].set_index("country")
    best_lags = lags.loc[lags.groupby("country").correlation.idxmax()]
    assert (best_lags.observation_shift_hours == 0).sum() == 9
    phoenix = n[(n.source.str.contains("Phoenix")) & (n.variable == "temperature_c")]
    phoenix_mae = float((phoenix.mae * phoenix.n).sum() / phoenix.n.sum())
    phi_bias = float((phoenix.bias * phoenix.n).sum() / phoenix.n.sum())
    colocated = ""
    if (ROOT / "collocated_diagnostics.csv").exists():
        diag = pd.read_csv(ROOT / "collocated_diagnostics.csv")
        diag_rows = []
        for c in ["US", "JP", "AU"]:
            for var in ["temperature_c", "wind_ms"]:
                original = annual[(annual.country == c) & (annual.year == 2024) & (annual.variable == var)].iloc[0]
                revised = diag[(diag.country == c) & (diag.variable == var)].iloc[0]
                diag_rows.append(
                    [
                        names[c],
                        var,
                        f"{original.bias:+.3f}",
                        f"{revised.bias:+.3f}",
                        f"{original.mae:.3f}",
                        f"{revised.mae:.3f}",
                    ]
                )
        colocated = (
            "\n### Station-coordinate diagnostic (2024 only)\n\nThree additional EPWs were generated at the airport coordinates and elevation after large discrepancies were identified. They do not replace the 200 city-point results, and are a diagnostic, not an independently selected validation sample. Changes quantify sensitivity to location; they do not establish one cause for the entire discrepancy.\n\n"
            + table(["City", "Variable", "City bias", "Airport-point bias", "City MAE", "Airport-point MAE"], diag_rows)
            + "\n\nAll three station-coordinate diagnostics have their best 2024 temperature lag at zero. New York's small city-point phase preference is absent at the airport point in this diagnostic year. Location-specific meteorology remains a plausible contributor; this does not prove a cause for every year. Sydney's airport-point wind remains strongly underestimated.\n"
        )
    summary = {
        "period": [2005, 2024],
        "cities": 10,
        "countries": 10,
        "city_years": 200,
        "hourly_records": sum(x["hours"] for x in audit),
        "calendar_and_source_conversion_passes": 200,
        "energyplus_complete_actual_year_runs": 200,
        "energyplus_runs_with_warnings": warning_count,
        "energyplus_severe_errors": sum(x["severe_errors"] for x in energy),
        "default_snow_samples": 10,
        "temperature_mae_range_c": [float(temp.mae.min()), float(temp.mae.max())],
        "singapore_total_rain_bias_percent": float(rain_bias),
        "tokyo_annual_ghi_mean_bias_percent": float(solar_bias),
        "zero_paid_api_calls": True,
        "not_a_station_accuracy_certification": True,
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
    }
    (ROOT / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = f"""# Twenty-year validation of pyEPW in ten countries

Completed {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. Package version 0.1.0. Period: **2005–2024**, inclusive. All files contain individual historical years; none is a TMY.

## Finding

**The converter faithfully transfers its selected Open-Meteo data into EPW, but the resulting weather is not uniformly accurate enough to represent a particular station or building site.** All **200 EPWs / 1,753,200 hourly records** passed the independent source/calendar audit. Hourly temperature MAE against nearby stations ranges from **{temp.mae.min():.2f} to {temp.mae.max():.2f} °C**. Wind is materially underestimated at several cities; Sydney's mean difference is **{wind.loc["AU", "relative_bias_percent"]:+.1f}%**, New York's **{wind.loc["US", "relative_bias_percent"]:+.1f}%**, and Tokyo's **{wind.loc["JP", "relative_bias_percent"]:+.1f}%**. Singapore's accumulated city-point rain is **{rain_bias:+.1f}%** above the published Changi measurements.

These are errors of the delivered city-point weather relative to nearby instruments. They combine reanalysis error, city/airport differences, elevation, coastal effects, station exposure, observation conventions, and measurement uncertainty. A correct file conversion cannot remove those differences. No production-library changes or empirical bias corrections were made during this study.

## Ten cities and twenty actual years each

Bias means model minus observation. MAE is mean absolute error; RMSE is root mean square error; r is Pearson correlation. Each statistic uses only matched, accepted observations. Coverage is the accepted matched count divided by all expected EPW hours. The measured station can be 9–22 km from the requested city coordinates.

{main_table}

The principal common archive is [NOAA NCEI's Integrated Surface Database](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database): actual local surface/aviation station reports, redistributed and quality-checked by NOAA. **This is not a claim that twenty years were downloaded directly from ten different national websites.** Direct national-service checks were additionally performed for Ireland, Germany, Japan, Singapore, and Canada's missing 2005 file. Provider attribution and the exact download URL accompany each observation file.

![Ten-city comparison](comparison_overview.png)

## Conversion and file checks

- **200/200** source audits passed. A separate vectorized implementation reconstructs each year from the cached original API JSON without calling the library's conversion/interpolation helpers. It checks temperature, dew point, RH, station pressure, GHI, DNI, DHI, wind speed/direction, rain, cloud conversion and the infrared estimate, within the serializer's rounding precision.
- **200/200** calendars passed: 35 fields, eight EPW header lines, chronological hour-ending local standard time, 8,760/8,784 rows, February 29 retained, no duplicate/missing hours, and the requested actual year. New Delhi exercises UTC+5:30 interpolation and interval overlap. The other nine locations exercise positive/negative whole-hour offsets and both hemispheres.
- The main 200-file run used the public **`include_snow=False`** option. Snow is explicitly missing (`999`), not zero. Ten additional **2024 default-option** exports fetched ERA5-Land snow and passed an independent metres-to-centimetres source audit; all other weather columns match the snow-disabled files. This does **not** validate snow depth against snow measurements.
- The ten 2024 CSV and ten TXT exports contain exactly the same 35-field records as their corresponding EPWs. Every delivered weather file's SHA-256 matches its provenance sidecar.
- The existing **31 offline library tests passed**. The validation scripts and data sit outside the runtime library; pandas, NumPy, Matplotlib and requests are analysis-only dependencies.

### EnergyPlus compatibility

**200/200** EPWs completed full actual-year runs in installed **EnergyPlus 25.1**, using its one-zone example with the matching site, actual start/end year, daylight saving disabled, and actual-weather mode enabled. The SQLite hourly dry-bulb record counts equal the expected 8,760/8,784 in every run. There were **zero severe errors**.

**{warning_count}/200 runs contained psychrometric temperature-range warnings in `PsyPsatFnTemp` / `PsyTwbFnTdbWPb`.** These are retained in `energyplus/COUNTRY_YEAR/eplusout.err`; they must not be described as warning-free runs. Passing here means complete weather-file processing and the correct calendar, not certification of the example building or its numerical behavior. Warning causes are not established by this check. `energyplus_checks.json` identifies every affected case.

## What the observations actually cover

{station_table}

{coverage_table}

*RH in the common ISD comparison is derived from valid observed temperature/dew point using the Magnus relation, rather than an independent humidity instrument. Direct DWD and Met Éireann checks use their reported RH. Pressure comparisons use **station pressure only**; neither sea-level pressure nor altimeter settings are substituted. City/airport height differences can dominate pressure bias, particularly Dublin, Madrid, and Sydney. These raw pressure biases are not evidence of a Pa/hPa conversion mistake.

The strict common-archive QC accepts ISD flags **1 or 5** only and rejects missing sentinels. Valid reports are matched to the nearest fixed-standard-time endpoint within **15 minutes**, preferring SYNOP over METAR at ties and selecting the nearest valid value separately for each field. This is a point-observation approximation, particularly for METAR reports at :51/:53. No missing observations are filled with zero. A sensitivity check with gross-limit-only QC codes is retained for 2005 and 2024; see `qc_sensitivity.csv`.

One-hour precipitation comparisons require an explicit **one-hour** accumulation, endpoint within 60 seconds, strict QC, no estimated/incomplete accumulation codes, and observed temperature at least 3°C. Multi-hour totals are never relabelled as hourly rain. This leaves too little representative hourly rainfall in the common archive for a global rain-accuracy conclusion. ISD total precipitation may contain melted snow whereas the library requests rain. The table's insufficient cells mean **not validated**, not zero error. Singapore's direct monthly rain comparison provides a separate, meaningful twenty-year test.

### Observation quality and coverage exceptions

- NOAA's Toronto Pearson **2005** file is unavailable (HTTP 404). The complete year is supplied by twelve direct [Environment and Climate Change Canada](https://climate.weather.gc.ca/) hourly downloads for station 5097, with the same Pearson site identity verified from headers, local standard time UTC−5, km/h→m/s and kPa→hPa conversions. Its measured RH is retained. Nonempty element flags are excluded, including three estimated wind readings. No other year is substituted.
- The direct Met Éireann **Dublin Airport** download has indicator **111 for every record** in 2005–2024. It is excluded from direct national metrics (zero eligible pairs). NOAA applies its own QC to separately archived airport reports; those comparison results above are useful but provisional in light of this provider-file discrepancy. They do not override Met Éireann's indicators.
- A separate direct **Phoenix Park** check uses accepted Met Éireann indicators over all twenty years: temperature MAE **{phoenix_mae:.3f}°C**, bias **{phi_bias:+.3f}°C**, {int(phoenix.n.sum()):,} valid temperature pairs. Phoenix Park (53.364, −6.350, 48 m) is a different site, approximately 6 km from the city point; its results must not be presented as airport measurements.
- Year-edge station reports outside the downloaded 2005–2024 UTC range are absent for a few first/last local-year hours. Adjacent downloaded years are joined where available. Those observation gaps reduce the reported coverage; the EPWs themselves remain complete.
- Station metadata coordinates/elevations are a reference snapshot; station histories, instrument changes and relocations can affect the twenty-year comparison. ISD can merge SYNOP and aviation reports for one station identity.

## Direct national-service checks

{national_table}

Temperature/dew point units are °C; humidity is percentage points; GHI, DHI and horizontal infrared are **Wh/m² over one hour**. Numerical hourly energy errors also equal hourly-mean W/m² errors, but they are not instantaneous irradiance errors. The direct Irish airport rows have zero accepted pairs and are deliberately absent from this table.

- **Germany:** DWD station 01420 supplies all twenty years of hourly temperature and measured RH. Its ten-minute radiation measurements start **May 2022**, not 2005. Six valid previous-ten-minute J/cm² totals are required per hour and converted by 10000/3600 to Wh/m². Earlier radiation sentinels remain missing. GHI, DHI and the infrared estimate therefore have a **partial 2022 plus 2023–2024** instrument comparison, rather than twenty-year global validation. Quality levels used: 3, 5, 7, 8, 10, with missing values rejected. Current DWD metadata identify its automatic/complete quality-control stages; acceptance is not an assertion that every record has completed manual review.
- **Japan:** JMA's Tokyo city-observatory series supplies **20 annual actual-year** means/totals. Annual GHI mean bias is **{solar_bias:+.2f}%**; the reported mean-daily GHI MAE is **0.376 MJ/m²/day**. Annual averaging can hide compensating hourly errors, and annual GHI is rounded by JMA. The observatory differs from the Haneda airport station used above. No hourly solar accuracy is inferred from this annual check.
- **Singapore:** NEA's Changi series provides all **240 monthly rain totals**. The EPWs sum to **{sg.model_rain_mm.sum():,.1f} mm**, compared with **{sg.total_rainfall.sum():,.1f} mm** measured at Changi over twenty years: **{rain_bias:+.2f}%**. Monthly MAE is **76.93 mm** and r **0.634**. The city grid and Changi station differ spatially, so this is not evidence that the entire island has that exact bias.

![Direct national rain and solar checks](national_rain_and_solar.png)

## Extremes, annual consistency, and timing

Cold/hot subsets are defined from the station's pooled 5th/95th temperature percentiles, then evaluated on the corresponding matched hours. In the coldest 5%, Dublin's city EPW bias is **{cold.loc["IE", "bias"]:+.2f}°C**, Tokyo's **{cold.loc["JP", "bias"]:+.2f}°C**, and Sydney's **{cold.loc["AU", "bias"]:+.2f}°C**. Good annual means therefore do not establish accurate heating/cooling extremes. Full per-year, monthly and tail metrics are retained.

The −3…+3-hour temperature lag test has its highest correlation at zero in nine cities, including half-hour-offset New Delhi. New York peaks at +1 hour, with only a small change (r 0.987749→0.988156; MAE 1.151→1.144°C). This is flagged as residual phase/site sensitivity, not silently corrected. The API/calendar audit independently verifies the implemented UTC mapping; the observational lag test cannot establish whether the residual comes from model meteorology, spatial differences, report timing, or another source convention.

![Every city-year temperature error](temperature_by_year.png)

![Annual means](annual_temperature.png)
{colocated}
## Practical interpretation

The library is a working converter for the tested years and locations. The files can support exploratory annual energy studies **when these site/model errors are acceptable and the sensitive variables are reviewed**. The evidence does not support calling them measured station EPWs, design weather, certified EPWs, or an exact history of a particular building site. Wind-driven ventilation, heating/cooling extremes, precipitation-sensitive studies, and urban/coastal conditions need particular care.

**Not established:** global hourly DNI accuracy; opaque sky cover; cloud/visibility/weather-code fidelity; snow accuracy against instruments; globally accurate infrared or GHI/DHI; ground temperatures/design days; independent out-of-sample validation. ERA5 is a reanalysis informed by observations, and the station network may overlap its assimilation inputs. A comparison with those stations is not a fully independent withheld-station experiment. Estimated fields and EPW missing sentinels remain explicit.

## Free access and reproducibility

All downloads used public endpoints with **no API key, paid plan, purchase, or billing integration**. Open-Meteo's hosted free service is for non-commercial use and is rate-limited; it is not an unrestricted free commercial service. Data attribution remains required. The harness records conservative weighted requests and waits for the provider's documented/publicly implemented quota resets. This study is fully cached and resumable. These conclusions concern this exact source snapshot, not all future API versions or cities.

Run instructions: [validation/README.md](../../validation/README.md). Summary: [city_summary.csv](city_summary.csv), [validation_summary.json](validation_summary.json). Detailed results: [annual_metrics.csv](annual_metrics.csv), [pooled_metrics.csv](pooled_metrics.csv), [monthly_metrics.csv](monthly_metrics.csv), [national_source_metrics.csv](national_source_metrics.csv). Raw station gzip files, direct downloads, paired hourly data, input hashes, EPWs and provenance sidecars are retained locally.

Sources: [Open-Meteo archive documentation](https://open-meteo.com/en/docs/historical-weather-api), [free limits and usage terms](https://open-meteo.com/en/terms), [NOAA ISD and QC](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database), [ISD format](https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf), [Met Éireann data](https://www.met.ie/climate/available-data), [DWD radiation documentation](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/solar/DESCRIPTION_obsgermany_climate_10min_solar_en.pdf), [JMA Tokyo annual observations](https://www.data.jma.go.jp/stats/etrn/view/annually_s.php?prec_no=44&block_no=47662&year=&month=&day=&view=), [NEA Changi rainfall](https://data.gov.sg/datasets/d_b16d06b83473fdfcc92ed9d37b66ba58/view), [Environment Canada historical data](https://climate.weather.gc.ca/).

Weather credit: Open-Meteo; ERA5/ERA5-Land: Copernicus C3S/ECMWF; geocoding: GeoNames. Source data attribution and licence links accompany every EPW. Copyright Met Éireann; source https://www.met.ie/; CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Analysis filters/reformats the records and converts stated units. Met Éireann does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use. Additional measurement credit: NOAA NCEI and the local surface/aviation observing networks; DWD; JMA; Environment and Climate Change Canada; NEA Singapore. See `national_sources/sources_manifest.json` and observation sidecars for exact inputs.
"""
    (ROOT / "validation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("Report and four figures written;", len(integrity), "file hashes checked.")


if __name__ == "__main__":
    main()
