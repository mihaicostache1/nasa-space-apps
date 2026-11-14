"""End-to-end geometric evaluation of the committed real ephemeris archive."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app, get_reference_directory
from lunarwindow.api.reference_models import ReferenceEvaluation
from lunarwindow.ephemeris.models import TimeRange, iso_utc, parse_utc
from lunarwindow.visibility import calculate_visibility

REFERENCE = (
    Path(
        os.environ.get(
            "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
        )
    )
    / "validation-30d"
)
ENDPOINT = "/api/reference/evaluations"
REQUEST = {
    "siteId": "lola-site23-reference",
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-12-14T00:00:00Z",
    "stepMinutes": 60,
}


class ReferenceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: REFERENCE
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.source = json.loads(
            (REFERENCE / f"{REQUEST['siteId']}.json").read_text(encoding="utf-8")
        )

    def test_real_api_results_match_the_engine_on_exact_archived_samples(self):
        with (
            patch(
                "lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No network")
            ),
            patch(
                "lunarwindow.api.demo.DemoProvider.evaluate", side_effect=AssertionError("No demo")
            ),
        ):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200)
        actual = ReferenceEvaluation.model_validate(response.json())
        expected = calculate_visibility(
            self.source["series"],
            [{"az": az, "el": 0.0} for az in range(360)],
            TimeRange(REQUEST["startUtc"], REQUEST["endUtc"], 60),
        )
        self.assertEqual(actual.series, expected.series)
        self.assertEqual(actual.metrics, expected.metrics)
        self.assertEqual(actual.windows, expected.windows)
        self.assertEqual(actual.calculation, expected.calculation)
        self.assertEqual(actual.provenance.ephemeris, self.source["provenance"])
        self.assertEqual(actual.dataMode, "reference")
        self.assertEqual(actual.horizonMode, "geometric")
        self.assertTrue(all(point.el == 0 for point in actual.horizon))
        self.assertEqual(actual.provenance.archive.sampleCount, 720)

    def test_selection_coarser_step_and_short_final_interval_keep_original_archive_coverage(self):
        request = REQUEST | {
            "startUtc": "2026-11-15T01:00:00Z",
            "endUtc": "2026-11-15T06:30:00Z",
            "stepMinutes": 120,
        }
        response = self.client.post(ENDPOINT, json=request)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            [row["t"] for row in data["series"]],
            [row["t"] for row in self.source["series"][25:31:2]],
        )
        self.assertEqual(data["metrics"]["evaluatedHrs"], 5.5)
        self.assertEqual(data["calculation"]["stepMinutes"], 120)
        self.assertEqual(
            data["provenance"]["ephemeris"],
            self.source["provenance"]
            | {key: request[key] for key in ("startUtc", "endUtc", "stepMinutes")},
        )
        self.assertEqual(
            data["provenance"]["archive"],
            {
                "startUtc": REQUEST["startUtc"],
                "endUtc": REQUEST["endUtc"],
                "endExclusive": True,
                "stepMinutes": 60,
                "sampleCount": 720,
            },
        )
        expected = calculate_visibility(
            self.source["series"][25:31:2],
            [{"az": az, "el": 0.0} for az in range(360)],
            TimeRange(request["startUtc"], request["endUtc"], 120),
        )
        self.assertEqual(data["metrics"], expected.metrics.model_dump())
        self.assertEqual(data["windows"], expected.windows.model_dump())

    def test_visibility_rules_and_selected_time_are_forwarded_to_real_calculations(self):
        responses = [
            self.client.post(ENDPOINT, json=REQUEST | {"visibilityRule": rule}).json()
            for rule in ("any-disc", "body-center", "full-disc")
        ]
        percentages = [data["metrics"]["pctSun"] for data in responses]
        self.assertGreaterEqual(percentages[0], percentages[1])
        self.assertGreaterEqual(percentages[1], percentages[2])
        for rule, data in zip(("any-disc", "body-center", "full-disc"), responses):
            self.assertEqual(data["calculation"]["visibilityRule"], rule)
        sunset = responses[0]["metrics"]["nextSunset"]
        self.assertIsNotNone(sunset)
        selected = iso_utc(parse_utc(sunset) - timedelta(minutes=30))
        response = self.client.post(ENDPOINT, json=REQUEST | {"asOfUtc": selected})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["metrics"]["asOfUtc"], selected)
        self.assertEqual(data["metrics"]["hoursToSunset"], 0.5)
        self.assertEqual(data["windows"], responses[0]["windows"])
        self.assertEqual(data["metrics"]["nextSunsetBracket"]["byUtc"], sunset)

    def test_each_catalog_site_uses_its_own_archived_coordinates_and_angles(self):
        catalog = self.client.get("/api/reference/sites").json()
        for site in catalog["sites"]:
            with self.subTest(site=site["id"]):
                original = json.loads(
                    (REFERENCE / f"{site['id']}.json").read_text(encoding="utf-8")
                )
                response = self.client.post(
                    ENDPOINT,
                    json=REQUEST | {"siteId": site["id"], "endUtc": "2026-11-15T00:00:00Z"},
                )
                self.assertEqual(response.status_code, 200)
                data = response.json()
                for key in ("siteId", "site", "lat", "lon", "altitudeKm", "coordinateSource"):
                    self.assertEqual(data[key], original[key])
                raw_fields = set(original["series"][0])
                self.assertEqual(
                    [{key: row[key] for key in raw_fields} for row in data["series"]],
                    original["series"][:24],
                )

    def test_invalid_reference_requests_return_structured_body_errors(self):
        requests = [
            {key: value for key, value in REQUEST.items() if key != "horizonMode"},
            REQUEST | {"horizonMode": "terrain"},
            REQUEST | {"location": {"latitudeDeg": 0, "longitudeDeg": 0, "altitudeKm": 0}},
            REQUEST | {"stepMinutes": 30},
            REQUEST | {"stepMinutes": 90},
            REQUEST | {"startUtc": "2026-11-14T00:30:00Z"},
            REQUEST | {"startUtc": "2026-11-13T00:00:00Z"},
            REQUEST | {"endUtc": "2026-12-14T00:01:00Z"},
            REQUEST | {"asOfUtc": REQUEST["endUtc"]},
        ]
        for request in requests:
            with self.subTest(request=request):
                response = self.client.post(ENDPOINT, json=request)
                self.assertEqual(response.status_code, 422)
                error = response.json()["error"]
                self.assertEqual(error["code"], "validation_error")
                self.assertEqual(error["details"][0]["location"][0], "body")

    def test_unknown_sites_and_invalid_archives_never_fall_back_to_synthetic_data(self):
        with patch(
            "lunarwindow.api.demo.DemoProvider.evaluate", side_effect=AssertionError("No demo")
        ):
            unknown = self.client.post(ENDPOINT, json=REQUEST | {"siteId": "missing-site"})
            self.assertEqual(unknown.status_code, 404)
            self.assertEqual(unknown.json()["error"]["code"], "not_found")
            for damage in ("missing", "corrupted"):
                with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary) / "reference"
                    if damage == "corrupted":
                        shutil.copytree(REFERENCE, directory)
                        (directory / f"{REQUEST['siteId']}.json").write_text("{}", encoding="utf-8")
                    self.app.dependency_overrides[get_reference_directory] = lambda: directory
                    response = self.client.post(ENDPOINT, json=REQUEST)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(
                        response.json()["error"]["message"],
                        "Reference data is unavailable or failed validation.",
                    )
                    self.assertNotIn(str(directory), response.text)
                    self.assertNotIn("series", response.json())

    def test_openapi_publishes_the_reference_request_response_and_errors(self):
        schema = self.client.get("/openapi.json").json()
        operation = schema["paths"][ENDPOINT]["post"]
        request_body = operation["requestBody"]["content"]["application/json"]["schema"]
        response_body = operation["responses"]["200"]["content"]["application/json"]["schema"]
        for body in (request_body, response_body):
            self.assertEqual(body["discriminator"]["propertyName"], "horizonMode")
            self.assertEqual(set(body["discriminator"]["mapping"]), {"geometric", "terrain"})
        self.assertEqual(
            request_body["discriminator"]["mapping"]["geometric"],
            "#/components/schemas/ReferenceEvaluationRequest",
        )
        self.assertEqual(
            response_body["discriminator"]["mapping"]["geometric"],
            "#/components/schemas/ReferenceEvaluation",
        )
        self.assertTrue({"404", "422", "503"}.issubset(operation["responses"]))
        request_schema = schema["components"]["schemas"]["ReferenceEvaluationRequest"]
        self.assertIn("horizonMode", request_schema["required"])
        self.assertEqual(request_schema["properties"]["horizonMode"]["const"], "geometric")
