"""Analytical horizon cases on synthetic grids; no DEM download or GDAL required."""

import json
import math
import unittest

import numpy as np

from lunarwindow.terrain.dem import Grid
from lunarwindow.terrain.geometry import (
    elevation_angle_deg,
    great_circle_distance_m,
    latlon_to_stereographic,
    local_basis,
    sample_distances,
    smooth_sphere_horizon_deg,
    stereographic_to_latlon,
    unit_vector,
)
from lunarwindow.terrain.horizon import (
    OutsideCoverage,
    SiteSpec,
    compute_horizon,
    default_parameters,
    flat_horizon,
)
from lunarwindow.terrain.models import HorizonProfile
from lunarwindow.visibility.engine import calculate_visibility

R = 1_737_400.0
SITE = SiteSpec("test-site", "Test site", -88.0, 40.0, "Synthetic test grid")
FAST = default_parameters(maxRangeKm=12, nearFieldKm=12, raysPerDegree=2, stepGrowth=0.002)


def synthetic_grid(lat, lon, half_width_m, resolution_m, height_fn):
    """Grid centred on a site; height_fn(distance_m, azimuth_deg) gives each pixel height."""
    cx, cy = latlon_to_stereographic(lat, lon)
    n = int(2 * half_width_m / resolution_m)
    left, top = float(cx) - n * resolution_m / 2, float(cy) + n * resolution_m / 2
    centres = (np.arange(n) + 0.5) * resolution_m
    xs, ys = np.meshgrid(left + centres, top - centres)
    plat, plon = stereographic_to_latlon(xs, ys)
    distance = great_circle_distance_m(lat, lon, plat, plon)
    east, north, _ = local_basis(lat, lon)
    vectors = unit_vector(plat, plon)
    azimuth = np.degrees(np.arctan2(vectors @ east, vectors @ north)) % 360
    return Grid(height_fn(distance, azimuth).astype(float), left, top, resolution_m)


def plateau_angle(distance_m, height_m, observer_m):
    return float(elevation_angle_deg(distance_m, height_m, observer_m))


class GeometryTests(unittest.TestCase):
    def test_stereographic_matches_recorded_lola_pixel(self):
        # Site01 centre pixel from data/reference/site-provenance.json.
        x, y = latlon_to_stereographic(-89.46315775697248, -137.50198490762307)
        self.assertAlmostEqual(float(x), -10997.5, places=6)
        self.assertAlmostEqual(float(y), -12002.5, places=6)
        lat, lon = stereographic_to_latlon(x, y)
        self.assertAlmostEqual(float(lat), -89.46315775697248, places=10)
        self.assertAlmostEqual(float(lon), -137.50198490762307, places=10)

    def test_smooth_sphere_dip(self):
        self.assertAlmostEqual(smooth_sphere_horizon_deg(2.0), -math.degrees(math.sqrt(4 / R)), 4)
        self.assertEqual(smooth_sphere_horizon_deg(0.0), 0.0)
        with self.assertRaises(ValueError):
            smooth_sphere_horizon_deg(-1)

    def test_exact_elevation_matches_small_angle_formula(self):
        # Within a few km the exact angle agrees with atan((Δh - d²/2R) / d).
        exact = plateau_angle(5000.0, 300.0, 2.0)
        approx = math.degrees(math.atan((298.0 - 5000.0**2 / (2 * R)) / 5000.0))
        self.assertAlmostEqual(exact, approx, delta=0.002)

    def test_sample_distances_grow(self):
        distances = sample_distances(60, 50_000, 20, 0.001)
        self.assertEqual(distances[0], 60)
        self.assertEqual(distances[-1], 50_000)
        steps = np.diff(distances)
        self.assertTrue(np.all(steps > 0))
        self.assertAlmostEqual(steps[0], 20)
        self.assertGreater(steps[-2], 40)


