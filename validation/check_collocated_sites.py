"""Three post-hoc 2024 diagnostics at observation-site coordinates.

These do not replace city-center benchmark results. They help distinguish site
representation from conversion errors after large city/airport differences.
"""

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from analyze_global_study import ROOT, metrics, parse_isd, read_epw
from run_global_study import CACHE, instrument_client
from pyEPW import EPW, Location


def run(row):
    country = row["country"]
    location = Location(
        name=row["city"] + " airport diagnostic",
        admin1="",
        country=row["country"],
        country_code=country,
        latitude=row["station_latitude"],
        longitude=row["station_longitude"],
        elevation=row["station_elevation_m"],
        timezone=row["timezone"],
        geonames_id=0,
    )
    obj = EPW(
        location,
        2024,
        output_dir=ROOT / "collocated_2024",
        cache_dir=CACHE,
        include_snow=False,
        include_additional_fields=False,
        overwrite=True,
    )
    model, meta, a, headers = read_epw(obj.path)
    obs = parse_isd(ROOT / "observations" / f"{row['station']}-2024.gz", meta["utc_offset_hours"]).reindex(model.index)
    results = []
    for key in ["temperature_c", "wind_ms", "pressure_hpa"]:
        results.append(
            {
                "country": country,
                "site": "station coordinates",
                "variable": key,
                **metrics(model[key], obs[key], len(model)),
            }
        )
    for lag in range(-3, 4):
        results.append(
            {
                "country": country,
                "site": "station coordinates",
                "variable": "temperature_lag",
                "observation_shift_hours": lag,
                **metrics(model.temperature_c, obs.temperature_c.shift(lag), len(model)),
            }
        )
    print(country, "collocated diagnostic completed", flush=True)
    return results


if __name__ == "__main__":
    stations = pd.read_csv(ROOT / "stations.csv")
    instrument_client()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, stations[stations.country.isin(["US", "JP", "AU"])].to_dict("records")))
    pd.DataFrame([x for group in results for x in group]).to_csv(ROOT / "collocated_diagnostics.csv", index=False)
