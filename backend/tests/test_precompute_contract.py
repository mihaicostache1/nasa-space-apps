"""Manifest bookkeeping, state consistency, identity, and schema handoff tests."""

import copy
import json
import unittest
from importlib.resources import files
from unittest.mock import patch

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from lunarwindow.api.reference_cache_key import build_reference_evaluation_cache_key
from lunarwindow.api.terrain_models import ReferenceEvaluationRequestContract
from lunarwindow.precompute import PrecomputeJob, PrecomputeManifest

REQUEST = {
    "siteId": "lola-site01-reference",
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-15T00:00:00Z",
}


def job(*, terrain=False, status="pending"):
    request = REQUEST | (
        {
            "horizonMode": "terrain",
            "maskId": "lola-site01-reference-mast-0m",
            "allowMeanEarthApproximation": True,
        }
        if terrain
        else {}
    )
    # Contract-only fixture hashes; validation makes no claim about actual files.
    key = build_reference_evaluation_cache_key(
        TypeAdapter(ReferenceEvaluationRequestContract).validate_python(request),
        ephemeris_sha256="1" * 64,
        terrain_mask_sha256="2" * 64 if terrain else None,
    )
    result = {"evaluation": key.model_dump(), "status": status}
    if status == "complete":
        result["output"] = {
            "filename": f"{key.digest}.json",
            "sha256": "3" * 64,
            "responseSchemaVersion": (
                "lunarwindow.reference-evaluation.v2"
                if terrain
                else "lunarwindow.reference-evaluation.v1"
            ),
        }
    elif status == "failed":
        result["error"] = "Source verification failed."
    return result


def manifest(*, complete=False):
    return {
        "schemaVersion": "lunarwindow.precompute-manifest.v1",
        "runId": "site01-reference-example",
        "createdAtUtc": "2026-11-14T12:00:00Z",
        "completedAtUtc": "2026-11-14T12:01:00Z" if complete else None,
        "status": "complete" if complete else "incomplete",
        "jobs": [
            job(terrain=terrain, status="complete" if complete else "pending")
            for terrain in (False, True)
        ],
    }


