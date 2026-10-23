# Finding and listing city names

Weather is requested by coordinates. A name is resolved to coordinates first,
so country and region qualifiers help distinguish places with the same name.

## Search Open-Meteo

```python
from pyEPW import search_cities

for city in search_cities("Springfield", country="US", limit=20):
    print(city, city.geonames_id, city.latitude, city.longitude)
```

Queries use Open-Meteo's global GeoNames-backed search. Two characters require
an exact match; longer strings can match indexed prefixes. Qualifiers such as
`"Paris, France"` or `"Los Angeles, California"` can narrow results. The public
search endpoint returns at most 100 results, so it cannot enumerate the entire
world through one search request.

## Browse the published global catalog

To make names browsable without a hard-coded shortlist, the package supports
GeoNames' separately downloaded **cities500** directory:

```python
import pyEPW

print(pyEPW.help("cities", country="IE", limit=None))

catalog = pyEPW.CityCatalog.download()
print(len(catalog))
for city in catalog.iter_cities(country="GB"):
    print(city)

# No limit: every matching city in this downloaded catalog.
for name in catalog.names(country="IE"):
    print(name)

catalog.export("all_cities.csv")
catalog.export("ireland_cities.csv", country="IE")
```

The first catalog operation downloads `cities500.zip` and builds a local indexed
SQLite database. Later catalog operations use that database without additional
network calls. `refresh=True` explicitly refreshes it. The directory is not
bundled into the wheel, keeping installation small. It is free under CC BY 4.0.

**Coverage:** cities500 includes cities with population over 500 and qualifying
administrative seats. It does not include every settlement, spelling, or named
place on Earth. The live search service may find additional locations. Country
and administrative-region values in catalog results retain GeoNames' codes;
online search typically provides their readable names.

```python
catalog.search("sao", country="BR")  # accent-insensitive local name search
```

The `cities()` convenience function streams catalog results:

```python
from pyEPW import cities

for city in cities(country="FR"):
    print(city)
```

## Command line

```shell
pyEPW cities Dublin --country IE
pyEPW cities --country IE --limit 50
pyEPW cities --output all_cities.csv
```

The CSV export contains names, source region/country codes, coordinates,
elevation, timezone, GeoNames IDs and population. Keep its `.metadata.json`
companion for attribution and the coverage statement.

Sources: [Open-Meteo geocoding documentation](https://open-meteo.com/en/docs/geocoding-api),
[GeoNames dataset description and licence](https://download.geonames.org/export/dump/readme.txt).
