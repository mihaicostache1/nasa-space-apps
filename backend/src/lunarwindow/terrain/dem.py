"""Polar stereographic height grids: in-memory patches plus checked LOLA GeoTIFF access.

`Grid` needs only numpy, so tests and the horizon algorithm run without GDAL. `DemSource`
uses Rasterio (the `gis` extra) to read bounded windows from the large NASA files.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .products import PRODUCTS, REFERENCE_RADIUS_M


@dataclass(frozen=True)
class Grid:
    """Heights in metres on a regular grid; NaN marks missing data.

    `left`/`top` are the outer edges of the first column/row; pixel centres sit half a
    pixel inside them (GDAL "Area" convention, as in every LOLA GeoTIFF).
    """

    data: np.ndarray
    left: float
    top: float
    resolution_m: float
    source: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.data.ndim != 2 or min(self.data.shape) < 2:
            raise ValueError("A grid needs at least 2 x 2 pixels.")
        if not self.resolution_m > 0:
            raise ValueError("Grid resolution must be positive.")

    @property
    def right(self) -> float:
        return self.left + self.data.shape[1] * self.resolution_m

    @property
    def bottom(self) -> float:
        return self.top - self.data.shape[0] * self.resolution_m

    def sample(self, x, y) -> np.ndarray:
        """Bilinear heights at projected coordinates; NaN outside or next to missing data."""
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        col = (x - self.left) / self.resolution_m - 0.5
        row = (self.top - y) / self.resolution_m - 0.5
        c0, r0 = np.floor(col), np.floor(row)
        rows, cols = self.data.shape
        inside = (c0 >= 0) & (r0 >= 0) & (c0 + 1 < cols) & (r0 + 1 < rows)
        c0 = np.where(inside, c0, 0).astype(np.intp)
        r0 = np.where(inside, r0, 0).astype(np.intp)
        fc, fr = col - c0, row - r0
        data = self.data
        total = np.zeros(np.broadcast(x, y).shape)
        for dr, dc, weight in (
            (0, 0, (1 - fr) * (1 - fc)),
            (0, 1, (1 - fr) * fc),
            (1, 0, fr * (1 - fc)),
            (1, 1, fr * fc),
        ):
            # A missing neighbour only matters if it actually contributes to the value.
            total = total + np.where(weight > 0, data[r0 + dr, c0 + dc] * weight, 0.0)
        return np.where(inside, total, np.nan)


def check_crs(crs, path) -> None:
    """Reject anything other than the documented LOLA south polar stereographic sphere."""
    params = crs.to_dict()
    radius = params.get("R", params.get("a"))
    if (
        params.get("proj") != "stere"
        or params.get("lat_0") != -90
        or params.get("lat_ts", -90) != -90
        or params.get("lon_0", 0) != 0
        or params.get("x_0", 0) != 0
        or params.get("y_0", 0) != 0
        or radius != REFERENCE_RADIUS_M
        or params.get("b", radius) != radius
    ):
        raise ValueError(f"{path}: unexpected projection {crs.to_proj4()}.")


class DemSource:
    """A lazily opened LOLA GeoTIFF with verified projection and recorded provenance."""

    def __init__(self, path: Path, provenance: dict | None = None):
        import rasterio  # Imported here so numpy-only users never need GDAL.

        self.path = Path(path)
        self._dataset = rasterio.open(self.path)
        try:
            self._configure(provenance)
        except BaseException:
            self._dataset.close()
            raise

    def _configure(self, provenance: dict | None) -> None:
        from .download import read_provenance, sidecar_path

        check_crs(self._dataset.crs, self.path)
        transform = self._dataset.transform
        if transform.b or transform.d or transform.a != -transform.e:
            raise ValueError(f"{self.path}: grid must be north-up with square pixels.")
        self.resolution_m = transform.a
        self.left, self.top = transform.c, transform.f
        if provenance is None:
            provenance = (
                read_provenance(self.path)
                if sidecar_path(self.path).exists()
                else {"productId": self.path.stem, "sourceUrl": None, "sha256": None}
            )
        product = PRODUCTS.get(provenance.get("productId", ""))
        self.provenance = {
            "productId": provenance.get("productId"),
            "role": provenance.get("role", product.role if product else None),
            "sourceUrl": provenance.get("sourceUrl"),
            "sha256": provenance.get("sha256"),
            "resolutionM": self.resolution_m,
        }

    def close(self) -> None:
        self._dataset.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def contains(self, x: float, y: float) -> bool:
        bounds = self._dataset.bounds
        return bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top

    def read_patch(self, x: float, y: float, radius_m: float) -> Grid | None:
        """Read the square window of half-width `radius_m` around (x, y), clipped to the file."""
        from rasterio.windows import Window

        res = self.resolution_m
        col0 = max(0, math.floor((x - radius_m - self.left) / res))
        col1 = min(self._dataset.width, math.ceil((x + radius_m - self.left) / res))
        row0 = max(0, math.floor((self.top - (y + radius_m)) / res))
        row1 = min(self._dataset.height, math.ceil((self.top - (y - radius_m)) / res))
        if col1 - col0 < 2 or row1 - row0 < 2:
            return None
        window = Window(col0, row0, col1 - col0, row1 - row0)
        data = self._dataset.read(1, window=window, masked=True).astype(np.float64)
        data = np.ma.filled(data, np.nan)
        scale, offset = self._dataset.scales[0], self._dataset.offsets[0]
        if (scale, offset) != (1.0, 0.0):
            data = data * scale + offset
        return Grid(
            data,
            left=self.left + col0 * res,
            top=self.top - row0 * res,
            resolution_m=res,
            source=self.provenance,
        )
