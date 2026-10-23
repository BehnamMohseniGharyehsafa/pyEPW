"""Data permissions remain separate from the software licence in every export."""

import unittest

from pyEPW._attribution import attribution_metadata


class AttributionTests(unittest.TestCase):
    def test_optional_credits_only_appear_for_downloaded_products(self):
        metadata = {"city": {"geonames_id": 1}, "generated_utc": "2026-10-23T00:00:00Z"}
        info = attribution_metadata(metadata)
        self.assertEqual(info["software_licence"], "MIT")
        self.assertEqual(
            [e["provider"] for e in info["source_attributions"]], ["Open-Meteo", "Copernicus C3S / ECMWF", "GeoNames"]
        )
        self.assertTrue(all(e["licence"] != "MIT" for e in info["source_attributions"]))

    def test_mixed_sources_retain_noaa_and_nasa_conditions_and_version(self):
        info = attribution_metadata(
            {
                "snow_model": "ERA5-Land",
                "generated_utc": "2026-10-23T00:00:00Z",
                "station_text_sources": [
                    {"url": "https://example.invalid/GHCNh_station.psv"},
                    {"url": "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=EICK"},
                ],
                "albedo_source": {"responses": [{"header": {"api": {"version": "v2.10.3"}}}]},
            }
        )
        sources = {entry["provider"]: entry for entry in info["source_attributions"]}
        self.assertIn("Source-specific", sources["NOAA NCEI and originating station networks"]["licence"])
        self.assertEqual(sources["NASA Langley Research Center POWER Project"]["api_versions"], ["v2.10.3"])
        self.assertIn("Iowa Environmental Mesonet, Iowa State University", sources)
