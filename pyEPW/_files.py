"""Cache locations and atomic local file operations."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def default_cache_dir() -> Path:
    """Return a user-writable cache, never a directory inside site-packages."""
    if override := os.environ.get("PYEPW_CACHE") or os.environ.get("OPEN_METEO_EPW_CACHE"):
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "pyEPW" / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pyEPW"


def atomic_text(path: Path, content: str) -> None:
    """Replace one text file using a temporary file in the same directory."""
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
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_bytes(path: Path, content: bytes) -> None:
    """Retain an original compressed public dataset atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
