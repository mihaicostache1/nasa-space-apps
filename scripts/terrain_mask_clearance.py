"""Sun/Earth clearance and spatial-representativeness diagnostics for one exported mask.

Shifted and coarse variants use the 5 m tile only within 7.98 km, a conservative bound inside
both Site04 and Site23 tile patches.

    python scripts/terrain_mask_clearance.py MASK.json SITE_TILE_ID DEM_DIR HORIZONS_CACHE
Reports, over one year at 6 h steps, the best (upper limb - horizon) margin for Earth and Sun,
with the committed mask and with coarser terrain models (20 m only, 120 m only), and with the
observer moved +-60 m (half a PGDA 120 m pixel) in the four map directions.
"""

import json
import sys
from pathlib import Path

import numpy as np
from lunarwindow.ephemeris import HorizonsClient, Site, TimeRange
from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.terrain.dem import DemSource
from lunarwindow.terrain.geometry import (
    latlon_to_stereographic,
    stereographic_to_latlon,
)
from lunarwindow.terrain.horizon import SiteSpec, compute_horizon, default_parameters
from lunarwindow.terrain.products import FAR_FIELD, NEAR_FIELD, PRODUCTS


def interp(h, az):
    h = np.asarray(h)
    i = np.floor(az).astype(int) % 360
    f = az - np.floor(az)
    return h[i] * (1 - f) + h[(i + 1) % 360] * f


def margins(series, h):
    out = {}
    for body in ("sun", "earth"):
        az = np.array([r[f"{body}Az"] for r in series]) % 360
        el = np.array([r[f"{body}El"] for r in series])
        rad = np.array([r[f"{body}AngularRadiusDeg"] for r in series])
        m = el + rad - interp(h, az)
        k = int(m.argmax())
        out[body] = {
            "bestUpperLimbMarginDeg": round(float(m.max()), 3),
            "atAz": round(float(az[k]), 1),
            "bodyEl": round(float(el[k]), 3),
            "pctVisible": round(100 * float((m > 0).mean()), 1),
            "azRange": [round(float(az.min()), 1), round(float(az.max()), 1)],
            "elMax": round(float(el.max()), 2),
        }
    return out


def main():
    mask_path, tile_id, dem_dir, cache = sys.argv[1:5]
    dem_dir = Path(dem_dir)
    mask = json.loads(Path(mask_path).read_text())
    site_id = mask["siteId"]
    ob = mask["observer"]
    year = TimeRange("2026-11-14T00:00:00Z", "2027-11-14T00:00:00Z", 360)
    client = HorizonsClient(Path(cache))
    series = validate_dataset(
        client.evaluate(
            Site(
                site_id,
                mask["site"],
                ob["lat"],
                ob["lon"],
                round(round(ob["altitudeKm"]), 6),
                ob["coordinateSource"],
            ),
            year,
        )
    )["series"]
    result = {"committed": margins(series, [p["el"] for p in mask["horizon"]])}
    with (
        DemSource(dem_dir / PRODUCTS[tile_id].filename) as fine,
        DemSource(dem_dir / PRODUCTS[NEAR_FIELD].filename) as near,
        DemSource(dem_dir / PRODUCTS[FAR_FIELD].filename) as far,
    ):
        x0, y0 = (float(v) for v in latlon_to_stereographic(ob["lat"], ob["lon"]))
        npch = near.read_patch(x0, y0, 27000)
        fpch = far.read_patch(x0, y0, 211000)
        tile = fine.read_patch(x0, y0, 9000)

        def horizon(x, y, use_fine=True, use_near=True, min_d=60.0):
            lat, lon = (float(v) for v in stereographic_to_latlon(x, y))
            params = default_parameters(
                mastHeightM=0.0, stepGrowth=0.0, minDistanceM=min_d
            )
            prof = compute_horizon(
                SiteSpec(site_id, "", lat, lon, ""),
                npch if use_near else None,
                fpch,
                params,
                fine=tile if use_fine else None,
                fine_field_m=7980.0 if use_fine else 0.0,
                require_complete=True,
            )
            return [p.el for p in prof.horizon], prof.surfaceElevationM

        h, _ = horizon(x0, y0, use_fine=False)
        result["20m+120m (no 5 m tier)"] = margins(series, h)
        h, s = horizon(x0, y0, use_fine=False, use_near=False, min_d=120.0)
        result["120m only, from 120 m"] = margins(series, h) | {"surfaceM": s}
        for dx, dy in ((60, 0), (-60, 0), (0, 60), (0, -60)):
            h, s = horizon(x0 + dx, y0 + dy)
            result[f"shift dx={dx} dy={dy} m"] = margins(series, h) | {
                "surfaceM": round(s, 1)
            }
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
