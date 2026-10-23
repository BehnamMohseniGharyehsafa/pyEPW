"""Source-specific credits for downloaded products; not a blanket data licence."""

from __future__ import annotations

from typing import Any

CC_BY = "https://creativecommons.org/licenses/by/4.0/"


def source_attributions(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Describe only providers represented by the source metadata/downloads."""
    accessed = metadata.get("generated_utc")
    entries = [
        {
            "provider": "Open-Meteo",
            "product": "Historical Weather API",
            "credit": "Weather data by Open-Meteo.com",
            "source_url": "https://open-meteo.com/",
            "licence": "CC-BY-4.0",
            "licence_url": CC_BY,
            "terms_url": "https://open-meteo.com/en/terms",
            "access_condition": "Hosted free API: non-commercial use and published rate limits.",
            "citation": "Zippenfenig, P. (2023), Open-Meteo.com Weather API, doi:10.5281/zenodo.7970649.",
        },
        {
            "provider": "Copernicus C3S / ECMWF",
            "product": "ERA5",
            "credit": "Contains modified Copernicus Climate Change Service information.",
            "source_url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels",
            "licence": "CC-BY-4.0",
            "licence_url": CC_BY,
            "citation": "ERA5 hourly data on single levels, doi:10.24381/cds.adbb2d47.",
            "modifications": metadata.get("modifications", []),
        },
    ]
    if metadata.get("snow_model"):
        entries.append(
            {
                "provider": "Copernicus C3S / ECMWF",
                "product": "ERA5-Land",
                "credit": "Contains modified Copernicus Climate Change Service information.",
                "source_url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land",
                "licence": "CC-BY-4.0",
                "licence_url": CC_BY,
                "citation": "ERA5-Land hourly data, doi:10.24381/cds.e2161bac.",
            }
        )
    if metadata.get("city", {}).get("geonames_id"):
        entries.append(
            {
                "provider": "GeoNames",
                "product": "City/location data",
                "credit": "Location data: GeoNames.",
                "source_url": "https://www.geonames.org/",
                "licence": "CC-BY-4.0",
                "licence_url": CC_BY,
            }
        )
    urls = [item.get("url", "") for item in metadata.get("station_text_sources", [])]
    if any("GHCNh_" in url or "/pub/data/noaa/" in url and url.endswith(".gz") for url in urls):
        entries.append(
            {
                "provider": "NOAA NCEI and originating station networks",
                "product": "GHCNh / ISD station observations",
                "credit": "NOAA NCEI; retain originating station/network identities in observation lineage.",
                "source_url": "https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly",
                "licence": "Source-specific NOAA/originating-provider terms; not blanket CC-BY or CC0.",
                "terms_url": "https://www.noaa.gov/office-education/outreach-communication/faq",
                "citation": "Menne et al. (2023), GHCNh, doi:10.25921/jp3d-3v19; NOAA NCEI Global Surface Hourly (ISD), subset and access date in metadata.",
                "redistribution_note": "Verify originating-provider conditions for the selected international observations, especially commercial redistribution.",
            }
        )
    if any("mesonet.agron.iastate.edu" in url for url in urls):
        entries.append(
            {
                "provider": "Iowa Environmental Mesonet, Iowa State University",
                "product": "Published METAR archive",
                "credit": "Published METAR reports archived by Iowa Environmental Mesonet.",
                "source_url": "https://mesonet.agron.iastate.edu/request/download.phtml",
                "licence": "Public domain as stated by IEM; credit requested.",
                "terms_url": "https://mesonet.agron.iastate.edu/disclaimer.php",
                "quality_note": "Very little additional archive QC; distinct from NOAA QC-passed records.",
            }
        )
    responses = metadata.get("albedo_source", {}).get("responses", [])
    if responses:
        versions = sorted({str(r.get("header", {}).get("api", {}).get("version", "not supplied")) for r in responses})
        entries.append(
            {
                "provider": "NASA Langley Research Center POWER Project",
                "product": "Hourly POWER / CERES SYN1deg albedo",
                "credit": "NASA Langley Research Center POWER Project, funded by NASA Earth Science Division; CERES SYN1deg source product.",
                "source_url": "https://power.larc.nasa.gov/",
                "licence": "Public domain as described by NASA POWER; retain product-specific notices.",
                "terms_url": "https://forum.earthdata.nasa.gov/viewtopic.php?t=82",
                "reference_url": "https://power.larc.nasa.gov/docs/referencing/",
                "service": "POWER Hourly API",
                "api_versions": versions,
                "accessed_utc": accessed,
            }
        )
    return [{**entry, "retrieved_or_generated_utc": accessed} for entry in entries]


def attribution_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "software_licence": "MIT",
        "data_licence_scope": "The legacy data_licence field describes Open-Meteo/Copernicus components. Other products retain the source-specific terms below; downloaded data are not MIT-licensed by this package.",
        "source_attributions": source_attributions(metadata),
        "endorsement": "Independent conversion; no provider endorsement or certification implied.",
    }
