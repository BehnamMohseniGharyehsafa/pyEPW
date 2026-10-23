"""Command-line interface for weather exports and city discovery."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from ._version import __version__
from .api import EPW
from .catalog import CityCatalog
from .exceptions import PyEPWError, ValidationError
from .locations import search_cities, validate_country


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="pyEPW",
        description="Actual-year EPW, TXT, and CSV weather files.",
        epilog=(
            "Examples:\n  pyEPW 'Dublin, Ireland' 2024 --format epw\n"
            "  pyEPW cities Dublin --country IE\n"
            "  pyEPW cities --output all_cities.csv\n"
            "Public Open-Meteo access is free for non-commercial use."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subs = result.add_subparsers(dest="command")
    export = subs.add_parser("export", help="Create an actual-year weather file")
    export.add_argument("city", nargs="?")
    export.add_argument("year", nargs="?")
    export.add_argument("--city", dest="city_option")
    export.add_argument("--year", dest="year_option")
    export.add_argument("--format", default="epw", help="epw, txt, or csv (default: epw)")
    export.add_argument("--country", help="Two-letter country filter")
    export.add_argument("--match", type=int, default=1)
    export.add_argument("--list-locations", action="store_true", help="Legacy alias for city search")
    export.add_argument("--output-dir", type=Path, default=Path("output"))
    export.add_argument("--output", type=Path)
    export.add_argument("--cache-dir", type=Path)
    export.add_argument("--utc-offset", type=float)
    export.add_argument("--refresh", action="store_true")
    export.add_argument("--no-snow", action="store_true")
    export.add_argument("--basic", action="store_true", help="Omit the additional calculated/supplemental fields")
    export.add_argument(
        "--no-free-fallbacks",
        action="store_true",
        help="Disable NASA albedo, snow history and additional station archives",
    )
    export.add_argument(
        "--no-metar-fallback", action="store_true", help="Exclude minimally QC-reviewed published METAR gap fills"
    )
    export.add_argument(
        "--require-complete",
        action="store_true",
        help="Reject output if any canonical weather column has missing hours",
    )
    export.add_argument("--station", default="auto", help="GHCNh station ID, auto (default), or none")
    export.add_argument("--max-station-distance-km", type=float, default=30)
    export.add_argument("--station-tolerance-minutes", type=float, default=15)
    export.add_argument(
        "--require-field", action="append", default=[], help="Require every hour of this named field; repeatable"
    )
    export.add_argument(
        "--quality-report", action="store_true", help="Print supplemental field completeness and source classes"
    )
    export.add_argument("--overwrite", action="store_true")
    export.add_argument("--verbose", action="store_true")
    directory = subs.add_parser("cities", help="Search or browse/export the GeoNames city catalog")
    directory.add_argument("query", nargs="?", help="Omit to browse the optional global catalog")
    directory.add_argument("--country")
    directory.add_argument("--limit", type=int, default=20)
    directory.add_argument("--output", type=Path, help="Export catalog cities as CSV")
    directory.add_argument("--cache-dir", type=Path)
    directory.add_argument("--refresh", action="store_true")
    directory.add_argument("--overwrite", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = parser()
    if arguments and arguments[0] not in ("export", "cities", "--help", "-h", "--version"):
        arguments.insert(0, "export")
    args = root.parse_args(arguments)
    if args.command is None:
        root.print_help()
        return 0
    try:
        args.country = validate_country(args.country)
        if args.command == "cities":
            if args.limit < 1:
                raise ValidationError("--limit must be positive.")
            if args.query:
                if args.output:
                    raise ValidationError("For catalog export, omit the query; optionally use --country.")
                matches = search_cities(
                    args.query,
                    country=args.country,
                    limit=min(args.limit, 100),
                    cache_dir=args.cache_dir,
                    refresh=args.refresh,
                )
            else:
                catalog = CityCatalog.download(cache_dir=args.cache_dir, refresh=args.refresh)
                if args.output:
                    print(catalog.export(args.output, country=args.country, overwrite=args.overwrite))
                    return 0
                print(f"GeoNames cities500: {len(catalog):,} locations; showing up to {args.limit}.")
                matches = catalog.iter_cities(country=args.country, limit=args.limit)
            for index, location in enumerate(matches, 1):
                print(f"{index}. {location} ({location.latitude:.5f}, {location.longitude:.5f})")
            return 0
        city, year = args.city_option or args.city, args.year_option or args.year
        if not city:
            raise ValidationError("Provide a city, e.g. pyEPW 'Dublin, Ireland' 2024")
        if args.list_locations:
            for index, location in enumerate(search_cities(city, country=args.country, cache_dir=args.cache_dir), 1):
                print(f"{index}. {location} ({location.latitude:.5f}, {location.longitude:.5f})")
            return 0
        if year is None:
            raise ValidationError("Provide a completed calendar year, such as 2024.")
        if args.verbose:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        weather = EPW(
            city,
            year,
            args.format,
            output_dir=args.output_dir,
            output=args.output,
            country=args.country,
            match=args.match,
            cache_dir=args.cache_dir,
            overwrite=args.overwrite,
            include_snow=not args.no_snow,
            utc_offset=args.utc_offset,
            refresh=args.refresh,
            include_additional_fields=not args.basic,
            station=None if args.station.lower() == "none" else args.station,
            max_station_distance_km=args.max_station_distance_km,
            station_tolerance_minutes=args.station_tolerance_minutes,
            require_fields=args.require_field,
            use_free_fallbacks=not args.no_free_fallbacks,
            allow_metar_fallback=not args.no_metar_fallback,
            require_complete=args.require_complete,
        )
        print(f"Created {weather.path}\n{weather.hours:,} records for {weather.year}; {weather.location}")
        print(f"Metadata: {weather.metadata_path}")
        if args.quality_report:
            print(weather.quality_report())
        return 0
    except (PyEPWError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
