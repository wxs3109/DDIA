"""
MemTable — in-memory write buffer, backed by a Write-Ahead Log (WAL).

Writes land here first (after WAL append), so they are durable before
the process acknowledges them.  When size_bytes exceeds the threshold the
LSMTree flushes this table to an immutable SSTable on disk and starts a
fresh one.

WAL format (append-only, one record per line):
  PUT <key>\t<value>\n
  DEL <key>\n

On restart, replay the WAL to rebuild the MemTable before opening the tree.
"""

import json
from pathlib import Path

TOMBSTONE = "__TOMBSTONE__"


class WAL:
    def __init__(self, path: Path):
        self.path = path
        self._f = open(path, "a", encoding="utf-8")

    def append_put(self, key: str, value: str) -> None:
        self._f.write(json.dumps({"op": "put", "key": key, "value": value}) + "\n")
        self._f.flush()

    def append_delete(self, key: str) -> None:
        self._f.write(json.dumps({"op": "del", "key": key}) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    def delete_file(self) -> None:
        self._f.close()
        self.path.unlink(missing_ok=True)

    @staticmethod
    def replay(path: Path) -> dict[str, str]:
        """Return the key→value map reconstructed from a WAL file."""
        data: dict[str, str] = {}
        if not path.exists():
            return data
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # Compatibility with the original text WAL format.
                    if line.startswith("PUT "):
                        rest = line[4:]
                        key, _, value = rest.partition("\t")
                        data[key] = value
                    elif line.startswith("DEL "):
                        data[line[4:]] = TOMBSTONE
                    continue

                op = record.get("op")
                key = record.get("key")
                if not isinstance(key, str):
                    continue
                if op == "put":
                    value = record.get("value")
                    if isinstance(value, str):
                        data[key] = value
                elif op == "del":
                    data[key] = TOMBSTONE
        return data


class MemTable:
    def __init__(self, wal: WAL, size_threshold: int = 1024 * 1024):
        self._data: dict[str, str] = {}
        self._size_bytes: int = 0
        self._wal = wal
        self.size_threshold = size_threshold

    # ── public API ──────────────────────────────────────────────────────────

    def put(self, key: str, value: str) -> None:
        self._wal.append_put(key, value)
        self._update(key, value)

    def delete(self, key: str) -> None:
        self._wal.append_delete(key)
        self._update(key, TOMBSTONE)

    def get(self, key: str) -> str | None:
        """Return value, TOMBSTONE sentinel, or None if key not present."""
        return self._data.get(key)

    def is_full(self) -> bool:
        return self._size_bytes >= self.size_threshold

    def sorted_items(self) -> list[tuple[str, str]]:
        return sorted(self._data.items())

    def __len__(self) -> int:
        return len(self._data)

    # ── internals ───────────────────────────────────────────────────────────

    def _update(self, key: str, value: str) -> None:
        old = self._data.get(key)
        if old is not None:
            self._size_bytes -= len(key) + len(old)
        self._data[key] = value
        self._size_bytes += len(key) + len(value)

    @classmethod
    def from_wal(cls, wal: WAL, size_threshold: int = 1024 * 1024) -> "MemTable":
        """Reconstruct a MemTable by replaying an existing WAL."""
        mt = cls(wal, size_threshold)
        for key, value in WAL.replay(wal.path).items():
            mt._update(key, value)
        return mt
