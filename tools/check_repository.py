"""Offline checks for public links, citation/version and documented figure data."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    documents = [*ROOT.glob("*.md"), *ROOT.joinpath("docs").rglob("*.md"), ROOT / "validation/README.md"]
    failures = []
    for path in documents:
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", content):
            target = unquote(target.strip("<>"))
            if target.startswith("#") or urlparse(target).scheme:
                continue
            destination = (path.parent / target.split("#", 1)[0]).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                failures.append(f"{path.relative_to(ROOT)}: broken local link {target}")
        if re.search(r"[A-Z]:[\\/](?:Users|OneDrive)", content):
            failures.append(f"{path.relative_to(ROOT)} contains a private working path")
    cff = yaml.safe_load((ROOT / "CITATION.cff").read_text())
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "pyEPW/_version.py").read_text())[1]
    assert str(cff["version"]) == version and cff["license"] == "MIT" and cff["authors"]
    for path in ROOT.joinpath(".github").rglob("*.yml"):
        assert isinstance(yaml.safe_load(path.read_text()), dict), path
    for path in ROOT.joinpath("docs/assets").glob("*.svg"):
        ET.parse(path)
    data = ROOT / "docs/data"
    with (data / "continents_2024_monthly.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 72 and len({r["continent"] for r in rows}) == 6
    for city in {r["city"] for r in rows}:
        assert sum(int(r["hours"]) for r in rows if r["city"] == city) == 8784
    provenance = json.loads((data / "benchmark_provenance.json").read_text())
    for name, info in provenance["inputs"].items():
        assert hashlib.sha256((data / name).read_bytes()).hexdigest() == info["sha256"]
    assert not failures, "\n".join(failures)
    print(f"Checked {len(documents)} Markdown documents, local links, citation, YAML, SVG and six-city inputs.")


if __name__ == "__main__":
    main()
