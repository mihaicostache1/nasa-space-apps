"""Observer checks and an explicit, limited policy for the reviewed Mean Earth pairing."""

import math
import re
from dataclasses import dataclass

from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.ephemeris.models import TimeRange, parse_utc

from .models import TerrainMask

ANGLE_TOLERANCE_DEG = 1e-9
HEIGHT_TOLERANCE_KM = 1e-6
_REFERENCE_START = parse_utc("2000-01-01T00:00:00Z")
_REFERENCE_END = parse_utc("2040-01-01T00:00:00Z")
FRAME_REFERENCES = (
    "https://ssd.jpl.nasa.gov/horizons/manual.html",
    "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/moon_de440_250416.tf",
)
_DE421_REALIZATIONS = {
    "DE421",
    "DE421 (frame of the PGDA LOLA DEMs; the mask applies no frame transformation)",
}
_HORIZONS_FRAMES = {
    "MEAN_ME (high precision) {East-longitude positive}",
    "MOON_ME {East-longitude positive}",
}
_LIMITATION = (
    "The DE421 terrain and Horizons high-precision Mean Earth implementations have residual "
    "frame differences. Acceptance is a reference-demo approximation, with no frame "
    "transformation applied; it does not establish exact observer equivalence or mission accuracy."
)


class TerrainCompatibilityError(ValueError):
    """The supplied artifacts cannot be joined under the requested compatibility policy."""


@dataclass(frozen=True)
class TerrainCompatibility:
    """Record the accepted approximation without changing either artifact's declarations."""

    mask_id: str
    site_id: str
    frame_policy: str
    frame_status: str
    mask_frame_name: str
    mask_frame_realization: str
    ephemeris_frame: str
    ephemeris_dynamical_source: str
    reference_radius_km: float
    transformation_applied: bool
    limitation: str
    references: tuple[str, ...]


def _check_sphere(value: str, radius_km: float) -> None:
    try:
        numbers = re.fullmatch(r"(.+?)\s+km\s*(?:\{Equator_a, b, pole_c\})?", value)
        if numbers is None:
            raise ValueError("Expected radii in km.")
        axes = tuple(float(part.strip()) for part in numbers[1].split(","))
        if len(axes) != 3 or any(not math.isfinite(axis) or axis <= 0 for axis in axes):
            raise ValueError("Expected three finite positive radii.")
    except ValueError as exc:
        raise TerrainCompatibilityError("Cannot verify ephemeris reference sphere.") from exc
    if any(
        not math.isclose(axis, radius_km, rel_tol=0, abs_tol=HEIGHT_TOLERANCE_KM) for axis in axes
    ):
        raise TerrainCompatibilityError("Mask and ephemeris reference sphere radii differ.")


def check_terrain_compatibility(
    mask: TerrainMask,
    dataset: dict,
    *,
    allow_mean_earth_approximation: bool = False,
) -> TerrainCompatibility:
    """Check loaded contracts and observer geometry before any visibility calculation.

    The supported DE421/Horizons pairing is rejected by default because the frame
    implementations are not identical. Explicit reference-demo acceptance records
    the approximation and its sources. It never overrides a geometric mismatch.
    Callers remain responsible for artifact integrity through the verified loaders.
    """
    if not isinstance(allow_mean_earth_approximation, bool):
        raise TerrainCompatibilityError("allow_mean_earth_approximation must be a boolean.")
    try:
        mask = TerrainMask.model_validate(mask)
        validate_dataset(dataset)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise TerrainCompatibilityError(f"Invalid compatibility input: {exc}") from exc

    if mask.siteId != dataset["siteId"]:
        raise TerrainCompatibilityError("Mask and ephemeris siteId differ.")
    observer = mask.observer
    longitude_difference = (observer.lon - dataset["lon"] + 180) % 360 - 180
    if abs(observer.lat - dataset["lat"]) > ANGLE_TOLERANCE_DEG:
        raise TerrainCompatibilityError("Mask and ephemeris latitude differ.")
    if abs(longitude_difference) > ANGLE_TOLERANCE_DEG:
        raise TerrainCompatibilityError("Mask and ephemeris longitude differ.")
    if not math.isclose(
        observer.altitudeKm, dataset["altitudeKm"], rel_tol=0, abs_tol=HEIGHT_TOLERANCE_KM
    ):
        raise TerrainCompatibilityError("Mask and ephemeris total observer altitude differ.")

    frame = mask.referenceFrame
    if (
        frame.name not in {"MOON_ME", "MOON_ME_DE421"}
        or frame.realization not in _DE421_REALIZATIONS
    ):
        raise TerrainCompatibilityError(
            "Unsupported mask frame or realization; review is required."
        )

    frames, sources = set(), set()
    for request in dataset["provenance"]["requests"]:
        header = request["modelHeader"]
        center = re.fullmatch(
            r"Moon\s+\(301\)\s+\{source:\s*(DE440|DE441)\}", header.get("Center body name", "")
        )
        if center is None:
            raise TerrainCompatibilityError("Unsupported or missing lunar center/dynamical source.")
        orientation = " ".join(header["Center pole/equ"].split())
        if orientation not in _HORIZONS_FRAMES:
            raise TerrainCompatibilityError("Unsupported ephemeris orientation frame.")
        if header.get("Atmos refraction") != "NO (AIRLESS)":
            raise TerrainCompatibilityError("Ephemeris must declare airless positions.")
        _check_sphere(header["Center radii"], frame.referenceSurface.radiusKm)
        frames.add(orientation)
        sources.add(center[1])
    if len(frames) != 1 or len(sources) != 1:
        raise TerrainCompatibilityError("Ephemeris requests use inconsistent reference models.")

    period = TimeRange(
        dataset["provenance"]["startUtc"],
        dataset["provenance"]["endUtc"],
        dataset["provenance"]["stepMinutes"],
    )
    # The reference-demo policy is deliberately limited to modern dates.
    if period.start < _REFERENCE_START or period.end > _REFERENCE_END:
        raise TerrainCompatibilityError("Mean Earth reference policy requires dates in 2000–2039.")
    if not allow_mean_earth_approximation:
        raise TerrainCompatibilityError(
            "Frame realizations are not established as identical. Reference-demo use requires "
            "explicit allow_mean_earth_approximation=True; no transformation is applied."
        )

    return TerrainCompatibility(
        mask_id=mask.maskId,
        site_id=mask.siteId,
        frame_policy="mean-earth-reference-v1",
        frame_status="approximate",
        mask_frame_name=frame.name,
        mask_frame_realization=frame.realization,
        ephemeris_frame=next(iter(frames)),
        ephemeris_dynamical_source=next(iter(sources)),
        reference_radius_km=frame.referenceSurface.radiusKm,
        transformation_applied=False,
        limitation=_LIMITATION,
        references=FRAME_REFERENCES,
    )
