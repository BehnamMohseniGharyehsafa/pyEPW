"""Post-hoc source/selection diagnostics; kept separate from default-option results."""

from datetime import date
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyEPW import EPW, Location, api
from pyEPW.client import APIClient, ARCHIVE_URL
from extended_common import ROOT, CACHE, WATER, FreeRateGate, StudyClient, baseline, bulk_parameters


def main():
    diagnostics = []
    gate = FreeRateGate()
    for start, end in (("2024-01-01", "2024-01-31"), ("2024-07-01", "2024-07-31")):
        parameters = {**bulk_parameters("DE"), "start_date": start, "end_date": end}
        from urllib.parse import urlencode

        url = ARCHIVE_URL + "?" + urlencode(parameters)
        cached = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if not cached.exists():
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            gate.reserve(max(1, 0.1 * days / 14))
        response = APIClient(CACHE).get(ARCHIVE_URL, parameters)
        values = response["hourly"][WATER]
        diagnostics.append(
            {
                "kind": "direct_monthly_water_probe",
                "country": "DE",
                "start": start,
                "end": end,
                "valid_values": sum(v is not None for v in values),
                "hours": len(values),
                "url": url,
                "sha256": hashlib.sha256(cached.read_bytes()).hexdigest(),
            }
        )
    # An explicit station can test a selector limitation without changing the
    # library or quietly replacing the declared default test set.
    StudyClient.country = "ES"
    api.APIClient = StudyClient
    _, meta = baseline("ES", 2024)
    alternative = EPW(
        Location(**meta["city"]),
        2024,
        output_dir=ROOT / "diagnostics/madrid_barajas_2024",
        cache_dir=CACHE,
        include_snow=False,
        station="SPMU0098221",
        overwrite=True,
    )
    alternative.to_csv(overwrite=True)
    reference = json.loads((ROOT / "checkpoints/ES_2024.json").read_text(encoding="utf-8"))
    with Path(reference["path"]).open(newline="") as stream:
        default_rows = list(csv.reader(stream))[8:]
    unaffected = [i for i in range(35) if i not in (5, 24, 25)]
    assert all(all(a[i] == b[i] for i in unaffected) for a, b in zip(alternative.data, default_rows))
    diagnostics.append(
        {
            "kind": "explicit_station",
            "country": "ES",
            "year": 2024,
            "station": "SPMU0098221",
            "station_name": "Madrid Barajas",
            "path": str(alternative.path),
            "default_visibility_hours": reference["coverage"]["visibility_km"]["valid_hours"],
            "explicit_visibility_hours": alternative.field_coverage["visibility_km"]["valid_hours"],
            "default_ceiling_hours": reference["coverage"]["ceiling_height_m"]["valid_hours"],
            "explicit_ceiling_hours": alternative.field_coverage["ceiling_height_m"]["valid_hours"],
            "all_other_weather_columns_unchanged": True,
            "interpretation": "Post-hoc station-selection diagnostic; does not replace the default 200-file benchmark.",
        }
    )
    (ROOT / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    print(json.dumps(diagnostics, indent=2), flush=True)


if __name__ == "__main__":
    main()
