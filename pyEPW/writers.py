"""EPW, tab-delimited TXT, and column-labelled CSV output writers."""

from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ._files import atomic_text
from ._version import __version__
from ._attribution import attribution_metadata
from .exceptions import OutputExistsError
from .models import EPW_COLUMNS, OutputFormat, WeatherDataset
from .quality import MISSING_LIMITS


def metadata_path(path: Path) -> Path:
    return path.with_name(path.name + ".metadata.json")


def check_destination(path: Path, overwrite: bool) -> None:
    for target in (path, metadata_path(path)):
        if target.exists() and not overwrite:
            raise OutputExistsError(
                f"Output already exists: {target}. Use overwrite=True or --overwrite to replace it."
            )


def write_analysis_csv(dataset: WeatherDataset, path: Path, overwrite: bool = False) -> tuple[Path, dict]:
    """Physical-unit CSV with blank missing cells and uncapped modeled luminance.

    Unlike canonical EPW-compatible exports, CSV has no EPW sentinel-range
    restriction. Values beyond that range remain physical cd/m² estimates.
    """
    path = path.expanduser().resolve()
    check_destination(path, overwrite)
    path.parent.mkdir(parents=True, exist_ok=True)
    replacements = {
        r["row"]: r["zenith_luminance_cd_m2"] for r in dataset.metadata.get("zenith_luminance_outside_epw_range", [])
    }
    buffer = []
    for i, row in enumerate(dataset.rows):
        record = list(row)
        for column, limit in MISSING_LIMITS.items():
            if float(record[column]) >= limit:
                record[column] = ""
        if i in replacements:
            record[19] = f"{replacements[i]:.1f}"
            record[5] = record[5][:22] + "E9" + record[5][24:]
        buffer.append(record)
    import io

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(EPW_COLUMNS)
    writer.writerows(buffer)
    content = stream.getvalue()
    metadata = deepcopy(dataset.metadata)
    metadata.update(attribution_metadata(metadata))
    metadata.update(
        {
            "package_version": __version__,
            "package_name": "pyEPW",
            "distribution_name": "pyepw-openmeteo",
            "output_format": "analysis_csv",
            "output_file": path.name,
            "column_names": list(EPW_COLUMNS),
            "output_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "missing_values": "Empty CSV cells. Numeric EPW sentinel codes are not weather observations.",
            "analysis_csv_transformations": [
                "EPW missing sentinels replaced with empty cells.",
                "Modeled zenith luminance above EPW's supported range restored in physical cd/m2; empirical estimates, not measurements.",
                "Ceiling 77777/88888 remain explicit unlimited/cirroform category codes, not measured altitudes.",
            ],
        }
    )
    for column, name in enumerate(EPW_COLUMNS[6:], 6):
        info = metadata["field_coverage"][name]
        valid = sum(row[column] != "" for row in buffer)
        info.update(valid_hours=valid, missing_hours=len(buffer) - valid, coverage_percent=100 * valid / len(buffer))
        info.pop("missing_when_greater_or_equal", None)
    metadata["missing_fields"] = {
        name: info["missing_hours"] for name, info in metadata["field_coverage"].items() if info["missing_hours"]
    }
    metadata["is_complete"] = not metadata["missing_fields"]
    if replacements:
        metadata["field_coverage"][EPW_COLUMNS[19]]["method"] = (
            "Perez 1990 Eq.10 in physical cd/m²; no EPW sentinel-range restriction in analysis CSV."
        )
        metadata["warnings"] = [
            w for w in metadata.get("warnings", []) if "modeled zenith-luminance values exceed EPW" not in w
        ]
        metadata["warnings"].append(
            f"{len(replacements)} modeled zenith-luminance values outside EPW range are retained in this analysis CSV; they are empirical estimates."
        )
    check_destination(path, overwrite)
    atomic_text(path, content)
    atomic_text(metadata_path(path), json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    return path, metadata


def write_weather(
    dataset: WeatherDataset, format: OutputFormat, path: Path, overwrite: bool = False
) -> tuple[Path, dict[str, Any]]:
    path = path.expanduser().resolve()
    check_destination(path, overwrite)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            if format is OutputFormat.TXT:
                stream.write(f"# pyEPW {__version__}: actual year {dataset.year}\n")
                stream.write(f"# Location: {dataset.location.display_name}\n")
                stream.write(f"# Fixed standard UTC offset: {dataset.metadata['utc_offset_hours']:+g} hours\n")
                stream.write("# " + dataset.metadata["data_credit"] + "\n")
                stream.write("# Licence: " + dataset.metadata["data_licence"] + "\n")
                stream.write("# Estimated/missing fields and provenance: " + metadata_path(path).name + "\n")
            writer = csv.writer(stream, delimiter="\t" if format is OutputFormat.TXT else ",", lineterminator="\n")
            if format is OutputFormat.EPW:
                writer.writerows(dataset.headers)
            else:
                writer.writerow(EPW_COLUMNS)
            writer.writerows(dataset.rows)
        if format is OutputFormat.EPW:
            from ._engine import validate_epw

            validate_epw(temporary, dataset.year)
        metadata = deepcopy(dataset.metadata)
        metadata.update(attribution_metadata(metadata))
        metadata.update(
            {
                "package_version": __version__,
                "package_name": "pyEPW",
                "distribution_name": "pyepw-openmeteo",
                "output_format": format.value,
                "output_file": path.name,
                "column_names": list(EPW_COLUMNS),
                "output_sha256": hashlib.sha256(temporary.read_bytes()).hexdigest(),
                "missing_values": "EPW sentinel codes are preserved in all three formats; see docs/formats.md.",
            }
        )
        if format is OutputFormat.EPW:
            metadata["epw_sha256"] = metadata["output_sha256"]
        # Check again after serialization so a pre-existing destination is never
        # knowingly replaced when overwrite=False.
        check_destination(path, overwrite)
        os.replace(temporary, path)
        atomic_text(metadata_path(path), json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
        return path, metadata
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
