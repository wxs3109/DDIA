# Chapter 6 Replication

## 这章当前的阅读边界

这份笔记目前只覆盖 **`multi-leader replication` 之前** 的内容，可以先把它当成：

- `6.1 single-leader replication`
- `6.2 multi-leader replication`：明天继续
- `6.3 leaderless replication`：明天继续

这一章在当前阶段有一个很重要的前提：**先不讨论 `sharding`**。作者假设整个数据集小到每个节点都能放下，因此这一章先关注的是：**同一份完整数据，如何在多个节点上保留多个 `replica`**。到下一章才会转去讲 `sharding / partitioning`，也就是“不同机器只存数据的一部分”。

## 6.1 Single-Leader Replication

### 主线：一份数据如何从 leader 传播到 follower

`single-leader replication` 的基本结构很简单：

1. 一个节点是 `leader`，负责接收写入。
2. 其他节点是 `follower`，负责追上 leader。
3. 读取可以打到 leader，也可以打到 follower。

真正困难的地方不在这个结构本身，而在它后面立刻带出来的一串问题：

- `replication` 是 `synchronous` 还是 `asynchronous`
- 新 `follower` 怎么初始化
- 节点故障后怎么 `failover`
- `leader` 到底要把什么内容发给 `follower`
- 如果 `follower` 落后，读取会出现什么异常

所以这一部分不是在反复讲“leader/follower 是什么”，而是在讲：**只要你接受“写入集中到 leader，再把变更传播给 follower”这个架构，你就必须面对哪些 trade-off。**

### Synchronous vs Asynchronous Replication

这里的第一层取舍是：`leader` 在写入后，要不要等 `follower` 确认。

- `synchronous replication`：leader 要等 follower 确认后，才向客户端返回成功。
- `asynchronous replication`：leader 先向客户端返回成功，再慢慢把变更发给 follower。

`sync` 的好处是 durability 更强：如果 leader 立刻挂掉，最新写入更可能已经在其他副本上。

`async` 的好处是性能和 availability 更好：leader 不会因为某个 follower 慢、挂掉、网络抖动而阻塞写入。

这部分最核心的判断不是“哪种更先进”，而是：

**你要在 latency / availability 和 durability 之间做取舍。**

很多系统现实里用的是 `semi-synchronous`：至少等一个 follower，其他 follower 异步追。

### 新 Follower 怎么追上 Leader

新 follower 不能直接粗暴复制数据文件，因为数据库在持续写入，文件会处在一个不一致的中间状态。

初始化一个 follower 的标准流程是两段：

1. 先拿一个一致性的 `snapshot`
2. 再从某个精确的 log position 开始追后续增量

所以这里一定要把两个东西分开：

- `snapshot`：某个时刻的完整状态
- `replication log`：从这个状态之后发生的变更

可以把它记成：

```text
全量初始化（snapshot） + 增量追平（replication log）
```

真正关键的是：`snapshot` 必须和某个精确的 log position 绑定。例如 `LSN`、`binlog coordinates`、`GTID`。否则 follower 不知道自己该从哪里继续追，容易漏变更或重复应用变更。

#### `snapshot` 和 `replication log` 的关系

这两个东西最好不要混在一起理解。它们不是同一种数据，而是**同一套恢复流程里的两个部分**：

- `snapshot` 回答的是：**某个时刻系统长什么样**
- `replication log` 回答的是：**从那个时刻之后系统又发生了哪些变化**

所以可以把它想成一张照片加上一段之后的监控录像：

- 照片给你一个完整起点
- 录像告诉你从这个起点之后又发生了什么

如果只有 `snapshot`，你只能恢复到拍照那一刻；如果只有 `replication log`，你又缺少一个可靠起点，不知道应该从什么状态开始重放。

因此，新 follower 的正确初始化不是二选一，而是把两者拼起来：

```text
snapshot 提供起点状态
+ replication log 提供后续增量
= follower 追上 leader 的当前状态
```

这里最关键的不是“我拿到了 snapshot”，而是：**这个 snapshot 对应 leader 的哪个 log position**。只有把两者对齐，follower 才知道后续应该从哪条 log 开始追。

#### `snapshot` 到底长什么样，怎么保存和传输

`snapshot` 不一定是某种统一格式的“特殊文件”。更准确地说，它通常是：**足以把数据库恢复到某个时间点状态的一整份数据副本**。具体长什么样，取决于数据库实现。

常见形式有几种：

