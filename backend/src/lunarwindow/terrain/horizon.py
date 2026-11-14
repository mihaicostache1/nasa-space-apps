"""Ray-cast terrain horizons from LOLA height grids.

For each site, rays leave the observer along great circles at `raysPerDegree` per degree of
azimuth. Each ray samples terrain heights (bilinear) at distances that start at about one
pixel and grow geometrically, using the fine near-field grid within `nearFieldKm` and the
coarse far-field grid beyond it (or wherever the fine grid has no data). Every sample's exact
apparent elevation is computed on the sphere; the ray's horizon is its maximum. Whole-degree
values are the maximum of the rays in [az - 0.5°, az + 0.5°), so a narrow peak is never lost
between integer azimuths and visibility errs toward "blocked".
"""

import math
from dataclasses import dataclass

import numpy as np

from .dem import Grid
from .geometry import (
    elevation_angle_deg,
    latlon_to_stereographic,
    ray_unit_vectors,
    sample_distances,
    smooth_sphere_horizon_deg,
    stereographic_from_vectors,
)
from .models import (
    HorizonParameters,
    HorizonProfile,
    HorizonQuality,
    HorizonSource,
    RayProfile,
)
from .products import REFERENCE_RADIUS_M

ALGORITHM_VERSION = "lunarwindow.horizon-raycast.1"
RAY_CHUNK = 120


class OutsideCoverage(ValueError):
    """The site has no valid DEM height, so a terrain horizon cannot be computed."""


@dataclass(frozen=True)
class SiteSpec:
    site_id: str
    name: str
    lat: float
    lon: float
    coordinate_source: str


def default_parameters(**changes) -> HorizonParameters:
    values = {
        "mastHeightM": 2.0,
        "maxRangeKm": 200.0,
        "nearFieldKm": 25.0,
        "minDistanceM": 60.0,
        "raysPerDegree": 10,
        "stepGrowth": 0.001,
    }
    return HorizonParameters(**(values | changes))


