"""Actual GeoTIFF-to-HTTP custom terrain tests on explicitly synthetic local rasters.

Only product byte sizes and the ray extent/count are reduced for these fixtures.
The real source hashing, Rasterio/CRS/window access, ray caster, mask generation,
Horizons parser/archival, visibility engine, and HTTP route remain connected.
"""

import hashlib
import io
import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import numpy as np
from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app
from lunarwindow.api.custom_models import CustomEvaluation, canonical_model_sha256
from lunarwindow.api.custom_routes import get_custom_runtime
from lunarwindow.api.custom_runtime import CustomRuntime, CustomSettings
from lunarwindow.terrain.download import sidecar_path
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.horizon import default_parameters
from lunarwindow.terrain.models import HorizonProfile, TerrainMask
from lunarwindow.terrain.products import FAR_FIELD, NEAR_FIELD, PRODUCTS

try:
    import rasterio
    from rasterio.transform import from_origin
except ImportError:  # Native tests may omit GIS; the custom-test image installs it.
    rasterio = None

FIXTURES = Path(__file__).parent / "fixtures"
ENDPOINT = "/api/custom/evaluations"
UPSTREAM = "lunarwindow.ephemeris.horizons.urlopen"
CRS = "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m"
REQUEST = {
    "location": {"latitudeDeg": -89.0, "longitudeDeg": 0.0, "observerHeightM": 2.0},
    "horizonMode": "terrain",
    "allowMeanEarthApproximation": True,
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-14T03:00:00Z",
    "stepMinutes": 60,
}


def synthetic_observer_response(request, timeout):
    """Archived angles with an explicitly synthetic fixture observer header."""
    query = parse_qs(urlsplit(request.full_url).query)
    target = "sun" if query["COMMAND"] == ["'10'"] else "earth"
    raw = json.loads((FIXTURES / f"{target}.json").read_text())["rawResponse"]
    envelope = json.loads(raw)
    coordinates = query["SITE_COORD"][0].strip("'")
    envelope["result"] = re.sub(
        r"Center geodetic\s*:[^\n]+",
        f"Center geodetic : {coordinates} {{E-lon(deg),Lat(deg),Alt(km)}}",
        envelope["result"],
    )
    return io.BytesIO(json.dumps(envelope).encode("utf-8"))


