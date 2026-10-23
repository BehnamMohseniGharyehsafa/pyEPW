"""Download the public national-service inputs used by this validation study."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import requests

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "output" / "validation_10cities_20years"
OUT = ROOT / "national_sources"
OUT.mkdir(parents=True, exist_ok=True)
DWD = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/"
SOURCES = {
    "dublin_hly532.csv": "https://clidata.met.ie/cli/climate_data/webdata/hly532.csv",
    "phoenix_hly175.csv": "https://clidata.met.ie/cli/climate_data/webdata/hly175.csv",
    "frankfurt_temperature.zip": DWD
    + "hourly/air_temperature/historical/stundenwerte_TU_01420_19810101_20251231_hist.zip",
    "dwd_solar10_description.pdf": DWD + "10_minutes/solar/DESCRIPTION_obsgermany_climate_10min_solar_en.pdf",
    "jma_tokyo_annual.html": "https://www.data.jma.go.jp/stats/etrn/view/annually_s.php?prec_no=44&block_no=47662&year=&month=&day=&view=",
}
for start, end in [("20000101", "20091231"), ("20100101", "20191231"), ("20200101", "20251231")]:
    SOURCES[f"frankfurt_solar10_{start}_{end}.zip"] = (
        DWD + f"10_minutes/solar/historical/10minutenwerte_SOLAR_01420_{start}_{end}_hist.zip"
    )
for month in range(1, 13):
    SOURCES[f"toronto_5097_2005_{month:02d}.csv"] = (
        f"https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID=5097&Year=2005&Month={month}&Day=1&timeframe=1&submit=Download+Data"
    )


def main():
    manifest = []
    for name, url in SOURCES.items():
        path = OUT / name
        if not path.exists():
            r = requests.get(url, timeout=180)
            r.raise_for_status()
            path.write_bytes(r.content)
        manifest.append(
            {
                "file": name,
                "source_url": url,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    dataset = "d_b16d06b83473fdfcc92ed9d37b66ba58"
    url = f"https://api-open.data.gov.sg/v1/public/api/datasets/{dataset}/poll-download"
    path = OUT / "singapore_monthly_rain.csv"
    if not path.exists():
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        result = r.json()
        if not result.get("data", {}).get("url"):
            r = requests.get(
                f"https://api-open.data.gov.sg/v1/public/api/datasets/{dataset}/initiate-download", timeout=60
            )
            r.raise_for_status()
            for _ in range(20):
                time.sleep(3)
                r = requests.get(url, timeout=60)
                r.raise_for_status()
                result = r.json()
                if result.get("data", {}).get("url"):
                    break
        r = requests.get(result["data"]["url"], timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    manifest.append(
        {
            "file": path.name,
            "source_url": url,
            "dataset_page": f"https://data.gov.sg/datasets/{dataset}/view",
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
    provenance = {
        "manifest_created_utc": datetime.now(timezone.utc).isoformat(),
        "files": manifest,
        "met_eireann_attribution": {
            "copyright": "Copyright Met Éireann",
            "source": "https://www.met.ie/",
            "licence": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
            "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "modifications": "Source download unchanged. Analysis filters 2005–2024, applies quality indicators and converts knots to m/s.",
            "disclaimer": "Met Éireann does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use.",
        },
        "other_credit": "Deutscher Wetterdienst (DWD); Japan Meteorological Agency (JMA); Environment and Climate Change Canada; National Environment Agency, Singapore (Singapore Open Data Licence).",
    }
    (OUT / "sources_manifest.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
    print("National input files recorded:", len(manifest))


if __name__ == "__main__":
    main()
