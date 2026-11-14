"""Turn candidate-region polygons into one documented representative point per region.

Artemis III candidate regions are ~15 × 15 km areas, not points. For each region this picks
the 120 m pixel with the highest long-term average solar visibility (NASA PGDA
AVGVISIB_75S_120M_201608) among pixels whose LOLA slope is at most `max_slope_deg`, breaking
ties by average Earth visibility. The rule is reproducible and recorded in each entry; the
result is a representative point for comparison, never a proposed landing target.

Polygons are read from GeoJSON (RFC 7946 lon/lat degrees) or an ESRI shapefile with a .prj
(needs the `gis` extra: pyshp + Rasterio). Features sharing a name are merged.
"""

import json
import math
import re
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from .dem import DemSource, Grid
from .geometry import latlon_to_stereographic, stereographic_to_latlon
from .products import FAR_FIELD, PRODUCTS

NAME_FIELDS = ("name", "Name", "NAME", "region", "Region", "REGION", "Site_Name", "SITE_NAME")
STEREO_PROJ4 = "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _pick_name(properties: dict, name_field: str | None) -> str:
    if name_field:
        return str(properties[name_field]).strip()
    for field in NAME_FIELDS:
        if properties.get(field):
            return str(properties[field]).strip()
    raise ValueError(f"No name field in {sorted(properties)}; pass --name-field.")


