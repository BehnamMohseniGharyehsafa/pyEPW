# Ten-country validation: 2005–2024

Completed on 23 October 2026 with local package version 0.1.0. The study generated
200 actual-year EPWs containing 1,753,200 hourly records. No TMY data were used.
Runtime library code was unchanged by the study.

**Conversion passed; meteorological accuracy varies materially by location and
variable.** Correct conversion does not establish station-level accuracy.

| City | Country | Hourly temperature MAE °C | Mean wind difference vs station |
| --- | --- | --- | --- |
| Dublin | Ireland | 1.08 | −16.9% |
| Frankfurt | Germany | 0.86 | −17.0% |
| Madrid | Spain | 1.04 | −20.8% |
| New York | USA | 1.15 | −38.0% |
| Toronto | Canada | 1.09 | −17.5% |
| Tokyo | Japan | 1.33 | −35.6% |
| New Delhi | India | 1.20 | +2.0% |
| Singapore | Singapore | 1.15 | −1.1% |
| Sydney | Australia | 1.74 | −48.5% |
| Cape Town | South Africa | 1.17 | −18.4% |

The comparisons use ERA5 at the city coordinates and local airport stations
roughly 9–22 km away. Differences include model error, site elevation/exposure,
coastal and urban effects, and observation timing/precision. Temperature
observation coverage is 92.5–99.9%; missing observations were not filled.
Wind differences above are differences of matched means, not hourly error bounds.

## Checks completed

- 200/200 complete actual-year calendars and independent source-conversion audits
  passed, including leap days, fixed standard offsets and New Delhi's UTC+5:30.
- 200/200 EnergyPlus 25.1 actual-year runs completed with the expected hourly
  record counts and zero severe errors. **37 runs logged psychrometric warnings**;
  they are retained and are not presented as warning-free or building-model approvals.
- The main run explicitly omitted optional snow. Ten additional default-option
  2024 exports passed snow source-conversion checks; this is not validation against
  measured snow. All ten CSV/TXT sample pairs match their EPW records exactly.
- 31 existing offline library tests passed. Output files match their provenance hashes.

## Observation sources and exceptions

Actual station reports for all countries came from
[NOAA NCEI ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database).
This is an international archive of local station observations, **not ten direct
national-website downloads**. Direct checks additionally used Met Éireann, DWD,
JMA, Singapore NEA and ECCC.

Toronto Pearson 2005 was unavailable in the NOAA archive; twelve ECCC downloads
supplied that same site's actual 2005 measurements. Met Éireann's direct Dublin
Airport download marked every test-period record with indicator 111, so it was
excluded. NOAA's separately quality-checked airport comparison is qualified in
light of that discrepancy. A separate accepted-quality Phoenix Park comparison
over twenty years gave temperature MAE 0.943°C and bias +0.536°C.

[NEA's Changi series](https://data.gov.sg/datasets/d_b16d06b83473fdfcc92ed9d37b66ba58/view)
showed Singapore's city-point EPW rain totals to be **24.87% higher** over all
240 months. Sparse hourly rain in ISD was not treated as a representative global
rain benchmark. Explicit accumulations, quality flags and possible snowfall
contamination were checked.

[JMA Tokyo annual observations](https://www.data.jma.go.jp/stats/etrn/view/annually_s.php?prec_no=44&block_no=47662&year=&month=&day=&view=)
gave a **+2.53% mean annual GHI bias** across twenty actual years. DWD Frankfurt
provided a separate hourly GHI/DHI/infrared check for partial 2022 and 2023–2024;
older station files contained no measured radiation. Annual agreement does not
establish hourly solar or DNI accuracy.

Three 2024 requests at airport coordinates improved temperature agreement and
removed New York's small city-point lag preference. Sydney still substantially
underestimated airport wind. These post-hoc diagnostics do not replace the main results.

## Use of the results

These files can support exploratory annual energy studies when the documented
errors are acceptable. Wind-driven ventilation, cold/hot extremes, precipitation,
and site-specific urban/coastal conditions require further review. They should
not be labelled measured station EPWs, certified weather, or design weather.
The station network may overlap ERA5 assimilation inputs; this is not an
independent withheld-station experiment. Global DNI, opaque sky cover, snow and
estimated infrared accuracy remain unestablished.

All sources were free public endpoints without API keys or billing. Open-Meteo's
hosted free service remains **non-commercial and rate-limited**; source attribution
is required. The study stayed within conservative weighted call budgets.

The public [city summary](data/benchmark_v0_1_city_summary.csv) and
[snapshot provenance](data/benchmark_provenance.json) preserve compact results.
The full local report, raw/paired records and all EPWs are retained in the
excluded `output/validation_10cities_20years/` folder. The
[reproduction scripts and instructions](../validation/README.md) regenerate the
study from public sources and retain input hashes and provenance.
