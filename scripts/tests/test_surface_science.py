"""Independent comparisons must fail honestly and never promote camera/average data."""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

DIRECTORY = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(DIRECTORY), *sys.path]):
    SPEC = importlib.util.spec_from_file_location(
        "surface_science", DIRECTORY / "validate_surface_science.py"
    )
    science = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(science)


class PointingTests(unittest.TestCase):
    def test_invalid_screening_criteria_and_modified_kernels_are_rejected(self):
        generator = sys.modules["build_surface_spice_reference"]
        config = json.loads(generator.INPUTS.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs.json"
            for value in (float("nan"), float("inf"), 0, -1, True):
                changed = copy.deepcopy(config)
                changed["criteria"]["pointingToleranceDeg"] = value
                inputs.write_text(json.dumps(changed))
                with (
                    self.subTest(value=value),
                    self.assertRaisesRegex(ValueError, "finite positive"),
                ):
                    generator.read_inputs(inputs)
            kernel = config["kernels"][0]
            (root / kernel["filename"]).write_bytes(b"x" * kernel["sizeBytes"])
            with (
                patch.dict(sys.modules, {"spiceypy": object()}),
                patch("importlib.metadata.version", return_value="8.0.0"),
                self.assertRaisesRegex(ValueError, "kernel differs"),
            ):
                generator.build(root)

    def test_changed_oracle_observer_is_rejected_even_with_a_new_file_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "oracle.json"
            pin = Path(directory) / "oracle.sha256"
            body = json.loads(science.REFERENCE.read_text())
            body["sites"][0]["observer"]["mastHeightM"] = 2
            reference.write_text(json.dumps(body))
            pin.write_text(science.sha256(reference))
            with self.assertRaisesRegex(ValueError, "observer"):
                science.validate(reference=reference, reference_hash=pin)

    def row(self, **changes):
        return {
            "t": "2026-11-14T00:00:00Z",
            "sunAz": 359.9999,
            "sunEl": 1.0,
            "earthAz": 90.0,
            "earthEl": -1.0,
            "sunAngularRadiusDeg": 0.25,
            "earthAngularRadiusDeg": 1.0,
            **changes,
        }

    def test_wrapped_azimuth_and_angular_radius_use_separate_criteria(self):
        criteria = {"pointingToleranceDeg": 0.001, "angularRadiusToleranceDeg": 0.00001}
        actual, expected = self.row(), self.row(sunAz=0.0001)
        result = science.pointing_comparison([actual], [expected], criteria)
        self.assertEqual(result["failedComparisons"], 0)
        self.assertAlmostEqual(
            result["quantities"]["sunAz"]["maxAbsDifferenceDeg"], 0.0002
        )
        result = science.pointing_comparison(
            [self.row(sunAngularRadiusDeg=0.25002)], [expected], criteria
        )
        self.assertEqual(result["failedComparisons"], 1)
        result = science.pointing_comparison(
            [self.row(sunEl=1.01)], [expected], criteria
        )
        self.assertEqual(result["status"], "fail")

    def test_nan_missing_samples_and_observer_time_changes_cannot_pass(self):
        for actual, expected in (
            ([], []),
            ([self.row()], []),
            ([self.row(t="2026-11-14T01:00:00Z")], [self.row()]),
            ([self.row(sunEl=float("nan"))], [self.row()]),
            ([self.row()], [self.row(earthAz=360)]),
            ([self.row()], [self.row(sunEl=True)]),
        ):
            with (
                self.subTest(actual=actual, expected=expected),
                self.assertRaises(ValueError),
            ):
                list(science.checked_rows(actual, expected))

    def test_independent_horizon_interpolation_covers_seam_and_limb_rules(self):
        profile = [{"az": az, "el": 0.0} for az in range(360)]
        profile[359]["el"] = 2
        self.assertEqual(science.horizon_at(profile, 359.5), 1)
        self.assertEqual(science.horizon_at(profile, -0.5), 1)
        row = self.row(sunAz=90, sunEl=0)
        self.assertEqual(science.clearance(row, "sun", profile, "any-disc"), 0.25)
        self.assertEqual(science.clearance(row, "sun", profile, "body-center"), 0)
        self.assertEqual(science.clearance(row, "sun", profile, "full-disc"), -0.25)

    def test_pinned_replay_is_explicitly_partial_without_external_terrain(self):
        report, requests = science.validate()
        self.assertEqual(report["status"], "partial-pending-terrain-evidence")
        self.assertFalse(report["independentTerrainValidationComplete"])
        self.assertEqual(
            sum(item["samples"] for item in report["surfacePointing"]), 2160
        )
        self.assertEqual(
            sum(item["angleComparisons"] for item in report["surfacePointing"]), 12960
        )
        self.assertTrue(
            all(item["flagMismatches"] == 0 for item in report["modelConsistency"])
        )
        self.assertEqual(len(requests["cases"]), 4)
        self.assertTrue(
            all(item["referenceMeasurement"] is None for item in requests["cases"])
        )

    def test_empty_or_modified_oracle_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            pin = Path(directory) / "oracle.sha256"
            for text in ("", "0" * 64, "g" * 64):
                pin.write_text(text)
                with (
                    self.subTest(text=text),
                    self.assertRaisesRegex(ValueError, "checksum"),
                ):
                    science.validate(reference_hash=pin)

    def test_strict_completion_gate_reports_missing_evidence_without_false_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with (
                patch.object(
                    science,
                    "validate",
                    return_value=(
                        {
                            "status": "partial-pending-terrain-evidence",
                            "independentTerrainValidationComplete": False,
                        },
                        {},
                    ),
                ),
                patch("sys.stdout"),
            ):
                code = science.main(
                    ["--output", str(output), "--require-terrain-evidence"]
                )
            self.assertEqual(code, 2)
            self.assertFalse(
                json.loads(output.read_text())["independentTerrainValidationComplete"]
            )


class ExternalTerrainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "evidence").mkdir()
        path = self.root / "evidence" / "synthetic-test-only.txt"
        path.write_text(
            "Synthetic unit-test artifact; no scientific measurement is claimed."
        )
        self.record = {
            "caseId": "test-only",
            "siteId": "test-site",
            "timestampUtc": "2026-11-14T00:00:00Z",
            "body": "sun",
            "visible": True,
            "observerKind": "surface",
            "observer": {
                "lat": -89.0,
                "lon": 0.0,
                "altitudeKm": 0.1,
                "surfaceElevationM": 100.0,
                "mastHeightM": 0.0,
            },
            "quantity": "terrain-visibility-at-observer",
            "visibilityRule": "any-disc",
            "bodyDefinition": "finite-disc-any-part",
            "refractionModel": "none",
            "referenceFrame": "MOON_ME_DE421",
            "referenceRadiusKm": 1737.4,
            "sourceType": "dated-terrain-simulation",
            "sourceUrl": "https://example.invalid/synthetic-test",
            "sourceVersion": "synthetic-test",
            "method": "Synthetic test protocol, not a real measurement.",
            "demDescription": "Synthetic test data only.",
            "frameAssessment": "Synthetic test frame assessment only.",
            "independenceStatement": "Synthetic test attestation; not actual external evidence.",
            "independentOfLunarWindow": True,
            "evidencePath": "evidence/synthetic-test-only.txt",
            "evidenceSha256": science.sha256(path),
            "reviewer": "Test reviewer",
            "reviewedAtUtc": "2026-11-15T00:00:00Z",
            "reviewNotes": "Synthetic unit-test review; not a scientific approval.",
        }
        self.datasets = {
            "test-site": {
                "siteId": "test-site",
                "lat": -89.0,
                "lon": 0.0,
                "altitudeKm": 0.1,
            }
        }
        self.states = {
            "test-site": {
                "2026-11-14T00:00:00Z": {"sun": True, "earth": False},
                "2026-11-14T01:00:00Z": {"sun": False, "earth": True},
            }
        }

    def assess(self, records):
        return science.assess_terrain_evidence(
            {
                "schemaVersion": "lunarwindow.terrain-observations.v1",
                "observations": records,
            },
            self.datasets,
            self.states,
            self.root,
        )

    def test_camera_average_self_derived_and_mismatched_observers_are_rejected(self):
        changes = [
            {"observerKind": "camera"},
            {"sourceType": "long-term-average"},
            {"independentOfLunarWindow": False},
            {"quantity": "center-elevation"},
            {"referenceFrame": "IAU_MOON"},
            {"visible": "true"},
            {"timestampUtc": "2026-11-14T00:30:00Z"},
            {"observer": {**self.record["observer"], "mastHeightM": 2.0}},
            {"evidenceSha256": "0" * 64},
            {"evidencePath": "../outside.txt"},
        ]
        for change in changes:
            with (
                self.subTest(change=change),
                self.assertRaises((ValueError, ValidationError)),
            ):
                self.assess([{**self.record, **change}])

    def test_reviewed_mismatches_and_incomplete_coverage_stay_visible(self):
        result = self.assess([self.record])
        self.assertEqual(result["status"], "incomplete-coverage")
        self.assertFalse(result["coverageComplete"])
        wrong = {**self.record, "visible": False}
        self.assertEqual(self.assess([wrong])["status"], "fail")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.assess([self.record, self.record])

    def test_all_four_reviewed_states_are_required_for_recorded_case_completion(self):
        records = []
        for body in ("sun", "earth"):
            for hour, visible in ((0, body == "sun"), (1, body == "earth")):
                record = copy.deepcopy(self.record)
                record.update(
                    caseId=f"test-{body}-{hour}",
                    body=body,
                    visible=visible,
                    timestampUtc=f"2026-11-14T0{hour}:00:00Z",
                )
                records.append(record)
        result = self.assess(records)
        self.assertEqual(result["status"], "pass-recorded-cases")
        self.assertEqual(len(result["comparisons"]), 4)
        self.assertTrue(result["coverageComplete"])
