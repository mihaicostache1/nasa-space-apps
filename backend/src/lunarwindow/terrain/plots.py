"""Sanity-check figures for a horizon run (needs the `analysis` extra)."""

import math
from pathlib import Path

from .models import HorizonProfile


def write_overview(profiles: list[HorizonProfile], directory: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    columns = 3
    rows = math.ceil(len(profiles) / columns)
    figure, axes = plt.subplots(
        rows, columns, figsize=(5 * columns, 2.6 * rows), squeeze=False, sharex=True
    )
    for axis, profile in zip(axes.flat, profiles):
        if profile.rays is not None:
            step = profile.rays.stepDeg
            azimuths = [index * step for index in range(len(profile.rays.el))]
            axis.plot(azimuths, profile.rays.el, color="#4a5568", linewidth=0.6)
        degrees = [point.az for point in profile.horizon]
        axis.plot(degrees, [p.el for p in profile.horizon], color="#c05621", linewidth=1)
        for az in profile.quality.truncatedAzimuths if profile.rays is not None else []:
            axis.axvspan(az - 0.5, az + 0.5, color="#e53e3e", alpha=0.08, linewidth=0)
        axis.axhline(0, color="#a0aec0", linewidth=0.5)
        label = (
            "no terrain"
            if profile.terrainModel == "none"
            else (f"surface {profile.surfaceElevationM:.0f} m")
        )
        axis.set_title(
            f"{profile.name}\n{profile.lat:.3f}, {profile.lon:.3f} · {label}", fontsize=8
        )
        axis.tick_params(labelsize=7)
        axis.set_xlim(0, 360)
        axis.set_xticks(range(0, 361, 90))
    for axis in list(axes.flat)[len(profiles) :]:
        axis.axis("off")
    figure.supxlabel("Azimuth (deg, clockwise from north)", fontsize=9)
    figure.supylabel("Horizon elevation (deg)", fontsize=9)
    figure.tight_layout()
    figure.savefig(directory / "overview.png", dpi=130)
    plt.close(figure)
    return ["overview.png"]
