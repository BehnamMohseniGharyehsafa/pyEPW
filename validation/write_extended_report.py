"""Write the completed v0.2.0 observational report, figures and compact bundle."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from extended_common import ROOT, BASE, CITIES, YEARS

os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

COUNTRIES = {
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
ORDER = [c["country"] for c in CITIES]


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(map(str, row)) + " |" for row in rows],
        ]
    )


def main():
    audit = json.loads((ROOT / "conversion_audit.json").read_text(encoding="utf-8"))
    energy = json.loads((ROOT / "energyplus_checks.json").read_text(encoding="utf-8"))
    solar = pd.read_csv(ROOT / "solar_reference_checks.csv")
    fields = pd.read_csv(ROOT / "field_coverage.csv")
    city = pd.read_csv(ROOT / "city_summary.csv")
    summary_country = pd.read_csv(ROOT / "stations.csv").set_index("country").city.to_dict()
    annual = pd.read_csv(ROOT / "annual_metrics.csv")
    supplemental = pd.read_csv(ROOT / "supplemental_pooled_metrics.csv")
    diagnostics = json.loads((ROOT / "diagnostics.json").read_text(encoding="utf-8"))
    assert len(audit) == len(energy) == len(solar) == 200
    assert all(
        a["source_conversion_pass"]
        and a["calendar_pass"]
        and a["column_water_source_pass"]
        and a["station_source_pass"]
        and a["core_columns_identical_to_original_study"]
        for a in audit
    )
    assert all(e["pass"] and e["severe_errors"] == 0 for e in energy)
    assert sum(a["hours"] for a in audit) == 1753200
    reference_integrity = []
    for path in sorted((BASE / "observations").glob("*.gz")):
        provenance = json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == provenance["sha256"]
        reference_integrity.append({"file": str(path), "sha256": digest, "url": provenance["url"], "pass": True})
    national_manifest = json.loads((BASE / "national_sources/sources_manifest.json").read_text(encoding="utf-8"))
    for source in national_manifest["files"]:
        path = BASE / "national_sources" / source["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == source["sha256"]
        reference_integrity.append({"file": str(path), "sha256": digest, "url": source["source_url"], "pass": True})
    (ROOT / "reference_input_integrity.json").write_text(json.dumps(reference_integrity, indent=2), encoding="utf-8")
    # Inspect all current-version serialized sample formats, including the
    # analysis-specific missing/range transformation.
    formats = []
    for cp in (ROOT / "checkpoints").glob("*_2024.json"):
        checkpoint = json.loads(cp.read_text())
        epw = Path(checkpoint["path"])
        import csv

        with epw.open(newline="") as stream:
            rows = list(csv.reader(stream))[8:]
        for extension in (".csv", ".txt"):
            path = epw.with_suffix(extension)
            with path.open(encoding="utf-8", newline="") as stream:
                records = list(
                    csv.reader(
                        (line for line in stream if not line.startswith("#")),
                        delimiter="\t" if extension == ".txt" else ",",
                    )
                )[1:]
            assert rows == records
            formats.append({"country": checkpoint["country"], "format": extension, "matches_epw": True})
        analysis_path = epw.with_name(epw.stem + "_analysis.csv")
        analysis_meta = json.loads(Path(str(analysis_path) + ".metadata.json").read_text(encoding="utf-8"))
        with analysis_path.open(newline="") as stream:
            records = list(csv.reader(stream))[1:]
        assert len(records) == len(rows)
        for value in analysis_meta["zenith_luminance_outside_epw_range"]:
            assert abs(float(records[value["row"]][19]) - value["zenith_luminance_cd_m2"]) <= 0.051
        for i, row in enumerate(rows):
            for col, limit in ((24, 9999), (25, 99999), (28, 999)):
                if float(row[col]) >= limit:
                    assert records[i][col] == ""
        formats.append({"country": checkpoint["country"], "format": "analysis_csv", "range_and_missing_checks": True})
    assert len(formats) == 30
    (ROOT / "format_checks.json").write_text(json.dumps(formats, indent=2), encoding="utf-8")
    integrity = []
    for path in sorted((ROOT / "epw").iterdir()):
        if path.suffix not in (".epw", ".csv", ".txt"):
            continue
        meta = json.loads(Path(str(path) + ".metadata.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == meta["output_sha256"]
        integrity.append({"file": path.name, "sha256": digest, "pass": True})
    (ROOT / "file_integrity_audit.json").write_text(json.dumps(integrity, indent=2), encoding="utf-8")
    totals = fields.groupby(["country", "column"])[["valid_hours", "missing_hours"]].sum()
    totals["coverage_percent"] = 100 * totals.valid_hours / (totals.valid_hours + totals.missing_hours)
    coverage = totals.coverage_percent.unstack().loc[ORDER]
    coverage.to_csv(ROOT / "coverage_by_city.csv")
    for code, name in COUNTRIES.items():
        row = city.country == name
        for key in ("visibility_km", "ceiling_height_m", "zenith_luminance_cd_m2", "precipitable_water_mm"):
            city.loc[row, key + "_coverage_percent"] = coverage.loc[code, key]
    city.to_csv(ROOT / "extended_city_summary.csv", index=False)
    station_values = sum(sum(a["station_values_checked"].values()) for a in audit)
    warning_runs = sum(e["warning_messages"] > 0 for e in energy)
    zenith_outside = sum(a["zenith_values_preserved_outside_epw_range"] for a in audit)
    water_missing = int(fields.loc[fields.column == "precipitable_water_mm", "missing_hours"].sum())
    summary = {
        "package_version": "0.2.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "years": list(YEARS),
        "cities": CITIES,
        "epw_files": 200,
        "hourly_records": 1753200,
        "source_and_calendar_audits_passed": 200,
        "station_source_values_audited": station_values,
        "energyplus_full_year_runs_passed": 200,
        "energyplus_severe_errors": 0,
        "energyplus_runs_with_warnings": warning_runs,
        "solar_midpoints_compared": int(solar.midpoint_samples.sum()),
        "solar_integrated_hours_compared": int(solar.hourly_energy_samples.sum()),
        "maximum_solar_zenith_difference_degrees": float(solar.max_zenith_error_degrees.max()),
        "maximum_hourly_extraterrestrial_horizontal_difference_wh_m2": float(
            solar.max_horizontal_energy_error_wh_m2.max()
        ),
        "precipitable_water_missing_hours": water_missing,
        "modeled_zenith_values_outside_epw_range": zenith_outside,
        "runtime_library_modified_during_study": False,
        "core_metrics_reuse_basis": "Exact equality of every non-supplemental/non-flag column in all 200 current-version outputs.",
        "paid_services_used": False,
        "conclusion": "Core conversion is correct for this snapshot; meteorological accuracy varies, and supplemental coverage/validation is incomplete.",
    }
    (ROOT / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    labels = [summary_country[c] for c in ORDER]
    keyed = city.set_index("city").loc[labels]
    figure, axes = plt.subplots(1, 2, figsize=(12, 5.8))
    y = np.arange(10)
    axes[0].barh(y, keyed.temperature_mae_c, color="#187b80")
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Hourly temperature mean absolute error (°C)")
    axes[0].set_xlim(0, 2.15)
    axes[1].barh(y, keyed.wind_bias_percent, color="#bd6938")
    axes[1].set_yticks(y, labels)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Wind difference of matched means (%)")
    axes[1].axvline(0, color="#555", lw=0.8)
    axes[1].set_xlim(-61, 10)
    for i, value in enumerate(keyed.temperature_mae_c):
        axes[0].text(value + 0.025, i, f"{value:.2f}", va="center")
    for i, value in enumerate(keyed.wind_bias_percent):
        axes[1].text(
            value - 1 if value < 0 else value + 1, i, f"{value:+.1f}", va="center", ha="right" if value < 0 else "left"
        )
    figure.suptitle("Version 0.2.0 · 2005–2024 · city-point ERA5 versus local station reports", weight="bold")
    figure.text(
        0.02,
        0.015,
        "200 actual city-years. Airport stations are 9–22 km away. Core data verified identical to the original study snapshot.",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.045, 1, 0.95))
    figure.savefig(ROOT / "core_weather_accuracy.png", dpi=180)
    plt.close(figure)
    columns = [
        "extraterrestrial_horizontal_radiation_wh_m2",
        "extraterrestrial_direct_normal_radiation_wh_m2",
        "global_horizontal_illuminance_lux",
        "direct_normal_illuminance_lux",
        "diffuse_horizontal_illuminance_lux",
        "zenith_luminance_cd_m2",
        "visibility_km",
        "ceiling_height_m",
        "precipitable_water_mm",
    ]
    xlabels = [
        "ET horizontal",
        "ET direct normal",
        "Global illuminance",
        "Direct illuminance",
        "Diffuse illuminance",
        "Zenith luminance",
        "Visibility",
        "Ceiling",
        "Column water",
    ]
    figure, ax = plt.subplots(figsize=(12, 6.4))
    image = ax.imshow(coverage[columns], vmin=0, vmax=100, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(9), xlabels, rotation=30, ha="right")
    ax.set_yticks(range(10), labels)
    for i in range(10):
        for j, column in enumerate(columns):
            value = coverage.loc[ORDER[i], column]
            ax.text(
                j, i, f"{value:.1f}", color="white" if value > 75 else "#1b3035", ha="center", va="center", fontsize=9
            )
    figure.colorbar(image, ax=ax, label="Canonical EPW non-missing hours (%)")
    ax.set_title(
        "Supplemental-field coverage across twenty actual years\nNumerical completeness does not establish observed accuracy",
        weight="bold",
    )
    figure.text(
        0.015,
        0.015,
        "Photometry includes modeled nighttime zeros. Zenith range overflow is retained in metadata/analysis CSV. Station QC gaps are not filled.",
        fontsize=8.5,
    )
    figure.tight_layout(rect=(0, 0.045, 1, 1))
    figure.savefig(ROOT / "supplemental_coverage.png", dpi=180)
    plt.close(figure)
    heat = annual[annual.variable == "temperature_c"].pivot(index="country", columns="year", values="mae").loc[ORDER]
    figure, ax = plt.subplots(figsize=(13, 5.4))
    image = ax.imshow(heat, aspect="auto", vmin=0, vmax=max(2.5, heat.max().max()), cmap="YlOrRd")
    ax.set_yticks(range(10), labels)
    ax.set_xticks(range(20), heat.columns, rotation=55)
    ax.set_title("Hourly temperature MAE for each city and year · 200 comparisons", weight="bold")
    figure.colorbar(image, ax=ax, label="MAE (°C)")
    figure.tight_layout()
    figure.savefig(ROOT / "temperature_by_year.png", dpi=180)
    plt.close(figure)

    result_rows = []
    for code, row in zip(ORDER, keyed.itertuples()):
        result_rows.append(
            [
                summary_country[code],
                COUNTRIES[code],
                f"{row.temperature_mae_c:.2f}",
                f"{row.wind_bias_percent:+.1f}%",
                f"{coverage.loc[code, 'visibility_km']:.1f}%",
                f"{coverage.loc[code, 'ceiling_height_m']:.1f}%",
            ]
        )
    alt = next(d for d in diagnostics if d["kind"] == "explicit_station")
    status = [
        [
            "Extraterrestrial radiation (2)",
            "Independent NREL SPA geometry/integration reference in every city/year",
            "Astronomical calculation; not a weather observation",
        ],
        [
            "Illuminance (3) and zenith luminance",
            "Published numerical model checks, complete calendar/range/finite-value audit",
            "No twenty-year local photometer comparison; empirical estimates",
        ],
        [
            "Precipitable water",
            "All valid values and gaps traced to original ERA5 column-water arrays",
            "Source fidelity verified; local full-column observational accuracy unestablished",
        ],
        [
            "Visibility and ceiling",
            "Every accepted value traced to raw GHCNh; original local ISD reports compared",
            "Archives overlap underlying reports; censoring and unlimited categories handled separately",
        ],
    ]
    supplemental_rows = []
    for code in ORDER:
        record = [summary_country[code]]
        for variable in ("visibility_km", "ceiling_height_m"):
            metric = supplemental[(supplemental.country == code) & (supplemental.variable == variable)].iloc[0]
            record.extend([f"{int(metric['n']):,}", f"{metric.mae:.3f}" if metric["n"] >= 2 else "unvalidated"])
        supplemental_rows.append(record)
    pd.DataFrame(status, columns=["fields", "checks", "limit"]).to_csv(
        ROOT / "variable_validation_status.csv", index=False
    )
    report = f"""# Ten-country, twenty-year validation — version 0.2.0

