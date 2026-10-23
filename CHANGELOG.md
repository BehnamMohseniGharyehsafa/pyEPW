# Changelog

## 0.4.1 — 2026-10-23

- Prepared the public GitHub repository with architecture/UML diagrams,
  continent examples, source-attributed figures and compact reproducible results.
- Added per-provider export attribution, source licence scopes, NASA API
  references, citation metadata and publication/service-use documentation.
- Added maintainer metadata, repository URLs, community/security guidance,
  issue forms, offline CI, documentation checks and GitHub release automation.
- Preserved weather calculations and missing-data policy. Historical global
  validation remains explicitly labelled as a version 0.2.0 snapshot.

## 0.4.0 — 2026-10-23

- Renamed the canonical import to `pyEPW` and the project brand to pyEPW.
- Named the installable distribution `pyepw-openmeteo` to distinguish it from
  the unrelated, existing `pyepw` project on PyPI. No public upload was made.
- Added `pyEPW` and `python -m pyEPW` command-line entry points; retained the
  previous import, submodule/class identities, command and cache environment
  variable for compatibility.
- Added `PyEPWError` as the base exception name, retaining `OpenMeteoEPWError`
  as an identical alias. Added `PYEPW_CACHE` as the preferred cache override.
- Updated packaging, help, examples, documentation, CI paths and provenance
  package names. Weather calculations and existing weather outputs are unchanged.

## 0.3.0 — 2026-10-23

- Added ERA5-derived days since snowfall with prior-year history, gap invalidation
  and the documented 88-or-more code; no snow-depth heuristic.
- Added valid hourly NASA POWER albedo with UTC interval alignment, source hashes
  and preservation of undefined/nighttime values.
- Expanded nearby GHCNh discovery and added gap-only NOAA ISD and optional IEM
  published METAR supplements. NOAA QC and minimal METAR archive QC stay distinct.
- Retained original compressed ISD sources, report digests and per-hour lineage.
- Added `is_complete`, `missing_fields`, `require_complete`, source controls and
  matching CLI options. No unsupported fields are filled with guessed numbers.
- Audited regenerated Cork 2025 against downloaded source records. The prior
  ten-country/twenty-year study remains a version 0.2.0 study.

## 0.2.0 — 2026-10-23

- Added hour-integrated astronomical extraterrestrial radiation, published Perez
  illuminance/zenith-luminance models, and ERA5 total-column precipitable water.
- Added optional NOAA GHCNh visibility and ceiling observations with source-aware
  QC, reported-position distance limits, bounded time matching and per-hour lineage.
- Added field coverage, quality reports, station discovery, strict required-field
  checks, CLI controls, and an offline `help("fields")` topic.
- Added `to_analysis_csv()` with blank missing values and preserved full-range
  modeled luminance; canonical formats retain EPW ranges and sentinel codes.
- Retained basic conversion through `include_additional_fields=False`; the older
  ten-country benchmark explicitly selects it for reproducibility.
- Added numerical-reference, source-QC, range and export checks. Supplemental
  photometry remains empirical and has not been validated with local photometers.

## 0.1.0 — 2026-10-23

- Introduced the typed `EPW(city, year, format)` Python API.
- Added EPW, column-labelled CSV, and tab-delimited TXT export from one dataset.
- Added online city lookup and an optional downloadable GeoNames cities500 catalog.
- Added country filtering, city-name help, and complete catalog CSV export.
- Retained actual-year calendar handling, leap days, fixed standard time,
  fractional UTC-offset resampling, and rejection of missing core weather data.
- Added a command-line entry point, user cache, logging, typed exceptions,
  per-format provenance, packaging metadata, tests, examples and CI configuration.

This initial package has not been uploaded to PyPI. Local distribution files
can be installed and shared without a package-index account.
