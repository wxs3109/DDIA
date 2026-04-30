"""
Demo: walk through every major LSM-Tree concept from DDIA ch3.

Run:
  cd practice/storage-engines
  python -m lsm.demo
"""

import shutil
import tempfile
from pathlib import Path

from .bloom_filter import BloomFilter
from .lsm_tree import LSMTree


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def show(label: str, value) -> None:
    print(f"  {label:<35} {value!r}")


# ─── 1. Bloom Filter ─────────────────────────────────────────────────────────

def demo_bloom_filter() -> None:
    section("1. Bloom Filter")
    bf = BloomFilter(capacity=1000, false_positive_rate=0.01)
    print(f"  {bf}")
    print(f"  bit-array size m = {bf.m}, hash functions k = {bf.k}")

    for key in ["apple", "banana", "cherry"]:
        bf.add(key)

    print()
    for key in ["apple", "banana", "cherry", "durian", "elderberry"]:
        result = bf.maybe_contains(key)
        tag = "in set" if key in {"apple", "banana", "cherry"} else "NOT in set"
        verdict = "maybe v" if result else "definitely absent x"
        print(f"  {key:<12} ({tag:<12})  bloom says: {verdict}")

    print()
    print("  -> False negatives: NEVER happen (if key was added, bloom always says maybe).")
    print("  -> False positives: CAN happen (bloom says maybe for a key not in set).")


# ─── 2. MemTable + WAL ───────────────────────────────────────────────────────

def demo_memtable(data_dir: Path) -> None:
    section("2. MemTable + WAL")
    db = LSMTree(data_dir / "memtable_demo", memtable_threshold=10_000)

    print("  Writing 5 keys to MemTable (backed by WAL)...")
    for i in range(5):
        db.put(f"key{i:03}", f"value{i}")

    print(f"  MemTable entries: {db.info()['memtable_entries']}")
    show("get('key002')", db.get("key002"))
    show("get('key999') [absent]", db.get("key999"))

    # Simulate crash recovery: reopen the same directory
    print()
    print("  Simulating crash + reopen (WAL replay)...")
    db.close()
    db2 = LSMTree(data_dir / "memtable_demo", memtable_threshold=10_000)
    show("After reopen, get('key002')", db2.get("key002"))
    db2.close()


# ─── 3. SSTable flush ────────────────────────────────────────────────────────

def demo_sstable_flush(data_dir: Path) -> None:
    section("3. SSTable Flush (MemTable -> Disk)")
    db = LSMTree(data_dir / "flush_demo", memtable_threshold=200)

    print("  Writing enough data to trigger an automatic flush...")
    for i in range(20):
        db.put(f"row{i:04}", "x" * 20)

    info = db.info()
    print(f"  MemTable entries now: {info['memtable_entries']}")
    for lvl, tables in info["levels"].items():
        print(f"  {lvl}: {len(tables)} SSTable(s)")
        for t in tables:
            print(f"       {t}")

    show("get('row0005')", db.get("row0005"))
    db.close()


# ─── 4. Tombstone (delete) ───────────────────────────────────────────────────

def demo_tombstone(data_dir: Path) -> None:
    section("4. Tombstone - Deletes in LSM-Tree")
    db = LSMTree(data_dir / "tombstone_demo", memtable_threshold=200)

    db.put("ghost", "I exist")
    show("Before delete, get('ghost')", db.get("ghost"))

    db.delete("ghost")
    show("After delete,  get('ghost')", db.get("ghost"))

    # Flush so tombstone is on disk, then verify it still hides the value
    db.flush()
    show("After flush,   get('ghost')", db.get("ghost"))

    print()
    print("  A tombstone is written as a special marker value on disk.")
    print("  It shadows older versions during reads.")
    print("  This demo keeps tombstones during compaction so deletes stay correct.")
    db.close()


# ─── 5. Bloom Filter skipping SSTables ───────────────────────────────────────

def demo_bloom_skip(data_dir: Path) -> None:
    section("5. Bloom Filter Skipping Disk Reads")
    db = LSMTree(data_dir / "bloom_demo", memtable_threshold=100)

    print("  Writing 10 keys and flushing to SSTable...")
    for i in range(10):
        db.put(f"bloom_key{i}", f"val{i}")
    db.flush()

    print()
    existing = "bloom_key5"
    absent   = "nonexistent_key_xyz"
    show(f"get('{existing}') [exists]", db.get(existing))
    show(f"get('{absent}') [absent]", db.get(absent))
    print()
    print("  For the absent key, the Bloom Filter returns 'definitely not here'")
    print("  -> SSTable data blocks are NOT read from disk at all.")
    db.close()


# ─── 6. Compaction ───────────────────────────────────────────────────────────

def demo_compaction(data_dir: Path) -> None:
    section("6. Compaction - Merging SSTables")
    db = LSMTree(data_dir / "compact_demo", memtable_threshold=150)

    print("  Writing overlapping versions of the same keys across multiple flushes...")
    for version in range(5):
        for i in range(5):
            db.put(f"ck{i}", f"version_{version}")
        db.flush()
        print(f"    flush {version + 1}: ck0..ck4 = version_{version}")

    print()
    info = db.info()
    for lvl, tables in info["levels"].items():
        print(f"  {lvl}: {len(tables)} file(s)")

    print()
    print("  Triggering compaction on L0...")
    db.compact_level(0)

    info = db.info()
    print("  After compaction:")
    for lvl, tables in info["levels"].items():
        print(f"  {lvl}: {len(tables)} file(s)")
        for t in tables:
            print(f"       {t}")

    print()
    show("get('ck0') after compaction", db.get("ck0"))
    print("  -> Only the newest version survives; tombstones are kept for correctness.")
    db.close()


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="lsm_demo_"))
    print(f"Working directory: {tmp}")

    try:
        demo_bloom_filter()
        demo_memtable(tmp)
        demo_sstable_flush(tmp)
        demo_tombstone(tmp)
        demo_bloom_skip(tmp)
        demo_compaction(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  Done. Temp files cleaned up.")


if __name__ == "__main__":
    main()
