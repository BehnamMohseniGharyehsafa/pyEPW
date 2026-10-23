"""Independent numeric references and adverse-data cases for the new fields."""

import csv
from datetime import datetime, timedelta, timezone
import io
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyEPW import EPW, ADDITIONAL_FIELDS, DataError, ValidationError
from pyEPW import api
from pyEPW._solar import solar_cosine, solar_interval, SolarInterval
from pyEPW._daylight import perez_daylight
from pyEPW.observations import (
    ObservationStation,
    parse_observations,
    qc_accepted,
    station_catalog,
    lineage_runs,
)
from test_open_meteo_epw import FakeClient, LOCATION

UTC = timezone.utc
STATION = ObservationStation("EII0000EIME", "CASEMENT", 53.3017, -6.4513, 97.2, "IE", 13.23)


def psv(rows):
    columns = ["STATION", "DATE", "LATITUDE", "LONGITUDE"]
    for v in ["visibility", "ceiling_height"]:
        columns += [v, v + "_Quality_Code", v + "_Source_Code", v + "_Measurement_Code", v + "_Report_Type"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, delimiter="|")
    writer.writeheader()
    for change in rows:
        row = {
            "STATION": STATION.station_id,
            "DATE": "2025-01-01T01:00:00",
            "visibility": "12.0",
            "ceiling_height": "1200",
        }
        for v in ["visibility", "ceiling_height"]:
            row.update(
                {
                    v + "_Quality_Code": "1",
                    v + "_Source_Code": "223",
                    v + "_Measurement_Code": "",
                    v + "_Report_Type": "FM12",
                }
            )
        row.update(change)
        writer.writerow(row)
    return stream.getvalue()


class SolarTests(unittest.TestCase):
    def test_nrel_spa_published_example_geometric_zenith(self):
        # SPA published example, 2003-10-17 12:30:30 UTC-7, Colorado.
        # 50.111622° apparent + ~0.0163° refraction = 50.12795° geometric.
        t = datetime(2003, 10, 17, 19, 30, 30, tzinfo=UTC)
        angle = math.degrees(math.acos(solar_cosine(t, 39.742476, -105.1786)))
        self.assertAlmostEqual(angle, 50.12795, delta=0.02)

    def test_polar_day_night_and_midnight(self):
        summer = solar_interval(datetime(2025, 6, 21, 1, tzinfo=UTC), 80, 0)
        winter = solar_interval(datetime(2025, 12, 21, 13, tzinfo=UTC), 80, 0)
        self.assertAlmostEqual(summer.daylight_fraction, 1)
        self.assertGreater(summer.horizontal_wh_m2, 0)
        self.assertEqual(winter.horizontal_wh_m2, 0)
        self.assertEqual(winter.direct_normal_wh_m2, 0)
        self.assertEqual(solar_interval(datetime(2025, 3, 20, 1, tzinfo=UTC), 0, 0).daylight_fraction, 0)

    def test_sunrise_integration_against_one_second_quadrature(self):
        intervals = [
            (
                datetime(2025, 6, 21, h, tzinfo=UTC),
                solar_interval(datetime(2025, 6, 21, h, tzinfo=UTC), 53.385, -6.59361),
            )
            for h in range(1, 24)
        ]
        end, result = next((t, s) for t, s in intervals if 0 < s.daylight_fraction < 1)
        start = end - timedelta(hours=1)
        from pyEPW._solar import extraterrestrial_normal

        reference = 0
        duration = 0
        for second in range(3600):
            t = start + timedelta(seconds=second + 0.5)
            cosine = max(0, solar_cosine(t, 53.385, -6.59361))
            reference += extraterrestrial_normal(t) * cosine / 3600
            duration += cosine > 0
        self.assertAlmostEqual(result.horizontal_wh_m2, reference, delta=0.02)
        self.assertAlmostEqual(result.daylight_fraction, duration / 3600, delta=1 / 3600)
        self.assertLess(result.horizontal_wh_m2, result.direct_normal_wh_m2)

    def test_perez_paper_table4_category5_numeric_reference(self):
        # Independent substitution into published Eqs 6–8,10 / Table 4,
        # Z=60°, GHI=500, DNI=600, DHI=200 W/m², dew point=10°C.
        value = perez_daylight(SolarInterval(680, 1360, 1, 0.5), 500, 600, 200, 10)
        self.assertAlmostEqual(value.global_lux, 52765.12349, places=4)
        self.assertAlmostEqual(value.direct_normal_lux, 55426.42365, places=4)
        self.assertAlmostEqual(value.diffuse_lux, 25910.53008, places=4)
        self.assertAlmostEqual(value.zenith_cd_m2, 4304.14952, places=4)

    def test_daylight_night_zero_and_partial_hour_consistency(self):
        dark = perez_daylight(SolarInterval(0, 0, 0, 0), 0, 0, 0, 10)
        self.assertEqual((dark.global_lux, dark.direct_normal_lux, dark.diffuse_lux, dark.zenith_cd_m2), (0, 0, 0, 0))
        full = perez_daylight(SolarInterval(680, 1360, 1, 0.5), 500, 600, 200, 10)
        partial = perez_daylight(SolarInterval(340, 680, 0.5, 0.5), 250, 300, 100, 10)
        self.assertAlmostEqual(partial.global_lux, full.global_lux / 2)
        self.assertAlmostEqual(partial.zenith_cd_m2, full.zenith_cd_m2 / 2)