def _rings_from_geometry(geometry: dict) -> list[list[tuple[float, float]]]:
    if geometry["type"] == "Polygon":
        return [list(map(tuple, ring)) for ring in geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return [list(map(tuple, ring)) for poly in geometry["coordinates"] for ring in poly]
    raise ValueError(f"Unsupported geometry {geometry['type']}; expected (Multi)Polygon.")


def _project_lonlat(rings):
    projected = []
    for ring in rings:
        lon, lat = np.array(ring, dtype=float).T
        if np.any(np.abs(lat) > 90) or np.any(np.abs(lon) > 360):
            raise ValueError("GeoJSON coordinates must be lon/lat degrees (RFC 7946).")
        lon = (lon + 180) % 360 - 180
        x, y = latlon_to_stereographic(lat, lon)
        projected.append(np.column_stack([x, y]))
    return projected


def read_polygons(path: Path, name_field: str | None = None) -> dict[str, list[np.ndarray]]:
    """Return {region name: [rings as (N, 2) polar stereographic metres]}."""
    path = Path(path)
    regions: dict[str, list[np.ndarray]] = {}
    if path.suffix.lower() in {".json", ".geojson"}:
        data = json.loads(path.read_text(encoding="utf-8"))
        for feature in data["features"]:
            name = _pick_name(feature.get("properties") or {}, name_field)
            regions.setdefault(name, []).extend(
                _project_lonlat(_rings_from_geometry(feature["geometry"]))
            )
        return regions
    if path.suffix.lower() == ".shp":
        import shapefile
        from rasterio.crs import CRS
        from rasterio.warp import transform

        prj = path.with_suffix(".prj")
        if not prj.exists():
            raise ValueError(f"{path}: missing .prj; the polygon CRS must be explicit.")
        source = CRS.from_wkt(prj.read_text(encoding="utf-8", errors="replace"))
        target = CRS.from_proj4(STEREO_PROJ4)
        with shapefile.Reader(str(path)) as reader:
            for record in reader.iterShapeRecords():
                name = _pick_name(record.record.as_dict(), name_field)
                geometry = record.shape.__geo_interface__
                for ring in _rings_from_geometry(geometry):
                    xs, ys = np.array(ring, dtype=float).T
                    if source.is_geographic:
                        lon = (xs + 180) % 360 - 180
                        tx, ty = latlon_to_stereographic(ys, lon)
                    else:
                        tx, ty = transform(source, target, xs.tolist(), ys.tolist())
                    regions.setdefault(name, []).append(np.column_stack([tx, ty]))
        return regions
    raise ValueError(f"{path}: use .geojson/.json (lon/lat) or .shp with .prj.")


def points_in_rings(x: np.ndarray, y: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Even-odd rule across all rings, so holes and multipolygons work."""
    inside = np.zeros(x.shape, dtype=bool)
    for ring in rings:
        x1, y1 = ring[:, 0], ring[:, 1]
        x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        for ax, ay, bx, by in zip(x1, y1, x2, y2):
            if ay == by:
                continue
            crosses = (ay > y) != (by > y)
            xint = ax + (y - ay) * (bx - ax) / (by - ay)
            inside ^= crosses & (x < xint)
    return inside


def ring_area_m2(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def polygon_area_m2(rings: list[np.ndarray]) -> float:
    """Even-odd area: rings nested at odd depth (holes) subtract, matching points_in_rings."""
    total = 0.0
    for index, ring in enumerate(rings):
        others = [other for j, other in enumerate(rings) if j != index]
        depth = int(points_in_rings(ring[:1, 0], ring[:1, 1], others)[0]) if others else 0
        total += ring_area_m2(ring) * (-1 if depth % 2 else 1)
    return total


def slope_grid(dem: Grid) -> Grid:
    dy, dx = np.gradient(dem.data, dem.resolution_m)
    slope = np.degrees(np.arctan(np.hypot(dx, dy)))
    return Grid(slope, dem.left, dem.top, dem.resolution_m, dem.source)


def representative_point(
    rings: list[np.ndarray], sun: Grid, earth: Grid, slope: Grid, max_slope_deg: float
) -> dict:
    allxy = np.vstack(rings)
    res = sun.resolution_m
    cols = np.arange(
        math.floor((allxy[:, 0].min() - sun.left) / res),
        math.ceil((allxy[:, 0].max() - sun.left) / res),
    )
    rows = np.arange(
        math.floor((sun.top - allxy[:, 1].max()) / res),
        math.ceil((sun.top - allxy[:, 1].min()) / res),
    )
    xs, ys = np.meshgrid(sun.left + (cols + 0.5) * res, sun.top - (rows + 0.5) * res)
    inside = points_in_rings(xs, ys, rings)
    if not inside.any():
        raise ValueError("Polygon contains no visibility-map pixel centres.")
    x, y = xs[inside], ys[inside]
    sun_v, earth_v, slope_v = sun.sample(x, y), earth.sample(x, y), slope.sample(x, y)
    ok = np.isfinite(sun_v) & np.isfinite(slope_v) & (slope_v <= max_slope_deg)
    if not ok.any():
        raise ValueError(f"No pixel inside the polygon has slope <= {max_slope_deg}°.")
    earth_score = np.where(np.isfinite(earth_v), earth_v, -1)
    order = np.lexsort((-earth_score[ok], -sun_v[ok]))
    best = np.flatnonzero(ok)[order[0]]
    lat, lon = (float(v) for v in stereographic_to_latlon(x[best], y[best]))
    outer = max(rings, key=ring_area_m2)
    cx, cy = outer[:, 0].mean(), outer[:, 1].mean()
    clat, clon = (float(v) for v in stereographic_to_latlon(cx, cy))
    scale = 2 / (1 - math.sin(math.radians(clat)))  # Stereographic linear scale factor.
    return {
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "avgSunPct": round(float(sun_v[best]) * 100, 1),
        "avgEarthPct": None if earth_score[best] < 0 else round(float(earth_v[best]) * 100, 1),
        "slopeDeg": round(float(slope_v[best]), 2),
        "candidatePixels": int(ok.sum()),
        "polygonCentroidLat": round(clat, 6),
        "polygonCentroidLon": round(clon, 6),
        "polygonAreaKm2": round(polygon_area_m2(rings) / scale**2 / 1e6, 1),
    }


def build_region_catalog(
    polygons: Path,
    dem_dir: Path,
    polygon_source: str,
    name_field: str | None = None,
    max_slope_deg: float = 10.0,
    id_prefix: str = "artemis3-",
    name_suffix: str = " (Artemis III candidate region)",
) -> list[dict]:
    regions = read_polygons(polygons, name_field)
    entries = []
    with ExitStack() as stack:
        sources = {}
        for product_id in ("AVGVISIB_75S_120M_201608", "AVGVISIB_75S_120M_201608_EARTH", FAR_FIELD):
            path = Path(dem_dir) / PRODUCTS[product_id].filename
            if not path.exists():
                raise FileNotFoundError(f"{path} missing; run `lunarwindow-terrain download`.")
            sources[product_id] = stack.enter_context(DemSource(path))
        for name, rings in sorted(regions.items()):
            allxy = np.vstack(rings)
            cx, cy = allxy.mean(axis=0)
            radius = float(np.hypot(*(allxy - [cx, cy]).T).max()) + 1000
            sun = sources["AVGVISIB_75S_120M_201608"].read_patch(cx, cy, radius)
            earth = sources["AVGVISIB_75S_120M_201608_EARTH"].read_patch(cx, cy, radius)
            dem = sources[FAR_FIELD].read_patch(cx, cy, radius)
            if sun is None or earth is None or dem is None:
                raise ValueError(f"{name}: outside the visibility maps or DEM.")
            stats = representative_point(rings, sun, earth, slope_grid(dem), max_slope_deg)
            entries.append(
                {
                    "id": id_prefix + slugify(name),
                    "name": name + name_suffix,
                    "kind": "candidate-region",
                    "lat": stats["lat"],
                    "lon": stats["lon"],
                    "terrain": "lola-dem",
                    "coordinateSource": (
                        f"Representative point inside the '{name}' polygon from {polygon_source}; "
                        "highest long-term average solar visibility (NASA PGDA "
                        "AVGVISIB_75S_120M_201608, ties by Earth visibility) among 120 m "
                        f"pixels with LOLA LDEM_60S_120MPP_ADJ slope <= {max_slope_deg:g} deg. "
                        "Not a landing target."
                    ),
                    "region": stats
                    | {"polygonSource": polygon_source, "maxSlopeDeg": max_slope_deg},
                }
            )
    return entries
