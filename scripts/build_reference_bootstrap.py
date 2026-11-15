"""Publish frontend startup metadata only after verifying the pinned offline release."""

import argparse
import hashlib
import json
from pathlib import Path

from lunarwindow.api.reference_catalog import build_reference_catalog
from lunarwindow.ephemeris.contract import validation_session
from lunarwindow.precompute.release import verify_release

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "data/releases/lunarwindow-demo-v1"
REFERENCE = ROOT / "data/reference/validation-30d"
TERRAIN = ROOT / "data/reference/terrain-masks"
OUTPUT = ROOT / "data/frontend/reference-bootstrap.json"
SITES = ("lola-site01-reference", "lola-site23-reference")


@validation_session()
def build_metadata() -> dict:
    """Keep evaluations in their original release files; copy only discovery metadata."""
    manifest = verify_release(
        RELEASE, reference_directory=REFERENCE, terrain_directory=TERRAIN
    )
    catalog = build_reference_catalog(REFERENCE, TERRAIN)
    scenarios = []
    for slot, site_id in zip(("A", "B"), SITES, strict=True):
        site = next(site for site in catalog.sites if site.id == site_id)
        jobs = [
            job
            for job in manifest.jobs
            if job.evaluation.siteId == site_id
            and job.evaluation.horizonMode == "geometric"
            and job.evaluation.startUtc == site.availability.startUtc
            and job.evaluation.endUtc == site.availability.endUtc
            and job.evaluation.stepMinutes == site.availability.stepMinutes
            and job.evaluation.visibilityRule == "any-disc"
            and job.evaluation.asOfUtc == job.evaluation.startUtc
        ]
        if len(jobs) != 1:
            raise ValueError(
                f"Expected exactly one verified default evaluation for {site_id}."
            )
        job = jobs[0]
        scenarios.append(
            {
                "slot": slot,
                "request": job.evaluation.model_dump(
                    mode="json",
                    include={
                        "siteId",
                        "horizonMode",
                        "startUtc",
                        "endUtc",
                        "stepMinutes",
                        "visibilityRule",
                    },
                ),
                "output": job.output.model_dump(mode="json"),
            }
        )
    return {
        "schemaVersion": "lunarwindow.reference-bootstrap.v1",
        "releaseId": manifest.runId,
        "releaseManifestSha256": hashlib.sha256(
            (RELEASE / "bundle/manifest.json").read_bytes()
        ).hexdigest(),
        "catalog": catalog.model_dump(mode="json"),
        "scenarios": scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Reject missing or stale metadata."
    )
    args = parser.parse_args()
    expected = (
        json.dumps(build_metadata(), indent=2, ensure_ascii=False) + "\n"
    ).encode()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != expected:
            parser.exit(
                1,
                "Frontend bootstrap is stale; run scripts/build_reference_bootstrap.py.\n",
            )
        print(
            "Verified frontend startup metadata against the pinned release and source data."
        )
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_bytes(expected)
        print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
