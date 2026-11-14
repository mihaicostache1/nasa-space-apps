"""Sanity-check a horizon run against NASA PGDA long-term visibility maps.

For each polar `lola-dem` site this fetches (or replays from cache) a year of Sun/Earth angles
from JPL Horizons, joins them with the site's terrain horizon via the backend visibility
engine (any-disc rule, matching the PGDA definition), and compares the sunlit/Earth-visible
percentages with the AVGVISIB maps (18.6-year hourly averages, surface observer). It also
joins the committed 30-day reference ephemeris with the matching horizons, as an offline
end-to-end check of the P1 → P2 → P3 path.

Ephemeris requests use the observer altitude rounded to --altitude-step-km (default 1 km) so
the cache survives DEM refinements; 1 km of topocentric parallax moves the Sun or Earth by
less than 0.00015°. One year is a proxy for the 18.6-year average and the maps use an older, coarser DEM, so
expect agreement within roughly 10 percentage points, not exact equality.

Needs the gis extra and the downloaded validation maps (`lunarwindow-terrain download --all`).
"""

import argparse
import json
import math
from contextlib import ExitStack
from pathlib import Path

from lunarwindow.ephemeris import HorizonsClient, Site, TimeRange
from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.terrain import load_horizons
from lunarwindow.terrain.dem import DemSource
from lunarwindow.terrain.geometry import latlon_to_stereographic
from lunarwindow.terrain.products import PRODUCTS
from lunarwindow.visibility import calculate_visibility

ROOT = Path(__file__).resolve().parents[1]
FLAT = [{"az": az, "el": 0.0} for az in range(360)]
MAPS = {"sun": "AVGVISIB_75S_120M_201608", "earth": "AVGVISIB_75S_120M_201608_EARTH"}


def metrics(series, horizon, period):
    rows = [
        {
            key: row[key]
            for key in (
                "t",
                "sunAz",
                "sunEl",
                "earthAz",
                "earthEl",
                "sunAngularRadiusDeg",
                "earthAngularRadiusDeg",
            )
        }
        for row in series
    ]
    result = calculate_visibility(rows, horizon, period, rule="any-disc").metrics
    return {
        "pctSun": round(result.pctSun, 1),
        "pctEarth": round(result.pctEarth, 1),
        "pctBoth": round(result.pctBoth, 1),
        "longestDarkHrs": result.longestDarkHrs,
    }


def map_value(source: DemSource, lat: float, lon: float):
    x, y = (float(v) for v in latlon_to_stereographic(lat, lon))
    if not source.contains(x, y):
        return None
    patch = source.read_patch(x, y, 500)
    value = float(patch.sample(x, y)) if patch is not None else float("nan")
    return None if math.isnan(value) else round(value * 100, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Horizon run directory")
    parser.add_argument("--start", default="2026-11-14T00:00:00Z")
    parser.add_argument("--end", default="2027-11-14T00:00:00Z")
    parser.add_argument("--step-minutes", type=int, default=360)
    parser.add_argument("--altitude-step-km", type=float, default=1.0)
    parser.add_argument("--dem-dir", type=Path, default=ROOT / "data/raw/lola")
    parser.add_argument("--cache", type=Path, default=ROOT / "data/raw/horizons")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/validation/terrain-results.json"
    )
    args = parser.parse_args()

    profiles = load_horizons(args.run)
    period = TimeRange(args.start, args.end, args.step_minutes)
    client = HorizonsClient(args.cache)
    results = {
        "run": args.run.name,
        "period": {
            "startUtc": args.start,
            "endUtc": args.end,
            "stepMinutes": args.step_minutes,
        },
        "rule": "any-disc",
        "sites": [],
        "reference30d": [],
    }

    with ExitStack() as stack:
        maps = {
            key: stack.enter_context(DemSource(args.dem_dir / PRODUCTS[pid].filename))
            for key, pid in MAPS.items()
        }
        for profile in profiles.values():
            if profile.terrainModel != "lola-dem":
                continue
            pgda_sun = map_value(maps["sun"], profile.lat, profile.lon)
            pgda_earth = map_value(maps["earth"], profile.lat, profile.lon)
            if pgda_sun is None and pgda_earth is None:
                print(f"Skipping {profile.siteId}: outside the PGDA comparison maps.")
                continue
            step = args.altitude_step_km
            altitude = round(round(profile.observerAltitudeKm / step) * step, 6)
            site = Site(
                profile.siteId,
                profile.name,
                profile.lat,
                profile.lon,
                altitude,
                profile.coordinateSource,
            )
            print(f"Ephemeris for {site.site_id} ({period.sample_count} samples)...")
            dataset = validate_dataset(client.evaluate(site, period))
            horizon = [point.model_dump() for point in profile.horizon]
            terrain = metrics(dataset["series"], horizon, period)
            bare = metrics(dataset["series"], FLAT, period)
            results["sites"].append(
                {
                    "siteId": profile.siteId,
                    "terrain": terrain,
                    "noTerrain": bare,
                    "pgdaAvgSunPct": pgda_sun,
                    "pgdaAvgEarthPct": pgda_earth,
                    "sunDiffPct": None
                    if pgda_sun is None
                    else round(terrain["pctSun"] - pgda_sun, 1),
                    "earthDiffPct": None
                    if pgda_earth is None
                    else round(terrain["pctEarth"] - pgda_earth, 1),
                }
            )

    reference = ROOT / "data/reference/validation-30d"
    manifest = json.loads((reference / "manifest.json").read_text())
    ref_period = TimeRange(
        manifest["period"]["startUtc"],
        manifest["period"]["endUtc"],
        manifest["period"]["stepMinutes"],
    )
    for item in manifest["datasets"]:
        profile = profiles.get(item["siteId"])
        if profile is None:
            continue
        dataset = validate_dataset(json.loads((reference / item["json"]).read_text()))
        horizon = [point.model_dump() for point in profile.horizon]
        results["reference30d"].append(
            {
                "siteId": item["siteId"],
                "terrain": metrics(dataset["series"], horizon, ref_period),
                "noTerrain": metrics(dataset["series"], FLAT, ref_period),
            }
        )

    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(
        "\n| Site | Sun % (terrain) | Sun % (no terrain) | PGDA avg Sun % | Earth % (terrain) | PGDA avg Earth % |"
    )
    print("| --- | --: | --: | --: | --: | --: |")
    for row in results["sites"]:
        print(
            f"| {row['siteId']} | {row['terrain']['pctSun']} | {row['noTerrain']['pctSun']} | "
            f"{row['pgdaAvgSunPct']} | {row['terrain']['pctEarth']} | {row['pgdaAvgEarthPct']} |"
        )
    print("\n30-day reference bundle (2026-11-14 to 2026-12-14, hourly):")
    for row in results["reference30d"]:
        print(
            f"  {row['siteId']}: terrain {row['terrain']}, no terrain {row['noTerrain']}"
        )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
