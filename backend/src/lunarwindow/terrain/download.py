"""Resumable, checksummed downloads of the NASA rasters in `products.PRODUCTS`.

Files land unchanged under `data/raw/lola/`. Each completed file gets a JSON sidecar recording
its source URL, size, SHA-256, and retrieval time; horizon runs copy that provenance.
"""

import hashlib
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..ephemeris.models import iso_utc
from ..ephemeris.storage import atomic_write, file_lock
from .products import PRODUCTS, Product

USER_AGENT = "LunarWindow-Terrain/0.3.0 (+https://github.com/mihaicostache1/nasa-space-apps/issues)"
CHUNK = 4 * 1024 * 1024


def sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".provenance.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def read_provenance(path: Path) -> dict:
    """Return the sidecar for a completed download; re-hash only if the file changed."""
    sidecar = sidecar_path(path)
    if not sidecar.exists():
        raise FileNotFoundError(
            f"No provenance for {path}. Download it with `lunarwindow-terrain download`."
        )
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    stat = path.stat()
    if record.get("sizeBytes") != stat.st_size or record.get("mtimeNs") != stat.st_mtime_ns:
        if sha256_file(path) != record.get("sha256"):
            raise ValueError(f"{path} no longer matches its recorded SHA-256; re-download it.")
        record["mtimeNs"] = stat.st_mtime_ns
        atomic_write(sidecar, json.dumps(record, indent=2) + "\n")
    return record


def _fetch_segment(url: str, part: Path, start: int, end: int, counter, attempts: int = 6):
    """Download bytes [start, end] into `part`, resuming from its current length."""
    expected = end - start + 1
    for attempt in range(attempts):
        have = part.stat().st_size if part.exists() else 0
        if have > expected:
            part.unlink()
            have = 0
        if have == expected:
            return
        request = Request(
            url, headers={"User-Agent": USER_AGENT, "Range": f"bytes={start + have}-{end}"}
        )
        try:
            with urlopen(request, timeout=120) as response:
                if response.status != 206:
                    raise ValueError(f"{url} does not support byte ranges.")
                content_type = response.headers.get("Content-Type", "")
                if "html" in content_type:
                    raise ValueError(f"{url} returned {content_type}, not a raster.")
                with part.open("ab") as output:
                    while block := response.read(CHUNK):
                        output.write(block)
                        counter(len(block))
        except (OSError, HTTPError) as exc:
            if attempt == attempts - 1:
                raise
            print(f"  retrying {part.name} after {exc}", file=sys.stderr)
            time.sleep(min(60, 5 * 2**attempt))
    if part.stat().st_size != expected:
        raise ValueError(f"{part.name}: incomplete after {attempts} attempts; re-run to resume.")


def download(product: Product, directory: Path, progress=None, connections: int = 4) -> Path:
    """Fetch in `connections` byte-range segments; NASA's server throttles per connection."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / product.filename
    with file_lock(directory / ".locks" / f"{product.filename}.lock", timeout=24 * 3600):
        if path.exists() and sidecar_path(path).exists():
            read_provenance(path)
            return path
        partial = path.with_name(path.name + ".part")
        size = product.size_bytes
        segment = -(-size // connections)
        ranges = [(i, i * segment, min(size, (i + 1) * segment) - 1) for i in range(connections)]
        parts = [path.with_name(f"{path.name}.part{i}") for i, _, _ in ranges]
        lock = threading.Lock()
        state = {"done": sum(p.stat().st_size for p in parts if p.exists()), "reported": 0}

        def counter(count):
            with lock:
                state["done"] += count
                if progress and state["done"] - state["reported"] >= 128 * 1024 * 1024:
                    state["reported"] = state["done"]
                    progress(product, state["done"])

        with ThreadPoolExecutor(max_workers=connections) as pool:
            futures = [
                pool.submit(_fetch_segment, product.url, parts[i], start, end, counter)
                for i, start, end in ranges
            ]
            for future in futures:
                future.result()
        with partial.open("wb") as output:
            for part in parts:
                with part.open("rb") as stream:
                    shutil.copyfileobj(stream, output, CHUNK)
        for part in parts:
            part.unlink()
        size = partial.stat().st_size
        if size != product.size_bytes:
            raise ValueError(
                f"{product.filename}: expected {product.size_bytes} bytes, got {size}. "
                "Re-run to resume, or update products.py if NASA republished the file."
            )
        digest = sha256_file(partial)
        partial.replace(path)
        stat = path.stat()
        record = {
            "productId": product.product_id,
            "sourceUrl": product.url,
            "sourcePage": product.source_page,
            "role": product.role,
            "resolutionM": product.resolution_m,
            "sizeBytes": stat.st_size,
            "sha256": digest,
            "retrievedAtUtc": iso_utc(datetime.now(timezone.utc)),
            "mtimeNs": stat.st_mtime_ns,
        }
        atomic_write(sidecar_path(path), json.dumps(record, indent=2) + "\n")
        return path


def download_all(product_ids, directory: Path) -> list[Path]:
    def progress(product, written):
        print(
            f"  {product.filename}: {written / 1e9:.2f} / {product.size_bytes / 1e9:.2f} GB",
            file=sys.stderr,
        )

    paths = []
    for product_id in product_ids:
        product = PRODUCTS[product_id]
        print(
            f"Fetching {product.filename} ({product.size_bytes / 1e6:.0f} MB)...", file=sys.stderr
        )
        paths.append(download(product, directory, progress))
    return paths
