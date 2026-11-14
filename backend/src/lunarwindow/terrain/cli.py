"""P2 terrain tools: download LOLA rasters, build region points, export and verify horizons."""

import argparse
import json
import sys
from pathlib import Path

from ..ephemeris.storage import atomic_write
from .catalog import load_catalog
from .download import download_all
from .export import export_horizons, verify_horizon_run
from .horizon import default_parameters
from .products import FAR_FIELD, NEAR_FIELD, PRODUCTS

DEM_DIR = Path("data/raw/lola")


def _download(args) -> int:
    ids = list(PRODUCTS) if args.all else args.products
    unknown = sorted(set(ids) - set(PRODUCTS))
    if unknown:
        raise ValueError(f"Unknown products {unknown}; choose from {sorted(PRODUCTS)}.")
    for path in download_all(ids, args.dest):
        print(path)
    return 0


def _horizons(args) -> int:
    sites = load_catalog(args.sites)
    params = default_parameters(
        mastHeightM=args.mast_m,
        maxRangeKm=args.max_range_km,
        nearFieldKm=args.near_field_km,
        raysPerDegree=args.rays_per_degree,
    )

    def progress(site):
        print(f"Horizon for {site.site_id} ({site.terrain})...", file=sys.stderr)

    run = export_horizons(sites, args.dem_dir, args.output, params, args.plots, progress)
    manifest = verify_horizon_run(run)
    for item in manifest["horizons"]:
        for warning in item["warnings"]:
            print(f"  {item['siteId']}: {warning}", file=sys.stderr)
    print(f"Completed run: {run}", file=sys.stderr)
    print(run)
    return 0


def _regions(args) -> int:
    from .regions import build_region_catalog

    entries = build_region_catalog(
        args.polygons,
        args.dem_dir,
        args.source,
        args.name_field,
        args.max_slope_deg,
        id_prefix=args.id_prefix,
        name_suffix=args.name_suffix,
    )
    atomic_write(args.output, json.dumps(entries, indent=2) + "\n")
    for entry in entries:
        region = entry["region"]
        print(
            f"{entry['id']}: {entry['lat']:.4f}, {entry['lon']:.4f} "
            f"(sun {region['avgSunPct']}%, Earth {region['avgEarthPct']}%, "
            f"slope {region['slopeDeg']}°)",
            file=sys.stderr,
        )
    print(args.output)
    return 0


def _verify(args) -> int:
    manifest = verify_horizon_run(args.run)
    print(f"OK: {len(manifest['horizons'])} horizons in {args.run}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="Fetch NASA rasters (resumable, hashed)")
    download.add_argument("products", nargs="*", default=[NEAR_FIELD, FAR_FIELD])
    download.add_argument("--all", action="store_true", help="Also fetch validation maps")
    download.add_argument("--dest", type=Path, default=DEM_DIR)
    download.set_defaults(handler=_download)

    horizons = commands.add_parser("horizons", help="Compute a verified horizon run")
    horizons.add_argument("--sites", type=Path, nargs="+", required=True)
    horizons.add_argument("--dem-dir", type=Path, default=DEM_DIR)
    horizons.add_argument("--output", type=Path, default=Path("data/processed/horizons"))
    horizons.add_argument("--mast-m", type=float, default=2.0, help="Observer height above ground")
    horizons.add_argument("--max-range-km", type=float, default=200.0)
    horizons.add_argument("--near-field-km", type=float, default=25.0)
    horizons.add_argument("--rays-per-degree", type=int, default=10)
    horizons.add_argument("--plots", action="store_true", help="Write overview.png (analysis)")
    horizons.set_defaults(handler=_horizons)

    regions = commands.add_parser("regions", help="Representative points from region polygons")
    regions.add_argument("--polygons", type=Path, required=True, help=".geojson or .shp + .prj")
    regions.add_argument("--source", required=True, help="Citation for the polygon file")
    regions.add_argument("--name-field")
    regions.add_argument("--max-slope-deg", type=float, default=10.0)
    regions.add_argument("--id-prefix", default="artemis3-")
    regions.add_argument("--name-suffix", default=" (Artemis III candidate region)")
    regions.add_argument("--dem-dir", type=Path, default=DEM_DIR)
    regions.add_argument("--output", type=Path, default=Path("data/sites.artemis-regions.json"))
    regions.set_defaults(handler=_regions)

    verify = commands.add_parser("verify", help="Check a horizon run's hashes and contracts")
    verify.add_argument("run", type=Path)
    verify.set_defaults(handler=_verify)

    args = parser.parse_args()
    try:
        return args.handler(args)
    except (ValueError, KeyError, OSError) as exc:
        print(f"Terrain command failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
