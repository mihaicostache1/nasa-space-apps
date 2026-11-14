"""Contract-only checks using an archived three-hour NASA ephemeris fixture."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from lunarwindow.api.reference_models import ReferenceEvaluation, ReferenceEvaluationRequest

FIXTURE = Path(__file__).parent / "fixtures/dataset.json"


class ReferenceEvaluationContractTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source = self.dataset["provenance"]
        # The three observations have Sun fully above and Earth below a zero
        # horizon. This fixture does not run or connect the calculation engine.
        window = {
            "startUtc": source["startUtc"],
            "endUtc": source["endUtc"],
            "durationHrs": 3.0,
            "startTruncated": True,
            "endTruncated": True,
        }
        self.payload = {
            "horizonMode": "geometric",
            **{
                key: self.dataset[key]
                for key in ("siteId", "site", "lat", "lon", "altitudeKm", "coordinateSource")
            },
            "horizon": [{"az": az, "el": 0.0} for az in range(360)],
            "series": [
                row
                | {
                    "sunHorizonEl": 0.0,
                    "earthHorizonEl": 0.0,
                    "sunVisibility": "full",
                    "earthVisibility": "hidden",
                    "sunLit": True,
                    "earthVis": False,
                }
                for row in self.dataset["series"]
            ],
            "metrics": {
                "evaluatedHrs": 3.0,
                "sunlitHrs": 3.0,
                "earthVisibleHrs": 0.0,
                "bothHrs": 0.0,
                "pctSun": 100.0,
                "pctEarth": 0.0,
                "pctBoth": 0.0,
                "longestDarkHrs": 0.0,
                "longestEarthBlackoutHrs": 3.0,
                "longestBothHrs": 0.0,
                "asOfUtc": source["startUtc"],
                "nextSunset": None,
                "nextEarthset": None,
                "hoursToSunset": None,
                "hoursToEarthset": None,
                "nextSunsetBracket": None,
                "nextEarthsetBracket": None,
            },
            "windows": {
                "sunlit": [copy.deepcopy(window)],
                "earthVisible": [],
                "both": [],
                "darkness": [],
                "earthBlackout": [copy.deepcopy(window)],
            },
            "calculation": {"visibilityRule": "any-disc", "stepMinutes": 60},
            "provenance": {
                "ephemeris": copy.deepcopy(source),
                "archive": {
                    "startUtc": source["startUtc"],
                    "endUtc": source["endUtc"],
                    "endExclusive": True,
                    "stepMinutes": 60,
                    "sampleCount": 3,
                },
            },
        }
        self.request = {
            "siteId": "lola-site01-reference",
            "horizonMode": "geometric",
            "startUtc": source["startUtc"],
            "endUtc": source["endUtc"],
        }

    def test_request_requires_a_site_and_explicit_geometric_mode(self):
        request = ReferenceEvaluationRequest.model_validate(self.request)
        self.assertEqual(request.siteId, "lola-site01-reference")
        self.assertEqual(request.stepMinutes, 60)
        self.assertEqual(request.visibilityRule, "any-disc")
        self.assertIsNone(request.asOfUtc)
        invalid = [
            {key: value for key, value in self.request.items() if key != "horizonMode"},
            self.request | {"horizonMode": "terrain"},
            self.request | {"siteId": "../site"},
            self.request | {"location": {"latitudeDeg": -89, "longitudeDeg": 0, "altitudeKm": 0}},
            self.request | {"asOfUtc": self.request["endUtc"]},
            self.request | {"endUtc": self.request["startUtc"]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                ReferenceEvaluationRequest.model_validate(payload)

    def test_response_round_trip_retains_source_evidence_and_explicit_model_labels(self):
        response = ReferenceEvaluation.model_validate(self.payload)
        self.assertEqual(response.schemaVersion, "lunarwindow.reference-evaluation.v1")
        self.assertEqual(response.dataMode, "reference")
        self.assertEqual(response.horizonMode, "geometric")
        self.assertEqual(response.provenance.ephemeris, self.dataset["provenance"])
        self.assertIn("flat 0-degree horizon", response.provenance.warning)
        self.assertEqual(
            ReferenceEvaluation.model_validate_json(response.model_dump_json()).model_dump(),
            response.model_dump(),
        )
        schema = ReferenceEvaluation.model_json_schema()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(response.model_dump())
        self.assertEqual(schema["properties"]["dataMode"]["const"], "reference")

    def test_synthetic_labels_and_missing_or_invalid_nasa_evidence_are_rejected(self):
        for overrides in (
            {"dataMode": "synthetic"},
            {"schemaVersion": "lunarwindow.evaluation.v2"},
            {"horizonMode": "terrain"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                ReferenceEvaluation.model_validate(self.payload | overrides)
        for overrides in (
            {"provider": "LunarWindow deterministic demo generator"},
            {"terrainModel": "synthetic"},
            {"requests": []},
        ):
            payload = copy.deepcopy(self.payload)
            payload["provenance"]["ephemeris"].update(overrides)
            with self.subTest(provenance=overrides), self.assertRaises(ValidationError):
                ReferenceEvaluation.model_validate(payload)
        payload = copy.deepcopy(self.payload)
        del payload["provenance"]["ephemeris"]["requests"][0]["responseSha256"]
        with self.assertRaises(ValidationError):
            ReferenceEvaluation.model_validate(payload)

    def test_nonzero_or_unordered_geometric_horizons_are_rejected(self):
        for field in ("mask", "order", "sample"):
            payload = copy.deepcopy(self.payload)
            if field == "mask":
                payload["horizon"][0]["el"] = 1
            elif field == "order":
                payload["horizon"][0]["az"] = 1
            else:
                payload["series"][0]["sunHorizonEl"] = 1
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ReferenceEvaluation.model_validate(payload)

    def test_mismatched_grid_coverage_calculation_and_metrics_are_rejected(self):
        for field in (
            "archive-count",
            "archive-end",
            "archive-grid",
            "step",
            "selected-time",
            "duration",
            "timestamp",
            "observer",
        ):
            payload = copy.deepcopy(self.payload)
            if field == "archive-count":
                payload["provenance"]["archive"]["sampleCount"] = 2
            elif field == "archive-end":
                payload["provenance"]["archive"] |= {
                    "endUtc": "2026-11-14T02:00:00Z",
                    "sampleCount": 2,
                }
            elif field == "archive-grid":
                payload["provenance"]["archive"] |= {"stepMinutes": 120, "sampleCount": 2}
            elif field == "step":
                payload["calculation"]["stepMinutes"] = 120
            elif field == "selected-time":
                payload["metrics"]["asOfUtc"] = payload["provenance"]["ephemeris"]["endUtc"]
            elif field == "duration":
                payload["metrics"]["evaluatedHrs"] = 24
            elif field == "timestamp":
                payload["series"][1]["t"] = payload["series"][0]["t"]
            else:
                payload["lat"] = -88
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ReferenceEvaluation.model_validate(payload)
