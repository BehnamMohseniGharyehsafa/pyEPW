# Python API

```python
import pyEPW

weather = pyEPW.EPW("Dublin, Ireland", "2024", ".epw")
```

The equivalent direct import is:

```python
from pyEPW import EPW

weather = EPW("Dublin, Ireland", 2024, "epw")
```

`import pyEPW` creates a module namespace. Therefore a bare `EPW(...)`
requires the second import form. Prefer `weather` as the result variable;
writing `EPW = EPW(...)` replaces the class name in the caller's scope.

## Constructor

```python
EPW(
    city,
    year,
    format="epw",
    *,
    output_dir="output",
    output=None,
    country=None,
    match=1,
    cache_dir=None,
    overwrite=False,
    include_snow=True,
    utc_offset=None,
    refresh=False,
    include_additional_fields=True,
    station="auto",
    max_station_distance_km=30,
    station_tolerance_minutes=15,
    require_fields=(),
    use_free_fallbacks=True,
    allow_metar_fallback=True,
    require_complete=False,
)
```

Construction performs city lookup, downloads or reuses cached weather, validates
the entire year, and writes the selected format plus attribution metadata.
Importing the package does none of these operations.

| Argument | Meaning |
|---|---|
| `city` | Name such as `"Paris, France"`, or a `Location` from city search/catalog |
| `year` | Integer or four-digit string; completed calendar years from 1940 |
| `format` | `"epw"`, `"txt"`, or `"csv"`; case-insensitive, optional leading dot |
| `output_dir` | Destination folder relative to the caller's working directory |
| `output` | Explicit path; its extension must match `format` |
| `country` | Optional ISO two-letter filter for name lookup |
| `match` | One-based ranked match, default 1 |
| `cache_dir` | Custom cache location; otherwise a user cache directory |
| `overwrite` | Replace an existing output and its companion metadata |
| `include_snow` | Request optional ERA5-Land snow depth, default True |
| `utc_offset` | Override fixed standard offset in hours, for example `5.5` |
| `refresh` | Re-download instead of using cached API responses |
| `include_additional_fields` | Enable astronomical radiation, modeled photometry, ERA5 column water and optional nearby station fields; default True |
| `station` | `"auto"`: bounded nearby station search; an 11-character GHCNh ID: explicit station; `None`: disable station downloads |
| `max_station_distance_km` | Positive finite maximum distance, default 30 km; applied to reported positions when present |
| `station_tolerance_minutes` | Nearest report tolerance, >0 and ≤30 minutes, default 15; no temporal gap filling |
| `require_fields` | Field name or sequence from `EPW_COLUMNS`; fail before writing if any has missing hours |
| `use_free_fallbacks` | Enable ERA5 snowfall history, NASA hourly albedo and gap-only NOAA ISD/METAR supplements; default True |
| `allow_metar_fallback` | Allow published METARs with minimal archive QC, labelled separately; default True |
| `require_complete` | Require every canonical weather field to have no missing hours; raise DataError before writing otherwise; default False |

`OutputFormat.EPW`, `.TXT`, and `.CSV` are accepted in place of strings.

## Working with a result

```python
print(weather.path)           # pathlib.Path: initial file
print(weather.metadata_path)  # pathlib.Path: initial export's metadata
print(weather.location)       # Location: resolved city/region/country
print(weather.year)           # int
print(weather.hours)          # 8760 or 8784
print(weather.is_leap_year)   # bool
print(weather.metadata)       # defensive copy of provenance
print(weather.is_complete)    # canonical weather-field completeness
print(weather.missing_fields) # field name -> missing hours

csv_path = weather.to_csv()
txt_path = weather.to_txt()
epw_path = weather.to_epw("other/location.epw")
another_csv = weather.save("csv", "other/location.csv")
analysis_csv = weather.to_analysis_csv()  # default: *_analysis.csv
print(weather.quality_report())
print(weather.field_coverage["visibility_km"])
```

These methods return `pathlib.Path` and use the already loaded dataset. They do
not change `weather.path`, which identifies the initial file. Calling an export
again for an existing path requires `overwrite=True`.

