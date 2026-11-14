"""Derive the fixed Site01 model baseline independently of LunarWindow production code.

Requires numpy, already a backend dependency. Run from the repo root with an explicit
--output path, then review the diff. CI never regenerates the expected results.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import groupby
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SITE_ID = "lola-site01-reference"
MASK_ID = "lola-site01-reference-mast-0m"
MASK_SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"
EPHEMERIS_SHA256 = "519628d7384992cc012039fe9df226a932d6c482de56b0b3277fdff6f30e9b50"
RULES = ("any-disc", "body-center", "full-disc")


def read_pinned(path, expected_sha256):
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError(f"Reviewed input checksum differs: {path}")
    return json.loads(content)


def horizon_at(profile, azimuth):
    azimuth = Decimal(str(azimuth))
    left = int(azimuth)
    return profile[left] + (profile[(left + 1) % 360] - profile[left]) * (
        azimuth - left
    )


def model_case(source, profile, rule):
    times = [row["t"] for row in source["series"]]
    start = datetime.fromisoformat(source["provenance"]["startUtc"])
    step = timedelta(minutes=source["provenance"]["stepMinutes"])
    end = datetime.fromisoformat(source["provenance"]["endUtc"])
    if len(times) != 720 or step != timedelta(hours=1) or end - start != 720 * step:
        raise ValueError(
            "This baseline is specifically the reviewed 720-hour Site01 archive."
        )
    bodies, states, horizons, margins = {}, {}, {}, {}
    for body in ("sun", "earth"):
        angles = [row[body + "Az"] for row in source["series"]]
        heights = [horizon_at(profile, az) for az in angles]
        independent = np.interp(
            angles, np.arange(360), [float(v) for v in profile], period=360
        )
        if not np.allclose(
            independent, [float(v) for v in heights], rtol=0, atol=1e-12
        ):
            raise ValueError("Decimal and NumPy horizon interpolation disagree.")
        center = [
            Decimal(str(row[body + "El"])) - height
            for row, height in zip(source["series"], heights)
        ]
        radius = [
            Decimal(str(row[body + "AngularRadiusDeg"])) for row in source["series"]
        ]
        upper = [value + size for value, size in zip(center, radius)]
        lower = [value - size for value, size in zip(center, radius)]
        flags = {
            "any-disc": [value > 0 for value in upper],
            "body-center": [value > 0 for value in center],
            "full-disc": [value >= 0 for value in lower],
        }
        bodies[body] = flags[rule]
        states[body] = dict(
            Counter(
                "hidden" if u <= 0 else "full" if l >= 0 else "partial"
                for u, l in zip(upper, lower)
            )
        )
        horizons[body] = heights
        margins[body] = min(
            abs(value) for values in (center, upper, lower) for value in values
        )

    def windows(flags):
        result = []
        for active, entries in groupby(enumerate(flags), key=lambda entry: entry[1]):
            indices = [entry[0] for entry in entries]
            if active:
                result.append(
                    {
                        "startUtc": times[indices[0]],
                        "endUtc": (start + (indices[-1] + 1) * step)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "durationHrs": len(indices),
                        "startTruncated": indices[0] == 0,
                        "endTruncated": indices[-1] == len(times) - 1,
                    }
                )
        return result

    sun, earth = bodies["sun"], bodies["earth"]
    flags = {
        "sunlit": sun,
        "earthVisible": earth,
        "both": [s and e for s, e in zip(sun, earth)],
        "darkness": [not s for s in sun],
        "earthBlackout": [not e for e in earth],
    }
    runs = {name: windows(values) for name, values in flags.items()}
    metrics = {"evaluatedHrs": 720, "asOfUtc": times[0]}
    for name, hours_key, percent_key in (
        ("sunlit", "sunlitHrs", "pctSun"),
        ("earthVisible", "earthVisibleHrs", "pctEarth"),
        ("both", "bothHrs", "pctBoth"),
    ):
        metrics[hours_key] = sum(flags[name])
        metrics[percent_key] = float(Fraction(100 * sum(flags[name]), len(times)))
    for name, key in (
        ("darkness", "longestDarkHrs"),
        ("earthBlackout", "longestEarthBlackoutHrs"),
        ("both", "longestBothHrs"),
    ):
        metrics[key] = max((run["durationHrs"] for run in runs[name]), default=0)
    for name, suffix in (("sunlit", "Sunset"), ("earthVisible", "Earthset")):
        setting = next(
            (run["endUtc"] for run in runs[name] if not run["endTruncated"]), None
        )
        instant = datetime.fromisoformat(setting) if setting else None
        metrics["next" + suffix] = setting
        metrics["hoursTo" + suffix] = (
            (instant - start).total_seconds() / 3600 if instant else None
        )
        metrics["next" + suffix + "Bracket"] = (
            {
                "afterUtc": (instant - step).isoformat().replace("+00:00", "Z"),
                "byUtc": setting,
            }
            if instant
            else None
        )
    checkpoints = [
        {
            "t": times[i],
            **{body + "HorizonEl": float(horizons[body][i]) for body in horizons},
        }
        for i in (0, 1, 24, 120, 240, 360, 480, 600, 719)
    ]
    return {
        "metrics": metrics,
        "windows": runs,
        "discStateCounts": states,
        "minAbsThresholdClearanceDeg": {
            body: float(value) for body, value in margins.items()
        },
        "horizonCheckpoints": checkpoints,
    }


def build(reference_root):
    source = read_pinned(
        reference_root / "validation-30d" / f"{SITE_ID}.json", EPHEMERIS_SHA256
    )
    mask = read_pinned(
        reference_root / "terrain-masks" / f"{MASK_ID}.json", MASK_SHA256
    )
    with localcontext() as context:
        context.prec = 50
        terrain = [Decimal(str(point["el"])) for point in mask["horizon"]]
        modes = {
            name: {rule: model_case(source, profile, rule) for rule in RULES}
            for name, profile in (
                ("geometric", [Decimal(0)] * 360),
                ("terrain", terrain),
            )
        }
    return {
        "schemaVersion": "lunarwindow.terrain-regression.v1",
        "scope": "Software model regression only; no independent terrain-observation validation",
        "derivation": "50-digit Decimal thresholds, NumPy periodic interpolation cross-check, grouped hourly runs and rational percentages; no production imports",
        "siteId": SITE_ID,
        "maskId": MASK_ID,
        "maskSha256": MASK_SHA256,
        "ephemerisSha256": EPHEMERIS_SHA256,
        "startUtc": source["provenance"]["startUtc"],
        "endUtc": source["provenance"]["endUtc"],
        "stepMinutes": 60,
        "modes": modes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, default=ROOT / "data/reference")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(build(args.reference_root), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
