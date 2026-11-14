"""Persisted API hits, live misses, validation order, and fail-closed configuration."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from lunarwindow.api.app import (
    create_app,
    get_precomputed_directory,
    get_reference_directory,
    get_terrain_directory,
)
from lunarwindow.api.reference_cache_key import (
    ReferenceEvaluationCacheKey,
    build_reference_evaluation_cache_key,
)
from lunarwindow.api.reference_provider import evaluate_reference
from lunarwindow.api.terrain_models import ReferenceEvaluationRequestContract
from lunarwindow.precompute import PrecomputeJob, generate_bundle
from lunarwindow.reference import load_verified_reference_dataset
from lunarwindow.terrain.registry import load_reviewed_mask
from lunarwindow.visibility import calculate_visibility

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
REQUEST = {
    "siteId": "lola-site01-reference",
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-15T00:00:00Z",
}
MASK_ID = "lola-site01-reference-mast-0m"
TERRAIN = REQUEST | {
    "horizonMode": "terrain",
    "maskId": MASK_ID,
    "allowMeanEarthApproximation": True,
}
ENDPOINT = "/api/reference/evaluations"
ENGINE = "lunarwindow.api.reference_provider.calculate_visibility"
LOOKUP = "lunarwindow.precompute.loader.load_precomputed_evaluation"


class PrecomputedReferenceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.fixture = Path(temporary.name) / "bundle"
        verified = load_verified_reference_dataset(REFERENCE / "validation-30d", REQUEST["siteId"])
        mask = load_reviewed_mask(REFERENCE / "terrain-masks", MASK_ID)
        jobs = []
        for request in (REQUEST, TERRAIN):
            key = build_reference_evaluation_cache_key(
                TypeAdapter(ReferenceEvaluationRequestContract).validate_python(request),
                ephemeris_sha256=verified.artifact_sha256,
                terrain_mask_sha256=mask.artifact_sha256
                if request["horizonMode"] == "terrain"
                else None,
            )
            jobs.append(PrecomputeJob(evaluation=key, status="pending"))
        cls.manifest = generate_bundle(
            jobs,
            run_id="api-precomputed-test",
            reference_directory=REFERENCE / "validation-30d",
            output_directory=cls.fixture,
        )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = Path(shutil.copytree(self.fixture, self.root / "bundle with spaces"))
        self.app = create_app()
        self.set_sources(REFERENCE)
        self.app.dependency_overrides[get_precomputed_directory] = lambda: self.bundle
        self.cache = self.app.state.reference_evaluation_cache
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def set_sources(self, root):
        self.app.dependency_overrides[get_reference_directory] = lambda: root / "validation-30d"
        self.app.dependency_overrides[get_terrain_directory] = lambda: root / "terrain-masks"

    def copy_sources(self):
        root = self.root / "sources"
        for name in ("validation-30d", "terrain-masks"):
            shutil.copytree(REFERENCE / name, root / name)
        self.set_sources(root)
        return root

    def post_ok(self, request=REQUEST):
        response = self.client.post(ENDPOINT, json=request)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_unavailable(self, response):
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json()["error"]["message"],
            "Reference data is unavailable or failed validation.",
        )
        self.assertNotIn("series", response.json())
        self.assertNotIn(str(self.root), response.text)

    def test_exact_geometric_and_terrain_matches_preserve_saved_response_and_provenance(self):
        with (
            patch(ENGINE, side_effect=AssertionError("No calculation for saved matches")),
            patch.object(
                self.cache, "get", side_effect=AssertionError("Saved results take priority")
            ),
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No NASA")),
            patch("lunarwindow.terrain.download.urlopen", side_effect=AssertionError("No DEM")),
        ):
            for request, job in zip((REQUEST, TERRAIN), self.manifest.jobs):
                expected = json.loads((self.bundle / job.output.filename).read_bytes())
                self.assertEqual(self.post_ok(request), expected)
                self.assertEqual(
                    self.post_ok(
                        request
                        | {
                            "startUtc": "2026-11-14T00:00Z",
                            "endUtc": "2026-11-15T00:00Z",
                            "stepMinutes": 60,
                            "visibilityRule": "any-disc",
                            "asOfUtc": None,
                        }
                    ),
                    expected,
                )
        self.assertEqual(self.cache.info().entry_count, 0)

    def test_verified_absent_keys_calculate_then_use_memory_cache(self):
        for request in (
            REQUEST | {"visibilityRule": "body-center"},
            REQUEST | {"endUtc": "2026-11-14T06:30:00Z", "stepMinutes": 120},
            TERRAIN | {"asOfUtc": "2026-11-14T01:00:00Z"},
            REQUEST | {"siteId": "lola-site23-reference"},
        ):
            expected = evaluate_reference(
                TypeAdapter(ReferenceEvaluationRequestContract).validate_python(request),
                REFERENCE / "validation-30d",
                REFERENCE / "terrain-masks",
            ).model_dump(mode="json")
            with self.subTest(request=request), patch(ENGINE, wraps=calculate_visibility) as engine:
                self.assertEqual(self.post_ok(request), expected)
                self.assertEqual(self.post_ok(request), expected)
                self.assertEqual(engine.call_count, 1)

    def test_corrupt_configured_bundle_cannot_be_hidden_by_a_warm_memory_cache(self):
        request = REQUEST | {"visibilityRule": "full-disc"}
        self.post_ok(request)
        self.assertEqual(self.cache.info().entry_count, 1)
        (self.bundle / self.manifest.jobs[1].output.filename).write_bytes(b"{}")
        with (
            patch(ENGINE, side_effect=AssertionError("No fallback on invalid bundle")),
            patch.object(self.cache, "get", side_effect=AssertionError("No memory lookup")),
        ):
            self.assert_unavailable(self.client.post(ENDPOINT, json=request))

    def test_request_selection_policy_and_unknown_ids_fail_before_persisted_lookup(self):
        self.app.dependency_overrides[get_precomputed_directory] = lambda: self.root / "missing"
        with (
            patch(LOOKUP, side_effect=AssertionError("No persisted lookup")),
            patch(ENGINE, side_effect=AssertionError("No calculation")),
        ):
            for changes, status in (
                ({"stepMinutes": 90}, 422),
                ({"startUtc": "2026-11-14T00:30:00Z"}, 422),
                ({"endUtc": "2026-12-15T00:00:00Z"}, 422),
                ({"allowMeanEarthApproximation": False}, 422),
                ({"siteId": "lola-site04-reference"}, 422),
                ({"siteId": "unknown-site"}, 404),
                ({"maskId": "unknown-mask"}, 404),
            ):
                with self.subTest(changes=changes):
                    response = self.client.post(ENDPOINT, json=TERRAIN | changes)
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertNotIn("series", response.json())

    def test_invalid_current_sources_fail_before_lookup_even_after_a_saved_hit(self):
        root = self.copy_sources()
        self.post_ok(TERRAIN)
        (root / "validation-30d" / f"{REQUEST['siteId']}.json").write_bytes(b"{}")
        with patch(LOOKUP, side_effect=AssertionError("No persisted lookup")):
            self.assert_unavailable(self.client.post(ENDPOINT, json=TERRAIN))

    def test_missing_incomplete_or_unsupported_configured_bundles_are_503(self):
        for index, damage in enumerate(
            (
                "missing-directory",
                "missing-manifest",
                "missing-output",
                "incomplete",
                "unsupported-model",
            )
        ):
            bundle = self.root / f"bad-{index}"
            if damage != "missing-directory":
                shutil.copytree(self.fixture, bundle)
                path = bundle / "manifest.json"
                manifest = json.loads(path.read_bytes())
                if damage == "missing-manifest":
                    path.unlink()
                elif damage == "missing-output":
                    (bundle / manifest["jobs"][1]["output"]["filename"]).unlink()
                elif damage == "incomplete":
                    manifest.update(status="incomplete", completedAtUtc=None)
                    manifest["jobs"][1].update(status="pending", output=None)
                    path.write_text(json.dumps(manifest), encoding="utf-8")
                else:
                    job = manifest["jobs"][1]
                    key = ReferenceEvaluationCacheKey.model_validate(
                        job["evaluation"]
                        | {"calculationModelVersion": "lunarwindow.visibility.future"}
                    )
                    old = bundle / job["output"]["filename"]
                    job["evaluation"] = key.model_dump()
                    job["output"]["filename"] = f"{key.digest}.json"
                    old.rename(bundle / job["output"]["filename"])
                    path.write_text(json.dumps(manifest), encoding="utf-8")
            self.app.dependency_overrides[get_precomputed_directory] = lambda: bundle
            with (
                self.subTest(damage=damage),
                patch(ENGINE, side_effect=AssertionError("No fallback")),
            ):
                self.assert_unavailable(self.client.post(ENDPOINT, json=REQUEST))

    def test_valid_source_revision_invalidates_a_stale_bundle_instead_of_becoming_a_miss(self):
        root = self.copy_sources()
        path = root / "validation-30d" / f"{REQUEST['siteId']}.json"
        source = json.loads(path.read_bytes())
        source["coordinateSource"] += " Updated test metadata."
        path.write_text(json.dumps(source), encoding="utf-8")
        manifest_path = path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        item = next(item for item in manifest["datasets"] if item["siteId"] == REQUEST["siteId"])
        item["jsonSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        load_verified_reference_dataset(path.parent, REQUEST["siteId"])
        with patch(ENGINE, side_effect=AssertionError("No fallback from stale bundle")):
            self.assert_unavailable(self.client.post(ENDPOINT, json=REQUEST))

    def test_server_environment_enables_lookup_and_blank_disables_it(self):
        self.app.dependency_overrides.pop(get_precomputed_directory)
        with patch.dict(os.environ, {"LUNARWINDOW_PRECOMPUTED_DIR": str(self.bundle)}):
            with patch(ENGINE, side_effect=AssertionError("Use persisted result")):
                self.post_ok()
        for value in ("", "   "):
            with patch.dict(os.environ, {"LUNARWINDOW_PRECOMPUTED_DIR": value}):
                self.assertIsNone(get_precomputed_directory())
                self.cache.clear()
                with (
                    patch(LOOKUP, side_effect=AssertionError("Disabled lookup")),
                    patch(ENGINE, wraps=calculate_visibility) as engine,
                ):
                    self.post_ok()
                self.assertEqual(engine.call_count, 1)

    def test_disabling_lookup_preserves_live_evaluation_when_bundle_is_invalid(self):
        self.post_ok()
        (self.bundle / "manifest.json").write_bytes(b"invalid")
        self.app.dependency_overrides[get_precomputed_directory] = lambda: None
        with (
            patch(LOOKUP, side_effect=AssertionError("Disabled lookup")),
            patch(ENGINE, wraps=calculate_visibility) as engine,
        ):
            self.post_ok()
        self.assertEqual(engine.call_count, 1)

    def test_enabling_lookup_takes_priority_over_results_previously_in_memory(self):
        self.app.dependency_overrides[get_precomputed_directory] = lambda: None
        expected = self.post_ok()
        self.assertEqual(self.cache.info().entry_count, 1)
        self.app.dependency_overrides[get_precomputed_directory] = lambda: self.bundle
        with (
            patch.object(self.cache, "get", side_effect=AssertionError("Use saved result first")),
            patch(ENGINE, side_effect=AssertionError("No calculation")),
        ):
            self.assertEqual(self.post_ok(), expected)

    def test_api_returns_the_checked_response_snapshot_without_rereading_output(self):
        path = self.bundle / self.manifest.jobs[0].output.filename
        expected = json.loads(path.read_bytes())
        read_bytes = Path.read_bytes
        reads = 0

        def change_after_read(source):
            nonlocal reads
            content = read_bytes(source)
            if source == path:
                reads += 1
                path.write_bytes(b"changed after snapshot")
            return content

        with (
            patch.object(Path, "read_bytes", change_after_read),
            patch(ENGINE, side_effect=AssertionError("No calculation")),
        ):
            self.assertEqual(self.post_ok(), expected)
        self.assertEqual(reads, 1)
        self.assert_unavailable(self.client.post(ENDPOINT, json=REQUEST))

    def test_bundle_path_is_server_only_and_not_exposed_as_a_request_option(self):
        with patch(LOOKUP, side_effect=AssertionError("Invalid request")):
            response = self.client.post(
                ENDPOINT, json=REQUEST | {"precomputedDirectory": str(self.bundle)}
            )
        self.assertEqual(response.status_code, 422)
        operation = self.client.get("/openapi.json").json()["paths"][ENDPOINT]["post"]
        self.assertFalse(operation.get("parameters"))
        self.assertIn("503", operation["responses"])
