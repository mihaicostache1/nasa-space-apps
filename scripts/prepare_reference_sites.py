"""Reproduce three NASA LOLA DEM center-pixel reference points (not landing targets).

Install backend[gis] first. Downloads stay under ignored data/raw/lola.
"""

import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[1]
SITES = {
    "Site01": "Connecting ridge",
    "Site04": "Shackleton rim",
    "Site23": "Malapert massif",
}


def main():
    catalog, sources = [], []
    for code, label in SITES.items():
        url = f"https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/{code}/{code}_final_adj_5mpp_surf.tif"
        path = ROOT / "data/raw/lola" / f"{code}.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            print(f"Downloading {code}...", file=sys.stderr)
            temporary = path.with_suffix(".part")
            with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            temporary.replace(path)
        with rasterio.open(path) as dem:
            # Product 78 specifies DE421 MOON_ME, south polar stereographic,
            # 1737.4 km sphere. Reject a changed projection instead of guessing.
            projection = dem.crs.to_dict()
            if projection.get("proj") != "stere" or projection.get("lat_0") != -90:
                raise ValueError(f"Unexpected projection: {dem.crs}")
            radius = projection.get("R", projection.get("a"))
            if radius != 1737400 or dem.res != (5, 5):
                raise ValueError("Unexpected reference radius or pixel size.")
            row, col = dem.height // 2, dem.width // 2
            x, y = dem.xy(row, col)
            # Inverse stereographic for this explicitly checked spherical CRS.
            lat = -90 + math.degrees(2 * math.atan(math.hypot(x, y) / (2 * radius)))
            lon = math.degrees(math.atan2(x, y))
            elevation = float(
                dem.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
            )
            if not math.isfinite(elevation):
                raise ValueError(f"No valid center height for {code}.")
            site_id = "lola-" + code.lower() + "-reference"
            catalog.append(
                {
                    "id": site_id,
                    "name": f"{label} DEM reference point",
                    "lat": lat,
                    "lon": lon,
                    "altitudeKm": elevation / 1000,
                    "coordinateSource": f"{url}; center pixel row={row}, col={col}; DE421 MOON_ME, 1737.4 km sphere; sampled surface height, 0 m mast; reference point, not a selected landing target.",
                }
            )
            sources.append(
                {
                    "siteId": site_id,
                    "sourceUrl": url,
                    "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "localFileMtimeUtc": datetime.fromtimestamp(
                        path.stat().st_mtime, UTC
                    ).isoformat(),
                    "crsWkt": dem.crs.to_wkt(),
                    "width": dem.width,
                    "height": dem.height,
                    "transform": list(dem.transform),
                    "row": row,
                    "col": col,
                    "pixelCenterXMetres": x,
                    "pixelCenterYMetres": y,
                    "surfaceElevationMetres": elevation,
                    "mastHeightMetres": 0,
                    "referenceRadiusMetres": radius,
                }
            )
    output = ROOT / "data/reference"
    output.mkdir(parents=True, exist_ok=True)
    (output / "sites.nasa.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "sourcePage": "https://pgda.gsfc.nasa.gov/products/78",
        "sourceReadme": "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/README",
        "points": sources,
    }
    (output / "site-provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(output / "sites.nasa.json")


if __name__ == "__main__":
    main()
