---
title: "7. Sharding：学习总结"
weight: 107
breadcrumbs: false
---

这一章只需要抓住一条主线：**sharding 是把数据集拆到多个节点上，以扩展存储容量和写吞吐量；但它会把查询、事务、索引、路由和运维都变成分布式问题。**

```text
为什么切
-> 按什么 key 切
-> key-range 还是 hash
-> 节点变化时如何 rebalance
-> hot spot 怎么处理
-> 请求怎么路由
-> secondary index 怎么办
```

## 1. 什么时候需要 Sharding

`sharding` 主要解决两个问题：

| 问题 | 是否适合 sharding | 说明 |
| --- | --- | --- |
| 数据量单机放不下 | 是 | 不同 shard 存不同数据 |
| 写吞吐量单机扛不住 | 是 | 写入分散到多个 shard |
| 读吞吐量不够 | 不一定 | 通常先考虑 `replication` 的 read scaling |
| 单机仍够用 | 通常不要 | sharding 会显著增加复杂度 |

核心判断：**sharding 是重量级方案，不是默认优化。**

它引入的主要复杂度：

- 要选 `partition key`；
- 要处理 `skew`、`hot shard`、`hot key`；
- 节点增删需要 `rebalancing`；
- 跨 shard `join`、`secondary index`、`distributed transaction` 都会变难；
- client / router 必须知道 `key -> shard -> node` 的映射。

## 2. Partition Key 是核心设计点

`partition key` 决定一条记录属于哪个 shard。

一个好的 `partition key` 不只是让数据量平均，还要让**访问负载**平均。数据平均但请求不平均，仍然会形成 hot spot。

典型坑：

- 只看数据大小，不看访问模式；
- 用单调递增 key 导致最新写入集中；
- 用会产生 celebrity / viral post 的字段做 partition key，导致 hot key。

## 3. Sharding 方法总览

| 方法 | 做法 | 优点 | 缺点 | 适用场景 |
| --- | --- | --- | --- | --- |
| `key-range sharding` | 按原始 key 的连续范围切 | range query 高效；可 split / merge | 连续写入容易 hot shard | 需要范围扫描，key 分布较可控 |
| `hash sharding` | 先 hash(key)，再映射到 shard | 分布更均匀；缓解连续 key 热点 | 破坏 key 顺序；range query 差 | 点查为主，不关心相邻 key |
| `hash modulo N` | `hash(key) % node_count` | 简单 | 节点数变化时大量 key 迁移 | 几乎只适合静态小系统 |
| 固定数量 shard | `hash(key) % shard_count`，再分配 shard 到 node | rebalance 只移动部分 shard | shard 数量一开始要估准 | 规模可预估的系统 |
| `hash-range sharding` | 按 hash value range 切 | 分布均匀，shard 数可动态变化 | 原始 key range query 差 | 不确定未来 shard 数，点查为主 |

## 4. Key-Range Sharding

`key-range sharding` 把连续 key 范围交给不同 shard。

```text
[A, C) -> shard 1
[C, H) -> shard 2
[H, Z) -> shard 3
```

**适合：** range scan、按时间或字典序查询、shard 需要动态 split 的场景。

**优势：** shard 内 key 有序，范围查询自然；数据增长后可以把大 range split。

**问题：** 如果写入集中在相邻 key，会产生 hot shard。

最典型的坑是 timestamp key：所有新写入都落到“当前时间”的 shard，旧 shard 空闲，新 shard 被打爆。

缓解方式是把更分散的字段放在前面：

```text
sensor_id + timestamp
```

代价是：按时间查所有 sensor 时，需要对多个 sensor 分别做 range query。

## 5. Hash Sharding

`hash sharding` 先对 partition key 做 hash，再用 hash value 决定 shard。

```text
key -> hash(key) -> shard
```

**适合：** 点查、按 tenant/user/key 访问、不需要保留 key 顺序的场景。

**优势：** 相似 key 也会被打散，负载通常比 key-range 更均匀。

**问题：** 原始 key 的 range query 变差；同一个 hot key 仍然只会落到一个 shard。

注意：sharding hash 不需要密码学安全，但必须 `stable`。不要直接用语言运行时内置 hash，例如 Java `Object.hashCode()` 或 Ruby `Object#hash`，它们可能跨进程或重启不稳定。

## 6. Rebalancing 方法对比

`rebalancing` 是节点增加、删除或负载变化时，重新分配 shard。

| 方法 | 怎么做 | 优点 | 坑 |
| --- | --- | --- | --- |
| key-range split / merge | 大 range 切小，小 range 合并 | shard 数随数据量变化 | split 成本高，hot shard split 更危险 |
| 固定数量 shard | shard 数固定，只调整 shard 到 node 的分配 | 添加节点只搬部分 shard | shard 数量估错会很痛 |
| hash-range split | 按 hash value range split / move | 比固定 shard 更灵活 | 原始 key range query 仍差 |
| consistent hashing | 节点变化时尽量少移动 key | 减少 rebalance 迁移量 | 只能改善 key 分布，不能消灭 hot key |

`hash(key) % N` 最大的问题是 N 变化后大量 key 归属改变；固定数量 shard 的改进是把映射拆成两层：

```text
key -> shard -> node
```

这样添加节点时，只迁移部分 shard，不需要重算所有 key 的位置。

## 7. Consistent Hashing 要点

