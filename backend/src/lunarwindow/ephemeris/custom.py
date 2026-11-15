"""Acquire exact custom-observer ephemerides and replay bounded, self-contained archives.

An archive contains the original provider responses and a checksummed parsed dataset.
Reuse replays those responses through the existing parser and requires byte-equivalent
canonical dataset output. Corrupt entries fail explicitly; they never trigger a hidden
network refresh. Archive identity includes the exact observer, grid, and request URLs.
"""

import hashlib
import json
import math
import re
import time
from pathlib import Path

from lunarwindow.reference import VerifiedReferenceDataset

from .contract import validate_dataset
from .horizons import (
    TARGETS,
    HorizonsClient,
    HorizonsError,
    HorizonsTimeoutError,
    query_parameters,
    query_url,
)
from .models import Site, TimeRange, iso_utc
from .storage import atomic_write, file_lock

SCHEMA_VERSION = "lunarwindow.custom-ephemeris-archive.v1"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_ENTRY_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_FRAMES = {
    "MEAN_ME (high precision) {East-longitude positive}",
    "MOON_ME {East-longitude positive}",
}


class CustomEphemerisTimeout(TimeoutError):
    """The total acquisition or archive-lock budget expired."""


class CustomEphemerisUnavailable(RuntimeError):
    """NASA returned unavailable, invalid, or observer-incompatible data."""


class CustomArchiveError(ValueError):
    """A configured archive cannot be safely read, verified, or written."""


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _identity(site: Site, period: TimeRange) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "site": {
            "siteId": site.site_id,
            "name": site.name,
            "lat": site.lat,
            "lon": site.lon,
            "altitudeKm": site.altitude_km,
            "coordinateSource": site.coordinate_source,
        },
        "startUtc": iso_utc(period.start),
        "endUtc": iso_utc(period.end),
        "stepMinutes": period.step_minutes,
        "requestUrls": [
            query_url(query_parameters(site, target, start, end, period.step_minutes))
            for start, end in period.chunks()
            for target in TARGETS
        ],
    }


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CustomEphemerisTimeout("Custom ephemeris acquisition budget expired.")
    return remaining


def _validate_custom_dataset(dataset: dict) -> dict:
    validate_dataset(dataset)
    for item in dataset["provenance"]["requests"]:
        header = item["modelHeader"]
        if (
            re.fullmatch(
                r"Moon\s+\(301\)\s+\{source:\s*(DE440|DE441)\}", header["Center body name"]
            )
            is None
        ):
            raise ValueError("Custom ephemerides require a supported Moon dynamical source.")
        if " ".join(header["Center pole/equ"].split()) not in _FRAMES:
            raise ValueError("Custom ephemerides require the supported Mean Earth orientation.")
        radii = re.fullmatch(r"(.+?)\s+km\s*(?:\{Equator_a, b, pole_c\})?", header["Center radii"])
        axes = tuple(float(value.strip()) for value in radii[1].split(",")) if radii else ()
        if len(axes) != 3 or any(
            not math.isfinite(axis) or abs(axis - 1737.4) > 1e-6 for axis in axes
        ):
            raise ValueError("Custom ephemerides require the 1737.4 km reference sphere.")
        if header.get("Atmos refraction") != "NO (AIRLESS)":
            raise ValueError("Custom ephemerides require airless positions.")
    return dataset


