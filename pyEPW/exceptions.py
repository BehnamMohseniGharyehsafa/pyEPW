"""Exceptions raised by the public API."""


class PyEPWError(Exception):
    """Base class for all expected library errors."""


# Retain the original exception identity for existing integrations.
OpenMeteoEPWError = PyEPWError


class ValidationError(PyEPWError, ValueError):
    """A city, year, format, or other argument is invalid."""


class APIError(PyEPWError):
    """A remote service could not return a valid response."""


class CityNotFoundError(PyEPWError, LookupError):
    """A city query returned no suitable location."""


class DataError(PyEPWError):
    """Weather data are missing, inconsistent, or outside supported ranges."""


class OutputExistsError(PyEPWError, FileExistsError):
    """An output exists and overwrite=False was requested."""


class CatalogError(PyEPWError):
    """The optional GeoNames catalog could not be downloaded or read."""
