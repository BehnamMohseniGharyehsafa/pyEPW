"""Immutable location and weather containers, output formats, and column names."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .exceptions import ValidationError


class OutputFormat(str, Enum):
    """Supported file extensions; strings such as '.CSV' are also accepted."""

    EPW = "epw"
    TXT = "txt"
    CSV = "csv"

    @classmethod
    def parse(cls, value: str | OutputFormat) -> OutputFormat:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower().removeprefix("."))
            except ValueError:
                pass
        raise ValidationError("format must be 'epw', 'txt', or 'csv' (with or without a leading dot).")


@dataclass(frozen=True)
class Location:
    """A city/site with WGS84 coordinates and an IANA timezone.

    Returned by search_cities() and CityCatalog. A Location can also be passed
    directly to EPW(), which avoids a second city-name lookup.
    """

    name: str
    admin1: str
    country: str
    country_code: str
    latitude: float
    longitude: float
    elevation: float | None
    timezone: str
    geonames_id: int
    population: int = 0

    @property
    def display_name(self) -> str:
        """Human-readable city, region, and country."""
        return ", ".join(part for part in (self.name, self.admin1, self.country) if part)

    def __str__(self) -> str:
        return self.display_name


@dataclass(frozen=True)
class WeatherDataset:
    """Internal immutable record structure shared by every output writer."""

    location: Location
    year: int
    headers: tuple[tuple[str, ...], ...]
    rows: tuple[tuple[str, ...], ...]
    metadata: dict[str, Any]


EPW_COLUMNS: tuple[str, ...] = (
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "data_source_and_uncertainty_flags",
    "dry_bulb_temperature_c",
    "dew_point_temperature_c",
    "relative_humidity_percent",
    "atmospheric_station_pressure_pa",
    "extraterrestrial_horizontal_radiation_wh_m2",
    "extraterrestrial_direct_normal_radiation_wh_m2",
    "horizontal_infrared_radiation_wh_m2",
    "global_horizontal_radiation_wh_m2",
    "direct_normal_radiation_wh_m2",
    "diffuse_horizontal_radiation_wh_m2",
    "global_horizontal_illuminance_lux",
    "direct_normal_illuminance_lux",
    "diffuse_horizontal_illuminance_lux",
    "zenith_luminance_cd_m2",
    "wind_direction_degrees",
    "wind_speed_m_s",
    "total_sky_cover_tenths",
    "opaque_sky_cover_tenths",
    "visibility_km",
    "ceiling_height_m",
    "present_weather_observation",
    "present_weather_codes",
    "precipitable_water_mm",
    "aerosol_optical_depth",
    "snow_depth_cm",
    "days_since_last_snowfall",
    "albedo",
    "liquid_precipitation_depth_mm",
    "liquid_precipitation_quantity_hours",
)
