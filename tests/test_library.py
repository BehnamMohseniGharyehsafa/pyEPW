"""Public API and multi-format integration tests, with no live network."""

from contextlib import redirect_stdout, redirect_stderr
import csv
from datetime import datetime, timezone
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyEPW
from pyEPW import EPW, EPW_COLUMNS, OutputExistsError, ValidationError
from pyEPW import api
from pyEPW.cli import main
from test_open_meteo_epw import FakeClient, LOCATION


class LibraryTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        self.directory = tempfile.TemporaryDirectory(prefix=".epw-test-", dir=project)
        self.root = Path(self.directory.name)
        self.assertEqual(self.root.resolve().parent, project)
        self.addCleanup(self.directory.cleanup)

    def create(self, format="epw", year="2024", **kwargs):
        self.client = FakeClient()
        with patch.object(api, "APIClient", return_value=self.client):
            return EPW("Dublin, Ireland", year, format, output_dir=self.root, **kwargs)

    def test_requested_constructor_and_exports_do_not_redownload(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            weather = self.create(".EPW")
            requests = len(self.client.urls)
            csv_path = weather.to_csv()
            txt_path = weather.to_txt()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(self.client.urls), requests)
        self.assertEqual(weather.format, "epw")
        self.assertEqual(weather.year, 2024)
        self.assertEqual(weather.hours, 8784)
        self.assertEqual(len(weather), 8784)
        self.assertTrue(weather.is_leap_year)
        self.assertEqual(os.fspath(weather), str(weather.path))
        self.assertEqual(str(weather), str(weather.path))
        self.assertIn("hours=8784", repr(weather))
        with csv_path.open(encoding="utf-8", newline="") as stream:
            csv_rows = list(csv.reader(stream))
        self.assertEqual(csv_rows[0], list(EPW_COLUMNS))
        self.assertEqual(len(csv_rows), 8785)
        self.assertEqual(tuple(csv_rows[1]), weather.data[0])
        with txt_path.open(encoding="utf-8", newline="") as stream:
            lines = [line for line in stream if not line.startswith("#")]
        txt_rows = list(csv.reader(lines, delimiter="\t"))
        self.assertEqual(txt_rows[0], list(EPW_COLUMNS))
        self.assertEqual(txt_rows[1:], csv_rows[1:])
        for path in (weather.path, csv_path, txt_path):
            sidecar = path.with_name(path.name + ".metadata.json")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(metadata["output_format"], path.suffix[1:])
            self.assertEqual(len(metadata["output_sha256"]), 64)
            self.assertFalse(metadata["tmy"])
            self.assertEqual(metadata["package_name"], "pyEPW")
            self.assertEqual(metadata["distribution_name"], "pyepw-openmeteo")

    def test_csv_and_txt_can_be_initial_formats(self):
        for format in ("csv", ".txt"):
            with self.subTest(format=format):
                weather = self.create(format, year=2023)
                self.assertEqual(weather.path.suffix, "." + format.lstrip("."))
                self.assertEqual(weather.hours, 8760)

    def test_metadata_is_defensively_copied_and_rows_immutable(self):
        weather = self.create()
        copy = weather.metadata
        copy["city"]["name"] = "Changed"
        self.assertEqual(weather.metadata["city"]["name"], "Dublin")
        self.assertIsInstance(weather.data, tuple)
        self.assertEqual(next(weather.iter_records())["year"], "2024")

    def test_invalid_inputs_fail_before_network(self):
        with patch.object(api, "APIClient", side_effect=AssertionError("Unexpected network setup")):
            for year in (True, 2024.5, "2024.0", "abcd", 1939, datetime.now(timezone.utc).year):
                with self.subTest(year=year), self.assertRaises(ValidationError):
                    EPW("Dublin", year, "epw")
            for format in ("pdf", "..csv", "", 123):
                with self.subTest(format=format), self.assertRaises(ValidationError):
                    EPW("Dublin", 2024, format)
            with self.assertRaises(ValidationError):
                EPW("Dublin", 2024, country="Ireland")
            with self.assertRaises(ValidationError):
                EPW("Dublin", 2024, utc_offset=float("nan"))
            with self.assertRaises(ValidationError):
                EPW("Dublin", 2024, "csv", output=self.root / "wrong.epw")

    def test_output_exists_is_typed_and_never_overwrites(self):
        weather = self.create()
        before = weather.path.read_bytes()
        with self.assertRaises(OutputExistsError):
            weather.to_epw()
        self.assertEqual(weather.path.read_bytes(), before)
        self.assertEqual(weather.to_epw(overwrite=True), weather.path)

    def test_location_object_bypasses_geocoding(self):
        client = FakeClient()
        with patch.object(api, "APIClient", return_value=client):
            weather = EPW(LOCATION, "2023", "csv", output_dir=self.root)
        # Core, snow-depth and column-water monthly requests; snowfall includes
        # its prior-year lookback, followed by one NASA source-year request.
        self.assertEqual(len(client.urls), 56)
        self.assertEqual(weather.location, LOCATION)

    def test_usage_help_and_import_have_no_network_or_file_effects(self):
        with patch("pyEPW.client.urlopen", side_effect=AssertionError("network on import")):
            with patch("pathlib.Path.mkdir", side_effect=AssertionError("filesystem write on import")):
                importlib.reload(pyEPW)
                text = pyEPW.help()
        self.assertIn("EPW", text)
        self.assertIn("csv", pyEPW.help("formats"))
        self.assertIn("Parameters", EPW.__doc__)

    def test_cli_csv_export(self):
        path = self.root / "cli.csv"
        with patch.object(api, "APIClient", return_value=FakeClient()):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = main(["Dublin", "2023", "--format", "csv", "--output", str(path)])
        self.assertEqual(status, 0)
        self.assertTrue(path.exists())

    def test_format_change_requires_matching_extension(self):
        weather = self.create()
        with self.assertRaises(ValidationError):
            weather.to_csv(self.root / "wrong.txt")


if __name__ == "__main__":
    unittest.main()