`weather.data` is an immutable tuple of records in `EPW_COLUMNS` order.
`weather.iter_records()` yields dictionaries keyed by those names. Values are
strings, preserving EPW sentinel codes and the nine-character weather code.
Applications can explicitly convert the numeric columns they need.

`weather.field_coverage` returns a defensive copy of source/method classes, valid
and missing hour counts, and missing-code thresholds. Station fields additionally
report qualifier counts, station counts and actual distance ranges.
`ADDITIONAL_FIELDS` names the eleven supplemental columns. `quality_report()`
returns an offline text summary of those fields.

`to_analysis_csv(path=None, overwrite=False)` uses the same loaded data and
35 column names, writes blanks for missing values, and restores modeled zenith
luminance that cannot fit EPW's non-missing range. Its metadata describes this
analysis-specific representation. Standard `to_csv()` remains identical to EPW
records, including their sentinel codes. A CSV's completeness does not change
whether a field is modeled or observed.

`require_fields` checks canonical EPW completeness, including its representable
ranges. For example, requiring `zenith_luminance_cd_m2` can fail even when the
analysis export could retain every modeled value. Unknown field names and invalid
station/distance/tolerance settings raise `ValidationError` before downloading.

## Nearby station discovery

```python
from pyEPW import search_cities, search_stations

city = search_cities("Maynooth", country="IE")[0]
for site in search_stations(city, max_distance_km=30, limit=10):
    print(site.station_id, site.name, site.distance_km)
```

`search_stations(location, *, max_distance_km=30, limit=10, cache_dir=None,
refresh=False)` returns `ObservationStation` records from the public GHCNh
catalog. This explicit call may download/cache the station list. Catalog
membership does not guarantee visibility/ceiling coverage for a given year.
Automatic enrichment tests up to ten references, prioritizing aviation/airports
then nearby other sites. Enabled fallbacks try up to three NOAA ISD historical
sites, then their published METARs, filling only absent values. An explicit
GHCNh ID restricts archive fallback references to within 1 km of that selected
station; `station=None` disables all station supplements.
Nearest eligible reports at each station
are matched independently by field; among tested stations, the nearest reported
position wins. Historical positions can differ from catalog references.

`require_complete=True` is strict about data availability; it does not certify
measurement accuracy. It currently rejects Cork 2025 because some fields remain
unsupported or have source gaps. `allow_metar_fallback=False` accepts only the
supported NOAA QC-coded station records. See [fallback sources](fallbacks.md).

## City discovery and help

```python
from pyEPW import search_cities

matches = search_cities("Paris", country="FR", limit=10)
for index, city in enumerate(matches, 1):
    print(index, city, city.latitude, city.longitude, city.timezone)

# Passing the selected Location avoids a second name lookup.
weather = EPW(matches[0], 2024, "csv")

print(pyEPW.help())
print(pyEPW.help("formats"))
print(pyEPW.help("fields"))
print(pyEPW.help("cities", query="Dublin", country="IE"))
help(EPW)  # Python's built-in help and complete constructor docstring
```

See [city directory](cities.md) for listing/exporting every name in the optional
global catalog. No package-level list claims to enumerate every city on Earth.

## Errors and logging

```python
from pyEPW import EPW, PyEPWError

try:
    weather = EPW("Dublin, Ireland", 2024, "epw")
except PyEPWError as error:
    print(error)
```

Subclasses are `ValidationError`, `CityNotFoundError`, `APIError`, `DataError`,
`CatalogError`, and `OutputExistsError`. Local filesystem failures may also raise
ordinary `OSError` subclasses. No partial weather file is written for missing
core data. Existing files are preserved unless overwriting is explicitly enabled.

Enable progress logging if wanted:

```python
import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
```

Set `PYEPW_CACHE` or pass `cache_dir` to override the user cache location.
The older `OPEN_METEO_EPW_CACHE` variable remains accepted; `PYEPW_CACHE` wins
when both are set. The former `open_meteo_epw` import remains a compatibility
alias. `OpenMeteoEPWError` is an identical alias of `PyEPWError`.

The distribution name is `pyepw-openmeteo`; the import name is `pyEPW`.
Install this project's supplied wheel or source directory. The existing `pyepw`
project on PyPI is unrelated, and `pip install pyEPW` selects that project.
