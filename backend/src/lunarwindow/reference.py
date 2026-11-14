"""Read site metadata and ephemerides from a verified offline reference bundle."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from lunarwindow.ephemeris.contract import validate_dataset, verify_run
from lunarwindow.ephemeris.models import TimeRange, iso_utc


class ReferenceSelectionError(ValueError):
    """A requested range or sampling interval is unsupported by the archive."""


@dataclass(frozen=True)
class VerifiedReferenceDataset:
    """Parsed dataset and checksum from the same verified byte snapshot."""

    dataset: dict
    artifact_sha256: str


def _read_verified_artifact(directory: Path, item: dict) -> VerifiedReferenceDataset:
    content = (directory / item["json"]).read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    # Check the exact bytes returned, even if a file changed after verify_run.
    if checksum != item["jsonSha256"]:
        raise ValueError(f"Checksum mismatch: {item['json']}")
    return VerifiedReferenceDataset(validate_dataset(json.loads(content)), checksum)


def _read_verified_dataset(directory: Path, item: dict) -> dict:
    return _read_verified_artifact(directory, item).dataset


def load_reference_dataset(directory: str | Path, site_id: str) -> dict:
    """Return one dataset, including its original provenance, without writing files.

    Verify the entire complete bundle before selecting a site. Raise LookupError
    for an unknown site, or ValueError for an unreadable or invalid bundle. The
    caller supplies the directory explicitly; no working-directory guess is used.
    """
    return load_verified_reference_dataset(directory, site_id).dataset


def load_verified_reference_dataset(
    directory: str | Path, site_id: str
) -> VerifiedReferenceDataset:
    """Verify the whole run and return one dataset with its exact artifact checksum.

    Preserve the existing loader's lookup/error behavior. Never hash a second file
    read to identify data parsed from an earlier snapshot.
    """
    directory = Path(directory)
    try:
        manifest = verify_run(directory)
        item = next((item for item in manifest["datasets"] if item["siteId"] == site_id), None)
        if item is None:
            raise LookupError(f"Unknown reference site {site_id!r} in {directory}.")
        return _read_verified_artifact(directory, item)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot load reference bundle at {directory}: {exc}") from exc


def load_reference_catalog(directory: str | Path) -> list[dict]:
    """Return site coordinates and archive coverage after verifying the whole run.

    Preserve manifest order and the datasets' coordinate-source descriptions.
    Invalid bundles raise ValueError; no partial catalog is returned.
    """
    directory = Path(directory)
    try:
        manifest = verify_run(directory)
        sites = []
        for item in manifest["datasets"]:
            dataset = _read_verified_dataset(directory, item)
            provenance = dataset["provenance"]
            sites.append(
                {
                    "id": dataset["siteId"],
                    "name": dataset["site"],
                    "lat": dataset["lat"],
                    "lon": dataset["lon"],
                    "altitudeKm": dataset["altitudeKm"],
                    "coordinateSource": dataset["coordinateSource"],
                    "availability": {
                        "startUtc": provenance["startUtc"],
                        "endUtc": provenance["endUtc"],
                        "endExclusive": provenance["endExclusive"],
                        "stepMinutes": provenance["stepMinutes"],
                        "sampleCount": len(dataset["series"]),
                    },
                }
            )
        return sites
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot load reference bundle at {directory}: {exc}") from exc


def select_reference_dataset(
    dataset: dict,
    *,
    start_utc: str | None = None,
    end_utc: str | None = None,
    step_minutes: int | None = None,
) -> dict:
    """Select existing samples on a contained grid, preserving source evidence.

    Omitted bounds/step use the archive's values. The start must be on its grid;
    the end may fall between samples. No interpolation or extrapolation is used.
    Source validation errors remain distinct from unsupported request errors.
    """
    validate_dataset(dataset)
    source = dataset["provenance"]
    archive = TimeRange(source["startUtc"], source["endUtc"], source["stepMinutes"])
    try:
        period = TimeRange(
            source["startUtc"] if start_utc is None else start_utc,
            source["endUtc"] if end_utc is None else end_utc,
            source["stepMinutes"] if step_minutes is None else step_minutes,
        )
    except ValueError as exc:
        raise ReferenceSelectionError(str(exc)) from exc
    if period.start < archive.start or period.end > archive.end:
        raise ReferenceSelectionError(
            f"Requested range must be within [{source['startUtc']}, {source['endUtc']})."
        )
    if (period.start - archive.start) % archive.step:
        raise ReferenceSelectionError(
            f"startUtc must align with the archive's {archive.step_minutes}-minute grid "
            f"anchored at {source['startUtc']}."
        )
    if period.step_minutes % archive.step_minutes:
        raise ReferenceSelectionError(
            f"stepMinutes must be a multiple of the archive's {archive.step_minutes}-minute interval."
        )
    first = (period.start - archive.start) // archive.step
    stride = period.step_minutes // archive.step_minutes
    selected = {
        **dataset,
        "series": deepcopy(
            dataset["series"][first : first + period.sample_count * stride : stride]
        ),
        "provenance": deepcopy(source),
    }
    selected["provenance"].update(
        startUtc=iso_utc(period.start),
        endUtc=iso_utc(period.end),
        stepMinutes=period.step_minutes,
    )
    return validate_dataset(selected)
