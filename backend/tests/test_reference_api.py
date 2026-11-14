"""HTTP handoff of the verified offline bundle, without changing demo evaluations."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app, get_reference_directory

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


class ReferenceApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: REFERENCE
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

    def test_missing_or_corrupted_reference_data_returns_503_without_a_demo_fallback(self):
        for damage in ("missing", "corrupted"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "reference"
                if damage == "corrupted":
                    shutil.copytree(REFERENCE, directory)
                    (directory / f"{SITE_ID}.json").write_text("{}", encoding="utf-8")
                self.app.dependency_overrides[get_reference_directory] = lambda: directory
                with patch(
                    "lunarwindow.api.demo.DemoProvider.evaluate",
                    side_effect=AssertionError("No synthetic fallback"),
                ):
                    response = self.client.get(ENDPOINT)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["message"],
                    "Reference data is unavailable or failed validation.",
                )
                self.assertNotIn(str(directory), response.text)
                self.assertNotIn("series", response.json())
