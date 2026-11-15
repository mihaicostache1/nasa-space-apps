"""Custom HTTP evaluation exercises actual Horizons parsing, archival, and engine paths."""

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import numpy as np
from fastapi.testclient import TestClient

from lunarwindow.api.app import (
    create_app,
    get_precomputed_directory,
    get_reference_directory,
    get_terrain_directory,
)
from lunarwindow.api.custom_models import (
    CustomEvaluation,
    CustomLocation,
    canonical_model_sha256,
    observer_site_id,
)
from lunarwindow.api.custom_routes import get_custom_runtime
from lunarwindow.api.custom_runtime import CustomRuntime, CustomSettings
from lunarwindow.ephemeris.models import TimeRange
from lunarwindow.terrain.custom import (
    CustomTerrainCoverageError,
    CustomTerrainDataError,
    CustomTerrainResult,
    CustomTerrainTimeout,
)
from lunarwindow.terrain.dem import Grid
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.horizon import SiteSpec, compute_horizon, default_parameters
from lunarwindow.terrain.models import TerrainMask
from lunarwindow.visibility import calculate_visibility

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
ENDPOINT = "/api/custom/evaluations"
UPSTREAM = "lunarwindow.ephemeris.horizons.urlopen"
ENGINE = "lunarwindow.api.custom_provider.calculate_visibility"
TERRAIN_GENERATOR = "lunarwindow.terrain.custom.generate_custom_terrain"
REQUEST = {
    "location": {
        "latitudeDeg": -89.0,
        "longitudeDeg": 0.0,
        "observerHeightM": 0.0,
        "surfaceElevationM": 0.0,
    },
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-14T03:00:00Z",
    "stepMinutes": 60,
}


def fixture_response(request, timeout):
    query = parse_qs(urlsplit(request.full_url).query)
    target = "sun" if query["COMMAND"] == ["'10'"] else "earth"
    raw = json.loads((FIXTURES / f"{target}.json").read_text())["rawResponse"]
    return io.BytesIO(raw.encode("utf-8"))


def synthetic_observer_response(request, timeout):
    """Controlled test response changes coordinates AND samples; never production data."""
    query = parse_qs(urlsplit(request.full_url).query)
    target = "sun" if query["COMMAND"] == ["'10'"] else "earth"
    raw = json.loads((FIXTURES / f"{target}.json").read_text())["rawResponse"]
    envelope = json.loads(raw)
    coordinates = query["SITE_COORD"][0].strip("'")
    lon, lat, altitude = map(float, coordinates.split(","))
    result = re.sub(
        r"Center geodetic\s*:[^\n]+",
        f"Center geodetic : {coordinates} {{E-lon(deg),Lat(deg),Alt(km)}}",
        envelope["result"],
    )
    before, remainder = result.split("$$SOE")
    table, after = remainder.split("$$EOE")
    rows = list(csv.reader(io.StringIO(table)))
    for row in rows:
        if row and any(cell.strip() for cell in row):
            # Existing fixture CSV: date, solar presence, lunar presence, azimuth, elevation.
            row[4] = str(float(row[4]) + (lat + 89) + lon / 100 + altitude)
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows(rows)
    envelope["result"] = before + "$$SOE" + stream.getvalue() + "$$EOE" + after
    return io.BytesIO(json.dumps(envelope).encode("utf-8"))


