"""Thread-safe, bounded storage for immutable serialized reference responses."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from .reference_cache_key import ReferenceEvaluationCacheKey


@dataclass(frozen=True)
class ReferenceCacheInfo:
    """Atomic capacity snapshot; stored_bytes counts serialized response payloads."""

    entry_count: int
    stored_bytes: int
    max_entries: int
    max_bytes: int


class ReferenceEvaluationCache:
    """Process-local LRU storage, independent of calculation and source verification.

    Values are immutable bytes, normally UTF-8 JSON from a validated successful
    response. The byte budget counts payloads, excluding Python/container overhead;
    the entry limit also bounds the number of fixed-size digest keys and objects.
    Either limit being zero disables storage. Failed/oversized puts change nothing.
    """

    def __init__(self, *, max_entries: int = 32, max_bytes: int = 16 * 1024 * 1024) -> None:
        for name, value in (("max_entries", max_entries), ("max_bytes", max_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._stored_bytes = 0
        self._lock = Lock()

    def get(self, key: ReferenceEvaluationCacheKey) -> bytes | None:
        """Return immutable snapshot bytes, promoting a hit to most recently used."""
        digest = ReferenceEvaluationCacheKey.model_validate(key).digest
        with self._lock:
            snapshot = self._entries.get(digest)
            if snapshot is not None:
                self._entries.move_to_end(digest)
            return snapshot

    def put(self, key: ReferenceEvaluationCacheKey, snapshot: bytes) -> bool:
        """Store/replace a snapshot atomically; return false when it cannot fit.

        Caller-owned models, dictionaries, bytearrays, and memoryviews are not
        retained. Serialize a validated response before calling this method.
        Replacement counts as use; readers see the complete old or new snapshot.
        """
        digest = ReferenceEvaluationCacheKey.model_validate(key).digest
        if not isinstance(snapshot, bytes):
            raise TypeError("A reference cache snapshot must be immutable bytes.")
        # Normalize bytes subclasses so sizing and stored values use built-in bytes.
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
        """Discard all entries and reset byte accounting under the same lock."""
        with self._lock:
            self._entries.clear()
            self._stored_bytes = 0

    def info(self) -> ReferenceCacheInfo:
        """Read counts and limits together without exposing the storage mapping."""
        with self._lock:
            return ReferenceCacheInfo(
                entry_count=len(self._entries),
                stored_bytes=self._stored_bytes,
                max_entries=self._max_entries,
                max_bytes=self._max_bytes,
            )
