"""Optional browsable GeoNames cities500 directory, cached as SQLite.

This is a directory of the cities in a published dataset, not a claim that
every named settlement on Earth is present. Open-Meteo search can find places
outside this directory. No catalog is downloaded on import.
"""

from __future__ import annotations

from contextlib import closing
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterator
import unicodedata
from urllib.error import URLError
from urllib.request import Request, urlopen
import zipfile

from ._files import atomic_text, default_cache_dir
from ._version import __version__
from .exceptions import CatalogError, OutputExistsError, ValidationError
from .locations import validate_country
from .models import Location

CATALOG_URL = "https://download.geonames.org/export/dump/cities500.zip"
SOURCE_LICENCE = "https://creativecommons.org/licenses/by/4.0/"
SCHEMA_VERSION = 1
SELECT_COLUMNS = (
    "name, admin1, country, country_code, latitude, longitude, elevation, timezone, geonames_id, population"
)


def _normalized(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value).casefold()
        if not unicodedata.combining(character)
    )


def _download_archive(path: Path) -> None:
    temporary = None
    try:
        request = Request(CATALOG_URL, headers={"User-Agent": f"pyEPW/{__version__}"})
        with urlopen(request, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".zip.tmp", delete=False) as stream:
                temporary = Path(stream.name)
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 128 * 1024 * 1024:
                        raise CatalogError("The city archive exceeded the 128 MiB download limit.")
                    stream.write(chunk)
        os.replace(temporary, path)
    except (URLError, TimeoutError, OSError) as exc:
        raise CatalogError(f"Cannot download the GeoNames city directory: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _build_database(archive: Path, destination: Path) -> int:
    """Read the known member in place; never extract arbitrary archive paths."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".sqlite.tmp", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(archive) as zipped:
            if zipped.getinfo("cities500.txt").file_size > 512 * 1024 * 1024:
                raise CatalogError("The uncompressed city directory exceeds the 512 MiB limit.")
            with closing(sqlite3.connect(temporary)) as database:
                database.execute("""CREATE TABLE cities (
                    name TEXT, admin1 TEXT, country TEXT, country_code TEXT,
                    latitude REAL, longitude REAL, elevation REAL, timezone TEXT,
                    geonames_id INTEGER PRIMARY KEY, population INTEGER, search_name TEXT
                )""")
                with zipped.open("cities500.txt") as source:
                    reader = csv.reader(io.TextIOWrapper(source, encoding="utf-8"), delimiter="\t")
                    batch = []
                    count = 0
                    for row in reader:
                        if len(row) != 19:
                            raise CatalogError("The GeoNames city schema has changed or the archive is incomplete.")
                        if row[6] != "P" or not row[17]:
                            continue
                        elevation = row[15] or row[16]
                        elevation = float(elevation) if elevation and elevation != "-32768" else None
                        batch.append(
                            (
                                row[1],
                                row[10],
                                row[8],
                                row[8],
                                float(row[4]),
                                float(row[5]),
                                elevation,
                                row[17],
                                int(row[0]),
                                int(row[14] or 0),
                                _normalized(row[1] + " " + row[2]),
                            )
                        )
                        count += 1
                        if len(batch) == 5000:
                            database.executemany("INSERT INTO cities VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
                            batch.clear()
                    if batch:
                        database.executemany("INSERT INTO cities VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
                if count == 0:
                    raise CatalogError("The GeoNames archive contained no usable cities.")
                database.execute("CREATE INDEX cities_country_name ON cities(country_code, name COLLATE NOCASE)")
                database.execute("CREATE INDEX cities_name ON cities(name COLLATE NOCASE)")
                database.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                database.commit()
        os.replace(temporary, destination)
        return count
    except (zipfile.BadZipFile, KeyError, UnicodeError, ValueError, sqlite3.Error) as exc:
        raise CatalogError(f"Cannot build the GeoNames city catalog: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CityCatalog:
    """Browse all names in the optional GeoNames cities500 dataset.

    Obtain a cached catalog with ``CityCatalog.download()``. It includes cities
    with population over 500 and specified administrative seats; it is not an
    exhaustive list of every settlement. Country/region values use the source's
    ISO/admin codes. Names, coordinates and timezones can be used directly with
    EPW by passing a returned Location.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise CatalogError("Catalog not found. Use CityCatalog.download() first.")
        try:
            with closing(sqlite3.connect(self.path)) as database:
                if database.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise CatalogError("Catalog schema is incompatible; download it with refresh=True.")
                database.execute("SELECT COUNT(*) FROM cities").fetchone()
        except sqlite3.Error as exc:
            raise CatalogError("City catalog is corrupt; download it with refresh=True.") from exc

    @classmethod
    def download(cls, *, cache_dir: str | Path | None = None, refresh: bool = False) -> CityCatalog:
        """Download the free directory once; later calls reuse the local SQLite file."""
        cache = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
        destination = cache / "geonames-cities500.sqlite3"
        if destination.exists() and not refresh:
            return cls(destination)
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "geonames-cities500.zip"
        if not archive.exists() or refresh:
            _download_archive(archive)
        count = _build_database(archive, destination)
        atomic_text(
            destination.with_suffix(".metadata.json"),
            json.dumps(
                {
                    "source": CATALOG_URL,
                    "licence": SOURCE_LICENCE,
                    "credit": "GeoNames",
                    "coverage": "cities500: population >500 or qualifying administrative seats; not every settlement",
                    "rows": count,
                    "downloaded_utc": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
        )
        return cls(destination)

    def __len__(self) -> int:
        with closing(sqlite3.connect(self.path)) as database:
            return database.execute("SELECT COUNT(*) FROM cities").fetchone()[0]

    def iter_cities(
        self, *, country: str | None = None, query: str | None = None, limit: int | None = None
    ) -> Iterator[Location]:
        """Iterate alphabetically; limit=None returns every matching catalog row."""
        country = validate_country(country)
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise ValidationError("limit must be a positive integer or None.")
        if query is not None and not isinstance(query, str):
            raise ValidationError("query must be a string or None.")
        clauses, values = [], []
        if country:
            clauses.append("country_code=?")
            values.append(country)
        if query:
            clauses.append("search_name LIKE ? ESCAPE '\\'")
            term = _normalized(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append("%" + term + "%")
        sql = "SELECT " + SELECT_COLUMNS + " FROM cities"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name COLLATE NOCASE, country_code, geonames_id"
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        with closing(sqlite3.connect(self.path)) as database:
            for row in database.execute(sql, values):
                yield Location(*row)

    def names(self, *, country: str | None = None) -> Iterator[str]:
        """Yield every catalog display name, optionally restricted to a country."""
        for location in self.iter_cities(country=country):
            yield location.display_name

    def search(self, query: str, *, country: str | None = None, limit: int = 20) -> tuple[Location, ...]:
        """Search names/ascii names locally, without another network request."""
        return tuple(self.iter_cities(country=country, query=query, limit=limit))

    def export(self, path: str | Path, *, country: str | None = None, overwrite: bool = False) -> Path:
        """Export every matching city as UTF-8 CSV, with a GeoNames credit sidecar."""
        target = Path(path).expanduser().resolve()
        country = validate_country(country)
        if target.suffix.lower() != ".csv":
            raise ValidationError("City catalog export must use a .csv extension.")
        sidecar = target.with_name(target.name + ".metadata.json")
        if not overwrite and (target.exists() or sidecar.exists()):
            raise OutputExistsError(f"Output already exists: {target}.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=target.parent, suffix=".csv.tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(SELECT_COLUMNS.split(", "))
                count = 0
                for location in self.iter_cities(country=country):
                    writer.writerow(
                        (
                            location.name,
                            location.admin1,
                            location.country,
                            location.country_code,
                            location.latitude,
                            location.longitude,
                            location.elevation,
                            location.timezone,
                            location.geonames_id,
                            location.population,
                        )
                    )
                    count += 1
            os.replace(temporary, target)
            atomic_text(
                sidecar,
                json.dumps(
                    {
                        "credit": "GeoNames",
                        "source": CATALOG_URL,
                        "licence": SOURCE_LICENCE,
                        "rows": count,
                        "country": country,
                        "coverage": "cities500 dataset; not an exhaustive list of every settlement",
                    },
                    indent=2,
                )
                + "\n",
            )
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target


def cities(*, country: str | None = None, cache_dir: str | Path | None = None) -> Iterator[Location]:
    """Iterate all catalog cities; first iteration downloads the optional directory.

    Example: ``for city in cities(country='IE'): print(city)``.
    Use search_cities() for the live service's wider search coverage.
    """
    country = validate_country(country)
    yield from CityCatalog.download(cache_dir=cache_dir).iter_cities(country=country)
