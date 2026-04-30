"""
SSTable (Sorted String Table) — immutable, sorted, on-disk key-value file.

File layout (all lengths in bytes):
┌─────────────────────────────────────┐
│  Data Block                         │  key-value pairs, sorted by key
│    [4B key_len][key][4B val_len][val] repeated  │
├─────────────────────────────────────┤
│  Index Block                        │  sparse index: key → data offset
│    [4B key_len][key][8B offset]  x N │
├─────────────────────────────────────┤
│  Bloom Filter Block                 │
├─────────────────────────────────────┤
│  Footer (40 bytes)                  │
│    [8B index_offset]                │
│    [8B index_length]                │
│    [8B bloom_offset]                │
│    [8B bloom_length]                │
│    [8B entry_count]                 │
└─────────────────────────────────────┘

Read path:
  1. Load footer → locate index and bloom filter blocks.
  2. maybe_contains(key) on bloom filter → skip file if definitely absent.
  3. Binary-search the index for the largest key ≤ target.
  4. Seek to that data offset and scan forward until key matches or exceeds target.
"""

import struct
from pathlib import Path
from typing import Iterator

from .bloom_filter import BloomFilter

_ENTRY_HEADER = struct.Struct(">II")   # key_len, val_len  (4+4 bytes)
_INDEX_ENTRY  = struct.Struct(">IQ")   # key_len, offset   (4+8 bytes)
_FOOTER       = struct.Struct(">QQQQQ") # 5 × 8-byte uint64


class SSTable:
    def __init__(self, path: Path, level: int = 0):
        self.path = path
        self.level = level
        self._index: list[tuple[str, int]] = []   # [(key, data_offset), ...]
        self._bloom: BloomFilter | None = None
        self._entry_count: int = 0
        if path.exists():
            self._load_index_and_bloom()

    # ── build (write) ────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        path: Path,
        items: list[tuple[str, str]],
        level: int = 0,
        bloom_fpr: float = 0.01,
    ) -> "SSTable":
        """Write sorted (key, value) pairs to disk and return the SSTable."""
        bloom = BloomFilter(max(len(items), 1), bloom_fpr)
        index: list[tuple[str, int]] = []

        with open(path, "wb") as f:
            # ── data block ──────────────────────────────────────────────────
            for key, value in items:
                offset = f.tell()
                index.append((key, offset))
                bloom.add(key)
                key_b = key.encode()
                val_b = value.encode()
                f.write(_ENTRY_HEADER.pack(len(key_b), len(val_b)))
                f.write(key_b)
                f.write(val_b)

            # ── index block ─────────────────────────────────────────────────
            index_offset = f.tell()
            for key, offset in index:
                key_b = key.encode()
                f.write(_INDEX_ENTRY.pack(len(key_b), offset))
                f.write(key_b)
            index_length = f.tell() - index_offset

            # ── bloom filter block ───────────────────────────────────────────
            bloom_offset = f.tell()
            bloom_bytes = bloom.to_bytes()
            f.write(bloom_bytes)
            bloom_length = len(bloom_bytes)

            # ── footer ──────────────────────────────────────────────────────
            f.write(_FOOTER.pack(
                index_offset, index_length,
                bloom_offset, bloom_length,
                len(items),
            ))

        sst = cls(path, level)
        return sst

    # ── read ─────────────────────────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        """Return value string, TOMBSTONE, or None."""
        if self._bloom and not self._bloom.maybe_contains(key):
            return None   # bloom filter says definitely not here

        if not self._index:
            return None

        # binary search: find largest index key ≤ target
        lo, hi = 0, len(self._index) - 1
        pos = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._index[mid][0] <= key:
                pos = mid
                lo = mid + 1
            else:
                hi = mid - 1

        if pos == -1:
            return None

        start_offset = self._index[pos][1]
        # end_offset: next index entry's offset, or bloom_offset as sentinel
        end_offset = (
            self._index[pos + 1][1] if pos + 1 < len(self._index)
            else self._bloom_offset
        )

        with open(self.path, "rb") as f:
            f.seek(start_offset)
            while f.tell() < end_offset:
                header = f.read(_ENTRY_HEADER.size)
                if len(header) < _ENTRY_HEADER.size:
                    break
                key_len, val_len = _ENTRY_HEADER.unpack(header)
                k = f.read(key_len).decode()
                v = f.read(val_len).decode()
                if k == key:
                    return v
                if k > key:
                    break
        return None

    def scan(self) -> Iterator[tuple[str, str]]:
        """Yield all (key, value) pairs in sorted order."""
        with open(self.path, "rb") as f:
            f.seek(0)
            while f.tell() < self._index_offset:
                header = f.read(_ENTRY_HEADER.size)
                if len(header) < _ENTRY_HEADER.size:
                    break
                key_len, val_len = _ENTRY_HEADER.unpack(header)
                k = f.read(key_len).decode()
                v = f.read(val_len).decode()
                yield k, v

    # ── metadata ─────────────────────────────────────────────────────────────

    @property
    def min_key(self) -> str | None:
        return self._index[0][0] if self._index else None

    @property
    def max_key(self) -> str | None:
        return self._index[-1][0] if self._index else None

    @property
    def entry_count(self) -> int:
        return self._entry_count

    def delete_file(self) -> None:
        self.path.unlink(missing_ok=True)

    def __repr__(self) -> str:
        return (
            f"SSTable(level={self.level}, entries={self._entry_count}, "
            f"min={self.min_key!r}, max={self.max_key!r}, "
            f"path={self.path.name})"
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _load_index_and_bloom(self) -> None:
        with open(self.path, "rb") as f:
            # footer is always the last 40 bytes
            f.seek(-_FOOTER.size, 2)
            footer = _FOOTER.unpack(f.read(_FOOTER.size))
            idx_off, idx_len, bloom_off, bloom_len, entry_count = footer
            self._index_offset = idx_off
            self._bloom_offset = bloom_off
            self._entry_count = entry_count

            # load index
            f.seek(idx_off)
            raw_index = f.read(idx_len)
            pos = 0
            while pos < len(raw_index):
                key_len, offset = _INDEX_ENTRY.unpack_from(raw_index, pos)
                pos += _INDEX_ENTRY.size
                key = raw_index[pos: pos + key_len].decode()
                pos += key_len
                self._index.append((key, offset))

            # load bloom filter
            f.seek(bloom_off)
            self._bloom = BloomFilter.from_bytes(f.read(bloom_len))
