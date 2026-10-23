# Weather methodology

## What is in the file

- Eight EPW header lines and 35 columns per hourly weather record.
- 8,760 records in an ordinary year; **8,784 in a leap year**, retaining February 29.
- Actual dates and year in every record, from January 1 hour 1 through
  December 31 hour 24. The final hour ends at midnight on January 1 of the next
  year, while its EPW date remains December 31 of the requested year.
- The `DATA PERIODS` header also includes the year in its start/end dates,
  as required by EnergyPlus's actual-weather mode.
- Temperature, dew point, humidity, surface pressure, 10 m wind, GHI, DNI, DHI,
  total cloud cover, and liquid rain from the selected year's ERA5 data.
- Snow depth from ERA5-Land for years from 1950 when available. Snow-depth
  failures do not replace snow with fabricated zeros; a warning and missing
  values are recorded.

Only completed calendar years are accepted, starting in 1940. ERA5 is normally
around five days behind real time; the previous year can therefore be unavailable
in early January. In some positive UTC offsets the complete local year 1940
needs UTC data from December 1939, which is outside the archive; that case is
rejected. Missing or invalid **core** weather values stop the conversion before
the EPW is published. The program does not fill gaps with a different year's
weather, forecasts, or synthetic zero values.

## Time and unit handling

All source requests use UTC. EPW output uses one fixed local standard UTC offset
without daylight-saving changes. The offset is derived from the city's IANA
timezone for January of the requested year. Ireland explicitly uses GMT because
IANA represents its winter time as negative DST. For jurisdictions that changed
their standard timezone within a year, or for a different desired convention,
specify the fixed offset explicitly, e.g. `--utc-offset 5.5`.

Open-Meteo radiation is a mean for the **preceding hour**. The script aligns it
to EPW's hour-ending intervals; it does not relabel 00:00 as hour 1. Source dates
include the required boundary hours from adjacent UTC years. For a one-hour
interval, W/m² hourly means and Wh/m² hourly totals have the same numerical value.
Surface pressure is converted from hPa to Pa; snow from metres to centimetres.

For half-hour and quarter-hour UTC offsets, instantaneous fields are linearly
interpolated and wind vectors are interpolated. Rain and radiation are integrated
by interval overlap, assuming uniform conditions within each source UTC hour.
This resampling adds an approximation; no sub-hourly observations are implied.

## Supplemental fields (default since 0.2.0)

| Column group | Method | Interpretation |
|---|---|---|
| Extraterrestrial horizontal/direct normal radiation | Hour-integrated geometric solar calculation | Calculated energy above the atmosphere, not surface irradiance |
| Global/direct normal/diffuse illuminance | Perez (1990) empirical luminous efficacy models | Modeled whole-hour mean lux, not photometer observations |
| Zenith luminance | Perez (1990), Eq. 10 | Modeled whole-hour mean cd/m², with EPW range handling |
| Visibility/ceiling | NOAA GHCNh, then ISD and optional published METAR | Spatial proxies, with each provider's QC policy retained |
| Precipitable water | ERA5 total-column integrated water vapour | Reanalysis column water, not a surface-humidity approximation |
| Days since last snowfall | ERA5 snowfall history with 89-day lookback | Whole elapsed days; 88 means 88 or more, not an exact event age |
| Albedo | NASA POWER ALLSKY_SRF_ALB, available hourly from 2001 | Satellite-derived grid value; missing provider/nighttime values are preserved |

### Astronomical radiation

NOAA's published Meeus-based equations provide geometric zenith, without
atmospheric refraction. A 1361 W/m² solar constant and Spencer Earth-distance
harmonics give normal top-of-atmosphere irradiance. The preceding EPW hour is
integrated using five-minute brackets, located horizon crossings, and Simpson
quadrature. Horizontal energy includes cosine projection; both fields are zero
when the Sun is geometrically below the horizon. Sunrise/sunset partial hours
and polar day/night are handled explicitly. Spencer's 365-day harmonic convention
is retained in leap years. This calculation is deterministic, with small solar
algorithm/integration approximations; it does not depend on station reports.

