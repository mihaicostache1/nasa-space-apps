"""Catalog, region, export/verify, and service tests on small synthetic LOLA-like GeoTIFFs.

The GeoTIFF tests need the `gis` extra (Rasterio, pyshp) and are skipped without it.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from lunarwindow.terrain.catalog import load_catalog
from lunarwindow.terrain.dem import Grid
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.regions import points_in_rings, representative_point, slugify

try:
    import rasterio
    from rasterio.transform import from_origin

    HAVE_RASTERIO = True
except ImportError:  # pragma: no cover - depends on installed extras
    HAVE_RASTERIO = False

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(os.environ.get("LUNARWINDOW_REFERENCE_DIR", str(ROOT / "data/reference")))
DATA = REFERENCE.parent
STEREO = "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m"


def write_tif(path, data, left, top, res, dtype="float32", nodata=np.nan, scale=1.0):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=dtype,
        crs=STEREO,
        transform=from_origin(left, top, res, res),
        nodata=nodata,
    ) as dataset:
        dataset.write(data.astype(dtype), 1)
        if scale != 1.0:
            dataset.scales = (scale,)


def entry(**changes):
    return {
        "id": "test-point",
        "name": "Test point",
        "kind": "landing-target",
        "lat": -88.0,
        "lon": 40.0,
        "terrain": "lola-dem",
        "coordinateSource": "Synthetic",
    } | changes


class CatalogTests(unittest.TestCase):
    def test_committed_catalog_is_valid_and_sourced(self):
        sites = load_catalog([DATA / "sites.curated.json"])
        self.assertGreaterEqual(len(sites), 7)
        for site in sites:
            self.assertIn("http", site.coordinate_source)
        by_id = {site.site_id: site for site in sites}
        self.assertEqual(by_id["apollo-11"].terrain, "none")
        reference = json.loads((REFERENCE / "sites.nasa.json").read_text())
        for row in reference:  # Same points as the committed 30-day ephemeris bundle.
            self.assertEqual((by_id[row["id"]].lat, by_id[row["id"]].lon), (row["lat"], row["lon"]))

    def test_rejects_bad_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sites.json"
            for bad in (
                [entry(kind="guess")],
                [entry(terrain="maybe")],
                [entry(id="Bad ID")],
                [entry(extra=1)],
                [entry(), entry()],
                [entry(lon=200)],
            ):
                path.write_text(json.dumps(bad))
                with self.assertRaises((ValueError, KeyError), msg=bad):
                    load_catalog([path])


class RegionTests(unittest.TestCase):
    def test_point_in_polygon_with_hole(self):
        outer = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        hole = np.array([[4, 4], [6, 4], [6, 6], [4, 6]], dtype=float)
        x = np.array([1.0, 5.0, 11.0])
        y = np.array([1.0, 5.0, 5.0])
        self.assertEqual(points_in_rings(x, y, [outer, hole]).tolist(), [True, False, False])

    def test_representative_point_prefers_sun_then_flat_ground(self):
        cx, cy = (float(v) for v in latlon_to_stereographic(-87.0, 10.0))
        n, res = 40, 120.0
        left, top = cx - n * res / 2, cy + n * res / 2
        sun = np.full((n, n), 0.5)
        sun[10, 10] = 0.95  # Brightest, but steep: must be rejected.
        sun[25, 30] = 0.9  # Best flat pixel.
        earth = np.full((n, n), 0.3)
        slope = np.full((n, n), 2.0)
        slope[10, 10] = 25.0
        grids = [Grid(a, left, top, res) for a in (sun, earth, slope)]
        ring = np.array(
            [
                [left + 2 * res, top - 2 * res],
                [left + 38 * res, top - 2 * res],
                [left + 38 * res, top - 38 * res],
                [left + 2 * res, top - 38 * res],
            ]
        )
        stats = representative_point([ring], *grids, max_slope_deg=10)
        expected = latlon_to_stereographic(stats["lat"], stats["lon"])
        self.assertAlmostEqual(float(expected[0]), left + 30.5 * res, delta=1)
        self.assertAlmostEqual(float(expected[1]), top - 25.5 * res, delta=1)
        self.assertEqual(stats["avgSunPct"], 90.0)
        self.assertAlmostEqual(stats["polygonAreaKm2"], (36 * 0.12) ** 2, delta=0.3)
        self.assertEqual(slugify("de Gerlache Rim 2"), "de-gerlache-rim-2")


@unittest.skipUnless(HAVE_RASTERIO, "requires the gis extra")
class PolygonInputTests(unittest.TestCase):
    """Region polygons arrive as GeoJSON (lon/lat) or shapefiles in any declared CRS."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lonlat = [(10.0, -87.0), (12.0, -87.0), (12.0, -86.8), (10.0, -86.8), (10.0, -87.0)]
        self.expected = np.column_stack(
            latlon_to_stereographic([p[1] for p in self.lonlat], [p[0] for p in self.lonlat])
        )

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, regions, name="Haworth"):
        self.assertEqual(list(regions), [name])
        ring = regions[name][0]
        for vertex in self.expected:  # Order-insensitive: writers may reorient rings.
            self.assertLess(np.hypot(*(ring - vertex).T).min(), 0.01)

    def test_geojson(self):
        from lunarwindow.terrain.regions import read_polygons

        path = self.dir / "regions.geojson"
        feature = {
            "type": "Feature",
            "properties": {"Name": "Haworth"},
            "geometry": {"type": "Polygon", "coordinates": [self.lonlat]},
        }
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
        self.check(read_polygons(path))

    def test_projected_and_geographic_shapefiles(self):
        import shapefile
        from rasterio.crs import CRS

        from lunarwindow.terrain.regions import read_polygons

        for label, points, wkt in (
            ("projected", self.expected.tolist(), CRS.from_proj4(STEREO).to_wkt()),
            ("geographic", self.lonlat, CRS.from_proj4("+proj=longlat +R=1737400").to_wkt()),
        ):
            base = self.dir / label
            x, y = np.array(points).T
            if np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)) > 0:
                points = points[::-1]  # Shapefile outer rings are clockwise.
            with shapefile.Writer(str(base), shapeType=shapefile.POLYGON) as writer:
                writer.field("SITE_NAME", "C")
                writer.poly([points])
                writer.record("Haworth")
            base.with_suffix(".prj").write_text(wkt)
            self.check(read_polygons(base.with_suffix(".shp"), "SITE_NAME"))
            base.with_suffix(".prj").unlink()
            with self.assertRaises(ValueError):
                read_polygons(base.with_suffix(".shp"), "SITE_NAME")


