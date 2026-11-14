"""Publish immutable horizon runs and verify them before anyone consumes them.

A run directory holds one `<site>.json` horizon profile per site, a Horizons-ready
`sites.json` (altitude = LOLA surface + mast above the 1737.4 km sphere), optional PNG
sanity plots, and `manifest.json` with parameters, DEM provenance, and SHA-256 hashes. It
appears under its final name only after every site has been computed and verified.
"""

import hashlib
import json
import platform
import shutil
import tempfile
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from ..ephemeris.models import Site, iso_utc
from ..ephemeris.storage import atomic_write
from .catalog import CatalogSite
from .dem import DemSource
from .horizon import ALGORITHM_VERSION, compute_horizon, default_parameters, flat_horizon
from .models import HorizonParameters, HorizonProfile
from .products import FAR_FIELD, NEAR_FIELD, PRODUCTS

RUN_SCHEMA = "lunarwindow.horizon-run.v1"
# Stereographic distances exceed ground distances by the scale factor 2 / (1 - sin lat):
# about 1.003 at 84°S and 1.03 at 60°S. Read windows with headroom so rays never clip early.
PATCH_HEADROOM = 1.05


def open_dems(dem_dir: Path, stack: ExitStack) -> tuple[DemSource | None, DemSource | None]:
    def maybe(product_id):
        path = Path(dem_dir) / PRODUCTS[product_id].filename
        return stack.enter_context(DemSource(path)) if path.exists() else None

    near, far = maybe(NEAR_FIELD), maybe(FAR_FIELD)
    if near is None and far is None:
        raise FileNotFoundError(
            f"No LOLA DEMs in {dem_dir}. Run `lunarwindow-terrain download` first."
        )
    return near, far


def horizon_for_site(
    site: CatalogSite, near: DemSource | None, far: DemSource | None, params: HorizonParameters
) -> HorizonProfile:
    if site.terrain == "none":
        return flat_horizon(site.spec, params, site.published_elevation_m)
    from .geometry import latlon_to_stereographic

    x, y = (float(value) for value in latlon_to_stereographic(site.lat, site.lon))
    near_patch = (
        near.read_patch(x, y, params.nearFieldKm * 1000 * PATCH_HEADROOM + 2 * near.resolution_m)
        if near is not None and near.contains(x, y) and params.nearFieldKm > 0
        else None
    )
    far_patch = (
        far.read_patch(x, y, params.maxRangeKm * 1000 * PATCH_HEADROOM + 2 * far.resolution_m)
        if far is not None and far.contains(x, y)
        else None
    )
    if near_patch is None and far_patch is None:
        raise ValueError(
            f'{site.site_id} is outside the downloaded DEMs; set "terrain": "none" '
            "in its catalog entry to use a bare-sphere horizon deliberately."
        )
    return compute_horizon(site.spec, near_patch, far_patch, params)


