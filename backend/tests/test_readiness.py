"""Data readiness, startup resource settings, and private failure diagnostics."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import (
    create_app,
    get_precomputed_directory,
    get_reference_directory,
    get_terrain_directory,
)

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
RELEASE = REFERENCE.parent / "releases/lunarwindow-demo-v1/bundle"


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: (
            REFERENCE / "validation-30d"
        )
        self.app.dependency_overrides[get_terrain_directory] = lambda: REFERENCE / "terrain-masks"
        self.app.dependency_overrides[get_precomputed_directory] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_ready_checks_catalog_and_optional_bundle_without_calculating(self):
        with patch(
            "lunarwindow.api.reference_provider.calculate_visibility",
            side_effect=AssertionError("No calculation"),
        ):
            response = self.client.get("/api/ready")
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["schemaVersion"], "lunarwindow.readiness.v1")
            self.assertEqual(data["status"], "ready")
            self.assertEqual(data["dataMode"], "reference")
            self.assertEqual(data["referenceSiteCount"], 3)
            self.assertEqual(data["terrainMaskCount"], 1)
            self.assertEqual(data["precomputed"], "disabled")
            self.assertEqual(data["precomputedJobCount"], 0)
            self.app.dependency_overrides[get_precomputed_directory] = lambda: RELEASE
            data = self.client.get("/api/ready").json()
            self.assertEqual(data["precomputed"], "verified")
            self.assertEqual(data["precomputedJobCount"], 4)
        schema = self.client.get("/openapi.json").json()["paths"]["/api/ready"]["get"]
        self.assertIn("503", schema["responses"])
        self.assertFalse(schema.get("parameters"))

    def test_bad_archive_mask_or_configured_bundle_is_unready_while_process_remains_healthy(self):
        for dependency in (
            get_reference_directory,
            get_terrain_directory,
            get_precomputed_directory,
        ):
            with (
                self.subTest(dependency=dependency.__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                previous = self.app.dependency_overrides[dependency]
                missing = Path(temporary) / "private-missing-data"
                self.app.dependency_overrides[dependency] = lambda: missing
                with self.assertLogs("uvicorn.error", level="WARNING") as logs:
                    response = self.client.get("/api/ready")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["message"],
                    "Reference data is unavailable or failed validation.",
                )
                self.assertNotIn(str(missing), response.text)
                self.assertIn("operation=readiness", "\n".join(logs.output))
                self.assertIn(str(missing), "\n".join(logs.output))
                self.assertEqual(self.client.get("/api/health").status_code, 200)
                self.app.dependency_overrides[dependency] = previous

    def test_readiness_rechecks_files_on_each_request(self):
        self.assertEqual(self.client.get("/api/ready").status_code, 200)
        self.app.dependency_overrides[get_precomputed_directory] = lambda: RELEASE
        with patch(
            "lunarwindow.precompute.verifier.verify_bundle",
            side_effect=ValueError("changed bundle"),
        ):
            with self.assertLogs("uvicorn.error", level="WARNING"):
                self.assertEqual(self.client.get("/api/ready").status_code, 503)

    def test_cache_settings_are_validated_at_startup_and_reported_by_readiness(self):
        with patch.dict(
            os.environ,
            {"LUNARWINDOW_CACHE_MAX_ENTRIES": "7", "LUNARWINDOW_CACHE_MAX_BYTES": "4096"},
        ):
            app = create_app()
        app.dependency_overrides.update(self.app.dependency_overrides)
        with TestClient(app) as client:
            data = client.get("/api/ready").json()
        self.assertEqual(data["cacheMaxEntries"], 7)
        self.assertEqual(data["cacheMaxBytes"], 4096)
        self.assertEqual(app.state.reference_evaluation_cache.info().max_bytes, 4096)
        with patch.dict(
            os.environ, {"LUNARWINDOW_CACHE_MAX_ENTRIES": "0", "LUNARWINDOW_CACHE_MAX_BYTES": "0"}
        ):
            self.assertEqual(create_app().state.reference_evaluation_cache.info().max_entries, 0)

    def test_invalid_cache_settings_fail_startup_with_the_setting_name(self):
        for name in ("LUNARWINDOW_CACHE_MAX_ENTRIES", "LUNARWINDOW_CACHE_MAX_BYTES"):
            for value in ("", "-1", "true", "1.5", "unlimited"):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                    with self.assertRaisesRegex(ValueError, name):
                        create_app()

    def test_artifact_errors_are_logged_without_exposing_paths_in_evaluation_response(self):
        self.app.dependency_overrides[get_precomputed_directory] = lambda: Path(
            "/private/example-missing-bundle"
        )
        with self.assertLogs("uvicorn.error", level="WARNING") as logs:
            response = self.client.post(
                "/api/reference/evaluations",
                json={
                    "siteId": "lola-site01-reference",
                    "horizonMode": "geometric",
                    "startUtc": "2026-11-14T00:00:00Z",
                    "endUtc": "2026-11-15T00:00:00Z",
                },
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("/private/example-missing-bundle", response.text)
        self.assertIn("operation=evaluation", "\n".join(logs.output))
        self.assertIn("siteId=lola-site01-reference", "\n".join(logs.output))
