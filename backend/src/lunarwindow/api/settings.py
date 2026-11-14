"""Validated resource settings read when an API application is created."""

import os
import re

from .reference_cache import ReferenceEvaluationCache


def _nonnegative_integer(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    if not re.fullmatch(r"[0-9]+", value.strip()):
        raise ValueError(f"{name} must be a non-negative integer; use 0 to disable caching.")
    return int(value)


def configured_reference_cache() -> ReferenceEvaluationCache:
    return ReferenceEvaluationCache(
        max_entries=_nonnegative_integer("LUNARWINDOW_CACHE_MAX_ENTRIES", 32),
        max_bytes=_nonnegative_integer("LUNARWINDOW_CACHE_MAX_BYTES", 16 * 1024 * 1024),
    )