class _RecordingClient(HorizonsClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.records = []

    def fetch(self, parameters: dict) -> dict:
        archive = super().fetch(parameters)
        self.records.append(archive)
        return archive


class _ReplayClient(HorizonsClient):
    def __init__(self, records: list[dict]):
        super().__init__()
        self.records = records
        self.index = 0

    def fetch(self, parameters: dict) -> dict:
        if self.index >= len(self.records):
            raise ValueError("Archive is missing a provider response.")
        record = self.records[self.index]
        self.index += 1
        self._validate_archive(record, parameters)
        return record


def _read_archive(path: Path, identity: dict, site: Site, period: TimeRange, limit: int):
    if path.is_symlink() or not path.is_file():
        raise CustomArchiveError("Custom ephemeris archive must be a regular file.")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise CustomArchiveError("Custom ephemeris archive exceeds the configured byte limit.")
    archive = json.loads(content)
    if not isinstance(archive, dict) or set(archive) != {
        "schemaVersion",
        "identity",
        "dataset",
        "datasetSha256",
        "rawResponses",
    }:
        raise ValueError("Invalid custom ephemeris archive structure.")
    if archive["schemaVersion"] != SCHEMA_VERSION or archive["identity"] != identity:
        raise ValueError("Custom ephemeris archive identity differs from the request.")
    dataset_bytes = _canonical(archive["dataset"])
    checksum = hashlib.sha256(dataset_bytes).hexdigest()
    if archive["datasetSha256"] != checksum:
        raise ValueError("Custom ephemeris dataset checksum mismatch.")
    dataset = _validate_custom_dataset(archive["dataset"])
    records = archive["rawResponses"]
    if not isinstance(records, list) or len(records) != len(identity["requestUrls"]):
        raise ValueError("Custom ephemeris archive has an incorrect response count.")
    if any(
        not isinstance(record, dict)
        or not isinstance(record.get("rawResponse"), str)
        or len(record["rawResponse"].encode("utf-8")) > MAX_RESPONSE_BYTES
        for record in records
    ):
        raise ValueError("Custom ephemeris archive contains an invalid or oversized response.")
    client = _ReplayClient(records)
    replayed = _validate_custom_dataset(client.evaluate(site, period))
    if client.index != len(records) or _canonical(replayed) != dataset_bytes:
        raise ValueError("Custom ephemeris dataset differs from its archived provider responses.")
    return VerifiedReferenceDataset(dataset, checksum)


def _inventory(directory: Path) -> list[Path]:
    entries = []
    for path in directory.iterdir():
        if _ENTRY_NAME.fullmatch(path.name):
            if path.is_symlink() or not path.is_file():
                raise CustomArchiveError("Custom ephemeris inventory contains a non-regular entry.")
            entries.append(path)
    return entries


def _make_room(directory: Path, size: int, max_entries: int, max_bytes: int) -> None:
    if size > max_bytes:
        raise CustomArchiveError("Acquired ephemeris cannot fit in the configured archive budget.")
    entries = sorted(_inventory(directory), key=lambda path: (path.stat().st_mtime_ns, path.name))
    total = sum(path.stat().st_size for path in entries)
    while entries and (len(entries) >= max_entries or total + size > max_bytes):
        oldest = entries.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink()


def _trim_existing(directory: Path, max_entries: int, max_bytes: int) -> None:
    entries = sorted(_inventory(directory), key=lambda path: (path.stat().st_mtime_ns, path.name))
    total = sum(path.stat().st_size for path in entries)
    while entries and (len(entries) > max_entries or total > max_bytes):
        oldest = entries.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink()


def acquire_custom_ephemeris(
    site: Site,
    period: TimeRange,
    *,
    archive_directory: Path,
    timeout_seconds: float,
    max_archive_entries: int = 64,
    max_archive_bytes: int = 64 * 1024 * 1024,
) -> VerifiedReferenceDataset:
    """Acquire or replay one exact observer/grid, retaining raw reproducibility evidence.

    Storage is server-selected, bounded by complete entry count and bytes. Oldest
    acquisitions are evicted under the same interprocess lock used for acquisition.
    A single atomic JSON publication makes incomplete provider calls unconsumable.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be positive and finite.")
    for name, value in (
        ("max_archive_entries", max_archive_entries),
        ("max_archive_bytes", max_archive_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    deadline = time.monotonic() + timeout_seconds
    directory = Path(archive_directory)
    identity = _identity(site, period)
    digest = hashlib.sha256(_canonical(identity)).hexdigest()
    path = directory / f"{digest}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise CustomArchiveError("Custom ephemeris archive directory must be a real directory.")
        for name in ("archive.lock", "horizons-request.lock"):
            if (directory / name).is_symlink():
                raise CustomArchiveError("Custom ephemeris lock must not be a symlink.")
        with file_lock(directory / "archive.lock", timeout=_remaining(deadline)):
            _inventory(directory)
            if path.exists() or path.is_symlink():
                result = _read_archive(path, identity, site, period, max_archive_bytes)
                _trim_existing(directory, max_archive_entries, max_archive_bytes)
                _remaining(deadline)
                return result
            client = _RecordingClient(
                timeout=min(timeout_seconds, 20),
                deadline_monotonic=deadline,
                max_attempts=1,
                max_response_bytes=MAX_RESPONSE_BYTES,
                lock_dir=directory,
            )
            try:
                dataset = _validate_custom_dataset(client.evaluate(site, period))
            except HorizonsTimeoutError as exc:
                raise CustomEphemerisTimeout("Custom Horizons acquisition timed out.") from exc
            except (HorizonsError, ValueError, KeyError, TypeError) as exc:
                raise CustomEphemerisUnavailable(
                    "Custom Horizons response failed validation."
                ) from exc
            _remaining(deadline)
            dataset_bytes = _canonical(dataset)
            checksum = hashlib.sha256(dataset_bytes).hexdigest()
            archive = {
                "schemaVersion": SCHEMA_VERSION,
                "identity": identity,
                "dataset": dataset,
                "datasetSha256": checksum,
                "rawResponses": client.records,
            }
            content = _canonical(archive) + b"\n"
            _make_room(directory, len(content), max_archive_entries, max_archive_bytes)
            atomic_write(path, content.decode("utf-8"))
            _remaining(deadline)
            return VerifiedReferenceDataset(dataset, checksum)
    except (CustomEphemerisTimeout, CustomEphemerisUnavailable, CustomArchiveError):
        raise
    except TimeoutError as exc:
        raise CustomEphemerisTimeout("Custom ephemeris archive lock timed out.") from exc
    except (OSError, ValueError, KeyError, TypeError, HorizonsError) as exc:
        raise CustomArchiveError(
            "Custom ephemeris archive is unavailable or failed verification."
        ) from exc
