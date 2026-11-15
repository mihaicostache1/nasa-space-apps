"""Opt-in custom-observer resource settings, admission, and exact cache identity."""

import hashlib
import json
import math
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore

from pydantic import BaseModel, TypeAdapter

from lunarwindow.terrain.horizon import ALGORITHM_VERSION
from lunarwindow.terrain.models import Sha256
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION

from .snapshot_cache import SnapshotCache

CUSTOM_EVALUATION_POLICY_VERSION = "lunarwindow.custom-evaluation.v1"
_SHA256 = TypeAdapter(Sha256)


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    if value.strip().lower() not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false.")
    return value.strip().lower() == "true"


def _integer(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    if re.fullmatch(r"[0-9]+", value.strip()) is None:
        raise ValueError(f"{name} must be a non-negative integer.")
    return int(value)


def _seconds(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite number from 1 through 120.") from exc
    if not math.isfinite(seconds) or not 1 <= seconds <= 120:
        raise ValueError(f"{name} must be a finite number from 1 through 120.")
    return seconds


def _directory(name: str, default: str) -> Path:
    value = os.environ.get(name, default)
    if not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a nonblank filesystem path.")
    return Path(value).expanduser()


@dataclass(frozen=True)
class CustomSettings:
    """One process's explicit resource budget; construction performs no filesystem I/O."""

    enabled: bool = False
    terrain_enabled: bool = False
    archive_directory: Path = Path("data/processed/custom-ephemeris")
    dem_directory: Path = Path("data/raw/lola")
    terrain_cache_directory: Path | None = None
    max_concurrency: int = 1
    timeout_seconds: float = 30.0
    max_samples: int = 744
    max_archive_entries: int = 64
    max_archive_bytes: int = 64 * 1024 * 1024
    cache_max_entries: int = 16
    cache_max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.terrain_cache_directory is None and isinstance(self.archive_directory, Path):
            object.__setattr__(
                self, "terrain_cache_directory", self.archive_directory.parent / "custom-terrain"
            )
        for field, name in (
            ("enabled", "LUNARWINDOW_CUSTOM_ENABLED"),
            ("terrain_enabled", "LUNARWINDOW_CUSTOM_TERRAIN_ENABLED"),
        ):
            if not isinstance(getattr(self, field), bool):
                raise ValueError(f"{name} must be a boolean.")
        if self.terrain_enabled and not self.enabled:
            raise ValueError(
                "LUNARWINDOW_CUSTOM_TERRAIN_ENABLED requires LUNARWINDOW_CUSTOM_ENABLED=true."
            )
        for field, name, minimum, maximum in (
            ("max_concurrency", "LUNARWINDOW_CUSTOM_MAX_CONCURRENCY", 1, 4),
            ("max_samples", "LUNARWINDOW_CUSTOM_MAX_SAMPLES", 1, 744),
            ("max_archive_entries", "LUNARWINDOW_CUSTOM_ARCHIVE_MAX_ENTRIES", 1, None),
            ("max_archive_bytes", "LUNARWINDOW_CUSTOM_ARCHIVE_MAX_BYTES", 1, None),
            ("cache_max_entries", "LUNARWINDOW_CUSTOM_CACHE_MAX_ENTRIES", 0, None),
            ("cache_max_bytes", "LUNARWINDOW_CUSTOM_CACHE_MAX_BYTES", 0, None),
        ):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < minimum
                or (maximum is not None and value > maximum)
            ):
                upper = f" through {maximum}" if maximum is not None else " or greater"
                raise ValueError(f"{name} must be an integer from {minimum}{upper}.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 1 <= self.timeout_seconds <= 120
        ):
            raise ValueError("LUNARWINDOW_CUSTOM_TIMEOUT_SECONDS must be from 1 through 120.")
        for field, name in (
            ("archive_directory", "LUNARWINDOW_CUSTOM_ARCHIVE_DIR"),
            ("dem_directory", "LUNARWINDOW_CUSTOM_DEM_DIR"),
            ("terrain_cache_directory", "LUNARWINDOW_CUSTOM_TERRAIN_CACHE_DIR"),
        ):
            value = getattr(self, field)
            if not isinstance(value, Path) or "\x00" in str(value):
                raise ValueError(f"{name} must be a pathlib.Path.")

    @classmethod
    def from_env(cls) -> "CustomSettings":
        archive_directory = _directory(
            "LUNARWINDOW_CUSTOM_ARCHIVE_DIR", "data/processed/custom-ephemeris"
        )
        return cls(
            enabled=_boolean("LUNARWINDOW_CUSTOM_ENABLED", False),
            terrain_enabled=_boolean("LUNARWINDOW_CUSTOM_TERRAIN_ENABLED", False),
            archive_directory=archive_directory,
            dem_directory=_directory("LUNARWINDOW_CUSTOM_DEM_DIR", "data/raw/lola"),
            terrain_cache_directory=_directory(
                "LUNARWINDOW_CUSTOM_TERRAIN_CACHE_DIR",
                str(archive_directory.parent / "custom-terrain"),
            ),
            max_concurrency=_integer("LUNARWINDOW_CUSTOM_MAX_CONCURRENCY", 1),
            timeout_seconds=_seconds("LUNARWINDOW_CUSTOM_TIMEOUT_SECONDS", 30.0),
            max_samples=_integer("LUNARWINDOW_CUSTOM_MAX_SAMPLES", 744),
            max_archive_entries=_integer("LUNARWINDOW_CUSTOM_ARCHIVE_MAX_ENTRIES", 64),
            max_archive_bytes=_integer("LUNARWINDOW_CUSTOM_ARCHIVE_MAX_BYTES", 64 * 1024 * 1024),
            cache_max_entries=_integer("LUNARWINDOW_CUSTOM_CACHE_MAX_ENTRIES", 16),
            cache_max_bytes=_integer("LUNARWINDOW_CUSTOM_CACHE_MAX_BYTES", 16 * 1024 * 1024),
        )


class CustomDisabledError(RuntimeError):
    """Live custom-observer acquisition is disabled for this API deployment."""


class CustomBusyError(RuntimeError):
    """The process's custom computation slots are occupied; do not queue work."""


class CustomRuntime:
    def __init__(self, settings: CustomSettings | None = None):
        self.settings = CustomSettings.from_env() if settings is None else settings
        if not isinstance(self.settings, CustomSettings):
            raise TypeError("settings must be CustomSettings.")
        self.cache = SnapshotCache(
            max_entries=self.settings.cache_max_entries, max_bytes=self.settings.cache_max_bytes
        )
        self._slots = BoundedSemaphore(self.settings.max_concurrency)

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    @contextmanager
    def admit(self):
        """Reject unavailable capacity immediately; release on every success/failure path."""
        if not self.enabled:
            raise CustomDisabledError("Custom-coordinate evaluation is disabled.")
        if not self._slots.acquire(blocking=False):
            raise CustomBusyError("Custom-coordinate evaluation is busy; retry later.")
        try:
            yield
        finally:
            self._slots.release()

    def close(self) -> None:
        self.cache.clear()


def build_custom_cache_key(
    request: dict | BaseModel,
    *,
    ephemeris_sha256: str,
    terrain_sha256: str | None = None,
    calculation_model_version: str = VISIBILITY_MODEL_VERSION,
) -> str:
    """Hash exact validated inputs after source verification; no coordinate rounding.

    A syntactically valid checksum is not proof of source integrity. Acquire/check
    the ephemeris archive and current terrain before using this response cache.
    """
    from .custom_models import CustomEvaluationRequest

    if isinstance(request, BaseModel):
        request = request.model_dump()
    parsed = CustomEvaluationRequest.model_validate(request)
    source = _SHA256.validate_python(ephemeris_sha256, strict=True)
    terrain = parsed.horizonMode == "terrain"
    if terrain:
        terrain_sha256 = _SHA256.validate_python(terrain_sha256, strict=True)
    elif terrain_sha256 is not None:
        raise ValueError("Geometric cache keys cannot carry terrain checksums.")
    if not isinstance(calculation_model_version, str) or not calculation_model_version.strip():
        raise ValueError("calculation_model_version must be nonblank.")
    options = parsed.model_dump(mode="json")
    options["asOfUtc"] = parsed.asOfUtc or parsed.startUtc
    payload = {
        "schemaVersion": "lunarwindow.custom-cache-key.v1",
        "policyVersion": CUSTOM_EVALUATION_POLICY_VERSION,
        "calculationModelVersion": calculation_model_version,
        "terrainAlgorithmVersion": ALGORITHM_VERSION if terrain else None,
        "ephemerisSha256": source,
        "terrainSha256": terrain_sha256,
        "request": options,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
