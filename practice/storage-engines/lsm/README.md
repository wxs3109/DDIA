# LSM-Tree 实现

对应 DDIA 第三章「存储引擎」中 SSTable / LSM-Tree 一节的完整 Python 实现。

运行演示：

```bash
cd practice/storage-engines
py -m lsm.demo
```

---

## 文件结构

```
lsm/
├── bloom_filter.py   # 布隆过滤器
├── memtable.py       # 内存写缓冲 + WAL
├── sstable.py        # 磁盘有序文件
├── compaction.py     # 合并压缩
├── lsm_tree.py       # 顶层协调器
└── demo.py           # 6 个演示场景
```

---

## 组件说明

### bloom_filter.py — 布隆过滤器

**作用**：用极少内存快速判断一个 key「一定不在」某个 SSTable 里，从而跳过磁盘读取。

**原理**：维护一个长度为 $m$ 的 bit 数组，用 $k$ 个哈希函数把 key 映射到 $k$ 个位置并置 1。查询时若任意一个位置为 0，则 key 一定不存在；若全为 1，则 key *可能*存在（有误判概率 $p$）。

最优参数公式（给定容量 $n$、误判率 $p$）：

$$m = \lceil -\frac{n \ln p}{(\ln 2)^2} \rceil \qquad k = \lceil \frac{m}{n} \ln 2 \rceil$$

**关键性质**：
- 假阴性（false negative）：**永远不会发生**。加入过的 key 一定能被检测到。
- 假阳性（false positive）：**可能发生**。没加入的 key 有概率被误判为存在。
- 只支持 `add` / `maybe_contains`，不支持删除。

**序列化**：`to_bytes()` / `from_bytes()` 把过滤器和 SSTable 一起存到磁盘，重启后直接加载，无需重建。

---

### memtable.py — MemTable + WAL

**MemTable**：内存中的有序写缓冲，所有写操作首先落在这里。用 Python `dict` 存储，`sorted_items()` 在 flush 时一次性排序。超过 `size_threshold`（默认 1 MB）后自动触发 flush。

**WAL（Write-Ahead Log）**：每次写入 MemTable 之前，先把操作追加到磁盘上的 `wal.log`。格式：

```
{"op":"put","key":"key","value":"value"}
{"op":"del","key":"key"}
```

**崩溃恢复**：进程重启时调用 `MemTable.from_wal()` 重放 WAL，把内存状态还原到崩溃前的最新写入。WAL 在 flush 成功后才删除。

**墓碑（Tombstone）**：删除操作写入特殊值 `__TOMBSTONE__`，而非真正删除数据。读取时命中墓碑返回 `None`；这个 demo 在 Compaction 时保留墓碑，避免更低层旧值重新可见。

---

### sstable.py — SSTable

**作用**：MemTable flush 后生成的不可变磁盘文件，key 有序存储。

**二进制文件格式**：

```
┌─────────────────────────────────────────────┐
│  Data Block                                 │
│    [4B key_len][key bytes][4B val_len][val] │  每条记录
│    ... 按 key 升序排列 ...                  │
├─────────────────────────────────────────────┤
│  Index Block                                │
│    [4B key_len][key bytes][8B data_offset]  │  每个 key 的偏移量
├─────────────────────────────────────────────┤
│  Bloom Filter Block                         │
├─────────────────────────────────────────────┤
│  Footer (固定 40 字节)                       │
│    [8B index_offset][8B index_length]       │
│    [8B bloom_offset][8B bloom_length]       │
│    [8B entry_count]                         │
└─────────────────────────────────────────────┘
```

**读取流程**（`get(key)`）：

1. 读 Footer，定位 Index Block 和 Bloom Filter 的位置
2. 查 Bloom Filter —— 若返回「一定不存在」，直接返回 `None`，**不读 Data Block**
3. 在 Index Block 中二分查找最大的 `index_key <= target_key`
4. Seek 到对应 data offset，顺序扫描直到命中或超过 target key

