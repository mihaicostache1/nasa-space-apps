"""Review checks for one exported terrain mask (evidence for its README).

    python scripts/review_terrain_mask.py MASK.json SITE_TILE_ID DEM_DIR HORIZONS_CACHE OUT.json

Checks: contract/schema/loader/round trip, observer vs archived 30-day ephemeris, frame
compatibility policy (rejected without opt-in, approximate with it), full DEM re-hash, centre
pixel, regeneration, convergence and sensitivity variants (production code), 30-day join, and
one modelled year (6 h, Horizons via the local cache) against the PGDA AVGVISIB maps.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from lunarwindow.ephemeris import HorizonsClient, Site, TimeRange
from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.terrain.compatibility import (
    TerrainCompatibilityError,
    check_terrain_compatibility,
)
from lunarwindow.terrain.dem import DemSource
from lunarwindow.terrain.download import sha256_file
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.horizon import SiteSpec, compute_horizon, default_parameters
from lunarwindow.terrain.loader import load_terrain_mask
from lunarwindow.terrain.models import TerrainMask
from lunarwindow.terrain.products import FAR_FIELD, NEAR_FIELD, PRODUCTS
from lunarwindow.visibility import calculate_visibility

ROOT = Path(__file__).resolve().parents[1]
FLAT = [{"az": az, "el": 0.0} for az in range(360)]
KEYS = (
    "t",
    "sunAz",
    "sunEl",
    "earthAz",
    "earthEl",
    "sunAngularRadiusDeg",
    "earthAngularRadiusDeg",
)


def vis(series, horizon, period):
    rows = [{k: r[k] for k in KEYS} for r in series]
    m = calculate_visibility(rows, horizon, period, rule="any-disc").metrics
    return {
        "pctSun": round(m.pctSun, 1),
        "pctEarth": round(m.pctEarth, 1),
        "pctBoth": round(m.pctBoth, 1),
        "longestDarkHrs": m.longestDarkHrs,
    }


def main():
    mask_path, tile_id, dem_dir, cache, out = sys.argv[1:6]
    mask_path, dem_dir, worktree = Path(mask_path), Path(dem_dir), ROOT
    site_id = json.loads(mask_path.read_text())["siteId"]
    content = mask_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    sidecar = mask_path.with_suffix(".json.sha256").read_text().split()[0]
    report = {"siteId": site_id, "sha256": digest, "sidecarMatches": digest == sidecar}

    # 1. Contract, loader, round trip, JSON Schema.
    mask = TerrainMask.model_validate_json(content)
    load_terrain_mask(mask_path, expected_sha256=digest)
    report["roundTripIdentical"] = json.loads(mask.model_dump_json()) == json.loads(
        content
    )
    try:
        import jsonschema

        jsonschema.validate(json.loads(content), TerrainMask.model_json_schema())
        report["jsonSchema"] = "valid"
    except ImportError:
        report["jsonSchema"] = "jsonschema not installed"

    # 2. Observer identical to the archived ephemeris; compatibility policy.
    ref_dir = worktree / "data/reference/validation-30d"
    raw = (ref_dir / f"{site_id}.json").read_bytes()
    manifest = json.loads((ref_dir / "manifest.json").read_text())
    entry = next(d for d in manifest["datasets"] if d["siteId"] == site_id)
    report["ephemerisSha256MatchesManifest"] = (
        hashlib.sha256(raw).hexdigest() == entry["jsonSha256"]
    )
    dataset = validate_dataset(json.loads(raw))
    ob = mask.observer
    report["observerBitIdentical"] = (
        ob.lat == dataset["lat"]
        and ob.lon == dataset["lon"]
        and ob.altitudeKm == dataset["altitudeKm"]
    )
    report["coordinateSourceIdentical"] = (
        ob.coordinateSource == dataset["coordinateSource"]
    )
    report["siteNameIdentical"] = mask.site == dataset["site"]
    try:
        check_terrain_compatibility(mask, dataset)
        report["compatibilityWithoutOptIn"] = "accepted (unexpected)"
    except TerrainCompatibilityError as exc:
        report["compatibilityWithoutOptIn"] = f"rejected: {exc}"
    c = check_terrain_compatibility(mask, dataset, allow_mean_earth_approximation=True)
    report["compatibilityWithOptIn"] = {
        "frameStatus": c.frame_status,
        "ephemerisFrame": c.ephemeris_frame,
        "ephemerisSource": c.ephemeris_dynamical_source,
        "transformationApplied": c.transformation_applied,
    }

    # 3. Source integrity and centre pixel.
    prov = json.loads((worktree / "data/reference/site-provenance.json").read_text())
    point = next(p for p in prov["points"] if p["siteId"] == site_id)
    hashes = {}
    for src in mask.provenance.sources:
        path = dem_dir / src.sourceUrl.rsplit("/", 1)[1]
        hashes[src.productId] = sha256_file(path) == src.sourceSha256
    report["sourceRehashMatches"] = hashes
    tile_src = mask.provenance.sources[0]
    report["tileSha256MatchesSiteProvenance"] = (
        tile_src.sourceSha256 == point["sourceSha256"]
    )
    with rasterio.open(dem_dir / PRODUCTS[tile_id].filename) as ds:
        pixel = float(ds.read(1)[point["row"], point["col"]])
    report["centrePixelM"] = pixel
    report["surfaceEqualsCentrePixel"] = (
        pixel == ob.surfaceElevationM == point["surfaceElevationMetres"]
    )

    # 4. Production-code variants (same setup as scripts/export_terrain_mask.py).
    lat, lon = ob.lat, ob.lon
    file_el = np.array([p.el for p in mask.horizon])
    with (
        DemSource(dem_dir / PRODUCTS[tile_id].filename) as fine,
        DemSource(dem_dir / PRODUCTS[NEAR_FIELD].filename) as near,
        DemSource(dem_dir / PRODUCTS[FAR_FIELD].filename) as far,
    ):
        x, y = (float(v) for v in latlon_to_stereographic(lat, lon))
        fp = fine.read_patch(x, y, 9000)
        edge = min(x - fp.left, fp.right - x, fp.top - y, y - fp.bottom)
        fine_field = edge - 2 * fine.resolution_m
        np_ = near.read_patch(x, y, 25 * 1050 + 40)
        farp = far.read_patch(x, y, 200 * 1050 + 240)
        site = SiteSpec(site_id, mask.site, lat, lon, ob.coordinateSource)
        report["fineFieldM"] = fine_field

        def run(fine_grid=fp, ff=fine_field, **chg):
            params = default_parameters(
                **(
                    {
                        "mastHeightM": 0.0,
                        "maxRangeKm": 200.0,
                        "nearFieldKm": 25.0,
                        "minDistanceM": 60.0,
                        "stepGrowth": 0.0,
                    }
                    | chg
                )
            )
            return compute_horizon(
                site,
                np_,
                farp,
                params,
                fine=fine_grid,
                fine_field_m=ff,
                require_complete=True,
            )

        base = run()
        base_el = np.array([p.el for p in base.horizon])
        dist = np.array(base.rays.horizonDistanceKm, dtype=float)
        report["regeneratedEqualsFile"] = bool(np.array_equal(base_el, file_el))
        report["quality"] = base.quality.model_dump()
        report["horizonRange"] = {
            "min": [int(file_el.argmin()), float(file_el.min())],
            "max": [int(file_el.argmax()), float(file_el.max())],
            "mean": round(float(file_el.mean()), 3),
        }
        report["horizonDistanceKm"] = {
            "median": float(np.median(dist)),
            "p90": float(np.percentile(dist, 90)),
            "max": float(dist.max()),
            "fractionRaysWithinFineTier": float((dist * 1000 <= fine_field).mean()),
            "fractionRaysWithin60mTo200m": float((dist <= 0.2).mean()),
        }
        variants = {
            "variableStep": run(stepGrowth=0.001),
            "maxRange100km": run(maxRangeKm=100.0),
            "minDistance20m": run(minDistanceM=20.0),
            "no5mTier": run(fine_grid=None, ff=0.0),
            "mast1m": run(mastHeightM=1.0),
            "mast2m": run(mastHeightM=2.0),
            "mast5m": run(mastHeightM=5.0),
            "mast10m": run(mastHeightM=10.0),
        }
        diffs = {}
        horizons = {"base": [p.model_dump() for p in mask.horizon]}
        for name, prof in variants.items():
            el = np.array([p.el for p in prof.horizon])
            d = el - file_el
            diffs[name] = {
                "maxAbsDeg": round(float(np.abs(d).max()), 4),
                "meanDeg": round(float(d.mean()), 4),
                "azOfMaxAbs": int(np.abs(d).argmax()),
            }
            horizons[name] = [p.model_dump() for p in prof.horizon]
        report["variants"] = diffs

    # 5. 30-day join with the archived ephemeris (mast variants reuse 0 m ephemeris: approx).
    period = TimeRange(
        dataset["provenance"]["startUtc"],
        dataset["provenance"]["endUtc"],
        dataset["provenance"]["stepMinutes"],
    )
    report["join30d"] = {
        "noTerrain": vis(dataset["series"], FLAT, period),
        "terrain": vis(dataset["series"], horizons["base"], period),
        **{
            f"{k}(0 m ephemeris, approx.)": vis(dataset["series"], horizons[k], period)
            for k in ("mast2m", "mast5m", "mast10m")
        },
    }

    # 6. One modelled year vs PGDA long-term maps at this pixel.
    year = TimeRange("2026-11-14T00:00:00Z", "2027-11-14T00:00:00Z", 360)
    alt = round(round(ob.altitudeKm), 6)
    client = HorizonsClient(Path(cache))
    yds = validate_dataset(
        client.evaluate(
            Site(site_id, mask.site, lat, lon, alt, ob.coordinateSource), year
        )
    )
    pgda = {}
    for key, pid in (
        ("sun", "AVGVISIB_75S_120M_201608"),
        ("earth", "AVGVISIB_75S_120M_201608_EARTH"),
    ):
        with DemSource(dem_dir / PRODUCTS[pid].filename) as src:
            patch = src.read_patch(x, y, 500)
            pgda[key] = round(float(patch.sample(x, y)) * 100, 1)
    report["year6h"] = {
        "ephemerisAltitudeKm(rounded, parallax <0.00015°/km)": alt,
        "terrain": vis(yds["series"], horizons["base"], year),
        "mast2m": vis(yds["series"], horizons["mast2m"], year),
        "no5mTier": vis(yds["series"], horizons["no5mTier"], year),
        "noTerrain": vis(yds["series"], FLAT, year),
        "pgdaAvgSunPct": pgda["sun"],
        "pgdaAvgEarthPct": pgda["earth"],
    }
    Path(out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
