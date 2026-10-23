# Architecture and UML

The public entry point is `pyEPW.EPW(city, year, format)`. Construction resolves
the site, loads one actual calendar year, validates it and writes the selected
format. Additional exports use the same in-memory dataset. Importing the module
does not download data or create files.

## Data flow

```mermaid
flowchart LR
    U[City + actual year] --> A[Python API / CLI]
    A --> L[Location and fixed standard UTC offset]
    L --> C[Cached public HTTP client]
    C --> O[Open-Meteo ERA5 / ERA5-Land]
    C --> N[NASA POWER albedo]
    C --> S[NOAA GHCNh / ISD / published METAR]
    O --> E[Hour-ending alignment and unit conversion]
    N --> E
    S --> E
    E --> D[Astronomical and empirical derived fields]
    D --> Q[Calendar, core values, ranges and coverage]
    Q -->|requirements pass| W[EPW / CSV / TXT / analysis CSV]
    Q -->|required data missing| X[DataError before writing]
    W --> P[Source-specific attribution, hashes and lineage]
    classDef source fill:#e6f3f0,stroke:#087f75,color:#153b3a;
    classDef output fill:#eaf0ff,stroke:#5368bc,color:#21324a;
    class O,N,S source;
    class W,P output;
```

Core missing data stops conversion. Optional unsupported values remain explicit
gaps unless a required-field check rejects the export. There is no generic
numeric replacement to make a file appear complete.

## Class diagram

```mermaid
classDiagram
    class EPW {
        +Location location
        +int year
        +Path path
        +int hours
        +bool is_complete
        +dict missing_fields
        +dict metadata
        +to_epw(path, overwrite) Path
        +to_csv(path, overwrite) Path
        +to_txt(path, overwrite) Path
        +to_analysis_csv(path, overwrite) Path
        +quality_report() str
        +iter_records() Iterator
    }
    class Location {
        <<dataclass>>
        +str name
        +str country_code
        +float latitude
        +float longitude
        +float elevation
        +str timezone
        +int geonames_id
    }
    class WeatherDataset {
        <<dataclass>>
        +Location location
        +int year
        +tuple headers
        +tuple rows
        +dict metadata
    }
    class APIClient {
        +Path cache_dir
        +list urls
        +get(endpoint, parameters) dict
        +get_text(url, expected_start) str
    }
    class OutputFormat {
        <<enumeration>>
        EPW
        CSV
        TXT
    }
    class CityCatalog {
        +download(cache_dir) CityCatalog
        +iter_cities(country, limit) Iterator
        +export(path, country, overwrite) Path
    }
    class PyEPWError
    class DataError
    class APIError
    class ValidationError
    EPW *-- WeatherDataset : loaded once
    WeatherDataset --> Location
    EPW --> APIClient : requests through engine
    EPW --> OutputFormat
    CityCatalog --> Location : discovers
    PyEPWError <|-- DataError
    PyEPWError <|-- APIError
    PyEPWError <|-- ValidationError
```

`Location` and `WeatherDataset` are frozen dataclasses. Weather rows are immutable
tuples. Metadata properties return defensive copies. `OpenMeteoEPWError` and the
old `open_meteo_epw` namespace are compatibility aliases, not separate engines.

## Request and export sequence

```mermaid
sequenceDiagram
    actor User
    participant API as pyEPW.EPW
    participant Client as Cached HTTP client
    participant Sources as Public providers
    participant Engine as Conversion and coverage
    participant Writer as File writers
    User->>API: EPW(city, year, format)
    API->>Client: Resolve city and request actual-year inputs
    alt Response in cache
        Client-->>API: Cached original response
    else Uncached request
        Client->>Sources: Public data request
        Sources-->>Client: Original response / missing values
        Client-->>API: Validated response and provenance
    end
    API->>Engine: Assemble fixed-standard-time hourly records
    Engine-->>API: Dataset, coverage, warnings and lineage
    alt Required weather is absent
        API-->>User: DataError, no output written
    else Requirements pass
        API->>Writer: Write selected format + metadata
        Writer-->>User: Output path
        User->>API: to_csv() / to_txt()
        API->>Writer: Export the already loaded dataset
        Writer-->>User: Additional path, no new weather request
    end
```

## Source ownership

| Module | Responsibility |
|---|---|
| `api.py`, `cli.py` | Input validation and public entry points |
| `client.py`, `_files.py` | Bounded downloads, cache, hashes and atomic output |
| `_engine.py` | Actual-year calendar, resampling, units and assembly |
| `_solar.py`, `_daylight.py` | Astronomical integration and Perez photometry |
| `observations.py`, `station_fallbacks.py` | Source-aware QC, distance/time matching and gap-only station archives |
| `supplements.py` | ERA5 snowfall history and valid NASA albedo |
| `quality.py`, `_attribution.py` | Coverage/missing codes and source-specific credits |
| `writers.py` | Canonical formats, analysis export and metadata sidecars |

The [methodology](methodology.md) documents approximations and the
[source register](../DATA_SOURCES.md) documents data/access conditions.
