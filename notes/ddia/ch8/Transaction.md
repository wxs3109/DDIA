# Transaction

这份笔记先覆盖第 8 章从 transaction 概览到 `Materializing Conflicts` 的内容。后面的 `serializable`、`2PL`、`SSI`、`distributed transaction` 可以后续单独扩展。

这一段的主线是：**transaction 试图把 crash、partial failure、并发读写这些复杂问题包装成一个更好推理的编程模型；但弱隔离级别只挡住一部分异常，应用仍然要知道自己依赖的 invariant 会不会被并发破坏。**

```text
transaction programming model
-> ACID
-> single-object / multi-object transaction
-> read committed
-> snapshot isolation / MVCC
-> lost update
-> write skew / phantom read
-> materializing conflicts
```

## 1. Transaction 到底提供什么抽象

`transaction` 的理想效果是：把一组读写操作当成一个 logical unit。应用可以假装这组操作要么完整发生，要么完全没发生；并发 transaction 之间不会看到彼此不该看到的中间状态。

但现实里，`ACID` 这几个词并不是同等精确：

| 属性 | 重点 | 容易误解的地方 |
| --- | --- | --- |
| `Atomicity` | 出错时能 abort，撤销本 transaction 已做的 writes | 不是 concurrent programming 里的 atomic operation；这里重点是 failure handling |
| `Consistency` | 应用定义的 invariant 在 transaction 前后成立 | 主要是应用责任，不是数据库单独能保证的属性 |
| `Isolation` | 并发 transaction 彼此隔离，避免 race condition | 不同 isolation level 差异很大，很多数据库默认不是 serializable |
| `Durability` | commit 后的数据不会轻易丢 | 依赖 storage、replication、fsync、backup 等机制，没有绝对保证 |

最容易混的是 `atomicity` 和 `isolation`：

- `atomicity` 问的是：**如果中途失败，已经做了一半的修改怎么办？**
- `isolation` 问的是：**如果别人同时读写，会不会看到不一致状态或破坏业务规则？**

## 2. Single-Object 与 Multi-Object Transaction

很多数据库即使不支持完整 transaction，也至少支持单对象级别的 atomic write。例如更新一个 document、写入一行、给某个字段做 atomic increment。

但很多真实业务 invariant 跨越多个 object：

- 邮件系统中，新邮件和 unread counter 要同步；
- secondary index 要和 primary record 同步；
- denormalized data 的 canonical copy 和多个 derived copy 要同步；
- 一个业务操作可能要改多张表、多行或多个 document。

这就是 `multi-object transaction` 的价值：它把一组跨对象修改绑定成一个 commit/abort 单元。

> [!CAUTION] Wenbo 注
> document database 不是天然不需要 transaction。只有当 invariant 被限制在单个 document 内时，single-object operation 才够用。一旦为了 query performance 做 denormalization，或者业务规则跨 document，问题就回到了 multi-object transaction。

## 3. Error 和 Abort：abort 不是异常终点，而是 retry 入口

transaction abort 的意义是：数据库发现冲突、故障或约束违反时，可以放弃当前 transaction，让应用从干净状态重新来。

所以应用要区分两类错误：

| 错误类型 | 典型处理 |
| --- | --- |
| transient conflict / deadlock / serialization failure | retry whole transaction |
| constraint violation / bad input / business rejection | 返回错误，不 retry |

很多 ORM 或应用框架只把 abort 变成 exception 往外抛，这会浪费 transaction 的一个关键设计点：**safe retry**。不过 retry 也必须谨慎，尤其当 transaction 之外还有外部 side effect，例如发送 email、调用支付 API、发消息到 queue。

## 4. Read Committed：挡住 dirty read / dirty write，但不挡住很多 race

`read committed` 通常保证两件事：

1. `No dirty read`：只能读到已经 commit 的数据，不能读到别人未提交的 write。
2. `No dirty write`：不能覆盖别人尚未 commit 的 write。

它解决的是“不要看到或覆盖未提交的中间状态”。

但 `read committed` 不保证同一个 transaction 多次读取同一数据会得到相同结果，也不防止 `lost update`。比如两个 client 都读到 counter = 42，各自计算 43，然后先后写回 43，最后结果还是 43，而不是 44。

所以 read committed 的边界可以记成：

```text
防 dirty read
防 dirty write
不防 read skew
不防 lost update
不防 write skew
不保证 repeatable read
```

## 5. Snapshot Isolation / MVCC：读的是一致快照，不是最新世界

`snapshot isolation` 的目标是：一个 transaction 中的所有 reads 都基于同一个时间点的 database snapshot。这样可以避免 `read skew`：不会前一条 query 看到旧账户余额，后一条 query 看到新账户余额，导致总额不一致。

