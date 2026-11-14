"""Exact spherical geometry for horizon ray casting (no curvature approximations).

Conventions match the rest of LunarWindow: latitude in degrees, east-positive longitude,
azimuth clockwise from local north, elevation above the local horizontal plane. Heights are
metres above the 1737.4 km reference sphere used by LOLA and by the archived Horizons
responses. The south polar stereographic projection is the one used by every LOLA polar
product: lat_0 = lat_ts = -90°, lon_0 = 0°, true scale at the pole.

At exactly ±90° latitude "north" is undefined; the supplied longitude then selects the
meridian used as azimuth 0°, as in the local basis formulas below.
"""

import math

import numpy as np

from .products import REFERENCE_RADIUS_M


def unit_vector(lat_deg, lon_deg) -> np.ndarray:
    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1)


def local_basis(lat_deg: float, lon_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (east, north, up) unit vectors in the Moon-fixed frame."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array(
        [-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)]
    )
    return east, north, unit_vector(lat_deg, lon_deg)


def stereographic_from_vectors(vectors: np.ndarray, radius: float = REFERENCE_RADIUS_M):
    """Project unit vectors (…, 3) to south polar stereographic x, y in metres."""
    scale = 2 * radius / (1 - vectors[..., 2])
    return scale * vectors[..., 1], scale * vectors[..., 0]


def latlon_to_stereographic(lat_deg, lon_deg, radius: float = REFERENCE_RADIUS_M):
    return stereographic_from_vectors(unit_vector(lat_deg, lon_deg), radius)


def stereographic_to_latlon(x, y, radius: float = REFERENCE_RADIUS_M):
    rho = np.hypot(x, y)
    lat = -90 + np.degrees(2 * np.arctan(rho / (2 * radius)))
    lon = np.degrees(np.arctan2(x, y))
    return lat, lon


def ray_unit_vectors(
    lat_deg: float,
    lon_deg: float,
    azimuths_deg: np.ndarray,
    distances_m: np.ndarray,
    radius: float = REFERENCE_RADIUS_M,
) -> np.ndarray:
    """Points along great circles leaving the site at each azimuth, shape (A, D, 3).

    A great circle through the observer lies in the vertical plane of its initial azimuth,
    so every point on it is seen at exactly that azimuth.
    """
    east, north, up = local_basis(lat_deg, lon_deg)
    angle = np.radians(azimuths_deg)
    directions = np.cos(angle)[:, None] * north + np.sin(angle)[:, None] * east
    central = np.asarray(distances_m) / radius
    return (
        np.cos(central)[None, :, None] * up
        + np.sin(central)[None, :, None] * directions[:, None, :]
    )


def elevation_angle_deg(
    distances_m, heights_m, observer_height_m: float, radius: float = REFERENCE_RADIUS_M
):
    """Apparent elevation of a surface point at great-circle distance d and height h.

    In the vertical plane, the point is at (r·sin δ, r·cos δ) with r = R + h and δ = d / R;
    the observer is at (0, R + h₀). This is exact on the sphere, unlike d² / 2R.
    """
    central = np.asarray(distances_m) / radius
    r = radius + np.asarray(heights_m)
    return np.degrees(
        np.arctan2(r * np.cos(central) - (radius + observer_height_m), r * np.sin(central))
    )


def smooth_sphere_horizon_deg(observer_height_m: float, radius: float = REFERENCE_RADIUS_M):
    """Geometric horizon dip seen from height h above a bare sphere: -acos(R / (R + h))."""
    if observer_height_m < 0:
        raise ValueError("Observer height above the local surface must be nonnegative.")
    return -math.degrees(math.acos(radius / (radius + observer_height_m)))


def great_circle_distance_m(lat1, lon1, lat2, lon2, radius: float = REFERENCE_RADIUS_M):
    a, b = unit_vector(lat1, lon1), unit_vector(lat2, lon2)
    cross = np.linalg.norm(np.cross(a, b), axis=-1)
    return radius * np.arctan2(cross, np.sum(a * b, axis=-1))


def sample_distances(
    min_distance_m: float, max_distance_m: float, base_step_m: float, growth: float
) -> np.ndarray:
    """Step ≈ one DEM pixel near the site, then grow geometrically with distance.

    Growth g keeps each step below g radians of arc as seen from the observer, so far-away
    terrain is sampled at a near-constant angular spacing.
    """
    if not 0 < min_distance_m < max_distance_m or base_step_m <= 0 or growth < 0:
        raise ValueError("Invalid ray sampling parameters.")
    values = [min_distance_m]
    while values[-1] < max_distance_m:
        values.append(min(values[-1] + max(base_step_m, values[-1] * growth), max_distance_m))
    return np.array(values)
