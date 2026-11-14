"""Pinned demo coverage, release closure, reproducible payloads, and publication errors."""

import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from lunarwindow.precompute import PrecomputeGenerationError, PrecomputeManifest
from lunarwindow.precompute.release import build_release, main, verify_release
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
RELEASE = REFERENCE.parent / "releases/lunarwindow-demo-v1"


class DataReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def copy_release(self, name="release"):
        return Path(shutil.copytree(RELEASE, self.root / name))

    def test_shipped_release_pins_the_four_default_demo_jobs_and_source_observers(self):
        manifest = verify_release(RELEASE, reference_directory=REFERENCE / "validation-30d")
        self.assertEqual(manifest.runId, "lunarwindow-demo-v1")
        self.assertEqual(len(manifest.jobs), 4)
        self.assertEqual(
            [(job.evaluation.siteId, job.evaluation.horizonMode) for job in manifest.jobs],
            [
                ("lola-site01-reference", "geometric"),
                ("lola-site04-reference", "geometric"),
                ("lola-site23-reference", "geometric"),
                ("lola-site01-reference", "terrain"),
            ],
        )
        expected_hashes = {
            "lola-site01-reference": "519628d7384992cc012039fe9df226a932d6c482de56b0b3277fdff6f30e9b50",
            "lola-site04-reference": "fa9b4e639709be80d49274895aaff003da8233e2b5644de67d372e43e3cee470",
            "lola-site23-reference": "d6b6e13763f9ce645d87744f872ab754944c4fa87c2027c52b1bc0c2f28698aa",
        }
        for job in manifest.jobs:
            key = job.evaluation
            self.assertEqual(key.ephemerisSha256, expected_hashes[key.siteId])
            self.assertEqual(key.calculationModelVersion, VISIBILITY_MODEL_VERSION)
            self.assertEqual(
                (key.startUtc, key.endUtc), ("2026-11-14T00:00:00Z", "2026-12-14T00:00:00Z")
            )
            self.assertEqual(key.stepMinutes, 60)
            self.assertEqual(key.visibilityRule, "any-disc")
            self.assertEqual(key.asOfUtc, key.startUtc)
        terrain = manifest.jobs[-1]
        self.assertEqual(
            terrain.evaluation.terrainMaskSha256,
            "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d",
        )
        self.assertTrue(terrain.evaluation.allowMeanEarthApproximation)
        result = json.loads((RELEASE / "bundle" / terrain.output.filename).read_bytes())
        provenance = result["provenance"]["terrain"]
        self.assertEqual(provenance["mask"]["observer"]["mastHeightM"], 0)
        self.assertEqual(provenance["compatibility"]["frameStatus"], "approximate")
        self.assertFalse(provenance["compatibility"]["transformationApplied"])

    def test_check_cli_rebuilds_identical_payloads_without_modifying_the_release(self):
        before = {
            str(p.relative_to(RELEASE)): p.read_bytes() for p in RELEASE.rglob("*") if p.is_file()
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                ["check", str(RELEASE), "--reference-dir", str(REFERENCE / "validation-30d")]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["jobCount"], 4)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            before,
            {
                str(p.relative_to(RELEASE)): p.read_bytes()
                for p in RELEASE.rglob("*")
                if p.is_file()
            },
        )

    def test_build_creates_a_verified_release_and_refuses_overwrite(self):
        output = self.root / "new-release"
        manifest = build_release(
            RELEASE / "plan.json",
            output_directory=output,
            reference_directory=REFERENCE / "validation-30d",
        )
        self.assertEqual(
            verify_release(output, reference_directory=REFERENCE / "validation-30d"), manifest
        )
        self.assertEqual((output / "plan.json").read_bytes(), (RELEASE / "plan.json").read_bytes())
        original = PrecomputeManifest.model_validate_json(
            (RELEASE / "bundle/manifest.json").read_bytes()
        )
        self.assertEqual(
            manifest.model_dump(exclude={"createdAtUtc", "completedAtUtc"}),
            original.model_dump(exclude={"createdAtUtc", "completedAtUtc"}),
        )
        before = (output / "SHA256SUMS").read_bytes()
        with self.assertRaises(FileExistsError):
            build_release(
                RELEASE / "plan.json",
                output_directory=output,
                reference_directory=REFERENCE / "validation-30d",
            )
        self.assertEqual((output / "SHA256SUMS").read_bytes(), before)

    def test_changed_plan_manifest_or_payload_fails_release_verification(self):
        original = PrecomputeManifest.model_validate_json(
            (RELEASE / "bundle/manifest.json").read_bytes()
        )
        for index, name in enumerate(
            ("plan.json", "bundle/manifest.json", f"bundle/{original.jobs[0].output.filename}")
        ):
            copied = self.copy_release(f"changed-{index}")
            path = copied / name
            path.write_bytes(path.read_bytes() + b"\n")
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_release(copied, reference_directory=REFERENCE / "validation-30d")

    def test_checksum_inventory_cannot_omit_duplicate_or_escape_artifacts(self):
        for index, change in enumerate(("missing", "duplicate", "escape", "invalid-hash")):
            copied = self.copy_release(f"inventory-{index}")
            path = copied / "SHA256SUMS"
            rows = path.read_text(encoding="utf-8").splitlines()
            if change == "missing":
                rows.pop()
            elif change == "duplicate":
                rows.append(rows[0])
            elif change == "escape":
                rows[0] = "0" * 64 + "  ../../outside.json"
            else:
                rows[0] = "X" * 64 + "  " + rows[0].split("  ", 1)[1]
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_release(copied, reference_directory=REFERENCE / "validation-30d")

    def test_rehashed_plan_cannot_describe_different_jobs_or_run_identity(self):
        for index, change in enumerate(("order", "run-id")):
            copied = self.copy_release(f"plan-{index}")
            path = copied / "plan.json"
            plan = json.loads(path.read_bytes())
            if change == "order":
                plan["jobs"].reverse()
            else:
                plan["runId"] = "another-release"
            path.write_text(json.dumps(plan), encoding="utf-8")
            inventory = copied / "SHA256SUMS"
            rows = inventory.read_text(encoding="utf-8").splitlines()
            rows = [
                hashlib.sha256(path.read_bytes()).hexdigest() + "  plan.json"
                if row.endswith("  plan.json")
                else row
                for row in rows
            ]
            inventory.write_text("\n".join(rows) + "\n", encoding="utf-8")
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_release(copied, reference_directory=REFERENCE / "validation-30d")

    def test_failed_build_retains_diagnostics_without_a_release_completion_inventory(self):
        plan = json.loads((RELEASE / "plan.json").read_bytes())
        plan["jobs"][0]["evaluation"]["ephemerisSha256"] = "0" * 64
        path = self.root / "stale-plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        output = self.root / "failed-release"
        with self.assertRaises(PrecomputeGenerationError):
            build_release(
                path, output_directory=output, reference_directory=REFERENCE / "validation-30d"
            )
        self.assertFalse((output / "SHA256SUMS").exists())
        manifest = PrecomputeManifest.model_validate_json(
            (output / "bundle/manifest.json").read_bytes()
        )
        self.assertEqual(manifest.status, "incomplete")
        self.assertEqual(manifest.jobs[0].status, "failed")

    def test_verify_cli_errors_are_nonzero_with_no_success_output(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "verify",
                    str(self.root / "missing"),
                    "--reference-dir",
                    str(REFERENCE / "validation-30d"),
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Data release verify failed:", stderr.getvalue())