def _bin_max(values: np.ndarray, rays_per_degree: int) -> np.ndarray:
    if rays_per_degree == 1:
        return values
    if rays_per_degree % 2:
        raise ValueError("raysPerDegree must be 1 or even so bins centre on whole degrees.")
    return np.roll(values, rays_per_degree // 2).reshape(360, rays_per_degree).max(axis=1)


def _sources(*grids: Grid | None) -> list[HorizonSource]:
    sources = []
    for grid in grids:
        if grid is not None:
            sources.append(
                HorizonSource(
                    productId=grid.source.get("productId"),
                    role=grid.source.get("role"),
                    sourceUrl=grid.source.get("sourceUrl"),
                    sha256=grid.source.get("sha256"),
                    resolutionM=float(grid.resolution_m),
                )
            )
    return sources


def surface_height(lat: float, lon: float, near: Grid | None, far: Grid | None):
    x, y = latlon_to_stereographic(lat, lon)
    for grid in (near, far):
        if grid is not None:
            value = float(grid.sample(x, y))
            if math.isfinite(value):
                return value, grid
    raise OutsideCoverage(f"No DEM height at lat={lat}, lon={lon}.")


def compute_horizon(
    site: SiteSpec,
    near: Grid | None,
    far: Grid | None,
    parameters: HorizonParameters | None = None,
    radius: float = REFERENCE_RADIUS_M,
) -> HorizonProfile:
    params = parameters or default_parameters()
    surface, surface_grid = surface_height(site.lat, site.lon, near, far)
    observer = surface + params.mastHeightM
    base_step = min(grid.resolution_m for grid in (near, far) if grid is not None)
    distances = sample_distances(
        params.minDistanceM, params.maxRangeKm * 1000, base_step, params.stepGrowth
    )
    use_near = distances <= params.nearFieldKm * 1000
    count = 360 * params.raysPerDegree
    azimuths = np.arange(count) / params.raysPerDegree
    ray_el = np.empty(count)
    ray_dist = np.full(count, np.nan)
    ray_reach = np.zeros(count)
    missing = 0

    for start in range(0, count, RAY_CHUNK):
        chunk = azimuths[start : start + RAY_CHUNK]
        x, y = stereographic_from_vectors(
            ray_unit_vectors(site.lat, site.lon, chunk, distances, radius), radius
        )
        heights = np.full(x.shape, np.nan)
        if near is not None:
            heights[:, use_near] = near.sample(x[:, use_near], y[:, use_near])
        if far is not None:
            gaps = np.isnan(heights)
            heights[gaps] = far.sample(x[gaps], y[gaps])
        valid = ~np.isnan(heights)
        missing += int((~valid).sum())
        elevations = np.where(
            valid, elevation_angle_deg(distances, heights, observer, radius), -np.inf
        )
        best = elevations.argmax(axis=1)
        rows = np.arange(len(chunk))
        found = valid[rows, best]
        stop = start + len(chunk)
        ray_el[start:stop] = np.where(found, elevations[rows, best], np.nan)
        ray_dist[start:stop] = np.where(found, distances[best], np.nan)
        last_valid = np.where(valid.any(axis=1), valid.shape[1] - 1 - valid[:, ::-1].argmax(1), -1)
        ray_reach[start:stop] = np.where(last_valid >= 0, distances[last_valid.clip(0)], 0.0)

    # Rays with no terrain at all fall back to the bare-sphere horizon and are flagged. Valid
    # rays keep values below that dip: an observer on a peak sees terrain falling away.
    dip = smooth_sphere_horizon_deg(params.mastHeightM, radius)
    ray_el = np.where(np.isnan(ray_el), dip, ray_el)
    truncated_rays = ray_reach < distances[-1] - 1e-6
    truncated_bins = _bin_max(truncated_rays.astype(np.int8), params.raysPerDegree)
    degree_el = _bin_max(ray_el, params.raysPerDegree)

    warnings = []
    if truncated_bins.any():
        warnings.append(
            f"{int(truncated_bins.sum())} azimuth bins reach the DEM edge before "
            f"{params.maxRangeKm:g} km; distant terrain there is not modelled."
        )
    if near is None or surface_grid is not near:
        warnings.append("No near-field DEM at the site; local terrain uses the coarse grid.")
    total = count * len(distances)
    return HorizonProfile(
        siteId=site.site_id,
        name=site.name,
        lat=site.lat,
        lon=site.lon,
        coordinateSource=site.coordinate_source,
        terrainModel="lola-dem",
        surfaceElevationM=round(surface, 3),
        mastHeightM=params.mastHeightM,
        observerAltitudeKm=round(observer / 1000, 6),
        referenceRadiusM=radius,
        horizon=[{"az": az, "el": round(float(el), 4)} for az, el in enumerate(degree_el)],
        rays=RayProfile(
            stepDeg=1 / params.raysPerDegree,
            el=[round(float(value), 4) for value in ray_el],
            horizonDistanceKm=[
                None if math.isnan(value) else round(float(value) / 1000, 3) for value in ray_dist
            ],
            reachKm=[round(float(value) / 1000, 3) for value in ray_reach],
        ),
        quality=HorizonQuality(
            truncatedAzimuths=[int(az) for az in np.flatnonzero(truncated_bins)],
            minReachKm=round(float(ray_reach.min()) / 1000, 3),
            missingSampleFraction=round(missing / total, 6),
            nearFieldAvailable=near is not None and surface_grid is near,
            warnings=warnings,
        ),
        parameters=params,
        sources=_sources(near, far),
        algorithmVersion=ALGORITHM_VERSION,
    )


def flat_horizon(
    site: SiteSpec,
    parameters: HorizonParameters | None = None,
    surface_elevation_m: float | None = None,
    radius: float = REFERENCE_RADIUS_M,
) -> HorizonProfile:
    """Bare-sphere horizon for sites outside DEM coverage; explicitly `terrainModel: none`."""
    params = parameters or default_parameters()
    dip = round(smooth_sphere_horizon_deg(params.mastHeightM, radius), 4)
    base = surface_elevation_m if surface_elevation_m is not None else 0.0
    return HorizonProfile(
        siteId=site.site_id,
        name=site.name,
        lat=site.lat,
        lon=site.lon,
        coordinateSource=site.coordinate_source,
        terrainModel="none",
        surfaceElevationM=surface_elevation_m,
        mastHeightM=params.mastHeightM,
        observerAltitudeKm=round((base + params.mastHeightM) / 1000, 6),
        referenceRadiusM=radius,
        horizon=[{"az": az, "el": dip} for az in range(360)],
        rays=None,
        quality=HorizonQuality(
            truncatedAzimuths=list(range(360)),
            minReachKm=0.0,
            missingSampleFraction=1.0,
            nearFieldAvailable=False,
            warnings=["Outside the polar LOLA DEMs: bare-sphere horizon, terrain is not modelled."],
        ),
        parameters=params,
        sources=[],
        algorithmVersion=ALGORITHM_VERSION,
    )
