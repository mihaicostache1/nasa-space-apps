"""HTTP handoff of the verified offline bundle, without changing demo evaluations."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app, get_reference_directory, get_terrain_directory

REFERENCE = (
    Path(
        os.environ.get(
            "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
        )
    )
    / "validation-30d"
)
SITE_ID = "lola-site01-reference"
ENDPOINT = f"/api/reference/sites/{SITE_ID}/ephemeris"
CATALOG_ENDPOINT = "/api/reference/sites"


class ReferenceApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: REFERENCE
        self.app.dependency_overrides[get_terrain_directory] = lambda: (
            REFERENCE.parent / "terrain-masks"
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_returns_original_real_samples_and_documents_the_ephemeris_contract(self):
        expected = json.loads((REFERENCE / f"{SITE_ID}.json").read_text(encoding="utf-8"))
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No network")
        ):
            response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(len(response.json()["series"]), 720)
        self.assertEqual(response.json()["provenance"]["provider"], "NASA/JPL Horizons")
        operation = self.client.get("/openapi.json").json()["paths"][
            "/api/reference/sites/{site_id}/ephemeris"
        ]["get"]
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], "lunarwindow.ephemeris.v2")
        self.assertIn("404", operation["responses"])
        self.assertIn("503", operation["responses"])

    def test_unknown_reference_site_returns_structured_404(self):
        response = self.client.get("/api/reference/sites/missing-site/ephemeris")
        self.assertEqual(response.status_code, 404)
        error = response.json()["error"]
        self.assertEqual(error["code"], "not_found")
        self.assertIn("Unknown reference site", error["message"])

    def test_reference_query_returns_exact_samples_with_consistent_selected_range(self):
        expected = json.loads((REFERENCE / f"{SITE_ID}.json").read_text(encoding="utf-8"))
        options = {
            "startUtc": "2026-11-15T00:00:00Z",
            "endUtc": "2026-11-16T00:00:00Z",
            "stepMinutes": 120,
        }
        response = self.client.get(ENDPOINT, params=options)
        self.assertEqual(response.status_code, 200)
        expected["series"] = expected["series"][24:48:2]
        expected["provenance"].update(options)
        self.assertEqual(response.json(), expected)
        self.assertEqual(len(response.json()["series"]), 12)
        operation = self.client.get("/openapi.json").json()["paths"][
            "/api/reference/sites/{site_id}/ephemeris"
        ]["get"]
        query = {item["name"]: item for item in operation["parameters"] if item["in"] == "query"}
        self.assertEqual(set(query), {"startUtc", "endUtc", "stepMinutes"})
        self.assertTrue(all(not item["required"] for item in query.values()))

    def test_reference_query_defaults_unspecified_values_to_archive_coverage(self):
        for options, expected_count in (
            ({"endUtc": "2026-11-14T02:30:00Z"}, 3),
            ({"startUtc": "2026-12-13T23:00:00Z"}, 1),
            ({"stepMinutes": 120}, 360),
        ):
            with self.subTest(options=options):
                response = self.client.get(ENDPOINT, params=options)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["series"]), expected_count)

    def test_invalid_or_unavailable_reference_selection_returns_structured_422(self):
        cases = [
            {"startUtc": "2026-11-13T23:00:00Z"},
            {"endUtc": "2026-12-14T00:01:00Z"},
            {"startUtc": "2026-12-14T00:00:00Z"},
            {"startUtc": "2026-11-15T00:00:00Z", "endUtc": "2026-11-15T00:00:00Z"},
            {"startUtc": "2026-11-16T00:00:00Z", "endUtc": "2026-11-15T00:00:00Z"},
            {"startUtc": "2026-11-14T00:30:00Z"},
            {"startUtc": "2026-11-14T00:00:01Z"},
            {"startUtc": "2026-11-14T00:00:00+02:00"},
            {"endUtc": "2026-11-31T00:00:00Z"},
            {"startUtc": "not-a-date"},
            {"stepMinutes": 30},
            {"stepMinutes": 90},
            {"stepMinutes": 0},
            {"stepMinutes": 1441},
            {"stepMinutes": "invalid"},
            {"stepMinutes": "true"},
        ]
        for options in cases:
            with self.subTest(options=options):
                response = self.client.get(ENDPOINT, params=options)
                self.assertEqual(response.status_code, 422)
                error = response.json()["error"]
                self.assertEqual(error["code"], "validation_error")
                self.assertTrue(error["details"])
                self.assertEqual(error["details"][0]["location"][0], "query")

    def test_catalog_lists_verified_coordinates_sources_and_archive_coverage(self):
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No network")
        ):
            response = self.client.get(CATALOG_ENDPOINT)
        self.assertEqual(response.status_code, 200)
        catalog = response.json()
        self.assertEqual(catalog["schemaVersion"], "lunarwindow.reference-catalog.v1")
        self.assertEqual(catalog["provider"], "NASA/JPL Horizons")
        self.assertEqual(catalog["timeScale"], "UTC")
        self.assertEqual(catalog["longitudeConvention"], "east-positive")
        manifest = json.loads((REFERENCE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [site["id"] for site in catalog["sites"]],
            [item["siteId"] for item in manifest["datasets"]],
        )
        self.assertEqual(len(catalog["sites"]), 3)
        for site, item in zip(catalog["sites"], manifest["datasets"]):
            original = json.loads((REFERENCE / item["json"]).read_text(encoding="utf-8"))
            self.assertEqual(site["name"], original["site"])
            for field in ("lat", "lon", "altitudeKm", "coordinateSource"):
                self.assertEqual(site[field], original[field])
            self.assertIn(
                "reference point, not a selected landing target", site["coordinateSource"]
            )
            self.assertEqual(
                site["availability"],
                {
                    "startUtc": "2026-11-14T00:00:00Z",
                    "endUtc": "2026-12-14T00:00:00Z",
                    "endExclusive": True,
                    "stepMinutes": 60,
                    "sampleCount": 720,
                },
            )
            self.assertNotIn("series", site)
        operation = self.client.get("/openapi.json").json()["paths"][CATALOG_ENDPOINT]["get"]
        self.assertIn("503", operation["responses"])
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ReferenceSiteCatalog",
        )

    def test_catalog_rejects_invalid_coordinates_even_if_checksum_is_updated(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "reference"
            shutil.copytree(REFERENCE, directory)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            item = manifest["datasets"][-1]
            dataset_path = directory / item["json"]
            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
            dataset["lat"] = 91
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            item["jsonSha256"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.app.dependency_overrides[get_reference_directory] = lambda: directory
            response = self.client.get(CATALOG_ENDPOINT)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("sites", response.json())

    def test_missing_or_corrupted_reference_data_returns_503_without_a_demo_fallback(self):
        for damage in ("missing", "corrupted"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "reference"
                if damage == "corrupted":
                    shutil.copytree(REFERENCE, directory)
                    (directory / f"{SITE_ID}.json").write_text("{}", encoding="utf-8")
                self.app.dependency_overrides[get_reference_directory] = lambda: directory
                for endpoint in (ENDPOINT, CATALOG_ENDPOINT, ENDPOINT + "?stepMinutes=120"):
                    with patch(
                        "lunarwindow.api.demo.DemoProvider.evaluate",
                        side_effect=AssertionError("No synthetic fallback"),
                    ):
                        response = self.client.get(endpoint)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(
                        response.json()["error"]["message"],
                        "Reference data is unavailable or failed validation.",
                    )
                    self.assertNotIn(str(directory), response.text)
                    self.assertNotIn("series", response.json())
                    self.assertNotIn("sites", response.json())
