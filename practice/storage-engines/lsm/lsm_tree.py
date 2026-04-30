"""
LSMTree — top-level coordinator.

Write path:
  put/delete → WAL append → MemTable update → [flush if full]

Read path:
  MemTable → L0 SSTables (newest first) → L1 → L2 → ...

Flush:
  Dump sorted MemTable to a new L0 SSTable, delete WAL, start fresh MemTable.

Compaction (size-tiered):
  L0 >= L0_LIMIT  →  merge all L0 into one L1 file
  L1 >= L1_LIMIT  →  merge all L1 into one L2 file
  (etc.)
"""

from pathlib import Path
from time import time_ns

from .compaction import compact
from .memtable import TOMBSTONE, WAL, MemTable
from .sstable import SSTable

L0_LIMIT = 4   # trigger compaction when L0 reaches this many files
LEVEL_LIMIT = 4  # same threshold for L1, L2, ...
MAX_LEVELS = 5


class LSMTree:
    def __init__(self, data_dir: str | Path, memtable_threshold: int = 1024 * 1024):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._threshold = memtable_threshold
        self._file_seq = 0

        # levels[i] = list of SSTables at level i, newest first. Higher levels
        # may contain overlapping files until they hit the compaction threshold.
        self._levels: list[list[SSTable]] = [[] for _ in range(MAX_LEVELS)]

        self._load_existing_sstables()
        wal_path = self.dir / "wal.log"
        wal = WAL(wal_path)
        self._memtable = MemTable.from_wal(wal, self._threshold)
        self._wal = wal

    # ── public API ───────────────────────────────────────────────────────────

    def put(self, key: str, value: str) -> None:
        self._memtable.put(key, value)
        if self._memtable.is_full():
            self._flush()

    def delete(self, key: str) -> None:
        """Write a tombstone; physical removal happens during compaction."""
        self._memtable.delete(key)
        if self._memtable.is_full():
            self._flush()

    def get(self, key: str) -> str | None:
        # 1. MemTable (most recent)
        result = self._memtable.get(key)
        if result is not None:
            return None if result == TOMBSTONE else result

        # 2. SSTables level by level, newest first within each level
        for level_tables in self._levels:
            for sst in level_tables:
                result = sst.get(key)
                if result is not None:
                    return None if result == TOMBSTONE else result

        return None

    def flush(self) -> SSTable | None:
        """Force-flush the current MemTable even if not full."""
        if len(self._memtable) == 0:
            return None
        return self._flush()

    def compact_level(self, level: int) -> SSTable | None:
        """Manually trigger compaction at the given level."""
        return self._maybe_compact(level, force=True)

    def info(self) -> dict:
        return {
            "memtable_entries": len(self._memtable),
            "levels": {
                f"L{i}": [str(sst) for sst in tables]
                for i, tables in enumerate(self._levels)
                if tables
            },
        }

    def close(self) -> None:
        self._wal.close()

    # ── internals ────────────────────────────────────────────────────────────

    def _flush(self) -> SSTable:
        sst_path = self._next_sstable_path(0)
        sst = SSTable.build(sst_path, self._memtable.sorted_items(), level=0)
        self._levels[0].insert(0, sst)  # newest first

        self._wal.delete_file()
        new_wal = WAL(self.dir / "wal.log")
        self._memtable = MemTable(new_wal, self._threshold)
        self._wal = new_wal

        self._maybe_compact(0)
        return sst

    def _maybe_compact(self, level: int, force: bool = False) -> SSTable | None:
        limit = L0_LIMIT if level == 0 else LEVEL_LIMIT
        if not force and len(self._levels[level]) < limit:
            return None
        if not self._levels[level]:
            return None
        if level + 1 >= MAX_LEVELS:
            return None

        tables = self._levels[level]
        out_path = self._next_sstable_path(level + 1)
        new_sst = compact(tables, out_path, level=level + 1)

        for old in tables:
            old.delete_file()
        self._levels[level] = []
        self._levels[level + 1].insert(0, new_sst)

        # cascade
        self._maybe_compact(level + 1)
        return new_sst

    def _load_existing_sstables(self) -> None:
        """Reload SSTable files left on disk from a previous run."""
        sst_files = sorted(self.dir.glob("L*.sst"), key=lambda p: p.name, reverse=True)
        for path in sst_files:
            try:
                lvl = int(path.stem.split("_")[0][1:])
                sst = SSTable(path, level=lvl)
                self._levels[lvl].append(sst)
            except (ValueError, IndexError):
                pass

    def _next_sstable_path(self, level: int) -> Path:
        """Return a unique SSTable path that sorts newest-first by filename."""
        while True:
            self._file_seq += 1
            path = self.dir / f"L{level}_{time_ns()}_{self._file_seq}.sst"
            if not path.exists():
                return path
