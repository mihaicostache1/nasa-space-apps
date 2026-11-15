"""Explicit offline SPICE oracle generation; no LunarWindow runtime imports.

Kernel bytes and source observer/time grids must match the reviewed input pins.
Never fetches kernels, calls Horizons, or alters the source archives.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "docs/validation/surface-science-inputs.json"
VERSION = "lunarwindow.surface-spice-generator.v1"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_inputs(path=INPUTS):
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["schemaVersion"] != "lunarwindow.surface-science-inputs.v1":
        raise ValueError("Unsupported scientific input contract.")
    for key in ("pointingToleranceDeg", "angularRadiusToleranceDeg"):
        value = config["criteria"][key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(
                "Scientific screening criteria must be finite positive numbers."
            )
    conventions = config["conventions"]
    if any(
        conventions[key] != value
        for key, value in {
            "referenceFrame": "MOON_ME_DE440_ME421",
            "referenceRadiusKm": 1737.4,
            "flattening": 0,
            "aberrationCorrection": "CN+S",
            "azimuthConvention": "clockwise-from-local-north",
            "elevationReference": "local-horizontal",
            "refraction": "none",
            "timeScale": "UTC",
            "mastHeightM": 0,
        }.items()
    ):
        raise ValueError("Unsupported surface comparison conventions.")
    provenance = ROOT / config["siteProvenance"]["path"]
    if sha256(provenance) != config["siteProvenance"]["sha256"]:
        raise ValueError("Source site provenance has changed.")
    points = {
        point["siteId"]: point for point in json.loads(provenance.read_text())["points"]
    }
    datasets = []
    for entry in config["datasets"]:
        source = ROOT / entry["path"]
        if sha256(source) != entry["sha256"]:
            raise ValueError(f"Source archive changed: {entry['siteId']}")
        dataset = json.loads(source.read_text(encoding="utf-8"))
        observer = entry["observer"]
        point = points[entry["siteId"]]
        radius = point["referenceRadiusMetres"]
        ground_lat = -90 + math.degrees(
            2
            * math.atan(
                math.hypot(point["pixelCenterXMetres"], point["pixelCenterYMetres"])
                / (2 * radius)
            )
        )
        ground_lon = math.degrees(
            math.atan2(point["pixelCenterXMetres"], point["pixelCenterYMetres"])
        )
        if (
            radius != 1737400
            or point["mastHeightMetres"] != 0
            or observer["surfaceElevationM"] != point["surfaceElevationMetres"]
            or not math.isclose(observer["lat"], ground_lat, abs_tol=1e-10, rel_tol=0)
            or not math.isclose(observer["lon"], ground_lon, abs_tol=1e-10, rel_tol=0)
        ):
            raise ValueError(
                "Observer is not the pinned DEM surface pixel plus zero mast."
            )
        if dataset["siteId"] != entry["siteId"] or any(
            dataset[key] != observer[key] for key in ("lat", "lon", "altitudeKm")
        ):
            raise ValueError(
                "Oracle observer differs from the pinned surface observer."
            )
        if observer["mastHeightM"] != 0 or not math.isclose(
            observer["surfaceElevationM"] / 1000,
            observer["altitudeKm"],
            abs_tol=1e-12,
            rel_tol=0,
        ):
            raise ValueError(
                "A surface case must use the pinned ground plus zero mast."
            )
        datasets.append((entry, dataset))
    return config, datasets


def build(kernel_directory, inputs=INPUTS):
    import spiceypy as spice

    config, datasets = read_inputs(inputs)
    if importlib.metadata.version("spiceypy") != "8.0.0":
        raise ValueError("Reference generation requires pinned spiceypy==8.0.0.")
    for kernel in config["kernels"]:
        path = kernel_directory / kernel["filename"]
        if (
            path.is_symlink()
            or path.stat().st_size != kernel["sizeBytes"]
            or sha256(path) != kernel["sha256"]
        ):
            raise ValueError(
                f"SPICE kernel differs from reviewed bytes: {kernel['filename']}"
            )
    conventions = config["conventions"]
    result = {
        "schemaVersion": "lunarwindow.surface-spice-reference.v1",
        "createdAtUtc": datetime.now(UTC).isoformat(),
        "inputsSha256": sha256(inputs),
        "generator": {
            "version": VERSION,
            "scriptSha256": sha256(Path(__file__)),
            "spiceypy": importlib.metadata.version("spiceypy"),
            "numpy": importlib.metadata.version("numpy"),
            "toolkit": spice.tkvrsn("TOOLKIT"),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "conventions": conventions,
        "kernels": config["kernels"],
        "independence": "Separate NAIF CSPICE azlcpo calculation using DE440s positions and binary lunar orientation. No Horizons API, LunarWindow parser, or LunarWindow geometry implementation is used. Both systems share JPL ephemeris foundations; this is cross-tool consistency, not independent observational truth.",
        "sites": [],
    }
    spice.kclear()
    try:
        for kernel in config["kernels"]:
            spice.furnsh(str(kernel_directory / kernel["filename"]))
        if (
            list(spice.bodvrd("MOON", "RADII", 3)[1])
            != [conventions["referenceRadiusKm"]] * 3
        ):
            raise ValueError(
                "Kernel Moon radii differ from the archived reference sphere."
            )
        for entry, dataset in datasets:
            position = spice.georec(
                math.radians(entry["observer"]["lon"]),
                math.radians(entry["observer"]["lat"]),
                entry["observer"]["altitudeKm"],
                conventions["referenceRadiusKm"],
                0,
            )
            series = []
            # Only UTCs and observer coordinates come from the source; none of
            # the archived pointing angles or radii are used in this calculation.
            for archived in dataset["series"]:
                row = {"t": archived["t"]}
                et = spice.str2et(row["t"])
                for body in ("sun", "earth"):
                    state, _ = spice.azlcpo(
                        "ELLIPSOID",
                        body.upper(),
                        et,
                        conventions["aberrationCorrection"],
                        False,
                        True,
                        position,
                        "MOON",
                        conventions["referenceFrame"],
                    )
                    row[body + "Az"] = math.degrees(state[1]) % 360
                    row[body + "El"] = math.degrees(state[2])
                    row[body + "AngularRadiusDeg"] = math.degrees(
                        math.asin(conventions["targetRadiiKm"][body] / state[0])
                    )
                series.append(row)
            result["sites"].append(
                {
                    "siteId": entry["siteId"],
                    "archiveSha256": entry["sha256"],
                    "observer": entry["observer"],
                    "series": series,
                }
            )
    finally:
        spice.kclear()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-dir", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Explicit candidate output; source archives are never rewritten.",
    )
    args = parser.parse_args(argv)
    result = build(args.kernel_dir, args.inputs)
    protected = {
        INPUTS.resolve(),
        args.inputs.resolve(),
        (
            ROOT / json.loads(args.inputs.read_text())["siteProvenance"]["path"]
        ).resolve(),
        *((args.kernel_dir / item["filename"]).resolve() for item in result["kernels"]),
        *(
            (ROOT / item["path"]).resolve()
            for item in json.loads(args.inputs.read_text())["datasets"]
        ),
    }
    if args.output.resolve() in protected:
        parser.error(
            "Output must not replace input archives or the input configuration."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256(args.output),
                "sites": len(result["sites"]),
                "samples": sum(len(site["series"]) for site in result["sites"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
