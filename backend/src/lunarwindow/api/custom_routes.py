"""Opt-in custom-coordinate evaluation, with the existing structured error envelope."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from lunarwindow.ephemeris.custom import (
    CustomArchiveError,
    CustomEphemerisTimeout,
    CustomEphemerisUnavailable,
)

from .custom_models import CustomEvaluation, CustomEvaluationRequest
from .custom_provider import (
    CustomEvaluationInputError,
    CustomTerrainUnavailableError,
    evaluate_custom,
)
from .custom_runtime import CustomBusyError, CustomDisabledError, CustomRuntime
from .models import ApiError, ErrorResponse

router = APIRouter()
_LOG = logging.getLogger("uvicorn.error")


def get_custom_runtime(request: Request) -> CustomRuntime:
    return request.app.state.custom_runtime


def _failure(status: int, code: str, message: str, *, retry: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(error=ApiError(code=code, message=message)).model_dump(),
        headers={"Retry-After": "1"} if retry else None,
    )


@router.post(
    "/api/custom/evaluations",
    response_model=CustomEvaluation,
    responses={code: {"model": ErrorResponse} for code in (422, 502, 503, 504)},
    tags=["custom"],
    summary="Evaluate an exact custom lunar observer using Horizons and optional DEM terrain",
    description=(
        "Requires server opt-in. Coordinates are degrees with east-positive longitude; "
        "observerHeightM is above ground. Geometric mode requires explicit surfaceElevationM "
        "above the 1737.4 km reference sphere. Terrain mode derives ground from configured "
        "LOLA DEMs and requires explicit frame-approximation acceptance and complete coverage. "
        "Horizons samples and raw source responses are archived and verified before reuse. "
        "Generated terrain is preliminary, independently of reviewed reference-site masks."
    ),
)
def custom_evaluation(
    scenario: CustomEvaluationRequest,
    runtime: Annotated[CustomRuntime, Depends(get_custom_runtime)],
) -> CustomEvaluation | JSONResponse:
    try:
        return evaluate_custom(scenario, runtime)
    except CustomEvaluationInputError as exc:
        raise RequestValidationError(
            [{"loc": ("body",), "msg": str(exc), "type": "value_error"}]
        ) from exc
    except CustomDisabledError:
        return _failure(503, "custom_disabled", "Custom-coordinate evaluation is disabled.")
    except CustomBusyError:
        return _failure(
            503, "custom_busy", "Custom-coordinate evaluation is busy. Retry later.", retry=True
        )
    except CustomEphemerisTimeout as exc:
        _LOG.warning("custom_evaluation_unavailable operation=horizons-timeout reason=%s", exc)
        return _failure(
            504, "custom_upstream_timeout", "The custom evaluation time limit was exceeded."
        )
    except CustomEphemerisUnavailable as exc:
        _LOG.warning("custom_evaluation_unavailable operation=horizons reason=%s", exc)
        return _failure(
            502,
            "custom_upstream_unavailable",
            "Horizons samples could not be retrieved or verified.",
        )
    except (CustomArchiveError, CustomTerrainUnavailableError, OSError, ValueError) as exc:
        _LOG.warning("custom_evaluation_unavailable operation=data reason=%s", exc)
        return _failure(
            503,
            "custom_data_unavailable",
            "Custom evaluation data is unavailable or failed validation.",
        )
