# DDIA Technical Terms Reference

English terms to use as direct replacements for Chinese translations.

## Sharding & Partitioning (Ch7)

| Chinese | English |
|---------|---------|
| 分片 | shard / sharding |
| 分区 | partition / partitioning |
| 分区键 | partition key |
| 再平衡 / 再分片 | rebalancing / re-sharding |
| 热点 | hot spot |
| 热分片 | hot shard |
| 热键 | hot key |
| 偏斜 | skew |
| 一致性哈希 | consistent hashing |
| 会合哈希 | rendezvous hashing |
| 跳跃一致性哈希 | jump consistent hashing |
| 流言协议 | gossip protocol |
| 分散/收集 | scatter/gather |
| 词项 | term |
| 基于词项分区 | term-partitioned |
| 预分割 | pre-splitting |
| 虚节点 | vnode |
| 本地索引 | local index |
| 全局索引 | global index |
| 倒排列表 | inverted list |
| 协调器 | coordinator |
| 二级索引 | secondary index |
| 基于单元的架构 | cell-based architecture |
| 连接 | join |

## Transactions & Concurrency Control (Ch8)

| Chinese | English |
|---------|---------|
| 脏读 | dirty read |
| 脏写 | dirty write |
| 读取偏差 | read skew |
| 写偏差 | write skew |
| 幻读 | phantom read |
| 不可重复读 | non-repeatable read |
| 丢失更新 | lost update |
| 级联中止 | cascading abort |
| 读已提交 | read committed |
| 读未提交 | read uncommitted |
| 快照隔离 | snapshot isolation |
| 可重复读 | repeatable read |
| 可串行化 | serializable / serializability |
| 可串行化快照隔离 | serializable snapshot isolation (SSI) |
| 多版本并发控制 | MVCC / multi-version concurrency control (MVCC) |
| 两阶段锁定 | two-phase locking (2PL) |
| 两阶段提交 | two-phase commit (2PC) |
| 谓词锁 | predicate lock / predicate locking |
| 索引范围锁 | index-range lock / index-range locking |
| 死锁 | deadlock |
| 物化冲突 | materializing conflicts |
| 悲观 | pessimistic |
| 乐观 | optimistic |
| 恰好一次 | exactly-once |
| 启发式决策 / 启发式 | heuristic decision / heuristic |
| 条件写入 | conditional write |
| 提交点 | commit point |
| 参与者 | participant |
| 原子提交 | atomic commit |
| 存疑 | in-doubt |
| 协调器 | coordinator |
| 存储过程 | stored procedure |
