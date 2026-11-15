"""Read-only GIS handoff checks do not promote compatible files to reviewed artifacts."""

import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from lunarwindow.terrain.handoff import main, verify_candidate, verify_registered
from lunarwindow.terrain.registry import reviewed_mask_ids

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
SITE = "lola-site01-reference"
MASK_ID = f"{SITE}-mast-0m"
MASK = REFERENCE / "terrain-masks" / f"{MASK_ID}.json"
SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"


class TerrainHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def verify(self, path=MASK, checksum=SHA256, **options):
        return verify_candidate(
            path,
            expected_sha256=checksum,
            expected_site_id=options.pop("site_id", SITE),
            reference_directory=options.pop("reference_directory", REFERENCE / "validation-30d"),
            allow_mean_earth_approximation=options.pop("allow", True),
        )

    def test_report_preserves_matching_observer_sources_and_pinned_ephemeris_bytes_offline(self):
        before = MASK.read_bytes()
        registrations = reviewed_mask_ids()
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch(
                "lunarwindow.visibility.calculate_visibility", side_effect=AssertionError("No run")
            ),
            patch.object(Path, "write_bytes", side_effect=AssertionError("No writes")),
            patch.object(Path, "write_text", side_effect=AssertionError("No writes")),
        ):
            report = self.verify()
        payload = json.loads(before)
        self.assertEqual(report["schemaVersion"], "lunarwindow.terrain-handoff.v1")
        self.assertEqual(report["status"], "compatible")
        self.assertEqual(report["artifactSha256"], SHA256)
        self.assertEqual(report["observer"], payload["observer"])
        self.assertEqual(report["referenceFrame"], payload["referenceFrame"])
        self.assertEqual(report["demSources"], payload["provenance"]["sources"])
        self.assertEqual(report["algorithm"], payload["provenance"]["algorithm"])
        archive = REFERENCE / "validation-30d" / f"{SITE}.json"
        self.assertEqual(
            report["ephemeris"]["artifactSha256"], hashlib.sha256(archive.read_bytes()).hexdigest()
        )
        self.assertEqual(report["ephemeris"]["sampleCount"], 720)
        self.assertTrue(report["ephemeris"]["endExclusive"])
        self.assertEqual(report["compatibility"]["frameStatus"], "approximate")
        self.assertFalse(report["compatibility"]["transformationApplied"])
        self.assertIn("do not review DEM quality", report["limitation"])
        self.assertEqual(MASK.read_bytes(), before)
        self.assertEqual(reviewed_mask_ids(), registrations)

    def test_default_policy_and_wrong_expected_identity_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "explicit"):
            verify_candidate(
                MASK,
                expected_sha256=SHA256,
                expected_site_id=SITE,
                reference_directory=REFERENCE / "validation-30d",
            )
        for site_id in ("lola-site04-reference", "../outside", "Bad ID"):
            with self.subTest(site_id=site_id), self.assertRaises(ValueError):
                self.verify(site_id=site_id)

    def test_matching_contract_cannot_hide_wrong_height_frame_or_missing_archive(self):
        for damage in ("height", "latitude", "frame", "unknown-site"):
            payload = json.loads(MASK.read_bytes())
            site_id = SITE
            if damage == "height":
                payload["observer"]["mastHeightM"] = 2
                payload["observer"]["altitudeKm"] += 0.002
            elif damage == "latitude":
                payload["observer"]["lat"] += 0.001
            elif damage == "frame":
                payload["referenceFrame"]["realization"] = "unreviewed frame"
            else:
                site_id = payload["siteId"] = "missing-site"
            path = self.root / f"{damage}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(damage=damage), self.assertRaises((ValueError, LookupError)):
                self.verify(path, hashlib.sha256(path.read_bytes()).hexdigest(), site_id=site_id)

    def test_changed_mask_and_self_rehashed_sidecar_do_not_replace_trusted_checksum(self):
        path = self.root / MASK.name
        path.write_bytes(MASK.read_bytes() + b"\n")
        path.with_suffix(".json.sha256").write_text(
            hashlib.sha256(path.read_bytes()).hexdigest(), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.verify(path)

    def test_whole_archive_is_verified_even_when_another_site_is_corrupted(self):
        directory = Path(shutil.copytree(REFERENCE / "validation-30d", self.root / "archive"))
        path = directory / "lola-site23-reference.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            self.verify(reference_directory=directory)

    def test_registered_verification_rejects_orphan_and_missing_registrations(self):
        reports = verify_registered(
            REFERENCE / "validation-30d",
            REFERENCE / "terrain-masks",
            allow_mean_earth_approximation=True,
        )
        self.assertEqual([report["maskId"] for report in reports], list(reviewed_mask_ids()))
        with self.assertRaises(ValueError):
            verify_registered(
                REFERENCE / "validation-30d", self.root, allow_mean_earth_approximation=True
            )
        payload = json.loads(MASK.read_bytes())
        payload["siteId"] = "missing-site"
        payload["maskId"] = "missing-site-mast-0m"
        path = self.root / "orphan.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        registrations = {
            payload["maskId"]: (
                payload["siteId"],
                path.name,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        }
        with (
            patch("lunarwindow.terrain.registry._MASKS", registrations),
            self.assertRaises(LookupError),
        ):
            verify_registered(
                REFERENCE / "validation-30d", self.root, allow_mean_earth_approximation=True
            )

    def test_cli_outputs_json_only_on_success_and_returns_nonzero_on_failure(self):
        commands = [
            ["candidate", str(MASK), "--site-id", SITE, "--expected-sha256", SHA256],
            ["registered", "--terrain-dir", str(REFERENCE / "terrain-masks")],
        ]
        for command in commands:
            arguments = command + ["--reference-dir", str(REFERENCE / "validation-30d")]
            for accepted in (False, True):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(
                        arguments + (["--allow-mean-earth-approximation"] if accepted else [])
                    )
                with self.subTest(command=command[0], accepted=accepted):
                    self.assertEqual(code, 0 if accepted else 1)
                    if accepted:
                        self.assertEqual(json.loads(stdout.getvalue())["status"], "compatible")
                        self.assertEqual(stderr.getvalue(), "")
                    else:
                        self.assertEqual(stdout.getvalue(), "")
                        self.assertIn("Terrain handoff", stderr.getvalue())
