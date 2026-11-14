"""Read site metadata and ephemerides from a verified offline reference bundle."""

import hashlib
import json
from pathlib import Path

from lunarwindow.ephemeris.contract import validate_dataset, verify_run


def _read_verified_dataset(directory: Path, item: dict) -> dict:
    content = (directory / item["json"]).read_bytes()
    # Check the exact bytes returned, even if a file changed after verify_run.
    if hashlib.sha256(content).hexdigest() != item["jsonSha256"]:
        raise ValueError(f"Checksum mismatch: {item['json']}")
    return validate_dataset(json.loads(content))


def load_reference_dataset(directory: str | Path, site_id: str) -> dict:
    """Return one dataset, including its original provenance, without writing files.

    Verify the entire complete bundle before selecting a site. Raise LookupError
    for an unknown site, or ValueError for an unreadable or invalid bundle. The
    caller supplies the directory explicitly; no working-directory guess is used.
    """
    directory = Path(directory)
    try:
        manifest = verify_run(directory)
        item = next((item for item in manifest["datasets"] if item["siteId"] == site_id), None)
        if item is None:
            raise LookupError(f"Unknown reference site {site_id!r} in {directory}.")
        return _read_verified_dataset(directory, item)
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