@unittest.skipUnless(HAVE_RASTERIO, "requires the gis extra")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dem_dir = self.dir / "lola"
        self.dem_dir.mkdir()
        # A 300 m crater-rim-like ring 4 km from (-88, 40) on otherwise flat ground.
        from lunarwindow.terrain.geometry import great_circle_distance_m, stereographic_to_latlon

        cx, cy = (float(v) for v in latlon_to_stereographic(-88.0, 40.0))
        for name, half, res in (
            ("LDEM_80S_20MPP_ADJ.TIF", 6000, 40),
            ("LDEM_60S_120MPP_ADJ.TIF", 15000, 120),
        ):
            n = int(2 * half / res)
            left, top = cx - half, cy + half
            centres = (np.arange(n) + 0.5) * res
            xs, ys = np.meshgrid(left + centres, top - centres)
            lat, lon = stereographic_to_latlon(xs, ys)
            d = great_circle_distance_m(-88.0, 40.0, lat, lon)
            data = np.where((d > 4000) & (d < 4600), 300.0, 0.0)
            data[0, 0] = np.nan
            write_tif(self.dem_dir / name, data, left, top, res)
        self.catalog = self.dir / "sites.json"
        self.catalog.write_text(
            json.dumps([entry(), entry(id="flat-contrast", lat=0.67, lon=23.47, terrain="none")])
        )

    def tearDown(self):
        self.tmp.cleanup()

    def params(self):
        from lunarwindow.terrain.horizon import default_parameters

        return default_parameters(
            maxRangeKm=12, nearFieldKm=5, raysPerDegree=2, stepGrowth=0.002, minDistanceM=80
        )

    def test_export_verify_and_load(self):
        from lunarwindow.terrain.export import export_horizons, load_horizons, verify_horizon_run
        from lunarwindow.terrain.geometry import elevation_angle_deg

        run = export_horizons(
            load_catalog([self.catalog]), self.dem_dir, self.dir / "out", self.params()
        )
        profiles = load_horizons(run)
        point = profiles["test-point"]
        expected = float(elevation_angle_deg(4000, 300, 2))
        self.assertAlmostEqual(min(p.el for p in point.horizon), expected, delta=0.15)
        self.assertEqual(point.sources[0].productId, "LDEM_80S_20MPP_ADJ")
        self.assertEqual(
            point.quality.truncatedAzimuths, []
        )  # 12 km rays stay inside the 15 km far grid.
        self.assertEqual(profiles["flat-contrast"].terrainModel, "none")
        rows = json.loads((run / "sites.json").read_text())
        self.assertEqual(rows[0]["altitudeKm"], point.observerAltitudeKm)
        self.assertIn("mast", rows[0]["coordinateSource"])

        (run / "test-point.json").write_text("{}")
        with self.assertRaises(ValueError):
            verify_horizon_run(run)

    def test_outside_coverage_requires_explicit_none(self):
        from lunarwindow.terrain.export import export_horizons

        self.catalog.write_text(json.dumps([entry(lat=-70.0)]))
        with self.assertRaises(ValueError):
            export_horizons(
                load_catalog([self.catalog]), self.dem_dir, self.dir / "out", self.params()
            )

    def test_service_caches_and_falls_back_only_on_request(self):
        from lunarwindow.terrain.service import HorizonService

        service = HorizonService(self.dem_dir, self.dir / "cache", self.params())
        try:
            first = service.horizon(-88.0, 40.0)
            self.assertEqual(len(list((self.dir / "cache").glob("*.json"))), 1)
            again = service.horizon(-88.0, 40.0, site_id="named", name="Named")
            self.assertEqual(again.horizon, first.horizon)
            self.assertEqual(again.siteId, "named")
            taller = service.horizon(-88.0, 40.0, mast_height_m=50)
            self.assertLess(taller.horizon[0].el, first.horizon[0].el)
            with self.assertRaises(ValueError):
                service.horizon(-60.0, 0.0)
            bare = service.horizon(-60.0, 0.0, allow_bare_sphere=True)
            self.assertEqual(bare.terrainModel, "none")
        finally:
            service.close()

    def test_scaled_int16_rasters_and_crs_check(self):
        from lunarwindow.terrain.dem import DemSource

        cx, cy = (float(v) for v in latlon_to_stereographic(-87.0, 0.0))
        data = np.full((10, 10), 25000, dtype="int16")
        data[0, 0] = -32768
        path = self.dir / "AVGVISIB_test.TIF"
        write_tif(path, data, cx - 600, cy + 600, 120, "int16", -32768, scale=4e-5)
        with DemSource(path) as source:
            patch = source.read_patch(cx, cy, 2000)
            self.assertAlmostEqual(float(patch.sample(cx, cy)), 1.0, places=6)
            self.assertTrue(np.isnan(patch.data[0, 0]))
        bad = self.dir / "bad.tif"
        with rasterio.open(
            bad,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype="float32",
            crs="+proj=longlat +R=1737400",
            transform=from_origin(10, 10, 1, 1),
        ) as dataset:
            dataset.write(np.zeros((4, 4), dtype="float32"), 1)
        with self.assertRaises(ValueError):
            DemSource(bad)


if __name__ == "__main__":
    unittest.main()
