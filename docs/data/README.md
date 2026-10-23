# Figure inputs and provenance

Only compact, derived summaries are committed. Bulk weather, local caches,
station archives and all private working paths are excluded from Git.

## Six-continent 2024 gallery

- `continents_2024_monthly.csv`: 12 monthly summaries for each of six actual-year
  city files. Mean temperature and daily GHI profiles are calculated directly
  from the generated canonical records. No EPW missing code is averaged.
- `continents_2024_coverage.csv`: all 29 weather fields' available/missing-hour
  counts. Completeness is separate from measurement accuracy.
- `continents_2024_sources.json`: requested city coordinates, package version,
  source requests, source-specific attribution, offsets and output hashes.

The figures use **ERA5 via Open-Meteo**, CC BY 4.0, plus GeoNames city locations.
Credit [Open-Meteo](https://open-meteo.com/), Copernicus C3S/ECMWF ERA5 and
[GeoNames](https://www.geonames.org/). Data have been converted to EPW and
aggregated by calendar month. NASA/NOAA/IEM supplements can be present in the
local generated files but are not inputs to these temperature/GHI plots.

## Historical benchmark

The `benchmark_v0_1_*` and `benchmark_v0_2_*` CSVs are exact copies of the compact
2005–2024 study summaries. `benchmark_provenance.json` preserves their hashes and
version, plus counts derived from the retained EnergyPlus check results.
These snapshots do not certify the current release's global completeness.

Observation references: NOAA NCEI ISD/GHCNh and originating station networks;
direct national exceptions are documented in [validation sources](../validation_sources.md).
The figures show derived errors/coverage; no bulk third-party observation files
are redistributed here. Preserve these source references with reused figures.

Original chart code and styling are under the repository's MIT licence. The
underlying products retain their own terms in [DATA_SOURCES.md](../../DATA_SOURCES.md).
Figures are built by `python tools/build_figures.py` using these exact CSVs.
