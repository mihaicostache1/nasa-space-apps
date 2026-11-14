"""Generate and verify explicit evaluation bundles using offline reference artifacts."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .generator import PrecomputeGenerationError, generate_bundle
from .models import PrecomputeManifest
from .verifier import verify_bundle


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lunarwindow-precompute", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Generate every job in a pending manifest plan")
    generate.add_argument("plan", type=Path, help="Incomplete manifest JSON with all jobs pending")
    generate.add_argument(
        "--output", type=Path, required=True, help="New bundle directory; never overwritten"
    )
    verify = commands.add_parser(
        "verify", help="Verify a complete saved bundle against its sources"
    )
    verify.add_argument("bundle", type=Path, help="Directory containing manifest.json and outputs")
    for command in (generate, verify):
        command.add_argument(
            "--reference-dir",
            type=Path,
            required=True,
            help="Verified archive directory, e.g. data/reference/validation-30d",
        )
        command.add_argument(
            "--terrain-dir",
            type=Path,
            help="Reviewed masks; defaults to the archive directory's sibling terrain-masks",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            plan = PrecomputeManifest.model_validate_json(args.plan.read_bytes())
            if plan.status != "incomplete" or any(job.status != "pending" for job in plan.jobs):
                raise ValueError(
                    "Generation plans must be incomplete manifests with all jobs pending."
                )
            manifest = generate_bundle(
                plan.jobs,
                run_id=plan.runId,
                reference_directory=args.reference_dir,
                terrain_directory=args.terrain_dir,
                output_directory=args.output,
            )
            directory = args.output
        else:
            manifest = verify_bundle(
                args.bundle,
                reference_directory=args.reference_dir,
                terrain_directory=args.terrain_dir,
            )
            directory = args.bundle
        print(
            json.dumps(
                {
                    "command": args.command,
                    "status": manifest.status,
                    "runId": manifest.runId,
                    "jobCount": len(manifest.jobs),
                    "manifest": str(directory / "manifest.json"),
                }
            )
        )
        return 0
    except (OSError, ValueError, PrecomputeGenerationError) as exc:
        detail = str(exc)
        if isinstance(exc, PrecomputeGenerationError) and exc.__cause__ is not None:
            detail += f" Cause: {exc.__cause__}"
        print(f"Precompute {args.command} failed: {detail}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"Precompute {args.command} interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