class ObservationTests(unittest.TestCase):
    def test_source_specific_qc_codes(self):
        self.assertTrue(qc_accepted("313", "5"))
        self.assertFalse(qc_accepted("223", "5"))  # aviation 5 means removed
        self.assertFalse(qc_accepted("223", "4"))  # calculated, not strict measured
        self.assertTrue(qc_accepted("223", "1"))
        self.assertFalse(qc_accepted("223", ""))
        self.assertFalse(qc_accepted("unknown", "1"))

    def test_visibility_kilometres_ceiling_metres_and_unlimited(self):
        data = parse_observations(psv([{}, {"DATE": "2025-01-01T02:00:00", "ceiling_height": "22000"}]), STATION, 0)
        first = data[int(datetime(2025, 1, 1, 1, tzinfo=UTC).timestamp())]
        self.assertEqual(first["visibility_km"]["value"], 12)
        self.assertEqual(first["ceiling_height_m"]["value"], 1200)
        self.assertEqual(data[int(datetime(2025, 1, 1, 2, tzinfo=UTC).timestamp())]["ceiling_height_m"]["value"], 77777)

    def test_rejected_quality_and_cavok_do_not_invent_ceiling(self):
        data = parse_observations(
            psv([{"visibility_Quality_Code": "4", "ceiling_height": "", "ceiling_height_Measurement_Code": ";Y"}]),
            STATION,
            0,
        )
        self.assertFalse(any(data.values()))

    def test_visibility_code_is_marked_lower_bound(self):
        data = parse_observations(psv([{"visibility": "9.999"}]), STATION, 0)
        record = next(iter(data.values()))["visibility_km"]
        self.assertEqual(record["value"], 10)
        self.assertEqual(record["qualifier"], "lower_bound_10_km")

    def test_no_time_fill_and_fractional_standard_offset(self):
        self.assertFalse(parse_observations(psv([{"DATE": "2025-01-01T01:30:00"}]), STATION, 0))
        result = parse_observations(psv([{"DATE": "2025-01-01T01:30:00"}]), STATION, 5.5 * 3600)
        self.assertIn(int(datetime(2025, 1, 1, 1, 30, tzinfo=UTC).timestamp()), result)

    def test_station_identity_and_negative_values(self):
        with self.assertRaises(DataError):
            parse_observations(psv([{"STATION": "WRONG"}]), STATION, 0)
        result = parse_observations(psv([{"visibility": "-9999", "ceiling_height": "-9999"}]), STATION, 0)
        self.assertFalse(any(result.values()))

    def test_reported_position_enforces_distance_and_is_retained(self):
        # A historical station relocation must not defeat the distance limit.
        result = parse_observations(psv([{"LATITUDE": "0", "LONGITUDE": "0"}]), STATION, 0, location=LOCATION)
        self.assertFalse(result)
        result = parse_observations(
            psv([{"LATITUDE": str(LOCATION.latitude), "LONGITUDE": str(LOCATION.longitude)}]),
            STATION,
            0,
            location=LOCATION,
        )
        record = next(iter(result.values()))["visibility_km"]
        self.assertEqual(record["distance_km"], 0)
        self.assertEqual(record["position_source"], "reported_observation_position")

    def test_catalog_fixed_width_and_lineage(self):
        # WMO code after the 30-character name must not become part of the name.
        line = f"{'EIM00003971':11} {53.5333:8.4f} {-7.3667:9.4f} {100:6.1f}    {'MULLINGAR':30}         {'03971':5} IE"
        station = station_catalog(line, LOCATION)[0]
        self.assertEqual(station.name, "MULLINGAR")
        self.assertEqual(station.country_code, "IE")
        source = {"value": 12, "station_id": "test", "quality_code": "1"}
        runs = lineage_runs([source, source, None, None])
        self.assertEqual([r["count"] for r in runs], [2, 2])


class SupplementalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix=".epw-test-")
        self.addCleanup(self.tmp.cleanup)

    def test_coverage_analysis_csv_and_no_export_downloads(self):
        client = FakeClient()
        with patch.object(api, "APIClient", return_value=client):
            w = EPW(LOCATION, 2025, output_dir=self.tmp.name, station=None)
        requests = len(client.urls)
        csv_path = w.to_analysis_csv()
        self.assertEqual(len(client.urls), requests)
        self.assertEqual(w.field_coverage["precipitable_water_mm"]["valid_hours"], 8760)
        self.assertEqual(w.field_coverage["visibility_km"]["missing_hours"], 8760)
        self.assertIn("empirical_model", w.quality_report())
        with csv_path.open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["precipitable_water_mm"], "20.00")
        self.assertEqual(rows[0]["visibility_km"], "")
        self.assertEqual(len(ADDITIONAL_FIELDS), 11)

    def test_required_missing_field_prevents_publication(self):
        with patch.object(api, "APIClient", return_value=FakeClient()):
            with self.assertRaisesRegex(DataError, "visibility_km is missing"):
                EPW(LOCATION, 2025, output_dir=self.tmp.name, station=None, require_fields=["visibility_km"])
        self.assertEqual(list(Path(self.tmp.name).glob("*.epw")), [])

    def test_invalid_station_configuration_fails_before_network(self):
        with patch.object(api, "APIClient", side_effect=AssertionError("unexpected network")):
            for kwargs in [
                {"station": "../bad"},
                {"max_station_distance_km": float("nan")},
                {"station_tolerance_minutes": 31},
                {"require_fields": ["unknown"]},
                {"include_additional_fields": "yes"},
            ]:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                    EPW(LOCATION, 2025, output_dir=self.tmp.name, **kwargs)

    def test_analysis_csv_restores_luminance_without_fabricating_observations(self):
        from pyEPW.models import WeatherDataset
        from pyEPW.quality import field_coverage
        from pyEPW.writers import write_analysis_csv

        row = ["2025", "1", "1", "1", "60", "?9" * 22] + ["999999999"] * 29
        row[19] = "9999"
        metadata = {
            "field_coverage": field_coverage([row]),
            "zenith_luminance_outside_epw_range": [{"row": 0, "zenith_luminance_cd_m2": 12345.6}],
        }
        dataset = WeatherDataset(LOCATION, 2025, (), (tuple(row),), metadata)
        path, meta = write_analysis_csv(dataset, Path(self.tmp.name) / "analysis.csv")
        with path.open() as stream:
            records = list(csv.DictReader(stream))
        self.assertEqual(records[0]["zenith_luminance_cd_m2"], "12345.6")
        self.assertEqual(records[0]["visibility_km"], "")
        self.assertEqual(meta["field_coverage"]["zenith_luminance_cd_m2"]["valid_hours"], 1)
