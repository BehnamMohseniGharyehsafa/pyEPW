# Free fallback sources and Cork 2025

Version 0.3.0 uses source-backed supplements rather than substituting generic
numbers for EPW missing codes. All requests use public endpoints without an API
key or paid account. Open-Meteo's hosted free service remains subject to its
non-commercial terms and rate limits. No provider promises complete coverage.

## Source policy

| Field | Source and acceptance | Remaining limitations |
|---|---|---|
| Days since last snowfall | ERA5 hourly snowfall via Open-Meteo, plus 89-day lookback; whole days since positive source snowfall | Reanalysis and hourly event timing, not local snow observations; gaps invalidate history; 88 means at least 88 days |
| Albedo | NASA POWER ALLSKY_SRF_ALB, dimensionless valid hourly values in UTC, aligned to EPW intervals | Satellite-derived grid ratio, not a specific building surface; undefined/nighttime or provider-missing hours stay missing |
| Visibility/ceiling | Nearby GHCNh, then gap-only NOAA ISD QC 1/5, then optional published METAR reports | Nearby spatial proxies within 30 km and reports within 15 minutes by default; METAR archive has very little additional QC |

ISD original gzip files and decoded text are cached with hashes. METAR lineage
includes report hashes, station, position, time difference, qualifiers and an
explicit minimal-QC label. Existing accepted station values are not overwritten.
Explicit station selection constrains fallback references to the same site
(within 1 km); `station=None` disables all station supplements.

METAR ceiling is the lowest reported BKN/OVC/VV layer. FEW/SCT heights are not
ceilings. CAVOK or NSC does not provide an exact finite or unlimited ceiling, so
the code does not invent one. METAR forecast and remark groups are excluded.
Source `9999` metre visibility is a lower bound of 10 km, retained as a qualifier.

NASA albedo is reflected divided by incoming solar radiation. Replacing its
undefined nighttime ratio with zero, repeating a daytime value or substituting
a daily mean would add an assumption. This release preserves the source gap.
Likewise, unsupported present-weather codes and aerosol optical depth remain
missing; they are not inferred from other fields.

## Verified Cork results

These are actual-year 2025 files, with 8,760 fixed-standard-time hourly rows,
35 columns and an unchanged ERA5 core. The following counts describe available
values, not measured accuracy at the city coordinates.

| Field | Previous valid hours | Version 0.3.0 valid hours | Remaining missing hours |
|---|---:|---:|---:|
| Days since last snowfall | 0 | 8,760 | 0 |
| Albedo | 0 | 4,509 | 4,251 |
| Ceiling height | 5,551 | 7,945 | 815 |
| Visibility | 8,588 | 8,759 | 1 |

Ceiling sources: 5,551 GHCNh, 2,144 ISD and 250 published METAR values. Visibility
sources: 8,588 GHCNh, 35 ISD and 136 published METAR values. The metadata preserves
each accepted source. Mixing nearby sites improves availability but does not
turn these values into observations at the requested city point.

Of the 815 remaining ceiling gaps, the nearest published METAR has only FEW/SCT
layers in 793 hours and CAVOK in four. Two have no usable finite ceiling, and
16 have no report within the time tolerance. These reports do not establish an
exact or unlimited ceiling. Substituting a cloud-base height would change the
meaning of the EPW field.

An independent audit compares every exported snow-history/albedo hour and all
16,704 accepted visibility/ceiling values with downloaded raw sources, without
calling the library's decoders. It verifies source hashes, QC labels, timing,
unit conversions, original gzip contents, calendar and EPW/CSV identity. The
full-year EnergyPlus 25.1 actual-weather run completes with zero warnings and
zero severe errors. The offline suite has 62 passing tests; packaging is also
checked in an isolated wheel installation.

These checks establish file compatibility and source consistency. They do not
certify meteorological accuracy. The prior ten-city/twenty-year study documents
version 0.2.0; this release's fallbacks have not undergone that full global study.

## Completeness controls

```python
from pyEPW import EPW

weather = EPW("Cork, Ireland", 2025, ".epw")
weather.to_csv()                  # same canonical EPW codes
weather.to_analysis_csv()         # blank missing cells; full modeled luminance
print(weather.missing_fields)     # field -> absent hour count
print(weather.is_complete)        # False for this Cork dataset

# Optional: exclude the minimally QC'd METAR archive.
# EPW("Cork, Ireland", 2025, allow_metar_fallback=False)

# Strict mode rejects any remaining missing weather field before writing.
# Cork 2025 will raise DataError, rather than claim to be complete.
# EPW("Cork, Ireland", 2025, require_complete=True)
```

Present-weather fields and aerosol optical depth remain unsupported by this
converter. Additionally, 197 modeled zenith-luminance values are beyond EPW's
non-missing representable range; canonical outputs mark them missing and the
analysis CSV retains those empirical-model values. The analysis CSV is still
incomplete in the other fields.

## Primary references

- [NASA POWER albedo definition](https://power.larc.nasa.gov/docs/methodology/energy-fluxes/derived-parameters/)
- [NASA POWER hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)
- [NOAA GHCNh](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly)
- [NOAA ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database)
- [IEM archive and its QC limitations](https://mesonet.agron.iastate.edu/request/download.phtml)
- [EnergyPlus EPW data dictionary](https://bigladdersoftware.com/epx/docs/26-1/auxiliary-programs/auxiliary-programs.html#energyplus-weather-file-epw-data-dictionary)
- [NREL weather-format tables: 88-or-more snow-history code](https://www.nrel.gov/docs/fy08osti/43388.pdf)
- [Open-Meteo historical API](https://open-meteo.com/en/docs/historical-weather-api)
