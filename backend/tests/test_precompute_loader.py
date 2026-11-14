"""Lookup hits/misses, same-snapshot responses, and fail-closed bundle loading."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter, ValidationError

from lunarwindow.api.reference_cache_key import (
    ReferenceEvaluationCacheKey,
    build_reference_evaluation_cache_key,
)
from lunarwindow.api.terrain_models import ReferenceEvaluationRequestContract
from lunarwindow.precompute import (
    PrecomputeJob,
    PrecomputeManifest,
    PrecomputeVerificationError,
    generate_bundle,
    load_precomputed_evaluation,
)
from lunarwindow.reference import load_verified_reference_dataset
from lunarwindow.terrain.registry import load_reviewed_mask

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
SITE_ID = "lola-site01-reference"
MASK_ID = "lola-site01-reference-mast-0m"


class PrecomputeLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.fixture = Path(temporary.name) / "bundle"
        archive = load_verified_reference_dataset(REFERENCE / "validation-30d", SITE_ID)
        mask = load_reviewed_mask(REFERENCE / "terrain-masks", MASK_ID)
        jobs = []
        for terrain in (False, True):
            payload = {
                "siteId": SITE_ID,
                "horizonMode": "terrain" if terrain else "geometric",
                "startUtc": "2026-11-14T00:00:00Z",
                "endUtc": "2026-11-15T00:00:00Z",
            }
            if terrain:
                payload.update(maskId=MASK_ID, allowMeanEarthApproximation=True)
            request = TypeAdapter(ReferenceEvaluationRequestContract).validate_python(payload)
            jobs.append(
                PrecomputeJob(
                    evaluation=build_reference_evaluation_cache_key(
                        request,
                        ephemeris_sha256=archive.artifact_sha256,
                        terrain_mask_sha256=mask.artifact_sha256 if terrain else None,
                    ),
                    status="pending",
                )
            )
        cls.generated = generate_bundle(
            jobs,
            run_id="lookup-site01-test",
            reference_directory=REFERENCE / "validation-30d",
            output_directory=cls.fixture,
        )
        cls.keys = [job.evaluation for job in cls.generated.jobs]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.fresh_bundle("bundle")

    def fresh_bundle(self, name):
        return Path(shutil.copytree(self.fixture, self.root / name))

    def load(self, key=None, *, bundle=None, source_root=REFERENCE):
        return load_precomputed_evaluation(
            self.bundle if bundle is None else bundle,
            self.keys[0] if key is None else key,
            reference_directory=source_root / "validation-30d",
        )

    def changed_key(self, index=0, **changes):
        return ReferenceEvaluationCacheKey.model_validate(self.keys[index].model_dump() | changes)

    def test_geometric_and_terrain_hits_return_exact_saved_response_models(self):
        for key, job in zip(self.keys, self.generated.jobs):
            with self.subTest(mode=key.horizonMode):
                expected = json.loads((self.bundle / job.output.filename).read_bytes())
                actual = self.load(key)
                self.assertIsNotNone(actual)
                self.assertEqual(actual.model_dump(mode="json"), expected)
                self.assertEqual(actual.horizonMode, key.horizonMode)
                self.assertEqual(actual.provenance.ephemeris["provider"], "NASA/JPL Horizons")
        canonical = self.changed_key(startUtc="2026-11-14T00:00Z", asOfUtc="2026-11-14T00:00Z")
        self.assertEqual(self.load(canonical).model_dump(), self.load().model_dump())

    def test_absent_keys_are_misses_only_after_a_valid_bundle_is_verified(self):
        for key in (
            self.changed_key(visibilityRule="body-center"),
            self.changed_key(stepMinutes=120),
            self.changed_key(asOfUtc="2026-11-14T01:00:00Z"),
            self.changed_key(siteId="another-reference-site"),
            self.changed_key(ephemerisSha256="0" * 64),
            self.changed_key(1, maskId="another-mask"),
            self.changed_key(1, terrainMaskSha256="0" * 64),
            self.changed_key(1, allowMeanEarthApproximation=False),
        ):
            with self.subTest(key=key):
                self.assertIsNone(self.load(key))

    def test_returned_models_are_fresh_and_nested_mutation_does_not_leak(self):
        first = self.load(self.keys[1])
        expected = first.model_dump()
        first.series.clear()
        first.provenance.ephemeris["requests"].clear()
        first.provenance.terrain.mask.horizon.clear()
        second = self.load(self.keys[1])
        self.assertIsNot(first, second)
        self.assertEqual(second.model_dump(), expected)

    def test_matching_output_is_not_reread_after_its_verified_snapshot(self):
        path = self.bundle / self.generated.jobs[0].output.filename
        expected = json.loads(path.read_bytes())
        read_bytes = Path.read_bytes
        reads = 0

        def change_after_read(source):
            nonlocal reads
            content = read_bytes(source)
            if source == path:
                reads += 1
                path.write_bytes(b"changed after the verified read")
            return content

        with patch.object(Path, "read_bytes", change_after_read):
            actual = self.load()
        self.assertEqual(actual.model_dump(mode="json"), expected)
        self.assertEqual(reads, 1)
        with self.assertRaisesRegex(PrecomputeVerificationError, "checksum mismatch"):
            self.load()

    def test_corrupted_sibling_rejects_both_a_match_and_a_miss(self):
        # The matching geometric output is processed before this damaged sibling.
        (self.bundle / self.generated.jobs[1].output.filename).write_bytes(b"{}")
        for key in (self.keys[0], self.changed_key(visibilityRule="body-center")):
            with self.subTest(key=key), self.assertRaises(PrecomputeVerificationError):
                self.load(key)

    def test_missing_or_incomplete_bundle_is_an_error_instead_of_a_miss(self):
        with self.assertRaises(PrecomputeVerificationError):
            self.load(bundle=self.root / "missing-bundle")
        path = self.bundle / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest.update(status="incomplete", completedAtUtc=None)
        manifest["jobs"][1].update(status="pending", output=None)
        PrecomputeManifest.model_validate(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(PrecomputeVerificationError, "Only complete"):
            self.load(self.changed_key(visibilityRule="body-center"))

    def test_invalid_and_unsupported_lookup_keys_are_rejected_before_artifact_reads(self):
        invalid = self.keys[0].model_copy(update={"stepMinutes": 0})
        unsupported = self.changed_key(calculationModelVersion="lunarwindow.visibility.future")
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("No artifact reads")):
            with self.assertRaises(ValidationError):
                self.load(invalid)
            with self.assertRaisesRegex(
                PrecomputeVerificationError, "Unsupported calculation-model"
            ):
                self.load(unsupported)

    def test_unsupported_model_in_another_job_invalidates_the_whole_bundle(self):
        path = self.bundle / "manifest.json"
        manifest = json.loads(path.read_bytes())
        job = manifest["jobs"][1]
        updated = ReferenceEvaluationCacheKey.model_validate(
            job["evaluation"] | {"calculationModelVersion": "lunarwindow.visibility.future"}
        )
        old_path = self.bundle / job["output"]["filename"]
        job["evaluation"] = updated.model_dump()
        job["output"]["filename"] = f"{updated.digest}.json"
        old_path.rename(self.bundle / job["output"]["filename"])
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(PrecomputeVerificationError, "Unsupported calculation-model"):
            self.load()

    def test_sources_are_reverified_on_each_load_and_mismatches_are_not_misses(self):
        source = self.root / "sources"
        for name in ("validation-30d", "terrain-masks"):
            shutil.copytree(REFERENCE / name, source / name)
        first = self.load(source_root=source)
        self.assertIsNotNone(first)
        (source / "validation-30d" / f"{SITE_ID}.json").write_bytes(b"{}")
        with self.assertRaises(PrecomputeVerificationError):
            self.load(source_root=source)

    def test_mixed_bundle_requires_valid_masks_but_geometric_only_bundle_does_not(self):
        with self.assertRaises(PrecomputeVerificationError):
            load_precomputed_evaluation(
                self.bundle,
                self.keys[0],
                reference_directory=REFERENCE / "validation-30d",
                terrain_directory=self.root / "missing-masks",
            )
        path = self.bundle / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["jobs"] = manifest["jobs"][:1]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        actual = load_precomputed_evaluation(
            self.bundle,
            self.keys[0],
            reference_directory=REFERENCE / "validation-30d",
            terrain_directory=self.root / "missing-masks",
        )
        self.assertEqual(actual.horizonMode, "geometric")

    def test_loading_is_read_only_and_never_calculates_or_uses_the_result_cache(self):
        before = {p.name: p.read_bytes() for p in self.bundle.iterdir()}
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch(
                "lunarwindow.api.reference_provider.calculate_visibility",
                side_effect=AssertionError("No calculation"),
            ),
            patch(
                "lunarwindow.precompute.generator.evaluate_reference",
                side_effect=AssertionError("No evaluation"),
            ),
            patch(
                "lunarwindow.api.reference_cache.ReferenceEvaluationCache.get",
                side_effect=AssertionError("No cache reads"),
            ),
            patch(
                "lunarwindow.api.reference_cache.ReferenceEvaluationCache.put",
                side_effect=AssertionError("No cache writes"),
            ),
            patch("pathlib.Path.write_bytes", side_effect=AssertionError("No writes")),
            patch("pathlib.Path.write_text", side_effect=AssertionError("No writes")),
        ):
            self.assertIsNotNone(self.load(self.keys[1]))
        self.assertEqual({p.name: p.read_bytes() for p in self.bundle.iterdir()}, before)
