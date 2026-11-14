"""Terrain API contracts and the boundary before runtime engine integration."""

import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from lunarwindow.api.app import create_app, get_reference_directory
from lunarwindow.api.reference_models import ReferenceEvaluation, ReferenceEvaluationRequest
from lunarwindow.api.terrain_models import (
    ReferenceEvaluationContract,
    ReferenceEvaluationRequestContract,
    TerrainCompatibilityProvenance,
    TerrainReferenceEvaluation,
    TerrainReferenceEvaluationRequest,
)
from lunarwindow.ephemeris.models import TimeRange
from lunarwindow.reference import load_reference_dataset, select_reference_dataset
from lunarwindow.terrain import check_terrain_compatibility, load_terrain_mask
from lunarwindow.visibility import calculate_visibility

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
MASK_SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"


class TerrainEvaluationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mask = load_terrain_mask(
            REFERENCE / "terrain-masks/lola-site01-reference-mast-0m.json",
            expected_sha256=MASK_SHA256,
        )
        archive = load_reference_dataset(REFERENCE / "validation-30d", mask.siteId)
        dataset = select_reference_dataset(archive, end_utc="2026-11-14T02:00:00Z")
        period = TimeRange("2026-11-14T00:00:00Z", "2026-11-14T02:00:00Z", 60)
        # Prepare coherent test data offline; the API provider is not wired to terrain.
        visibility = calculate_visibility(dataset["series"], mask.horizon, period)
        assessment = check_terrain_compatibility(mask, dataset, allow_mean_earth_approximation=True)
        cls.fixture = {
            "schemaVersion": "lunarwindow.reference-evaluation.v2",
            "horizonMode": "terrain",
            "maskId": mask.maskId,
            "allowMeanEarthApproximation": True,
            **{
                key: dataset[key]
                for key in ("siteId", "site", "lat", "lon", "altitudeKm", "coordinateSource")
            },
            "horizon": [point.model_dump() for point in mask.horizon],
            **visibility.model_dump(),
            "provenance": {
                "ephemeris": dataset["provenance"],
                "archive": {
                    "startUtc": archive["provenance"]["startUtc"],
                    "endUtc": archive["provenance"]["endUtc"],
                    "stepMinutes": 60,
                    "sampleCount": 720,
                },
                "terrain": {
                    "artifactSha256": MASK_SHA256,
                    "mask": mask.model_dump(),
                    "compatibility": TerrainCompatibilityProvenance.from_assessment(
                        assessment
                    ).model_dump(),
                },
            },
        }

    def setUp(self):
        self.payload = copy.deepcopy(self.fixture)
        source = self.payload["provenance"]["ephemeris"]
        self.request = {
            "siteId": self.payload["siteId"],
            "horizonMode": "terrain",
            "maskId": self.payload["maskId"],
            "startUtc": source["startUtc"],
            "endUtc": source["endUtc"],
        }

    def test_request_defaults_to_strict_and_requires_a_mask_identifier(self):
        request = TerrainReferenceEvaluationRequest.model_validate(self.request)
        self.assertFalse(request.allowMeanEarthApproximation)
        self.assertEqual(request.stepMinutes, 60)
        self.assertEqual(request.visibilityRule, "any-disc")
        self.assertTrue(
            TerrainReferenceEvaluationRequest.model_validate(
                self.request | {"allowMeanEarthApproximation": True}
            ).allowMeanEarthApproximation
        )
        for changes in (
            {"maskId": "../mask.json"},
            {"horizonMode": "geometric"},
            {"allowMeanEarthApproximation": "true"},
            {"allowMeanEarthApproximation": 1},
            {"maskPath": "/tmp/mask.json"},
            {"expectedSha256": MASK_SHA256},
            {"endUtc": self.request["startUtc"]},
            {"asOfUtc": self.request["endUtc"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                TerrainReferenceEvaluationRequest.model_validate(self.request | changes)
        del self.request["maskId"]
        with self.assertRaises(ValidationError):
            TerrainReferenceEvaluationRequest.model_validate(self.request)

    def test_request_union_and_json_schema_discriminate_horizon_modes(self):
        adapter = TypeAdapter(ReferenceEvaluationRequestContract)
        self.assertIsInstance(
            adapter.validate_python(self.request), TerrainReferenceEvaluationRequest
        )
        geometric = {key: value for key, value in self.request.items() if key != "maskId"}
        geometric["horizonMode"] = "geometric"
        self.assertIsInstance(adapter.validate_python(geometric), ReferenceEvaluationRequest)
        schema = adapter.json_schema()
        self.assertEqual(schema["discriminator"]["propertyName"], "horizonMode")
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(self.request)
        for invalid in (
            self.request | {"horizonMode": "unknown"},
            geometric | {"maskId": self.request["maskId"]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                adapter.validate_python(invalid)

    def test_response_round_trip_preserves_mask_checksum_and_all_source_evidence(self):
        before = copy.deepcopy(self.payload)
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch(
                "lunarwindow.visibility.engine.calculate_visibility",
                side_effect=AssertionError("No engine during contract validation"),
            ),
        ):
            response = TerrainReferenceEvaluation.model_validate(self.payload)
        self.assertEqual(response.dataMode, "reference")
        self.assertEqual(response.schemaVersion, "lunarwindow.reference-evaluation.v2")
        self.assertEqual(response.provenance.terrain.artifactSha256, MASK_SHA256)
        self.assertEqual(
            response.provenance.terrain.mask.model_dump(), before["provenance"]["terrain"]["mask"]
        )
        self.assertEqual(response.provenance.ephemeris, before["provenance"]["ephemeris"])
        self.assertEqual(response.provenance.terrain.compatibility.frameStatus, "approximate")
        self.assertFalse(response.provenance.terrain.compatibility.transformationApplied)
        self.assertLess(min(point.el for point in response.horizon), 0)
        self.assertIn("Near-field exclusions", response.provenance.warning)
        self.assertEqual(self.payload, before)
        self.assertEqual(
            TerrainReferenceEvaluation.model_validate_json(response.model_dump_json()), response
        )
        schema = TerrainReferenceEvaluation.model_json_schema()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(response.model_dump())
        self.assertIsInstance(
            TypeAdapter(ReferenceEvaluationContract).validate_python(self.payload),
            TerrainReferenceEvaluation,
        )

    def test_response_requires_terrain_labels_and_explicit_boolean_acceptance(self):
        for changes in (
            {"schemaVersion": "lunarwindow.reference-evaluation.v1"},
            {"horizonMode": "geometric"},
            {"dataMode": "synthetic"},
            {"allowMeanEarthApproximation": False},
            {"allowMeanEarthApproximation": 1},
            {"maskId": "another-mask"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                TerrainReferenceEvaluation.model_validate(self.payload | changes)
        del self.payload["allowMeanEarthApproximation"]
        with self.assertRaises(ValidationError):
            TerrainReferenceEvaluation.model_validate(self.payload)

    def test_provenance_checksum_and_required_mask_metadata_cannot_be_omitted(self):
        for damage in ("terrain", "mask", "checksum", "bad-checksum", "sources", "frame", "report"):
            payload = copy.deepcopy(self.payload)
            terrain = payload["provenance"]["terrain"]
            if damage == "terrain":
                del payload["provenance"]["terrain"]
            elif damage == "mask":
                del terrain["mask"]
            elif damage == "checksum":
                del terrain["artifactSha256"]
            elif damage == "bad-checksum":
                terrain["artifactSha256"] = "invalid"
            elif damage == "sources":
                terrain["mask"]["provenance"]["sources"] = []
            elif damage == "frame":
                del terrain["mask"]["referenceFrame"]
            else:
                del terrain["compatibility"]
            with self.subTest(damage=damage), self.assertRaises(ValidationError):
                TerrainReferenceEvaluation.model_validate(payload)

    def test_mask_and_sample_horizons_must_match_the_provenance_profile(self):
        for damage in ("flat", "order", "sample", "observer"):
            payload = copy.deepcopy(self.payload)
            if damage == "flat":
                payload["horizon"] = [{"az": az, "el": 0.0} for az in range(360)]
            elif damage == "order":
                payload["horizon"].reverse()
            elif damage == "sample":
                payload["series"][0]["sunHorizonEl"] += 0.01
            else:
                payload["provenance"]["terrain"]["mask"]["observer"]["mastHeightM"] = 2.0
            with self.subTest(damage=damage), self.assertRaises(ValidationError):
                TerrainReferenceEvaluation.model_validate(payload)

    def test_frame_assessment_cannot_claim_exactness_or_hide_its_limitation(self):
        for changes in (
            {"frameStatus": "exact"},
            {"framePolicy": "strict"},
            {"transformationApplied": True},
            {"transformationApplied": 0},
            {"ephemerisDynamicalSource": "DE440"},
            {"limitation": "No limitations"},
            {"references": ["https://example.invalid/a", "https://example.invalid/b"]},
            {"maskId": "another-mask"},
        ):
            payload = copy.deepcopy(self.payload)
            payload["provenance"]["terrain"]["compatibility"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                TerrainReferenceEvaluation.model_validate(payload)

    def test_shared_archive_and_calculation_consistency_checks_apply_to_terrain(self):
        for damage in ("archive-count", "step", "duration", "time", "nasa-evidence"):
            payload = copy.deepcopy(self.payload)
            if damage == "archive-count":
                payload["provenance"]["archive"]["sampleCount"] = 1
            elif damage == "step":
                payload["calculation"]["stepMinutes"] = 120
            elif damage == "duration":
                payload["metrics"]["evaluatedHrs"] = 24
            elif damage == "time":
                payload["series"][1]["t"] = payload["series"][0]["t"]
            else:
                del payload["provenance"]["ephemeris"]["requests"][0]["responseSha256"]
            with self.subTest(damage=damage), self.assertRaises(ValidationError):
                TerrainReferenceEvaluation.model_validate(payload)

    def test_runtime_remains_geometric_until_the_provider_is_connected(self):
        app = create_app()
        app.dependency_overrides[get_reference_directory] = lambda: REFERENCE / "validation-30d"
        with TestClient(app) as client:
            with patch(
                "lunarwindow.api.app.evaluate_reference", side_effect=AssertionError("No provider")
            ):
                response = client.post(
                    "/api/reference/evaluations",
                    json=self.request | {"allowMeanEarthApproximation": True},
                )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"]["code"], "validation_error")
            geometric = {key: value for key, value in self.request.items() if key != "maskId"}
            geometric["horizonMode"] = "geometric"
            response = client.post("/api/reference/evaluations", json=geometric)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["schemaVersion"], "lunarwindow.reference-evaluation.v1")
            self.assertIsInstance(
                TypeAdapter(ReferenceEvaluationContract).validate_python(data), ReferenceEvaluation
            )
            self.assertNotIn("terrain", data["provenance"])
            schemas = client.get("/openapi.json").json()["components"]["schemas"]
            self.assertNotIn("TerrainReferenceEvaluationRequest", schemas)