@unittest.skipUnless(rasterio is not None, "requires the gis extra; mandatory in custom-test image")
class CustomGeoTiffHttpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dem_directory = self.root / "dems"
        self.dem_directory.mkdir()
        self.settings = CustomSettings(
            enabled=True,
            terrain_enabled=True,
            archive_directory=self.root / "ephemeris",
            terrain_cache_directory=self.root / "terrain",
            dem_directory=self.dem_directory,
            timeout_seconds=10,
        )
        self.runtime = CustomRuntime(self.settings)
        self.addCleanup(self.runtime.close)
        self.app = create_app()
        self.app.dependency_overrides[get_custom_runtime] = lambda: self.runtime
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def write_dems(self, *, far_gap=False, far_crs=CRS):
        x, y = (float(value) for value in latlon_to_stereographic(-89, 0))
        products = dict(PRODUCTS)
        self.hashes = {}
        for product_id, width in ((NEAR_FIELD, 128), (FAR_FIELD, 64)):
            product = PRODUCTS[product_id]
            data = np.full((width, width), 100.0, dtype="float32")
            if product_id == FAR_FIELD and far_gap:
                center = width // 2
                data[center - 1 : center + 1, center - 1 : center + 1] = np.nan
            path = self.dem_directory / product.filename
            resolution = product.resolution_m
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=width,
                height=width,
                count=1,
                dtype="float32",
                crs=far_crs if product_id == FAR_FIELD else CRS,
                transform=from_origin(
                    x - width * resolution / 2,
                    y + width * resolution / 2,
                    resolution,
                    resolution,
                ),
                nodata=np.nan,
            ) as dataset:
                dataset.write(data, 1)
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            self.hashes[product_id] = checksum
            products[product_id] = replace(product, size_bytes=path.stat().st_size)
            sidecar_path(path).write_text(
                json.dumps(
                    {
                        "productId": product_id,
                        "role": product.role,
                        "sourceUrl": product.url,
                        "sizeBytes": path.stat().st_size,
                        "mtimeNs": path.stat().st_mtime_ns,
                        "sha256": checksum,
                        "retrievedAtUtc": "2026-11-14T00:00:00Z",
                        "resolutionM": resolution,
                    }
                ),
                encoding="utf-8",
            )
        product_patch = patch("lunarwindow.terrain.custom.PRODUCTS", products)
        product_patch.start()
        self.addCleanup(product_patch.stop)

        def small_fixture_parameters(**changes):
            # A short test extent is sufficient to check actual GIS integration;
            # it makes no claim about the production 200 km model's science.
            return default_parameters(
                **(changes | {"maxRangeKm": 0.1, "nearFieldKm": 0.05, "raysPerDegree": 1})
            )

        parameter_patch = patch(
            "lunarwindow.terrain.custom.default_parameters", side_effect=small_fixture_parameters
        )
        parameter_patch.start()
        self.addCleanup(parameter_patch.stop)

    def test_real_geotiff_horizon_http_reuse_and_source_corruption_before_warm_cache(self):
        self.write_dems()
        with patch(UPSTREAM, side_effect=synthetic_observer_response) as upstream:
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        CustomEvaluation.model_validate(result)
        self.assertEqual(upstream.call_count, 2)
        self.assertEqual(result["observer"]["surfaceElevationM"], 100)
        self.assertEqual(result["observer"]["mastHeightM"], 2)
        self.assertEqual(result["observer"]["altitudeKm"], 0.102)
        coordinates = {
            parse_qs(urlsplit(call.args[0].full_url).query)["SITE_COORD"][0]
            for call in upstream.call_args_list
        }
        self.assertEqual(coordinates, {"'0.0,-89.0,0.102'"})
        terrain = result["provenance"]["terrain"]
        profile = HorizonProfile.model_validate(terrain["profile"])
        mask = TerrainMask.model_validate(terrain["mask"])
        self.assertEqual(canonical_model_sha256(profile), terrain["profileSha256"])
        self.assertEqual(canonical_model_sha256(mask), terrain["maskSha256"])
        self.assertEqual(terrain["reviewStatus"], "preliminary")
        self.assertEqual(profile.quality.missingSampleFraction, 0)
        self.assertEqual(profile.quality.truncatedAzimuths, [])
        self.assertEqual(result["horizon"], terrain["mask"]["horizon"])
        self.assertEqual(
            {source.productId: source.sourceSha256 for source in mask.provenance.sources},
            self.hashes,
        )
        self.assertTrue(all("stere" in source.crs.lower() for source in mask.provenance.sources))
        self.assertEqual(len(list(self.settings.terrain_cache_directory.glob("*.json"))), 1)
        self.assertEqual(len(list(self.settings.archive_directory.glob("*.json"))), 1)
        with patch(UPSTREAM, side_effect=AssertionError("No NASA on verified cache reuse")):
            cached = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertEqual(cached.json(), result)
        sidecar_path(self.dem_directory / PRODUCTS[NEAR_FIELD].filename).unlink()
        with patch(UPSTREAM, side_effect=AssertionError("Corrupt DEMs must fail before NASA")):
            failed = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(failed.json()["error"]["code"], "custom_data_unavailable")
        self.assertNotIn(str(self.root), failed.text)

    def test_geotiff_missing_ray_samples_are_rejected_without_a_bare_sphere_fallback(self):
        self.write_dems(far_gap=True)
        with patch(UPSTREAM, side_effect=AssertionError("Incomplete terrain must not fetch NASA")):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertEqual(list(self.settings.archive_directory.glob("*.json")), [])
        self.assertEqual(list(self.settings.terrain_cache_directory.glob("*.json")), [])

    def test_wrong_geotiff_projection_is_rejected_even_with_matching_source_checksums(self):
        self.write_dems(far_crs="EPSG:4326")
        opened = []
        real_open = rasterio.open

        def track_open(*args, **kwargs):
            dataset = real_open(*args, **kwargs)
            opened.append(dataset)
            return dataset

        with (
            patch("rasterio.open", side_effect=track_open),
            patch(UPSTREAM, side_effect=AssertionError("Incorrect DEM frame must not fetch NASA")),
        ):
            response = self.client.post(ENDPOINT, json=REQUEST)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["error"]["code"], "custom_data_unavailable")
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(len(opened), 2)
        self.assertTrue(all(dataset.closed for dataset in opened))
