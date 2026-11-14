"""Build, verify, and replay pinned offline data releases without changing published runs."""

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter

from lunarwindow.ephemeris.storage import atomic_write
from lunarwindow.terrain.models import Sha256

from .generator import PrecomputeGenerationError, generate_bundle
from .models import PrecomputeManifest
from .verifier import _read_artifact, verify_bundle

_SHA256 = TypeAdapter(Sha256)


def _plan(content: bytes) -> PrecomputeManifest:
    plan = PrecomputeManifest.model_validate_json(content)
    if plan.status != "incomplete" or any(job.status != "pending" for job in plan.jobs):
        raise ValueError("Release plans require an incomplete manifest with all jobs pending.")
    return plan


def _checksums(content: bytes, expected: set[str]) -> dict[str, str]:
    result = {}
    for line in content.decode("utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise ValueError("Invalid SHA256SUMS row; expected checksum, two spaces, and filename.")
        checksum, name = parts
        _SHA256.validate_python(checksum, strict=True)
        if name not in expected or name in result:
            raise ValueError("SHA256SUMS contains an unexpected or duplicate artifact.")
        result[name] = checksum
    if set(result) != expected:
        raise ValueError("SHA256SUMS must describe exactly the plan, bundle manifest, and outputs.")
    return result


def verify_release(
    directory: Path,
    *,
    reference_directory: Path,
    terrain_directory: Path | None = None,
) -> PrecomputeManifest:
    """Check the release closure, pinned plan, payloads, and current source evidence."""
    directory = Path(directory)
    plan_bytes = _read_artifact(directory, "plan.json")
    plan = _plan(plan_bytes)
    manifest_bytes = _read_artifact(directory / "bundle", "manifest.json")
    recorded = PrecomputeManifest.model_validate_json(manifest_bytes)
    if recorded.status != "complete" or recorded.runId != plan.runId:
        raise ValueError("Release bundle must be complete and use the planned run ID.")
    if [job.evaluation for job in recorded.jobs] != [job.evaluation for job in plan.jobs]:
        raise ValueError("Release bundle jobs must exactly match the pinned plan in order.")
    expected = {"plan.json", "bundle/manifest.json"} | {
        f"bundle/{job.output.filename}" for job in recorded.jobs
    }
    sums = _checksums(_read_artifact(directory, "SHA256SUMS"), expected)
    for name, content in (("plan.json", plan_bytes), ("bundle/manifest.json", manifest_bytes)):
        if hashlib.sha256(content).hexdigest() != sums[name]:
            raise ValueError(f"Release checksum mismatch: {name}")
    for job in recorded.jobs:
        if sums[f"bundle/{job.output.filename}"] != job.output.sha256:
            raise ValueError("Release and bundle output checksums disagree.")
    verified = verify_bundle(
        directory / "bundle",
        reference_directory=reference_directory,
        terrain_directory=terrain_directory,
    )
    if verified != recorded:
        raise ValueError("Bundle manifest changed during release verification.")
    return verified


def build_release(
    plan_path: Path,
    *,
    output_directory: Path,
    reference_directory: Path,
    terrain_directory: Path | None = None,
) -> PrecomputeManifest:
    """Build a fresh release; publish SHA256SUMS only after all bundle checks pass."""
    plan_bytes = Path(plan_path).read_bytes()
    plan = _plan(plan_bytes)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    atomic_write(output_directory / "plan.json", plan_bytes.decode("utf-8"))
    generate_bundle(
        plan.jobs,
        run_id=plan.runId,
        output_directory=output_directory / "bundle",
        reference_directory=reference_directory,
        terrain_directory=terrain_directory,
    )
    manifest = verify_bundle(
        output_directory / "bundle",
        reference_directory=reference_directory,
        terrain_directory=terrain_directory,
    )
    checksums = {
        "plan.json": hashlib.sha256(plan_bytes).hexdigest(),
        "bundle/manifest.json": hashlib.sha256(
            (output_directory / "bundle/manifest.json").read_bytes()
        ).hexdigest(),
        **{f"bundle/{job.output.filename}": job.output.sha256 for job in manifest.jobs},
    }
    atomic_write(
        output_directory / "SHA256SUMS",
        "".join(f"{checksums[name]}  {name}\n" for name in sorted(checksums)),
    )
    return verify_release(
        output_directory,
        reference_directory=reference_directory,
        terrain_directory=terrain_directory,
    )


def check_release(
    directory: Path,
    *,
    reference_directory: Path,
    terrain_directory: Path | None = None,
) -> PrecomputeManifest:
    """Rebuild into temporary storage; compare exact payload bytes and manifest semantics.

    Actual generation timestamps are retained as audit metadata and excluded from
    replay comparison. The published release is never modified.
    """
    directory = Path(directory)
    original = verify_release(
        directory, reference_directory=reference_directory, terrain_directory=terrain_directory
    )
    with tempfile.TemporaryDirectory(prefix="lunarwindow-release-") as temporary:
        candidate_dir = Path(temporary) / "release"
        candidate = build_release(
            directory / "plan.json",
            output_directory=candidate_dir,
            reference_directory=reference_directory,
            terrain_directory=terrain_directory,
        )
        excluded = {"createdAtUtc", "completedAtUtc"}
        if original.model_dump(exclude=excluded) != candidate.model_dump(exclude=excluded):
            raise ValueError("Rebuilt release manifest differs beyond generation timestamps.")
        for job in original.jobs:
            filename = job.output.filename
            if (directory / "bundle" / filename).read_bytes() != (
                candidate_dir / "bundle" / filename
            ).read_bytes():
                raise ValueError(f"Rebuilt release payload differs: {filename}")
    return original


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lunarwindow-data-release", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build a new release from an explicit pending plan")
    build.add_argument("path", type=Path, help="Pending plan JSON")
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify a published release and its sources")
    check = commands.add_parser("check", help="Verify and independently rebuild a release")
    for command in (verify, check):
        command.add_argument("path", type=Path, help="Published release directory")
    for command in (build, verify, check):
        command.add_argument("--reference-dir", type=Path, required=True)
        command.add_argument("--terrain-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        options = {"reference_directory": args.reference_dir, "terrain_directory": args.terrain_dir}
        if args.command == "build":
            manifest = build_release(args.path, output_directory=args.output, **options)
            directory = args.output
        else:
            operation = check_release if args.command == "check" else verify_release
            manifest = operation(args.path, **options)
            directory = args.path
        print(
            json.dumps(
                {
                    "command": args.command,
                    "runId": manifest.runId,
                    "status": manifest.status,
                    "jobCount": len(manifest.jobs),
                    "release": str(directory),
                }
            )
        )
        return 0
    except (OSError, ValueError, PrecomputeGenerationError) as exc:
        print(f"Data release {args.command} failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Data release interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
