"""Reproducible pointing plots and contract-validation summary for a complete run."""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from .contract import verify_run
from .storage import atomic_write


def make_report(directory: Path, quickmap_results: Path | None = None) -> dict:
    manifest = verify_run(directory)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np

    datasets = [
        json.loads((directory / item["json"]).read_text(encoding="utf-8"))
        for item in manifest["datasets"]
    ]
    fig, axes = plt.subplots(
        3, len(datasets), figsize=(5 * len(datasets), 9), squeeze=False, sharex="col"
    )
    report = {
        "runId": manifest["runId"],
        "contractValidation": "pass",
        "quickmapValidation": "pending",
        "terrainModel": "none",
        "sites": [],
    }
    if quickmap_results is not None:
        comparison = json.loads(quickmap_results.read_text(encoding="utf-8"))
        report["quickmapValidation"] = comparison["status"]
        report["quickmapScope"] = comparison["scope"]
        report["quickmapEvidenceSha256"] = hashlib.sha256(quickmap_results.read_bytes()).hexdigest()
    for column, dataset in enumerate(datasets):
        times = [
            datetime.fromisoformat(row["t"].replace("Z", "+00:00")) for row in dataset["series"]
        ]
        earth = [row["earthEl"] for row in dataset["series"]]
        sun = [row["sunEl"] for row in dataset["series"]]
        azimuth = np.rad2deg(np.unwrap(np.deg2rad([row["earthAz"] for row in dataset["series"]])))
        for row, (values, label, color) in enumerate(
            [
                (earth, "Earth elevation (deg)", "#3671ab"),
                (sun, "Sun elevation (deg)", "#b96c13"),
                (azimuth, "Earth azimuth, unwrapped (deg)", "#8054a0"),
            ]
        ):
            ax = axes[row, column]
            ax.plot(times, values, color=color, linewidth=1.7)
            ax.set_ylabel(label)
            ax.set_xlim(times[0], times[-1])
            ax.grid(alpha=0.2)
            if row < 2:
                ax.axhline(0, color="#67717e", linewidth=0.8, linestyle="--")
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=4))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        axes[0, column].set_title(
            dataset["site"].replace(" DEM reference point", "")
            + f"\n{dataset['lat']:.4f} deg, {dataset['lon']:.4f} deg E",
            fontsize=11,
        )
        axes[2, column].set_xlabel("UTC date")
        report["sites"].append(
            {
                "siteId": dataset["siteId"],
                "samples": len(times),
                "earthElevationRangeDeg": [min(earth), max(earth)],
                "sunElevationRangeDeg": [min(sun), max(sun)],
                "earthAzimuthRangeUnwrappedDeg": [float(min(azimuth)), float(max(azimuth))],
            }
        )
    start = datetime.fromisoformat(manifest["period"]["startUtc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(manifest["period"]["endUtc"].replace("Z", "+00:00"))
    days = (end - start).total_seconds() / 86400
    fig.suptitle(
        f"LunarWindow | {days:g}-day Sun and Earth pointing reference", fontsize=18, y=0.98
    )
    fig.text(
        0.5,
        0.925,
        "NASA LOLA DEM reference points | apparent body centers | local horizontal plane | terrain obstruction not modeled",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.025,
        "Earth azimuth is unwrapped for continuity. These local angles are not libration longitude/latitude.\nThe 0-degree lines do not model a terrain horizon; positive elevation alone does not establish usable power or a radio link.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.075, 1, 0.91), h_pad=2)
    for extension in ("png", "svg"):
        fig.savefig(directory / f"pointing-reference.{extension}", dpi=160)
    svg = directory / "pointing-reference.svg"
    atomic_write(
        svg,
        "\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n",
    )
    plt.close(fig)
    report["figureSha256"] = hashlib.sha256(
        (directory / "pointing-reference.png").read_bytes()
    ).hexdigest()
    atomic_write(directory / "validation-summary.json", json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--quickmap-results", type=Path)
    args = parser.parse_args()
    try:
        result = make_report(args.run, args.quickmap_results)
        print(json.dumps(result, indent=2))
        return 0
    except ImportError:
        print(
            "Install analysis dependencies with: pip install -e './backend[analysis]'",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Report failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
