"""City catalog parsing, filtering, export, and help; tiny local fixtures only."""

import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pyEPW
from pyEPW.catalog import CityCatalog, _build_database
from pyEPW.exceptions import CatalogError, OutputExistsError


class CatalogTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        self.directory = tempfile.TemporaryDirectory(prefix=".epw-test-", dir=project)
        self.root = Path(self.directory.name)
        self.assertEqual(self.root.resolve().parent, project)
        self.addCleanup(self.directory.cleanup)
        self.archive = self.root / "geonames-cities500.zip"
        rows = [
            [
                "1",
                "Dublin",
                "Dublin",
                "",
                "53.35",
                "-6.26",
                "P",
                "PPLC",
                "IE",
                "",
                "L",
                "",
                "",
                "",
                "500000",
                "20",
                "20",
                "Europe/Dublin",
                "2026-01-01",
            ],
            [
                "2",
                "Paris",
                "Paris",
                "",
                "48.85",
                "2.35",
                "P",
                "PPLC",
                "FR",
                "",
                "11",
                "",
                "",
                "",
                "2000000",
                "35",
                "35",
                "Europe/Paris",
                "2026-01-01",
            ],
            [
                "3",
                "São Paulo",
                "Sao Paulo",
                "",
                "-23.55",
                "-46.63",
                "P",
                "PPLA",
                "BR",
                "",
                "27",
                "",
                "",
                "",
                "10000000",
                "760",
                "760",
                "America/Sao_Paulo",
                "2026-01-01",
            ],
        ]
        buffer = io.StringIO()
        csv.writer(buffer, delimiter="\t", lineterminator="\n").writerows(rows)
        with zipfile.ZipFile(self.archive, "w") as zipped:
            zipped.writestr("cities500.txt", buffer.getvalue())
        self.database = self.root / "geonames-cities500.sqlite3"

    def test_build_browse_and_diacritic_search(self):
        self.assertEqual(_build_database(self.archive, self.database), 3)
        catalog = CityCatalog(self.database)
        self.assertEqual(len(catalog), 3)
        self.assertEqual([city.name for city in catalog.iter_cities()], ["Dublin", "Paris", "São Paulo"])
        self.assertEqual(list(catalog.names(country="ie")), ["Dublin, L, IE"])
        self.assertEqual(catalog.search("sao")[0].name, "São Paulo")
        self.assertEqual(catalog.search("%"), ())

    def test_download_reuses_local_archive_and_database(self):
        with patch("pyEPW.catalog.urlopen", side_effect=AssertionError("network not expected")):
            catalog = CityCatalog.download(cache_dir=self.root)
            self.assertEqual(len(catalog), 3)
            self.assertEqual(len(CityCatalog.download(cache_dir=self.root)), 3)

    def test_complete_country_export_and_attribution(self):
        _build_database(self.archive, self.database)
        path = CityCatalog(self.database).export(self.root / "cities.csv", country="IE")
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Dublin")
        self.assertTrue(path.with_name(path.name + ".metadata.json").exists())
        with self.assertRaises(OutputExistsError):
            CityCatalog(self.database).export(path)

    def test_help_can_list_every_city_in_selected_country(self):
        text = pyEPW.help("cities", country="IE", limit=None, cache_dir=self.root)
        self.assertIn("Dublin", text)
        self.assertNotIn("Paris", text)
        self.assertEqual(len(tuple(pyEPW.cities(country="FR", cache_dir=self.root))), 1)

    def test_malformed_archive_never_publishes_database(self):
        with zipfile.ZipFile(self.archive, "w") as zipped:
            zipped.writestr("cities500.txt", "incorrect\tcolumns\n")
        with self.assertRaises(CatalogError):
            _build_database(self.archive, self.database)
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
