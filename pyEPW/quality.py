"""Field-level completeness, source classes and EPW sentinel interpretation."""

from __future__ import annotations

from .models import EPW_COLUMNS

ADDITIONAL_FIELDS = tuple(EPW_COLUMNS[i] for i in (10, 11, 16, 17, 18, 19, 24, 25, 28, 31, 32))
MISSING_LIMITS = {
    6: 99.9,
    7: 99.9,
    8: 999,
    9: 999999,
    10: 9999,
    11: 9999,
    12: 9999,
    13: 9999,
    14: 9999,
    15: 9999,
    16: 999900,
    17: 999900,
    18: 999900,
    19: 9999,
    20: 999,
    21: 999,
    22: 99,
    23: 99,
    24: 9999,
    25: 99999,
    26: 9,
    27: 999999999,
    28: 999,
    29: 0.999,
    30: 999,
    31: 99,
    32: 999,
    33: 999,
    34: 99,
}


def field_coverage(rows):
    methods = {
        10: (
            "astronomical_calculation",
            "NOAA/Meeus geometric solar position; Spencer distance correction; integrated previous hour",
        ),
        11: (
            "astronomical_calculation",
            "Daylight-masked extraterrestrial normal energy integrated over the previous hour",
        ),
        12: ("empirical_model", "Clark-Allen/Walton infrared; total cloud cover as opaque-cover proxy"),
        16: ("empirical_model", "Perez 1990 global luminous efficacy, original Table 4"),
        17: ("empirical_model", "Perez 1990 direct luminous efficacy, original Table 4"),
        18: ("empirical_model", "Perez 1990 diffuse luminous efficacy, original Table 4"),
        19: ("empirical_model", "Perez 1990 Eq.10 zenith luminance in cd/m²; values in EPW missing range rejected"),
        23: ("empirical_model", "Total cloud cover used as opaque-cloud proxy"),
        24: (
            "nearby_station_observation",
            "NOAA GHCNh; optional gap-only QC-filtered ISD and published METAR; per-row provider/QC retained",
        ),
        25: (
            "nearby_station_observation",
            "Reported NOAA ceilings or observed METAR BKN/OVC/VV; no cloud-base proxy or CAVOK inference",
        ),
        28: ("reanalysis", "ERA5 total-column integrated water vapour: 1 kg/m² = 1 mm liquid water"),
        30: ("reanalysis", "ERA5-Land snow depth, m to cm"),
        31: (
            "derived_reanalysis",
            "Elapsed whole days from ERA5 hourly snowfall with 89-day lookback; 88 means >=88; source gaps stay unknown",
        ),
        32: (
            "satellite_derived",
            "NASA POWER ALLSKY_SRF_ALB hourly means; provider fill codes and undefined nighttime ratios remain missing",
        ),
    }
    result = {}
    for index in range(6, 35):
        valid = sum(float(row[index]) < MISSING_LIMITS[index] for row in rows)
        kind, method = methods.get(index, ("reanalysis", "ERA5 via Open-Meteo; see request URLs and unit conversions"))
        if not valid:
            kind, method = "unavailable", "EPW missing sentinel; no value invented"
        result[EPW_COLUMNS[index]] = {
            "data_kind": kind,
            "method": method,
            "valid_hours": valid,
            "missing_hours": len(rows) - valid,
            "coverage_percent": 100 * valid / len(rows) if rows else 0,
            "missing_when_greater_or_equal": MISSING_LIMITS[index],
        }
    return result
