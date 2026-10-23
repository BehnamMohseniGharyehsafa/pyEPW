"""Run with an isolated wheel-installed Python: python -I tools/smoke_installed.py."""

import importlib.metadata
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch("urllib.request.urlopen", side_effect=AssertionError("Network on import")):
    with patch("pathlib.Path.mkdir", side_effect=AssertionError("Filesystem write on import")):
        import pyEPW
        import open_meteo_epw

assert "site-packages" in Path(pyEPW.__file__).parts, pyEPW.__file__
assert pyEPW.EPW is open_meteo_epw.EPW
assert importlib.metadata.version("pyepw-openmeteo") == pyEPW.__version__
# Add only the fixture directory, never the source package directory. This
# explicitly synthetic test weather is removed with the temporary directory.
sys.path.insert(0, str(ROOT / "tests"))
from test_open_meteo_epw import FakeClient, LOCATION  # noqa: E402

with tempfile.TemporaryDirectory(prefix=".epw-test-", dir=ROOT) as folder:
    with patch("pyEPW.api.APIClient", return_value=FakeClient()):
        weather = pyEPW.EPW(LOCATION, 2023, ".epw", station=None, output_dir=folder)
    paths = [weather.path, weather.to_csv(), weather.to_txt(), weather.to_analysis_csv()]
    assert weather.hours == 8760 and all(p.exists() for p in paths)
    assert weather.metadata["software_licence"] == "MIT"
    assert weather.metadata["source_attributions"]
run = subprocess.run([sys.executable, "-I", "-m", "pyEPW", "--version"], capture_output=True, text=True, check=True)
assert run.stdout.strip() == "pyEPW " + pyEPW.__version__
print("Isolated wheel import, aliases, CLI, four exports and attribution passed.")
