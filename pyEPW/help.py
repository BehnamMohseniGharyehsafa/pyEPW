"""Text help for interactive Python sessions."""

from __future__ import annotations

from itertools import islice
from pathlib import Path

from .catalog import CityCatalog
from .exceptions import ValidationError
from .locations import search_cities, validate_country

USAGE = """pyEPW — actual-year weather files

    from pyEPW import EPW
    weather = EPW("Dublin, Ireland", "2024", ".epw")
    weather.to_csv()
    weather.to_txt()
    weather.to_analysis_csv()  # blank missing values; full modeled luminance
    print(weather.quality_report())
    print(weather.missing_fields)

Formats: epw, txt, csv (a leading dot and uppercase are accepted).
Years: completed calendar years from 1940; leap days are retained.
EPW(...) downloads and writes immediately; additional exports reuse loaded data.
Output: ./output by default. Existing files need overwrite=True.

City help:
    pyEPW.search_cities("Dublin", country="IE")
    pyEPW.help("cities", query="Paris")
    pyEPW.help("cities", country="IE", limit=None)
    catalog = pyEPW.CityCatalog.download()
    catalog.export("all_cities.csv")

The optional GeoNames cities500 directory lists its published city names, not
every settlement. It includes population >500 cities and administrative seats.
Online search may find additional locations. Imports and this usage help are offline.
Public Open-Meteo service access is free for non-commercial use under its terms.
Use Python's built-in help(EPW) for the full constructor documentation.
"""


def help(
    topic: str | None = None,
    *,
    query: str | None = None,
    country: str | None = None,
    limit: int | None = 50,
    cache_dir: str | Path | None = None,
) -> str:
    """Return help text; print the returned string to display it.

    With topic='cities', query uses live city search (maximum 100 results).
    Without query, the optional global GeoNames catalog is downloaded/reused.
    limit=None lists every catalog city in the chosen country or worldwide.
    """
    if topic is None or topic in ("usage", "api"):
        return USAGE
    if topic == "formats":
        return (
            "epw: EnergyPlus EPW with eight headers and 35 columns.\n"
            "csv: one row of named columns and hourly records.\n"
            "txt: tab-delimited text with provenance comments and named columns.\n"
            "Every format has a separate *.EXT.metadata.json attribution sidecar.\n"
        )
    if topic == "fields":
        return (
            "Extraterrestrial radiation: integrated astronomical calculation.\n"
            "Illuminance and zenith luminance: empirical Perez (1990) estimates.\n"
            "Precipitable water: ERA5 total-column integrated water vapour.\n"
            "Visibility and ceiling: quality-checked nearby NOAA GHCNh reports, when available.\n"
            "Gap-only station fallbacks: NOAA ISD QC 1/5, then published METAR (minimal archive QC, labelled).\n"
            "Days since snowfall: ERA5 hourly snowfall history, with an 89-day lookback; 88 means >=88.\n"
            "Albedo: NASA POWER hourly source values; undefined nighttime ratios remain missing.\n"
            "Coverage varies by location/year; use weather.quality_report() and metadata.\n"
            "Canonical exports retain EPW missing codes; to_analysis_csv() uses blanks\n"
            "and preserves modeled luminance outside the EPW representable range.\n"
            "Use require_fields=(column_name, ...) to reject incomplete requested fields.\n"
            "Use require_complete=True to reject any remaining missing weather field.\n"
        )
    if topic != "cities":
        raise ValidationError("Help topics are 'usage', 'api', 'formats', 'fields', and 'cities'.")
    country = validate_country(country)
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValidationError("limit must be a positive integer or None.")
    if query:
        matches = search_cities(query, country=country, limit=min(limit or 100, 100), cache_dir=cache_dir)
        return "City search results:\n" + "\n".join(f"{i}. {location}" for i, location in enumerate(matches, 1))
    catalog = CityCatalog.download(cache_dir=cache_dir)
    names = catalog.names(country=country)
    selected = names if limit is None else islice(names, limit)
    return (
        "GeoNames cities500 directory (population >500 or administrative seats):\n"
        + "\n".join(selected)
        + ("\nSet limit=None to list every matching catalog city." if limit is not None else "")
    )
