"""Offline HTTP contract tests for synthetic sources and calculated visibility."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from lunarwindow.api.app import create_app
from lunarwindow.api.models import Period

SCENARIO = {
    "name": "Scenario A",
    "location": {"latitudeDeg": -89, "longitudeDeg": 0, "altitudeKm": 0},
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-15T00:00:00Z",
    "stepMinutes": 60,
}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def test_health_and_catalog_identify_demo_mode(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["service"], "lunarwindow-backend")
        self.assertEqual(health.json()["dataMode"], "synthetic")
        catalog = self.client.get("/api/sites")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["dataMode"], "synthetic")
        sites = catalog.json()["sites"]
        self.assertEqual(len({site["id"] for site in sites}), 3)
        for site in sites:
            self.assertIn("Illustrative", site["coordinateSource"])
            response = self.client.get(f"/api/sites/{site['id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["siteId"], site["id"])
            self.assertEqual(len(response.json()["series"]), 720)

    def test_scenario_contract_horizon_and_half_open_grid(self):
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No NASA calls")
        ):
            response = self.client.post("/api/evaluations", json=SCENARIO)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["schemaVersion"], "lunarwindow.evaluation.v2")
        self.assertEqual(data["dataMode"], "synthetic")
        self.assertEqual(data["site"], SCENARIO["name"])
        self.assertEqual(data["horizon"][0]["az"], 0)
        self.assertEqual([point["az"] for point in data["horizon"]], list(range(360)))
        self.assertEqual(len(data["series"]), 24)
        self.assertEqual(data["series"][0]["t"], SCENARIO["startUtc"])
        self.assertEqual(data["series"][-1]["t"], "2026-11-14T23:00:00Z")
        self.assertTrue(data["provenance"]["endExclusive"])
        self.assertEqual(data["provenance"]["terrainModel"], "synthetic")
        self.assertEqual(data["metrics"]["evaluatedHrs"], 24)
        self.assertIsInstance(data["metrics"]["pctSun"], (int, float))
        self.assertIsInstance(data["metrics"]["longestDarkHrs"], (int, float))
        self.assertEqual(data["calculation"]["visibilityRule"], "any-disc")
        self.assertEqual(data["calculation"]["timeModel"], "sample-and-hold")
        self.assertEqual(
            set(data["windows"]), {"sunlit", "earthVisible", "both", "darkness", "earthBlackout"}
        )
        for row in data["series"]:
            self.assertIsInstance(row["sunLit"], bool)
            self.assertIsInstance(row["earthVis"], bool)
            self.assertEqual(
                row["sunLit"], row["sunEl"] + row["sunAngularRadiusDeg"] > row["sunHorizonEl"]
            )
            self.assertEqual(
                row["earthVis"],
                row["earthEl"] + row["earthAngularRadiusDeg"] > row["earthHorizonEl"],
            )
            self.assertIn(row["sunVisibility"], ("hidden", "partial", "full"))
            self.assertIn(row["earthVisibility"], ("hidden", "partial", "full"))

    def test_catalog_get_and_scenario_post_share_the_contract(self):
        site = self.client.get("/api/sites").json()["sites"][0]
        params = {key: SCENARIO[key] for key in ("startUtc", "endUtc", "stepMinutes")}
        saved = self.client.get(f"/api/sites/{site['id']}", params=params).json()
        scenario = self.client.post(
            "/api/evaluations", json=SCENARIO | {"name": site["name"]}
        ).json()
        self.assertEqual(saved | {"siteId": "custom"}, scenario)

    def test_demo_is_deterministic_and_overlapping_ranges_match(self):
        first = self.client.post("/api/evaluations", json=SCENARIO).json()
        repeated = self.client.post("/api/evaluations", json=SCENARIO).json()
        self.assertEqual(first, repeated)
        subset = self.client.post(
            "/api/evaluations", json=SCENARIO | {"startUtc": "2026-11-14T12:00:00Z"}
        ).json()
        self.assertEqual(first["series"][12:], subset["series"])
        moved = self.client.post(
            "/api/evaluations",
            json=SCENARIO | {"location": SCENARIO["location"] | {"longitudeDeg": 30}},
        ).json()
        self.assertNotEqual(first["series"], moved["series"])

    def test_site_query_accepts_the_same_calculation_options_as_post(self):
        scenario = SCENARIO | {"visibilityRule": "full-disc", "asOfUtc": "2026-11-14T01:30:00Z"}
        site = self.client.get("/api/sites").json()["sites"][0]
        params = {key: value for key, value in scenario.items() if key not in ("name", "location")}
        saved = self.client.get(f"/api/sites/{site['id']}", params=params)
        custom = self.client.post("/api/evaluations", json=scenario | {"name": site["name"]})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(custom.status_code, 200)
        self.assertEqual(saved.json() | {"siteId": "custom"}, custom.json())
        self.assertEqual(saved.json()["metrics"]["asOfUtc"], scenario["asOfUtc"])
        self.assertEqual(saved.json()["calculation"]["visibilityRule"], "full-disc")

    def test_visibility_rule_and_selected_time_reach_the_engine(self):
        scenario = SCENARIO | {"endUtc": "2026-12-14T00:00:00Z"}
        results = [
            self.client.post("/api/evaluations", json=scenario | {"visibilityRule": rule}).json()
            for rule in ("any-disc", "body-center", "full-disc")
        ]
        any_disc, center, full = [result["metrics"] for result in results]
        self.assertGreater(any_disc["pctSun"], center["pctSun"])
        self.assertGreater(center["pctSun"], full["pctSun"])
        self.assertIsNotNone(any_disc["nextSunset"])
        response = self.client.post(
            "/api/evaluations", json=scenario | {"asOfUtc": any_disc["nextSunset"]}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["metrics"]["hoursToSunset"], 0)
        self.assertEqual(data["windows"], results[0]["windows"])
        self.assertEqual(data["metrics"]["pctSun"], any_disc["pctSun"])
        self.assertEqual(data["metrics"]["nextSunsetBracket"]["byUtc"], any_disc["nextSunset"])

    def test_windows_and_metrics_account_for_the_entire_requested_range(self):
        data = self.client.get("/api/sites/demo-polar-a").json()
        metrics, windows = data["metrics"], data["windows"]
        self.assertEqual(metrics["evaluatedHrs"], 720)
        self.assertEqual(metrics["asOfUtc"], "2026-11-14T00:00:00Z")
        for lane, hours, percentage in (
            ("sunlit", "sunlitHrs", "pctSun"),
            ("earthVisible", "earthVisibleHrs", "pctEarth"),
            ("both", "bothHrs", "pctBoth"),
        ):
            self.assertAlmostEqual(
                sum(window["durationHrs"] for window in windows[lane]), metrics[hours]
            )
            self.assertAlmostEqual(metrics[percentage], 100 * metrics[hours] / 720)
        self.assertAlmostEqual(
            metrics["sunlitHrs"] + sum(window["durationHrs"] for window in windows["darkness"]),
            720,
        )
        self.assertLessEqual(metrics["pctBoth"], min(metrics["pctSun"], metrics["pctEarth"]))

    def test_calculation_options_are_validated_for_body_and_query_requests(self):
        invalid = [
            {"visibilityRule": "unknown"},
            {"asOfUtc": "2026-11-13T23:59:00Z"},
            {"asOfUtc": SCENARIO["endUtc"]},
            {"asOfUtc": "2026-11-14T00:00:01Z"},
            {"asOfUtc": "2026-11-14T00:00:00+02:00"},
            {"asOfUtc": "not-a-date"},
        ]
        for options in invalid:
            with self.subTest(options=options):
                response = self.client.post("/api/evaluations", json=SCENARIO | options)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "validation_error")
                params = {key: SCENARIO[key] for key in ("startUtc", "endUtc", "stepMinutes")}
                response = self.client.get("/api/sites/demo-polar-a", params=params | options)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["details"][0]["location"][0], "query")

    def test_non_aligned_end_includes_last_on_grid_sample(self):
        response = self.client.post(
            "/api/evaluations", json=SCENARIO | {"endUtc": "2026-11-14T02:01:00Z"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["series"]), 3)
        self.assertEqual(response.json()["series"][-1]["t"], "2026-11-14T02:00:00Z")

    def test_invalid_scenarios_return_structured_errors(self):
        changes = [
            {"name": "   "},
            {"name": "a" * 81},
            {"location": SCENARIO["location"] | {"latitudeDeg": -91}},
            {"location": SCENARIO["location"] | {"longitudeDeg": 181}},
            {"location": SCENARIO["location"] | {"altitudeKm": "0"}},
            {"location": SCENARIO["location"] | {"latitudeDeg": True}},
            {"endUtc": SCENARIO["startUtc"]},
            {"endUtc": "2026-11-13T00:00:00Z"},
            {"endUtc": "2026-12-16T00:00:00Z"},
            {"endUtc": "2026-11-21T00:00:00Z", "stepMinutes": 1},
            {"stepMinutes": 0},
            {"stepMinutes": 1441},
            {"stepMinutes": True},
            {"stepMinutes": 1.5},
            {"stepMinutes": "60"},
            {"startUtc": "2026-11-14"},
            {"startUtc": "2026-11-14T00:00:01Z"},
            {"startUtc": "2026-11-14T00:00:00+02:00"},
            {"startUtc": "2026-02-30T00:00:00Z"},
            {"startUtc": "1961-01-01T00:00:00Z"},
            {"unexpected": True},
        ]
        for change in changes:
            with self.subTest(change=change):
                response = self.client.post("/api/evaluations", json=SCENARIO | change)
                self.assertEqual(response.status_code, 422)
                error = response.json()["error"]
                self.assertEqual(error["code"], "validation_error")
                self.assertTrue(error["details"])

    def test_period_sample_limits_use_the_exclusive_end(self):
        period = Period(startUtc=SCENARIO["startUtc"], endUtc="2026-11-20T22:40:00Z", stepMinutes=1)
        self.assertEqual(period.to_time_range().sample_count, 10_000)
        with self.assertRaises(ValidationError):
            Period(startUtc=SCENARIO["startUtc"], endUtc="2026-11-20T22:41:00Z", stepMinutes=1)

    def test_nonfinite_numbers_are_rejected_without_breaking_error_serialization(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                payload = SCENARIO | {"location": SCENARIO["location"] | {"altitudeKm": value}}
                response = self.client.post(
                    "/api/evaluations",
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_bad_query_and_unknown_sites_are_structured(self):
        for params in [
            {"stepMinutes": 0},
            {"stepMinutes": "bad"},
            {"startUtc": "not-a-date"},
            {"endUtc": "2026-01-01T00:00:00Z"},
            {"endUtc": "2027-01-01T00:00:00Z"},
        ]:
            with self.subTest(params=params):
                response = self.client.get("/api/sites/demo-polar-a", params=params)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["details"][0]["location"][0], "query")
        response = self.client.get("/api/sites/unknown")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")
        self.assertEqual(self.client.get("/missing").json()["error"]["code"], "not_found")

    def test_malformed_json_uses_the_error_contract(self):
        response = self.client.post(
            "/api/evaluations", content="{", headers={"Content-Type": "application/json"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_cors_allows_frontend_and_configurable_origins(self):
        with patch.dict("os.environ", {"LUNARWINDOW_CORS_ORIGINS": "http://localhost:3000"}):
            with TestClient(create_app()) as client:
                response = client.options(
                    "/api/evaluations",
                    headers={
                        "Origin": "http://localhost:3000",
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "Content-Type",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers["access-control-allow-origin"], "http://localhost:3000"
                )
                denied = client.get("/api/sites", headers={"Origin": "https://other.example"})
                self.assertNotIn("access-control-allow-origin", denied.headers)
        with patch.dict("os.environ", {"LUNARWINDOW_CORS_ORIGINS": "https://demo.example"}):
            with TestClient(create_app()) as client:
                response = client.get("/api/sites", headers={"Origin": "https://demo.example"})
                self.assertEqual(
                    response.headers["access-control-allow-origin"], "https://demo.example"
                )

    def test_openapi_describes_request_response_and_errors(self):
        schema = self.client.get("/openapi.json").json()
        operation = schema["paths"]["/api/evaluations"]["post"]
        self.assertIn("requestBody", operation)
        self.assertIn("200", operation["responses"])
        self.assertIn("422", operation["responses"])
        self.assertIn("Evaluation", schema["components"]["schemas"])
        self.assertIn("ErrorResponse", schema["components"]["schemas"])
        self.assertEqual(self.client.get("/docs").status_code, 200)


if __name__ == "__main__":
    unittest.main()
