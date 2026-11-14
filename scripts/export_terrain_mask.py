"""Export one `lunarwindow.terrain-mask.v1` mask for an archived reference ephemeris site.

The observer is taken from the archived P1 dataset (coordinates and total altitude), and its
surface height is checked against the original 5 m PGDA site tile that produced it. The
horizon is ray-cast with a constant step through three DEM tiers (5 m site tile, 20 m
regional, 120 m polar) and rejected if any required sample lacks DEM data.

    python scripts/export_terrain_mask.py --site-id lola-site01-reference \
        --site-tile Site01_final_adj_5mpp_surf
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

from lunarwindow.terrain.dem import DemSource
from lunarwindow.terrain.download import USER_AGENT
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.horizon import (
    ALGORITHM_VERSION,
    SiteSpec,
    compute_horizon,
    default_parameters,
)
from lunarwindow.terrain.products import (
    FAR_FIELD,
    NEAR_FIELD,
    PRODUCTS,
    REFERENCE_RADIUS_M,
)

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "NASA GSFC Planetary Geology, Geophysics and Geochemistry Laboratory (PGDA), LOLA team"


def git_revision(allow_dirty: bool = False) -> str:
    def run(*args):
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    revision = run("rev-parse", "HEAD")
    if run("status", "--porcelain", "--", "backend/src", "scripts"):
        if allow_dirty:
            return revision + "-dirty (test output, not a reviewed artifact)"
        raise SystemExit(
            "Commit the terrain code first: the mask must name a clean revision."
        )
    return revision


def revision_label(provenance: dict) -> str:
    """Published file revision: Last-Modified/ETag from download time, or checked now."""
    last_modified, etag = provenance.get("lastModified"), provenance.get("etag")
    checked = ""
    if not last_modified:
        request = Request(
            provenance["sourceUrl"], method="HEAD", headers={"User-Agent": USER_AGENT}
        )
        with urlopen(request, timeout=60) as response:
            if int(response.headers["Content-Length"]) != provenance["sizeBytes"]:
                raise SystemExit(
                    f"{provenance['sourceUrl']} changed size since download."
                )
            last_modified, etag = (
                response.headers["Last-Modified"],
                response.headers.get("ETag"),
            )
            checked = " (header checked at export; size matches the hashed download)"
    stamp = parsedate_to_datetime(last_modified).astimezone(UTC)
    page = PRODUCTS[provenance["productId"]].source_page
    return (
        f"{page} file revision Last-Modified {stamp.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f", ETag {etag}{checked}"
    )


def source_entry(dem: DemSource, record: dict) -> dict:
    return {
        "provider": PROVIDER,
        "productId": record["productId"],
        "productVersion": revision_label(record),
        "sourceUrl": record["sourceUrl"],
        "sourceSha256": record["sha256"],
        "retrievedAtUtc": record["retrievedAtUtc"],
        "resolutionM": dem.resolution_m,
        "crs": dem._dataset.crs.to_wkt(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-id", default="lola-site01-reference")
    parser.add_argument("--site-tile", default="Site01_final_adj_5mpp_surf")
    parser.add_argument(
        "--ephemeris-dir", type=Path, default=ROOT / "data/reference/validation-30d"
    )
    parser.add_argument("--dem-dir", type=Path, default=ROOT / "data/raw/lola")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/reference/terrain-masks"
    )
    parser.add_argument("--mast-m", type=float, default=0.0)
    parser.add_argument("--ray-step-m", type=float, default=5.0)
    parser.add_argument("--max-range-km", type=float, default=200.0)
    parser.add_argument("--near-field-km", type=float, default=25.0)
    parser.add_argument("--min-distance-m", type=float, default=60.0)
    parser.add_argument("--allow-dirty", action="store_true", help="Testing only")
    args = parser.parse_args()

    revision = git_revision(args.allow_dirty)
    archived = json.loads((args.ephemeris_dir / f"{args.site_id}.json").read_text())
    lat, lon, altitude_km = archived["lat"], archived["lon"], archived["altitudeKm"]
    surface_m = altitude_km * 1000 - args.mast_m

    from lunarwindow.terrain.download import read_provenance

    paths = {
        key: args.dem_dir / PRODUCTS[pid].filename
        for key, pid in (
            ("fine", args.site_tile),
            ("near", NEAR_FIELD),
            ("far", FAR_FIELD),
        )
    }
    records = {key: read_provenance(path) for key, path in paths.items()}
    with (
        DemSource(paths["fine"]) as fine,
        DemSource(paths["near"]) as near,
        DemSource(paths["far"]) as far,
    ):
        x, y = (float(v) for v in latlon_to_stereographic(lat, lon))
        fine_patch = fine.read_patch(x, y, 9000)
        sampled = float(fine_patch.sample(x, y))
        if abs(sampled - surface_m) > 0.001:
            raise SystemExit(
                f"Archived altitude implies {surface_m} m ground, 5 m tile gives {sampled} m."
            )
        # Use the 5 m tile only inside the square it fully covers around the site.
        edge = min(
            x - fine_patch.left,
            fine_patch.right - x,
            fine_patch.top - y,
            y - fine_patch.bottom,
        )
        params = default_parameters(
            mastHeightM=args.mast_m,
            maxRangeKm=args.max_range_km,
            nearFieldKm=args.near_field_km,
            minDistanceM=args.min_distance_m,
            stepGrowth=0.0,
        )
        near_patch = near.read_patch(x, y, args.near_field_km * 1050 + 40)
        far_patch = far.read_patch(x, y, args.max_range_km * 1050 + 240)
        site = SiteSpec(
            args.site_id, archived["site"], lat, lon, archived["coordinateSource"]
        )
        # Constant step = finest pixel (5 m), so rayStepM is exact for every sample.
        profile = compute_horizon(
            site,
            near_patch,
            far_patch,
            params,
            fine=fine_patch,
            fine_field_m=edge - 2 * fine.resolution_m,
            require_complete=True,
        )
        if args.ray_step_m != fine.resolution_m:
            raise SystemExit(
                "This exporter samples at the finest DEM pixel; use --ray-step-m 5."
            )
        sources = [
            source_entry(dem, records[key])
            for key, dem in (("fine", fine), ("near", near), ("far", far))
        ]

    mast = f"{args.mast_m:g}".replace(".", "p")
    mask = {
        "schemaVersion": "lunarwindow.terrain-mask.v1",
        "maskId": f"{args.site_id}-mast-{mast}m",
        "siteId": args.site_id,
        "site": archived["site"],
        "terrainModel": "dem-horizon",
        "observer": {
            "lat": lat,
            "lon": lon,
            "coordinateSource": archived["coordinateSource"],
            "surfaceElevationM": surface_m,
            "mastHeightM": args.mast_m,
            "altitudeKm": altitude_km,
        },
        "referenceFrame": {
            "body": "Moon",
            "name": "MOON_ME",
            "realization": "DE421 (frame of the PGDA LOLA DEMs; the mask applies no frame transformation)",
            "coordinateType": "GEODETIC",
            "longitudeConvention": "east-positive",
            "referenceSurface": {
                "shape": "sphere",
                "radiusKm": REFERENCE_RADIUS_M / 1000,
            },
        },
        "angularUnits": "degrees",
        "azimuthConvention": "clockwise-from-local-north",
        "elevationReference": "local-horizontal",
        "refractionModel": "none",
        "horizon": [point.model_dump() for point in profile.horizon],
        "provenance": {
            "createdAtUtc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": sources,
            "algorithm": {
                "name": (
                    "LunarWindow terrain ray caster (lunarwindow.terrain.horizon.compute_horizon, "
                    "scripts/export_terrain_mask.py): exact spherical line-of-sight along "
                    f"{360 * params.raysPerDegree} great-circle rays, whole-degree value = max of "
                    f"rays within ±0.5°, samples from {args.min_distance_m:g} m, 5 m tile then "
                    f"20 m (≤{args.near_field_km:g} km) then 120 m DEM, bilinear heights"
                ),
                "version": f"{ALGORITHM_VERSION}; git {revision}",
                "curvatureModel": "spherical",
                "rayStepM": float(args.ray_step_m),
                "maxDistanceM": args.max_range_km * 1000,
                "noDataPolicy": "reject",
            },
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"{mask['maskId']}.json"
    content = json.dumps(mask, indent=2, ensure_ascii=False) + "\n"
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path.with_suffix(".json.sha256").write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"path": str(path), "sha256": digest, "warnings": profile.quality.warnings}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
