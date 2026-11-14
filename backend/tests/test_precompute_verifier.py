"""Read-only bundle verification against real archives and deliberately altered outputs."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter

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
    verify_bundle,
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


class PrecomputeVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.fixture = Path(temporary.name) / "bundle"
        archive = load_verified_reference_dataset(REFERENCE / "validation-30d", SITE_ID)
        reviewed = load_reviewed_mask(REFERENCE / "terrain-masks", MASK_ID)
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
            key = build_reference_evaluation_cache_key(
                request,
                ephemeris_sha256=archive.artifact_sha256,
                terrain_mask_sha256=reviewed.artifact_sha256 if terrain else None,
            )
            jobs.append(PrecomputeJob(evaluation=key, status="pending"))
        cls.generated = generate_bundle(
            jobs,
            run_id="verify-site01-test",
            reference_directory=REFERENCE / "validation-30d",
            output_directory=cls.fixture,
        )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.fresh_bundle("bundle")

    def fresh_bundle(self, name):
        return Path(shutil.copytree(self.fixture, self.root / name))

    def read_manifest(self, bundle=None):
        return json.loads(((bundle or self.bundle) / "manifest.json").read_bytes())

    def save_manifest(self, manifest, bundle=None):
        ((bundle or self.bundle) / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def verify(self, bundle=None, *, reference_root=REFERENCE):
        return verify_bundle(
            bundle or self.bundle, reference_directory=reference_root / "validation-30d"
        )

    def rewrite_output(self, index, change, *, bundle=None):
        bundle = bundle or self.bundle
        manifest = self.read_manifest(bundle)
        output = manifest["jobs"][index]["output"]
        path = bundle / output["filename"]
        payload = json.loads(path.read_bytes())
        change(payload)
        content = json.dumps(payload).encode("utf-8")
        path.write_bytes(content)
        output["sha256"] = hashlib.sha256(content).hexdigest()
        self.save_manifest(manifest, bundle)

    def change_job(self, index, change, *, bundle=None):
        bundle = bundle or self.bundle
        manifest = self.read_manifest(bundle)
        job = manifest["jobs"][index]
        key = ReferenceEvaluationCacheKey.model_validate(job["evaluation"] | change)
        old = bundle / job["output"]["filename"]
        job["evaluation"] = key.model_dump()
        job["output"]["filename"] = f"{key.digest}.json"
        old.rename(bundle / job["output"]["filename"])
        self.save_manifest(manifest, bundle)

    def test_generated_geometric_and_terrain_bundle_verifies_without_side_effects(self):
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
                side_effect=AssertionError("No cache"),
            ),
            patch(
                "lunarwindow.ephemeris.storage.atomic_write",
                side_effect=AssertionError("No writes"),
            ),
        ):
            actual = self.verify()
        self.assertEqual(actual, self.generated)
        self.assertEqual(actual.status, "complete")
        self.assertEqual(
            [job.evaluation.horizonMode for job in actual.jobs], ["geometric", "terrain"]
        )
        self.assertEqual({p.name: p.read_bytes() for p in self.bundle.iterdir()}, before)

    def test_incomplete_pending_or_failed_runs_are_rejected(self):
        for index, status in enumerate(("pending", "failed")):
            bundle = self.fresh_bundle(f"incomplete-{index}")
            manifest = self.read_manifest(bundle)
            manifest.update(status="incomplete", completedAtUtc=None)
            manifest["jobs"][1].update(status=status, output=None)
            if status == "failed":
                manifest["jobs"][1]["error"] = "Previous generation failed."
            PrecomputeManifest.model_validate(manifest)
            self.save_manifest(manifest, bundle)
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(PrecomputeVerificationError, "Only complete"),
            ):
                self.verify(bundle)

    def test_missing_or_malformed_manifest_or_output_is_rejected(self):
        for index, damage in enumerate(
            ("missing-manifest", "malformed-manifest", "missing-output", "corrupt-output")
        ):
            bundle = self.fresh_bundle(f"missing-{index}")
            manifest = self.read_manifest(bundle)
            path = bundle / (
                "manifest.json"
                if "manifest" in damage
                else manifest["jobs"][1]["output"]["filename"]
            )
            if damage.startswith("missing"):
                path.unlink()
            else:
                path.write_bytes(b"not json")
            with self.subTest(damage=damage), self.assertRaises(PrecomputeVerificationError):
                self.verify(bundle)

    def test_rehashed_but_invalid_response_and_wrong_response_schema_are_rejected(self):
        self.rewrite_output(0, lambda result: result["metrics"].update(evaluatedHrs=999))
        with self.assertRaises(PrecomputeVerificationError):
            self.verify()
        other = self.fresh_bundle("wrong-schema")
        manifest = self.read_manifest(other)
        terrain_bytes = (other / manifest["jobs"][1]["output"]["filename"]).read_bytes()
        output = manifest["jobs"][0]["output"]
        (other / output["filename"]).write_bytes(terrain_bytes)
        output["sha256"] = hashlib.sha256(terrain_bytes).hexdigest()
        self.save_manifest(manifest, other)
        with self.assertRaisesRegex(PrecomputeVerificationError, "schema differs"):
            self.verify(other)

    def test_changed_job_options_and_mask_identity_are_rejected_even_after_renaming(self):
        cases = [
            (0, {"siteId": "lola-site04-reference"}),
            (0, {"startUtc": "2026-11-14T01:00:00Z", "asOfUtc": "2026-11-14T01:00:00Z"}),
            (0, {"endUtc": "2026-11-16T00:00:00Z"}),
            (0, {"stepMinutes": 120}),
            (0, {"visibilityRule": "body-center"}),
            (0, {"asOfUtc": "2026-11-14T01:00:00Z"}),
            (1, {"maskId": "different-mask"}),
            (1, {"terrainMaskSha256": "0" * 64}),
        ]
        for index, (job, change) in enumerate(cases):
            bundle = self.fresh_bundle(f"options-{index}")
            self.change_job(job, change, bundle=bundle)
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(PrecomputeVerificationError, "job identity"),
            ):
                self.verify(bundle)

    def test_ephemeris_hash_is_checked_against_actual_source_bytes(self):
        self.change_job(0, {"ephemerisSha256": "0" * 64})
        with self.assertRaisesRegex(PrecomputeVerificationError, "source archive checksum"):
            self.verify()

    def test_rehashed_source_metadata_provenance_and_raw_samples_must_match_archive(self):
        def archive_coverage(result):
            result["provenance"]["archive"].update(endUtc="2026-12-15T00:00:00Z", sampleCount=744)

        cases = [
            lambda r: r.update(coordinateSource="Altered source description."),
            lambda r: r.update(site="Altered site title"),
            lambda r: r["provenance"]["ephemeris"]["requests"][0].update(responseSha256="0" * 64),
            archive_coverage,
            lambda r: r["series"][0].update(sunEl=r["series"][0]["sunEl"] + 0.001),
        ]
        for index, change in enumerate(cases):
            bundle = self.fresh_bundle(f"provenance-{index}")
            self.rewrite_output(0, change, bundle=bundle)
            with (
                self.subTest(index=index),
                self.assertRaisesRegex(PrecomputeVerificationError, "differs|differ"),
            ):
                self.verify(bundle)

    def test_full_terrain_mask_metadata_is_checked_not_just_claimed_hash(self):
        def change(result):
            result["provenance"]["terrain"]["mask"]["provenance"]["sources"][0][
                "productVersion"
            ] += "-altered"

        self.rewrite_output(1, change)
        with self.assertRaisesRegex(PrecomputeVerificationError, "terrain provenance"):
            self.verify()

    def test_unsupported_calculation_manifest_and_response_versions_are_rejected(self):
        self.change_job(0, {"calculationModelVersion": "lunarwindow.visibility.future"})
        with self.assertRaisesRegex(PrecomputeVerificationError, "Unsupported calculation-model"):
            self.verify()
        for index, path in enumerate(
            (
                ("schemaVersion",),
                ("jobs", 0, "evaluation", "schemaVersion"),
                ("jobs", 0, "output", "responseSchemaVersion"),
            )
        ):
            bundle = self.fresh_bundle(f"version-{index}")
            manifest = self.read_manifest(bundle)
            target = manifest
            for name in path[:-1]:
                target = target[name]
            target[path[-1]] = "unsupported.v99"
            self.save_manifest(manifest, bundle)
            with self.subTest(path=path), self.assertRaises(PrecomputeVerificationError):
                self.verify(bundle)

    def test_invalid_or_changed_source_artifacts_are_rejected_without_recalculation(self):
        for index, damage in enumerate(
            ("missing-archive", "sibling-csv", "mask", "revised-archive")
        ):
            root = self.root / f"sources-{index}"
            for name in ("validation-30d", "terrain-masks"):
                shutil.copytree(REFERENCE / name, root / name)
            if damage == "mask":
                (root / "terrain-masks" / f"{MASK_ID}.json").write_bytes(b"{}")
            elif damage == "sibling-csv":
                (root / "validation-30d/lola-site04-reference.csv").write_bytes(b"corrupt")
            else:
                path = root / "validation-30d" / f"{SITE_ID}.json"
                if damage == "missing-archive":
                    path.unlink()
                else:
                    data = json.loads(path.read_bytes())
                    data["coordinateSource"] += " Revised test provenance."
                    path.write_text(json.dumps(data), encoding="utf-8")
                    manifest_path = path.parent / "manifest.json"
                    manifest = json.loads(manifest_path.read_bytes())
                    item = next(item for item in manifest["datasets"] if item["siteId"] == SITE_ID)
                    item["jsonSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    load_verified_reference_dataset(path.parent, SITE_ID)
            with (
                self.subTest(damage=damage),
                patch(
                    "lunarwindow.api.reference_provider.calculate_visibility",
                    side_effect=AssertionError("No calculation"),
                ),
            ):
                with self.assertRaises(PrecomputeVerificationError):
                    self.verify(reference_root=root)

    def test_geometric_only_bundle_does_not_need_terrain_files(self):
        manifest = self.read_manifest()
        manifest["jobs"] = manifest["jobs"][:1]
        self.save_manifest(manifest)
        with patch(
            "lunarwindow.precompute.verifier.load_reviewed_mask",
            side_effect=AssertionError("No terrain"),
        ):
            result = verify_bundle(
                self.bundle,
                reference_directory=REFERENCE / "validation-30d",
                terrain_directory=self.root / "absent-terrain",
            )
        self.assertEqual(len(result.jobs), 1)

    def test_symlinked_manifest_or_output_is_rejected(self):
        for index, manifest_link in enumerate((True, False)):
            bundle = self.fresh_bundle(f"links-{index}")
            manifest = self.read_manifest(bundle)
            path = bundle / (
                "manifest.json" if manifest_link else manifest["jobs"][0]["output"]["filename"]
            )
            external = self.root / f"external-{index}.json"
            external.write_bytes(path.read_bytes())
            path.unlink()
            try:
                path.symlink_to(external)
            except OSError as exc:
                self.skipTest(f"Creating symlinks is unavailable: {exc}")
            with (
                self.subTest(manifest_link=manifest_link),
                self.assertRaisesRegex(PrecomputeVerificationError, "regular file"),
            ):
                self.verify(bundle)

    def test_output_is_hashed_and_parsed_from_the_same_read(self):
        path = self.bundle / self.generated.jobs[0].output.filename
        read_bytes = Path.read_bytes
        reads = 0

        def change_after_read(source):
            nonlocal reads
            content = read_bytes(source)
            if source == path:
                reads += 1
                path.write_bytes(b"{}")
            return content

        with patch.object(Path, "read_bytes", change_after_read):
            self.assertEqual(self.verify(), self.generated)
        self.assertEqual(reads, 1)
        with self.assertRaisesRegex(PrecomputeVerificationError, "checksum mismatch"):
            self.verify()
