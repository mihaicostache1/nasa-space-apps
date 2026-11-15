"""Replay pinned surface SPICE evidence and explicitly audit terrain-evidence gaps."""

import argparse
import json
import math
import sys
from decimal import Decimal, localcontext
from pathlib import Path

from build_surface_spice_reference import INPUTS, ROOT, VERSION, read_inputs, sha256
from science_terrain_evidence import assess_terrain_evidence

REFERENCE = ROOT / "docs/validation/evidence/surface-spice-reference.json"
REFERENCE_HASH = REFERENCE.with_suffix(".json.sha256")
MASK = ROOT / "data/reference/terrain-masks/lola-site01-reference-mast-0m.json"
MASK_SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"
QUANTITIES = (
    "sunAz",
    "sunEl",
    "earthAz",
    "earthEl",
    "sunAngularRadiusDeg",
    "earthAngularRadiusDeg",
)


def checked_rows(actual, expected):
    if len(actual) != len(expected) or not actual:
        raise ValueError("Oracle and archive sample counts differ or are empty.")
    for row, oracle in zip(actual, expected):
        if row["t"] != oracle["t"]:
            raise ValueError("Oracle and archive UTC grids differ.")
        for key in QUANTITIES:
            for value in (row[key], oracle[key]):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError("Non-finite or invalid scientific angle.")
                low, high = (
                    (0, 360)
                    if key.endswith("Az")
                    else (0, 90)
                    if key.endswith("RadiusDeg")
                    else (-90, 90)
                )
                if not low <= value <= high or (key.endswith("Az") and value == 360):
                    raise ValueError(
                        "Scientific angle is outside its coordinate range."
                    )
        yield row, oracle


def pointing_comparison(actual, expected, criteria):
    worst = {key: {"maxAbsDifferenceDeg": -1.0} for key in QUANTITIES}
    failed = 0
    samples = 0
    for row, oracle in checked_rows(actual, expected):
        samples += 1
        for key in QUANTITIES:
            delta = row[key] - oracle[key]
            if key.endswith("Az"):
                delta = (delta + 180) % 360 - 180
            tolerance = (
                criteria["angularRadiusToleranceDeg"]
                if key.endswith("RadiusDeg")
                else criteria["pointingToleranceDeg"]
            )
            failed += int(abs(delta) > tolerance)
            if abs(delta) > worst[key]["maxAbsDifferenceDeg"]:
                worst[key] = {
                    "maxAbsDifferenceDeg": abs(delta),
                    "differenceDeg": delta,
                    "timestampUtc": row["t"],
                    "horizonsDeg": row[key],
                    "spiceDeg": oracle[key],
                    "toleranceDeg": tolerance,
                }
    return {
        "status": "fail" if failed else "pass-cross-tool-consistency",
        "samples": samples,
        "angleComparisons": samples * len(QUANTITIES),
        "failedComparisons": failed,
        "quantities": worst,
    }


def horizon_at(profile, azimuth):
    """Independent decimal interpolation for the reviewed whole-degree profile."""
    with localcontext() as context:
        context.prec = 50
        az = Decimal(str(azimuth)) % Decimal(360)
        if az < 0:
            az += 360
        low = int(az)
        weight = az - Decimal(low)
        return float(
            Decimal(str(profile[low]["el"])) * (1 - weight)
            + Decimal(str(profile[(low + 1) % 360]["el"])) * weight
        )


def clearance(row, body, profile, rule):
    limb = {"any-disc": 1, "body-center": 0, "full-disc": -1}[rule]
    return (
        row[body + "El"]
        + limb * row[body + "AngularRadiusDeg"]
        - horizon_at(profile, row[body + "Az"])
    )


