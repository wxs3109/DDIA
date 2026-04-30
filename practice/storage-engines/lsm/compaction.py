"""
Compaction — merge multiple SSTables into one, dropping stale keys.

Strategy: size-tiered compaction (simplified).
  - When L0 accumulates >= L0_LIMIT files, merge all L0 into a single L1 file.
  - When L1 accumulates >= L1_LIMIT files, merge all L1 into a single L2 file.
  - And so on.

Merge algorithm: k-way merge with a min-heap (heapq).
  - Open a sorted iterator over each SSTable.
  - Always pop the smallest key; if the same key appears in multiple tables,
    keep only the value from the newest table (lowest sequence number = newest,
    since we flush in order).
  - Keep tombstones so deletes continue to shadow older versions in lower
    levels. This simplified compactor does not prove when a tombstone is safe
    to garbage-collect.
"""

import heapq
from pathlib import Path
from typing import Iterator

from .sstable import SSTable


def _merge_iterators(
    sstables: list[SSTable],
) -> Iterator[tuple[str, str]]:
    """
    k-way merge over sorted SSTable iterators.

    Heap entries: (key, seq, value)
    seq = index in sstables list; lower index = newer (flushed later).
    When keys tie we keep the one with the lowest seq (newest).
    """
    # Each element: (key, seq, value, iterator). seq is stable for the source
    # table; lower seq means newer because LSMTree stores tables newest first.
    heap: list[tuple[str, int, str, Iterator]] = []
    iters = [sst.scan() for sst in sstables]

    for seq, it in enumerate(iters):
        try:
            k, v = next(it)
            heapq.heappush(heap, (k, seq, v, it))
        except StopIteration:
            pass

    while heap:
        key, seq, value, it = heapq.heappop(heap)
        same_key = [(seq, value, it)]

        while heap and heap[0][0] == key:
            _, dup_seq, dup_val, dup_it = heapq.heappop(heap)
            same_key.append((dup_seq, dup_val, dup_it))

        winner_seq, winner_value, _ = min(same_key, key=lambda item: item[0])

        # Keep tombstones. They may still be needed to hide older values in
        # lower levels that are not part of this compaction.
        yield key, winner_value

        for source_seq, _, source_it in same_key:
            try:
                nk, nv = next(source_it)
                heapq.heappush(heap, (nk, source_seq, nv, source_it))
            except StopIteration:
                pass


def compact(
    sstables: list[SSTable],
    output_path: Path,
    level: int,
) -> SSTable:
    """
    Merge `sstables` into a single new SSTable at `output_path`.
    Returns the new SSTable; callers are responsible for deleting the old files.
    """
    merged = list(_merge_iterators(sstables))
    return SSTable.build(output_path, merged, level=level)
