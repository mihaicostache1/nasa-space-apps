"""Evaluate an exact custom lunar observer with existing ephemeris and visibility tools."""

import hashlib
import json
import math
import time
from typing import TYPE_CHECKING

from pydantic import ValidationError

from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.ephemeris.custom import (
    CustomEphemerisTimeout,
    CustomEphemerisUnavailable,
    acquire_custom_ephemeris,
)
from lunarwindow.ephemeris.models import Site, TimeRange, iso_utc
from lunarwindow.reference import VerifiedReferenceDataset
from lunarwindow.terrain.compatibility import (
    TerrainCompatibilityError,
    check_terrain_compatibility,
)
from lunarwindow.terrain.models import MaskObserver
from lunarwindow.visibility import calculate_visibility
from lunarwindow.visibility.models import HorizonPoint

from .custom_models import (
    CustomEvaluation,
    CustomEvaluationProvenance,
    CustomEvaluationRequest,
    CustomTerrainProvenance,
    canonical_model_sha256,
    observer_site_id,
)
from .custom_runtime import CustomRuntime, build_custom_cache_key
from .terrain_models import TerrainCompatibilityProvenance

if TYPE_CHECKING:
    from lunarwindow.terrain.custom import CustomTerrainResult

CUSTOM_SITE_NAME = "Custom lunar observer"
GEOMETRIC_COORDINATE_SOURCE = (
    "User-supplied lunar coordinates; ground elevation explicitly supplied above the "
    "1737.4 km reference sphere; observer height above ground."
)
GEOMETRIC_WARNING = (
    "Geometric custom visibility uses NASA/JPL Horizons for the exact requested observer "
    "and a flat zero-degree horizon. Ground elevation is supplied by the caller, not "
    "verified against terrain. Terrain, eclipses, power generation, and radio-link "
    "performance are not modeled. Durations and event brackets depend on sampling."
)
TERRAIN_WARNING = (
    "Custom terrain horizons are generated from the configured DEMs and remain preliminary, "
    "not independently reviewed landing-site predictions. The observer altitude is DEM ground "
    "plus requested height; the Mean Earth pairing is explicitly accepted as an approximation "
    "without a frame transformation. DEM resolution, near-field exclusion, the local "
    "horizontal-disc model, and temporal sampling limit precision. Eclipses, power generation, "
    "and radio-link performance are not modeled."
)


class CustomEvaluationInputError(ValueError):
    """A valid custom request exceeds a configured limit or cannot describe this observer."""


class CustomTerrainUnavailableError(RuntimeError):
    """Custom terrain is disabled or its configured source data is unavailable."""


def _remaining(started: float, seconds: float) -> float:
    remaining = seconds - (time.monotonic() - started)
    if remaining <= 0:
        raise CustomEphemerisTimeout("Custom evaluation budget expired.")
    return remaining