def model_comparison(dataset, oracle, profile, rule, criteria):
    from lunarwindow.ephemeris.models import TimeRange
    from lunarwindow.visibility import calculate_visibility

    period = TimeRange(
        dataset["provenance"]["startUtc"],
        dataset["provenance"]["endUtc"],
        dataset["provenance"]["stepMinutes"],
    )
    result = calculate_visibility(dataset["series"], profile, period, rule=rule)
    expected = {body: [] for body in ("sun", "earth")}
    near = mismatches = 0
    minimum = float("inf")
    for reference, calculated in zip(oracle, result.series):
        for body, actual in (
            ("sun", calculated.sunLit),
            ("earth", calculated.earthVis),
        ):
            gap = clearance(reference, body, profile, rule)
            visible = gap >= 0 if rule == "full-disc" else gap > 0
            expected[body].append(visible)
            mismatches += int(visible != actual)
            minimum = min(minimum, abs(gap))
            az = reference[body + "Az"]
            # Include the entire piecewise-linear azimuth uncertainty interval,
            # including its integer knots and the 359/0 seam.
            tolerance = criteria["pointingToleranceDeg"]
            probes = [az - tolerance, az, az + tolerance]
            probes.extend(
                range(math.ceil(az - tolerance), math.floor(az + tolerance) + 1)
            )
            h = horizon_at(profile, az)
            uncertainty = (
                max(abs(horizon_at(profile, value) - h) for value in probes) + tolerance
            )
            if rule != "body-center":
                uncertainty += criteria["angularRadiusToleranceDeg"]
            near += int(abs(gap) <= uncertainty)
    hours = period.step_minutes / 60
    totals = {
        "sunlitHrs": sum(expected["sun"]) * hours,
        "earthVisibleHrs": sum(expected["earth"]) * hours,
        "bothHrs": sum(a and b for a, b in zip(expected["sun"], expected["earth"]))
        * hours,
    }
    metrics_match = all(
        math.isclose(getattr(result.metrics, key), value, abs_tol=1e-9, rel_tol=0)
        for key, value in totals.items()
    )
    states = {
        row.t: {"sun": row.sunLit, "earth": row.earthVis} for row in result.series
    }
    return {
        "status": "pass-model-consistency"
        if mismatches == 0 and metrics_match
        else "fail",
        "visibilityRule": rule,
        "sampleBodyComparisons": 2 * len(oracle),
        "flagMismatches": mismatches,
        "totalsMatch": metrics_match,
        "referenceTotalsHrs": totals,
        "nearScreeningEnvelopeCount": near,
        "minimumAbsoluteClearanceDeg": minimum,
        "scope": "SPICE pointing plus a shared fixed horizon and disc model; this does not independently establish that terrain horizon or physical visibility.",
    }, states


def observation_requests(dataset, profile, mask):
    candidates = []
    for body in ("sun", "earth"):
        for visible in (True, False):
            eligible = [
                row
                for row in dataset["series"]
                if (clearance(row, body, profile, "any-disc") > 0) == visible
                and abs(clearance(row, body, profile, "any-disc")) >= 0.05
            ]
            if not eligible:
                continue
            row = min(
                eligible,
                key=lambda item: abs(clearance(item, body, profile, "any-disc")),
            )
            candidates.append(
                {
                    "caseId": f"site01-{body}-{'visible' if visible else 'blocked'}",
                    "siteId": dataset["siteId"],
                    "timestampUtc": row["t"],
                    "body": body,
                    "modelPredictedVisible": visible,
                    "modelClearanceDeg": clearance(row, body, profile, "any-disc"),
                    "observer": mask.observer.model_dump(exclude={"coordinateSource"}),
                    "visibilityRule": "any-disc",
                    "referenceFrame": "MOON_ME_DE421",
                    "referenceRadiusKm": 1737.4,
                    "referenceMeasurement": None,
                    "status": "pending-independent-evidence",
                }
            )
    return {
        "schemaVersion": "lunarwindow.terrain-observation-request.v1",
        "maskArtifactSha256": MASK_SHA256,
        "warning": "These UTCs and states select candidate checks using the model; they are not external measurements or ground truth. Do not copy model predictions into reference observations.",
        "cases": candidates,
    }


