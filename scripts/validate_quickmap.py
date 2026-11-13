"""Replay three captured QuickMap geometry-panel comparisons against archived Horizons.

Use --refresh only to retrieve new Horizons results; default replay is offline.
QuickMap angles are for the CAMERA, not the surface or an illumination layer.
"""

import argparse
import csv
import json
import math
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lunarwindow.ephemeris import HorizonsClient, Site, TimeRange
from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.ephemeris.models import iso_utc, parse_utc

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    cases, rows = [], []
    evidence = ROOT / "docs/validation/evidence"
    for number in range(1, 4):
        case_id = f"quickmap-case-{number:02}"
        reference = json.loads(
            (evidence / f"{case_id}.json").read_text(encoding="utf-8")
        )
        camera = parse_qs(urlparse(reference["url"]).query)["camera"][0]
        x, y, z = map(float, camera.split(",")[:3])
        radius = math.sqrt(x * x + y * y + z * z)
        # QuickMap exports Cartesian camera position in metres. The lunar
        # reference sphere is 1737.4 km, consistent with the inspected UI height.
        lat, lon = math.degrees(math.asin(z / radius)), math.degrees(math.atan2(y, x))
        altitude = radius / 1000 - 1737.4
        site = Site(
            case_id, "QuickMap camera observer", lat, lon, altitude, reference["url"]
        )
        period = TimeRange(
            reference["timestampUtc"],
            iso_utc(parse_utc(reference["timestampUtc"]) + timedelta(minutes=1)),
            1,
        )
        path = evidence / f"{case_id}-horizons.json"
        if not path.exists() and not args.refresh:
            raise FileNotFoundError(
                f"Missing archive {path}; use --refresh to retrieve it explicitly."
            )
        if args.refresh:
            dataset = HorizonsClient(
                ROOT / "data/reference/quickmap-horizons", refresh=args.refresh
            ).evaluate(site, period)
            path.write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")
        dataset = validate_dataset(json.loads(path.read_text(encoding="utf-8")))
        if any(
            abs(dataset[key] - value) > 1e-10
            for key, value in [("lat", lat), ("lon", lon), ("altitudeKm", altitude)]
        ):
            raise ValueError(
                "Archived Horizons observer differs from the captured camera."
            )
        actual = dataset["series"][0]
        if actual["t"] != reference["timestampUtc"]:
            raise ValueError("Comparison times differ.")
        # Half of the displayed 0.01-degree step, plus 1e-6 deg for rounding
        # the Cartesian coordinates in the share URL. This is a display-rounding
        # consistency criterion, not a physical instrument/ephemeris error bound.
        tolerance = reference["angularDisplayResolutionDeg"] / 2 + 1e-6
        differences = {}
        for key in ("sunAz", "sunEl", "earthAz", "earthEl"):
            difference = actual[key] - reference[key]
            if key.endswith("Az"):
                difference = (difference + 180) % 360 - 180
            differences[key] = difference
            status = "pass" if abs(difference) <= tolerance else "fail"
            rows.append(
                [
                    case_id,
                    status,
                    case_id,
                    lat,
                    lon,
                    altitude,
                    actual["t"],
                    reference["url"],
                    "3D Time and Key Geometry Info",
                    "1737.4 km lunar sphere; camera position from URL",
                    "none: pointing comparison",
                    "body center",
                    key,
                    reference[key],
                    actual[key],
                    difference,
                    tolerance,
                    f"evidence/{case_id}.png",
                    "Cross-tool display consistency only; camera is elevated above terrain.",
                ]
            )
        cases.append(
            {
                "caseId": case_id,
                "status": "pass-display-precision"
                if all(abs(v) <= tolerance for v in differences.values())
                else "fail",
                "observer": {
                    "lat": lat,
                    "lon": lon,
                    "altitudeKm": altitude,
                    "cameraCartesianMetres": [x, y, z],
                },
                "timeUtc": actual["t"],
                "referenceUrl": reference["url"],
                "reference": {k: reference[k] for k in differences},
                "horizons": {k: actual[k] for k in differences},
                "differencesDeg": differences,
                "toleranceDeg": tolerance,
                "evidence": f"evidence/{case_id}.png",
            }
        )
    result = {
        "scope": "Sun/Earth center pointing at three elevated QuickMap camera observers, at one UTC timestamp; no terrain-visibility or mission-site certification",
        "criterion": "within half the 0.01-degree UI display step plus 1e-6 degree coordinate-rounding allowance",
        "status": "pass-display-precision"
        if all(c["status"] == "pass-display-precision" for c in cases)
        else "fail",
        "cases": cases,
    }
    (ROOT / "docs/validation/quickmap-results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    with (ROOT / "docs/validation/quickmap-cases.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "case_id",
                "status",
                "site_id",
                "lat_deg",
                "lon_east_deg",
                "observer_altitude_km",
                "time_utc",
                "quickmap_url",
                "layer_or_tool",
                "reference_frame",
                "terrain_model",
                "body_disc_rule",
                "quantity",
                "reference_value",
                "calculated_value",
                "wrapped_difference_deg",
                "tolerance",
                "evidence_path",
                "reviewer_notes",
            ]
        )
        writer.writerows(rows)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass-display-precision" else 1


if __name__ == "__main__":
    raise SystemExit(main())