def _checked_dataset(verified: VerifiedReferenceDataset, site: Site, period: TimeRange) -> dict:
    """Bind the adapter's verified snapshot to the exact observer and selected grid."""
    try:
        dataset = validate_dataset(verified.dataset)
        encoded = json.dumps(
            dataset, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != verified.artifact_sha256:
            raise ValueError("Custom ephemeris snapshot checksum differs.")
        expected = {
            "siteId": site.site_id,
            "site": site.name,
            "lat": site.lat,
            "lon": site.lon,
            "altitudeKm": site.altitude_km,
            "coordinateSource": site.coordinate_source,
        }
        if any(dataset[name] != value for name, value in expected.items()):
            raise ValueError("Custom ephemeris snapshot observer differs.")
        source = dataset["provenance"]
        if (
            source["startUtc"] != iso_utc(period.start)
            or source["endUtc"] != iso_utc(period.end)
            or source["stepMinutes"] != period.step_minutes
        ):
            raise ValueError("Custom ephemeris snapshot sampling grid differs.")
        return dataset
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CustomEphemerisUnavailable(
            "Custom ephemeris does not match its requested observer."
        ) from exc


def _cached_result(
    snapshot: bytes | None,
    request: CustomEvaluationRequest,
    observer: MaskObserver,
    verified: VerifiedReferenceDataset,
    terrain: CustomTerrainProvenance | None = None,
) -> CustomEvaluation | None:
    if snapshot is None:
        return None
    try:
        result = CustomEvaluation.model_validate_json(snapshot)
        if (
            result.observer != observer
            or result.horizonMode != request.horizonMode
            or result.provenance.ephemerisSha256 != verified.artifact_sha256
            or result.to_ephemeris_dataset() != verified.dataset
            or result.calculation.visibilityRule != request.visibilityRule
            or result.metrics.asOfUtc != (request.asOfUtc or request.startUtc)
            or result.provenance.terrain != terrain
        ):
            return None
        return result
    except (ValueError, TypeError, KeyError, ValidationError):
        return None


def _prepare_terrain(
    request: CustomEvaluationRequest, runtime: CustomRuntime, started: float
) -> "CustomTerrainResult":
    """Import optional GIS code only for an explicitly enabled terrain request."""
    if not request.allowMeanEarthApproximation:
        raise CustomEvaluationInputError(
            "Terrain mode requires explicit allowMeanEarthApproximation=true."
        )
    if not runtime.settings.terrain_enabled:
        raise CustomTerrainUnavailableError("Custom terrain evaluation is disabled.")
    from lunarwindow.terrain.custom import (
        CustomTerrainCoverageError,
        CustomTerrainDataError,
        CustomTerrainTimeout,
        generate_custom_terrain,
    )

    location = request.location
    settings = runtime.settings
    try:
        terrain = generate_custom_terrain(
            latitude_deg=location.latitudeDeg,
            longitude_deg=location.longitudeDeg,
            observer_height_m=location.observerHeightM,
            surface_elevation_m=location.surfaceElevationM,
            dem_directory=settings.dem_directory,
            cache_directory=settings.terrain_cache_directory,
            timeout_seconds=_remaining(started, settings.timeout_seconds),
            max_cache_entries=settings.max_archive_entries,
            max_cache_bytes=settings.max_archive_bytes,
        )
    except CustomTerrainCoverageError as exc:
        raise CustomEvaluationInputError(str(exc)) from exc
    except CustomTerrainDataError as exc:
        raise CustomTerrainUnavailableError("Custom terrain data is unavailable.") from exc
    except CustomTerrainTimeout as exc:
        raise CustomEphemerisTimeout("Custom terrain generation timed out.") from exc
    observer = terrain.mask.observer
    if (
        observer.lat != location.latitudeDeg
        or observer.lon != location.longitudeDeg
        or observer.mastHeightM != location.observerHeightM
        or terrain.mask.siteId != observer_site_id(location, observer.altitudeKm)
        or canonical_model_sha256(terrain.profile) != terrain.profile_sha256
        or canonical_model_sha256(terrain.mask) != terrain.mask_sha256
    ):
        raise CustomTerrainUnavailableError("Custom terrain does not match the requested observer.")
    if location.surfaceElevationM is not None and not math.isclose(
        location.surfaceElevationM, observer.surfaceElevationM, rel_tol=0, abs_tol=0.001
    ):
        raise CustomEvaluationInputError("Supplied ground elevation differs from the terrain DEM.")
    return terrain


def evaluate_custom(request: CustomEvaluationRequest, runtime: CustomRuntime) -> CustomEvaluation:
    """Verify source snapshots before reuse and calculate with the shared visibility engine.

    Admission is bounded and nonblocking. Geometric mode never opens terrain DEMs.
    A cache hit still acquires/verifies the exact local ephemeris archive; successful
    snapshots are deserialized into fresh models rather than shared with callers.
    """
    request = CustomEvaluationRequest.model_validate(request.model_dump())
    with runtime.admit():
        started = time.monotonic()
        settings = runtime.settings
        period = request.to_time_range()
        if period.sample_count > settings.max_samples:
            raise CustomEvaluationInputError(
                f"Choose a larger step or shorter period (maximum {settings.max_samples} samples)."
            )
        location = request.location
        prepared = (
            _prepare_terrain(request, runtime, started)
            if request.horizonMode == "terrain"
            else None
        )
        observer = (
            prepared.mask.observer
            if prepared is not None
            else MaskObserver(
                lat=location.latitudeDeg,
                lon=location.longitudeDeg,
                coordinateSource=GEOMETRIC_COORDINATE_SOURCE,
                surfaceElevationM=location.surfaceElevationM,
                mastHeightM=location.observerHeightM,
                altitudeKm=(location.surfaceElevationM + location.observerHeightM) / 1000,
            )
        )
        site = Site(
            prepared.mask.siteId
            if prepared is not None
            else observer_site_id(location, observer.altitudeKm),
            prepared.mask.site if prepared is not None else CUSTOM_SITE_NAME,
            observer.lat,
            observer.lon,
            observer.altitudeKm,
            observer.coordinateSource,
        )
        verified = acquire_custom_ephemeris(
            site,
            period,
            archive_directory=settings.archive_directory,
            timeout_seconds=_remaining(started, settings.timeout_seconds),
            max_archive_entries=settings.max_archive_entries,
            max_archive_bytes=settings.max_archive_bytes,
        )
        dataset = _checked_dataset(verified, site, period)
        terrain = None
        terrain_sha256 = None
        if prepared is not None:
            try:
                assessment = check_terrain_compatibility(
                    prepared.mask, dataset, allow_mean_earth_approximation=True
                )
            except TerrainCompatibilityError as exc:
                raise CustomEvaluationInputError(str(exc)) from exc
            terrain = CustomTerrainProvenance(
                profile=prepared.profile,
                profileSha256=prepared.profile_sha256,
                mask=prepared.mask,
                maskSha256=prepared.mask_sha256,
                compatibility=TerrainCompatibilityProvenance.from_assessment(assessment),
            )
            terrain_sha256 = hashlib.sha256(
                json.dumps(
                    [prepared.profile_sha256, prepared.mask_sha256], separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        key = build_custom_cache_key(
            request,
            ephemeris_sha256=verified.artifact_sha256,
            terrain_sha256=terrain_sha256,
        )
        cached = _cached_result(runtime.cache.get(key), request, observer, verified, terrain)
        if cached is not None:
            _remaining(started, settings.timeout_seconds)
            return cached
        horizon = (
            prepared.mask.horizon
            if prepared is not None
            else [HorizonPoint(az=az, el=0.0) for az in range(360)]
        )
        _remaining(started, settings.timeout_seconds)
        visibility = calculate_visibility(
            dataset["series"],
            horizon,
            period,
            rule=request.visibilityRule,
            as_of_utc=request.asOfUtc,
        )
        result = CustomEvaluation(
            siteId=site.site_id,
            site=site.name,
            observer=observer,
            horizonMode=request.horizonMode,
            allowMeanEarthApproximation=request.allowMeanEarthApproximation,
            horizon=horizon,
            series=visibility.series,
            metrics=visibility.metrics,
            windows=visibility.windows,
            calculation=visibility.calculation,
            provenance=CustomEvaluationProvenance(
                ephemeris=dataset["provenance"],
                ephemerisSha256=verified.artifact_sha256,
                terrain=terrain,
                warning=TERRAIN_WARNING if terrain is not None else GEOMETRIC_WARNING,
            ),
        )
        _remaining(started, settings.timeout_seconds)
        runtime.cache.put(key, result.model_dump_json().encode("utf-8"))
        return result
