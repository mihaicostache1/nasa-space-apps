"""Export one JSON and one CSV per site for the backend/data lead."""

import argparse
import csv
import json
from pathlib import Path
import sys

from .horizons import HorizonsClient, HorizonsError, query_parameters, query_url
from .models import Site, TimeRange


def load_sites(path: Path) -> list[Site]:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("Site file must contain a nonempty JSON array.")
    sites = [Site(
        site_id=row["id"], name=row["name"], lat=row["lat"], lon=row["lon"],
        altitude_km=row["altitudeKm"], coordinate_source=row["coordinateSource"],
    ) for row in rows]
    if len({site.site_id for site in sites}) != len(sites):
        raise ValueError("Site IDs must be unique.")
    return sites


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=Path, required=True, help="JSON site catalog; see data/sites.example.json")
    parser.add_argument("--start", required=True, help="Inclusive UTC start, e.g. 2026-11-14T00:00:00Z")
    parser.add_argument("--end", required=True, help="Exclusive UTC end")
    parser.add_argument("--step-minutes", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("data/processed/ephemeris"))
    parser.add_argument("--cache", type=Path, default=Path("data/raw/horizons"))
    parser.add_argument("--refresh", action="store_true", help="Replace cached responses from NASA")
    parser.add_argument("--dry-run", action="store_true", help="Print request counts and first URLs; no network or writes")
    args = parser.parse_args()
    try:
        sites = load_sites(args.sites)
        period = TimeRange(args.start, args.end, args.step_minutes)
        if args.dry_run:
            chunks = list(period.chunks())
            print(json.dumps({
                "sites": len(sites), "samplesPerSite": period.sample_count,
                "requests": len(sites) * len(chunks) * 2,
                "firstRequests": [query_url(query_parameters(sites[0], target, *chunks[0], period.step_minutes)) for target in ("sun", "earth")],
            }, indent=2))
            return 0
        client = HorizonsClient(args.cache, refresh=args.refresh)
        for site in sites:
            print(f"Evaluating {site.site_id} ({period.sample_count} samples)...", file=sys.stderr)
            result = client.evaluate(site, period)
            args.output.mkdir(parents=True, exist_ok=True)
            # Repeated exports for a site replace that site's prior JSON/CSV pair.
            path = args.output / f"{site.site_id}.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
            temporary.replace(path)
            with path.with_suffix(".csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["t", "sunAz", "sunEl", "earthAz", "earthEl"])
                writer.writeheader()
                writer.writerows(result["series"])
            print(f"Wrote {path}", file=sys.stderr)
        return 0
    except (ValueError, KeyError, TypeError, OSError, HorizonsError) as exc:
        print(f"Ephemeris export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
