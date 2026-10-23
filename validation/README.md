# Reproducing the ten-country study

**Version scope:** committed summaries are historical 0.1.0/0.2.0 results. The
current library is 0.4.1. Rebuilding figures from committed CSVs is offline
(`python tools/build_figures.py`). Running the historical live harness against
a newer library produces a new study, not an exact recreation of the old
release. Use original archived library/input snapshots for historical replay.

## Version 0.2.0 supplemental-field study

The completed [updated summary](../docs/validation_v0_2.md)
tests all 200 actual city-years with the nine supplemental fields enabled. It
includes every accepted station value's raw-source audit, column-water values
and gaps, independent NREL SPA checks, and 200 new full-year EnergyPlus runs.
The library's runtime code was unchanged by the study. Default station selection
and strict QC leave major coverage gaps in some countries; see the report.

After installing the analysis dependencies and free EnergyPlus as described below,
run these sequentially from the project directory:

```shell
python validation/run_extended_study.py
python validation/finish_extended_study.py
python validation/check_extended_diagnostics.py
python validation/write_extended_report.py
```

The first command fetches ten original bulk ERA5 column-water responses, then
passes exact hourly slices through the normal conversion engine using a
validation-only input adapter. Original bulk URLs and hashes are retained.
This avoids thousands of redundant one-variable API requests. The free request
gate shares the baseline's reservation history; weights use the current official
`ForecastApiResult.calculateQueryWeight()` formula. Cached core weather is reused.
No paid endpoint, credential or billing is used.

Source-audit checkpoints make completed country checks resumable. Remove only the
specific study checkpoint(s) you intend to rerun when changing inputs or code;
otherwise the harness reuses completed results for that exact local snapshot.
Do not run several generation jobs against the same cache/checkpoints at once.
`finish_extended_study.py` can also run alongside one generation job: it starts
independent checks after each country's full twenty-year set is ready.

Local/national core metrics are reused **after exact equality of all 25 unaffected
columns is established in every new EPW**, and the retained observation inputs
are rechecked against their source hashes. This is a new conversion/coverage and
solver audit of current files, not a new independent observing campaign. The
200-file run omits optional snow, which remains covered separately in the original
default-option source checks. Supplemental raw/paired data, reports and EPWs are
under `output/validation_10cities_20years_v0_2/`. The compact results ZIP excludes
the large raw archives and EPW collection, which remain available locally.

## Original core-weather benchmark

The completed [report summary](../docs/validation.md)
covers 2005–2024 for Dublin, Frankfurt, Madrid, New York, Toronto, Tokyo,
New Delhi, Singapore, Sydney, and Cape Town: 200 actual city-years, not TMYs.
The runtime library was unchanged by this validation.

## Run

Install the library and separate analysis dependencies from the project root:

```shell
python -m pip install -e .
python -m pip install -r validation/requirements.txt
```

Run these **sequentially**. Downloads reuse the local cache and checkpoints.
Do not launch multiple network scripts simultaneously: the shared request
ledger is protected within one process, rather than across separate processes.

```shell
python validation/run_global_study.py
python validation/download_national_sources.py
python validation/analyze_global_study.py
python validation/check_national_sources.py
python validation/check_default_options.py
python validation/check_collocated_sites.py
python validation/check_global_energyplus.py
python validation/write_global_report.py
```

The compatibility check requires a separate free EnergyPlus installation.
The default is `C:\EnergyPlusV25-1-0`; set `ENERGYPLUS_INSTALL` to another
installation directory if needed. It uses the installation's supplied
`ExampleFiles/1ZoneUncontrolled.idf`. This study used EnergyPlus 25.1.
The report writer requires the compatibility results, preventing an unperformed
check from silently being described as complete.

The main run disables optional snow. Ten additional 2024 default-option files
check snow conversion and the three serializers. Three 2024 airport-coordinate
files are post-hoc diagnostics and do not replace the city-point benchmark.

## Comparison rules and limits

- Actual local station reports for all ten countries come from NOAA NCEI ISD.
  Original gzip files retain URL, station/year and SHA-256 sidecars.
- Toronto Pearson 2005 is absent from that archive. Twelve ECCC downloads
  supply the same site's actual year in local standard time UTC−5.
- Additional direct national checks cover Phoenix Park, Frankfurt, Tokyo and
  Changi. The Dublin Airport national download is excluded because its test-period
  indicators are all 111. The NOAA airport result is consequently qualified;
  Phoenix Park is a separate nearby station with valid provider indicators.
- Strict ISD QC accepts flags 1/5. Instantaneous values use the nearest valid
  report within 15 minutes. Rain requires an explicit one-hour accumulation,
  endpoint within one minute, acceptable accumulation conditions and temperature
  ≥3°C. Missing observations remain missing. Sparse rain is not declared validated.
- DWD radiation has a partial 2022 plus 2023–2024 measurement comparison;
  older Frankfurt records have sunshine duration but no measured radiation.
  JMA supplies a separate twenty-year **annual** solar comparison.
- Independent code reconstructs fields from raw API arrays without using the
  library's conversion helpers. This checks conversion, not meteorological accuracy.
- All calendars, leap years, file hashes and full-year solver record counts are
  checked. The report preserves solver warnings and quality exceptions.

Main outputs: `city_summary.csv`, annual/pooled/monthly/national metric CSVs,
`conversion_audit.json`, `energyplus_checks.json`, the report and four figures.
`paired/` holds matched values. `epw/` holds 200 EPWs and ten representative
CSV/TXT exports, each with provenance. All paths are under
`output/validation_10cities_20years/`.

## Free access and attribution

No paid source, API key, subscription or billing integration is used.
Open-Meteo's **hosted free service is non-commercial and rate-limited**.
The gate accounts for variables/time range and waits for quota resets.
Allow headroom for other applications sharing the same public IP.

Upstream files may be revised. `national_sources/sources_manifest.json`,
observation sidecars and the API cache identify the exact snapshot. Reference
station metadata do not reconstruct every historical relocation. This is an
observational benchmark and conversion audit, not a withheld-station experiment
or EPW certification.

Credit Open-Meteo; Copernicus C3S/ECMWF ERA5/ERA5-Land; GeoNames; NOAA NCEI
and local observing networks; Met Éireann; DWD; JMA; Environment and Climate
Change Canada; and NEA Singapore. Retain the supplied licence and attribution
information when sharing data.
