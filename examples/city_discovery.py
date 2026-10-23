"""Search online, then optionally export the separately downloaded directory."""

import pyEPW


def main() -> None:
    print(pyEPW.help())
    for city in pyEPW.search_cities("Dublin", country="IE"):
        print(city, city.latitude, city.longitude)
    catalog = pyEPW.CityCatalog.download()
    print(f"Catalog: {len(catalog):,} cities and administrative seats")
    print(catalog.export("output/all_cities.csv"))


if __name__ == "__main__":
    main()
