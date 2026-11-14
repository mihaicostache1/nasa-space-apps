"""Read a single ephemeris dataset from a verified offline reference bundle."""

import hashlib
import json
from pathlib import Path

from lunarwindow.ephemeris.contract import validate_dataset, verify_run


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
        content = (directory / item["json"]).read_bytes()
        # Check the exact bytes returned, even if a file changed after verify_run.
        if hashlib.sha256(content).hexdigest() != item["jsonSha256"]:
            raise ValueError(f"Checksum mismatch: {item['json']}")
        return validate_dataset(json.loads(content))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot load reference bundle at {directory}: {exc}") from exc
