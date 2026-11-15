"""Exact custom-observer identity and canonical evidence hashing, independent of HTTP."""

import hashlib
import json
import math

from pydantic import BaseModel


def custom_observer_id(lat: float, lon: float, altitude_km: float) -> str:
    values = [lat, lon, altitude_km]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Observer coordinates and altitude must be finite.")
    canonical = json.dumps(
        [0.0 if value == 0 else float(value) for value in values],
        separators=(",", ":"),
        allow_nan=False,
    )
    return "custom-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_model_sha256(value: BaseModel) -> str:
    content = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()