### Daylight photometry

The implementation follows Perez et al. (1990), Eqs. 1–3, 6–8 and 10, and original
Table 4. Inputs are ERA5 global/direct/diffuse irradiance and dew point, with
daylight-average geometric zenith. Kasten–Young (1989) relative optical air mass
is a documented adaptation. The paper's internal water proxy is
`exp(0.07 * dewpoint_C - 0.075)` cm; this empirical-model input is **separate**
from the ERA5 column-water field exported as precipitable water.

For a partial sunrise/sunset hour, whole-hour irradiances are converted to
daylight-only means to determine model brightness/clearness. Outputs remain
whole-hour means. A 0.1 W/m² diffuse floor applies only inside model parameters,
not to the source diffuse irradiance. Negative fitted outputs are bounded at
zero; all photometry is zero in geometrical night. Global, direct and diffuse
models are independent empirical fits and need not satisfy exact photometric
closure. Zenith uses the authors' `Z'=max(Z,0.6)` correction in the lowest
clearness bin.

The zenith-luminance fit was developed for zenith angles between 17° and 85°;
values outside that range are extrapolations. Metadata counts low-sun hours.
These models do not restore missing measurements or make reanalysis exact.
No local photometer validation is claimed. EPW reserves `9999` and larger for
missing zenith luminance. Values that round into that range are marked missing
in canonical formats, retained in metadata, and restored in `to_analysis_csv()`
as physical cd/m² without clipping or a hidden factor-of-ten conversion.

### Column water

The API variable `total_column_integrated_water_vapour` is requested explicitly
from ERA5, separately from mandatory core weather. Its unit is checked as kg/m²;
1 kg/m² equals 1 mm of equivalent liquid water. It is aligned/interpolated at
the hourly endpoint using the same fixed-standard-time convention. Missing
column-water downloads/values remain missing with warnings. The library does
not estimate full atmospheric-column water from surface relative humidity.

### Visibility and ceiling observations

Open-Meteo's ERA5 API does not supply usable visibility or cloud-base values for
these exports. Instead, the optional supplement uses NOAA GHCNh station-year
PSV files. It does not substitute a heuristic based on humidity or cloud cover.
Station lists and original text files are cached and hashed for audit.

The default search tests up to ten nearby GHCNh station references within 30 km,
prioritizing aviation/airports and then other sites. Gap-only fallback archives
try up to three nearest NOAA ISD historical station references.
An explicit GHCNh station ID can be supplied; `station=None` disables downloads.
Reported historical observation coordinates are also checked against the
distance limit when present; otherwise the catalog reference is retained and
labelled. A catalog search is not an exhaustive guarantee of all local data.

Each field independently selects the closest-in-time accepted report at a
station, within 15 minutes of the EPW endpoint by default; SYNOP wins equal-time
ties. Among tested stations the nearest reported position is preferred. There
is no interpolation, forward fill or unlimited-ceiling inference from an absent
cloud layer or CAVOK alone. Boundary-year reports are requested when needed.

QC meanings vary by source: the supported legacy ISD sources accept codes `1`
or `5`; supported aviation sources accept `1` only. Aviation `4` is calculated
and `5` is removed, so those are rejected. Blank/unknown QC/source combinations
are rejected. This strict policy may leave real gaps rather than report false
completeness. Actual accepted source/QC codes, station, coordinates, distance,
time difference and qualifiers are retained per row through run-length lineage.

GHCNh visibility is already in **km** and ceiling is in **m**. Aviation visibility
`9.999` encodes at least 10 km and becomes `10.000` with a lower-bound qualifier.
An explicit GHCNh unlimited ceiling of 22000 becomes EPW category `77777`;
explicit legacy cirroform becomes category `88888`. These are categories, not
77 km or 88 km measured heights. Missing reports use `9999` visibility and
`99999` ceiling. Measurements tens of kilometres away cannot guarantee the
visibility or cloud ceiling at a building site.

Original ISD fixed-width files accept QC codes 1/5, convert visibility metres to
km, and preserve explicit ceiling categories. Published METARs from IEM are a
separate optional fallback: IEM reports very little archive QC. The parser checks
station identity, coordinates, report timestamp and syntax; it does not claim
additional meteorological QC. It uses original observed BKN/OVC/VV layers, in
hundreds of feet converted to metres, before forecast/remark groups. FEW/SCT
layers are not ceilings. CAVOK, NSC, CLR and absent layers do not imply an exact
height or an unlimited ceiling. Raw report digests and source lineage are kept.

### Snow history and albedo (0.3.0)

ERA5 hourly snowfall in cm is downloaded with 89 days of preceding history.
Positive source amounts identify events without a made-up threshold. The field
counts whole 24-hour days since the event interval ended, capped at the documented
88-or-more code. Unknown source intervals invalidate the history until a known
later event or 88 complete consecutive zero-snow days. Snow depth is never used
to infer a snowfall event. Fractional UTC offsets use the documented hourly
overlap approximation; event timing is limited to the source hourly resolution.

NASA POWER supplies dimensionless hourly ALLSKY_SRF_ALB in UTC. These source
hours begin at the labelled time and are shifted to EPW hour-ending intervals;
fractional offsets use interval-overlap weighting only when all contributing
hours are valid. Provider fill values and values outside 0–1 remain missing.
NASA defines albedo as reflected divided by incoming shortwave radiation, so
the hourly ratio is undefined at night. The library does not fill those hours
with zero, a daytime value, another year or a climatological mean. This is a
satellite-derived native-grid product, not the reflectivity of a specific roof
or ground surface. Full response provenance and hashes are recorded.

## Other estimated and missing fields

Opaque sky cover uses total cloud cover as a proxy. Horizontal infrared uses
the EnergyPlus-documented Clark-Allen/Walton method with temperature, dew point
and that proxy; sky emissivity is bounded to 0–1. These remain modeled fields.
Present-weather observation/codes and aerosol optical depth remain unsupported
by this conversion; other fields retain gaps when no valid source is available.
Ground temperatures and design-day
statistics are not invented: their header counts are zero. Configure these
separately when a simulation needs them.

`quality_report()` and `field_coverage` expose completeness and source classes.
`require_fields=(...)` raises `DataError` before writing if requested fields
have missing canonical hours. `require_complete=True` requires all weather fields
to be non-missing before any output is written. Optional failures produce explicit
warnings and missing codes. A full numerical column is not an accuracy guarantee.
`include_additional_fields=False` reproduces the v0.1.0 core conversion; its
ten-country benchmark does not validate the newly added fields.

The file is intended for weather-driven simulation of that particular year.
Acceptance and treatment of missing fields vary between EPW-consuming programs.
In EnergyPlus, use the actual calendar year in the `RunPeriod`, enable its
**Treat Weather as Actual** setting, and retain leap days for leap years. This
converter does not generate an EnergyPlus model or certified design weather.


## Data sources

[Open-Meteo historical API](https://open-meteo.com/en/docs/historical-weather-api)

[EnergyPlus EPW specification](https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html)

[NOAA solar equations](https://gml.noaa.gov/grad/solcalc/calcdetails.html)

[Perez et al. daylight paper](https://doi.org/10.1016/0038-092X(90)90055-H)

[NOAA NCEI GHCNh](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly)

[NOAA ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database)

[IEM METAR archive and QC limitations](https://mesonet.agron.iastate.edu/request/download.phtml)

[NASA POWER albedo methodology](https://power.larc.nasa.gov/docs/methodology/energy-fluxes/derived-parameters/)

[NASA POWER hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)