Completed {datetime.now(timezone.utc).date().isoformat()}. **200 actual-year EPWs,
1,753,200 hourly records, 2005–2024. No TMY data and no paid services.**

**The core conversion passes; local weather accuracy varies. The nine supplemental
fields are not uniformly complete or observationally validated across the world.**
The runtime library was unchanged during this study. No bias correction was fitted.

## City results

Temperature MAE is the hourly mean absolute difference from the local station.
Wind bias is the difference of matched means relative to the station mean, not
an hourly percentage error. Station coverage is the proportion of all EPW hours
with accepted visibility/ceiling under the library's default rules.

{table(["City", "Country", "Temperature MAE °C", "Wind mean bias", "Visibility coverage", "Ceiling coverage"], result_rows)}

![Core observational comparisons](core_weather_accuracy.png)

Airport reference stations are about 9–22 km from the city coordinates. Error
includes reanalysis error, exposure, elevation, coastal/urban differences and
observation timing. The ERA5 assimilation network may overlap the observing
network: this is not a withheld-station experiment.

## What was tested

- **200/200** full-year calendars and independent core source/unit/time audits passed.
- All 25 columns outside supplemental fields and source flags match the original
  benchmark EPWs exactly. The previously archived station/national comparisons
  therefore apply to the new outputs without changing their paired weather values.
  Exact-value and source-file hash checks justify reuse; no new national download
  or new independent field campaign is implied.
