# Hash Sharding 下的 Range Query

这篇是 DDIA 第 7 章 `sharding` 部分的补充：**在 `hash sharding` 下，原始 key 的 `range query` 通常不能高效执行。**

核心原因是：`hash` 会把原始 key 的顺序打散。相邻的 key 经过 hash 后，可能落到完全不同的 shard。

```text
key:   1  2  3  4  5  6  7  8
hash:  A  C  B  A  D  C  B  D
```

所以这样的查询：

```sql
WHERE key BETWEEN 1000 AND 2000
```

这些 key 可能分布在所有 shard 上，系统不能只定位到某几个 shard。`hash sharding` 对 `key = ?` 这样的 point lookup 很友好，但会破坏原始 key 的有序性。

## 1. Scatter-Gather

最直接的做法是向所有 shard 发起 `range query`，然后在 coordinator / application 层合并结果。

```text
query range [1000, 2000]
   -> shard 1
   -> shard 2
   -> shard 3
   -> shard 4
merge results
```

这个方案实现直观，但代价很明显：

- 查询会 fan-out 到所有 shard；
- 延迟通常取决于最慢的 shard；
- 所有 shard 都要承受额外读取压力；
- `pagination`、`sorting`、`limit` 都会变复杂；
- 如果需要全局有序结果，还要做跨 shard merge sort。

所以 `scatter-gather` 更适合低频、后台、管理类的 range query，不适合作为核心读路径。

## 2. 改用 Range Sharding

如果 `range query` 是核心访问模式，就不应该只用 `hash sharding`，而应该考虑按 key range 分片。

```text
shard 1: key 0000 - 0999
shard 2: key 1000 - 1999
shard 3: key 2000 - 2999
```

这样查询：

```sql
WHERE key BETWEEN 1200 AND 1600
```

只需要访问 `shard 2`。

`range sharding` 的优势是保留了 key 的顺序，range scan 可以自然地裁剪 shard。但它也有典型风险：如果 key 是递增 ID、时间戳或其他单调增长字段，写入会集中到最新 range，形成 `hot shard`。

所以它适合 range scan 很重要、key 分布相对可控，或者系统有能力动态 split / move hot range 的场景。

## 3. Range Partition + Hash Bucket

很多时间序列、订单、日志系统会采用折中方案：先按范围切大分区，再在范围内 hash。

```text
2026-05-01:
  bucket 0
  bucket 1
  bucket 2
  bucket 3

2026-05-02:
  bucket 0
  bucket 1
  bucket 2
  bucket 3
```

例如查询：

```sql
WHERE created_at BETWEEN '2026-05-01' AND '2026-05-02'
```

系统只需要扫描命中日期范围内的 buckets，而不是全库所有 shard。

这个方案的 trade-off 是：

- range partition 让 query 可以裁剪一部分 shard；
- hash bucket 把同一时间范围内的写入打散，缓解热点；
- 命中的多个 bucket 仍然需要 merge；
- bucket 数量和 range 粒度需要提前设计，后续调整有成本。

这是一种很常见的实用折中：既承认 range query 的重要性，也承认连续写入容易造成热点。

## 4. 维护额外的 Range Index / Read Model

另一种做法是让主表继续按 `hash sharding` 支持 point lookup，同时额外维护一份按 range 组织的索引或 read model。

主表：

```text
user_id -> hash(user_id) -> shard
```

额外索引表：

```text
created_at -> record_id
```

查询流程：

```text
1. 在 range index 中查出 record ids
2. 根据 id / hash 定位主表 shard
3. 批量读取主表记录
4. 合并并返回结果
```

这本质上是牺牲写入复杂度换查询能力：

- 写入时要更新两份结构；
- 需要处理主表和索引之间的一致性问题；
- range read 会快很多；
- 索引可以按不同查询维度分别设计。

很多系统都使用这种思路，例如 `secondary index`、`materialized view`、search index、专门的 read model。它们共同的思想是：主存储布局只优化一种访问模式时，其他重要访问模式需要额外的数据结构来支持。

## 判断标准

简单判断可以用访问模式反推分片方式：

| 访问模式 | 更自然的设计 |
| --- | --- |
| 主要是 `key = ?` point lookup | `hash sharding` |
| 主要是 `key BETWEEN a AND b` | `range sharding` |
| 既要抗连续写入热点，又要 range query | `range partition + hash bucket` |
| 多种查询维度都重要 | 多个 `secondary index` / `materialized view` / read model / 搜索系统 |

## 小结

如果数据已经按 `hash sharding` 分布，那么原始 key 的 `range query` 本质上通常只能：

```text
scan all shards -> merge results
```

如果 range query 是重要需求，设计上通常要改成以下几类方案之一：

- 使用 `range sharding` 保留 key 顺序；
- 使用 `range partition + hash bucket` 在范围裁剪和写入分散之间折中；
- 额外维护按 range 排序的 `secondary index` / `materialized view` / read model。

关键不是问哪种 sharding 更高级，而是问：**系统最重要的访问路径是什么？** `hash sharding` 优化的是 point lookup 和负载均衡；`range sharding` 优化的是有序扫描；多个索引或 read model 则是在多个访问维度都重要时付出的复杂度成本。
