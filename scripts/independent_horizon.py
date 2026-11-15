"""Independent horizon recomputation for review (no lunarwindow terrain code).

Reads the GeoTIFFs with rasterio, projects with its own south polar stereographic formulas,
walks great circles with the spherical destination formula, interpolates bilinearly at pixel
centres, and applies the documented definition:
  elevation = atan2((R+h)cos d - (R+h0), (R+h) sin d), d = s/R
  ray horizon = max over samples s = 60, 65, ... 200000 m
  degree value = max of the 10 rays az-0.5 .. az+0.4
Tiers: 5 m tile for s <= fine_field_m, 20 m DEM for s <= 25 km, 120 m DEM beyond.

usage: python -I scripts/independent_horizon.py MASK.json TILE.tif DEM20.tif DEM120.tif FINE_FIELD_M OUT.json
"""

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

R = 1737400.0


def to_xy(lat, lon):
    rho = 2 * R * np.tan(np.radians(90 + lat) / 2)
    lon = np.radians(lon)
    return rho * np.sin(lon), rho * np.cos(lon)


class Raster:
    def __init__(self, path, x, y, half):
        with rasterio.open(path) as ds:
            t = ds.transform
            assert t.b == 0 and t.d == 0 and t.a == -t.e
            self.res = t.a
            c0 = max(0, int(np.floor((x - half - t.c) / self.res)))
            c1 = min(ds.width, int(np.ceil((x + half - t.c) / self.res)))
            r0 = max(0, int(np.floor((t.f - (y + half)) / self.res)))
            r1 = min(ds.height, int(np.ceil((t.f - (y - half)) / self.res)))
            a = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), masked=True)
            self.z = np.ma.filled(a.astype(np.float64), np.nan)
            self.left = t.c + c0 * self.res
            self.top = t.f - r0 * self.res

    def bilinear(self, x, y):
        col = (x - self.left) / self.res - 0.5
        row = (self.top - y) / self.res - 0.5
        c, r = np.floor(col).astype(np.int64), np.floor(row).astype(np.int64)
        ok = (c >= 0) & (r >= 0) & (c + 1 < self.z.shape[1]) & (r + 1 < self.z.shape[0])
        c, r = np.where(ok, c, 0), np.where(ok, r, 0)
        fx, fy = col - c, row - r
        z = self.z
        v = (
            z[r, c] * (1 - fx) * (1 - fy)
            + z[r, c + 1] * fx * (1 - fy)
            + z[r + 1, c] * (1 - fx) * fy
            + z[r + 1, c + 1] * fx * fy
        )
        return np.where(ok, v, np.nan)


def main():
    mask_path, tile, dem20, dem120, fine_field, out = sys.argv[1:7]
    fine_field = float(fine_field)
    mask = json.loads(Path(mask_path).read_text())
    ob = mask["observer"]
    lat0, lon0 = np.radians(ob["lat"]), np.radians(ob["lon"])
    h0 = ob["altitudeKm"] * 1000
    x0, y0 = to_xy(ob["lat"], ob["lon"])
    fine = Raster(tile, x0, y0, 12000)
    near = Raster(dem20, x0, y0, 26000)
    far = Raster(dem120, x0, y0, 201000)
    ground = fine.bilinear(np.array([x0]), np.array([y0]))[0]
    s = np.arange(60.0, 200000.0 + 1e-6, 5.0)
    d = s / R
    az = np.radians(np.arange(3600) / 10)
    ray_el = np.empty(3600)
    ray_dist = np.empty(3600)
    missing = 0
    for i0 in range(0, 3600, 20):
        a = az[i0 : i0 + 20, None]
        lat = np.arcsin(np.sin(lat0) * np.cos(d) + np.cos(lat0) * np.sin(d) * np.cos(a))
        lon = lon0 + np.arctan2(
            np.sin(a) * np.sin(d) * np.cos(lat0), np.cos(d) - np.sin(lat0) * np.sin(lat)
        )
        x, y = to_xy(np.degrees(lat), np.degrees(lon))
        h = np.full(x.shape, np.nan)
        m = np.broadcast_to(s <= fine_field, x.shape)
        h[m] = fine.bilinear(x[m], y[m])
        m = np.isnan(h) & (s <= 25000)
        h[m] = near.bilinear(x[m], y[m])
        m = np.isnan(h)
        h[m] = far.bilinear(x[m], y[m])
        missing += int(np.isnan(h).sum())
        el = np.degrees(np.arctan2((R + h) * np.cos(d) - (R + h0), (R + h) * np.sin(d)))
        el = np.where(np.isnan(el), -np.inf, el)
        k = el.argmax(axis=1)
        ray_el[i0 : i0 + 20] = el[np.arange(len(k)), k]
        ray_dist[i0 : i0 + 20] = s[k]
    bins = np.array(
        [max(ray_el[(10 * b + o) % 3600] for o in range(-5, 5)) for b in range(360)]
    )
    file_el = np.array([p["el"] for p in mask["horizon"]])
    result = {
        "maskId": mask["maskId"],
        "groundBilinearM": ground,
        "groundMinusMaskSurfaceM": ground - ob["surfaceElevationM"],
        "fineFieldM": fine_field,
        "samples": int(3600 * len(s)),
        "missingSamples": missing,
        "maxAbsDiffDeg": float(np.abs(bins - file_el).max()),
        "meanAbsDiffDeg": float(np.abs(bins - file_el).mean()),
        "independentMin": [int(bins.argmin()), float(bins.min())],
        "independentMax": [int(bins.argmax()), float(bins.max())],
        "rayHorizonDistanceKm": {
            "median": float(np.median(ray_dist) / 1000),
            "p90": float(np.percentile(ray_dist, 90) / 1000),
            "max": float(ray_dist.max() / 1000),
            "fractionWithinFineTier": float((ray_dist <= fine_field).mean()),
        },
    }
    Path(out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