class GridTests(unittest.TestCase):
    def test_bilinear_and_missing_data(self):
        grid = Grid(np.array([[0.0, 10.0], [20.0, np.nan]]), left=0, top=20, resolution_m=10)
        self.assertAlmostEqual(float(grid.sample(5, 15)), 0.0)
        self.assertTrue(np.isnan(grid.sample(10, 10)))  # Touches the NaN pixel.
        self.assertTrue(np.isnan(grid.sample(100, 100)))  # Outside.
        flat = Grid(np.array([[0.0, 10.0], [20.0, 30.0]]), left=0, top=20, resolution_m=10)
        self.assertAlmostEqual(float(flat.sample(10, 10)), 15.0)


class HorizonTests(unittest.TestCase):
    def test_flat_sphere_horizon_is_the_geometric_dip(self):
        grid = synthetic_grid(SITE.lat, SITE.lon, 13_000, 20, lambda d, a: np.zeros_like(d))
        profile = compute_horizon(SITE, grid, None, FAST)
        dip = smooth_sphere_horizon_deg(2.0)
        for point in profile.horizon:
            self.assertAlmostEqual(point.el, dip, places=3)
        self.assertEqual(profile.surfaceElevationM, 0.0)
        self.assertAlmostEqual(profile.observerAltitudeKm, 0.002)
        # The tangent point of a 2 m observer on a bare sphere is √(2Rh) ≈ 2.64 km away.
        self.assertAlmostEqual(np.nanmedian(profile.rays.horizonDistanceKm), 2.64, delta=0.1)

    def test_ring_plateau_matches_exact_angle(self):
        def ring(d, a):
            return np.where(d >= 5000, 300.0, 0.0)

        grid = synthetic_grid(SITE.lat, SITE.lon, 13_000, 20, ring)
        profile = compute_horizon(SITE, grid, None, FAST)
        expected = plateau_angle(5000, 300, 2)
        for point in profile.horizon:
            self.assertAlmostEqual(point.el, expected, delta=0.05)
        self.assertFalse(profile.quality.truncatedAzimuths)

    def test_directional_wall_and_wraparound(self):
        def walls(d, a):
            east = (a >= 85) & (a <= 95) & (d >= 3000) & (d <= 3500)
            north = ((a >= 357) | (a <= 3)) & (d >= 4000) & (d <= 4500)
            return np.where(east, 500.0, np.where(north, 200.0, 0.0))

        grid = synthetic_grid(SITE.lat, SITE.lon, 13_000, 20, walls)
        profile = compute_horizon(SITE, grid, None, FAST)
        el = [point.el for point in profile.horizon]
        dip = smooth_sphere_horizon_deg(2.0)
        self.assertAlmostEqual(el[90], plateau_angle(3000, 500, 2), delta=0.1)
        self.assertAlmostEqual(el[0], plateau_angle(4000, 200, 2), delta=0.1)
        self.assertGreater(el[359], 2)
        self.assertGreater(el[1], 2)
        self.assertAlmostEqual(el[180], dip, places=3)
        self.assertAlmostEqual(el[270], dip, places=3)
        self.assertLess(el[80], 0)

    def test_peak_observer_sees_below_bare_sphere_dip(self):
        grid = synthetic_grid(
            SITE.lat, SITE.lon, 13_000, 20, lambda d, a: np.maximum(0.0, 1000.0 - 0.2 * d)
        )
        profile = compute_horizon(SITE, grid, None, FAST)
        self.assertAlmostEqual(
            profile.surfaceElevationM, 1000.0, delta=5
        )  # Bilinear rounds the tip.
        self.assertLess(max(point.el for point in profile.horizon), -1)

    def test_far_field_fills_beyond_near_radius_and_edges_are_flagged(self):
        near = synthetic_grid(SITE.lat, SITE.lon, 3000, 20, lambda d, a: np.zeros_like(d))
        far = synthetic_grid(
            SITE.lat, SITE.lon, 8000, 100, lambda d, a: np.where(d >= 6000, 800.0, 0.0)
        )
        params = default_parameters(maxRangeKm=12, nearFieldKm=2, raysPerDegree=2, stepGrowth=0.002)
        profile = compute_horizon(SITE, near, far, params)
        self.assertGreater(min(point.el for point in profile.horizon), 6)
        self.assertEqual(len(profile.quality.truncatedAzimuths), 360)
        self.assertLess(profile.quality.minReachKm, 9)
        self.assertTrue(profile.quality.nearFieldAvailable)
        self.assertTrue(any("DEM edge" in warning for warning in profile.quality.warnings))
        self.assertEqual(len(profile.sources), 2)

    def test_outside_coverage_and_flat_fallback(self):
        grid = synthetic_grid(SITE.lat, SITE.lon, 2000, 20, lambda d, a: np.zeros_like(d))
        elsewhere = SiteSpec("far", "Far away", 0.67416, 23.47314, "test")
        with self.assertRaises(OutsideCoverage):
            compute_horizon(elsewhere, grid, None, FAST)
        profile = flat_horizon(elsewhere, FAST)
        self.assertEqual(profile.terrainModel, "none")
        self.assertIsNone(profile.rays)
        self.assertEqual(len(profile.horizon), 360)

    def test_profile_round_trips_and_feeds_the_visibility_engine(self):
        from lunarwindow.ephemeris.models import TimeRange

        grid = synthetic_grid(SITE.lat, SITE.lon, 13_000, 20, lambda d, a: np.zeros_like(d))
        profile = compute_horizon(SITE, grid, None, FAST)
        restored = HorizonProfile.model_validate(json.loads(profile.model_dump_json()))
        self.assertEqual(restored, profile)
        period = TimeRange("2026-11-14T00:00:00Z", "2026-11-14T02:00:00Z", 60)
        row = {
            "sunAz": 10.0,
            "sunEl": 0.1,
            "earthAz": 200.0,
            "earthEl": -0.5,
            "sunAngularRadiusDeg": 0.27,
            "earthAngularRadiusDeg": 0.95,
        }
        series = [
            {"t": "2026-11-14T00:00:00Z"} | row,
            {"t": "2026-11-14T01:00:00Z"} | row,
        ]
        horizon = [point.model_dump() for point in restored.horizon]
        result = calculate_visibility(series, horizon, period, rule="body-center")
        self.assertTrue(result.series[0].sunLit)
        self.assertFalse(result.series[0].earthVis)

    def test_rejects_malformed_profiles(self):
        grid = synthetic_grid(SITE.lat, SITE.lon, 13_000, 20, lambda d, a: np.zeros_like(d))
        data = json.loads(compute_horizon(SITE, grid, None, FAST).model_dump_json())
        broken = data | {"horizon": data["horizon"][:-1]}
        with self.assertRaises(ValueError):
            HorizonProfile.model_validate(broken)
        with self.assertRaises(ValueError):
            HorizonProfile.model_validate(data | {"sources": []})


if __name__ == "__main__":
    unittest.main()


class SchemaTests(unittest.TestCase):
    def test_packaged_schema_matches_model(self):
        from importlib.resources import files

        packaged = json.loads(
            files("lunarwindow.terrain").joinpath("horizon.schema.json").read_text("utf-8")
        )
        generated = HorizonProfile.model_json_schema()
        self.assertEqual(
            {k: v for k, v in packaged.items() if not k.startswith("$s") and k != "$id"}, generated
        )

    def test_example_profile_validates_against_json_schema(self):
        from importlib.resources import files

        import jsonschema

        schema = json.loads(
            files("lunarwindow.terrain").joinpath("horizon.schema.json").read_text("utf-8")
        )
        grid = synthetic_grid(SITE.lat, SITE.lon, 13_000, 20, lambda d, a: np.zeros_like(d))
        jsonschema.validate(
            json.loads(compute_horizon(SITE, grid, None, FAST).model_dump_json()), schema
        )
        jsonschema.validate(json.loads(flat_horizon(SITE, FAST).model_dump_json()), schema)
