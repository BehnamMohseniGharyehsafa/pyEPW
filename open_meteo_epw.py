"""Compatibility launcher. Prefer: python -m pyEPW CITY YEAR."""

from pyEPW.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