`consistent hashing` 的“consistent”不是一致性模型里的 consistency，而是：**节点数变化前后，key 尽量保持在原来的 shard / node 上。**

它要同时满足：

1. key 大致均匀分布；
2. 节点变化时尽量少移动 key。

Cassandra / ScyllaDB 的思路是把 hash space 切成多个 ranges，每个节点持有多个 ranges。加入新节点时，只从旧节点切出部分 range 给新节点。

例如图 7-6 中，Node 3 加入后拿到：

```text
60-88    原来属于 Node 1
276-309  原来属于 Node 2
551-672  原来属于 Node 1
```

这里迁移的是满足范围条件的记录，例如：

```text
551 <= hash(key) < 672
```

不是原始 key 在 551 到 672 之间。

## 8. Skew、Hot Shard、Hot Key

几个概念：

| 概念 | 含义 |
| --- | --- |
| `skew` | 数据量或请求量分布不均 |
| `hot shard` | 某个 shard 负载明显高于其他 shard |
| `hot key` | 单个 key 请求量特别高 |

关键坑：**hash sharding 只能打散不同 key，不能打散同一个 hot key。**

缓解方式：

| 方法 | 做法 | 代价 |
| --- | --- | --- |
| 单独处理 hot key | 给 hot key 独立 shard / 专用机器 | 需要识别和迁移 hot key |
| 随机前后缀 | 把一个 logical key 拆成多个 physical keys | 读取要 fan-out 再合并 |
| 自动 hot shard 管理 | 系统自动 split / move / allocate capacity | 复杂且可能不可预测 |
| 缓存 / 预聚合 | 缓解读热点 | 一致性和失效更复杂 |

随机后缀例子：

```text
celebrity:42:comments
-> celebrity:42:comments:00
-> celebrity:42:comments:37
-> celebrity:42:comments:99
```

写入被分散到多个 physical keys；读取完整数据时要读所有 bucket 后合并。这是用 `read amplification` 换写入扩展。

## 9. 自动 vs 手动 Rebalancing

| 模式 | 做法 | 优点 | 风险 |
| --- | --- | --- | --- |
| fully automatic | 系统自动 split / move | 运维省心 | 可能误判并放大故障 |
| manual | 管理员显式调整 | 可控 | 慢，依赖人工 |
| semi-automatic | 系统建议，人工确认 | 平衡可控和自动化 | 仍需人工介入 |

自动 rebalancing 的坑：节点只是变慢，不一定真的 dead；如果系统误判并开始搬数据，会给其他节点和网络增加负载，可能引发级联故障。

## 10. Request Routing

sharding 后，请求必须被送到持有目标 shard 的节点。

三种 routing 方式：

| 方式 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| 任意节点转发 | client 连任意节点，由节点转发 | client 简单 | 多一跳，节点要知道全局映射 |
| routing layer | client 先连路由层 | client 简单，集中管理 | 路由层要高可用 |
| shard-aware client | client 直接连正确节点 | 少一跳 | client 要维护 mapping |

核心元数据：

```text
key -> shard
shard -> node
```

坑点：mapping 变化要及时传播；coordinator 要防止 split brain；shard 迁移期间旧节点上的请求要被正确处理。

## 11. Secondary Index：Local vs Global

`secondary index` 难是因为查询不一定带 partition key。

| 方案 | 做法 | 读 | 写 | 适合 |
| --- | --- | --- | --- | --- |
| `local secondary index` | 每个 shard 只索引本 shard 数据 | 不知道 partition key 时要 scatter/gather | 简单，只更新一个 shard | 写多，或查询常带 partition key |
| `global secondary index` | index 覆盖所有 shard，但 index 自己也 sharding | 单 term 查询可定位 index shard | 复杂，可能更新多个 index shards | secondary lookup 高频，读多写少 |

一句话：

```text
local index:  写便宜，读可能贵
global index: 读更直接，写和一致性更贵
```

`global secondary index` 的大坑是同步问题：如果异步更新，读 index 可能 stale；如果要求原子更新 primary data 和 index，可能需要 `distributed transaction`。

## 12. 最容易踩的坑

1. 过早 sharding：单机能扛时，不要先把复杂度引进来。
2. partition key 只看数据量，不看访问量。
3. timestamp / auto-increment ID 做 key-range sharding，导致新写入集中。
4. 用不稳定的语言内置 hash 做 sharding。
5. 直接 `hash(key) % N` 映射节点，节点数变化时代价巨大。
6. 固定 shard 数估错：太少限制扩展，太多增加管理开销。
7. 以为 hash sharding 能解决 hot key。
8. 随机后缀只分散写，读会 fan-out。
9. 自动 rebalancing 误判可能放大故障。
10. secondary index 在 sharding 后不是自动变简单，而是通常更复杂。
11. global index 要么 stale，要么写入成本高。
12. request routing 的元数据如果不可靠，会造成错误路由。

## 13. 最后一张脑图

```text
sharding
├── 目标：扩展存储和写吞吐量
├── 核心：partition key
├── 方法
│   ├── key-range：range query 好，但容易 hot shard
│   └── hash：分布均匀，但 range query 差
├── rebalancing
│   ├── split / merge
│   ├── fixed shards
│   └── consistent hashing
├── 风险
│   ├── skew / hot key
│   ├── distributed transaction
│   ├── request routing metadata
│   └── secondary index
└── 判断标准：围绕访问模式设计，而不是只围绕数据大小设计
```
