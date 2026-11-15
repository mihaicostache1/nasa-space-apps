"""Custom acquisition stays opt-in, bounded, exact-observer-aware, and non-queueing."""

import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event
from unittest.mock import patch

from lunarwindow.api.custom_runtime import (
    CustomBusyError,
    CustomDisabledError,
    CustomRuntime,
    CustomSettings,
    build_custom_cache_key,
)
from lunarwindow.api.snapshot_cache import SnapshotCache

REQUEST = {
    "location": {
        "latitudeDeg": -89.0,
        "longitudeDeg": 0.0,
        "observerHeightM": 0.0,
        "surfaceElevationM": 0.0,
    },
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-14T03:00:00Z",
}


class CustomSettingsTests(unittest.TestCase):
    def test_defaults_are_disabled_and_initialization_does_not_touch_the_filesystem(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(Path, "mkdir", side_effect=AssertionError("No filesystem writes")),
        ):
            runtime = CustomRuntime()
        settings = runtime.settings
        self.assertFalse(settings.enabled)
        self.assertFalse(settings.terrain_enabled)
        self.assertEqual(settings.max_concurrency, 1)
        self.assertEqual(settings.timeout_seconds, 30)
        self.assertEqual(settings.max_samples, 744)
        self.assertEqual(settings.max_archive_entries, 64)
        self.assertEqual(settings.max_archive_bytes, 64 * 1024 * 1024)
        self.assertEqual(settings.cache_max_entries, 16)
        self.assertEqual(settings.cache_max_bytes, 16 * 1024 * 1024)
        self.assertEqual(settings.archive_directory, Path("data/processed/custom-ephemeris"))
        self.assertEqual(settings.terrain_cache_directory, Path("data/processed/custom-terrain"))
        with self.assertRaises(FrozenInstanceError):
            settings.enabled = True
        with self.assertRaises(CustomDisabledError), runtime.admit():
            self.fail("Disabled acquisition must never run")

    def test_explicit_settings_and_server_paths_are_honored(self):
        environment = {
            "LUNARWINDOW_CUSTOM_ENABLED": "true",
            "LUNARWINDOW_CUSTOM_TERRAIN_ENABLED": "true",
            "LUNARWINDOW_CUSTOM_ARCHIVE_DIR": "/tmp/test-custom/ephemeris",
            "LUNARWINDOW_CUSTOM_DEM_DIR": "/tmp/test-dems",
            "LUNARWINDOW_CUSTOM_MAX_CONCURRENCY": "2",
            "LUNARWINDOW_CUSTOM_TIMEOUT_SECONDS": "12.5",
            "LUNARWINDOW_CUSTOM_MAX_SAMPLES": "48",
            "LUNARWINDOW_CUSTOM_ARCHIVE_MAX_ENTRIES": "8",
            "LUNARWINDOW_CUSTOM_ARCHIVE_MAX_BYTES": "1048576",
            "LUNARWINDOW_CUSTOM_CACHE_MAX_ENTRIES": "0",
            "LUNARWINDOW_CUSTOM_CACHE_MAX_BYTES": "2048",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = CustomSettings.from_env()
        self.assertTrue(settings.enabled)
        self.assertTrue(settings.terrain_enabled)
        self.assertEqual(settings.archive_directory, Path("/tmp/test-custom/ephemeris"))
        self.assertEqual(settings.terrain_cache_directory, Path("/tmp/test-custom/custom-terrain"))
        self.assertEqual(settings.dem_directory, Path("/tmp/test-dems"))
        self.assertEqual(settings.max_concurrency, 2)
        self.assertEqual(settings.timeout_seconds, 12.5)
        self.assertEqual(settings.max_samples, 48)
        self.assertEqual(settings.max_archive_entries, 8)
        self.assertEqual(settings.max_archive_bytes, 1048576)
        runtime = CustomRuntime(settings)
        self.assertFalse(runtime.cache.put("0" * 64, b"disabled cache"))
        with tempfile.TemporaryDirectory() as temporary:
            settings = CustomSettings(archive_directory=Path(temporary) / "archive")
            self.assertEqual(settings.terrain_cache_directory, Path(temporary) / "custom-terrain")

    def test_invalid_environment_values_fail_with_the_setting_name(self):
        invalid = {
            "LUNARWINDOW_CUSTOM_ENABLED": ("1", "yes", "", "on"),
            "LUNARWINDOW_CUSTOM_TERRAIN_ENABLED": ("1", "", "true"),
            "LUNARWINDOW_CUSTOM_MAX_CONCURRENCY": ("0", "5", "-1", "1.5", "true"),
            "LUNARWINDOW_CUSTOM_TIMEOUT_SECONDS": ("0", "121", "nan", "inf", "", "no"),
            "LUNARWINDOW_CUSTOM_MAX_SAMPLES": ("0", "745", "-1", ""),
            "LUNARWINDOW_CUSTOM_ARCHIVE_MAX_ENTRIES": ("0", "-1", ""),
            "LUNARWINDOW_CUSTOM_ARCHIVE_MAX_BYTES": ("0", "-1", ""),
            "LUNARWINDOW_CUSTOM_CACHE_MAX_ENTRIES": ("-1", "1.5", ""),
            "LUNARWINDOW_CUSTOM_CACHE_MAX_BYTES": ("-1", "false", ""),
            "LUNARWINDOW_CUSTOM_ARCHIVE_DIR": ("", "  ", "bad\x00path"),
            "LUNARWINDOW_CUSTOM_DEM_DIR": ("", "  ", "bad\x00path"),
            "LUNARWINDOW_CUSTOM_TERRAIN_CACHE_DIR": ("", "  ", "bad\x00path"),
        }
        for name, values in invalid.items():
            for value in values:
                # os.environ itself rejects NUL; test that path helper through a mock mapping.
                with (
                    self.subTest(name=name, value=value),
                    patch("lunarwindow.api.custom_runtime.os.environ", {name: value}),
                    self.assertRaisesRegex(ValueError, name),
                ):
                    CustomSettings.from_env()

    def test_direct_settings_also_validate_resource_limits(self):
        for field, values in {
            "enabled": (1, "true"),
            "max_concurrency": (0, 5, True, "1"),
            "timeout_seconds": (0, 121, float("nan"), True),
            "max_samples": (0, 745, True),
            "max_archive_entries": (0, -1, True),
            "max_archive_bytes": (0, -1, True),
            "cache_max_entries": (-1, True),
            "cache_max_bytes": (-1, True),
            "archive_directory": ("/tmp/archive", None),
            "dem_directory": ("/tmp/dem", None),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CustomSettings(**{field: value})


class CustomAdmissionTests(unittest.TestCase):
    def test_busy_requests_are_rejected_without_queuing_and_release_after_failure(self):
        runtime = CustomRuntime(CustomSettings(enabled=True))
        entered, release = Event(), Event()

        def hold():
            with runtime.admit():
                entered.set()
                self.assertTrue(release.wait(timeout=5))

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(hold)
            self.assertTrue(entered.wait(timeout=5))
            try:
                with self.assertRaises(CustomBusyError), runtime.admit():
                    self.fail("Busy admission must not queue")
            finally:
                release.set()
            pending.result(timeout=5)
        with self.assertRaisesRegex(RuntimeError, "test failure"), runtime.admit():
            raise RuntimeError("test failure")
        with runtime.admit():
            pass

    def test_configured_capacity_accepts_only_that_many_active_calls(self):
        runtime = CustomRuntime(CustomSettings(enabled=True, max_concurrency=2))
        with runtime.admit(), runtime.admit():
            with self.assertRaises(CustomBusyError), runtime.admit():
                self.fail("Exceeded configured capacity")
        with runtime.admit():
            pass


class CustomCacheTests(unittest.TestCase):
    def key(self, request=None, **options):
        return build_custom_cache_key(
            copy.deepcopy(REQUEST) if request is None else request,
            ephemeris_sha256=options.pop("ephemeris_sha256", "a" * 64),
            **options,
        )

    def test_default_and_canonical_equivalent_requests_share_a_key(self):
        request = copy.deepcopy(REQUEST)
        request.update(stepMinutes=60, visibilityRule="any-disc", asOfUtc=request["startUtc"])
        self.assertEqual(self.key(request), self.key())
        request["startUtc"] = "2026-11-14T00:00Z"
        self.assertEqual(self.key(request), self.key())
        request["location"]["longitudeDeg"] = -0.0
        self.assertEqual(self.key(request), self.key())

    def test_every_computation_input_and_source_identity_changes_the_key(self):
        base = self.key()
        for field, value in (
            ("latitudeDeg", -89.000000000001),
            ("longitudeDeg", 0.000000000001),
            ("observerHeightM", 2),
            ("surfaceElevationM", 0.001),
        ):
            request = copy.deepcopy(REQUEST)
            request["location"][field] = value
            with self.subTest(field=field):
                self.assertNotEqual(base, self.key(request))
        for field, value in (
            ("startUtc", "2026-11-14T01:00:00Z"),
            ("endUtc", "2026-11-14T04:00:00Z"),
            ("stepMinutes", 120),
            ("visibilityRule", "full-disc"),
            ("asOfUtc", "2026-11-14T01:00:00Z"),
        ):
            request = copy.deepcopy(REQUEST) | {field: value}
            with self.subTest(field=field):
                self.assertNotEqual(base, self.key(request))
        self.assertNotEqual(base, self.key(ephemeris_sha256="b" * 64))
        self.assertNotEqual(base, self.key(calculation_model_version="test.next-model"))
        request = copy.deepcopy(REQUEST) | {
            "horizonMode": "terrain",
            "allowMeanEarthApproximation": True,
        }
        terrain_key = self.key(request, terrain_sha256="c" * 64)
        self.assertNotEqual(base, terrain_key)
        self.assertNotEqual(terrain_key, self.key(request, terrain_sha256="d" * 64))
        request["allowMeanEarthApproximation"] = False
        self.assertNotEqual(terrain_key, self.key(request, terrain_sha256="c" * 64))

    def test_invalid_identity_inputs_are_not_usable_cache_keys(self):
        for options in (
            {"ephemeris_sha256": "bad"},
            {"terrain_sha256": "c" * 64},
            {"calculation_model_version": ""},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.key(**options)
        request = copy.deepcopy(REQUEST) | {"horizonMode": "terrain"}
        with self.assertRaises(ValueError):
            self.key(request)
        request = copy.deepcopy(REQUEST)
        request["location"]["latitudeDeg"] = True
        with self.assertRaises(ValueError):
            self.key(request)

    def test_shared_lru_enforces_entry_and_byte_limits_and_immutable_snapshots(self):
        runtime = CustomRuntime(CustomSettings(cache_max_entries=2, cache_max_bytes=6))
        cache = runtime.cache
        a, b, c = (str(index) * 64 for index in range(3))
        cache.put(a, b"aa")
        cache.put(b, b"bb")
        self.assertEqual(cache.get(a), b"aa")
        cache.put(c, b"ccc")
        self.assertIsNone(cache.get(b))
        self.assertEqual(cache.info().stored_bytes, 5)
        self.assertFalse(cache.put(a, b"too large"))
        self.assertEqual(cache.get(a), b"aa")
        for value in (bytearray(b"x"), memoryview(b"x"), "string", {}):
            with self.subTest(value=value), self.assertRaises(TypeError):
                cache.put(a, value)
        runtime.close()
        self.assertEqual(cache.info().entry_count, 0)
        self.assertEqual(cache.info().stored_bytes, 0)

    def test_payload_decoding_does_not_mutate_retained_result_and_digest_keys_are_bounded(self):
        cache = SnapshotCache(max_entries=1, max_bytes=100)
        key = "0" * 64
        content = json.dumps({"observer": {"lat": -89}}).encode()
        self.assertTrue(cache.put(key, content))
        decoded = json.loads(cache.get(key))
        decoded["observer"]["lat"] = 0
        self.assertEqual(json.loads(cache.get(key))["observer"]["lat"], -89)
        for value in ("", "x" * 64, "A" * 64, "0" * 65, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cache.put(value, b"not retained")
        self.assertEqual(cache.get(key), content)
