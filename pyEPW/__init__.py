"""Create actual-year EPW, TXT, and CSV weather files from a city and year.

Quick start::

    from pyEPW import EPW
    weather = EPW("Dublin, Ireland", "2024", ".epw")
    weather.to_csv()
    weather.to_txt()

City discovery::

    import pyEPW
    print(pyEPW.help())
    print(pyEPW.search_cities("Dublin", country="IE"))
    print(pyEPW.help("cities", country="IE", limit=None))

Weather downloads use the free non-commercial Open-Meteo service. Importing
this module performs no network requests, downloads, or filesystem writes.
"""

import logging

from ._version import __version__
from .api import EPW
from .catalog import CityCatalog, cities
from .exceptions import (
    APIError,
    CatalogError,
    CityNotFoundError,
    DataError,
    PyEPWError,
    OpenMeteoEPWError,
    OutputExistsError,
    ValidationError,
)
from .help import help
from .locations import search_cities
from .models import EPW_COLUMNS, Location, OutputFormat
from .observations import ObservationStation, search_stations
from .quality import ADDITIONAL_FIELDS

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "EPW",
    "OutputFormat",
    "Location",
    "EPW_COLUMNS",
    "ADDITIONAL_FIELDS",
    "ObservationStation",
    "search_stations",
    "search_cities",
    "cities",
    "CityCatalog",
    "help",
    "PyEPWError",
    "OpenMeteoEPWError",
    "ValidationError",
    "APIError",
    "CityNotFoundError",
    "DataError",
    "OutputExistsError",
    "CatalogError",
    "__version__",
]
