"""Curated site catalogs: sourced coordinates plus the terrain model each site should use."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..ephemeris.models import Site, finite_number
from .horizon import SiteSpec

Kind = Literal["dem-reference", "landing-target", "historic-landing", "candidate-region"]
KINDS = {"dem-reference", "landing-target", "historic-landing", "candidate-region"}


@dataclass(frozen=True)
class CatalogSite:
    site_id: str
    name: str
    kind: Kind
    lat: float
    lon: float
    terrain: Literal["lola-dem", "none"]
    coordinate_source: str
    published_elevation_m: float | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        # Reuse the ephemeris contract's checks for IDs, ranges, and provenance.
        Site(self.site_id, self.name, self.lat, self.lon, 0.0, self.coordinate_source)
        if self.kind not in KINDS:
            raise ValueError(f"{self.site_id}: kind must be one of {sorted(KINDS)}.")
        if self.terrain not in {"lola-dem", "none"}:
            raise ValueError(f"{self.site_id}: terrain must be 'lola-dem' or 'none'.")
        if self.published_elevation_m is not None:
            finite_number(self.published_elevation_m, "publishedElevationM")

    @property
    def spec(self) -> SiteSpec:
        return SiteSpec(self.site_id, self.name, self.lat, self.lon, self.coordinate_source)

    @classmethod
    def from_json(cls, row: dict) -> "CatalogSite":
        allowed = {
            "id",
            "name",
            "kind",
            "lat",
            "lon",
            "terrain",
            "coordinateSource",
            "publishedElevationM",
            "notes",
            "region",
        }
        unknown = set(row) - allowed
        if unknown:
            raise ValueError(f"{row.get('id')}: unknown catalog fields {sorted(unknown)}.")
        return cls(
            site_id=row["id"],
            name=row["name"],
            kind=row["kind"],
            lat=row["lat"],
            lon=row["lon"],
            terrain=row.get("terrain", "lola-dem"),
            coordinate_source=row["coordinateSource"],
            published_elevation_m=row.get("publishedElevationM"),
            notes=row.get("notes"),
        )


def load_catalog(paths: list[Path]) -> list[CatalogSite]:
    sites = []
    for path in paths:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{path}: catalog must be a nonempty JSON array.")
        sites.extend(CatalogSite.from_json(row) for row in rows)
    ids = [site.site_id for site in sites]
    duplicates = sorted({site_id for site_id in ids if ids.count(site_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate site IDs across catalogs: {duplicates}.")
    return sites
