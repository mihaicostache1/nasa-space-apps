"""Future-site integration uses SYNTHETIC masks, never evidence of reviewed GIS coverage."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import (
    create_app,
    get_precomputed_directory,
    get_reference_directory,
    get_terrain_directory,
)
from lunarwindow.api.reference_cache_key import build_reference_evaluation_cache_key
from lunarwindow.api.terrain_models import TerrainReferenceEvaluationRequest
from lunarwindow.precompute import PrecomputeJob, generate_bundle
from lunarwindow.reference import load_verified_reference_dataset
from lunarwindow.terrain import registry
from lunarwindow.terrain.handoff import verify_candidate, verify_registered

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
MASK_ID = "lola-site01-reference-mast-0m"
SITES = ("lola-site04-reference", "lola-site23-reference")
ENDPOINT = "/api/reference/evaluations"
ENGINE = "lunarwindow.api.reference_provider.calculate_visibility"


class MultisiteTerrainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.terrain = Path(shutil.copytree(REFERENCE / "terrain-masks", self.root / "masks"))
        self.sources = {}
        self.payloads = {}
        registrations = dict(registry._MASKS)
        for site_id, elevation in zip(SITES, (60.0, -60.0), strict=True):
            source = load_verified_reference_dataset(REFERENCE / "validation-30d", site_id)
            self.sources[site_id] = source
            dataset = source.dataset
            payload = json.loads((self.terrain / f"{MASK_ID}.json").read_bytes())
            mask_id = f"{site_id}-synthetic-test-only"
            payload.update(siteId=site_id, site=dataset["site"], maskId=mask_id)
            payload["observer"].update(
                lat=dataset["lat"],
                lon=dataset["lon"],
                altitudeKm=dataset["altitudeKm"],
                surfaceElevationM=dataset["altitudeKm"] * 1000,
                coordinateSource=dataset["coordinateSource"],
            )
            payload["horizon"] = [{"az": az, "el": elevation} for az in range(360)]
            payload["provenance"]["algorithm"]["name"] = "SYNTHETIC test horizon; not GIS data"
            payload["provenance"]["sources"] = [
                payload["provenance"]["sources"][0]
                | {"provider": "SYNTHETIC test data", "productId": "synthetic-test-only"}
            ]
            path = self.terrain / f"{mask_id}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            registrations[mask_id] = (site_id, path.name, checksum)
            self.payloads[site_id] = payload
        registration_patch = patch("lunarwindow.terrain.registry._MASKS", registrations)
        registration_patch.start()
        self.addCleanup(registration_patch.stop)
        self.app = create_app()
        self.app.dependency_overrides[get_reference_directory] = lambda: (
            REFERENCE / "validation-30d"
        )
        self.app.dependency_overrides[get_terrain_directory] = lambda: self.terrain
        self.app.dependency_overrides[get_precomputed_directory] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def request(self, site_id):
        return {
            "siteId": site_id,
            "horizonMode": "terrain",
            "maskId": self.payloads[site_id]["maskId"],
            "allowMeanEarthApproximation": True,
            "startUtc": "2026-11-14T00:00:00Z",
            "endUtc": "2026-11-15T00:00:00Z",
        }

    def test_catalog_handoff_readiness_and_evaluation_support_multiple_registered_sites(self):
        with patch("socket.socket.connect", side_effect=AssertionError("No NASA or DEM requests")):
            reports = verify_registered(
                REFERENCE / "validation-30d", self.terrain, allow_mean_earth_approximation=True
            )
            self.assertEqual(len(reports), 3)
            catalog = self.client.get("/api/reference/sites")
            self.assertEqual(catalog.status_code, 200, catalog.text)
            sites = {site["id"]: site for site in catalog.json()["sites"]}
            ready = self.client.get("/api/ready")
            self.assertEqual(ready.status_code, 200, ready.text)
            self.assertEqual(ready.json()["terrainMaskCount"], 3)
            for site_id in SITES:
                with self.subTest(site_id=site_id):
                    mask = self.payloads[site_id]
                    terrain = sites[site_id]["terrainMasks"][0]
                    self.assertEqual(
                        sites[site_id]["supportedHorizonModes"], ["geometric", "terrain"]
                    )
                    self.assertEqual(terrain["maskId"], mask["maskId"])
                    self.assertEqual(terrain["observer"], mask["observer"])
                    self.assertTrue(terrain["requiresMeanEarthApproximation"])
                    handoff = verify_candidate(
                        self.terrain / f"{mask['maskId']}.json",
                        expected_sha256=terrain["artifactSha256"],
                        expected_site_id=site_id,
                        reference_directory=REFERENCE / "validation-30d",
                        allow_mean_earth_approximation=True,
                    )
                    self.assertEqual(handoff["observer"], terrain["observer"])
                    response = self.client.post(ENDPOINT, json=self.request(site_id))
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()
                    self.assertEqual(result["horizon"], mask["horizon"])
                    self.assertEqual(result["provenance"]["terrain"]["mask"], mask)
                    self.assertEqual(
                        result["provenance"]["terrain"]["artifactSha256"], terrain["artifactSha256"]
                    )
                    # Known synthetic walls exercise real blocking/window calculation.
                    expected = site_id == SITES[1]
                    self.assertTrue(all(row["sunLit"] is expected for row in result["series"]))
                    self.assertTrue(all(row["earthVis"] is expected for row in result["series"]))
                    self.assertEqual(result["metrics"]["bothHrs"], 24 if expected else 0)
                    self.assertEqual(len(result["windows"]["both"]), 1 if expected else 0)

    def test_cross_site_masks_and_implicit_frame_acceptance_are_rejected(self):
        for site_id, other in ((SITES[0], SITES[1]), (SITES[1], SITES[0])):
            for change in (
                {"maskId": self.payloads[other]["maskId"]},
                {"maskId": MASK_ID},
                {"allowMeanEarthApproximation": False},
            ):
                with self.subTest(site_id=site_id, change=change):
                    response = self.client.post(ENDPOINT, json=self.request(site_id) | change)
                    self.assertEqual(response.status_code, 422, response.text)

    def test_cached_results_remain_separate_and_cannot_hide_changed_masks(self):
        for site_id in SITES:
            response = self.client.post(ENDPOINT, json=self.request(site_id))
            self.assertEqual(response.status_code, 200, response.text)
        with patch(ENGINE, side_effect=AssertionError("Expected a cache hit")):
            for site_id in SITES:
                response = self.client.post(ENDPOINT, json=self.request(site_id))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["siteId"], site_id)
        path = self.terrain / f"{self.payloads[SITES[0]]['maskId']}.json"
        path.write_bytes(path.read_bytes() + b"\n")
        path.with_suffix(".json.sha256").write_text(
            hashlib.sha256(path.read_bytes()).hexdigest(), encoding="utf-8"
        )
        for endpoint in ("/api/reference/sites", "/api/ready"):
            response = self.client.get(endpoint)
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn(str(self.terrain), response.text)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        response = self.client.post(ENDPOINT, json=self.request(SITES[0]))
        self.assertEqual(response.status_code, 503, response.text)
        response = self.client.post(ENDPOINT, json=self.request(SITES[1]))
        self.assertEqual(response.status_code, 200, response.text)

    def test_each_additional_site_can_use_exact_precomputed_results_with_full_provenance(self):
        jobs = []
        for site_id in SITES:
            request = TerrainReferenceEvaluationRequest.model_validate(self.request(site_id))
            reviewed = registry.load_reviewed_mask(self.terrain, request.maskId)
            jobs.append(
                PrecomputeJob(
                    status="pending",
                    evaluation=build_reference_evaluation_cache_key(
                        request,
                        ephemeris_sha256=self.sources[site_id].artifact_sha256,
                        terrain_mask_sha256=reviewed.artifact_sha256,
                    ),
                )
            )
        bundle = self.root / "bundle"
        manifest = generate_bundle(
            jobs,
            run_id="synthetic-multisite-test",
            output_directory=bundle,
            reference_directory=REFERENCE / "validation-30d",
            terrain_directory=self.terrain,
        )
        self.app.dependency_overrides[get_precomputed_directory] = lambda: bundle
        with patch(ENGINE, side_effect=AssertionError("Expected an exact saved result")):
            for site_id, job in zip(SITES, manifest.jobs, strict=True):
                response = self.client.post(ENDPOINT, json=self.request(site_id))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.json(), json.loads((bundle / job.output.filename).read_bytes())
                )
                self.assertEqual(response.json()["maskId"], self.payloads[site_id]["maskId"])
            ready = self.client.get("/api/ready")
            self.assertEqual(ready.status_code, 200, ready.text)
            self.assertEqual(ready.json()["precomputedJobCount"], 2)
