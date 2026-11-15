"""Strict on-demand LOLA terrain, with source-verified, bounded generated-artifact reuse.

Generated horizons are preliminary model outputs, not reviewed reference masks. The
operator supplies the downloaded 20 m and 120 m source products and their provenance.
Both source files are re-hashed before a generated-cache hit is considered. Timeout
checks are cooperative around file blocks, GDAL reads, and ray-casting chunks; a single
blocking OS/GDAL operation cannot be interrupted safely by this synchronous service.
"""

import hashlib
import json
import math
import re
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter

from lunarwindow.ephemeris.models import finite_number, iso_utc
from lunarwindow.ephemeris.storage import atomic_write, file_lock
from lunarwindow.observer import canonical_model_sha256, custom_observer_id

from .dem import DemSource
from .download import sidecar_path
from .export import PATCH_HEADROOM
from .geometry import latlon_to_stereographic
from .horizon import (
    ALGORITHM_VERSION,
    IncompleteTerrain,
    OutsideCoverage,
    SiteSpec,
    compute_horizon,
    default_parameters,
    surface_height,
)
from .models import DemSource as MaskDemSource
from .models import HorizonProfile, Sha256, TerrainMask, UtcTimestamp
from .products import FAR_FIELD, NEAR_FIELD, PRODUCTS, REFERENCE_RADIUS_M

SCHEMA = "lunarwindow.custom-terrain-cache.v1"
COORDINATE_SOURCE = (
    "User-supplied lunar coordinates; ground elevation derived from configured LOLA DEMs "
    "on the 1737.4 km reference sphere; observer height above ground."
)
_PROVIDER = "NASA GSFC PGDA, LOLA team"
_SHA256 = TypeAdapter(Sha256)
_UTC = TypeAdapter(UtcTimestamp)
_CACHE_FILE = re.compile(r"^[0-9a-f]{64}\.json$")
_FIELDS = {"schemaVersion", "identity", "profile", "profileSha256", "mask", "maskSha256"}


class CustomTerrainCoverageError(ValueError):
    """Requested geometry cannot be supported by the configured terrain coverage."""


class CustomTerrainDataError(RuntimeError):
    """Configured DEMs or a generated artifact are absent, unreadable, or invalid."""


class CustomTerrainTimeout(TimeoutError):
    """The terrain generation/verification time budget was exhausted."""


