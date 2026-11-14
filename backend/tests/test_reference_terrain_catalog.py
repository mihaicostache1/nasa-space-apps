"""Terrain discovery verifies artifacts and agrees with the evaluation endpoint."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from lunarwindow.api.app import create_app, get_reference_directory, get_terrain_directory
from lunarwindow.api.models import ReferenceSiteCatalog
from lunarwindow.terrain.models import TerrainMask
from lunarwindow.terrain.registry import ReviewedTerrainMask

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
SITE_ID = "lola-site01-reference"
MASK_ID = "lola-site01-reference-mast-0m"
MASK_SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"
ENDPOINT = "/api/reference/sites"


class ReferenceTerrainCatalogTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: (
            REFERENCE / "validation-30d"
        )
        self.app.dependency_overrides[get_terrain_directory] = lambda: REFERENCE / "terrain-masks"
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.mask_bytes = (REFERENCE / "terrain-masks" / f"{MASK_ID}.json").read_bytes()
        self.mask = json.loads(self.mask_bytes)

    def test_only_site01_advertises_verified_terrain_with_original_source_metadata(self):
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No NASA")),
            patch("lunarwindow.terrain.download.urlopen", side_effect=AssertionError("No DEM")),
            patch(
                "lunarwindow.api.reference_provider.calculate_visibility",
                side_effect=AssertionError("No evaluation during discovery"),
            ),
            patch(
                "lunarwindow.terrain.horizon.compute_horizon",
                side_effect=AssertionError("No terrain regeneration"),
            ),
        ):
            response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200, response.text)
        catalog = response.json()
        self.assertEqual(catalog["schemaVersion"], "lunarwindow.reference-catalog.v1")
        sites = {site["id"]: site for site in catalog["sites"]}
        self.assertEqual(set(sites), {SITE_ID, "lola-site04-reference", "lola-site23-reference"})
        self.assertEqual(sites[SITE_ID]["supportedHorizonModes"], ["geometric", "terrain"])
        self.assertEqual(len(sites[SITE_ID]["terrainMasks"]), 1)
        terrain = sites[SITE_ID]["terrainMasks"][0]
        self.assertEqual(terrain["maskId"], MASK_ID)
        self.assertEqual(terrain["artifactSha256"], MASK_SHA256)
        self.assertEqual(terrain["artifactSha256"], hashlib.sha256(self.mask_bytes).hexdigest())
        self.assertEqual(terrain["observer"], self.mask["observer"])
        self.assertEqual(terrain["observer"]["mastHeightM"], 0)
        self.assertEqual(terrain["observer"]["altitudeKm"], sites[SITE_ID]["altitudeKm"])
        self.assertEqual(terrain["referenceFrame"], self.mask["referenceFrame"])
        self.assertEqual(terrain["demSources"], self.mask["provenance"]["sources"])
        self.assertTrue(terrain["requiresMeanEarthApproximation"])
        self.assertEqual(terrain["framePolicy"], "mean-earth-reference-v1")
        self.assertIn("no frame transformation applied", terrain["limitation"])
        self.assertNotIn("horizon", terrain)
        for site_id in ("lola-site04-reference", "lola-site23-reference"):
            self.assertEqual(sites[site_id]["supportedHorizonModes"], ["geometric"])
            self.assertEqual(sites[site_id]["terrainMasks"], [])
        schema = ReferenceSiteCatalog.model_json_schema()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(catalog)
        api_schema = self.client.get("/openapi.json").json()["components"]["schemas"]
        self.assertIn("terrainMasks", api_schema["ReferenceSite"]["required"])
        self.assertIn("supportedHorizonModes", api_schema["ReferenceSite"]["required"])

    def test_discovered_mask_evaluates_only_with_explicit_acceptance(self):
        catalog = self.client.get(ENDPOINT).json()
        site = next(site for site in catalog["sites"] if site["id"] == SITE_ID)
        terrain = site["terrainMasks"][0]
        request = {
            "siteId": site["id"],
            "horizonMode": "terrain",
            "maskId": terrain["maskId"],
            "startUtc": site["availability"]["startUtc"],
            "endUtc": "2026-11-15T00:00:00Z",
        }
        self.assertEqual(
            self.client.post("/api/reference/evaluations", json=request).status_code, 422
        )
        response = self.client.post(
            "/api/reference/evaluations",
            json=request | {"allowMeanEarthApproximation": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        provenance = response.json()["provenance"]["terrain"]
        self.assertEqual(provenance["artifactSha256"], terrain["artifactSha256"])
        self.assertEqual(provenance["mask"]["observer"], terrain["observer"])
        self.assertEqual(provenance["mask"]["provenance"]["sources"], terrain["demSources"])

    def test_missing_or_corrupted_registered_mask_returns_503_without_partial_catalog(self):
        for damage in ("missing", "corrupt", "changed-with-sidecar"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                path = directory / f"{MASK_ID}.json"
                if damage == "corrupt":
                    path.write_bytes(b"{}")
                elif damage == "changed-with-sidecar":
                    changed = json.loads(self.mask_bytes)
                    changed["horizon"][0]["el"] += 0.01
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    path.with_suffix(".json.sha256").write_text(
                        hashlib.sha256(path.read_bytes()).hexdigest(), encoding="utf-8"
                    )
                self.app.dependency_overrides[get_terrain_directory] = lambda: directory
                response = self.client.get(ENDPOINT)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["message"],
                    "Reference data is unavailable or failed validation.",
                )
                self.assertNotIn("sites", response.json())
                self.assertNotIn(str(directory), response.text)
                # Catalog integrity failure does not disable geometric evaluations.
                request = {
                    "siteId": SITE_ID,
                    "horizonMode": "geometric",
                    "startUtc": "2026-11-14T00:00:00Z",
                    "endUtc": "2026-11-15T00:00:00Z",
                }
                self.assertEqual(
                    self.client.post("/api/reference/evaluations", json=request).status_code, 200
                )

    def test_valid_mask_contract_with_incompatible_observer_or_frame_is_not_advertised(self):
        for mismatch in ("height", "frame"):
            with self.subTest(mismatch=mismatch):
                payload = json.loads(self.mask_bytes)
                if mismatch == "height":
                    payload["observer"]["mastHeightM"] = 2
                    payload["observer"]["altitudeKm"] += 0.002
                else:
                    payload["referenceFrame"]["realization"] = "unreviewed frame"
                reviewed = ReviewedTerrainMask(TerrainMask.model_validate(payload), MASK_SHA256)
                with patch(
                    "lunarwindow.api.reference_catalog.load_reviewed_mask", return_value=reviewed
                ):
                    response = self.client.get(ENDPOINT)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("sites", response.json())

    def test_unregistered_files_are_ignored_and_discovery_does_not_write_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / f"{MASK_ID}.json").write_bytes(self.mask_bytes)
            (directory / "unreviewed.json").write_bytes(b"not a mask")
            before = {path.name: path.read_bytes() for path in directory.iterdir()}
            self.app.dependency_overrides[get_terrain_directory] = lambda: directory
            response = self.client.get(ENDPOINT)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                [
                    mask["maskId"]
                    for site in response.json()["sites"]
                    for mask in site["terrainMasks"]
                ],
                [MASK_ID],
            )
            self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir()}, before)

    def test_catalog_contract_rejects_contradictory_modes_or_duplicate_masks(self):
        original = self.client.get(ENDPOINT).json()
        for change in ("missing-mode", "unsupported-terrain", "duplicate-mask"):
            payload = json.loads(json.dumps(original))
            site = next(site for site in payload["sites"] if site["id"] == SITE_ID)
            if change == "missing-mode":
                site["supportedHorizonModes"] = ["geometric"]
            elif change == "unsupported-terrain":
                site["terrainMasks"] = []
            else:
                site["terrainMasks"] *= 2
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ReferenceSiteCatalog.model_validate(payload)