1. **数据文件副本**  
	对很多数据库来说，`snapshot` 本质上就是某个时刻的数据目录副本，例如表文件、索引文件、元数据文件的集合。也就是说，它看起来更像“把数据库磁盘上的那套文件在一致性时刻打了一个包”。
2. **逻辑导出结果**  
	有些系统也可以把 `snapshot` 做成逻辑层导出，例如某个时刻的表数据 dump。但这种方式更常见于备份、迁移，不一定是最高效的 replication 初始化方式。
3. **对象存储里的备份快照**  
	在现代云数据库或备份体系里，`snapshot` 也可能已经提前被保存到对象存储中，例如一组备份分片文件、checkpoint 文件、manifest 文件等。新 follower 不一定非要现场从 leader 拷贝，也可以直接从备份仓库下载。

所以你可以把 `snapshot` 理解成：**“一组能还原出时刻 $T$ 完整状态的数据文件或数据导出”**，而不必把它想成单个神秘的 `.snapshot` 文件。

它的保存和传输方式也通常很朴素：

1. 在 leader 上生成一致性快照。
2. 把这组文件写到本地磁盘、备份系统或对象存储。
3. 新 follower 通过网络把这些文件拷过去，或者直接从对象存储下载。
4. follower 在本地把这份 snapshot 放到自己的数据目录里，再从对应的 log position 开始追增量。

所以“传输 snapshot”通常不是传一条消息，而是**复制一整批文件**。它可能通过数据库自带工具完成，也可能通过备份工具、rsync 风格文件复制、对象存储下载来完成。

这里真正难的不是“怎么传”，而是**怎么保证你拿到的是一个一致时刻的完整副本，并且知道它对应哪个 log position**。只要这两个条件满足，snapshot 的具体物理包装形式反而不是最重要的。

### Failover 的本质

`leader` 挂掉时，系统要做 `failover`：

1. 认定 leader 已失效
2. 选一个 follower 升为新 leader
3. 让客户端和其他 follower 改为跟随新 leader

这里最容易误解的是：**failover 不是“找回所有数据”**，而是“在幸存副本里挑一个最接近旧 leader 的来接班”。

如果旧 leader 上有一部分写入还没复制到任何 follower，那么旧 leader 一旦失效，这部分写入就不在集群里了。新 leader 不可能凭空把它变出来。

所以在 `asynchronous replication` 下：

- 客户端收到“写成功”
- 不等于这条写入一定已经安全存在于其他副本

这也是为什么 failover 会和 durability 绑定在一起讨论。

### Replication 到底复制什么

这一部分是本章很重要的一层：不同 replication method 的差别，不只是实现细节，而是系统能力边界的差别。

#### 1. Statement-Based Replication

复制的是 SQL `statement`，也就是“leader 执行了什么命令”。

follower 需要自己重新执行：

- `INSERT`
- `UPDATE`
- `DELETE`

这种方法的问题在于：**复制的是“做法”，不是“结果”。**

因此它要求同一条语句在每个副本上重放时，都得到相同结果。但现实里很多东西会破坏这个前提：

- `NOW()`、`RAND()` 这类非确定性函数
- 自增 ID
- `UPDATE ... WHERE ...` 对当前状态的依赖
- 触发器、存储过程、UDF 的副作用

所以 `statement-based replication` 最脆弱的点在于：**高层操作的重放很容易不确定。**

#### 2. WAL Shipping

复制的是存储引擎的 `WAL`，也就是底层物理变更。

这里要分两层：

- 本地写 `WAL`：解决单机 crash recovery
- 把 `WAL` 发给 follower：解决 follower 怎么追上 leader

如果目标是让 follower 尽可能精确地同步 leader，`WAL shipping` 的优势很明显：它复制的不是高层命令，而是 leader 已经产出的底层变更。所以 follower 不需要自己再重新计算 `NOW()`、自增 ID、命中哪些行等问题。

但 `WAL shipping` 也有代价：它和存储引擎内部格式耦合很深。因此：

- 不容易跨版本复制
- leader / follower 往往要跑相近版本
- 外部系统也不容易直接消费这种日志

还要特别分清：

**WAL 解决的是“复制什么”，不自动解决“什么时候才算 durable”。**

如果 leader 只是把 WAL 写到自己本地，还没发到 follower 就返回成功，然后立刻宕机，那么这条写入仍然可能在 failover 后丢失。这件事取决于 `sync` / `async` 策略，不取决于日志是不是 WAL。