def validate(reference=REFERENCE, reference_hash=REFERENCE_HASH, terrain_evidence=None):
    from lunarwindow.reference import load_reference_dataset
    from lunarwindow.terrain.loader import load_terrain_mask

    config, pinned = read_inputs()
    expected_hash = reference_hash.read_text(encoding="utf-8").strip()
    if (
        len(expected_hash) != 64
        or any(char not in "0123456789abcdef" for char in expected_hash)
        or sha256(reference) != expected_hash
    ):
        raise ValueError("SPICE reference evidence differs from its reviewed checksum.")
    evidence = json.loads(reference.read_text(encoding="utf-8"))
    if (
        evidence["schemaVersion"] != "lunarwindow.surface-spice-reference.v1"
        or evidence["inputsSha256"] != sha256(INPUTS)
        or evidence["conventions"] != config["conventions"]
        or evidence["kernels"] != config["kernels"]
        or evidence["generator"]["version"] != VERSION
        or evidence["generator"]["scriptSha256"]
        != sha256(ROOT / "scripts/build_surface_spice_reference.py")
    ):
        raise ValueError(
            "SPICE evidence inputs, generator or conventions differ from the reviewed configuration."
        )
    if [item["siteId"] for item in evidence["sites"]] != [
        entry["siteId"] for entry, _ in pinned
    ]:
        raise ValueError(
            "SPICE evidence must cover every pinned surface observer once."
        )
    datasets = {}
    surface = []
    for (entry, _), oracle in zip(pinned, evidence["sites"]):
        dataset = load_reference_dataset((ROOT / entry["path"]).parent, entry["siteId"])
        if (
            oracle["archiveSha256"] != entry["sha256"]
            or oracle["observer"] != entry["observer"]
        ):
            raise ValueError("SPICE observer or archived source identity changed.")
        comparison = pointing_comparison(
            dataset["series"], oracle["series"], config["criteria"]
        )
        surface.append(
            {"siteId": entry["siteId"], "observer": entry["observer"], **comparison}
        )
        datasets[entry["siteId"]] = dataset
    mask = load_terrain_mask(MASK, expected_sha256=MASK_SHA256)
    models = []
    terrain_states = {}
    for oracle in evidence["sites"]:
        dataset = datasets[oracle["siteId"]]
        modes = [("geometric", [{"az": az, "el": 0.0} for az in range(360)])]
        if dataset["siteId"] == mask.siteId:
            modes.append(("terrain", [point.model_dump() for point in mask.horizon]))
        for mode, profile in modes:
            for rule in ("any-disc", "body-center", "full-disc"):
                comparison, states = model_comparison(
                    dataset, oracle["series"], profile, rule, config["criteria"]
                )
                models.append(
                    {"siteId": dataset["siteId"], "horizonMode": mode, **comparison}
                )
                if mode == "terrain" and rule == "any-disc":
                    terrain_states[dataset["siteId"]] = states
    terrain = {
        "status": "pending-independent-evidence",
        "coverageComplete": False,
        "comparisons": [],
        "reason": "No reviewed same-observer, same-UTC terrain visibility evidence is supplied. Elevated QuickMap camera geometry and mismatched-period PGDA averages cannot fill this gap.",
    }
    if terrain_evidence is not None:
        terrain = assess_terrain_evidence(
            json.loads(terrain_evidence.read_text(encoding="utf-8")),
            datasets,
            terrain_states,
            ROOT / "docs/validation",
        )
    failed = (
        any(item["failedComparisons"] for item in surface)
        or any(item["status"] == "fail" for item in models)
        or terrain["status"] == "fail"
    )
    complete = not failed and terrain["status"] == "pass-recorded-cases"
    report = {
        "schemaVersion": "lunarwindow.surface-science-report.v1",
        "status": "fail"
        if failed
        else "complete-recorded-checks"
        if complete
        else "partial-pending-terrain-evidence",
        "independentTerrainValidationComplete": complete,
        "referenceSha256": sha256(reference),
        "inputsSha256": sha256(INPUTS),
        "criteria": config["criteria"],
        "surfacePointing": surface,
        "modelConsistency": models,
        "externalTerrainEvidence": terrain,
        "limitations": [
            "CSPICE and Horizons share JPL ephemeris foundations; agreement is cross-tool consistency, not independent observational truth.",
            "SPICE uses DE440s and CN+S without relativistic light deflection; Horizons archives use DE441 source positions and apparent airless angles. Screening tolerances are engineering envelopes, not accuracy estimates.",
            "Surface cases retain DEM ground plus 0 m mast; these checks do not validate a different antenna height or custom-coordinate coverage.",
            "Model checks use the same reviewed terrain mask and do not independently validate its skyline. The production frame-approximation acceptance policy is unchanged.",
            "Hourly samples and sample-and-hold metrics do not validate sub-hour sunrise, shadow or Earthset times. Near-threshold states remain sensitive to model differences.",
        ],
    }
    return report, observation_requests(
        datasets[mask.siteId], [point.model_dump() for point in mask.horizon], mask
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--reference-sha256", type=Path, default=REFERENCE_HASH)
    parser.add_argument("--terrain-evidence", type=Path)
    parser.add_argument("--require-terrain-evidence", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requests-output", type=Path)
    args = parser.parse_args(argv)
    protected = {
        INPUTS.resolve(),
        args.reference.resolve(),
        args.reference_sha256.resolve(),
        MASK.resolve(),
        *(
            (ROOT / item["path"]).resolve()
            for item in json.loads(INPUTS.read_text())["datasets"]
        ),
    }
    if args.terrain_evidence:
        protected.add(args.terrain_evidence.resolve())
    outputs = [args.output] + ([args.requests_output] if args.requests_output else [])
    if (
        any(path.resolve() in protected for path in outputs)
        or len({path.resolve() for path in outputs}) != len(outputs)
        or any(
            path.resolve().is_relative_to(ROOT / "data/reference")
            or path.resolve().is_relative_to(ROOT / "docs/validation/evidence")
            for path in outputs
        )
    ):
        parser.error("Reports must not overwrite evidence/inputs or each other.")
    try:
        report, requests = validate(
            args.reference, args.reference_sha256, args.terrain_evidence
        )
        if args.requests_output:
            args.requests_output.parent.mkdir(parents=True, exist_ok=True)
            args.requests_output.write_text(
                json.dumps(requests, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {
            "schemaVersion": "lunarwindow.surface-science-report.v1",
            "status": "fail",
            "independentTerrainValidationComplete": False,
            "error": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("status", "independentTerrainValidationComplete")
            }
        )
    )
    if report["status"] == "fail":
        print(report.get("error", "Scientific comparison failed."), file=sys.stderr)
        return 1
    return (
        2
        if args.require_terrain_evidence
        and not report["independentTerrainValidationComplete"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