`MVCC` 是实现 snapshot isolation 的常见方式。核心思路是：一行数据可以同时保留多个 committed version，不同 transaction 根据自己的 snapshot 看到不同版本。

可见性大致可以这样理解：

```text
transaction start 时确定一个 snapshot
-> 只看当时已经 commit 的 versions
-> 忽略当时尚未 commit 或之后才 commit 的 versions
-> update 通常表现为 old version marked deleted + new version inserted
```

这里最容易混淆的是：

- snapshot isolation 的 read 不一定读最新 committed value；它读的是 transaction 开始时的一致快照。
- SQL 标准里的 `repeatable read` 和实际数据库里的名字不完全一致。
- PostgreSQL 的 `repeatable read` 接近 snapshot isolation；MySQL/InnoDB 的 `repeatable read` 行为又不完全一样。
- Oracle 的 `serializable` 实际更接近 snapshot isolation，而不是真正 serializable。

所以不要只看 isolation level 名字，要看它具体防哪些 anomaly。

## 6. Lost Update：同一 object 的 read-modify-write 被覆盖

`lost update` 出现在 read-modify-write cycle：

```text
read old value
-> application modifies value
-> write new value back
```

如果两个 transaction 同时基于同一个 old value 计算，后写入者可能覆盖先写入者的结果。

典型场景：

- counter increment；
- account balance update；
- 修改 JSON document 中的 list；
- 两个用户同时编辑 wiki 页面并提交整页内容。

防止 lost update 的方式：

| 方法 | 思路 | 适合场景 |
| --- | --- | --- |
| atomic write | 让数据库直接执行 `value = value + 1` | counter、balance 等简单表达式 |
| explicit locking | `SELECT ... FOR UPDATE` 锁住要修改的 row | 修改前需要应用逻辑检查 |
| automatic detection | 数据库发现 lost update 后 abort 一个 transaction | 依赖具体数据库和 isolation level |
| conditional write / CAS | `WHERE version = old_version`，不匹配就失败 | Web 表单、wiki 编辑、optimistic locking |

### Wiki 编辑里的 version check

A 和 B 同时打开 wiki 页面，看到的都是 `version = 1`。B 先保存，把 version 改成 `2`。A 后保存时，如果只是：

```sql
UPDATE wiki_pages
SET content = 'A edited content'
WHERE id = 1234;
```

A 会覆盖 B 的修改。

正确做法是把 A 当初读到的 version 带回来：

```sql
UPDATE wiki_pages
SET content = 'A edited content', version = version + 1
WHERE id = 1234 AND version = 1;
```

如果 B 已经提交，数据库里的 version 是 `2`，这条 update 影响 0 行。应用就知道 A 基于旧版本编辑，需要 retry、提示 merge，或让用户确认覆盖。

注意：真实 Web 编辑通常不会从用户打开页面到保存期间一直持有数据库 transaction，因为用户可能编辑很久。更常见的是打开时读出 `version`，保存时做 conditional update。

## 7. ORM 的坑：SaveChanges 不等于防 lost update

ORM 很容易生成 unsafe read-modify-write：先把 entity 读到应用内存，在应用代码中修改字段，然后 `SaveChanges()` 写回。

以 EF/EF Core 为例：

```csharp
var counter = db.Counters.Single(c => c.Id == id);
counter.Value++;
await db.SaveChangesAsync();
```

这类代码常常生成的是“把应用算出的新值写回去”，而不是数据库侧的 atomic increment。

要避免问题，可以考虑：

- 使用数据库侧 atomic update，例如 EF Core 7+ `ExecuteUpdate`；
- 配置 optimistic concurrency token，例如 SQL Server `rowversion` / `[Timestamp]`；
- 冲突时捕获 `DbUpdateConcurrencyException` 并 retry；
- 对复杂逻辑使用 transaction + explicit lock；
- 必要时提高 isolation level。

`SaveChanges()` 自带 transaction 只保证这一批写入原子提交，不自动保证不会 lost update。

## 8. Write Skew：不是改同一行，而是共同破坏一个跨 row invariant

`write skew` 比 lost update 更隐蔽。它不是两个 transaction 同时写同一 object，而是：两个 transaction 读取同一组数据，各自基于这个全局判断修改不同 object，最后合起来破坏 invariant。

医生值班例子：

```text
invariant: 至少 1 个医生 on_call
初始状态: Aaliyah = on_call, Bryce = on_call
```

Aaliyah 的 transaction 看到有 2 个医生值班，于是把自己改成 off_call。

Bryce 的 transaction 也在自己的 snapshot 里看到有 2 个医生值班，于是也把自己改成 off_call。

两个 transaction 写的是不同 row，所以数据库不认为发生了同一行覆盖；但最终结果是 0 个医生值班，业务 invariant 被破坏。

这和 lost update 的区别：

