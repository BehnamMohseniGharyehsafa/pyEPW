"""The public EPW(city, year, format) API."""

from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import datetime, timezone
import logging
import math
from pathlib import Path
import re
from typing import Any, Iterator

from . import _engine
from .client import APIClient
from .exceptions import CityNotFoundError, ValidationError
from .locations import _search, validate_country
from .models import EPW_COLUMNS, Location, OutputFormat
from .quality import ADDITIONAL_FIELDS
from .writers import check_destination, metadata_path, write_weather, write_analysis_csv

logger = logging.getLogger(__name__)


def _year(value: int | str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValidationError("year must be an integer or a four-digit year string, such as 2024.")
    if isinstance(value, str) and not re.fullmatch(r"\d{4}", value.strip()):
        raise ValidationError("year must be a four-digit year, such as '2024'.")
    year = int(value)
    current_year = datetime.now(timezone.utc).year
    if not 1940 <= year < current_year:
        raise ValidationError(f"year must be a completed calendar year from 1940 to {current_year - 1}.")
    return year


class EPW:
    """Download one historical year and write the requested weather-file format.

    ``EPW('Dublin, Ireland', '2024', '.epw')`` creates a file immediately.
    Use the object's to_csv()/to_txt()/to_epw() methods to export the same
    in-memory dataset again without re-downloading weather.

    Parameters
    ----------
    city : str or Location
        City name, optionally qualified by country, or a search_cities() result.
    year : int or str
        A completed calendar year from 1940 onward. Leap days are retained.
    format : str or OutputFormat
        'epw', 'txt', or 'csv', case-insensitive; a leading dot is optional.
    output_dir : str or pathlib.Path
        Destination directory. Default: ./output in the caller's working folder.
    output : str or pathlib.Path, optional
        Explicit file path, overriding output_dir. Its extension must match format.
    country : str, optional
        Two-letter country filter for a city-name query.
    match : int
        One-based ranked city match; default 1. Inspect search_cities() first
        when names are ambiguous, or pass the chosen Location directly.
    cache_dir : str or pathlib.Path, optional
        Local API cache. Default is a user cache, never the installed package.
    overwrite : bool
        Replace existing output and metadata. Default False.
    include_snow : bool
        Fetch optional ERA5-Land snow depth when available. Default True.
    utc_offset : float, optional
        Override the fixed standard offset in hours, for example 5.5.
    refresh : bool
        Re-download rather than reuse cached API responses. Default False.
    include_additional_fields : bool
        Calculate extraterrestrial radiation/Perez photometry and retrieve ERA5
        column water plus nearby NOAA visibility/ceiling. Default True.
    station : str or None
        'auto' (default): use eligible stations within max_station_distance_km.
        A GHCNh station ID selects that station. None disables station downloads.
    max_station_distance_km : float
        Maximum station-to-site distance; default 30 km. Nearby measurements are
        spatial proxies, never relabelled as on-site observations.
    station_tolerance_minutes : float
        Nearest report tolerance, >0 to 30 minutes; default 15. No temporal filling.
    require_fields : sequence of str
        Fail before writing if any requested named EPW field has missing hours.
        Default empty. Completeness does not certify meteorological accuracy.
    use_free_fallbacks : bool
        Enable NASA hourly albedo, ERA5 snowfall history and station fallback
        archives. Default True. Unsupported gaps remain missing.
    allow_metar_fallback : bool
        Allow published METAR observations from IEM to fill station gaps; default
        True. Archive QC is minimal and recorded separately from NOAA QC flags.
    require_complete : bool
        Default False. Reject output if any of the 29 weather fields has missing
        hours after supported providers are tried. Never fill gaps to pass.

    Attributes
    ----------
    path : pathlib.Path
        The initially created weather file.
    metadata_path : pathlib.Path
        Its attribution/provenance JSON companion.
    location : Location
        The resolved city and coordinates.
    year : int
        The actual year in the file.
    format : OutputFormat
        Initial output format.

    Notes
    -----
    ERA5 reanalysis is used, with estimated infrared/opaque-cloud fields. Missing
    core data raise DataError; no substitute year is invented. Public Open-Meteo
    access is free for non-commercial use, subject to its terms and rate limits.
    Importing the package performs no network or file operations.
    """

    def __init__(
        self,
        city: str | Location,
        year: int | str,
        format: str | OutputFormat = "epw",
        *,
        output_dir: str | Path = "output",
        output: str | Path | None = None,
        country: str | None = None,
        match: int = 1,
        cache_dir: str | Path | None = None,
        overwrite: bool = False,
        include_snow: bool = True,
        utc_offset: float | None = None,
        refresh: bool = False,
        include_additional_fields: bool = True,
        station: str | None = "auto",
        max_station_distance_km: float = 30,
        station_tolerance_minutes: float = 15,
        require_fields: tuple[str, ...] | list[str] | str = (),
        use_free_fallbacks: bool = True,
        allow_metar_fallback: bool = True,
        require_complete: bool = False,
    ) -> None:
        self.year = _year(year)
        self.format = OutputFormat.parse(format)
        country = validate_country(country)
        if not isinstance(include_snow, bool) or not isinstance(include_additional_fields, bool):
            raise ValidationError("include_snow and include_additional_fields must be booleans.")
        if any(not isinstance(value, bool) for value in (use_free_fallbacks, allow_metar_fallback, require_complete)):
            raise ValidationError("use_free_fallbacks, allow_metar_fallback and require_complete must be booleans.")
        if station is not None:
            if not isinstance(station, str):
                raise ValidationError("station must be 'auto', a GHCNh station ID, or None.")
            station = "auto" if station.lower() == "auto" else station.upper()
            if station != "auto" and not re.fullmatch(r"[A-Z0-9-]{11}", station):
                raise ValidationError("station must be 'auto', an 11-character GHCNh ID, or None.")
        for name, value in [
            ("max_station_distance_km", max_station_distance_km),
            ("station_tolerance_minutes", station_tolerance_minutes),
        ]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValidationError(f"{name} must be a positive finite number.")
        if station_tolerance_minutes > 30:
            raise ValidationError("station_tolerance_minutes must be <=30; larger gaps are not filled.")
        if isinstance(require_fields, str):
            require_fields = (require_fields,)
        if not isinstance(require_fields, (tuple, list)) or any(
            not isinstance(f, str) or f not in EPW_COLUMNS[6:] for f in require_fields
        ):
            raise ValidationError("require_fields must contain valid meteorological EPW_COLUMNS names.")
        require_fields = tuple(require_fields)
        if require_complete:
            require_fields = tuple(dict.fromkeys((*require_fields, *EPW_COLUMNS[6:])))
        if isinstance(match, bool) or not isinstance(match, int) or not 1 <= match <= 100:
            raise ValidationError("match must be an integer between 1 and 100.")
        if not isinstance(city, (str, Location)) or (isinstance(city, str) and len(city.strip()) < 2):
            raise ValidationError("city must be a city name with at least two characters or a Location.")
        if utc_offset is not None:
            if (
                isinstance(utc_offset, bool)
                or not isinstance(utc_offset, (float, int))
                or not math.isfinite(utc_offset)
                or not -12 <= utc_offset <= 14
            ):
                raise ValidationError("utc_offset must be a number between -12 and +14 hours.")
        explicit_output = Path(output).expanduser() if output is not None else None
        if explicit_output is not None:
            self._check_extension(explicit_output, self.format)
            check_destination(explicit_output, overwrite)
        client = APIClient(cache_dir, refresh)
        if isinstance(city, Location):
            self.location = city
        else:
            locations = _search(client, city, country, max(10, match))
            if not locations:
                raise CityNotFoundError(f"No city found for {city!r}. Try search_cities() and a country filter.")
            if match > len(locations):
                raise ValidationError(f"match={match} was requested but only {len(locations)} matches were found.")
            self.location = locations[match - 1]
            logger.info("Selected city: %s (%s, %s)", self.location, self.location.latitude, self.location.longitude)
        self._validate_location(self.location)
        offset = _engine.standard_utc_offset(self.location.timezone, self.year, utc_offset)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", _engine.header_text(self.location.name)).strip("_")
        self._stem = f"{name or 'city'}_{self.location.country_code}_{self.year}"
        self._output_dir = Path(output_dir).expanduser().resolve()
        target = explicit_output or self._output_dir / f"{self._stem}.{self.format.value}"
        check_destination(target, overwrite)
        self._dataset = _engine.load_dataset(
            client,
            self.location,
            self.year,
            offset,
            include_snow,
            include_additional_fields=include_additional_fields,
            station=station,
            max_station_distance_km=max_station_distance_km,
            station_tolerance_minutes=station_tolerance_minutes,
            require_fields=require_fields,
            use_free_fallbacks=use_free_fallbacks,
            allow_metar_fallback=allow_metar_fallback,
        )
        self.path, self._metadata = write_weather(self._dataset, self.format, target, overwrite)
        self.metadata_path = metadata_path(self.path)
        # Additional formats default to the same directory as the first file.
        self._output_dir = self.path.parent

    @staticmethod
    def _check_extension(path: Path, format: OutputFormat) -> None:
        if path.suffix.lower() != "." + format.value:
            raise ValidationError(f"The output path must end in .{format.value}.")

    @staticmethod
    def _validate_location(location: Location) -> None:
        if not location.name or not location.timezone:
            raise ValidationError("Location must have a name and an IANA timezone.")
        if not math.isfinite(location.latitude) or not -90 <= location.latitude <= 90:
            raise ValidationError("Location latitude must be between -90 and 90.")
        if not math.isfinite(location.longitude) or not -180 <= location.longitude <= 180:
            raise ValidationError("Location longitude must be between -180 and 180.")

    @property
    def hours(self) -> int:
        """Number of hourly records (8,760 or 8,784)."""
        return len(self._dataset.rows)

    @property
    def is_leap_year(self) -> bool:
        return calendar.isleap(self.year)

    @property
    def metadata(self) -> dict[str, Any]:
        """A defensive copy of provenance and the initial export's metadata."""
        return deepcopy(self._metadata)

    @property
    def data(self) -> tuple[tuple[str, ...], ...]:
        """Immutable string records in EPW_COLUMNS order, preserving sentinel codes."""
        return self._dataset.rows

    @property
    def field_coverage(self) -> dict[str, dict[str, Any]]:
        """Per-field valid/missing hours, source class and method; defensive copy."""
        return deepcopy(self._metadata["field_coverage"])

    def quality_report(self) -> str:
        """Readable coverage summary; completeness is not an accuracy guarantee."""
        lines = [
            f"{self.location.display_name} — {self.year}: {self.hours:,} hours",
            "Field | valid hours | missing hours | source/method class",
        ]
        for field in ADDITIONAL_FIELDS:
            info = self.field_coverage[field]
            lines.append(f"{field} | {info['valid_hours']} | {info['missing_hours']} | {info['data_kind']}")
        lines.append("Station distance/QC and modeled-field limitations are recorded in the metadata sidecar.")
        return "\n".join(lines)

    @property
    def is_complete(self) -> bool:
        """Whether every canonical weather field has a value in every hour."""
        return self._metadata["is_complete"]

    @property
    def missing_fields(self) -> dict[str, int]:
        """Remaining missing-hour counts, keyed by weather column name."""
        return deepcopy(self._metadata["missing_fields"])

    def iter_records(self) -> Iterator[dict[str, str]]:
        """Yield named weather records; values are strings with EPW missing codes."""
        for row in self.data:
            yield dict(zip(EPW_COLUMNS, row))

    def save(
        self, format: str | OutputFormat | None = None, path: str | Path | None = None, *, overwrite: bool = False
    ) -> Path:
        """Write a format from already-loaded data; return its path; no HTTP calls."""
        selected = self.format if format is None else OutputFormat.parse(format)
        target = Path(path).expanduser() if path is not None else self._output_dir / f"{self._stem}.{selected.value}"
        self._check_extension(target, selected)
        return write_weather(self._dataset, selected, target, overwrite)[0]

    def to_epw(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path:
        """Write EnergyPlus EPW, with eight header lines and 35 data columns."""
        return self.save(OutputFormat.EPW, path, overwrite=overwrite)

    def to_csv(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path:
        """Write CSV with one row of unit-labelled column names and hourly rows."""
        return self.save(OutputFormat.CSV, path, overwrite=overwrite)

    def to_analysis_csv(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path:
        """CSV with blank missing values and full-range modeled luminance.

        Same 35 named columns and physical units. Unlike to_csv(), values are
        not constrained by EPW's reserved missing ranges. No new HTTP requests.
        Ceiling category codes 77777/88888 are retained and documented.
        """
        target = Path(path).expanduser() if path is not None else self._output_dir / (self._stem + "_analysis.csv")
        self._check_extension(target, OutputFormat.CSV)
        return write_analysis_csv(self._dataset, target, overwrite)[0]

    def to_txt(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path:
        """Write tab-delimited UTF-8 text with provenance comments and column names."""
        return self.save(OutputFormat.TXT, path, overwrite=overwrite)

    def __len__(self) -> int:
        return self.hours

    def __fspath__(self) -> str:
        return str(self.path)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        return f"EPW(city={self.location.name!r}, year={self.year}, format={self.format.value!r}, hours={self.hours}, path={str(self.path)!r})"
