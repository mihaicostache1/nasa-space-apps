"""Strict custom terrain uses real ray casting with controlled synthetic DEM adapters."""

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from lunarwindow.api.custom_models import CustomLocation, observer_site_id
from lunarwindow.observer import canonical_model_sha256
from lunarwindow.terrain import custom
from lunarwindow.terrain.dem import Grid
from lunarwindow.terrain.download import sidecar_path
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.horizon import compute_horizon, default_parameters
from lunarwindow.terrain.products import FAR_FIELD, NEAR_FIELD, PRODUCTS

LAT = -89.0
LON = 0.0


class FakeDem:
    """Small synthetic grid; only file/CRS I/O is replaced, not ray geometry."""

    grids = {}

    def __init__(self, path, provenance):
        self.provenance = {
            "productId": provenance["productId"],
            "role": provenance["role"],
            "sourceUrl": provenance["sourceUrl"],
            "sha256": provenance["sha256"],
            "resolutionM": provenance["resolutionM"],
        }
        self.grid = self.grids[provenance["productId"]]
        self.resolution_m = self.grid.resolution_m
        self._dataset = SimpleNamespace(crs=SimpleNamespace(to_wkt=lambda: "SYNTHETIC test CRS"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def contains(self, x, y):
        return self.grid.left <= x <= self.grid.right and self.grid.bottom <= y <= self.grid.top

    def read_patch(self, x, y, radius_m):
        return Grid(
            self.grid.data, self.grid.left, self.grid.top, self.resolution_m, self.provenance
        )


class CustomTerrainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dem_dir = self.root / "dem"
        self.cache_dir = self.root / "cache"
        self.dem_dir.mkdir()
        self.products = dict(PRODUCTS)
        x, y = (float(v) for v in latlon_to_stereographic(LAT, LON))
        FakeDem.grids = {}
        for pid in (NEAR_FIELD, FAR_FIELD):
            content = f"SYNTHETIC DEM bytes for {pid}".encode()
            product = self.products[pid] = replace(PRODUCTS[pid], size_bytes=len(content))
            path = self.dem_dir / product.filename
            path.write_bytes(content)
            record = {
                "productId": pid,
                "sourceUrl": product.url,
                "sha256": hashlib.sha256(content).hexdigest(),
                "sizeBytes": len(content),
                "resolutionM": product.resolution_m,
                "role": product.role,
                "retrievedAtUtc": "2026-11-14T00:00:00Z",
                "mtimeNs": path.stat().st_mtime_ns,
            }
            sidecar_path(path).write_text(json.dumps(record), encoding="utf-8")
            resolution = product.resolution_m
            FakeDem.grids[pid] = Grid(
                np.full((64, 64), 100.0), x - 32 * resolution, y + 32 * resolution, resolution
            )
        for target, value in (
            ("lunarwindow.terrain.custom.PRODUCTS", self.products),
            ("lunarwindow.terrain.custom.DemSource", FakeDem),
        ):
            controller = patch(target, value)
            controller.start()
            self.addCleanup(controller.stop)
        params_patch = patch(
            "lunarwindow.terrain.custom.default_parameters",
            side_effect=lambda **kwargs: default_parameters(
                **(kwargs | {"maxRangeKm": 0.1, "nearFieldKm": 0.05, "raysPerDegree": 1})
            ),
        )
        params_patch.start()
        self.addCleanup(params_patch.stop)

    def generate(self, **changes):
        values = {
            "latitude_deg": LAT,
            "longitude_deg": LON,
            "observer_height_m": 2.0,
            "surface_elevation_m": None,
            "dem_directory": self.dem_dir,
            "cache_directory": self.cache_dir,
            "timeout_seconds": 10.0,
        }
        return custom.generate_custom_terrain(**(values | changes))

    def cache_files(self):
        return list(self.cache_dir.glob("*.json"))

    def test_real_ray_caster_produces_matching_mask_and_exact_requested_observer(self):
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("lunarwindow.terrain.custom.compute_horizon", wraps=compute_horizon) as engine,
        ):
            result = self.generate(surface_elevation_m=100.0)
        self.assertEqual(engine.call_count, 1)
        self.assertTrue(engine.call_args.kwargs["require_complete"])
        self.assertEqual(result.profile.horizon, result.mask.horizon)
        self.assertEqual(result.mask.observer.lat, LAT)
        self.assertEqual(result.mask.observer.lon, LON)
        self.assertEqual(result.mask.observer.surfaceElevationM, 100)
        self.assertEqual(result.mask.observer.mastHeightM, 2)
        self.assertEqual(result.mask.observer.altitudeKm, 0.102)
        location = CustomLocation(latitudeDeg=LAT, longitudeDeg=LON, observerHeightM=2)
        self.assertEqual(result.profile.siteId, observer_site_id(location, 0.102))
        self.assertEqual(result.profile_sha256, canonical_model_sha256(result.profile))
        self.assertEqual(result.mask_sha256, canonical_model_sha256(result.mask))
        self.assertEqual(result.profile.quality.missingSampleFraction, 0)
        self.assertEqual(result.profile.quality.truncatedAzimuths, [])
        self.assertTrue(all(point.el < 0 for point in result.mask.horizon))
        self.assertEqual(result.mask.referenceFrame.name, "MOON_ME")
        self.assertIn("no frame transformation", result.mask.referenceFrame.realization)
        self.assertIn("variable step", result.mask.provenance.algorithm.name)

    def test_cache_hit_rechecks_sources_and_returns_identical_created_at_and_hashes(self):
        first = self.generate()
        metadata = {p.name: p.read_bytes() for p in self.dem_dir.iterdir()}
        with patch(
            "lunarwindow.terrain.custom.compute_horizon", side_effect=AssertionError("Cache")
        ):
            second = self.generate()
        self.assertEqual(first, second)
        self.assertEqual(metadata, {p.name: p.read_bytes() for p in self.dem_dir.iterdir()})
        # Even replacing the sidecar's timestamp with its current value cannot skip hashing.
        path = self.dem_dir / PRODUCTS[NEAR_FIELD].filename
        content = path.read_bytes()
        path.write_bytes(b"X" + content[1:])
        record = json.loads(sidecar_path(path).read_bytes())
        record["mtimeNs"] = path.stat().st_mtime_ns
        sidecar_path(path).write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(custom.CustomTerrainDataError, "SHA-256"):
            self.generate()

    def test_precise_nearby_coordinates_and_height_have_distinct_cache_identities(self):
        first = self.generate()
        nearby = self.generate(latitude_deg=LAT + 1e-8)
        higher = self.generate(observer_height_m=3)
        self.assertNotEqual(first.profile.siteId, nearby.profile.siteId)
        self.assertNotEqual(first.profile.siteId, higher.profile.siteId)
        self.assertNotEqual(first.profile.horizon, higher.profile.horizon)
        self.assertEqual(len(self.cache_files()), 3)

    def test_generated_cache_tampering_is_rejected_without_regeneration(self):
        self.generate()
        path = self.cache_files()[0]
        payload = json.loads(path.read_bytes())
        payload["profile"]["horizon"][0]["el"] += 0.1
        path.write_text(json.dumps(payload), encoding="utf-8")
        with (
            patch(
                "lunarwindow.terrain.custom.compute_horizon",
                side_effect=AssertionError("No repair"),
            ),
            self.assertRaises(custom.CustomTerrainDataError),
        ):
            self.generate()

    def test_unavailable_or_unverified_sources_fail_explicitly(self):
        path = self.dem_dir / PRODUCTS[NEAR_FIELD].filename
        sidecar = sidecar_path(path)
        original = sidecar.read_bytes()
        for damage in ("missing", "url", "hash", "size", "resolution"):
            sidecar.write_bytes(original)
            if damage == "missing":
                sidecar.unlink()
            else:
                record = json.loads(original)
                if damage == "url":
                    record["sourceUrl"] = "https://example.invalid/unreviewed.tif"
                elif damage == "hash":
                    record["sha256"] = "0" * 64
                elif damage == "size":
                    record["sizeBytes"] += 1
                else:
                    record["resolutionM"] = 5
                sidecar.write_text(json.dumps(record), encoding="utf-8")
            with self.subTest(damage=damage), self.assertRaises(custom.CustomTerrainDataError):
                self.generate()

    def test_out_of_region_invalid_ground_and_holes_never_fall_back_to_flat(self):
        with patch(
            "lunarwindow.terrain.custom._source_record", side_effect=AssertionError("No I/O")
        ):
            with self.assertRaises(custom.CustomTerrainCoverageError):
                self.generate(latitude_deg=0)
        with self.assertRaisesRegex(custom.CustomTerrainCoverageError, "surfaceElevationM"):
            self.generate(surface_elevation_m=101)
        # Both synthetic DEM tiers contain an uncovered east-facing region.
        for pid, grid in FakeDem.grids.items():
            data = grid.data.copy()
            data[:, 33:] = np.nan
            FakeDem.grids[pid] = Grid(data, grid.left, grid.top, grid.resolution_m)
        with self.assertRaisesRegex(custom.CustomTerrainCoverageError, "incomplete DEM coverage"):
            self.generate()
        self.assertEqual(self.cache_files(), [])

    def test_deadline_is_cooperative_and_disk_cache_is_bounded(self):
        with self.assertRaises(custom.CustomTerrainTimeout):
            self.generate(timeout_seconds=0)
        first = self.generate(max_cache_entries=1)
        second = self.generate(observer_height_m=3, max_cache_entries=1)
        self.assertNotEqual(first.mask_sha256, second.mask_sha256)
        self.assertEqual(len(self.cache_files()), 1)
        # Oversized values may be evaluated but are never retained in the cache.
        uncached = self.root / "uncached"
        self.generate(cache_directory=uncached, max_cache_bytes=10)
        self.assertEqual(list(uncached.glob("*.json")), [])

    def test_ray_caster_invokes_deadline_callback_without_altering_legacy_signature(self):
        def stop():
            raise custom.CustomTerrainTimeout("Test deadline")

        with self.assertRaises(custom.CustomTerrainTimeout):
            compute_horizon(None, None, None, check_callback=stop)

    def test_reduced_limits_are_enforced_on_warm_cache_hits_without_recomputation(self):
        self.generate()
        self.generate(observer_height_m=3)
        self.generate(observer_height_m=4)
        self.assertEqual(len(self.cache_files()), 3)
        with patch("lunarwindow.terrain.custom.compute_horizon", side_effect=AssertionError("Hit")):
            self.generate(max_cache_entries=1)
        self.assertEqual(len(self.cache_files()), 1)
        self.generate(observer_height_m=3)
        self.generate(observer_height_m=4)
        byte_cap = max(path.stat().st_size for path in self.cache_files()) + 1
        with patch("lunarwindow.terrain.custom.compute_horizon", side_effect=AssertionError("Hit")):
            self.generate(max_cache_entries=10, max_cache_bytes=byte_cap)
        self.assertEqual(len(self.cache_files()), 1)
        self.assertLessEqual(sum(path.stat().st_size for path in self.cache_files()), byte_cap)

    def test_symlink_cache_lock_is_rejected_before_opening_its_target(self):
        self.cache_dir.mkdir()
        target = self.root / "outside-lock-target"
        target.write_text("Preserve this file", encoding="utf-8")
        try:
            (self.cache_dir / ".custom-terrain.lock").symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation requires privileges on this platform.")
        with self.assertRaisesRegex(custom.CustomTerrainDataError, "lock must not be a symlink"):
            self.generate()
        self.assertEqual(target.read_text(encoding="utf-8"), "Preserve this file")
