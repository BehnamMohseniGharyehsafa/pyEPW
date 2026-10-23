"""Geometric solar position and integrated top-of-atmosphere hourly energy.

Independent implementation of NOAA's published Meeus-based solar equations.
No refraction: extraterrestrial radiation uses the geometric horizon.
Earth-distance correction: Spencer (1971), solar constant 1361 W/m².
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math

SOLAR_CONSTANT = 1361.0


@lru_cache(maxsize=4096)
def solar_cosine(instant: datetime, latitude: float, longitude: float) -> float:
    """Cosine of geometric zenith at a UTC-aware instant, east-positive longitude."""
    t = instant.astimezone(timezone.utc)
    jd = t.timestamp() / 86400 + 2440587.5
    century = (jd - 2451545) / 36525
    mean_longitude = (280.46646 + century * (36000.76983 + 0.0003032 * century)) % 360
    anomaly = math.radians(357.52911 + century * (35999.05029 - 0.0001537 * century))
    eccentricity = 0.016708634 - century * (0.000042037 + 0.0000001267 * century)
    center = (
        math.sin(anomaly) * (1.914602 - century * (0.004817 + 0.000014 * century))
        + math.sin(2 * anomaly) * (0.019993 - 0.000101 * century)
        + 0.000289 * math.sin(3 * anomaly)
    )
    omega = math.radians(125.04 - 1934.136 * century)
    apparent_longitude = math.radians(mean_longitude + center - 0.00569 - 0.00478 * math.sin(omega))
    obliquity = math.radians(
        23
        + (26 + (21.448 - century * (46.815 + century * (0.00059 - 0.001813 * century))) / 60) / 60
        + 0.00256 * math.cos(omega)
    )
    declination = math.asin(math.sin(obliquity) * math.sin(apparent_longitude))
    y = math.tan(obliquity / 2) ** 2
    mean_longitude_rad = math.radians(mean_longitude)
    equation = 4 * math.degrees(
        y * math.sin(2 * mean_longitude_rad)
        - 2 * eccentricity * math.sin(anomaly)
        + 4 * eccentricity * y * math.sin(anomaly) * math.cos(2 * mean_longitude_rad)
        - 0.5 * y * y * math.sin(4 * mean_longitude_rad)
        - 1.25 * eccentricity**2 * math.sin(2 * anomaly)
    )
    minutes = t.hour * 60 + t.minute + t.second / 60 + t.microsecond / 60e6
    hour_angle = math.radians(((minutes + equation + 4 * longitude) % 1440) / 4 - 180)
    lat = math.radians(latitude)
    return max(
        -1.0,
        min(1.0, math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)),
    )


@lru_cache(maxsize=4096)
def extraterrestrial_normal(instant: datetime) -> float:
    """Earth-distance-adjusted normal irradiance, W/m² (before horizon masking)."""
    utc = instant.astimezone(timezone.utc)
    # Spencer's 365-day harmonic convention is retained in leap years.
    angle = 2 * math.pi * (utc.timetuple().tm_yday - 1) / 365
    correction = (
        1.00011
        + 0.034221 * math.cos(angle)
        + 0.00128 * math.sin(angle)
        + 0.000719 * math.cos(2 * angle)
        + 0.000077 * math.sin(2 * angle)
    )
    return SOLAR_CONSTANT * correction


@dataclass(frozen=True)
class SolarInterval:
    horizontal_wh_m2: float
    direct_normal_wh_m2: float
    daylight_fraction: float
    daylight_mean_cosine: float


def solar_interval(end_utc: datetime, latitude: float, longitude: float) -> SolarInterval:
    """Integrate the preceding hour, explicitly locating sunrise/sunset crossings.

    Five-minute brackets with horizon roots to <0.01 seconds and Simpson
    integration in each illuminated subinterval avoid midnight and sunrise
    midpoint shifts. Energy is Wh/m²; normal energy is daylight-masked.
    """
    start = end_utc - timedelta(hours=1)

    def cosine(seconds):
        return solar_cosine(start + timedelta(seconds=seconds), latitude, longitude)

    boundaries = [0.0]
    left = 0.0
    c_left = cosine(left)
    for step in range(1, 13):
        right = step * 300.0
        c_right = cosine(right)
        if c_left * c_right < 0:
            lo, hi, c_lo = left, right, c_left
            for _ in range(16):
                mid = (lo + hi) / 2
                if c_lo * cosine(mid) <= 0:
                    hi = mid
                else:
                    lo, c_lo = mid, cosine(mid)
            boundaries.append((lo + hi) / 2)
        boundaries.append(right)
        left, c_left = right, c_right
    horizontal = normal = duration = cosine_integral = 0.0
    for lo, hi in zip(boundaries, boundaries[1:]):
        mid = (lo + hi) / 2
        if cosine(mid) <= 0:
            continue
        seconds = hi - lo
        weights = [(lo, 1), (mid, 4), (hi, 1)]
        c = sum(weight * max(0, cosine(t)) for t, weight in weights) / 6
        norm = sum(weight * extraterrestrial_normal(start + timedelta(seconds=t)) for t, weight in weights) / 6
        horiz = (
            sum(
                weight * extraterrestrial_normal(start + timedelta(seconds=t)) * max(0, cosine(t))
                for t, weight in weights
            )
            / 6
        )
        cosine_integral += seconds * c
        duration += seconds
        normal += seconds * norm / 3600
        horizontal += seconds * horiz / 3600
    return SolarInterval(horizontal, normal, duration / 3600, cosine_integral / duration if duration else 0)
