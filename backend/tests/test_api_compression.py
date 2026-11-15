"""Compress large reference responses without changing data, CORS, or error envelopes."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app


class ApiCompressionTests(unittest.TestCase):
    def test_large_reference_response_compresses_with_identical_decoded_values_and_cors(self):
        with patch.dict(os.environ, {"LUNARWINDOW_CORS_ORIGINS": "https://demo.example"}):
            app = create_app()
        path = "/api/reference/sites/lola-site01-reference/ephemeris"
        query = {"startUtc": "2026-11-14T00:00:00Z", "endUtc": "2026-11-14T03:00:00Z"}
        with TestClient(app) as client:
            plain = client.get(
                path,
                params=query,
                headers={"Accept-Encoding": "identity", "Origin": "https://demo.example"},
            )
            compressed = client.get(
                path,
                params=query,
                headers={"Accept-Encoding": "gzip", "Origin": "https://demo.example"},
            )
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(compressed.status_code, 200)
        self.assertEqual(compressed.json(), plain.json())
        self.assertEqual(compressed.headers["content-encoding"], "gzip")
        self.assertLess(
            int(compressed.headers["content-length"]), int(plain.headers["content-length"])
        )
        self.assertEqual(compressed.headers["access-control-allow-origin"], "https://demo.example")
        self.assertIn("accept-encoding", compressed.headers["vary"].lower())
        self.assertIn("origin", compressed.headers["vary"].lower())

    def test_small_health_and_errors_retain_their_contracts(self):
        with TestClient(create_app()) as client:
            health = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
            missing = client.get("/api/does-not-exist", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(health.status_code, 200)
        self.assertNotIn("content-encoding", health.headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "not_found")
