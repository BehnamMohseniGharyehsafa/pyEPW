# Contributing

Use Python 3.10 or newer and a virtual environment:

```shell
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check pyEPW open_meteo_epw tests examples
python -m pip install ".[docs]"
python tools/check_repository.py
python -m build
python -m twine check dist/*
```

Tests use temporary synthetic weather and tiny catalog fixtures. They must not
make live API requests, consume quota, or require a city-directory download.
Keep temporary test directories inside the checkout; cleanup must remain scoped
to the directory that the individual test created.

Preserve the actual calendar, hour-ending solar convention, leap days, pressure
units and missing-data semantics when changing calculations. Add regression
tests for material conversion changes. EPW, CSV and TXT must represent the same
ordered records. Additional format exports must never re-download weather.

Public methods need annotations and docstrings. Libraries should log through
the `pyEPW` logger and should not print, configure root logging, or access
the network at import time. Do not write into the installed package directory.

The code uses the MIT licence. Downloaded data retain their separate terms and
attribution requirements; see NOTICE. Do not copy AGPL service implementation
code into the library without first resolving the resulting licence obligations.

Before a public release, choose the maintainer identity and project URLs, check
package-name availability, review service terms, and test the built wheel in a
clean environment. Uploading to a package index is a separate release action.

The GitHub release workflow builds/checks wheels and source distributions and
attaches them to a tagged GitHub release. It does not upload to PyPI or start
paid services. Figure inputs are committed: `python tools/build_figures.py` is
offline. Live continent examples are opt-in and subject to upstream limits.