- **{station_values:,} accepted visibility/ceiling values** were independently
  checked against raw GHCNh reports, accepted source/QC, timing and source hashes.
  Missing observations were not filled. Original ISD comparisons and pair counts
  are in `supplemental_annual_metrics.csv` and `supplemental_pooled_metrics.csv`.
- Every precipitable-water value/gap was compared with raw ERA5 column-water arrays.
- All {len(reference_integrity)} retained local/national observation input files
  matched their original SHA-256 provenance before reusing the comparisons.
- Independent NREL SPA checks cover **{int(solar.midpoint_samples.sum()):,} hourly
  midpoints** and **{int(solar.hourly_energy_samples.sum()):,} integrated seasonal hours**.
  Maximum geometric zenith difference: **{solar.max_zenith_error_degrees.max():.4f}°**;
  maximum hourly extraterrestrial-horizontal difference: **{solar.max_horizontal_energy_error_wh_m2.max():.3f} Wh/m²**.
- **200/200 EnergyPlus 25.1 actual-year runs completed**, with expected hourly record
  counts and zero severe errors. **{warning_runs} runs had warnings**, retained in
  `energyplus/*/eplusout.err`. Solver success is a compatibility result.
- Ten 2024 standard CSV/TXT pairs equal their EPW records. Ten analysis exports
  passed missing-cell and luminance-restoration checks. All output hashes passed.