class PrecomputeContractTests(unittest.TestCase):
    def test_pending_and_complete_manifests_round_trip_with_full_identity(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                payload = manifest(complete=complete)
                parsed = PrecomputeManifest.model_validate(payload)
                restored = PrecomputeManifest.model_validate_json(parsed.model_dump_json())
                self.assertEqual(restored, parsed)
                self.assertEqual(
                    [j.evaluation.horizonMode for j in parsed.jobs], ["geometric", "terrain"]
                )
                self.assertEqual(parsed.jobs[0].evaluation.ephemerisSha256, "1" * 64)
                self.assertEqual(parsed.jobs[1].evaluation.terrainMaskSha256, "2" * 64)
                self.assertTrue(parsed.jobs[1].evaluation.allowMeanEarthApproximation)
                self.assertEqual(parsed.jobs[0].evaluation.asOfUtc, REQUEST["startUtc"])
                self.assertEqual(
                    parsed.jobs[0].evaluation.calculationModelVersion, "lunarwindow.visibility.v1"
                )
                with self.assertRaises(ValidationError):
                    parsed.status = "complete"

    def test_complete_run_requires_every_output_and_a_valid_completion_timestamp(self):
        for change in ("missing-time", "earlier-time", "pending-job", "failed-job", "empty-jobs"):
            payload = manifest(complete=True)
            if change == "missing-time":
                payload.pop("completedAtUtc")
            elif change == "earlier-time":
                payload["completedAtUtc"] = "2026-11-14T11:59:59Z"
            elif change in ("pending-job", "failed-job"):
                payload["jobs"][0] = job(status="pending" if change == "pending-job" else "failed")
            else:
                payload["jobs"] = []
            with self.subTest(change=change), self.assertRaises(ValidationError):
                PrecomputeManifest.model_validate(payload)

    def test_incomplete_run_records_failures_and_partial_outputs_without_claiming_success(self):
        payload = manifest()
        payload["jobs"] = [job(status="complete"), job(terrain=True, status="failed")]
        parsed = PrecomputeManifest.model_validate(payload)
        self.assertEqual(parsed.status, "incomplete")
        self.assertIsNone(parsed.completedAtUtc)
        self.assertIsNotNone(parsed.jobs[0].output)
        self.assertIsNone(parsed.jobs[1].output)
        self.assertEqual(parsed.jobs[1].error, "Source verification failed.")
        for change in ("finished-time", "all-complete"):
            bad = copy.deepcopy(payload)
            if change == "finished-time":
                bad["completedAtUtc"] = "2026-11-14T12:01:00Z"
            else:
                bad["jobs"][1] = job(terrain=True, status="complete")
            with self.subTest(change=change), self.assertRaises(ValidationError):
                PrecomputeManifest.model_validate(bad)

    def test_job_status_controls_output_and_error_fields(self):
        invalid = [
            job(status="complete") | {"output": None},
            job(status="complete") | {"error": "Failed"},
            job() | {"error": "Failed"},
            job() | {"output": job(status="complete")["output"]},
            job(status="failed") | {"error": None},
            job(status="failed") | {"error": "   "},
            job(status="failed") | {"output": job(status="complete")["output"]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                PrecomputeJob.model_validate(payload)

    def test_output_filenames_are_portable_and_tied_to_the_evaluation_identity(self):
        for filename in (
            "../result.json",
            "/tmp/result.json",
            "sub/result.json",
            "sub\\result.json",
            "C:\\result.json",
            "https://example.com/result.json",
            "manifest.json",
            "3" * 64 + ".json",
            "A" * 64 + ".json",
            "0" * 64 + ".csv",
        ):
            payload = job(status="complete")
            payload["output"]["filename"] = filename
            with self.subTest(filename=filename), self.assertRaises(ValidationError):
                PrecomputeJob.model_validate(payload)

    def test_output_schema_matches_geometric_or_terrain_mode(self):
        for terrain in (False, True):
            payload = job(terrain=terrain, status="complete")
            payload["output"]["responseSchemaVersion"] = (
                "lunarwindow.reference-evaluation.v1"
                if terrain
                else "lunarwindow.reference-evaluation.v2"
            )
            with self.subTest(terrain=terrain), self.assertRaises(ValidationError):
                PrecomputeJob.model_validate(payload)

    def test_duplicate_jobs_are_rejected_even_with_equivalent_utc_spellings(self):
        payload = manifest()
        duplicate = copy.deepcopy(payload["jobs"][0])
        for name in ("startUtc", "endUtc", "asOfUtc"):
            duplicate["evaluation"][name] = duplicate["evaluation"][name].replace(":00Z", "Z")
        payload["jobs"].append(duplicate)
        with self.assertRaisesRegex(ValidationError, "unique evaluation jobs"):
            PrecomputeManifest.model_validate(payload)

    def test_strict_versions_checksums_and_job_options(self):
        for path, value in (
            (("schemaVersion",), "lunarwindow.run.v1"),
            (("runId",), "../run"),
            (("createdAtUtc",), "2026-02-30T12:00:00Z"),
            (("createdAtUtc",), "2026-11-14T12:00:00+02:00"),
            (("jobs", 0, "status"), "success"),
            (("jobs", 0, "evaluation", "ephemerisSha256"), "not-a-checksum"),
            (("jobs", 1, "evaluation", "terrainMaskSha256"), None),
            (("jobs", 0, "evaluation", "calculationModelVersion"), ""),
            (("jobs", 0, "evaluation", "stepMinutes"), True),
            (("jobs", 0, "evaluation", "asOfUtc"), REQUEST["endUtc"]),
            (("jobs", 1, "evaluation", "allowMeanEarthApproximation"), False),
            (("jobs", 0, "output", "sha256"), "A" * 64),
            (("unexpected",), "extra"),
        ):
            payload = manifest(complete=True)
            target = payload
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path, value=value), self.assertRaises(ValidationError):
                PrecomputeManifest.model_validate(payload)

    def test_nested_model_instances_are_revalidated_before_a_run_can_be_complete(self):
        parsed = PrecomputeManifest.model_validate(manifest(complete=True))
        invalid_job = parsed.jobs[0].model_copy(update={"output": None})
        with self.assertRaises(ValidationError):
            PrecomputeManifest.model_validate(parsed.model_dump() | {"jobs": [invalid_job]})
        parsed.jobs.append(PrecomputeJob.model_validate(job()))
        with self.assertRaises(ValidationError):
            PrecomputeManifest.model_validate(parsed)

    def test_packaged_json_schema_matches_models_and_validates_good_manifests(self):
        schema = json.loads(
            files("lunarwindow.precompute")
            .joinpath("precompute-manifest.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(schema, PrecomputeManifest.model_json_schema())
        Draft202012Validator.check_schema(schema)
        for complete in (False, True):
            Draft202012Validator(schema).validate(manifest(complete=complete))

    def test_contract_validation_has_no_source_output_network_or_calculation_side_effects(self):
        payload = manifest(complete=True)
        with (
            patch("pathlib.Path.read_bytes", side_effect=AssertionError("No source reads")),
            patch("pathlib.Path.write_bytes", side_effect=AssertionError("No artifact writes")),
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch(
                "lunarwindow.visibility.engine.calculate_visibility",
                side_effect=AssertionError("No calculation"),
            ),
        ):
            parsed = PrecomputeManifest.model_validate(payload)
            self.assertEqual(parsed.status, "complete")
