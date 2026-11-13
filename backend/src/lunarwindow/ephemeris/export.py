"""Publish an immutable run directory only after every site's files are complete."""

import csv
import hashlib
import io
import json
import platform
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .contract import validate_dataset, verify_run
from .models import iso_utc
from .storage import atomic_write

FIELDS = [
    "t",
    "sunAz",
    "sunEl",
    "earthAz",
    "earthEl",
    "sunAngularRadiusDeg",
    "earthAngularRadiusDeg",
]


def export_run(client, sites, period, output: Path, progress=None) -> Path:
    sites = list(sites)
    if not sites or len({site.site_id for site in sites}) != len(sites):
        raise ValueError("Exports require a nonempty list of unique site IDs.")
    output.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=output))
    manifest = {
        "schemaVersion": "lunarwindow.run.v1",
        "runId": run_id,
        "status": "incomplete",
        "createdAtUtc": iso_utc(datetime.now(timezone.utc)),
        "software": {
            "packageVersion": version("lunarwindow-ephemeris"),
            "pythonVersion": platform.python_version(),
        },
        "period": {
            "startUtc": iso_utc(period.start),
            "endUtc": iso_utc(period.end),
            "stepMinutes": period.step_minutes,
        },
        "datasets": [],
    }
    try:
        for site in sites:
            if progress:
                progress(site, period)
            dataset = validate_dataset(client.evaluate(site, period))
            json_path = staging / f"{site.site_id}.json"
            csv_path = json_path.with_suffix(".csv")
            atomic_write(json_path, json.dumps(dataset, indent=2, allow_nan=False) + "\n")
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(dataset["series"])
            atomic_write(csv_path, buffer.getvalue())
            manifest["datasets"].append(
                {
                    "siteId": site.site_id,
                    "samples": len(dataset["series"]),
                    "json": json_path.name,
                    "csv": csv_path.name,
                    "jsonSha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
                    "csvSha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                }
            )
        manifest["status"] = "complete"
        atomic_write(staging / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        verify_run(staging)
        destination = output / run_id
        staging.rename(destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)
