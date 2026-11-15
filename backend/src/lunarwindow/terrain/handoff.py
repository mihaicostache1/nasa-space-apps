"""Offline GIS handoff checks; compatibility never grants scientific review or registration."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter

from lunarwindow.api.terrain_models import TerrainCompatibilityProvenance
from lunarwindow.reference import load_verified_reference_dataset

from .compatibility import check_terrain_compatibility
from .loader import load_terrain_mask
from .models import Slug, TerrainMask
from .registry import load_reviewed_mask, reviewed_mask_ids

_SITE_ID = TypeAdapter(Slug)
_LIMITATION = (
    "These checks establish artifact integrity, contract validity, and observer/frame "
    "compatibility under the stated policy. They do not review DEM quality, independently "
    "validate terrain events, register a mask, or accept an approximation for API callers."
)


def _report(
    mask: TerrainMask,
    checksum: str,
    reference_directory: Path,
    *,
    allow_mean_earth_approximation: bool,
) -> dict:
    verified = load_verified_reference_dataset(reference_directory, mask.siteId)
    dataset = verified.dataset
    assessment = check_terrain_compatibility(
        mask, dataset, allow_mean_earth_approximation=allow_mean_earth_approximation
    )
    source = dataset["provenance"]
    return {
        "schemaVersion": "lunarwindow.terrain-handoff.v1",
        "status": "compatible",
        "siteId": mask.siteId,
        "maskId": mask.maskId,
        "artifactSha256": checksum,
        "observer": mask.observer.model_dump(mode="json"),
        "referenceFrame": mask.referenceFrame.model_dump(mode="json"),
        "demSources": [item.model_dump(mode="json") for item in mask.provenance.sources],
        "algorithm": mask.provenance.algorithm.model_dump(mode="json"),
        "ephemeris": {
            "artifactSha256": verified.artifact_sha256,
            "startUtc": source["startUtc"],
            "endUtc": source["endUtc"],
            "endExclusive": source["endExclusive"],
            "stepMinutes": source["stepMinutes"],
            "sampleCount": len(dataset["series"]),
            "coordinateSource": dataset["coordinateSource"],
        },
        "compatibility": TerrainCompatibilityProvenance.from_assessment(assessment).model_dump(
            mode="json"
        ),
        "limitation": _LIMITATION,
    }


def verify_candidate(
    path: Path,
    *,
    expected_sha256: str,
    expected_site_id: str,
    reference_directory: Path,
    allow_mean_earth_approximation: bool = False,
) -> dict:
    """Check a supplied artifact against separately trusted identity and exact source bytes.

    Read-only and offline: no downloads, registration, sidecar trust, or calculations.
    Check the full archive, rather than a selected date subset. Raise on any failure.
    """
    site_id = _SITE_ID.validate_python(expected_site_id, strict=True)
    mask = load_terrain_mask(path, expected_sha256=expected_sha256)
    if mask.siteId != site_id:
        raise ValueError("Terrain handoff siteId differs from the expected site.")
    return _report(
        mask,
        expected_sha256,
        reference_directory,
        allow_mean_earth_approximation=allow_mean_earth_approximation,
    )


def verify_registered(
    reference_directory: Path,
    terrain_directory: Path,
    *,
    allow_mean_earth_approximation: bool = False,
) -> list[dict]:
    """Check every trusted registration, including sites absent from the archive."""
    reports = []
    for mask_id in reviewed_mask_ids():
        reviewed = load_reviewed_mask(terrain_directory, mask_id)
        reports.append(
            _report(
                reviewed.mask,
                reviewed.artifact_sha256,
                reference_directory,
                allow_mean_earth_approximation=allow_mean_earth_approximation,
            )
        )
    return reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lunarwindow-terrain-handoff", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("candidate", help="Check a GIS file before registration")
    candidate.add_argument("path", type=Path)
    candidate.add_argument("--site-id", required=True)
    candidate.add_argument("--expected-sha256", required=True)
    registered = commands.add_parser("registered", help="Check all trusted registrations")
    registered.add_argument("--terrain-dir", type=Path, required=True)
    for command in (candidate, registered):
        command.add_argument("--reference-dir", type=Path, required=True)
        command.add_argument("--allow-mean-earth-approximation", action="store_true")
    args = parser.parse_args(argv)
    try:
        options = {"allow_mean_earth_approximation": args.allow_mean_earth_approximation}
        if args.command == "candidate":
            report = verify_candidate(
                args.path,
                expected_sha256=args.expected_sha256,
                expected_site_id=args.site_id,
                reference_directory=args.reference_dir,
                **options,
            )
        else:
            report = {
                "schemaVersion": "lunarwindow.terrain-handoffs.v1",
                "status": "compatible",
                "masks": verify_registered(args.reference_dir, args.terrain_dir, **options),
                "limitation": _LIMITATION,
            }
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, LookupError) as exc:
        print(f"Terrain handoff {args.command} failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Terrain handoff interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
