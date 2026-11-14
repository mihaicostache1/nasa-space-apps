"""HTTP integration of the reviewed mask, archived samples, and existing engine."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app, get_reference_directory, get_terrain_directory
from lunarwindow.api.terrain_models import TerrainReferenceEvaluation
from lunarwindow.ephemeris.models import TimeRange
from lunarwindow.reference import load_reference_dataset, select_reference_dataset
from lunarwindow.terrain import TerrainMask, load_terrain_mask
from lunarwindow.visibility import calculate_visibility

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
MASK_ID = "lola-site01-reference-mast-0m"
MASK_SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"
REQUEST = {
    "siteId": "lola-site01-reference",
    "horizonMode": "terrain",
    "maskId": MASK_ID,
    "allowMeanEarthApproximation": True,
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-12-14T00:00:00Z",
    "stepMinutes": 60,
}
ENDPOINT = "/api/reference/evaluations"


class TerrainEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = load_reference_dataset(REFERENCE / "validation-30d", REQUEST["siteId"])
        cls.mask_path = REFERENCE / "terrain-masks" / f"{MASK_ID}.json"
        cls.mask = load_terrain_mask(cls.mask_path, expected_sha256=MASK_SHA256)

    def setUp(self):
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: (
            REFERENCE / "validation-30d"
        )
        self.app.dependency_overrides[get_terrain_directory] = lambda: REFERENCE / "terrain-masks"
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def assert_error(self, request, status):
        with patch(
            "lunarwindow.api.reference_provider.calculate_visibility",
            side_effect=AssertionError("No calculation for rejected inputs"),
        ):
            response = self.client.post(ENDPOINT, json=request)
        self.assertEqual(response.status_code, status, response.text)
        self.assertIn("error", response.json())
        self.assertNotIn("series", response.json())
        return response

    def test_real_mask_and_ephemerides_reach_the_engine_with_complete_provenance(self):
        original = self.mask_path.read_bytes()
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch(
                "lunarwindow.api.demo.DemoProvider.evaluate", side_effect=AssertionError("No demo")
            ),
            patch(
                "lunarwindow.terrain.horizon.compute_horizon",
                side_effect=AssertionError("No DEM regeneration"),
            ),
        ):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200, response.text)
        actual = TerrainReferenceEvaluation.model_validate(response.json())
        expected = calculate_visibility(
            self.archive["series"],
            self.mask.horizon,
            TimeRange(REQUEST["startUtc"], REQUEST["endUtc"], 60),
        )
        self.assertEqual(actual.horizon, self.mask.horizon)
        self.assertEqual(actual.series, expected.series)
        self.assertEqual(actual.metrics, expected.metrics)
        self.assertEqual(actual.windows, expected.windows)
        self.assertEqual(actual.calculation, expected.calculation)
        self.assertEqual(actual.provenance.ephemeris, self.archive["provenance"])
        self.assertEqual(actual.provenance.archive.sampleCount, 720)
        self.assertEqual(actual.provenance.terrain.mask, self.mask)
        self.assertEqual(actual.provenance.terrain.artifactSha256, MASK_SHA256)
        self.assertEqual(actual.provenance.terrain.compatibility.frameStatus, "approximate")
        self.assertFalse(actual.provenance.terrain.compatibility.transformationApplied)
        self.assertEqual(self.mask_path.read_bytes(), original)

    def test_selected_grid_visibility_rule_and_countdown_are_forwarded(self):
        request = REQUEST | {
            "startUtc": "2026-11-15T01:00:00Z",
            "endUtc": "2026-11-15T06:30:00Z",
            "stepMinutes": 120,
            "visibilityRule": "full-disc",
            "asOfUtc": "2026-11-15T02:00:00Z",
        }
        selected = select_reference_dataset(
            self.archive,
            start_utc=request["startUtc"],
            end_utc=request["endUtc"],
            step_minutes=request["stepMinutes"],
        )
        expected = calculate_visibility(
            selected["series"],
            self.mask.horizon,
            TimeRange(request["startUtc"], request["endUtc"], 120),
            rule="full-disc",
            as_of_utc=request["asOfUtc"],
        )
        response = self.client.post(ENDPOINT, json=request)
        self.assertEqual(response.status_code, 200, response.text)
        actual = TerrainReferenceEvaluation.model_validate(response.json())
        self.assertEqual(actual.series, expected.series)
        self.assertEqual(actual.metrics, expected.metrics)
        self.assertEqual(actual.windows, expected.windows)
        self.assertEqual(actual.provenance.ephemeris, selected["provenance"])
        self.assertEqual(actual.provenance.archive.sampleCount, 720)
        self.assertEqual(actual.metrics.evaluatedHrs, 5.5)

    def test_frame_approximation_is_never_enabled_implicitly(self):
        for request in (
            {key: value for key, value in REQUEST.items() if key != "allowMeanEarthApproximation"},
            REQUEST | {"allowMeanEarthApproximation": False},
            REQUEST | {"allowMeanEarthApproximation": "true"},
            REQUEST | {"allowMeanEarthApproximation": 1},
        ):
            with self.subTest(request=request):
                response = self.assert_error(request, 422)
                self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_unknown_ids_and_incompatible_site_pairings_fail_without_a_fallback(self):
        for changes, status in (
            ({"maskId": "unknown-mask"}, 404),
            ({"siteId": "unknown-site"}, 404),
            ({"siteId": "lola-site04-reference"}, 422),
            ({"maskId": "../mask.json"}, 422),
        ):
            with self.subTest(changes=changes):
                self.assert_error(REQUEST | changes, status)

    def test_unavailable_and_corrupt_registered_masks_return_503_without_paths(self):
        for damage in ("missing", "invalid", "changed-with-updated-sidecar"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "masks"
                directory.mkdir()
                path = directory / self.mask_path.name
                if damage != "missing":
                    content = b"{}"
                    if damage == "changed-with-updated-sidecar":
                        payload = json.loads(self.mask_path.read_bytes())
                        payload["horizon"][0]["el"] += 0.01
                        content = json.dumps(payload).encode()
                    path.write_bytes(content)
                    path.with_suffix(".json.sha256").write_text(
                        f"{hashlib.sha256(content).hexdigest()}  {path.name}\n"
                    )
                self.app.dependency_overrides[get_terrain_directory] = lambda: directory
                response = self.assert_error(REQUEST, 503)
                self.assertEqual(
                    response.json()["error"]["message"],
                    "Reference data is unavailable or failed validation.",
                )
                self.assertNotIn(str(directory), response.text)

    def test_registration_rejects_inconsistent_artifact_identity(self):
        payload = self.mask.model_dump()
        payload["maskId"] = "another-mask"
        with patch(
            "lunarwindow.terrain.registry.load_terrain_mask",
            return_value=TerrainMask.model_validate(payload),
        ):
            self.assert_error(REQUEST, 503)

    def test_terrain_requests_keep_archive_selection_validation(self):
        for changes in (
            {"stepMinutes": 30},
            {"stepMinutes": 90},
            {"startUtc": "2026-11-14T00:30:00Z"},
            {"endUtc": "2026-12-14T00:01:00Z"},
            {"maskPath": "/tmp/unchecked.json"},
        ):
            with self.subTest(changes=changes):
                self.assert_error(REQUEST | changes, 422)

    def test_geometric_mode_does_not_depend_on_mask_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.app.dependency_overrides[get_terrain_directory] = lambda: (
                Path(temporary) / "absent"
            )
            request = {
                key: value
                for key, value in REQUEST.items()
                if key not in {"maskId", "allowMeanEarthApproximation"}
            } | {"horizonMode": "geometric", "endUtc": "2026-11-15T00:00:00Z"}
            with patch(
                "lunarwindow.api.reference_provider.load_reviewed_mask",
                side_effect=AssertionError("No mask access"),
            ):
                response = self.client.post(ENDPOINT, json=request)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["schemaVersion"], "lunarwindow.reference-evaluation.v1")
            self.assertNotIn("terrain", data["provenance"])
            self.assertTrue(all(point["el"] == 0 for point in data["horizon"]))
