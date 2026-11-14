"""Pure cache identity contract; no storage, source verification, or API integration."""

import hashlib
import json
from typing import Literal, Self

from pydantic import ConfigDict, TypeAdapter, field_validator, model_validator

from lunarwindow.ephemeris.models import iso_utc, parse_utc
from lunarwindow.terrain.models import NonBlank, Sha256, Slug
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION

from .reference_models import ReferenceSiteEvaluationRequest
from .terrain_models import ReferenceEvaluationRequestContract, TerrainReferenceEvaluationRequest

_REQUEST = TypeAdapter(ReferenceEvaluationRequestContract)


class ReferenceEvaluationCacheKey(ReferenceSiteEvaluationRequest):
    """Immutable, inspectable identity for a complete reference evaluation response.

    The ephemeris hash identifies the site's full archived JSON, including original
    provenance and coverage. The terrain hash identifies the complete reviewed mask.
    A hash with valid syntax is not evidence that its source bytes were verified.
    """

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    schemaVersion: Literal["lunarwindow.reference-cache-key.v1"] = (
        "lunarwindow.reference-cache-key.v1"
    )
    calculationModelVersion: NonBlank
    ephemerisSha256: Sha256
    horizonMode: Literal["geometric", "terrain"]
    maskId: Slug | None
    terrainMaskSha256: Sha256 | None
    allowMeanEarthApproximation: bool
    asOfUtc: str

    @field_validator("startUtc", "endUtc", "asOfUtc")
    @classmethod
    def canonical_utc(cls, value: str) -> str:
        return iso_utc(parse_utc(value))

    @model_validator(mode="after")
    def validate_horizon_identity(self) -> Self:
        if self.horizonMode == "terrain":
            if self.maskId is None or self.terrainMaskSha256 is None:
                raise ValueError("Terrain cache keys require a mask ID and artifact checksum.")
        elif (
            self.maskId is not None
            or self.terrainMaskSha256 is not None
            or self.allowMeanEarthApproximation
        ):
            raise ValueError("Geometric cache keys cannot declare terrain inputs or acceptance.")
        return self

    @property
    def digest(self) -> str:
        """SHA-256 of UTF-8 JSON with sorted keys, compact separators, and all fields."""
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def build_reference_evaluation_cache_key(
    request: ReferenceEvaluationRequestContract,
    *,
    ephemeris_sha256: str,
    terrain_mask_sha256: str | None = None,
    calculation_model_version: str = VISIBILITY_MODEL_VERSION,
) -> ReferenceEvaluationCacheKey:
    """Build identity from request options and caller-verified source checksums.

    Revalidate mutable request models and normalize defaults/timestamps. This does
    not check archive availability, checksum/file agreement, or terrain compatibility.
    Future cache lookup must follow those checks; a key never authorizes evaluation.
    """
    request = _REQUEST.validate_python(request.model_dump())
    terrain = isinstance(request, TerrainReferenceEvaluationRequest)
    return ReferenceEvaluationCacheKey(
        **request.model_dump(exclude={"asOfUtc", "maskId", "allowMeanEarthApproximation"}),
        asOfUtc=request.startUtc if request.asOfUtc is None else request.asOfUtc,
        calculationModelVersion=calculation_model_version,
        ephemerisSha256=ephemeris_sha256,
        maskId=request.maskId if terrain else None,
        terrainMaskSha256=terrain_mask_sha256,
        allowMeanEarthApproximation=request.allowMeanEarthApproximation if terrain else False,
    )
