"""Real offline generation, publication checkpoints, and failure isolation."""

import hashlib
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
from lunarwindow.api.reference_provider import evaluate_reference
from lunarwindow.api.terrain_models import (
    ReferenceEvaluationContract,
    ReferenceEvaluationRequestContract,
)
from lunarwindow.ephemeris.storage import atomic_write
from lunarwindow.precompute import (
    PrecomputeGenerationError,
    PrecomputeJob,
    PrecomputeManifest,
    generate_bundle,
)
from lunarwindow.reference import load_verified_reference_dataset
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
    "stepMinutes": 60,
}
ENGINE = "lunarwindow.api.reference_provider.calculate_visibility"
RESPONSE = TypeAdapter(ReferenceEvaluationContract)


class PrecomputeGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = load_verified_reference_dataset(REFERENCE / "validation-30d", REQUEST["siteId"])
        mask = load_reviewed_mask(REFERENCE / "terrain-masks", MASK_ID)
        cls.requests = [
            TypeAdapter(ReferenceEvaluationRequestContract).validate_python(payload)
            for payload in (
                REQUEST,
                REQUEST
                | {
                    "horizonMode": "terrain",
                    "maskId": MASK_ID,
                    "allowMeanEarthApproximation": True,
                },
            )
        ]
        cls.jobs = [
            PrecomputeJob(
                evaluation=build_reference_evaluation_cache_key(
                    request,
                    ephemeris_sha256=archive.artifact_sha256,
                    terrain_mask_sha256=mask.artifact_sha256 if index else None,
                ),
                status="pending",
            )
            for index, request in enumerate(cls.requests)
        ]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "bundle"

    def generate(self, jobs=None, *, reference_root=REFERENCE, output=None):
        return generate_bundle(
            self.jobs if jobs is None else jobs,
            run_id="site01-offline-test",
            reference_directory=reference_root / "validation-30d",
            terrain_directory=reference_root / "terrain-masks",
            output_directory=self.output if output is None else output,
        )

    def manifest(self, output=None):
        path = (self.output if output is None else output) / "manifest.json"
        return PrecomputeManifest.model_validate_json(path.read_bytes())

    def copy_sources(self):
        root = self.root / "sources"
        for name in ("validation-30d", "terrain-masks"):
            shutil.copytree(REFERENCE / name, root / name)
        return root

    def changed_job(self, index=0, **changes):
        key = ReferenceEvaluationCacheKey.model_validate(
            self.jobs[index].evaluation.model_dump() | changes
        )
        return PrecomputeJob(evaluation=key, status="pending")

    def test_real_geometric_and_terrain_outputs_match_provider_and_exact_file_checksums(self):
        source_paths = [
            REFERENCE / "validation-30d" / f"{REQUEST['siteId']}.json",
            REFERENCE / "terrain-masks" / f"{MASK_ID}.json",
        ]
        original = [path.read_bytes() for path in source_paths]
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No NASA")),
            patch("lunarwindow.terrain.download.urlopen", side_effect=AssertionError("No DEM")),
            patch(
                "lunarwindow.api.reference_cache.ReferenceEvaluationCache.get",
                side_effect=AssertionError("No cache reads"),
            ),
            patch(
                "lunarwindow.api.reference_cache.ReferenceEvaluationCache.put",
                side_effect=AssertionError("No cache writes"),
            ),
            patch(ENGINE, wraps=calculate_visibility) as engine,
        ):
            result = self.generate()
        self.assertEqual(engine.call_count, 2)
        self.assertEqual(result, self.manifest())
        self.assertEqual(result.status, "complete")
        self.assertIsNotNone(result.completedAtUtc)
        self.assertEqual(len(list(self.output.iterdir())), 3)
        for job, request in zip(result.jobs, self.requests):
            self.assertEqual(job.status, "complete")
            content = (self.output / job.output.filename).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), job.output.sha256)
            self.assertTrue(content.endswith(b"\n"))
            self.assertNotIn(b"\r\n", content)
            parsed = RESPONSE.validate_json(content)
            expected = evaluate_reference(
                request, REFERENCE / "validation-30d", REFERENCE / "terrain-masks"
            )
            self.assertEqual(parsed.model_dump(), expected.model_dump())
            self.assertEqual(parsed.schemaVersion, job.output.responseSchemaVersion)
        self.assertEqual([path.read_bytes() for path in source_paths], original)
        self.assertTrue(all(job.status == "pending" and job.output is None for job in self.jobs))

    def test_manifest_is_incomplete_before_calculations_and_checkpointed_between_jobs(self):
        observed = []

        def observe(*args, **kwargs):
            current = self.manifest()
            observed.append((current.status, [job.status for job in current.jobs]))
            return evaluate_reference(*args, **kwargs)

        with patch("lunarwindow.precompute.generator.evaluate_reference", side_effect=observe):
            self.generate()
        self.assertEqual(
            observed,
            [("incomplete", ["pending", "pending"]), ("incomplete", ["complete", "pending"])],
        )
        self.assertEqual(self.manifest().status, "complete")

    def test_invalid_duplicate_empty_and_non_pending_plans_write_nothing(self):
        completed = PrecomputeJob.model_validate(
            self.jobs[0].model_dump() | {"status": "failed", "error": "Previously failed."}
        )
        for jobs in ([], [self.jobs[0], self.jobs[0]], [completed]):
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                self.generate(jobs)
            self.assertFalse(self.output.exists())

    def test_existing_directory_or_file_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "manifest.json"
        sentinel.write_bytes(b"existing run")
        with self.assertRaises(FileExistsError):
            self.generate()
        self.assertEqual(sentinel.read_bytes(), b"existing run")
        other = self.root / "existing-file"
        other.write_bytes(b"existing file")
        with self.assertRaises(FileExistsError):
            self.generate(output=other)
        self.assertEqual(other.read_bytes(), b"existing file")

    def test_second_job_failure_preserves_first_output_and_leaves_later_job_pending(self):
        root = self.copy_sources()
        (root / "terrain-masks" / f"{MASK_ID}.json").write_bytes(b"{}")
        extra = self.changed_job(visibilityRule="body-center")
        with patch(ENGINE, wraps=calculate_visibility) as engine:
            with self.assertRaises(PrecomputeGenerationError) as failure:
                self.generate([*self.jobs, extra], reference_root=root)
        self.assertIsInstance(failure.exception.__cause__, ValueError)
        manifest = self.manifest()
        self.assertEqual(manifest.status, "incomplete")
        self.assertIsNone(manifest.completedAtUtc)
        self.assertEqual([j.status for j in manifest.jobs], ["complete", "failed", "pending"])
        self.assertIsNone(manifest.jobs[1].output)
        self.assertIn("checksum", manifest.jobs[1].error.lower())
        self.assertEqual(engine.call_count, 1)
        output = manifest.jobs[0].output
        self.assertEqual(
            hashlib.sha256((self.output / output.filename).read_bytes()).hexdigest(), output.sha256
        )
        self.assertEqual(len(list(self.output.iterdir())), 2)

    def test_missing_or_corrupt_archive_cannot_generate_a_response(self):
        for index, damage in enumerate(("missing", "sibling")):
            root = self.root / f"sources-{index}"
            shutil.copytree(REFERENCE / "validation-30d", root / "validation-30d")
            if damage == "missing":
                (root / "validation-30d" / f"{REQUEST['siteId']}.json").unlink()
            else:
                (root / "validation-30d/lola-site04-reference.csv").write_bytes(b"broken")
            output = self.root / f"bundle-{index}"
            with (
                self.subTest(damage=damage),
                patch(ENGINE, side_effect=AssertionError("No calculation")),
            ):
                with self.assertRaises(PrecomputeGenerationError):
                    self.generate(reference_root=root, output=output)
            self.assertEqual(self.manifest(output).jobs[0].status, "failed")
            self.assertEqual(len(list(output.iterdir())), 1)

    def test_stale_source_mask_or_model_identity_is_rejected_before_calculation(self):
        jobs = [
            self.changed_job(ephemerisSha256="0" * 64),
            self.changed_job(1, terrainMaskSha256="0" * 64),
            self.changed_job(calculationModelVersion="lunarwindow.visibility.old"),
        ]
        with patch(ENGINE, side_effect=AssertionError("No stale-identity calculation")):
            for index, job in enumerate(jobs):
                output = self.root / f"stale-{index}"
                with (
                    self.subTest(index=index),
                    self.assertRaises(PrecomputeGenerationError) as failure,
                ):
                    self.generate([job], output=output)
                self.assertIn("planned precompute identity", str(failure.exception.__cause__))
                self.assertEqual(self.manifest(output).status, "incomplete")
                self.assertEqual(len(list(output.iterdir())), 1)

    def test_valid_source_revision_cannot_be_silently_used_under_an_old_planned_hash(self):
        root = self.copy_sources()
        path = root / "validation-30d" / f"{REQUEST['siteId']}.json"
        updated = json.loads(path.read_bytes())
        updated["coordinateSource"] += " Revised test metadata."
        path.write_text(json.dumps(updated), encoding="utf-8")
        manifest_path = path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        item = next(item for item in manifest["datasets"] if item["siteId"] == REQUEST["siteId"])
        item["jsonSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        # The revised bundle verifies; the planned artifact identity still must match.
        load_verified_reference_dataset(path.parent, REQUEST["siteId"])
        with patch(ENGINE, side_effect=AssertionError("No calculation")):
            with self.assertRaises(PrecomputeGenerationError) as failure:
                self.generate(reference_root=root)
        self.assertIn("planned precompute identity", str(failure.exception.__cause__))
        self.assertEqual(self.manifest().jobs[0].status, "failed")

    def test_terrain_for_another_site_is_rejected_by_compatibility(self):
        job = self.changed_job(1, siteId="lola-site04-reference")
        with patch(ENGINE, side_effect=AssertionError("No calculation")):
            with self.assertRaises(PrecomputeGenerationError) as failure:
                self.generate([job])
        self.assertIn("siteId differ", str(failure.exception.__cause__))
        self.assertEqual(self.manifest().jobs[0].status, "failed")

    def test_invalid_or_wrong_identity_results_are_not_written_as_successful_outputs(self):
        valid = evaluate_reference(self.requests[0], REFERENCE / "validation-30d")
        invalid = valid.model_copy(
            update={"metrics": valid.metrics.model_copy(update={"evaluatedHrs": 999})}
        )
        different = evaluate_reference(
            TypeAdapter(ReferenceEvaluationRequestContract).validate_python(
                REQUEST | {"visibilityRule": "full-disc"}
            ),
            REFERENCE / "validation-30d",
        )
        for index, result in enumerate((invalid, different)):
            output = self.root / f"invalid-result-{index}"
            with patch("lunarwindow.precompute.generator.evaluate_reference", return_value=result):
                with self.assertRaises(PrecomputeGenerationError) as failure:
                    self.generate([self.jobs[0]], output=output)
            self.assertIsInstance(
                failure.exception.__cause__, ValidationError if index == 0 else ValueError
            )
            self.assertEqual(self.manifest(output).jobs[0].status, "failed")
            self.assertEqual(len(list(output.iterdir())), 1)

    def test_failed_atomic_output_replace_cleans_temporary_file_and_records_failure(self):
        replace = Path.replace

        def fail_output_replace(source, destination):
            if Path(destination).name != "manifest.json":
                raise OSError("Simulated output publication failure.")
            return replace(source, destination)

        with patch.object(Path, "replace", fail_output_replace):
            with self.assertRaises(PrecomputeGenerationError):
                self.generate()
        self.assertEqual(self.manifest().jobs[0].status, "failed")
        self.assertEqual([p.name for p in self.output.iterdir()], ["manifest.json"])

    def test_unexpected_saved_bytes_and_failed_final_publication_never_claim_completion(self):
        for index, mode in enumerate(("saved-bytes", "final-manifest")):
            output = self.root / f"write-failure-{index}"

            def faulty_write(path, content):
                if mode == "saved-bytes" and path.name != "manifest.json":
                    content += "\n"
                if (
                    mode == "final-manifest"
                    and path.name == "manifest.json"
                    and json.loads(content)["status"] == "complete"
                ):
                    raise OSError("Simulated final manifest write failure.")
                return atomic_write(path, content)

            with (
                self.subTest(mode=mode),
                patch("lunarwindow.precompute.generator.atomic_write", side_effect=faulty_write),
            ):
                with self.assertRaises(PrecomputeGenerationError):
                    self.generate(output=output)
            manifest = self.manifest(output)
            self.assertEqual(manifest.status, "incomplete")
            self.assertIsNone(manifest.completedAtUtc)
            self.assertTrue(any(j.status == "failed" for j in manifest.jobs))

    def test_process_interruption_leaves_an_incomplete_checkpoint(self):
        with patch(
            "lunarwindow.precompute.generator.evaluate_reference", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.generate()
        self.assertEqual(self.manifest().status, "incomplete")
        self.assertTrue(all(j.status == "pending" for j in self.manifest().jobs))

    def test_prior_output_damage_is_detected_before_the_complete_manifest_is_published(self):
        for index, damage in enumerate(("changed", "missing")):
            output = self.root / f"prior-output-{index}"
            calls = 0

            def damage_prior_output(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    first = output / f"{self.jobs[0].evaluation.digest}.json"
                    if damage == "changed":
                        first.write_bytes(b"{}")
                    else:
                        first.unlink()
                return evaluate_reference(*args, **kwargs)

            with (
                self.subTest(damage=damage),
                patch(
                    "lunarwindow.precompute.generator.evaluate_reference",
                    side_effect=damage_prior_output,
                ),
            ):
                with self.assertRaises(PrecomputeGenerationError):
                    self.generate(output=output)
            manifest = self.manifest(output)
            self.assertEqual(manifest.status, "incomplete")
            self.assertEqual([j.status for j in manifest.jobs], ["failed", "complete"])
