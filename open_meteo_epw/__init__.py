"""Compatibility imports for the former open_meteo_epw package.

Use ``import pyEPW`` for new projects. Aliases refer to the same classes and
modules so old imports, exception handling and patches keep their identities.
"""

from importlib import import_module as _import_module
import sys as _sys

import pyEPW as _canonical

__all__ = _canonical.__all__
for _name in __all__:
    globals()[_name] = getattr(_canonical, _name)

for _name in (
    "_attribution",
    "_daylight",
    "_engine",
    "_files",
    "_solar",
    "_version",
    "api",
    "catalog",
    "cli",
    "client",
    "exceptions",
    "help",
    "locations",
    "models",
    "observations",
    "quality",
    "station_fallbacks",
    "supplements",
    "writers",
):
    _module = _import_module("pyEPW." + _name)
    _sys.modules[__name__ + "." + _name] = _module
    if _name not in __all__:
        globals()[_name] = _module

del _canonical, _import_module, _sys, _module, _name
