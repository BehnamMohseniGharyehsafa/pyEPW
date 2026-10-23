# Version 0.2.0 validation: 2005–2024

Completed on 23 October 2026: **200 enriched actual-year EPWs and 1,753,200 hours**
for Dublin, Frankfurt, Madrid, New York City, Toronto, Tokyo, New Delhi,
Singapore, Sydney and Cape Town. No TMY data or paid services were used.

**Core conversion is correct for this snapshot. Meteorological accuracy and
supplemental-field completeness vary substantially.**

All 200 calendars/core source audits passed. Every valid column-water value and
every missing hour matched the original ERA5 arrays. All 1,950,786 accepted
visibility/ceiling values were traced to their original quality-filtered GHCNh
reports. Independent NREL SPA checks covered all 1,753,200 hourly midpoints and
19,200 seasonal integrated hours; maximum zenith difference was 0.0177° and
maximum hourly extraterrestrial-horizontal energy difference was 0.342 Wh/m².

All 200 new EnergyPlus 25.1 actual-year runs completed with the expected number
of hourly records and zero severe errors. **37 runs had warnings**; these remain
in the retained logs. Ten standard CSV/TXT pairs matched EPW records; ten analysis
CSV exports passed missing/range checks. Output and reference-input hashes passed.

Every one of the 25 columns outside supplemental fields and source flags matched
the original benchmark exactly in all 200 files. The [original local/national
metrics](validation.md) consequently apply to these new outputs: temperature
MAE ranges from 0.86°C to 1.74°C; mean wind differences range from −48.5% to +2.0%.
Station distances, observation coverage and direct-national exceptions remain
material. This is not a withheld-station experiment.

## Coverage limits found

| City | Accepted visibility hours | Accepted ceiling hours |
|---|---:|---:|
| Dublin | 99.8% | 96.9% |
| Frankfurt | 87.2% | 53.0% |
| Madrid | 84.7% | 38.6% |
| New York City | 99.9% | 100.0% |
| Toronto | 0.0% | 0.0% |
| Tokyo | 52.6% | 33.7% |
| New Delhi | 93.1% | 74.4% |
| Singapore | 99.7% | 98.2% |
| Sydney | 0.3% | 0.8% |
| Cape Town | under 0.1% | under 0.1% |

These are completeness percentages under default selection/QC, not accuracy
scores. Numeric national-source records with unsupported/blank QC are rejected;
zero accepted coverage does not prove that no observations exist. The bounded
airport-name search also misses useful records. In a separate Madrid 2024
diagnostic, explicit Barajas station `SPMU0098221` increased visibility coverage
from 4,409 to 8,495 hours and ceiling from 2,928 to 4,872 hours. It did not replace
the default benchmark or modify runtime code.

There are 43,681 missing column-water hours, chiefly January–June 2024. Direct
monthly API probes confirmed Frankfurt's January gap and valid July data.
The library preserves those gaps. The 75,408 modeled zenith-luminance values
outside EPW's valid range remain in metadata; the ten sample analysis CSVs restore
their applicable values. Illuminance and
luminance have no local twenty-year photometer comparison; source/model fidelity
does not establish their observational accuracy.

The main run omits optional snow. Global DNI, opaque cloud, snow, modeled infrared
and full-column water observational accuracy remain unestablished for all ten
cities. Local airport reports for all countries are archived by NOAA; direct
national checks cover five countries with the temporal limits in the report.

See the [summary CSV](data/benchmark_v0_2_city_summary.csv),
[coverage CSV](data/benchmark_v0_2_coverage.csv),
[snapshot provenance](data/benchmark_provenance.json) and
[reproduction instructions](../validation/README.md). All 200 files and complete
provenance are retained locally in the excluded study's `epw/` folder. The full
local report and logs are not links to files shipped in this repository.
