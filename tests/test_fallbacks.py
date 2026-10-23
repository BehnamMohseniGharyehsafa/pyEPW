"""Adverse-source and independent interval/code cases for free fallbacks."""

import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyEPW import EPW, DataError
from pyEPW import api
from pyEPW.client import APIClient
from pyEPW.supplements import SnowHistory, interval_albedo, load_power_albedo
from pyEPW.station_fallbacks import metar_values, parse_iem, parse_isd, history_catalog, fill_station_gaps
from test_open_meteo_epw import FakeClient, LOCATION

UTC = timezone.utc
SITE = {
    "station_id": "039550-99999",
    "name": "CORK",
    "latitude": 51.841,
    "longitude": -8.491,
    "distance_km": 6.3,
    "icao": "EICK",
    "begin": "19730101",
    "end": "20250824",
}


def isd_line(hour=1, ceiling="00150", ceil_qc="1", visibility="010000", vis_qc="1", station="03955099999"):
    line = list(" " * 105)
    for start, value in [
        (4, station),
        (15, f"20250101{hour:02}00"),
        (28, "+51841"),
        (34, "-008491"),
        (41, "FM-12"),
        (70, ceiling),
        (75, ceil_qc),
        (76, "M"),
        (78, visibility),
        (84, vis_qc),
        (85, "N"),
    ]:
        line[start : start + len(value)] = value
    return "".join(line)


def iem_csv(raw, time="2025-01-01 01:00", station="EICK"):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["station", "valid", "lon", "lat", "metar"])
    writer.writerow([station, time, -8.4794, 51.8481, raw])
    return out.getvalue()


