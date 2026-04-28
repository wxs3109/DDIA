# LSM-Tree (Log-Structured Merge Tree)
# Reference: DDIA ch4, sec_storage_lsm
#
# Simplified implementation to understand the core ideas:
# - writes go to in-memory memtable (sorted)
# - memtable flushes to disk as immutable SSTable segments
# - reads check memtable first, then segments from newest to oldest
# - background compaction merges and garbage-collects segments

class LSMTree:
    pass  # TODO