def synthetic_terrain_result():
    """Run the real ray caster on a small synthetic ring wall, not NASA terrain evidence."""
    location = CustomLocation.model_validate(REQUEST["location"])
    site_id = observer_site_id(location, 0.0)
    coordinate_source = "Synthetic ring-wall fixture for HTTP integration tests only"
    x, y = (float(value) for value in latlon_to_stereographic(-89, 0))
    row, col = np.indices((41, 41))
    data = np.where(np.hypot(row - 20, col - 20) > 3, 1000.0, 0.0)
    source_sha = hashlib.sha256(b"synthetic ring wall for tests only").hexdigest()
    source_url = "https://example.invalid/synthetic-http-ring-wall.tif"
    grid = Grid(
        data,
        left=x - 2050,
        top=y + 2050,
        resolution_m=100,
        source={
            "productId": "synthetic-test-dem",
            "role": "near-field",
            "sourceUrl": source_url,
            "sha256": source_sha,
        },
    )
    parameters = default_parameters(mastHeightM=0, maxRangeKm=1, nearFieldKm=1, raysPerDegree=1)
    profile = compute_horizon(
        SiteSpec(site_id, "Synthetic test terrain", -89, 0, coordinate_source),
        grid,
        None,
        parameters,
        require_complete=True,
    )
    mask = TerrainMask.model_validate(
        {
            "schemaVersion": "lunarwindow.terrain-mask.v1",
            "maskId": f"{site_id}-synthetic-mask",
            "siteId": site_id,
            "site": profile.name,
            "terrainModel": "dem-horizon",
            "observer": {
                "lat": -89.0,
                "lon": 0.0,
                "coordinateSource": coordinate_source,
                "surfaceElevationM": 0.0,
                "mastHeightM": 0.0,
                "altitudeKm": 0.0,
            },
            "referenceFrame": {
                "body": "Moon",
                "name": "MOON_ME",
                "realization": "DE421",
                "coordinateType": "GEODETIC",
                "longitudeConvention": "east-positive",
                "referenceSurface": {"shape": "sphere", "radiusKm": 1737.4},
            },
            "angularUnits": "degrees",
            "azimuthConvention": "clockwise-from-local-north",
            "elevationReference": "local-horizontal",
            "refractionModel": "none",
            "horizon": [point.model_dump() for point in profile.horizon],
            "provenance": {
                "createdAtUtc": "2026-11-15T00:00:00Z",
                "sources": [
                    {
                        "provider": "Synthetic HTTP integration fixture",
                        "productId": "synthetic-test-dem",
                        "productVersion": "test-only-v1",
                        "sourceUrl": source_url,
                        "sourceSha256": source_sha,
                        "retrievedAtUtc": "2026-11-14T00:00:00Z",
                        "resolutionM": 100.0,
                        "crs": "Synthetic south-polar stereographic; sphere radius 1737400 m",
                    }
                ],
                "algorithm": {
                    "name": "Synthetic ring-wall ray-casting test fixture",
                    "version": profile.algorithmVersion,
                    "curvatureModel": "spherical",
                    "rayStepM": 100.0,
                    "maxDistanceM": 1000.0,
                    "noDataPolicy": "reject",
                },
            },
        }
    )
    return CustomTerrainResult(
        profile,
        mask,
        canonical_model_sha256(profile),
        canonical_model_sha256(mask),
    )


class CustomHttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = CustomSettings(
            enabled=True,
            archive_directory=self.root / "ephemeris",
            terrain_cache_directory=self.root / "terrain",
            dem_directory=self.root / "missing-dems",
            timeout_seconds=10,
        )
        self.runtime = CustomRuntime(self.settings)
        self.app = create_app()
        self.app.dependency_overrides[get_custom_runtime] = lambda: self.runtime
        self.app.dependency_overrides[get_reference_directory] = lambda: (
            REFERENCE / "validation-30d"
        )
        self.app.dependency_overrides[get_terrain_directory] = lambda: REFERENCE / "terrain-masks"
        self.app.dependency_overrides[get_precomputed_directory] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(lambda: self.runtime.close())

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertTrue(body["error"]["message"])
        self.assertNotIn(str(self.root), response.text)
        return body["error"]

    def test_geometric_http_path_uses_real_samples_engine_and_verified_archive_reuse(self):
        with patch(UPSTREAM, side_effect=fixture_response) as upstream:
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        CustomEvaluation.model_validate(result)
        self.assertEqual(upstream.call_count, 2)
        self.assertEqual(result["dataMode"], "custom")
        self.assertEqual(result["observer"]["lat"], -89)
        self.assertEqual(result["observer"]["altitudeKm"], 0)
        self.assertEqual(result["series"][0]["sunEl"], 0.960002237)
        fixture = json.loads((FIXTURES / "dataset.json").read_bytes())
        expected = calculate_visibility(
            fixture["series"],
            [{"az": az, "el": 0.0} for az in range(360)],
            TimeRange(REQUEST["startUtc"], REQUEST["endUtc"], 60),
        )
        self.assertEqual(result["metrics"], expected.metrics.model_dump())
        self.assertEqual(result["windows"], expected.windows.model_dump())
        entries = list(self.settings.archive_directory.glob("*.json"))
        self.assertEqual(len(entries), 1)
        archive = json.loads(entries[0].read_bytes())
        self.assertEqual(len(archive["rawResponses"]), 2)
        self.assertEqual(archive["datasetSha256"], result["provenance"]["ephemerisSha256"])
        with (
            patch(UPSTREAM, side_effect=AssertionError("Archive hit must not fetch")),
            patch(ENGINE, side_effect=AssertionError("Result cache hit must not calculate")),
        ):
            cached = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertEqual(cached.json(), result)
        self.assertFalse(self.settings.dem_directory.exists())

    def test_exact_coordinate_and_height_changes_reach_horizons_and_change_results(self):
        requests = [deepcopy(REQUEST) for _ in range(3)]
        requests[1]["location"]["latitudeDeg"] = -88
        requests[1]["location"]["longitudeDeg"] = 1
        requests[2]["location"]["observerHeightM"] = 2
        results = []
        with patch(UPSTREAM, side_effect=synthetic_observer_response) as upstream:
            for payload in requests:
                response = self.client.post(ENDPOINT, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                results.append(response.json())
        self.assertEqual(upstream.call_count, 6)
        self.assertEqual(len({result["siteId"] for result in results}), 3)
        self.assertEqual(len({result["series"][0]["sunEl"] for result in results}), 3)
        coordinates = {
            parse_qs(urlsplit(call.args[0].full_url).query)["SITE_COORD"][0]
            for call in upstream.call_args_list
        }
        self.assertEqual(coordinates, {"'0.0,-89.0,0.0'", "'1.0,-88.0,0.0'", "'0.0,-89.0,0.002'"})

    def test_validation_errors_are_structured_and_never_fetch(self):
        candidates = []
        for field, value in (
            ("latitudeDeg", 91),
            ("longitudeDeg", -181),
            ("observerHeightM", -1),
            ("latitudeDeg", True),
            ("latitudeDeg", "-89"),
        ):
            payload = deepcopy(REQUEST)
            payload["location"][field] = value
            candidates.append(payload)
        for field in ("observerHeightM", "surfaceElevationM"):
            payload = deepcopy(REQUEST)
            del payload["location"][field]
            candidates.append(payload)
        candidates.extend(
            [
                REQUEST | {"horizonMode": "unavailable"},
                REQUEST | {"undeclared": True},
                REQUEST | {"allowMeanEarthApproximation": True},
                REQUEST | {"startUtc": "2026-11-14"},
                REQUEST | {"endUtc": "2026-11-14T00:00:00Z"},
                REQUEST | {"endUtc": "2026-11-15T00:00:00Z", "stepMinutes": 1},
            ]
        )
        with patch(UPSTREAM, side_effect=AssertionError("Invalid requests must not fetch")):
            for payload in candidates:
                with self.subTest(payload=payload):
                    error = self.assert_error(
                        self.client.post(ENDPOINT, json=payload), 422, "validation_error"
                    )
                    self.assertTrue(error["details"])

    def test_disabled_and_busy_are_explicit_and_do_not_queue_upstream_work(self):
        self.runtime = CustomRuntime(replace(self.settings, enabled=False))
        with patch(UPSTREAM, side_effect=AssertionError("Disabled")):
            self.assert_error(self.client.post(ENDPOINT, json=REQUEST), 503, "custom_disabled")
        self.runtime = CustomRuntime(self.settings)
        with self.runtime.admit(), patch(UPSTREAM, side_effect=AssertionError("Busy")):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assert_error(response, 503, "custom_busy")
        self.assertEqual(response.headers.get("Retry-After"), "1")
        # Capacity is released after the competing operation ends.
        with patch(UPSTREAM, side_effect=fixture_response):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200, response.text)

    def test_upstream_failures_and_wrong_observer_return_502_without_partial_archive(self):
        cases = [
            (REQUEST, URLError("example network failure")),
            (REQUEST, lambda request, timeout: io.BytesIO(b"{}")),
            (
                REQUEST | {"location": REQUEST["location"] | {"latitudeDeg": -88}},
                fixture_response,
            ),
        ]
        for payload, failure in cases:
            with (
                self.subTest(payload=payload, failure=failure),
                patch(UPSTREAM, side_effect=failure),
            ):
                response = self.client.post(ENDPOINT, json=payload)
            self.assert_error(response, 502, "custom_upstream_unavailable")
            self.assertEqual(list(self.settings.archive_directory.glob("*.json")), [])

    def test_upstream_timeout_returns_504_and_frees_admission(self):
        with patch(UPSTREAM, side_effect=TimeoutError("example slow provider")):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assert_error(response, 504, "custom_upstream_timeout")
        with patch(UPSTREAM, side_effect=fixture_response):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200, response.text)

    def test_terrain_requires_explicit_frame_acceptance_and_server_enablement(self):
        payload = deepcopy(REQUEST)
        payload["horizonMode"] = "terrain"
        del payload["location"]["surfaceElevationM"]
        with patch(UPSTREAM, side_effect=AssertionError("No upstream before terrain checks")):
            self.assert_error(self.client.post(ENDPOINT, json=payload), 422, "validation_error")
            payload["allowMeanEarthApproximation"] = True
            self.assert_error(
                self.client.post(ENDPOINT, json=payload), 503, "custom_data_unavailable"
            )

    def test_terrain_http_uses_actual_ray_cast_profile_and_preserves_preliminary_provenance(self):
        self.runtime = CustomRuntime(replace(self.settings, terrain_enabled=True))
        prepared = synthetic_terrain_result()
        payload = deepcopy(REQUEST)
        payload["horizonMode"] = "terrain"
        payload["allowMeanEarthApproximation"] = True
        del payload["location"]["surfaceElevationM"]
        with (
            patch(TERRAIN_GENERATOR, return_value=prepared) as generator,
            patch(UPSTREAM, side_effect=fixture_response) as upstream,
        ):
            response = self.client.post(ENDPOINT, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        CustomEvaluation.model_validate(result)
        self.assertEqual(upstream.call_count, 2)
        self.assertIsNone(generator.call_args.kwargs["surface_elevation_m"])
        self.assertEqual(generator.call_args.kwargs["latitude_deg"], -89)
        self.assertEqual(result["horizonMode"], "terrain")
        terrain = result["provenance"]["terrain"]
        self.assertEqual(terrain["reviewStatus"], "preliminary")
        self.assertEqual(terrain["profile"], prepared.profile.model_dump(mode="json"))
        self.assertEqual(terrain["mask"], prepared.mask.model_dump(mode="json"))
        self.assertEqual(terrain["maskSha256"], prepared.mask_sha256)
        self.assertEqual(terrain["profileSha256"], prepared.profile_sha256)
        self.assertEqual(terrain["compatibility"]["frameStatus"], "approximate")
        self.assertFalse(terrain["compatibility"]["transformationApplied"])
        self.assertEqual(result["horizon"], terrain["mask"]["horizon"])
        self.assertEqual(result["metrics"]["sunlitHrs"], 0)
        self.assertEqual(result["metrics"]["bothHrs"], 0)
        self.assertIn("preliminary", result["provenance"]["warning"].lower())
        with (
            patch(TERRAIN_GENERATOR, return_value=prepared) as generator,
            patch(UPSTREAM, side_effect=AssertionError("Verified archive hit")),
            patch(ENGINE, side_effect=AssertionError("Verified result cache hit")),
        ):
            cached = self.client.post(ENDPOINT, json=payload)
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertEqual(cached.json(), result)
        self.assertEqual(
            generator.call_count, 1, "Terrain verification precedes every result-cache hit"
        )

    def test_terrain_coverage_data_and_timeout_errors_remain_explicit_without_nasa_calls(self):
        self.runtime = CustomRuntime(replace(self.settings, terrain_enabled=True))
        payload = deepcopy(REQUEST)
        payload.update(horizonMode="terrain", allowMeanEarthApproximation=True)
        del payload["location"]["surfaceElevationM"]
        for exception, status, code in (
            (
                CustomTerrainCoverageError("Location has no complete terrain coverage."),
                422,
                "validation_error",
            ),
            (
                CustomTerrainDataError(f"Missing raster in {self.root}"),
                503,
                "custom_data_unavailable",
            ),
            (CustomTerrainTimeout("Terrain budget expired."), 504, "custom_upstream_timeout"),
        ):
            with (
                self.subTest(exception=type(exception).__name__),
                patch(TERRAIN_GENERATOR, side_effect=exception),
                patch(UPSTREAM, side_effect=AssertionError("Terrain must verify before NASA")),
            ):
                self.assert_error(self.client.post(ENDPOINT, json=payload), status, code)
        # Exercise the real adapter's missing-data behavior rather than only its exception boundary.
        with patch(UPSTREAM, side_effect=AssertionError("No DEMs, no NASA")):
            response = self.client.post(ENDPOINT, json=payload)
        self.assert_error(response, 503, "custom_data_unavailable")

    def test_corrupted_archive_cannot_be_served_by_a_warm_response_cache(self):
        with patch(UPSTREAM, side_effect=fixture_response):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200, response.text)
        entry = next(self.settings.archive_directory.glob("*.json"))
        archive = json.loads(entry.read_bytes())
        archive["dataset"]["series"][0]["sunEl"] += 10
        entry.write_text(json.dumps(archive), encoding="utf-8")
        with patch(UPSTREAM, side_effect=AssertionError("No implicit refresh after corruption")):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assert_error(response, 503, "custom_data_unavailable")

    def test_reference_endpoints_remain_available_when_custom_is_disabled_or_corrupt(self):
        for enabled in (False, True):
            settings = replace(self.settings, enabled=enabled)
            if enabled:
                broken_directory = self.root / "broken-custom-archive"
                broken_directory.write_text("Not a directory", encoding="utf-8")
                settings = replace(settings, archive_directory=broken_directory)
            self.runtime = CustomRuntime(settings)
            with patch(UPSTREAM, side_effect=AssertionError("Reference evaluation stays offline")):
                if enabled:
                    self.assert_error(
                        self.client.post(ENDPOINT, json=REQUEST), 503, "custom_data_unavailable"
                    )
                health = self.client.get("/api/health")
                catalog = self.client.get("/api/reference/sites")
                reference = self.client.post(
                    "/api/reference/evaluations",
                    json={
                        "siteId": "lola-site01-reference",
                        "horizonMode": "geometric",
                        "startUtc": "2026-11-14T00:00:00Z",
                        "endUtc": "2026-11-14T03:00:00Z",
                    },
                )
            self.assertEqual(health.status_code, 200, health.text)
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual(reference.status_code, 200, reference.text)
            self.assertEqual(reference.json()["dataMode"], "reference")

    def test_openapi_documents_custom_contract_without_replacing_reference_contracts(self):
        schema = self.client.get("/openapi.json").json()
        operation = schema["paths"][ENDPOINT]["post"]
        self.assertEqual(set(operation["responses"]), {"200", "422", "502", "503", "504"})
        location = schema["components"]["schemas"]["CustomLocation"]
        self.assertIn("observerHeightM", location["required"])
        self.assertNotIn("surfaceElevationM", location["required"])
        self.assertIn("/api/reference/evaluations", schema["paths"])