class SnowHistoryTests(unittest.TestCase):
    def test_88_requires_complete_history_not_a_default(self):
        history = SnowHistory()
        first = datetime(2024, 10, 1, 1, tzinfo=UTC)
        for hour in range(88 * 24 - 1):
            self.assertIsNone(history.advance(first + timedelta(hours=hour), 0))
        self.assertEqual(history.advance(first + timedelta(hours=88 * 24 - 1), 0), 88)

    def test_event_prior_year_elapsed_days_and_capping(self):
        history = SnowHistory()
        event = datetime(2024, 12, 31, 1, tzinfo=UTC)
        self.assertEqual(history.advance(event, 0.01), 0)
        for hour in range(1, 24 * 90 + 1):
            count = history.advance(event + timedelta(hours=hour), 0)
            self.assertEqual(count, min(88, hour // 24))

    def test_missing_or_skipped_hour_invalidates_event_history(self):
        history = SnowHistory()
        t = datetime(2025, 1, 1, tzinfo=UTC)
        history.advance(t, 0.1)
        self.assertIsNone(history.advance(t + timedelta(hours=1), None))
        self.assertIsNone(history.advance(t + timedelta(hours=2), 0))
        self.assertEqual(history.advance(t + timedelta(hours=3), 0.001), 0)
        self.assertIsNone(history.advance(t + timedelta(hours=5), 0))


class SourceParsingTests(unittest.TestCase):
    def setUp(self):
        from pyEPW import Location

        self.location = Location("Cork", "Munster", "Ireland", "IE", 51.89797, -8.47061, 10, "Europe/Dublin", 2965140)

    def test_metar_observed_lowest_broken_ceiling_not_few_or_forecast(self):
        values = metar_values("EICK 010100Z 22023KT 6000 -RADZ FEW002 BKN003 OVC010 11/11 Q1002 TEMPO BKN001")
        self.assertAlmostEqual(values["ceiling_height_m"][0], 91.44)
        self.assertEqual(values["visibility_km"], (6.0, None))

    def test_metar_cavok_clear_and_unknown_layers_are_not_unlimited(self):
        for sky in ("CAVOK", "NSC", "SKC", "CLR", "FEW003 SCT010", "BKN/// OVC030", "VV///"):
            with self.subTest(sky=sky):
                self.assertNotIn("ceiling_height_m", metar_values(f"EICK 010100Z 22005KT {sky} 10/08 Q1010"))
        self.assertNotIn("ceiling_height_m", metar_values("EICK 010100Z 22005KT 9999 10/08 Q1010 TEMPO BKN003"))

    def test_metar_vertical_visibility_and_visibility_bounds(self):
        values = metar_values("EICK 010100Z 22005KT 9999 VV002 10/08 Q1010")
        self.assertAlmostEqual(values["ceiling_height_m"][0], 60.96)
        self.assertEqual(values["visibility_km"], (10.0, "lower_bound_10_km"))
        self.assertAlmostEqual(metar_values("KJFK 010100Z 22005KT 1 1/2SM BKN020")["visibility_km"][0], 2.414016)
        self.assertEqual(metar_values("KJFK 010100Z 22005KT P6SM BKN020")["visibility_km"][1], "reported_lower_bound")

    def test_iem_identity_timestamp_position_and_qc_are_explicit(self):
        raw = "EICK 010100Z 22005KT 9999 BKN010 10/08 Q1010"
        data = parse_iem(iem_csv(raw), SITE, self.location, 0)
        r = next(iter(data.values()))["ceiling_height_m"]
        self.assertAlmostEqual(r["value"], 304.8)
        self.assertEqual(r["quality_code"], "not_supplied")
        self.assertEqual(r["raw_metar_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertFalse(parse_iem(iem_csv(raw, time="2025-01-01 02:00"), SITE, self.location, 0))
        self.assertFalse(parse_iem(iem_csv(raw).replace("51.8481", "0.0"), SITE, self.location, 0))
        with self.assertRaises(DataError):
            parse_iem(iem_csv(raw, station="WRONG"), SITE, self.location, 0)

    def test_isd_original_units_qc_categories_and_position(self):
        data = parse_isd(isd_line(), SITE, self.location, 0)
        first = next(iter(data.values()))
        self.assertEqual(first["visibility_km"]["value"], 10)
        self.assertEqual(first["ceiling_height_m"]["value"], 150)
        unlimited = parse_isd(isd_line(ceiling="22000", ceil_qc="5"), SITE, self.location, 0)
        self.assertEqual(next(iter(unlimited.values()))["ceiling_height_m"]["value"], 77777)
        self.assertFalse(any(parse_isd(isd_line(ceil_qc="0", vis_qc="0"), SITE, self.location, 0).values()))
        self.assertFalse(parse_isd(isd_line().replace("+51841", "+00000"), SITE, self.location, 0))
        with self.assertRaises(DataError):
            parse_isd(isd_line(station="99999999999"), SITE, self.location, 0)

    def test_gap_chain_preserves_existing_values_and_labels_metar_quality(self):
        history = (
            "USAF,WBAN,STATION NAME,LAT,LON,BEGIN,END,ICAO\n039550,99999,CORK,51.841,-8.491,19730101,20250824,EICK\n"
        )

        class Client:
            def get_text(self, url, **kwargs):
                if url.endswith("isd-history.csv"):
                    return history
                if url.endswith(".gz"):
                    return isd_line(ceiling="00200") + "\n" + isd_line(hour=2, ceil_qc="0", vis_qc="0")
                return iem_csv("EICK 010200Z 22005KT 6000 BKN010 10/08 Q1010", "2025-01-01 02:00")

        first, final = datetime(2025, 1, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, 2, tzinfo=UTC)
        existing = {int(first.timestamp()): {"ceiling_height_m": {"value": 100}}}
        data, meta, warnings = fill_station_gaps(Client(), self.location, first, final, 0, existing)
        self.assertEqual(data[int(first.timestamp())]["ceiling_height_m"]["value"], 100)
        self.assertAlmostEqual(data[int(final.timestamp())]["ceiling_height_m"]["value"], 304.8)
        self.assertIn("IEM", meta["providers"][-1]["provider"])
        self.assertFalse(warnings)

    def test_history_schema_and_active_interval(self):
        with self.assertRaises(DataError):
            history_catalog("bad,columns\n1,2", self.location, datetime(2025, 1, 1), datetime(2025, 12, 31), 30)


class PowerAndTransportTests(unittest.TestCase):
    def test_invalid_power_period_does_not_retain_partially_parsed_values(self):
        class Client:
            def get(self, endpoint, parameters):
                return {
                    "header": {"time_standard": "UTC", "fill_value": -999},
                    "parameters": {"ALLSKY_SRF_ALB": {"units": "dimensionless"}},
                    "properties": {"parameter": {"ALLSKY_SRF_ALB": {"2025010100": 0.15, "2026010100": 0.2}}},
                }

        first = datetime(2025, 1, 1, 1, tzinfo=UTC)
        data, meta, warnings = load_power_albedo(Client(), LOCATION, first, first)
        self.assertFalse(data)
        self.assertFalse(meta["responses"])
        self.assertTrue(warnings)

    def test_power_hour_zero_is_epw_hour_one_and_missing_night_stays_missing(self):
        class Client:
            def get(self, endpoint, parameters):
                return {
                    "header": {"time_standard": "UTC", "fill_value": -999},
                    "parameters": {"ALLSKY_SRF_ALB": {"units": "dimensionless"}},
                    "properties": {
                        "parameter": {"ALLSKY_SRF_ALB": {"2025010100": -999, "2025010101": 0.15, "2025010102": 1.5}}
                    },
                }

        first, final = datetime(2025, 1, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, 3, tzinfo=UTC)
        data, meta, warnings = load_power_albedo(Client(), LOCATION, first, final)
        self.assertIsNone(interval_albedo(data, first))
        self.assertEqual(interval_albedo(data, first + timedelta(hours=1)), 0.15)
        self.assertIsNone(interval_albedo(data, first + timedelta(hours=2)))
        self.assertIsNone(interval_albedo(data, first + timedelta(minutes=30)))
        self.assertFalse(warnings)

    def test_gzip_original_retained_and_cached_without_redownload(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root, prefix=".epw-test-") as folder:
            client = APIClient(folder)
            original = gzip.compress(b"original station report\r\n")
            with patch("pyEPW.client.urlopen", return_value=io.BytesIO(original)) as request:
                self.assertEqual(client.get_text("https://example.invalid/report.gz"), "original station report\r\n")
                client.get_text("https://example.invalid/report.gz")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(client.text_sources[0]["sha256_utf8"], client.text_sources[1]["sha256_utf8"])
            source = client.text_sources[-1]
            self.assertEqual(source["compressed_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual((Path(folder) / source["compressed_cached_file"]).read_bytes(), original)

    def test_require_complete_rejects_unsupported_fields_before_writing(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root, prefix=".epw-test-") as folder:
            with patch.object(api, "APIClient", return_value=FakeClient()):
                with self.assertRaisesRegex(DataError, "present_weather_observation"):
                    EPW(LOCATION, 2025, output_dir=folder, station=None, require_complete=True)
            self.assertFalse(list(Path(folder).glob("*.epw")))


if __name__ == "__main__":
    unittest.main()
