"""Offline regression tests. All generated weather is synthetic and temporary."""

from contextlib import redirect_stdout, redirect_stderr
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyEPW import _engine as epw
from pyEPW import api
from pyEPW.cli import main
from pyEPW.client import GEOCODING_URL
from pyEPW.supplements import POWER_HOURLY
from pyEPW.exceptions import OutputExistsError
from pyEPW.exceptions import APIError


class FakeClient:
    """Serve complete UTC days with identifiable hour-ending radiation values."""

    def __init__(self, missing_core=False, fail_snow=False, wrong_units=False):
        self.urls = []
        self.missing_core = missing_core
        self.fail_snow = fail_snow
        self.wrong_units = wrong_units

    def get(self, endpoint, parameters):
        self.urls.append(endpoint + "?synthetic-test-only")
        if endpoint == POWER_HOURLY:
            first = datetime.strptime(parameters["start"], "%Y%m%d").replace(tzinfo=timezone.utc)
            finish = datetime.strptime(parameters["end"], "%Y%m%d").replace(tzinfo=timezone.utc)
            values = {
                (first + timedelta(hours=i)).strftime("%Y%m%d%H"): 0.2
                for i in range(int((finish - first).total_seconds() / 3600) + 24)
            }
            return {
                "header": {"time_standard": "UTC", "fill_value": -999},
                "parameters": {"ALLSKY_SRF_ALB": {"units": "dimensionless"}},
                "properties": {"parameter": {"ALLSKY_SRF_ALB": values}},
            }
        if endpoint == GEOCODING_URL:
            return {
                "results": [
                    {
                        "id": 2964574,
                        "name": "Dublin",
                        "admin1": "Leinster",
                        "country": "Ireland",
                        "country_code": "IE",
                        "latitude": 53.35,
                        "longitude": -6.26,
                        "elevation": 20,
                        "timezone": "Europe/Dublin",
                    }
                ]
            }
        snow = parameters["models"] == "era5_land"
        if snow and self.fail_snow:
            raise epw.WeatherError("Synthetic optional snow failure")
        start = date.fromisoformat(parameters["start_date"])
        finish = date.fromisoformat(parameters["end_date"])
        count = ((finish - start).days + 1) * 24
        first = datetime.combine(start, datetime.min.time(), timezone.utc)
        stamps = [int((first + timedelta(hours=n)).timestamp()) for n in range(count)]
        all_units = {**epw.CORE_UNITS, **epw.WATER_UNITS, "snow_depth": "m", "snowfall": "cm"}
        units = {name: all_units[name] for name in parameters["hourly"].split(",")}
        if self.wrong_units and not snow:
            units["wind_speed_10m"] = "km/h"
        constants = {
            "temperature_2m": 15.0,
            "dew_point_2m": 10.0,
            "relative_humidity_2m": 72.0,
            "surface_pressure": 1013.25,
            "wind_speed_10m": 3.0,
            "wind_direction_10m": 350.0,
            "cloud_cover": 50.0,
            "rain": 1.5,
            "snow_depth": 0.02,
            "total_column_integrated_water_vapour": 20.0,
            "snowfall": 0.0,
        }
        hourly = {"time": stamps}
        for variable in units:
            if variable in epw.RADIATION:
                hourly[variable] = [float((first + timedelta(hours=n)).hour) for n in range(count)]
            else:
                hourly[variable] = [constants[variable]] * count
        missing_stamp = int(datetime(2023, 1, 1, 1, tzinfo=timezone.utc).timestamp())
        if self.missing_core and not snow and missing_stamp in stamps and "temperature_2m" in hourly:
            hourly["temperature_2m"][stamps.index(missing_stamp)] = None
        return {
            "utc_offset_seconds": 0,
            "latitude": 53.25,
            "longitude": -6.25,
            "elevation": 20,
            "hourly_units": units,
            "hourly": hourly,
        }

    def get_text(self, *args, **kwargs):
        raise APIError("Synthetic station archive unavailable (offline test)")


LOCATION = epw.Location("Dublin", "Leinster", "Ireland", "IE", 53.35, -6.26, 20.0, "Europe/Dublin", 2964574)


class ConversionTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.directory = tempfile.TemporaryDirectory(prefix=".epw-test-", dir=project_root)
        self.root = Path(self.directory.name)
        if self.root.resolve().parent != project_root:
            raise AssertionError("Temporary test folder must stay inside the workspace.")
        self.addCleanup(self.directory.cleanup)

    def generate(self, year=2023, offset=timedelta(0), client=None, **kwargs):
        path = self.root / f"year_{year}.epw"
        with redirect_stdout(io.StringIO()):
            metadata = epw.create_epw(client or FakeClient(), LOCATION, year, offset, path, **kwargs)
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        return path, metadata, rows[:8], rows[8:]

    def test_complete_ordinary_year_and_hour_ending_boundary(self):
        path, metadata, headers, rows = self.generate()
        self.assertEqual(len(rows), 8760)
        self.assertTrue(all(len(row) == 35 and row[0] == "2023" for row in rows))
        self.assertEqual(rows[0][:5], ["2023", "1", "1", "1", "60"])
        self.assertEqual(rows[-1][:5], ["2023", "12", "31", "24", "60"])
        # API 01:00 describes 00:00--01:00, while next Jan 1 00:00 is the
        # requested year's final hour. Neither is shifted to the wrong EPW hour.
        self.assertEqual(float(rows[0][13]), 1.0)
        self.assertEqual(float(rows[-1][13]), 0.0)
        self.assertEqual(float(rows[0][9]), 101325.0)
        self.assertEqual(float(rows[0][30]), 2.0)
        self.assertEqual(float(rows[0][33]), 1.5)
        self.assertEqual(rows[0][34], "1")
        self.assertEqual(len(rows[0][5]), 44)
        self.assertEqual(headers[4][1], "No")
        self.assertEqual(headers[7][4], "Sunday")
        self.assertEqual(headers[7][-2:], ["1/1/2023", "12/31/2023"])
        self.assertFalse(metadata["tmy"])
        self.assertEqual(metadata["missing_snow_hours"], 0)
        self.assertTrue(path.with_name(path.name + ".metadata.json").exists())

    def test_full_leap_year_through_cli(self):
        path = self.root / "leap.epw"
        with patch.object(api, "APIClient", return_value=FakeClient()):
            with redirect_stdout(io.StringIO()):
                status = main(["--city", "Dublin, Ireland", "--year", "2024", "--output", str(path)])
        self.assertEqual(status, 0)
        self.assertEqual(epw.validate_epw(path, 2024), 8784)
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[4][1], "Yes")
        self.assertEqual(rows[7][-2:], ["1/1/2024", "12/31/2024"])
        leap_rows = [row for row in rows[8:] if row[1:3] == ["2", "29"]]
        self.assertEqual(len(leap_rows), 24)
        self.assertEqual(rows[-1][:5], ["2024", "12", "31", "24", "60"])
        metadata = json.loads(path.with_name(path.name + ".metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["rows"], 8784)
        self.assertFalse(metadata["tmy"])

    def test_half_hour_offset_resamples_intervals_across_new_year(self):
        _, metadata, headers, rows = self.generate(offset=timedelta(hours=5.5))
        self.assertEqual(len(rows), 8760)
        self.assertEqual(float(headers[0][8]), 5.5)
        # Jan 1 00:00--01:00 in UTC+05:30 spans Dec 31 18:30--19:30 UTC.
        # It takes half the source intervals ending at 19:00 and 20:00 UTC.
        self.assertAlmostEqual(float(rows[0][13]), 19.5)
        self.assertAlmostEqual(float(rows[-1][13]), 18.5)
        self.assertEqual(metadata["source_utc_dates"], ["2022-12-31", "2023-12-31"])

    def test_missing_core_data_never_publishes_partial_epw(self):
        path = self.root / "year_2023.epw"
        with self.assertRaisesRegex(epw.WeatherError, "Missing temperature_2m"):
            self.generate(client=FakeClient(missing_core=True))
        self.assertFalse(path.exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_optional_snow_failure_is_explicitly_missing(self):
        _, metadata, _, rows = self.generate(client=FakeClient(fail_snow=True))
        self.assertEqual(metadata["missing_snow_hours"], 8760)
        self.assertTrue(all(row[30] == "999" for row in rows))
        self.assertTrue(any("Snow depth" in warning for warning in metadata["warnings"]))

    def test_unexpected_units_stop_conversion(self):
        with self.assertRaisesRegex(epw.WeatherError, "Unexpected unit for wind_speed_10m"):
            self.generate(client=FakeClient(wrong_units=True))

    def test_existing_file_is_preserved(self):
        path = self.root / "year_2023.epw"
        path.write_text("existing user file", encoding="utf-8")
        with self.assertRaisesRegex(OutputExistsError, "Output already exists"):
            self.generate()
        self.assertEqual(path.read_text(encoding="utf-8"), "existing user file")

    def test_standard_offsets_include_irish_negative_dst(self):
        self.assertEqual(epw.standard_utc_offset("Europe/Dublin", 2023), timedelta(0))
        self.assertEqual(epw.standard_utc_offset("Europe/London", 2023), timedelta(0))
        self.assertEqual(epw.standard_utc_offset("America/New_York", 2023), timedelta(hours=-5))
        self.assertEqual(epw.standard_utc_offset("Australia/Sydney", 2023), timedelta(hours=10))
        self.assertEqual(epw.standard_utc_offset("Asia/Kathmandu", 2023), timedelta(hours=5.75))

    def test_quarter_hour_intervals_and_wind_wraparound(self):
        lower = int(datetime(2023, 1, 1, 19, tzinfo=timezone.utc).timestamp())
        rows = {
            lower: {"shortwave_radiation": 100.0, "wind_direction_10m": 350.0, "wind_speed_10m": 5.0},
            lower + 3600: {"shortwave_radiation": 200.0, "wind_direction_10m": 10.0, "wind_speed_10m": 5.0},
        }
        sample = epw.sample_hour(rows, datetime(2023, 1, 1, 19, 15, tzinfo=timezone.utc), tuple(rows[lower]))
        self.assertEqual(sample["shortwave_radiation"], 125.0)
        self.assertTrue(sample["wind_direction_10m"] > 350 or sample["wind_direction_10m"] < 10)

    def test_missing_boundary_hour_stops_sampling(self):
        rows = {0: {"shortwave_radiation": 100.0}}
        with self.assertRaisesRegex(epw.WeatherError, "Missing shortwave_radiation"):
            epw.sample_hour(rows, datetime.fromtimestamp(1800, timezone.utc), ("shortwave_radiation",))

    def test_infrared_estimate_matches_documented_clear_sky_example(self):
        # EnergyPlus documents approximately 340.6 W/m2 at 20 C / 10 C clear sky.
        self.assertAlmostEqual(epw.horizontal_infrared(20, 10, 0), 340.6, delta=1.0)

    def test_invalid_year_is_rejected_before_any_network_request(self):
        with patch.object(api.APIClient, "get", side_effect=AssertionError("network should not be used")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--city", "Dublin", "--year", "2100"]), 1)


if __name__ == "__main__":
    unittest.main()
