"""Worldwide city lookup through Open-Meteo's GeoNames-backed search."""

from __future__ import annotations

from pathlib import Path
import re

from .client import APIClient, GEOCODING_URL
from .exceptions import APIError, ValidationError
from .models import Location


def validate_country(country: str | None) -> str | None:
    if country is not None:
        if not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2}", country):
            raise ValidationError("country must be a two-letter country code, such as IE or US.")
        return country.upper()
    return None


def _search(client: APIClient, query: str, country: str | None, limit: int) -> tuple[Location, ...]:
    if not isinstance(query, str) or len(query.strip()) < 2:
        raise ValidationError("City search needs at least two characters, such as 'Dublin'.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValidationError("limit must be an integer between 1 and 100.")
    country = validate_country(country)
    parameters = {"name": query.strip(), "count": limit, "language": "en", "format": "json"}
    if country:
        parameters["countryCode"] = country
    response = client.get(GEOCODING_URL, parameters)
    matches = []
    try:
        for item in response.get("results", []):
            if not item.get("timezone"):
                continue
            matches.append(
                Location(
                    name=item["name"],
                    admin1=item.get("admin1", ""),
                    country=item.get("country", ""),
                    country_code=item.get("country_code", ""),
                    latitude=float(item["latitude"]),
                    longitude=float(item["longitude"]),
                    elevation=float(item["elevation"]) if item.get("elevation") is not None else None,
                    timezone=item["timezone"],
                    geonames_id=int(item["id"]),
                    population=int(item.get("population", 0)),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise APIError("The city-search service returned malformed location data.") from exc
    return tuple(matches)


def search_cities(
    query: str,
    *,
    country: str | None = None,
    limit: int = 10,
    cache_dir: str | Path | None = None,
    refresh: bool = False,
) -> tuple[Location, ...]:
    """Find matching cities by name, coordinates, country, and timezone.

    Parameters
    ----------
    query : str
        Name or prefix, optionally qualified: ``'Paris, France'``.
    country : str, optional
        ISO two-letter country filter, such as ``'FR'`` or ``'IE'``.
    limit : int
        Maximum results, from 1 to 100. Default is 10.
    cache_dir : str or pathlib.Path, optional
        Override the user cache directory.
    refresh : bool
        Ignore an existing cached response.

    Returns
    -------
    tuple[Location, ...]
        Ranked city matches. An empty tuple means no matching city was found.

    Notes
    -----
    This function may access the free public geocoding service. It does not
    download weather. Use CityCatalog/cities() for a browsable city directory.
    """
    return _search(APIClient(cache_dir, refresh), query, country, limit)
