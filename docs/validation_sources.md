# Sources in the historical validation study

The runtime providers are listed in [DATA_SOURCES.md](../DATA_SOURCES.md).
The version 0.1.0/0.2.0 research harness additionally downloaded the following
national records for limited comparisons. The public repository contains derived
summary metrics and source links, not their bulk raw observation archives.

| Provider | Comparison and source | Attribution / conditions |
|---|---|---|
| Met Éireann | Phoenix Park accepted-quality records; Dublin Airport excluded because of provider indicator 111 | [Open-data conditions](https://www.met.ie/about-us/specialised-services/open-data), generally CC BY 4.0; dataset exceptions must be checked. Copyright Met Éireann; source met.ie; transformed into comparison metrics, not official Met Éireann outputs. |
| Deutscher Wetterdienst | Frankfurt observations and partial 2022 plus 2023–2024 radiation | [DWD CDC archive](https://opendata.dwd.de/climate_environment/CDC/), [DWD copyright/use conditions](https://www.dwd.de/EN/service/copyright/copyright_node.html). Credit DWD and identify the station/time subset. |
| Japan Meteorological Agency | Tokyo annual solar comparison, 2005–2024 | [JMA observations](https://www.data.jma.go.jp/stats/etrn/), [JMA terms](https://www.jma.go.jp/jma/en/copyright.html). Credit JMA and identify modifications; do not imply endorsement. |
| Singapore NEA / data.gov.sg | Changi monthly rainfall comparison, 2005–2024 | [Dataset](https://data.gov.sg/datasets/d_b16d06b83473fdfcc92ed9d37b66ba58/view), [Singapore Open Data Licence](https://data.gov.sg/open-data-licence). Credit the originating agency and dataset. |
| Environment and Climate Change Canada | Toronto Pearson 2005 gap in NOAA's archive | [Historical climate data](https://climate.weather.gc.ca/), [ECCC data licence](https://eccc-msc.github.io/open-data/licence/readme_en/). Credit ECCC and the subset; retain the applicable licence. |

Met Éireann disclaims responsibility for errors, omissions, availability and
resulting losses. Retain its full provider disclaimer and the five attribution
statements in its linked licence notice when redistributing its data/derivatives.
The local study's downloaded metadata preserve provider indicators and source
notices. Review the particular dataset's conditions before redistributing raw data.

The main ten-country comparisons use NOAA ISD observations from originating
local networks. They are not ten direct national-website data extractions.
Country-specific checks have the temporal/quality limits described in the
[core study](validation.md) and [supplemental study](validation_v0_2.md).
