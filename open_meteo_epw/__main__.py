"""Compatibility command: prefer python -m pyEPW."""

from pyEPW.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
