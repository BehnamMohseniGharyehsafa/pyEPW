"""Run every generated EPW through a full actual-year EnergyPlus simulation.

Uses the locally installed open-source EnergyPlus 25.1 and its supplied one-zone
example. This checks file/calendar compatibility, not building-model accuracy.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "output" / "validation_10cities_20years"
INSTALL = Path(os.environ.get("ENERGYPLUS_INSTALL", r"C:\EnergyPlusV25-1-0"))
OUT = ROOT / "energyplus"
OUT.mkdir(exist_ok=True)


def run(cp):
    status = json.loads(cp.read_text())
    if not status.get("success"):
        return None
    year, country = status["year"], status["country"]
    folder = OUT / f"{country}_{year}"
    folder.mkdir(exist_ok=True)
    summary_file = folder / "check.json"
    if summary_file.exists():
        previous = json.loads(summary_file.read_text())
        if previous.get("pass"):
            return previous
    epw = Path(status["path"])
    meta = json.loads(epw.with_suffix(".epw.metadata.json").read_text(encoding="utf-8"))
    source = (INSTALL / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text(encoding="utf-8")
    source = re.sub(r"(?mi)^\s*SimulationControl\s*,[^;]*;", "\nSimulationControl,No,No,No,No,Yes;", source)
    source = re.sub(r"(?mi)^\s*SizingPeriod:DesignDay\s*,[^;]*;", "", source)
    source = re.sub(
        r"(?mi)^\s*RunPeriod\s*,[^;]*;",
        f"\nRunPeriod,Actual year {year},1,1,{year},12,31,{year},,No,No,No,Yes,Yes,Yes,Hour1;",
        source,
    )
    c = meta["city"]
    source = re.sub(
        r"(?mi)^\s*Site:Location\s*,[^;]*;",
        f"\nSite:Location,Test site,{c['latitude']},{c['longitude']},{meta['utc_offset_hours']},{c['elevation']};",
        source,
    )
    source = re.sub(r"(?mi)^\s*Output:SQLite\s*,[^;]*;", "", source)
    source += "\nOutput:SQLite,Simple;\nOutput:Variable,*,Site Outdoor Air Drybulb Temperature,Hourly;\n"
    model = folder / "check.idf"
    model.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            str(INSTALL / ("energyplus.exe" if os.name == "nt" else "energyplus")),
            "-w",
            str(epw),
            "-d",
            str(folder),
            str(model),
        ],
        capture_output=True,
        text=True,
    )
    errors = (folder / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    record = {
        "country": country,
        "year": year,
        "exit_code": result.returncode,
        "completed_successfully": "Completed Successfully" in errors,
        "warning_messages": len(re.findall(r"\*\* Warning \*\*", errors)),
        "severe_errors": len(re.findall(r"\*\* Severe\s+\*\*", errors)),
        "expected_hours": meta["rows"],
        "actual_weather_mode": True,
    }
    sql = folder / "eplusout.sql"
    if sql.exists():
        db = sqlite3.connect(sql)
        try:
            row = db.execute(
                "SELECT count(*) FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name='Site Outdoor Air Drybulb Temperature' AND d.ReportingFrequency='Hourly' AND COALESCE(t.WarmupFlag,0)=0"
            ).fetchone()
            record["simulated_weather_hours"] = row[0]
        finally:
            db.close()
    record["pass"] = (
        record["completed_successfully"]
        and record["exit_code"] == 0
        and record.get("simulated_weather_hours") == record["expected_hours"]
    )
    summary_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # Retain reproducible input, complete errors and summary. These are exact
    # files created in this job's own output folder; large solver intermediates
    # can be regenerated from the retained input and EPW.
    for file in folder.iterdir():
        if file.name not in {"check.idf", "check.json", "eplusout.err"} and file.is_file():
            file.unlink()
    print(
        country,
        year,
        record["pass"],
        record.get("simulated_weather_hours"),
        "warnings",
        record["warning_messages"],
        flush=True,
    )
    return record


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [x for x in pool.map(run, sorted((ROOT / "checkpoints").glob("*.json"))) if x]
    (ROOT / "energyplus_checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Simulations", len(results), "passed", sum(x["pass"] for x in results), flush=True)
