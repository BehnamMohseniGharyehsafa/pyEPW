"""Start independent checks as each country's complete twenty-year set is ready."""

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extended_common import ROOT, CITIES, YEARS
from analyze_extended_study import cached_city, main as consolidate
from check_extended_solar import prepare_reference, run as check_solar
import check_global_energyplus as solver


def finish_country(city):
    country = city["country"]
    result_path = ROOT / "audits" / f"{country}_complete.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    cached_city(city)
    solar = check_solar(city)
    pd.DataFrame(solar).to_csv(ROOT / "audits" / f"{country}_solar.csv", index=False)
    solver.ROOT = ROOT
    solver.OUT = ROOT / "energyplus"
    solver.OUT.mkdir(exist_ok=True)
    energy = []
    for year in YEARS:
        checkpoint = ROOT / "checkpoints" / f"{country}_{year}.json"
        cp = json.loads(checkpoint.read_text(encoding="utf-8"))
        digest = hashlib.sha256(Path(cp["path"]).read_bytes()).hexdigest()
        summary_path = solver.OUT / f"{country}_{year}" / "check.json"
        if summary_path.exists() and json.loads(summary_path.read_text()).get("epw_sha256") != digest:
            summary_path.unlink()
        summary = solver.run(checkpoint)
        assert summary["pass"] and not summary["severe_errors"], summary
        summary.update(epw_sha256=digest, package_version="0.2.0")
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        energy.append(summary)
    result = {"country": country, "complete": True, "energyplus": energy, "solar": solar}
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(country, "all source, local-station, solar and 20 solver checks complete", flush=True)
    return result


def main():
    prepare_reference()
    scheduled, results = set(), []
    with ProcessPoolExecutor(max_workers=2) as pool:
        pending = {}
        while len(results) < 10:
            for city in CITIES:
                country = city["country"]
                if country in scheduled:
                    continue
                files = [ROOT / "checkpoints" / f"{country}_{year}.json" for year in YEARS]
                if all(path.exists() and json.loads(path.read_text(encoding="utf-8")).get("success") for path in files):
                    pending[pool.submit(finish_country, city)] = country
                    scheduled.add(country)
                    print(country, "twenty-year set ready; independent checks queued", flush=True)
            for future in list(pending):
                if future.done():
                    results.append(future.result())
                    del pending[future]
            if len(results) < 10:
                time.sleep(5)
    # consolidate() uses completed per-country audit checkpoints, with no new
    # downloads or repetition of already passed source checks.
    consolidate()
    energy = [record for result in results for record in result["energyplus"]]
    solar = [record for result in results for record in result["solar"]]
    (ROOT / "energyplus_checks.json").write_text(json.dumps(energy, indent=2), encoding="utf-8")
    pd.DataFrame(solar).to_csv(ROOT / "solar_reference_checks.csv", index=False)
    assert len(energy) == len(solar) == 200
    print("All 200 current-version EPWs and independent checks are complete.", flush=True)


if __name__ == "__main__":
    main()