| 异常 | 读什么 | 写什么 | 问题 |
| --- | --- | --- | --- |
| lost update | 同一个 object 的旧值 | 同一个 object | 后写覆盖先写 |
| write skew | 同一组 object / predicate 的整体状态 | 不同 object | 每个局部写都合法，组合后破坏 invariant |

如果两个医生请假操作 serially 执行，就不会出错：第一个医生下班后，第二个医生再检查会看到只剩 1 个医生，因此不能下班。write skew 只有在并发执行时出现。

## 9. Phantom Read：查询结果集合被另一个 transaction 改变

`phantom read` 指一个 transaction 的 write 改变了另一个 transaction 中 search query 的结果集合。

很多 write skew 场景都遵循这个模式：

1. 先查询是否满足条件。
2. 应用根据查询结果决定是否继续。
3. 如果继续，就写入数据。
4. 这个写入改变了其他 transaction 做同样查询时应该看到的结果。

例子：

- 会议室预订：检查某房间某时间段没有冲突预订，然后插入预订。
- 用户名注册：检查用户名不存在，然后插入用户。
- 防止透支：检查账户项目总和仍为正，然后插入新的支出项。
- 多人游戏：检查某个位置没有棋子，然后把棋子移动过去。

难点在于：如果第一步查询的是“不存在匹配行”，那么 `SELECT ... FOR UPDATE` 可能没有 row 可以锁。没有 row，就没有具体对象可挂锁，于是并发 insert 可能制造出新的 matching row。

## 10. Materializing Conflicts：把抽象冲突变成可锁的 row

`materializing conflicts` 的思路是：如果 phantom read 的问题是“没有对象可以锁”，那就人为创建一些 lock object。

会议室预订例子：提前创建一张 `room_time_slots` 表，每个 room + time slot 对应一行。预订前先锁定对应时间段的 slot rows：

```sql
SELECT * FROM room_time_slots
WHERE room_id = 123
  AND slot_start >= '2025-01-01 12:00'
  AND slot_start < '2025-01-01 13:00'
FOR UPDATE;
```

锁住这些 row 后，再检查是否有重叠预订并插入 booking。

这个方法的本质是：

```text
原本冲突发生在“查询条件 / predicate”上
-> 数据库没有具体 row 可锁
-> 人为创建代表 predicate 的 rows
-> 把 predicate conflict 转成 row lock conflict
```

它能工作，但很丑，也容易出错：

- application data model 被 concurrency control 污染；
- 要设计合适粒度的 lock rows；
- 粒度太粗会降低并发，粒度太细又可能漏锁；
- 很多业务 predicate 很难 materialize。

所以它通常是 last resort。更自然的方案是使用真正的 `serializable isolation`，或者用数据库能直接 enforce 的 constraint。

## 11. 易混淆点速查

| 概念 | 不是 | 是 |
| --- | --- | --- |
| `atomicity` | 并发里的 atomic increment | transaction 失败时 all-or-nothing abort |
| `consistency` | 数据库自动知道所有业务规则 | 应用定义 invariant，数据库提供工具帮助维护 |
| `read committed` | 每次读都一致、不会并发出错 | 只保证不读未提交、不写未提交 |
| `snapshot isolation` | 读最新数据 | 读 transaction 开始时的一致快照 |
| `repeatable read` | 所有数据库含义一致 | 名字高度混乱，要看实现 |
| `lost update` | 所有并发写问题 | 同一 object 的 read-modify-write 被覆盖 |
| `write skew` | lost update 的同义词 | 不同 row 的写共同破坏跨 row invariant |
| `phantom read` | 普通重复读变了 | search query 的匹配集合被并发 write 改变 |
| `SELECT FOR UPDATE` | 万能防并发 | 只能锁实际返回的 rows；不存在的 rows 锁不到 |
| `materializing conflicts` | 业务建模技巧 | 为了锁 predicate，人为创建 lock rows |

## 12. 一个判断框架

看到一个并发业务规则时，可以按这个顺序问：

1. 这个 invariant 是单 object 内的，还是跨多个 objects？
2. 是否是简单数值/集合更新，可以用 atomic operation 表达？
3. 是否所有冲突都落在同一 row 上，可以用 optimistic locking 或 `SELECT FOR UPDATE`？
4. 是否依赖“不存在某些 row”这种 predicate？如果是，小心 phantom read。
5. 数据库当前 isolation level 是否真的防这个 anomaly？不要只看名字。
6. 能否用 unique constraint、foreign key、check、trigger、materialized view 等让数据库 enforce？
7. 如果都不行，是不是需要 serializable isolation，或者 last resort 的 materializing conflicts？

一句话总结：**transaction 不是“开了就安全”的魔法。你要知道自己的业务规则依赖哪些 rows/predicates，以及当前 isolation level 是否会在并发下保护这些依赖。**
