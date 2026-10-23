"""Actual-year examples on six continents; downloads occur only when run."""

from __future__ import annotations

import argparse
from pathlib import Path

import pyEPW

CASES = {
    "Europe": ("Dublin, Ireland", "IE"),
    "Africa": ("Cape Town, South Africa", "ZA"),
    "Asia": ("Tokyo, Japan", "JP"),
    "North America": ("New York City, United States", "US"),
    "South America": ("Santiago, Chile", "CL"),
    "Oceania": ("Sydney, Australia", "AU"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continent", choices=["all", *CASES], default="Europe")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--output-dir", type=Path, default=Path("output/continents"))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    selected = CASES if args.continent == "all" else {args.continent: CASES[args.continent]}
    for continent, (city, country) in selected.items():
        weather = pyEPW.EPW(
            city,
            args.year,
            ".epw",
            country=country,
            output_dir=args.output_dir,
            cache_dir=args.cache_dir,
            overwrite=args.overwrite,
        )
        print(continent, weather.path, weather.to_csv(overwrite=args.overwrite))
        print("Hours:", weather.hours, "Remaining missing hours:", weather.missing_fields)


if __name__ == "__main__":
    main()
