"""
Demo: B-Tree operations walkthrough

Run:
  cd practice/storage-engines
  py -m btree.demo
"""

import shutil
import tempfile
from pathlib import Path

from .btree import ORDER, BTree


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def show(label: str, value) -> None:
    print(f"  {label:<40} {value!r}")


# --- 1. Basic get / put -------------------------------------------------------

def demo_basic(data_dir: Path) -> None:
    section("1. Basic put / get")
    db = BTree(data_dir / "basic.db")

    entries = [
        ("banana", "yellow"),
        ("apple",  "red"),
        ("cherry", "red"),
        ("date",   "brown"),
    ]
    print("  Inserting 4 key-value pairs ...")
    for k, v in entries:
        db.put(k, v)

    print()
    for k, _ in entries:
        show(f"get('{k}')", db.get(k))
    show("get('mango') [absent]", db.get("mango"))
    db.close()


# --- 2. Page split ------------------------------------------------------------

def demo_split(data_dir: Path) -> None:
    section(f"2. Page split (ORDER={ORDER}, max {2*ORDER-1} keys per page)")
    db = BTree(data_dir / "split.db")

    keys = ["b", "d", "f", "a", "c", "e", "g", "h"]
    print(f"  Inserting in order: {keys}")
    print()

    for k in keys:
        db.put(k, f"val_{k}")
        print(f"  After inserting '{k}':")
        db.print_tree()

    print()
    print("  Observations:")
    print("  - A leaf overflows (> 3 keys) -> split into two half-full leaves")
    print("  - The middle key is pushed up to the parent as a routing key")
    print("  - If the root splits, tree height increases by 1 with a new root")
    db.close()


# --- 3. Range scan (leaf sibling chain) ----------------------------------------

def demo_scan(data_dir: Path) -> None:
    section("3. Range scan (using leaf left/right sibling pointers)")
    db = BTree(data_dir / "scan.db")

    import random
    keys = list(range(1, 16))
    random.shuffle(keys)
    print(f"  Inserting {len(keys)} integer keys in random order ...")
    for k in keys:
        db.put(str(k).zfill(3), f"v{k}")

    result = db.scan()
    print(f"  scan() returned {len(result)} entries in sorted order:")
    print(f"  {[k for k, _ in result]}")
    print()
    print("  scan() traverses leaf pages horizontally via right_sib pointers,")
    print("  never touching internal nodes.")
    db.close()


# --- 4. Update (in-place overwrite) -------------------------------------------

def demo_update(data_dir: Path) -> None:
    section("4. Update key (in-place page overwrite)")
    db = BTree(data_dir / "update.db")

    db.put("status", "pending")
    show("Initial get('status')", db.get("status"))

    db.put("status", "done")
    show("After update get('status')", db.get("status"))

    print()
    print("  B-Tree updates find the leaf page and overwrite it in-place.")
    print("  Contrast with LSM-Tree, which appends a new version.")
    print("  The WAL is written first to guarantee crash safety.")
    db.close()


# --- 5. Delete (with rebalancing) ---------------------------------------------

def demo_delete(data_dir: Path) -> None:
    section("5. Delete key (may trigger borrow or merge)")
    db = BTree(data_dir / "delete.db")

    keys = ["b", "d", "f", "a", "c", "e", "g"]
    for k in keys:
        db.put(k, f"val_{k}")

    print("  Initial tree:")
    db.print_tree()

    to_delete = ["a", "b", "g", "f"]
    for k in to_delete:
        ok = db.delete(k)
        print(f"\n  delete('{k}') = {ok}  ->  tree after delete:")
        db.print_tree()

    print()
    print("  Observations:")
    print("  - If a page drops below ORDER-1 keys, try borrowing from sibling (rotation)")
    print("  - If sibling has no spare keys, merge with sibling; parent loses a key")
    print("  - Merge can propagate upward; tree height may shrink")
    db.close()


# --- 6. WAL crash recovery ----------------------------------------------------

def demo_wal_recovery(data_dir: Path) -> None:
    section("6. WAL crash recovery")

    db_path  = data_dir / "recovery.db"
    wal_path = data_dir / "recovery.wal"

    db = BTree(db_path, wal_path)
    db.put("persistent_key", "I survived the crash")
    for i in range(5):
        db.put(f"k{i}", f"v{i}")
    # Simulate crash: skip close() so WAL is not truncated
    db._wal.close()
    print("  [crash simulation] Wrote 6 keys, then process died. WAL not truncated.")

    print("  [restart] Replaying WAL ...")
    db2 = BTree(db_path, wal_path)
    show("After recovery get('persistent_key')", db2.get("persistent_key"))
    show("After recovery get('k3')", db2.get("k3"))
    show("After recovery get('missing')", db2.get("missing"))
    db2.close()

    print()
    print("  B-Tree WAL records physical page contents (not logical ops).")
    print("  On replay, each page is written back to its offset in the db file.")
    print("  Contrast with LSM WAL, which records logical PUT/DEL operations.")


# --- main ---------------------------------------------------------------------

def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="btree_demo_"))
    print(f"Working directory: {tmp}")

    try:
        demo_basic(tmp)
        demo_split(tmp)
        demo_scan(tmp)
        demo_update(tmp)
        demo_delete(tmp)
        demo_wal_recovery(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  Done. Temp files cleaned up.")


if __name__ == "__main__":
    main()
