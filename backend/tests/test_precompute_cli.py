"""CLI command wiring, offline generation/verification, stdout, and exit codes."""

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter

from lunarwindow.api.reference_cache_key import (
    ReferenceEvaluationCacheKey,
    build_reference_evaluation_cache_key,
)
from lunarwindow.api.terrain_models import ReferenceEvaluationRequestContract
from lunarwindow.precompute import PrecomputeJob, PrecomputeManifest
from lunarwindow.precompute.cli import main
from lunarwindow.reference import load_verified_reference_dataset
from lunarwindow.terrain.registry import load_reviewed_mask

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
SITE_ID = "lola-site01-reference"
MASK_ID = "lola-site01-reference-mast-0m"


class PrecomputeCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        cls.plan_payload = PrecomputeManifest(
            runId="cli-site01-test",
            createdAtUtc="2026-11-14T12:00:00Z",
            status="incomplete",
            jobs=jobs,
        ).model_dump()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = self.root / "plan with spaces.json"
        self.plan.write_text(json.dumps(self.plan_payload), encoding="utf-8")
        self.output = self.root / "bundle with spaces"

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(arg) for arg in args])
        return code, stdout.getvalue(), stderr.getvalue()

    def generate(self, *extra, reference=REFERENCE / "validation-30d", output=None):
        return self.invoke(
            "generate",
            self.plan,
            "--reference-dir",
            reference,
            "--output",
            self.output if output is None else output,
            *extra,
        )

    def test_real_generate_and_verify_are_offline_and_print_json_summaries(self):
        original_plan = self.plan.read_bytes()
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No NASA")),
            patch("lunarwindow.terrain.download.urlopen", side_effect=AssertionError("No DEM")),
        ):
            code, stdout, stderr = self.generate()
            self.assertEqual(code, 0, stderr)
            summary = json.loads(stdout)
            self.assertEqual(
                summary,
                {
                    "command": "generate",
                    "status": "complete",
                    "runId": "cli-site01-test",
                    "jobCount": 2,
                    "manifest": str(self.output / "manifest.json"),
                },
            )
            self.assertEqual(stderr, "")
            before = {p.name: p.read_bytes() for p in self.output.iterdir()}
            with patch(
                "lunarwindow.api.reference_provider.calculate_visibility",
                side_effect=AssertionError("Verification must not calculate"),
            ):
                code, stdout, stderr = self.invoke(
                    "verify", self.output, "--reference-dir", REFERENCE / "validation-30d"
                )
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout), summary | {"command": "verify"})
            self.assertEqual(stderr, "")
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        self.assertEqual(self.plan.read_bytes(), original_plan)

    def test_invalid_malformed_or_non_pending_plans_fail_without_output_writes(self):
        failed = copy.deepcopy(self.plan_payload)
        failed["jobs"][0].update(status="failed", error="Previously failed.")
        duplicate = copy.deepcopy(self.plan_payload)
        duplicate["jobs"].append(duplicate["jobs"][0])
        completed = copy.deepcopy(self.plan_payload)
        completed.update(status="complete", completedAtUtc="2026-11-14T12:01:00Z")
        for job in completed["jobs"]:
            key = ReferenceEvaluationCacheKey.model_validate(job["evaluation"])
            job.update(
                status="complete",
                output={
                    "filename": f"{key.digest}.json",
                    "sha256": "0" * 64,
                    "responseSchemaVersion": "lunarwindow.reference-evaluation.v2"
                    if key.horizonMode == "terrain"
                    else "lunarwindow.reference-evaluation.v1",
                },
            )
        for payload in (
            b"not json",
            b"{}",
            json.dumps(failed).encode(),
            json.dumps(duplicate).encode(),
            json.dumps(completed).encode(),
        ):
            self.plan.write_bytes(payload)
            with self.subTest(payload=payload[:40]):
                code, stdout, stderr = self.generate()
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertIn("Precompute generate failed:", stderr)
                self.assertNotIn("Traceback", stderr)
                self.assertFalse(self.output.exists())

    def test_missing_plan_returns_failure_without_creating_output(self):
        self.plan.unlink()
        code, stdout, stderr = self.generate()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("failed", stderr)
        self.assertFalse(self.output.exists())

    def test_generation_failure_returns_one_and_reports_retained_checkpoint_and_cause(self):
        code, stdout, stderr = self.generate(reference=self.root / "missing reference")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("incomplete manifest retained", stderr)
        self.assertIn("Cause:", stderr)
        self.assertNotIn("Traceback", stderr)
        manifest = PrecomputeManifest.model_validate_json(
            (self.output / "manifest.json").read_bytes()
        )
        self.assertEqual(manifest.status, "incomplete")
        self.assertEqual([j.status for j in manifest.jobs], ["failed", "pending"])

    def test_existing_output_is_preserved_and_returns_failure(self):
        self.output.mkdir()
        sentinel = self.output / "existing.txt"
        sentinel.write_bytes(b"keep this")
        code, stdout, stderr = self.generate()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("failed", stderr)
        self.assertEqual(sentinel.read_bytes(), b"keep this")
        self.assertEqual([p.name for p in self.output.iterdir()], ["existing.txt"])

    def test_missing_or_corrupt_bundles_return_failure_without_success_output(self):
        code, stdout, stderr = self.invoke(
            "verify", self.output, "--reference-dir", REFERENCE / "validation-30d"
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Precompute verify failed:", stderr)
        self.assertEqual(self.generate()[0], 0)
        manifest = PrecomputeManifest.model_validate_json(
            (self.output / "manifest.json").read_bytes()
        )
        (self.output / manifest.jobs[1].output.filename).write_bytes(b"broken")
        code, stdout, stderr = self.invoke(
            "verify", self.output, "--reference-dir", REFERENCE / "validation-30d"
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("checksum mismatch", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_explicit_archive_and_terrain_directories_are_honored_by_both_commands(self):
        archive = self.root / "custom archive"
        terrain = self.root / "custom terrain"
        shutil.copytree(REFERENCE / "validation-30d", archive)
        shutil.copytree(REFERENCE / "terrain-masks", terrain)
        code, _, stderr = self.generate("--terrain-dir", terrain, reference=archive)
        self.assertEqual(code, 0, stderr)
        code, _, stderr = self.invoke(
            "verify", self.output, "--reference-dir", archive, "--terrain-dir", terrain
        )
        self.assertEqual(code, 0, stderr)
        code, stdout, stderr = self.invoke(
            "verify",
            self.output,
            "--reference-dir",
            archive,
            "--terrain-dir",
            self.root / "missing masks",
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("failed", stderr)

    def test_argparse_help_and_usage_errors_use_standard_exit_codes(self):
        for arguments, expected in (
            (["--help"], 0),
            (["generate", "--help"], 0),
            (["verify", "--help"], 0),
            ([], 2),
            (["unknown"], 2),
            (["generate", str(self.plan)], 2),
            (["verify", str(self.output)], 2),
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                self.subTest(arguments=arguments),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as exit:
                    main(arguments)
                self.assertEqual(exit.exception.code, expected)
            self.assertFalse(self.output.exists())

    def test_interruption_uses_exit_code_130_and_no_success_output(self):
        with patch("lunarwindow.precompute.cli.generate_bundle", side_effect=KeyboardInterrupt):
            code, stdout, stderr = self.generate()
        self.assertEqual(code, 130)
        self.assertEqual(stdout, "")
        self.assertIn("interrupted", stderr)
        with patch("lunarwindow.precompute.cli.verify_bundle", side_effect=KeyboardInterrupt):
            code, stdout, stderr = self.invoke(
                "verify", self.output, "--reference-dir", REFERENCE / "validation-30d"
            )
        self.assertEqual(code, 130)
        self.assertEqual(stdout, "")

    def test_python_module_entrypoint_help_and_failure_exit_codes(self):
        for arguments, expected in (
            (["--help"], 0),
            (["verify", str(self.output), "--reference-dir", str(REFERENCE / "validation-30d")], 1),
        ):
            result = subprocess.run(
                [sys.executable, "-m", "lunarwindow.precompute", *arguments],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            with self.subTest(arguments=arguments):
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected == 0:
                    self.assertIn("generate", result.stdout)
                    self.assertIn("verify", result.stdout)
                else:
                    self.assertEqual(result.stdout, "")
                    self.assertIn("Precompute verify failed:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
