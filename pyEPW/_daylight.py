"""Perez et al. (1990) daylight models, independently implemented from paper.

Equations 1–3, 6–8, 10 and Table 4, Solar Energy 44(5), 271–289.
doi:10.1016/0038-092X(90)90055-H. Coefficients are published model data.
These outputs are estimates, not photometer measurements.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math

from ._solar import SolarInterval

GLOBAL = (
    (96.63, -0.47, 11.50, -9.16),
    (107.54, 0.79, 1.79, -1.19),
    (98.73, 0.70, 4.40, -6.95),
    (92.72, 0.56, 8.36, -8.31),
    (86.73, 0.98, 7.10, -10.94),
    (88.34, 1.39, 6.06, -7.60),
    (78.63, 1.47, 4.93, -11.37),
    (99.65, 1.86, -4.46, -3.15),
)
DIRECT = (
    (57.20, -4.55, -2.98, 117.12),
    (98.99, -3.46, -1.21, 12.38),
    (109.83, -4.90, -1.71, -8.81),
    (110.34, -5.84, -1.99, -4.56),
    (106.36, -3.97, -1.75, -6.16),
    (107.19, -1.25, -1.51, -26.73),
    (105.75, 0.77, -1.26, -34.44),
    (101.18, 1.58, -1.10, -8.29),
)
DIFFUSE = (
    (97.24, -0.46, 12.00, -8.91),
    (107.22, 1.15, 0.59, -3.95),
    (104.97, 2.96, -5.53, -8.77),
    (102.39, 5.59, -13.95, -13.90),
    (100.71, 5.94, -22.75, -23.74),
    (106.42, 3.83, -36.15, -28.83),
    (141.88, 1.90, -53.24, -14.03),
    (152.23, 0.35, -45.27, -7.98),
)
ZENITH = (
    (40.86, 26.77, -29.59, -45.75),
    (26.58, 14.73, 58.46, -21.25),
    (19.34, 2.28, 100.00, 0.25),
    (13.25, -1.39, 124.79, 15.66),
    (14.47, -5.09, 160.09, 9.13),
    (19.76, -3.88, 154.61, -19.21),
    (28.39, -9.67, 151.58, -69.39),
    (42.91, -19.62, 130.80, -164.08),
)
CLEARNESS_BOUNDS = (1.065, 1.230, 1.500, 1.950, 2.800, 4.500, 6.200)


@dataclass(frozen=True)
class Daylight:
    global_lux: float
    direct_normal_lux: float
    diffuse_lux: float
    zenith_cd_m2: float
    low_sun_extrapolation: bool = False


def perez_daylight(solar: SolarInterval, ghi: float, dni: float, dhi: float, dewpoint: float) -> Daylight:
    """Hour-average daylight from hour-average irradiances and surface dew point.

    Uses the paper's dew-point water proxy (0.07 coefficient), not a claim that
    column water can be measured from ground humidity. Real ERA5 column water
    is fetched separately for the EPW precipitable-water field. The empirical
    models are independent fits; GHI lux need not equal DHI lux + DNI lux*cosZ.
    """
    if solar.daylight_fraction <= 0 or max(ghi, dni, dhi) <= 0:
        return Daylight(0, 0, 0, 0)
    c = max(0.0, min(1.0, solar.daylight_mean_cosine))
    z = math.acos(c)
    fraction = solar.daylight_fraction
    # Convert full-hour means to daylight-only means for a partial sunrise or
    # sunset interval, then average the modeled photometry back over the hour.
    diffuse = max(0.1, dhi / fraction)
    direct = dni / fraction
    eps = ((diffuse + direct) / diffuse + 1.041 * z**3) / (1 + 1.041 * z**3)
    category = bisect_left(CLEARNESS_BOUNDS, eps)
    # Kasten–Young 1989 relative optical air mass, geometric zenith.
    airmass = 1 / (c + 0.50572 * (96.07995 - math.degrees(z)) ** -1.6364)
    delta = max(1e-8, diffuse * airmass / 1360)
    water_cm = math.exp(0.07 * dewpoint - 0.075)

    def horizontal(coefficients, irradiance):
        a, b, cc, d = coefficients[category]
        return max(0.0, irradiance * (a + b * water_cm + cc * c + d * math.log(delta)))

    global_lux = horizontal(GLOBAL, ghi)
    diffuse_lux = horizontal(DIFFUSE, dhi)
    a, b, cc, d = DIRECT[category]
    direct_lux = max(0.0, dni * (a + b * water_cm + cc * math.exp(5.73 * z - 5) + d * delta))
    a, cc, cp, d = ZENITH[category]
    # Authors recommend Z'=max(Z,0.6) in the lowest clearness bin.
    zz = max(z, 0.6) if category == 0 else z
    zenith = max(0.0, dhi * (a + cc * math.cos(zz) + cp * math.exp(-3 * zz) + d * delta))
    return Daylight(global_lux, direct_lux, diffuse_lux, zenith, z > math.radians(85))
