"""Cached evaluations reuse calculations while preserving source/policy validation."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import (
    create_app,
    get_reference_cache,
    get_reference_directory,
    get_terrain_directory,
)
from lunarwindow.api.reference_cache import ReferenceEvaluationCache
from lunarwindow.api.reference_cache_key import build_reference_evaluation_cache_key
from lunarwindow.api.reference_models import ReferenceEvaluationRequest
from lunarwindow.api.reference_provider import evaluate_reference
from lunarwindow.reference import load_verified_reference_dataset
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.registry import load_reviewed_mask
from lunarwindow.visibility import calculate_visibility

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
MASK_ID = "lola-site01-reference-mast-0m"
REQUEST = {
    "siteId": "lola-site01-reference",
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-15T00:00:00Z",
}
TERRAIN = REQUEST | {
    "horizonMode": "terrain",
    "maskId": MASK_ID,
    "allowMeanEarthApproximation": True,
}
ENDPOINT = "/api/reference/evaluations"
ENGINE = "lunarwindow.api.reference_provider.calculate_visibility"


class ReferenceCacheApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.set_directories(REFERENCE)
        self.cache = self.app.state.reference_evaluation_cache
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def set_directories(self, root):
        self.app.dependency_overrides[get_reference_directory] = lambda: root / "validation-30d"
        self.app.dependency_overrides[get_terrain_directory] = lambda: root / "terrain-masks"

    def post_ok(self, payload=REQUEST):
        response = self.client.post(ENDPOINT, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def copy_sources(self, root):
        for name in ("validation-30d", "terrain-masks"):
            shutil.copytree(REFERENCE / name, root / name)
        self.set_directories(root)

    def test_geometric_and_terrain_hits_skip_calculation_but_reverify_sources(self):
        with (
            patch(ENGINE, wraps=calculate_visibility) as engine,
            patch(
                "lunarwindow.api.reference_provider.load_verified_reference_dataset",
                wraps=load_verified_reference_dataset,
            ) as ephemeris,
            patch(
                "lunarwindow.api.reference_provider.load_reviewed_mask", wraps=load_reviewed_mask
            ) as mask,
            patch(
                "lunarwindow.api.reference_provider.check_terrain_compatibility",
                wraps=check_terrain_compatibility,
            ) as compatibility,
        ):
            for request in (REQUEST, TERRAIN):
                first = self.post_ok(request)
                second = self.post_ok(request)
                self.assertEqual(second, first)
                self.assertEqual(second["horizonMode"], request["horizonMode"])
            self.assertEqual(engine.call_count, 2)
            self.assertEqual(ephemeris.call_count, 4)
            self.assertEqual(mask.call_count, 2)
            self.assertEqual(compatibility.call_count, 2)
        self.assertEqual(self.cache.info().entry_count, 2)

    def test_explicit_defaults_and_equivalent_utc_forms_hit_the_same_entry(self):
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            first = self.post_ok()
            second = self.post_ok(
                REQUEST
                | {
                    "startUtc": "2026-11-14T00:00Z",
                    "endUtc": "2026-11-15T00:00Z",
                    "asOfUtc": "2026-11-14T00:00Z",
                    "stepMinutes": 60,
                    "visibilityRule": "any-disc",
                }
            )
            third = self.post_ok(REQUEST | {"asOfUtc": None})
            self.assertEqual(first, second)
            self.assertEqual(first, third)
            self.assertEqual(engine.call_count, 1)

    def test_options_site_horizon_and_model_version_changes_miss(self):
        requests = [REQUEST, TERRAIN] + [
            REQUEST | change
            for change in (
                {"siteId": "lola-site23-reference"},
                {"startUtc": "2026-11-14T01:00:00Z"},
                {"endUtc": "2026-11-14T23:30:00Z"},
                {"stepMinutes": 120},
                {"visibilityRule": "body-center"},
                {"visibilityRule": "full-disc"},
                {"asOfUtc": "2026-11-14T01:00:00Z"},
            )
        ]
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            for count, request in enumerate(requests, 1):
                with self.subTest(request=request):
                    first = self.post_ok(request)
                    self.assertEqual(self.post_ok(request), first)
                    self.assertEqual(engine.call_count, count)
            with patch(
                "lunarwindow.api.reference_provider.VISIBILITY_MODEL_VERSION",
                "lunarwindow.visibility.v2",
            ):
                self.post_ok()
                self.post_ok()
                self.assertEqual(engine.call_count, len(requests) + 1)

    def test_verified_ephemeris_revision_changes_key_and_returned_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_sources(root)
            path = root / "validation-30d" / f"{REQUEST['siteId']}.json"
            manifest_path = path.parent / "manifest.json"
            original_bytes, original_manifest = path.read_bytes(), manifest_path.read_bytes()
            with patch(ENGINE, wraps=calculate_visibility) as engine:
                first = self.post_ok()
                updated = json.loads(original_bytes)
                updated["coordinateSource"] += " Updated test source description."
                path.write_text(json.dumps(updated), encoding="utf-8")
                manifest = json.loads(original_manifest)
                item = next(d for d in manifest["datasets"] if d["siteId"] == REQUEST["siteId"])
                item["jsonSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                second = self.post_ok()
                self.assertEqual(second["coordinateSource"], updated["coordinateSource"])
                self.assertNotEqual(second["coordinateSource"], first["coordinateSource"])
                self.assertEqual(self.post_ok(), second)
                self.assertEqual(engine.call_count, 2)
                path.write_bytes(original_bytes)
                manifest_path.write_bytes(original_manifest)
                self.assertEqual(self.post_ok(), first)
                self.assertEqual(engine.call_count, 2)

    def test_reviewed_mask_revision_changes_key_and_complete_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_sources(root)
            path = root / "terrain-masks" / f"{MASK_ID}.json"
            with patch(ENGINE, wraps=calculate_visibility) as engine:
                first = self.post_ok(TERRAIN)
                updated = json.loads(path.read_bytes())
                # Test-only reviewed revision; changing source metadata must also
                # invalidate a complete response, even with the same horizon.
                updated["provenance"]["sources"][0]["productVersion"] += "-test-revision"
                path.write_text(json.dumps(updated), encoding="utf-8")
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                with patch.dict(
                    "lunarwindow.terrain.registry._MASKS",
                    {MASK_ID: (REQUEST["siteId"], path.name, checksum)},
                ):
                    second = self.post_ok(TERRAIN)
                    provenance = second["provenance"]["terrain"]
                    self.assertEqual(provenance["artifactSha256"], checksum)
                    self.assertEqual(provenance["mask"]["provenance"], updated["provenance"])
                    self.assertNotEqual(provenance, first["provenance"]["terrain"])
                    self.assertEqual(self.post_ok(TERRAIN), second)
                    self.assertEqual(engine.call_count, 2)

    def test_corrupted_or_missing_sources_fail_before_lookup_even_with_a_warm_cache(self):
        for damage in ("json", "missing-json", "sibling-csv", "manifest", "mask", "missing-mask"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.copy_sources(root)
                self.post_ok(TERRAIN)
                before = self.cache.info()
                if damage in ("mask", "missing-mask"):
                    path = root / "terrain-masks" / f"{MASK_ID}.json"
                elif damage == "sibling-csv":
                    path = root / "validation-30d/lola-site04-reference.csv"
                elif damage == "manifest":
                    path = root / "validation-30d/manifest.json"
                else:
                    path = root / "validation-30d" / f"{REQUEST['siteId']}.json"
                if damage.startswith("missing"):
                    path.unlink()
                else:
                    path.write_bytes(b"{}")
                with (
                    patch.object(self.cache, "get", side_effect=AssertionError("No cache lookup")),
                    patch(ENGINE, side_effect=AssertionError("No calculation")),
                ):
                    response = self.client.post(ENDPOINT, json=TERRAIN)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(
                    response.json()["error"]["message"],
                    "Reference data is unavailable or failed validation.",
                )
                self.assertNotIn(str(root), response.text)
                self.assertNotIn("series", response.json())
                self.assertEqual(self.cache.info(), before)

    def test_invalid_selection_policy_and_ids_fail_before_cache_lookup(self):
        self.post_ok(TERRAIN)
        before = self.cache.info()
        with (
            patch.object(self.cache, "get", side_effect=AssertionError("No cache lookup")),
            patch(ENGINE, side_effect=AssertionError("No calculation")),
        ):
            for changes, status in (
                ({"stepMinutes": 90}, 422),
                ({"startUtc": "2026-11-14T00:30:00Z"}, 422),
                ({"endUtc": "2026-12-15T00:00:00Z"}, 422),
                ({"asOfUtc": TERRAIN["endUtc"]}, 422),
                ({"allowMeanEarthApproximation": False}, 422),
                ({"siteId": "lola-site04-reference"}, 422),
                ({"siteId": "unknown-site"}, 404),
                ({"maskId": "unknown-mask"}, 404),
            ):
                with self.subTest(changes=changes):
                    response = self.client.post(ENDPOINT, json=TERRAIN | changes)
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertIn("error", response.json())
                    self.assertNotIn("series", response.json())
        self.assertEqual(self.cache.info(), before)

    def test_new_reviewed_artifact_with_incompatible_observer_or_frame_still_returns_422(self):
        for mismatch in ("height", "frame"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.copy_sources(root)
                self.post_ok(TERRAIN)
                path = root / "terrain-masks" / f"{MASK_ID}.json"
                updated = json.loads(path.read_bytes())
                if mismatch == "height":
                    updated["observer"]["mastHeightM"] = 2
                    updated["observer"]["altitudeKm"] += 0.002
                else:
                    updated["referenceFrame"]["realization"] = "unreviewed frame"
                path.write_text(json.dumps(updated), encoding="utf-8")
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                with (
                    patch.dict(
                        "lunarwindow.terrain.registry._MASKS",
                        {MASK_ID: (REQUEST["siteId"], path.name, checksum)},
                    ),
                    patch.object(self.cache, "get", side_effect=AssertionError("No cache lookup")),
                    patch(ENGINE, side_effect=AssertionError("No calculation")),
                ):
                    response = self.client.post(ENDPOINT, json=TERRAIN)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn("series", response.json())

    def test_cached_models_are_fresh_and_cannot_mutate_the_stored_snapshot(self):
        request = ReferenceEvaluationRequest.model_validate(REQUEST)
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            first = evaluate_reference(request, REFERENCE / "validation-30d", cache=self.cache)
            original = first.model_dump()
            first.series.clear()
            first.provenance.ephemeris["requests"].clear()
            second = evaluate_reference(request, REFERENCE / "validation-30d", cache=self.cache)
            self.assertEqual(second.model_dump(), original)
            self.assertIsNot(first, second)
            self.assertEqual(engine.call_count, 1)

    def test_disabled_or_oversized_cache_does_not_change_successful_responses(self):
        for options in ({"max_entries": 0}, {"max_bytes": 1}):
            with self.subTest(options=options):
                cache = ReferenceEvaluationCache(**options)
                self.app.dependency_overrides[get_reference_cache] = lambda: cache
                with patch(ENGINE, wraps=calculate_visibility) as engine:
                    self.assertEqual(self.post_ok(), self.post_ok())
                    self.assertEqual(engine.call_count, 2)
                self.assertEqual(cache.info().entry_count, 0)

    def test_endpoint_uses_bounded_storage_and_app_instances_are_isolated(self):
        cache = ReferenceEvaluationCache(max_entries=1)
        self.app.dependency_overrides[get_reference_cache] = lambda: cache
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            first = self.post_ok()
            self.post_ok(REQUEST | {"visibilityRule": "full-disc"})
            self.assertEqual(self.post_ok(), first)
            self.assertEqual(engine.call_count, 3)
            self.assertEqual(cache.info().entry_count, 1)
            other = create_app()
            other.dependency_overrides[get_reference_directory] = lambda: (
                REFERENCE / "validation-30d"
            )
            with TestClient(other) as client:
                response = client.post(ENDPOINT, json=REQUEST)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), first)
            self.assertEqual(engine.call_count, 4)
            self.assertIsNot(other.state.reference_evaluation_cache, self.cache)

    def test_invalid_calculated_response_is_not_cached_and_next_request_recovers(self):
        def invalid_result(*args, **kwargs):
            result = calculate_visibility(*args, **kwargs)
            return result.model_copy(
                update={"metrics": result.metrics.model_copy(update={"evaluatedHrs": 999})}
            )

        with patch(ENGINE, side_effect=invalid_result):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.cache.info().entry_count, 0)
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            self.assertEqual(self.post_ok(), self.post_ok())
            self.assertEqual(engine.call_count, 1)

    def test_invalid_internal_snapshot_is_recomputed_and_replaced(self):
        request = ReferenceEvaluationRequest.model_validate(REQUEST)
        verified = load_verified_reference_dataset(REFERENCE / "validation-30d", request.siteId)
        key = build_reference_evaluation_cache_key(
            request, ephemeris_sha256=verified.artifact_sha256
        )
        self.cache.put(key, b"not a response")
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            first = self.post_ok()
            self.assertEqual(self.post_ok(), first)
            self.assertEqual(engine.call_count, 1)