def horizons_site_row(site: CatalogSite, profile: HorizonProfile) -> dict:
    """An ephemeris `--sites` entry whose altitude matches the horizon's observer."""
    if profile.terrainModel == "lola-dem":
        product = profile.sources[0].productId
        height = (
            f"observer altitude = LOLA {product} surface {profile.surfaceElevationM:.1f} m "
            f"+ {profile.mastHeightM:g} m mast above the 1737.4 km sphere"
        )
    else:
        base = (
            f"published surface {profile.surfaceElevationM:g} m"
            if profile.surfaceElevationM is not None
            else "surface height unknown (0 m assumed)"
        )
        height = f"observer altitude = {base} + {profile.mastHeightM:g} m mast; no terrain model"
    row = {
        "id": site.site_id,
        "name": site.name,
        "lat": site.lat,
        "lon": site.lon,
        "altitudeKm": profile.observerAltitudeKm,
        "coordinateSource": f"{site.coordinate_source}; {height}",
        "kind": site.kind,
        "terrainModel": profile.terrainModel,
    }
    Site(row["id"], row["name"], row["lat"], row["lon"], row["altitudeKm"], row["coordinateSource"])
    return row


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_horizons(
    sites: list[CatalogSite],
    dem_dir: Path,
    output: Path,
    params: HorizonParameters | None = None,
    plots: bool = False,
    progress=None,
) -> Path:
    params = params or default_parameters()
    if not sites:
        raise ValueError("No sites to export.")
    output.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=output))
    try:
        with ExitStack() as stack:
            needs_dem = any(site.terrain == "lola-dem" for site in sites)
            near, far = open_dems(dem_dir, stack) if needs_dem else (None, None)
            profiles = []
            for site in sites:
                if progress:
                    progress(site)
                profiles.append(horizon_for_site(site, near, far, params))
            dems = [dem.provenance for dem in (near, far) if dem is not None]

        files, rows = [], []
        for site, profile in zip(sites, profiles):
            path = staging / f"{site.site_id}.json"
            atomic_write(path, profile.model_dump_json(indent=1) + "\n")
            rows.append(horizons_site_row(site, profile))
            files.append(
                {
                    "siteId": site.site_id,
                    "json": path.name,
                    "sha256": _sha256(path),
                    "terrainModel": profile.terrainModel,
                    "warnings": profile.quality.warnings,
                }
            )
        atomic_write(staging / "sites.json", json.dumps(rows, indent=2) + "\n")
        extras = {"sites.json": _sha256(staging / "sites.json")}
        if plots:
            from .plots import write_overview

            for name in write_overview(profiles, staging):
                extras[name] = _sha256(staging / name)

        manifest = {
            "schemaVersion": RUN_SCHEMA,
            "runId": run_id,
            "status": "complete",
            "createdAtUtc": iso_utc(datetime.now(timezone.utc)),
            "software": {
                "packageVersion": version("lunarwindow-ephemeris"),
                "pythonVersion": platform.python_version(),
                "algorithmVersion": ALGORITHM_VERSION,
            },
            "parameters": params.model_dump(),
            "dems": dems,
            "horizons": files,
            "files": extras,
        }
        atomic_write(staging / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        verify_horizon_run(staging)
        destination = output / run_id
        staging.rename(destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_horizon_run(run: Path) -> dict:
    """Check hashes, schemas, and that sites.json altitudes match each horizon's observer."""
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != RUN_SCHEMA or manifest.get("status") != "complete":
        raise ValueError(f"{run}: not a complete {RUN_SCHEMA} run.")
    for name, digest in manifest["files"].items():
        if _sha256(run / name) != digest:
            raise ValueError(f"{run / name}: SHA-256 mismatch.")
    rows = {row["id"]: row for row in json.loads((run / "sites.json").read_text("utf-8"))}
    for item in manifest["horizons"]:
        path = run / item["json"]
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"{path}: SHA-256 mismatch.")
        profile = HorizonProfile.model_validate_json(path.read_text(encoding="utf-8"))
        if (
            profile.siteId != item["siteId"]
            or profile.parameters.model_dump() != manifest["parameters"]
        ):
            raise ValueError(f"{path}: site ID or parameters disagree with the manifest.")
        row = rows.get(profile.siteId)
        if row is None or row["altitudeKm"] != profile.observerAltitudeKm:
            raise ValueError(f"{profile.siteId}: sites.json altitude disagrees with the horizon.")
    if set(rows) != {item["siteId"] for item in manifest["horizons"]}:
        raise ValueError(f"{run}: sites.json and horizons list different sites.")
    return manifest


def load_horizons(run: Path) -> dict[str, HorizonProfile]:
    """Verified profiles by site ID — the backend's entry point for precomputed horizons."""
    manifest = verify_horizon_run(run)
    return {
        item["siteId"]: HorizonProfile.model_validate_json(
            (Path(run) / item["json"]).read_text(encoding="utf-8")
        )
        for item in manifest["horizons"]
    }