**追加写**：SSTable 一旦写入就不可修改（immutable）。更新和删除通过写新版本 + Compaction 去重实现。

---

### compaction.py — 合并压缩

**作用**：把多个 SSTable 合并成一个，去除旧版本，减少读放大和空间放大。

**算法：k-way 堆归并**

对每个 SSTable 打开一个有序迭代器，用最小堆同时推进所有迭代器：

```
heap = [(key, seq, value, iterator), ...]   # seq 越小 = 越新
```

- 同一个 key 出现在多个文件时，保留 `seq` 最小（最新）的版本
- 墓碑继续保留，直到实现能证明所有更旧版本都已被覆盖后才可安全丢弃

**压缩策略：Size-Tiered（简化版）**

| 层级 | 触发条件 | 动作 |
|------|----------|------|
| L0   | 文件数 >= 4 | 合并全部 L0 -> 一个 L1 文件 |
| L1   | 文件数 >= 4 | 合并全部 L1 -> 一个 L2 文件 |
| ...  | 以此类推   | 最多 5 层 |

压缩级联：L0 压缩完成后若触发 L1 阈值，自动继续压缩 L1。

---

### lsm_tree.py — 顶层协调器

统一对外暴露 `put` / `get` / `delete` 接口，内部协调以上所有组件。

**写路径**：

```
put(key, value)
  └─ WAL.append_put()          # 先持久化
  └─ MemTable.put()            # 写内存
  └─ [MemTable.is_full()]
       └─ flush()              # MemTable -> L0 SSTable
            └─ [L0 >= 4 files]
                 └─ compact(L0) -> L1
                      └─ [L1 >= 4 files]
                           └─ compact(L1) -> L2 ...
```

**读路径**：

```
get(key)
  └─ MemTable.get()            # 1. 最新数据在内存
  └─ L0 SSTables (newest first) # 2. L0 可能有重叠，从新到旧
  └─ L1 SSTables               # 3. 每层一个文件，key range 不重叠
  └─ L2, L3 ...
  └─ return None               # 4. 全部未命中
```

每个 SSTable 的读取都先过 Bloom Filter，绝大多数情况下不需要真正做磁盘 I/O。

---

## 读写工作流对比

| 操作 | 写路径 | 读路径 |
|------|--------|--------|
| **写** | WAL -> MemTable，顺序追加，极快 | — |
| **读（命中 MemTable）** | — | 内存 hash 查找，O(1) |
| **读（命中 L0）** | — | Bloom Filter + Index 二分 + Disk seek |
| **读（不存在）** | — | 每层 Bloom Filter 过滤，通常 0 次磁盘 I/O |
| **删除** | 写墓碑，等同于一次写操作 | 读到墓碑返回 None |
| **Flush** | MemTable 排序后顺序写盘，批量 I/O | — |
| **Compaction** | k-way 归并，顺序读 + 顺序写，后台执行 | — |

**写放大**：一条数据从 MemTable 到最终稳定在低层，会被反复合并写入多次。这是 LSM-Tree 的主要代价。

**读放大**：最坏情况下需要查询所有层的每个 SSTable（但 Bloom Filter 大幅缩短了这条路径）。

**空间放大**：同一个 key 的多个版本在 Compaction 前同时占据磁盘空间。

---

## 与 B-Tree 的对比

| | LSM-Tree | B-Tree |
|---|---|---|
| 写性能 | 高（顺序追加） | 中（随机写，原地更新） |
| 读性能 | 中（多层查找） | 高（一次树遍历） |
| 空间利用率 | 低（多版本共存） | 高（原地更新） |
| 适合场景 | 写密集（日志、时序、事件流） | 读密集（OLTP、频繁点查） |
| 典型系统 | LevelDB、RocksDB、Cassandra、HBase | PostgreSQL、MySQL InnoDB、SQLite |