The original 48 offline tests had passed before this run; runtime code remained
unchanged. The new validation harness is separate from the library.

## Supplemental fields: completeness and evidence

![Supplemental coverage](supplemental_coverage.png)

{table(["Fields", "Checks performed", "Limit"], status)}

Reported station-field comparisons (finite ceilings only; see independence and
censoring limits below):

{table(["City", "Visibility pairs", "Visibility MAE km", "Finite-ceiling pairs", "Ceiling MAE m"], supplemental_rows)}

There are **{water_missing:,} missing column-water hours**. The bulk source returns
nulls in January–June 2024; small direct monthly API requests confirmed the gap
for Frankfurt. The library correctly exports missing codes. The exact original
responses, URLs and SHA-256 hashes are retained, so future provider revisions
can be distinguished from this snapshot.

There are **{zenith_outside:,} modeled zenith-luminance values outside EPW's valid
non-missing range**. All are preserved in metadata; the ten sample analysis CSVs
restore the applicable values without clipping. The API supports analysis export
for any requested year.
Three illuminance fields contain modeled daylight values and legitimate nighttime
zeros. Numerical completeness does not establish their meteorological accuracy.
No local twenty-year photometer dataset was used.

Visibility values qualified as at least 10 km are excluded from numeric visibility
error metrics. Other reporting caps may remain in historical observations, so
reported-value agreement is not exact uncensored visibility accuracy. Unlimited
and cirroform ceilings are categories; finite-height MAE excludes those categories.
Category-pair counts and agreement are retained in `conversion_audit.json`.
GHCNh and ISD often contain the same underlying reports: very small station-field
errors can establish transcription consistency, not independent sensor validation.

### Selection and QC limitations found

The default bounded aviation-name search can overlook useful records with names
that lack its airport keywords. In a separate **post-hoc Madrid 2024** diagnostic,
explicit Barajas station `SPMU0098221` provided **{alt["explicit_visibility_hours"]:,}
visibility hours and {alt["explicit_ceiling_hours"]:,} ceiling hours**, versus
{alt["default_visibility_hours"]:,} and {alt["default_ceiling_hours"]:,} with defaults.
This diagnostic does not replace the declared default 200-file results. A more
complete automatic candidate-discovery strategy is warranted.

