# Data sources, attribution and service conditions

Reviewed on **23 October 2026**. The [MIT licence](LICENSE) covers this project's
code. It does not relicense downloaded weather, locations or third-party products.
The [usage guide](docs/legal.md) explains publication and commercial-use boundaries.

| Component | Provider / product | Data terms and required credit |
|---|---|---|
| Weather API | [Open-Meteo](https://open-meteo.com/) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); credit Open-Meteo with a link, retain licence and identify modifications. Its [hosted free API terms](https://open-meteo.com/en/terms) restrict access to non-commercial use and rate limits. |
| Atmospheric reanalysis | [Copernicus C3S / ECMWF ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) | CC BY 4.0; cite dataset DOI [10.24381/cds.adbb2d47](https://doi.org/10.24381/cds.adbb2d47), subset and access date; identify derived EPW calculations. |
| Snow depth | [ERA5-Land](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land) | CC BY 4.0; cite DOI [10.24381/cds.e2161bac](https://doi.org/10.24381/cds.e2161bac) and modifications. |
| City data | [GeoNames](https://www.geonames.org/export/) | CC BY 4.0; credit GeoNames. Optional cities500 catalog is fetched separately. |
| Station observations | [NOAA NCEI GHCNh](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly) and [ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database) | Cite NOAA NCEI and originating networks. GHCNh DOI [10.25921/jp3d-3v19](https://doi.org/10.25921/jp3d-3v19). Global archives contain third-party observations: verify the selected product/originator's terms before commercial redistribution; do not assign blanket CC0. [NOAA guidance](https://www.noaa.gov/office-education/outreach-communication/faq). |
| Published METAR fallback | [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/request/download.phtml) | IEM states its materials are public domain and usable for lawful purposes; acknowledgement requested. Preserve originating station identity and [minimal-QC limitation](https://mesonet.agron.iastate.edu/disclaimer.php). |
| Hourly albedo | [NASA POWER / CERES SYN1deg](https://power.larc.nasa.gov/) | NASA POWER describes its data as public domain, including commercial applications. Retain product-specific notices and [POWER references](https://power.larc.nasa.gov/docs/referencing/): NASA Langley Research Center POWER Project, Earth Science Division, service, API version and access date. [NASA statement](https://forum.earthdata.nasa.gov/viewtopic.php?t=82). |

## Attribution that travels with a file

Each EPW/CSV/TXT export has `*.metadata.json` with `source_attributions`, source
URLs, access/generation time, source methods, modifications, coverage and hashes.
NASA responses retain API versions; accepted station records retain identities,
QC and qualifiers. Optional providers are credited when their products were
downloaded. Keep this metadata when sharing files and display the Open-Meteo
credit beside online results. A metadata sidecar does not replace visible
attribution on a website that displays those data.

Example notice, adjusting the sources to the actual export:

> Weather data by [Open-Meteo.com](https://open-meteo.com/). Contains modified
> Copernicus C3S/ECMWF ERA5 information, CC BY 4.0. Location data: GeoNames.
> Converted to actual-year EPW by pyEPW; derived fields, missing values and any
> station/NASA supplements are described in the accompanying metadata.

Do not imply endorsement by Open-Meteo, ECMWF, Copernicus, NOAA, NASA, GeoNames,
IEM, Met Éireann or EnergyPlus. These are reanalysis/derived files, not certified
observations at a building site. Missing source values are preserved.

## Published algorithms and software dependencies

- Perez, R. et al. (1990), *Modeling daylight availability and irradiance
  components from direct and global irradiance*, Solar Energy 44(5), 271–289,
  [doi:10.1016/0038-092X(90)90055-H](https://doi.org/10.1016/0038-092X(90)90055-H).
  Independent implementation; no paper PDF or third-party implementation bundled.
- Solar geometry: [NOAA/Meeus equations](https://gml.noaa.gov/grad/solcalc/calcdetails.html)
  and Spencer Earth-distance correction; infrared: documented Clark-Allen/Walton
  model. These are modeled/calculated quantities, not extra observations.
- Runtime dependency [`tzdata`](https://github.com/python/tzdata): package under
  Apache-2.0; IANA timezone data public domain. Installed separately, with its
  own licence. Python's standard library is supplied by the Python installation.
- Development/plotting dependencies are optional and retain their own licences.
  Repository diagrams and original figures are by pyEPW contributors; figure
  inputs retain the source credits in `docs/data/README.md`.

## Additional sources in the historical validation study

The old benchmark also used Met Éireann, DWD, JMA, Singapore NEA and ECCC for
specific comparisons. They are **not runtime providers** for the default library.
Their attribution and source links are in [validation sources](docs/validation_sources.md).
The repository publishes compact derived summaries, not those bulk raw archives.
