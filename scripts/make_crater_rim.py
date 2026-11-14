"""Write a crater-rim annulus as GeoJSON for `lunarwindow-terrain regions`.

The band spans [inner, outer] × the crater radius around the IAU Gazetteer centre, so the
region rule (best long-term sunlight among gently sloping pixels) picks a rim point instead
of a hand-placed one. Example (Shackleton, IAU Gazetteer feature 5450):

    python scripts/make_crater_rim.py --name "Shackleton rim" --lat -89.67 --lon 129.78 \
        --diameter-km 20.92 --output data/regions/shackleton-rim.geojson
"""

import argparse
import json
from pathlib import Path

import numpy as np
from lunarwindow.terrain.geometry import ray_unit_vectors


def ring(lat, lon, radius_m, count=144):
    azimuths = np.linspace(0, 360, count, endpoint=False)
    points = ray_unit_vectors(lat, lon, azimuths, np.array([radius_m]))[:, 0, :]
    lats = np.degrees(np.arcsin(points[:, 2]))
    lons = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
    coords = [[round(float(a), 7), round(float(b), 7)] for a, b in zip(lons, lats)]
    return coords + [coords[0]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--diameter-km", type=float, required=True)
    parser.add_argument(
        "--inner", type=float, default=0.85, help="Inner radius / crater radius"
    )
    parser.add_argument(
        "--outer", type=float, default=1.25, help="Outer radius / crater radius"
    )
    parser.add_argument("--source", default="IAU Gazetteer of Planetary Nomenclature")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    radius = args.diameter_km * 500
    feature = {
        "type": "Feature",
        "properties": {
            "name": args.name,
            "centerLat": args.lat,
            "centerLon": args.lon,
            "diameterKm": args.diameter_km,
            "band": [args.inner, args.outer],
            "source": args.source,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                ring(args.lat, args.lon, radius * args.outer),
                ring(args.lat, args.lon, radius * args.inner)[::-1],
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]}, indent=1)
        + "\n"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
