"""Deployment opt-ins, independent of upstream or local data readiness."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from .custom_routes import get_custom_runtime
from .custom_runtime import CustomRuntime


class CustomEvaluationCapabilities(BaseModel):
    enabled: bool
    terrainEnabled: bool


class Capabilities(BaseModel):
    schemaVersion: Literal["lunarwindow.capabilities.v1"] = "lunarwindow.capabilities.v1"
    customEvaluation: CustomEvaluationCapabilities


router = APIRouter()


@router.get(
    "/api/capabilities",
    response_model=Capabilities,
    tags=["capabilities"],
    summary="Discover custom-evaluation deployment opt-ins",
    description=(
        "Reports the active process configuration, without acquisition, DEM reads, or "
        "cache writes. Enabled flags do not establish Horizons availability, writable "
        "storage, GIS dependencies, or terrain coverage. Evaluation requests still "
        "perform all admission, source, and coverage checks. Reference terrain "
        "availability is advertised separately by GET /api/reference/sites."
    ),
)
def capabilities(
    response: Response,
    runtime: Annotated[CustomRuntime, Depends(get_custom_runtime)],
) -> Capabilities:
    response.headers["Cache-Control"] = "no-store"
    return Capabilities(
        customEvaluation=CustomEvaluationCapabilities(
            enabled=runtime.enabled,
            terrainEnabled=runtime.enabled and runtime.settings.terrain_enabled,
        )
    )
