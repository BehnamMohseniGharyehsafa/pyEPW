# Output formats

All three formats serialize the **same actual-year weather records**, with
8,760 hours in an ordinary year and 8,784 in a leap year. Each export has a unique
companion file named `FILENAME.EXT.metadata.json`. It records credits, source
requests, units/column names, estimates, missing fields, warnings and a SHA-256
digest of that output. Keep it when redistributing files.

| Format | Structure | Intended use |
|---|---|---|
| `.epw` | Eight EPW header rows and 35 fields per hourly record | EnergyPlus and other EPW consumers |
| `.csv` | One unit-labelled column-name row and hourly records | Pandas, Excel, analysis and interchange |
| `.txt` | `#` provenance comments, then a tab-delimited column-name row and records | Human inspection and text workflows |
| `*_analysis.csv` | Same 35 columns, blank missing cells, full modeled zenith-luminance range | Numeric analysis with `to_analysis_csv()` |

CSV is a conventional tabular export, not EnergyPlus's separate Weather Converter
CSV dialect. TXT is tab-delimited; it is not an EPW file with its extension changed.

```python
from pyEPW import EPW

weather = EPW("Dublin, Ireland", 2024, "epw")
weather.to_csv()
weather.to_txt()
weather.to_analysis_csv()

# Optional pandas analysis; pandas is not a package dependency.
# import pandas as pd
# frame = pd.read_csv(weather.to_csv("analysis.csv"))
```

## Columns and time

`pyEPW.EPW_COLUMNS` lists all 35 names, in order. Column names include
their units, for example `dry_bulb_temperature_c`, `wind_speed_m_s`,
`atmospheric_station_pressure_pa`, and `global_horizontal_radiation_wh_m2`.

The date identifies the interval's start day. Hour 1 represents 00:00–01:00;
hour 24 represents 23:00–24:00. `minute` is 60. All formats use the site's fixed
standard UTC offset, without daylight saving. The final record is dated
December 31 of the requested year, even though its interval ends at the next
year's midnight. See [methodology](methodology.md) for resampling assumptions.

## Missing values

EPW sentinel codes are preserved consistently in CSV and TXT. They are **not
blank cells or measured numeric values**. Important codes include:

| Field | Missing code |
|---|---|
| Extraterrestrial radiation | `9999` |
| Illuminance | `999999` |
| Zenith luminance | `9999` |
| Visibility | `9999` |
| Ceiling height | `99999` |
| Present weather observation / codes | `9` / `999999999` |
| Precipitable water | `999` |
| Aerosol optical depth | `.999` |
| Snow depth, when unavailable | `999` |
| Days since snow | `99` |
| Albedo | `999` |

Core temperature/humidity/pressure/wind/solar/cloud/rain data are mandatory.
The conversion raises `DataError` instead of using sentinel values for them.
Infrared and opaque sky cover are estimates, documented in each output.

Since 0.3.0 eleven supplemental fields are populated where supported; missing
codes indicate actual gaps or an EPW range limit, not numeric measurements.
Zenith luminance at or above `9999 cd/m²` cannot be represented as a non-missing
canonical EPW value. The standard EPW/CSV/TXT use the missing code; the original
modeled values are retained in metadata and restored by `to_analysis_csv()`.
They are never clipped down to appear valid. The analysis export uses blank
cells for other missing fields, rather than filling unobserved data.

Ceiling `77777` means unlimited, `88888` means cirroform, and `99999` means
missing. The first two remain categorical codes even in the analysis export;
do not treat them as heights for averaging. NOAA visibility `9.999 km` from
aviation reports is written as `10.000 km` with a `lower_bound_10_km` qualifier
in per-hour metadata. Such reports say at least 10 km, not exactly 10 km.

Metadata `observation_lineage_runs` uses zero-based row ranges to preserve the
source station, reported position, distance, source/QC/report codes, time
difference and qualifier for each accepted station value. A `source: null` run
means no accepted report. `station_text_sources` records public URLs, cached
filenames and SHA-256 hashes of the UTF-8 source text.
Original downloaded ISD gzip files also have a retained filename and SHA-256.
Published METAR values retain a report digest and an explicit `not_supplied`
archive-QC label; they are not presented as NOAA QC-passed data.

`days_since_last_snowfall=88` means **88 or more days**, established from ERA5
snowfall history. It is not a missing code. Albedo `999` remains missing when
NASA supplies a fill code, including undefined nighttime values. The analysis
CSV leaves such cells blank. `is_complete` and `missing_fields` describe the
particular exported representation; the `EPW` object's properties refer to its
canonical records. See [source and gap policy](fallbacks.md).