Some national-source records contain numeric values but blank or unsupported
source-specific QC. The current strict policy rejects those values. Zero accepted
coverage therefore does not prove that no national observations exist. Toronto,
Cape Town and Sydney show that the supplement cannot currently promise global
coverage. Do not silently weaken QC or fill gaps to advertise completeness.

IGRA's published derived precipitable-water product was considered but excluded
as a direct full-column reference: it integrates only surface to 500 hPa, unlike
the ERA5 full-column field. No mismatched-column accuracy score is reported.

## Local/national observation provenance

Local airport reports for all ten countries come from NOAA NCEI's international
archive. **This is not ten direct national-website downloads.** Direct national
checks in the retained benchmark additionally use Met Éireann, DWD, JMA, ECCC
and Singapore NEA, with their actual temporal coverage retained.

- Toronto Pearson 2005 uses twelve ECCC downloads because that ISD year is absent.
- Met Éireann's direct Dublin Airport test-period indicators were all 111 and were
  excluded. A separate accepted-quality Phoenix Park twenty-year temperature
  comparison gave MAE 0.943°C and bias +0.536°C. NOAA airport results remain qualified.
- Singapore NEA's 240 monthly Changi rain totals showed **+24.87%** EPW rain bias.
- JMA Tokyo annual GHI showed **+2.53%** mean annual bias over twenty years.
- DWD's measured radiation check covers partial 2022 and 2023–2024. This does not
  establish twenty-year hourly solar or global DNI accuracy. Sparse ISD rain was
  not treated as a representative global precipitation validation.

No direct twenty-year local observations established photometry, full-column
water, global DNI, opaque cloud, snow or modeled infrared accuracy for all cities.
The main 200-file run omitted optional snow; the earlier ten default-snow source
checks remain separate and do not validate measured snow.

![Every city/year temperature result](temperature_by_year.png)

## Practical conclusion

The library correctly converts this source snapshot into actual-year EPW files.
It does **not** deliver 100% accurate site weather, nor nine fully validated
supplemental fields worldwide. Wind is substantially low in several cities;
temperature errors and extremes remain site-dependent. Review the variable-specific
errors and coverage for the intended use. `require_fields=[...]` can enforce
canonical completeness; it cannot certify weather accuracy.

Reproduce with [the validation instructions](../../validation/README.md).
Key files: [city summary](extended_city_summary.csv), [coverage](coverage_by_city.csv),
[annual metrics](annual_metrics.csv), [supplemental metrics](supplemental_pooled_metrics.csv),
[summary JSON](validation_summary.json). All 200 EPWs and provenance sidecars are
in `epw/`; original archived observations remain in the preserved baseline folder.

Sources: [Open-Meteo archive](https://open-meteo.com/en/docs/historical-weather-api),
[free service terms](https://open-meteo.com/en/terms),
[NOAA GHCNh](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly),
[NOAA ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database),
[IGRA variable definitions](https://www.ncei.noaa.gov/pub/data/igra/derived/igra2-derived-format.txt),
[Met Éireann](https://www.met.ie/climate/available-data),
[DWD](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/),
[JMA](https://www.data.jma.go.jp/stats/etrn/view/annually_s.php?prec_no=44&block_no=47662&year=&month=&day=&view=),
[ECCC](https://climate.weather.gc.ca/), [Singapore NEA](https://data.gov.sg/datasets/d_b16d06b83473fdfcc92ed9d37b66ba58/view).

Credit Open-Meteo; Copernicus C3S/ECMWF ERA5; GeoNames; NOAA NCEI and originating
national observing networks; Met Éireann; DWD; JMA; ECCC; Singapore NEA; pvlib/NREL
for the separate numerical solar reference. No paid source, key or billing was used.
Open-Meteo's hosted free service remains non-commercial and rate-limited.
"""
    (ROOT / "validation_report.md").write_text(report, encoding="utf-8")
    bundle = ROOT / "validation_results.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.iterdir()):
            if path.is_file() and path.suffix in (".md", ".csv", ".json", ".png"):
                archive.write(path, path.name)
    print(json.dumps(summary, indent=2))
    print("Report:", ROOT / "validation_report.md")
    print("Compact results bundle (EPWs/raw observations retained separately):", bundle)


if __name__ == "__main__":
    main()
