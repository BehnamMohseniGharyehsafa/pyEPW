"""Canonical import, compatibility identities and renamed command entry points."""

import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import pyEPW
from pyEPW._files import default_cache_dir


class RenameTests(unittest.TestCase):
    def test_legacy_imports_are_identical_to_canonical_modules_and_types(self):
        legacy = importlib.import_module("open_meteo_epw")
        self.assertIs(legacy.EPW, pyEPW.EPW)
        self.assertIs(legacy.Location, pyEPW.Location)
        self.assertIs(pyEPW.OpenMeteoEPWError, pyEPW.PyEPWError)
        self.assertIs(legacy.OpenMeteoEPWError, pyEPW.PyEPWError)
        for module in ("api", "client", "exceptions", "models", "observations", "station_fallbacks"):
            with self.subTest(module=module):
                self.assertIs(
                    importlib.import_module("open_meteo_epw." + module), importlib.import_module("pyEPW." + module)
                )

    def test_preferred_and_legacy_cache_environment_variables(self):
        with patch.dict(os.environ, {"PYEPW_CACHE": "preferred", "OPEN_METEO_EPW_CACHE": "previous"}, clear=True):
            self.assertEqual(default_cache_dir(), Path("preferred"))
        with patch.dict(os.environ, {"OPEN_METEO_EPW_CACHE": "previous"}, clear=True):
            self.assertEqual(default_cache_dir(), Path("previous"))

    def test_new_and_legacy_module_commands(self):
        root = Path(__file__).resolve().parents[1]
        for module in ("pyEPW", "open_meteo_epw"):
            result = subprocess.run(
                [sys.executable, "-m", module, "--version"], cwd=root, text=True, capture_output=True, check=True
            )
            self.assertEqual(result.stdout.strip(), f"pyEPW {pyEPW.__version__}")


if __name__ == "__main__":
    unittest.main()
