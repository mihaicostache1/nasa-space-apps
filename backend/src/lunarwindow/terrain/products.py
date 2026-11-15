"""NASA source rasters used by the terrain pipeline, with their documented conventions.

All products are south polar stereographic grids on the 1737.4 km reference sphere in the
DE421 MOON_ME frame. `dem.DemSource` re-checks the projection of every opened file, so a
changed upstream product fails instead of silently producing a wrong horizon.
"""

from dataclasses import dataclass
from typing import Literal

REFERENCE_RADIUS_M = 1_737_400.0
LOLA_20MPP_PAGE = "https://pgda.gsfc.nasa.gov/products/90"
ILLUMINATION_PAGE = "https://pgda.gsfc.nasa.gov/products/69"

LOLA_5MPP_PAGE = "https://pgda.gsfc.nasa.gov/products/78"

Role = Literal["site-tile", "near-field", "far-field", "validation-sun", "validation-earth"]


@dataclass(frozen=True)
class Product:
    product_id: str
    url: str
    source_page: str
    role: Role
    resolution_m: float
    half_width_m: float
    """Extent: half the side of the (square) grid. Polar products are centred on the pole."""
    size_bytes: int
    description: str

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[1]


PRODUCTS: dict[str, Product] = {
    product.product_id: product
    for product in (
        Product(
            "Site01_final_adj_5mpp_surf",
            "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site01/Site01_final_adj_5mpp_surf.tif",
            LOLA_5MPP_PAGE,
            "site-tile",
            5.0,
            8_000.0,
            40_980_810,
            "LOLA 5 m/px Site01 (connecting ridge) tile, 16 x 16 km; source of the Site01 "
            "reference point and its archived ephemeris altitude",
        ),
        Product(
            "Site04_final_adj_5mpp_surf",
            "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site04/Site04_final_adj_5mpp_surf.tif",
            LOLA_5MPP_PAGE,
            "site-tile",
            5.0,
            8_000.0,
            40_980_806,
            "LOLA 5 m/px Site04 (Shackleton inner wall) tile, 16 x 16 km; source of the Site04 "
            "reference point and its archived ephemeris altitude",
        ),
        Product(
            "Site23_final_adj_5mpp_surf",
            "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site23/Site23_final_adj_5mpp_surf.tif",
            LOLA_5MPP_PAGE,
            "site-tile",
            5.0,
            10_500.0,
            70_586_804,
            "LOLA 5 m/px Site23 (Malapert massif) tile, 21 x 21 km; source of the Site23 "
            "reference point and its archived ephemeris altitude",
        ),
        Product(
            "LDEM_80S_20MPP_ADJ",
            "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_20MPP_ADJ.TIF",
            LOLA_20MPP_PAGE,
            "near-field",
            20.0,
            304_000.0,
            2_696_082_051,
            "LOLA south pole DEM, 80-90°S, 20 m/px, heights in metres above 1737.4 km",
        ),
        Product(
            "LDEM_60S_120MPP_ADJ",
            "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_60S_120MPP_ADJ.TIF",
            LOLA_20MPP_PAGE,
            "far-field",
            120.0,
            931_200.0,
            821_504_895,
            "LOLA south polar DEM, 60-90°S, 120 m/px, heights in metres above 1737.4 km",
        ),
        Product(
            "AVGVISIB_75S_120M_201608",
            "https://pgda.gsfc.nasa.gov/data/MoonIllumination/AVGVISIB_75S_120M_201608.TIF",
            ILLUMINATION_PAGE,
            "validation-sun",
            120.0,
            457_440.0,
            83_052_039,
            "Long-term average solar visibility fraction (LOLA GDR, 2016 release)",
        ),
        Product(
            "AVGVISIB_75S_120M_201608_EARTH",
            "https://pgda.gsfc.nasa.gov/data/MoonIllumination/AVGVISIB_75S_120M_201608_EARTH.TIF",
            ILLUMINATION_PAGE,
            "validation-earth",
            120.0,
            457_440.0,
            43_148_153,
            "Long-term average Earth visibility fraction (LOLA GDR, 2016 release)",
        ),
    )
}

NEAR_FIELD = "LDEM_80S_20MPP_ADJ"
FAR_FIELD = "LDEM_60S_120MPP_ADJ"
