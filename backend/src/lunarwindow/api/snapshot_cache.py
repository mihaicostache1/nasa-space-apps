"""Thread-safe byte-budgeted LRU shared by validated evaluation providers."""

import re
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class SnapshotCacheInfo:
    """Atomic counts; the byte budget covers retained payloads, not process memory."""

    entry_count: int
    stored_bytes: int
    max_entries: int
    max_bytes: int


class SnapshotCache:
    """Retain immutable snapshots under fixed-size caller-validated identity digests.

    Neither cache hits nor well-formed digests establish source integrity. Providers
    must check their sources and policies before consulting this cache.
    """

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        for name, value in (("max_entries", max_entries), ("max_bytes", max_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._stored_bytes = 0
        self._lock = Lock()

    @staticmethod
    def _validate_digest(digest: str) -> None:
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("A snapshot key must be a lowercase SHA-256 digest.")

    def get(self, digest: str) -> bytes | None:
        self._validate_digest(digest)
        with self._lock:
            snapshot = self._entries.get(digest)
            if snapshot is not None:
                self._entries.move_to_end(digest)
            return snapshot

    def put(self, digest: str, snapshot: bytes) -> bool:
        self._validate_digest(digest)
        if not isinstance(snapshot, bytes):
            raise TypeError("A cache snapshot must be immutable bytes.")
        snapshot = bytes(snapshot)
        size = len(snapshot)
        with self._lock:
            if not self._max_entries or not self._max_bytes or size > self._max_bytes:
                return False
            previous = self._entries.pop(digest, None)
            if previous is not None:
                self._stored_bytes -= len(previous)
            while (
                len(self._entries) >= self._max_entries
                or self._stored_bytes + size > self._max_bytes
            ):
                _, evicted = self._entries.popitem(last=False)
                self._stored_bytes -= len(evicted)
            self._entries[digest] = snapshot
            self._stored_bytes += size
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._stored_bytes = 0

    def info(self) -> SnapshotCacheInfo:
        with self._lock:
            return SnapshotCacheInfo(
                entry_count=len(self._entries),
                stored_bytes=self._stored_bytes,
                max_entries=self._max_entries,
                max_bytes=self._max_bytes,
            )