#### 3. Logical (Row-Based) Log Replication

复制的是“表里的哪一行变成了什么样”。

例如一张 `users(id, name, city)` 表：

- 插入：记录新行的值
- 更新：记录哪一行被改，以及改成什么
- 删除：记录哪一行被删

它不像 `WAL` 那样记录哪个磁盘页、哪些字节被改，而是记录更高层、面向表和行的变化。

这带来两个直接好处：

1. 更容易跨版本复制，因为它和存储引擎内部格式解耦
2. 更容易给外部系统消费，例如 `CDC`、cache、自定义索引、数据仓库

所以可以把三种方式粗略记成：

- `statement-based`：复制“怎么做”
- `WAL shipping`：复制“底层实际改了什么”
- `logical row-based`：复制“哪张表的哪一行变成了什么”

### Replication Lag 带来的读一致性问题

只要 follower 是异步追 leader，就可能出现：**写成功了，但读到的还是旧世界。**

作者在这里用三个例子说明 replication lag 会导致什么异常。

#### 1. Read-After-Write / Read-Your-Writes

用户刚写完，马上去读，却读到了一个还没追平的 follower，于是看不到自己刚刚写入的内容。

这不是数据真的丢了，而是：

- leader 已经返回成功
- follower 还没追上
- 读取被路由到了 stale replica

这个问题的核心不是“所有读都走 leader”，而是：**把一致性要求更高的那部分读取单独识别出来。**

可以按不同标准做区分：

- 按对象区分：自己的 profile 走 leader，别人的走 follower
- 按时间窗口区分：刚写完的一小段时间内走 leader
- 按 lag 区分：只把读发给足够新的 replica
- 按用户最近写入位置区分：只发给已经追到某个 timestamp / LSN 的 replica

#### 2. Monotonic Reads

用户第一次从较新的 follower 读到了某条数据，第二次又被路由到更旧的 follower，于是先看到新值，后又看到旧值，像时间倒退一样。

`monotonic reads` 的目标不是保证每次都读到最新值，而是保证：**同一用户连续读取时，不会先看到更新版本，后又看到更旧版本。**

一种常见做法是让同一个用户尽量固定读同一个 replica。

#### 3. Consistent Prefix Reads

这类异常涉及 `causality`：本来应该按顺序出现的写入，被用户看到时顺序乱了。

经典例子是：先看到回答，后看到问题。

这说明系统不是单纯“旧一点”而已，而是**读到了一个违反因果顺序的前缀**。

这个问题在 `sharding` 下更容易出现，因为不同 shard 的复制进度可能不一样。

### Strong Consistency vs Eventual Consistency

这两个词很容易被说得很模糊，这里我先把它们压成这几个判断。

#### Strong Consistency

可以先粗略理解成：**系统读起来更像只有一个最新副本存在。**

也就是说，读请求不会明显看到“过期世界”。对于 `single-leader` 架构来说：

- 从 leader 读
- 或从已经同步确认过的副本读

更接近这种体验。

#### Eventual Consistency

`eventual consistency` 不是说“系统经常错”，而是说：

**副本在某个时刻可以暂时不一致，但如果停止写入并等待足够久，它们最终会收敛。**

最关键的不是“最终会一致”这句话本身，而是：

**这个“最终”没有严格时间上界。**

所以 follower 可能只落后几毫秒，也可能落后几秒、几分钟，甚至在系统承压时更久。

### 这一段真正的 Trade-Off

如果把这部分压成一句最重要的话，就是：

**你越想让读取表现得像 `strong consistency`，就越要限制读取只能走 leader 或足够新的 replica；你越想把读取自由地下放给大量 follower 做扩展，就越要接受某些读取只能拿到 `eventual consistency`。**

也就是说，这里不是“数据库理论名词”问题，而是很实际的系统设计取舍：

- 要更多 read scaling
- 还是要更强的 read guarantees
- 要更低 latency
- 还是要更强 durability

这些目标往往不能同时最大化。

## 6.2 Multi-Leader Replication

明天继续。先预留一个框架：

- 为什么 single-leader 不够
- 为什么会想让多个节点都接收写入
- 多个 leader 带来的写冲突、拓扑、跨 region 问题

## 6.3 Leaderless Replication

明天继续。先预留一个框架：

- 不依赖 leader 时，写入怎么被接受
- `quorum`、`read repair`、`hinted handoff` 怎么工作
- 它为什么更能容忍某些故障，但也更容易带来弱一致性
