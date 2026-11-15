"""Thread-safe, bounded storage for immutable serialized reference responses."""

from dataclasses import dataclass

from .reference_cache_key import ReferenceEvaluationCacheKey
from .snapshot_cache import SnapshotCache


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
        self._cache = SnapshotCache(max_entries=max_entries, max_bytes=max_bytes)

    def get(self, key: ReferenceEvaluationCacheKey) -> bytes | None:
        """Return immutable snapshot bytes, promoting a hit to most recently used."""
        digest = ReferenceEvaluationCacheKey.model_validate(key).digest
        return self._cache.get(digest)

    def put(self, key: ReferenceEvaluationCacheKey, snapshot: bytes) -> bool:
        """Store/replace a snapshot atomically; return false when it cannot fit.

        Caller-owned models, dictionaries, bytearrays, and memoryviews are not
        retained. Serialize a validated response before calling this method.
        Replacement counts as use; readers see the complete old or new snapshot.
        """
        digest = ReferenceEvaluationCacheKey.model_validate(key).digest
        return self._cache.put(digest, snapshot)

    def clear(self) -> None:
        """Discard all entries and reset byte accounting under the same lock."""
        self._cache.clear()

    def info(self) -> ReferenceCacheInfo:
        """Read counts and limits together without exposing the storage mapping."""
        info = self._cache.info()
        return ReferenceCacheInfo(
            entry_count=info.entry_count,
            stored_bytes=info.stored_bytes,
            max_entries=info.max_entries,
            max_bytes=info.max_bytes,
        )
