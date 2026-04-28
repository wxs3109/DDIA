# B-Tree
# Reference: DDIA ch4, sec_storage_btree
#
# Key differences from LSM-Tree:
# - in-place updates (no append-only)
# - reads are faster; writes require random I/O
# - WAL (write-ahead log) for crash recovery

class BTree:
    pass  # TODO