@dataclass(frozen=True)
class CustomTerrainResult:
    profile: HorizonProfile
    mask: TerrainMask
    profile_sha256: str
    mask_sha256: str


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _file_signature(path: Path) -> tuple:
    stat = path.stat()
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            "Custom terrain inputs/cache artifacts must be regular, non-symlink files."
        )
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _source_record(path: Path, product_id: str, check) -> dict:
    check()
    product = PRODUCTS[product_id]
    before = _file_signature(path)
    metadata_path = sidecar_path(path)
    _file_signature(metadata_path)
    if metadata_path.stat().st_size > 64 * 1024:
        raise ValueError("DEM provenance is unexpectedly large.")
    record = json.loads(metadata_path.read_bytes())
    checksum = _SHA256.validate_python(record["sha256"], strict=True)
    _UTC.validate_python(record["retrievedAtUtc"], strict=True)
    if (
        record["productId"] != product_id
        or record["sourceUrl"] != product.url
        or record["sizeBytes"] != before[2]
        or before[2] != product.size_bytes
        or record["resolutionM"] != product.resolution_m
        or record["role"] != product.role
    ):
        raise ValueError("DEM download provenance differs from the configured product.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            check()
            digest.update(block)
    check()
    if before != _file_signature(path) or digest.hexdigest() != checksum:
        raise ValueError("DEM changed or differs from its recorded SHA-256.")
    return record


def _mask_source(dem: DemSource, record: dict) -> MaskDemSource:
    product = PRODUCTS[record["productId"]]
    if dem.resolution_m != product.resolution_m:
        raise ValueError("DEM pixel resolution differs from the declared product.")
    return MaskDemSource(
        provider=_PROVIDER,
        productId=product.product_id,
        productVersion=f"{product.source_page}; content SHA-256 {record['sha256']}",
        sourceUrl=record["sourceUrl"],
        sourceSha256=record["sha256"],
        retrievedAtUtc=record["retrievedAtUtc"],
        resolutionM=dem.resolution_m,
        crs=dem._dataset.crs.to_wkt(),
    )


def _mask(profile: HorizonProfile, sources: list[MaskDemSource], cache_key: str) -> TerrainMask:
    params = profile.parameters
    return TerrainMask.model_validate(
        {
            "schemaVersion": "lunarwindow.terrain-mask.v1",
            "maskId": f"{profile.siteId}-terrain-{cache_key[:16]}",
            "siteId": profile.siteId,
            "site": profile.name,
            "terrainModel": "dem-horizon",
            "observer": {
                "lat": profile.lat,
                "lon": profile.lon,
                "coordinateSource": profile.coordinateSource,
                "surfaceElevationM": profile.surfaceElevationM,
                "mastHeightM": profile.mastHeightM,
                "altitudeKm": profile.observerAltitudeKm,
            },
            "referenceFrame": {
                "body": "Moon",
                "name": "MOON_ME",
                "realization": "DE421 (frame of the PGDA LOLA DEMs; the mask applies no frame transformation)",
                "coordinateType": "GEODETIC",
                "longitudeConvention": "east-positive",
                "referenceSurface": {"shape": "sphere", "radiusKm": REFERENCE_RADIUS_M / 1000},
            },
            "angularUnits": "degrees",
            "azimuthConvention": "clockwise-from-local-north",
            "elevationReference": "local-horizontal",
            "refractionModel": "none",
            "horizon": [point.model_dump() for point in profile.horizon],
            "provenance": {
                "createdAtUtc": iso_utc(datetime.now(timezone.utc)),
                "sources": [source.model_dump() for source in sources],
                "algorithm": {
                    "name": (
                        "LunarWindow exact spherical great-circle terrain ray caster; "
                        f"{360 * params.raysPerDegree} rays, max-per-degree binning, "
                        f"bilinear heights, distances from {params.minDistanceM:g} m, "
                        f"variable step max(base pixel, distance * {params.stepGrowth:g}), "
                        f"near-field tier through {params.nearFieldKm:g} km; preliminary custom model"
                    ),
                    "version": f"{ALGORITHM_VERSION}; {SCHEMA}",
                    "curvatureModel": "spherical",
                    "rayStepM": min(source.resolutionM for source in sources),
                    "maxDistanceM": params.maxRangeKm * 1000,
                    "noDataPolicy": "reject",
                },
            },
        }
    )


def _check_result(
    result: CustomTerrainResult,
    identity: dict,
    sources: list[MaskDemSource],
    ground_m: float,
    cache_key: str,
) -> None:
    profile, mask = result.profile, result.mask
    altitude = round((ground_m + identity["observerHeightM"]) / 1000, 6)
    site_id = custom_observer_id(identity["lat"], identity["lon"], altitude)
    expected_sources = [
        (source.productId, source.sourceSha256, source.resolutionM) for source in sources
    ]
    if (
        profile.siteId != site_id
        or profile.name != "Custom lunar observer"
        or profile.lat != identity["lat"]
        or profile.lon != identity["lon"]
        or profile.coordinateSource != COORDINATE_SOURCE
        or profile.terrainModel != "lola-dem"
        or profile.surfaceElevationM != round(ground_m, 3)
        or profile.mastHeightM != identity["observerHeightM"]
        or profile.observerAltitudeKm != altitude
        or profile.referenceRadiusM != REFERENCE_RADIUS_M
        or profile.parameters.model_dump() != identity["parameters"]
        or profile.algorithmVersion != ALGORITHM_VERSION
        or profile.rays is None
        or profile.quality.missingSampleFraction != 0
        or profile.quality.truncatedAzimuths
        or profile.quality.minReachKm < profile.parameters.maxRangeKm - 0.001
        or [(s.productId, s.sha256, s.resolutionM) for s in profile.sources] != expected_sources
    ):
        raise ValueError("Custom terrain profile differs from its source/observer identity.")
    if (
        mask.siteId != site_id
        or mask.maskId != f"{site_id}-terrain-{cache_key[:16]}"
        or mask.site != profile.name
        or mask.horizon != profile.horizon
        or mask.observer.lat != profile.lat
        or mask.observer.lon != profile.lon
        or mask.observer.surfaceElevationM != profile.surfaceElevationM
        or mask.observer.altitudeKm != profile.observerAltitudeKm
        or mask.observer.mastHeightM != profile.mastHeightM
        or mask.observer.coordinateSource != COORDINATE_SOURCE
        or mask.provenance.sources != sources
        or mask.referenceFrame.name != "MOON_ME"
        or mask.referenceFrame.realization
        != "DE421 (frame of the PGDA LOLA DEMs; the mask applies no frame transformation)"
        or mask.referenceFrame.referenceSurface.radiusKm != REFERENCE_RADIUS_M / 1000
        or mask.provenance.algorithm.version != f"{ALGORITHM_VERSION}; {SCHEMA}"
        or canonical_model_sha256(profile) != result.profile_sha256
        or canonical_model_sha256(mask) != result.mask_sha256
    ):
        raise ValueError("Custom terrain mask or hashes differ from the generated profile.")


def _cache_files(directory: Path) -> list[Path]:
    files = [path for path in directory.iterdir() if _CACHE_FILE.fullmatch(path.name)]
    for path in files:
        _file_signature(path)
    return files


def _prune(directory: Path, *, reserve_bytes: int, max_entries: int, max_bytes: int) -> None:
    files = sorted(_cache_files(directory), key=lambda path: path.stat().st_mtime_ns)
    total = sum(path.stat().st_size for path in files)
    while files and (len(files) >= max_entries or total + reserve_bytes > max_bytes):
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink()


def generate_custom_terrain(
    *,
    latitude_deg: float,
    longitude_deg: float,
    observer_height_m: float,
    surface_elevation_m: float | None,
    dem_directory: Path,
    cache_directory: Path,
    timeout_seconds: float,
    max_cache_entries: int = 64,
    max_cache_bytes: int = 64 * 1024 * 1024,
) -> CustomTerrainResult:
    """Generate complete terrain for the exact observer, or raise an explicit error.

    Both configured DEMs are required and verified, even for a cache hit. Terrain
    outside the south-polar products or with any uncovered ray sample is rejected.
    No bare-sphere fallback, remote fetch, or mutation of DEM provenance is allowed.
    """
    lat = finite_number(latitude_deg, "Latitude")
    lon = finite_number(longitude_deg, "Longitude")
    mast = finite_number(observer_height_m, "Observer height")
    budget = finite_number(timeout_seconds, "Timeout")
    if not -90 <= lat <= -60 or not -180 <= lon <= 180:
        raise CustomTerrainCoverageError(
            "Custom terrain requires south-polar DEM coverage (60–90°S)."
        )
    if not 0 <= mast <= 1000:
        raise CustomTerrainCoverageError(
            "Observer height must be in [0, 1000] metres above ground."
        )
    if budget <= 0:
        raise CustomTerrainTimeout("Terrain time budget was exhausted.")
    if surface_elevation_m is not None:
        surface_elevation_m = finite_number(surface_elevation_m, "Surface elevation")
    for value in (max_cache_entries, max_cache_bytes):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Terrain cache limits must be positive integers.")
    lat, lon, mast = (0.0 if value == 0 else value for value in (lat, lon, mast))
    lon = -180.0 if lon == 180 else lon
    deadline = time.monotonic() + budget

    def check():
        if time.monotonic() >= deadline:
            raise CustomTerrainTimeout("Terrain verification/generation time limit was exceeded.")

    try:
        cache_directory = Path(cache_directory)
        if cache_directory.is_symlink():
            raise ValueError("Terrain cache directory must not be a symlink.")
        cache_directory.mkdir(parents=True, exist_ok=True)
        lock_path = cache_directory / ".custom-terrain.lock"
        if lock_path.is_symlink():
            raise ValueError("Terrain cache lock must not be a symlink.")
        with file_lock(lock_path, timeout=max(0, deadline - time.monotonic())):
            if cache_directory.is_symlink():
                raise ValueError("Terrain cache directory must not be a symlink.")
            _file_signature(lock_path)
            check()
            paths = {
                pid: Path(dem_directory) / PRODUCTS[pid].filename for pid in (NEAR_FIELD, FAR_FIELD)
            }
            records = {pid: _source_record(path, pid, check) for pid, path in paths.items()}
            params = default_parameters(mastHeightM=mast)
            identity = {
                "lat": lat,
                "lon": lon,
                "observerHeightM": mast,
                "parameters": params.model_dump(),
                "sources": records,
                "algorithmVersion": ALGORITHM_VERSION,
                "policyVersion": SCHEMA,
            }
            cache_key = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()
            path = cache_directory / f"{cache_key}.json"
            with ExitStack() as stack:
                dems = {
                    pid: stack.enter_context(DemSource(paths[pid], provenance=records[pid]))
                    for pid in paths
                }
                check()
                x, y = (float(v) for v in latlon_to_stereographic(lat, lon))
                available = {pid: dem for pid, dem in dems.items() if dem.contains(x, y)}
                if FAR_FIELD not in available:
                    raise CustomTerrainCoverageError(
                        "The requested observer is outside the configured DEMs."
                    )
                sources = [_mask_source(dem, records[pid]) for pid, dem in available.items()]
                ground_patches = [
                    dem.read_patch(x, y, 3 * dem.resolution_m) for dem in available.values()
                ]
                check()
                try:
                    ground_m, _ = surface_height(lat, lon, *ground_patches)
                except OutsideCoverage as exc:
                    raise CustomTerrainCoverageError(
                        "There is no valid DEM ground elevation at this location."
                    ) from exc
                if surface_elevation_m is not None and not math.isclose(
                    ground_m, surface_elevation_m, rel_tol=0, abs_tol=0.001
                ):
                    raise CustomTerrainCoverageError(
                        "Supplied surfaceElevationM differs from the DEM ground height."
                    )
                if path.exists() or path.is_symlink():
                    _file_signature(path)
                    if path.stat().st_size > max_cache_bytes:
                        raise ValueError(
                            "Generated terrain artifact exceeds the configured cache byte limit."
                        )
                    record = json.loads(path.read_bytes())
                    if (
                        set(record) != _FIELDS
                        or record["schemaVersion"] != SCHEMA
                        or record["identity"] != identity
                    ):
                        raise ValueError(
                            "Generated terrain cache identity differs from the requested observer."
                        )
                    result = CustomTerrainResult(
                        HorizonProfile.model_validate(record["profile"]),
                        TerrainMask.model_validate(record["mask"]),
                        record["profileSha256"],
                        record["maskSha256"],
                    )
                    _check_result(result, identity, sources, ground_m, cache_key)
                    check()
                    path.touch()
                    # An operator may lower the configured caps between requests.
                    # Promote this hit first, then remove older retained artifacts.
                    _prune(
                        cache_directory,
                        reserve_bytes=0,
                        max_entries=max_cache_entries + 1,
                        max_bytes=max_cache_bytes,
                    )
                    return result
                patches = {}
                for pid, dem in available.items():
                    radius_m = (
                        params.nearFieldKm if pid == NEAR_FIELD else params.maxRangeKm
                    ) * 1000
                    patches[pid] = dem.read_patch(
                        x, y, radius_m * PATCH_HEADROOM + 2 * dem.resolution_m
                    )
                    check()
                site = SiteSpec("custom", "Custom lunar observer", lat, lon, COORDINATE_SOURCE)
                try:
                    profile = compute_horizon(
                        site,
                        patches.get(NEAR_FIELD),
                        patches.get(FAR_FIELD),
                        params,
                        require_complete=True,
                        check_callback=check,
                    )
                except (OutsideCoverage, IncompleteTerrain) as exc:
                    raise CustomTerrainCoverageError(
                        "The requested horizon has incomplete DEM coverage."
                    ) from exc
                profile = profile.model_copy(
                    update={"siteId": custom_observer_id(lat, lon, profile.observerAltitudeKm)}
                )
                mask = _mask(profile, sources, cache_key)
                result = CustomTerrainResult(
                    profile, mask, canonical_model_sha256(profile), canonical_model_sha256(mask)
                )
                _check_result(result, identity, sources, ground_m, cache_key)
                check()
                content = _canonical(
                    {
                        "schemaVersion": SCHEMA,
                        "identity": identity,
                        "profile": profile.model_dump(mode="json"),
                        "profileSha256": result.profile_sha256,
                        "mask": mask.model_dump(mode="json"),
                        "maskSha256": result.mask_sha256,
                    }
                )
                if len(content.encode("utf-8")) <= max_cache_bytes:
                    _prune(
                        cache_directory,
                        reserve_bytes=len(content.encode("utf-8")),
                        max_entries=max_cache_entries,
                        max_bytes=max_cache_bytes,
                    )
                    atomic_write(path, content)
                return result
    except (CustomTerrainCoverageError, CustomTerrainTimeout):
        raise
    except TimeoutError as exc:
        raise CustomTerrainTimeout("Terrain cache lock time limit was exceeded.") from exc
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        raise CustomTerrainDataError(
            f"Custom terrain data is unavailable or invalid: {exc}"
        ) from exc
