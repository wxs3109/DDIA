---
title: "8. Transactions（事务）"
weight: 208
math: true
breadcrumbs: false
---

<a id="ch_transactions"></a>

<img src="../../static/map/ch08.png" alt="章节导图" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

> *有些作者声称，支持通用的 two-phase commit 代价太大，会带来 performance 和 availability 的问题。我们认为，让程序员处理过度使用 transactions 带来的 performance 问题，总比没有 transaction 编程模型要好得多。*
>
> James Corbett 等人，*Spanner：Google 的全球分布式数据库*（2012）

在数据系统的残酷现实中，很多事情都可能出错：

* 数据库软件或硬件可能在任意时刻发生故障（包括写操作进行到一半时）。
* 应用程序可能在任意时刻崩溃（包括一系列操作的中间）。
* 网络中断可能会意外切断应用程序与数据库的连接，或数据库节点之间的连接。
* 多个 client 可能会同时 write 数据库，覆盖彼此的 change。
* client 可能读取到无意义的数据，因为数据只 update 了一部分。
* client 之间的 race condition 可能导致令人惊讶的 error。

为了实现可靠性，系统必须处理这些故障，确保它们不会导致整个系统的灾难性故障。然而，实现容错机制需要大量工作。它需要仔细考虑所有可能出错的事情，并进行大量测试，以确保解决方案真正有效。

数十年来，*transaction*（事务）一直是简化这些问题的首选机制。transaction 是应用程序将多个 read/write 操作组合成一个 logical unit 的方式。从概念上讲，transaction 中的所有 read/write 操作被视作单个操作来执行：整个 transaction 要么成功（*commit*），要么失败（*abort* / *rollback*）。如果失败，应用程序可以安全地重试。对于 transaction 来说，应用程序的错误处理变得简单多了，因为它不用再担心 partial failure：某些操作成功、某些失败，无论原因是什么。

如果你与 transaction 打交道多年，它们可能看起来显而易见，但我们不应该将其视为理所当然。transaction 不是自然法则；它们是有目的地创建的，即为了*简化应用程序的 programming model*。通过使用 transaction，应用程序可以忽略某些潜在的错误场景和 concurrency 问题，因为数据库会替应用处理好这些（我们称之为 *safety guarantees*）。

并非所有应用程序都需要 transaction，有时弱化 transaction guarantees 或完全放弃 transaction 也有好处，例如为了获得更高 performance 或更高 availability。某些 safety properties 可以在没有 transaction 的情况下实现。另一方面，transaction 可以防止很多麻烦：例如，邮局 Horizon 丑闻（参见["可靠性有多重要？"](/ch2#sidebar_reliability_importance)）背后的技术原因可能是底层会计系统缺乏 ACID transactions[^1]。

你如何确定是否需要 transaction？为了回答这个问题，我们首先需要准确理解 transaction 可以提供哪些 safety guarantees，以及相关的 cost。尽管 transaction 乍看起来很简单，但实际上有许多细微但重要的细节在起作用。

在本章中，我们将研究许多可能出错的案例，并探索数据库用于防范这些问题的算法。我们将特别深入 concurrency control，讨论可能发生的各种 race condition，以及数据库如何实现 *read committed*、*snapshot isolation* 和 *serializable* 等 isolation levels。

concurrency control 对单节点和 distributed database 都很重要。在本章后面的["分布式事务"](#sec_transactions_distributed)部分，我们将研究 *two-phase commit* 协议，以及在 distributed transaction 中实现 atomicity 的挑战。

## Transaction 到底是什么？ {#sec_transactions_overview}

今天，几乎所有的关系型数据库和一些非关系数据库都支持事务。它们大多遵循 1975 年由 IBM System R（第一个 SQL 数据库）引入的风格[^2] [^3] [^4]。尽管一些实现细节发生了变化，但总体思路在 50 年里几乎保持不变：MySQL、PostgreSQL、Oracle、SQL Server 等的事务支持与 System R 惊人地相似。

在 2000 年代后期，非关系（NoSQL）数据库开始流行起来。它们旨在通过提供新的数据模型选择（参见[第 3 章](/ch3#ch_datamodels)），以及默认包含复制（[第 6 章](/ch6#ch_replication)）和分片（[第 7 章](/ch7#ch_sharding)）来改进关系型数据库的现状。事务是这一运动的主要牺牲品：许多这一代数据库完全放弃了事务，或者重新定义了这个词，用来描述比以前理解的更弱的保证集。

围绕 NoSQL distributed database 的炒作导致了一种流行信念：transaction 从根本上不具备 scalability，任何大规模系统都必须放弃 transaction 以保持良好的 performance 和 high availability。最近，这种信念被证明是错误的。所谓 "NewSQL" 数据库，如 CockroachDB[^5]、TiDB[^6]、Spanner[^7]、FoundationDB[^8] 和 YugabyteDB 已经证明，transactional system 同样可以具备很强的 scalability，并支持大数据量与高 throughput。这些系统将 sharding 与 consensus protocol（[第 10 章](/ch10#ch_consistency)）结合，在大规模下提供强 ACID guarantees。

然而，这并不意味着每个系统都必须是事务型的：与任何其他技术设计选择一样，事务有优点也有局限性。为了理解这些权衡，让我们深入了解事务可以提供的保证的细节——无论是在正常操作中还是在各种极端（但现实）的情况下。

### ACID 的含义 {#sec_transactions_acid}

transaction 提供的 safety guarantees 通常由著名 acronym *ACID* 来描述：*Atomicity*（原子性）、*Consistency*（一致性）、*Isolation*（隔离性）和 *Durability*（持久性）。它由 Theo Härder 和 Andreas Reuter 于 1983 年提出[^9]，旨在为数据库中的 fault-tolerance 机制建立精确术语。

然而，在实践中，一个数据库的 ACID 实现并不等同于另一个数据库的实现。例如，正如我们将看到的，*Isolation* 的含义有很多歧义[^10]。高层次的想法是合理的，但魔鬼在细节中。今天，当一个系统声称自己"符合 ACID"时，实际上你能期待什么 guarantee 并不清楚。不幸的是，ACID 基本上已经成为了一个营销术语。

（不符合 ACID 标准的系统有时被称为 *BASE*，它代表 *Basically Available*（基本可用）、*Soft state*（软状态）和 *Eventual consistency*（最终一致性）[^11]。这比 ACID 的定义更加模糊。似乎 BASE 唯一合理的定义是"非 ACID"；也就是说，它几乎可以代表任何你想要的东西。）

让我们深入了解 atomicity、consistency、isolation 和 durability 的定义，这将让我们提炼出 transaction 的思想。

#### Atomicity（原子性） {#sec_transactions_acid_atomicity}

一般来说，*原子*是指不能分解成更小部分的东西。这个词在计算机的不同分支中意味着相似但又微妙不同的东西。例如，在多线程编程中，如果一个线程执行原子操作，这意味着另一个线程无法看到该操作的半完成结果。系统只能处于操作之前或操作之后的状态，而不是介于两者之间。

相比之下，在 ACID 的上下文中，atomicity *不是*关于 concurrency 的。它不描述如果几个进程试图同时访问相同的数据会发生什么，因为这包含在字母 *I*（*Isolation*）中（参见["Isolation（隔离性）"](#sec_transactions_acid_isolation)）。

相反，ACID atomicity 描述的是：当客户端想要进行多次 write，但在某些 write 被处理后发生故障时会发生什么。例如，进程崩溃、网络连接中断、磁盘变满，或者违反了某些 integrity constraints。如果这些 write 被分组到一个 atomic transaction 中，并且由于故障无法完成（*commit*）transaction，则 transaction 被 *abort*，数据库必须丢弃或撤消该 transaction 中迄今为止所做的任何 write。

如果没有 atomicity，当进行多处 change 的中途发生错误时，很难知道哪些 change 已经生效、哪些没有。应用程序可以重试，但这有重复执行同一 change 的风险，导致数据重复或错误。atomicity 简化了这个问题：如果 transaction 被 abort，应用程序可以确定它没有改变任何东西，因此可以安全地重试。

在错误时 abort transaction 并丢弃该 transaction 的所有 write 的能力，是 ACID atomicity 的定义特征。也许 *abortability*（可中止性）比 *atomicity* 更准确，但我们仍然使用 *atomicity*，因为这是常用术语。

#### Consistency（一致性） {#sec_transactions_acid_consistency}

*Consistency* 这个词被严重重载：

* 在[第 6 章](/ch6#ch_replication)中，我们讨论了 *replica consistency* 和异步复制系统中出现的 *eventual consistency* 问题（参见["复制延迟的问题"](/ch6#sec_replication_lag)）。
* 数据库的 *consistent snapshot*（例如，用于 backup）是整个数据库在某一时刻存在的 snapshot。更准确地说，它与 *happens-before relation* 一致（参见["“先发生”关系和并发"](/ch6#sec_replication_happens_before)）：也就是说，如果 snapshot 包含在特定时间写入的值，那么它也反映了在该值写入之前发生的所有 write。
* *Consistent hashing* 是某些系统用于 rebalancing 的 sharding 方法（参见["一致性哈希"](/ch7#sec_sharding_consistent_hashing)）。
* 在 CAP theorem 中（参见[第 10 章](/ch10#ch_consistency)），*consistency* 一词用于表示 *linearizability*（参见["线性一致性"](/ch10#sec_consistency_linearizability)）。
* 在 ACID 的上下文中，*consistency* 是指应用程序特定的数据库处于"良好状态"的概念。

不幸的是，同一个词至少有五种不同的含义。

ACID consistency 的思想是，你对数据有某些 statement（*invariants*，不变式）必须始终为真。例如，在会计系统中，所有账户的 credit 和 debit 必须始终平衡。如果 transaction 从满足这些 invariants 的 valid database 开始，并且 transaction 期间的任何 write 都保持 validity，那么你可以确定 invariants 始终得到满足。（invariants 可能在 transaction 执行期间暂时违反，但在 transaction commit 时应该再次满足。）

如果你希望数据库 enforce 你的 invariants，你需要将它们声明为 schema 的一部分，也就是 *constraints*。例如，foreign key constraint、unique constraint 或 check constraint（限制单个 row 中可以出现的值）通常用于对特定类型的 invariant 建模。更复杂的 consistency requirement 有时可以使用 trigger 或 materialized view 建模[^12]。

然而，复杂的 invariant 可能很难或不可能使用数据库通常提供的 constraint 来建模。在这种情况下，应用程序有责任正确定义其 transaction，以便它们保持 consistency。如果你写入违反 invariant 的错误数据，但你没有声明这些 invariant，数据库无法阻止你。因此，ACID 中的 C 通常取决于应用程序如何使用数据库，而不仅仅是数据库的属性。

#### Isolation（隔离性） {#sec_transactions_acid_isolation}

大多数数据库都会同时被多个 client 访问。如果它们 read/write 数据库的不同部分，这没有问题；但如果它们访问相同的 database records，你可能会遇到 concurrency 问题（race condition）。

[图 8-1](#fig_transactions_increment) 是这种问题的一个简单例子。假设你有两个 client 同时 increment 存储在数据库中的 counter。每个 client 需要读取当前值，加 1，然后写回新值（假设数据库中没有内置 increment operation）。在[图 8-1](#fig_transactions_increment) 中，counter 应该从 42 增加到 44，因为发生了两次 increment，但实际上由于 race condition 只增加到 43。

<a id="fig_transactions_increment"></a>

图 8-1. 两个 client concurrently increment counter 时的 race condition。

<img src="../../static/fig/ddia_0801.png" alt="图 8-1. 两个 client concurrently increment counter 时的 race condition。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

> [!CAUTION] Wenbo 注
> 这里要区分 *expected result* 和 *actual result*：如果两个 increment 都真正生效，counter 应该从 `42` 变成 `44`。但图里的两个 client 都先读到了同一个旧值 `42`，各自计算出 `43`，然后都写回 `43`；后一次 write 覆盖了前一次 increment 的效果，所以最终实际结果是 `43`。
>
> 这是一种典型的 *lost update* anomaly，也可以理解为 isolation/concurrency control 失败：如果两个 transaction 是 serializable 的，无论顺序是 T1 再 T2，还是 T2 再 T1，结果都必须是 `44`。出现 `43` 说明这次 concurrent execution 不等价于任何 serial execution。注意它不是 dirty read，问题不在于读到了 uncommitted data，而在于两个 transaction 基于同一个 stale value 做 read-modify-write，最后丢掉了其中一次 update。
>
> 常见修复方式包括使用数据库的 atomic update（例如 `UPDATE counters SET value = value + 1`）、显式 lock（例如 `SELECT FOR UPDATE`）、CAS/version check，或者直接使用能防止 lost update 的 isolation/serializable transaction。


ACID 意义上的 *isolation* 意味着同时执行的 transactions 彼此隔离：它们不能相互干扰。经典的数据库教科书将 isolation 形式化为 *serializable*，这意味着每个 transaction 可以假装自己是唯一在整个数据库上运行的 transaction。数据库确保当 transactions 已经 commit 时，结果与它们 *serially* 运行（一个接一个）相同，即使实际上它们可能是 concurrently 运行的[^13]。

然而，serializable 有 performance cost。在实践中，许多数据库使用比 serializable 更弱的 isolation：也就是说，它们允许 concurrent transactions 以有限的方式相互干扰。一些流行数据库，如 Oracle，甚至没有真正实现它（Oracle 有一个称为 "serializable" 的 isolation level，但它实际上实现的是 *snapshot isolation*，这是比 serializable 更弱的 guarantee[^10] [^14]）。这意味着某些类型的 race condition 仍然可能发生。我们将在["弱隔离级别"](#sec_transactions_isolation_levels)中探讨 snapshot isolation 和其他形式的 isolation。

> [!CAUTION] Wenbo 注
> *Serializable* 不等于完整的 *ACID*，它主要对应 ACID 里的 *I*：*Isolation*。也就是说，serializable isolation 只是在说 concurrent transactions 的执行结果必须等价于某个 serial order，从而防止 lost update、write skew、phantom read 等 race condition。
>
> 但 ACID 还包括 *Atomicity*、*Consistency* 和 *Durability*。Serializable 本身并不保证 transaction 失败时一定 all-or-nothing rollback，也不保证 commit 后的数据一定 survive crash；这些分别是 atomicity 和 durability 要解决的问题。至于 consistency，很多时候还依赖应用是否正确表达并维护 invariant，而不只是数据库的 isolation level。
>
> 所以更准确的说法是：如果一个数据库已经提供真正的 transaction atomicity 和 durability，并且你在其中使用真正的 serializable isolation，那么它在 ACID 的 *I* 上很强；但“serializable”这个词单独出现时，不能自动推出“这个系统就是完整 ACID”。反过来，很多数据库营销上说自己支持 ACID，也不一定默认提供 serializable isolation，因为它们可能默认使用 read committed、repeatable read 或 snapshot isolation。

#### Durability（持久性） {#durability}

数据库系统的目的是提供一个安全的地方来存储数据，而不用担心丢失它。*Durability* 是一个承诺：一旦 transaction 成功 commit，它写入的任何数据都不会被遗忘，即使发生 hardware fault 或 database crash。

在单节点数据库中，durability 通常意味着数据已经写入 nonvolatile storage，如硬盘或 SSD。普通文件 write 通常会先在内存中 buffer，然后才发送到磁盘，这意味着如果突然断电它们会丢失；因此，许多数据库使用 `fsync()` 系统调用来确保数据真正写入磁盘。数据库通常还有 write-ahead log（WAL）或类似机制（参见["使 B 树可靠"](/ch4#sec_storage_btree_wal)），这允许它们在 write 过程中发生 crash 时恢复。

在 replicated database 中，durability 可能意味着数据已成功复制到某些节点。为了提供 durability guarantee，数据库必须等到这些 writes 或 replication 完成，然后才报告 transaction 成功 commit。然而，如["可靠性和容错"](/ch2#sec_introduction_reliability)中所讨论的，完美的 durability 不存在：如果所有硬盘和所有 backup 同时被销毁，显然你的数据库无法挽救你。

--------

<a id="sidebar_transactions_durability"></a>

> [!TIP] Replication 与 Durability

历史上，durability 意味着写入归档磁带。后来它被理解为写入磁盘或 SSD。最近，它又被扩展为意味着 replication。哪种实现更好？

事实是，没有什么是完美的：

* 如果你写入磁盘而机器死机，即使你的数据没有丢失，在你修复机器或将磁盘转移到另一台机器之前，它也是不可访问的。复制系统可以保持可用。
* 相关故障——停电或导致每个节点在特定输入上崩溃的错误——可以一次性摧毁所有副本（参见["可靠性和容错"](/ch2#sec_introduction_reliability)），失去任何仅在内存中的数据。因此，写入磁盘对于复制数据库仍然相关。
* 在异步复制系统中，当领导者变得不可用时，最近的写入可能会丢失（参见["处理节点故障"](/ch6#sec_replication_failover)）。
* 当电源突然切断时，SSD 特别被证明有时会违反它们应该提供的保证：即使 `fsync` 也不能保证正常工作[^15]。磁盘固件可能有错误，就像任何其他类型的软件一样[^16] [^17]，例如，导致驱动器在正好 32,768 小时操作后失败[^18]。而且 `fsync` 很难使用；即使 PostgreSQL 使用它不正确超过 20 年[^19] [^20] [^21]。
* 存储引擎和文件系统实现之间的微妙交互可能导致难以追踪的错误，并可能导致磁盘上的文件在崩溃后损坏[^22] [^23]。一个副本上的文件系统错误有时也会传播到其他副本[^24]。
* 磁盘上的数据可能在未被检测到的情况下逐渐损坏[^25]。如果数据已经损坏了一段时间，副本和最近的备份也可能损坏。在这种情况下，你需要尝试从历史备份中恢复数据。
* 一项关于 SSD 的研究发现，在前四年的运行中，30% 到 80% 的驱动器会开发至少一个坏块，其中只有一些可以通过固件纠正[^26]。磁盘驱动器的坏扇区率较低，但完全故障率高于 SSD。
* 当磨损的 SSD（经历了许多写/擦除周期）断电时，它可能在几周到几个月的时间尺度上开始丢失数据，具体取决于温度[^27]。对于磨损水平较低的驱动器，这不是问题[^28]。

在实践中，没有一种技术可以提供绝对保证。只有各种降低风险的技术，包括写入磁盘、复制到远程机器和备份——它们可以而且应该一起使用。一如既往，明智的做法是对任何理论上的"保证"持健康的怀疑态度。

--------

### Single-Object 与 Multi-Object 操作 {#sec_transactions_multi_object}

回顾一下，在 ACID 中，atomicity 和 isolation 描述了如果 client 在同一 transaction 中进行多次 write，数据库应该做什么：

Atomicity
: 如果在 write sequence 的中途发生错误，transaction 应该被 abort，并且到该点为止所做的 write 应该被丢弃。换句话说，数据库让你不用担心 partial failure，通过提供 all-or-nothing guarantee 来简化错误处理。

Isolation
: Concurrent transactions 不应该相互干扰。例如，如果一个 transaction 进行多次 write，那么另一个 transaction 应该看到所有这些 write，或者完全看不到，而不是只看到某个 subset。

这些定义假设你想要同时修改多个 object（row、document、record）。这种 *multi-object transaction* 通常需要保持多块数据同步。[图 8-2](#fig_transactions_read_uncommitted) 显示了一个来自电子邮件应用程序的示例。要显示用户的未读消息数，你可以查询类似这样的内容：

```
SELECT COUNT(*) FROM emails WHERE recipient_id = 2 AND unread_flag = true
```

<a id="fig_transactions_read_uncommitted"></a>

图 8-2. 违反 isolation：一个 transaction 读取另一个 transaction 的 uncommitted write（“dirty read”）。

<img src="../../static/fig/ddia_0802.png" alt="图 8-2. 违反 isolation：一个 transaction 读取另一个 transaction 的 uncommitted write（dirty read）。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


然而，如果有很多电子邮件，你可能会发现这个 query 太慢，并决定将 unread message count 存储在一个单独字段中（一种 denormalization，我们在["规范化、反规范化和连接"](/ch3#sec_datamodels_normalization)中讨论）。现在，每当有新消息进来时，你必须增加 unread counter；每当消息被标记为已读时，你也必须减少 unread counter。

在[图 8-2](#fig_transactions_read_uncommitted) 中，用户 2 遇到了 anomaly：邮箱列表显示有 unread message，但 counter 显示零，因为 counter increment 尚未发生。（如果电子邮件应用程序中的错误 counter 看起来太微不足道，请考虑 customer account balance 而不是 unread counter，以及 payment transaction 而不是电子邮件。）isolation 本可以通过确保用户 2 看到插入的电子邮件和更新的 counter，或者两者都不看到，而不是看到 inconsistent intermediate state，来防止这个问题。

[图 8-3](#fig_transactions_atomicity) 说明了为什么需要 atomicity：如果在 transaction 过程中某处发生错误，邮箱内容和 unread counter 可能会失去同步。在 atomic transaction 中，如果对 counter 的 update 失败，transaction 将被 abort，插入的电子邮件将被 rollback。

<a id="fig_transactions_atomicity"></a>

图 8-3. Atomicity 确保如果发生错误，该 transaction 的任何先前 write 都会被撤消，以避免 inconsistent state。

<img src="../../static/fig/ddia_0803.png" alt="图 8-3. Atomicity 确保如果发生错误，该 transaction 的任何先前 write 都会被撤消，以避免 inconsistent state。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

> [!CAUTION] Wenbo 注
> 图 8-2 和图 8-3 可以合起来看：它们都在讲同一个 multi-object update 场景，也就是“插入一封 unread email”和“更新 unread counter”这两个 write 必须保持同步。但两个图强调的 failure mode 不一样。
>
> 图 8-2 是 *isolation* 问题：transaction 还没有 commit，中间状态却被另一个 client 看到了。这个中间状态是“email 已经插入，但 counter 还没更新”，所以 user 看到 mailbox 里有 unread email，但 unread counter 仍然是 `0`。这里的问题不是 transaction 最后一定失败，而是别人不应该在它完成前看到 partial result。这类 anomaly 叫 *dirty read*。
>
> 图 8-3 是 *atomicity* 问题：执行 transaction 的过程中真的发生了 error，例如 email 插入成功了，但 counter update 失败了。如果没有 atomicity，数据库可能把前半段 write 留下来，导致 email 和 counter 永久 inconsistent。atomicity 的作用是 all-or-nothing：只要 transaction 不能完整 commit，就 abort/rollback，把已经做过的 write 撤销掉。
>
> 所以可以用一句话区分：isolation 防止“别人看到半成品”，atomicity 防止“半成品被永久留下”。这也是为什么 multi-object transaction 很重要：它让多个 object 上的 change 对外表现得像一个 indivisible logical unit。


multi-object transaction 需要某种方式来确定哪些 read/write 操作属于同一 transaction。在 relational database 中，这通常基于 client 与 database server 的 TCP connection：在任何特定 connection 上，`BEGIN TRANSACTION` 和 `COMMIT` 语句之间的所有内容都被认为是同一 transaction 的一部分。如果 TCP connection 中断，transaction 必须被 abort。

另一方面，许多 non-relational database 没有这样的方式来将操作组合在一起。即使有 multi-object API（例如，key-value store 可能有一个 *multi-put* 操作，在一个操作中更新多个 key），这也不一定意味着它具有 transactional semantics：该命令可能在某些 key 上成功而在其他 key 上失败，使数据库处于 partially updated state。

#### Single-Object Write {#sec_transactions_single_object}

当单个 object 被更改时，atomicity 和 isolation 也适用。例如，假设你正在向数据库写入 20 KB 的 JSON document：

* 如果在发送了前 10 KB 后网络连接中断，数据库是否存储了无法解析的 10 KB JSON 片段？
* 如果数据库正在覆盖磁盘上的先前值的过程中电源失效，你是否最终会将新旧值拼接在一起？
* 如果另一个客户端在写入过程中读取该文档，它会看到部分更新的值吗？

这些问题会令人非常困惑，因此 storage engine 几乎普遍的目标是在一个节点上的 single object（如 key-value pair）上提供 atomicity 和 isolation。atomicity 可以使用 log 实现 crash recovery（参见["使 B 树可靠"](/ch4#sec_storage_btree_wal)），isolation 可以使用每个 object 上的 lock 来实现（一次只允许一个线程访问 object）。

某些数据库还提供更复杂的 atomic operation，例如 increment，它消除了像[图 8-1](#fig_transactions_increment) 中那样的 read-modify-write cycle。另一个常见操作是 *conditional write*，它只在值未被其他人 concurrently 更改时才允许 write（参见["conditional write（compare-and-set）"](#sec_transactions_compare_and_set)），类似于 shared-memory concurrency 中的 compare-and-set 或 compare-and-swap（CAS）操作。

--------

> [!NOTE]
> 严格来说，术语 *atomic increment* 在多线程编程的意义上使用了 *atomic* 这个词。在 ACID 的上下文中，它实际上应该被称为 *isolated* 或 *serializable* increment，但这不是通常的术语。

--------

这些 single-object operations 很有用，因为它们可以防止多个 client 尝试同时写入同一 object 时的 lost update（参见["防止丢失更新"](#sec_transactions_lost_update)）。然而，它们不是通常意义上的 transaction。例如，Cassandra 和 ScyllaDB 的 "lightweight transaction" 功能以及 Aerospike 的 "strong consistency" 模式在单个 object 上提供 linearizable（参见["线性一致性"](/ch10#sec_consistency_linearizability)）read 和 conditional write，但不保证跨多个 object。

#### 为什么需要 Multi-Object Transaction {#sec_transactions_need}

我们是否需要多对象事务？是否可能仅使用键值数据模型和单对象操作来实现任何应用程序？

在某些用例中，单对象插入、更新和删除就足够了。然而，在许多其他情况下，需要协调对多个不同对象的写入：

* 在关系数据模型中，一个表中的行通常具有对另一个表中行的外键引用。类似地，在类似图的数据模型中，顶点具有指向其他顶点的边。多对象事务允许你确保这些引用保持有效：插入引用彼此的多个记录时，外键必须正确且最新，否则数据变得毫无意义。

> [!CAUTION] Wenbo 注
> 这个 item 的核心不是“foreign key”这一个 SQL 功能，而是更一般的 *referential integrity*：一个 object 里保存了对另一个 object 的 reference，那么系统里就隐含了一个 invariant：reference 指向的 target 必须存在，而且语义上必须仍然有效。这个 invariant 天然跨越多个 object，所以 single-object write 很难完整表达它。
>
> 例子一：`orders` 表里有 `customer_id`，指向 `customers.id`。创建订单时，你可能需要同时写入 `orders`、`order_items`、库存预留、付款记录等多行。如果 order 已经插入，但 order_items 或 payment write 失败，系统就会留下一个语义上不完整的 order。multi-object transaction 让这些 write 要么一起 commit，要么一起 rollback。
>
> 例子二：删除一个 customer/project/forum post 时，其他 row 可能还引用它。数据库如果声明了 *foreign key constraint*，可以选择 reject delete、cascade delete，或要求你先清理 child rows。但不管策略是什么，它都涉及多个 object 的一致变化：不能让 parent 已经消失、child reference 还留着，除非你的业务明确允许这种 tombstone/soft-delete 语义。
>
> 例子三：graph data model 里，edge 本质上就是 reference。创建一条 `userA -[:FOLLOWS]-> userB` 的 edge 时，两个 vertex 必须存在；删除 vertex 时，也要处理相关 edge。否则就会出现 dangling edge。这个问题和 SQL foreign key 是同一个抽象：reference 和 target 必须一起维护。
>
> 所以答案是：包括破坏 foreign key 的情况，但 foreign key 只是 referential integrity 在 relational model 里的一个具体机制。真正需要 multi-object transaction 的原因是：你的 correctness rule 跨越多个 object，例如“所有 order item 必须属于一个存在的 order”、“所有 edge 必须连接存在的 vertex”、“所有 child row 的 parent 必须存在”。这些 rule 不是单个 object 内部能独立保证的。

* 在文档数据模型中，需要一起更新的字段通常在同一文档内，它被视为单个对象——更新单个文档时不需要多对象事务。然而，缺乏连接功能的文档数据库也鼓励反规范化（参见["何时使用哪种模型"](/ch3#sec_datamodels_document_summary)）。当需要更新反规范化信息时，如[图 8-2](#fig_transactions_read_uncommitted) 的示例，你需要一次更新多个文档。事务在这种情况下非常有用，可以防止反规范化数据失去同步。

> [!CAUTION] Wenbo 注
> 这一条讲的是 document model 里一个很常见的 trade-off：如果所有需要一起 change 的数据都嵌在同一个 document 里，那它就是 single-object update，数据库通常可以保证这个 document 内部的 atomic update。例如一个 blog post document 里嵌着 `title`、`body`、`tags`、`authorSnapshot`，只改这个 post 本身时，不一定需要 multi-object transaction。
>
> 但 document database 经常为了 query performance 做 *denormalization*：把同一份信息复制到多个 document 里。比如 user 的 display name/avatar 可能被复制到 posts、comments、notifications；商品的 name/price 可能被复制到 cart item、order item、invoice；聊天室的 last message 可能被复制到 room summary、user inbox、notification feed。这样读取很快，因为不用 join，但 write 会变复杂：canonical data 改了以后，所有 denormalized copies 都要跟着改。
>
> 问题就在这里：这些 copies 已经不在同一个 object 里了。假设 user 改名，`users` document 更新成功了，但某些 `comments.authorName` 没更新；或者新消息写入 `messages` 成功了，但 `rooms.lastMessage` 更新失败。系统就进入了 inconsistent state：不同页面读到的是同一个事实的不同版本。
>
> multi-object transaction 的价值，是把这些跨 document 的 updates 绑定成一个 logical unit：要么 canonical document 和所有需要同步的 denormalized document 一起 commit，要么一起 abort/rollback。否则你就需要接受 eventual consistency，并设计 repair job、outbox/event、change stream、read model rebuild 等补偿机制。换句话说，document model 不是不需要 transaction，而是只有当你的 invariant 被限制在单个 document 内时，single-object operation 才够用；一旦 invariant 跨 document，问题就回到了 multi-object transaction。

* 在具有 secondary index 的数据库中（几乎除了纯 key-value store 之外的所有数据库），每次更改 value 时都需要更新 index。从 transaction 的角度来看，这些 indexes 是不同的 database object：例如，如果没有 transaction isolation，record 可能出现在一个 index 中但不在另一个 index 中，因为对第二个 index 的 update 尚未发生（参见["分片和二级索引"](/ch7#sec_sharding_secondary_indexes)）。

> [!CAUTION] Wenbo 注
> 这一条容易被忽略，因为我们平时把 index 当成数据库内部实现细节，不会把它当作“另一个 object”。但从 transaction 的角度看，primary record 和 secondary index entry 确实是需要同步维护的多份状态：你改了一条 row/document，数据库不只是改 data record，还要改所有相关 index entry。
>
> 例子一：`users` 表有 primary key `id`，还有 secondary index `email_idx(email)`。如果用户把 email 从 `a@example.com` 改成 `b@example.com`，数据库需要同时做几件事：更新 `users[id=1].email`，从 `email_idx` 删除 `a@example.com -> id=1`，再插入 `b@example.com -> id=1`。如果这些 change 不是 atomic 的，可能出现按 primary key 查到的是新 email，但按旧 email 仍然能查到这个 user，或者按新 email 还查不到。
>
> 例子二：商品表有 `category_idx(category)` 和 `price_idx(price)`。如果一个商品从 category A 改到 category B，同时价格也变了，那么查询路径不同就可能看到不同结果：按商品 ID 查是新 category/price，按 category listing 查还在旧 category，按 price range 查又可能在另一个状态。用户感受到的就是“列表里有，点进去没了”或“搜索结果和详情页不一致”。
>
> 这就是为什么 secondary index 不只是 performance optimization，它也参与 correctness。transaction isolation 要保证别的 transaction 不会观察到“primary record 已更新，但某个 index 还没更新”的 intermediate state；atomicity 要保证如果更新 index 的过程中失败，primary record 和所有 index entry 一起 rollback。否则同一份数据会因为查询路径不同而呈现不同版本。
>
> 在单机关系数据库里，这通常由 storage engine 自动处理，所以应用开发者不太感知。但在 distributed database 或 sharded secondary index 里，index entry 可能在不同 node/shard 上，维护它就真的变成跨 object、甚至跨 node 的 coordination 问题。这也是第 7 章讨论 secondary index 为什么会让 sharding 复杂的原因。

这些应用程序仍然可以在没有 transaction 的情况下实现。然而，没有 atomicity 的错误处理会变得更加复杂，缺乏 isolation 可能导致 concurrency 问题。我们将在["弱隔离级别"](#sec_transactions_isolation_levels)中讨论这些问题，并在["派生数据与分布式事务"](/ch13#sec_future_derived_vs_transactions)中探索替代方法。

#### 处理 Error 和 Abort {#handling-errors-and-aborts}

transaction 的一个关键特性是，如果发生 error，它可以被 abort 并安全地 retry。ACID 数据库基于这样的哲学：如果数据库有违反 atomicity、isolation 或 durability guarantee 的危险，它宁愿完全放弃 transaction，也不允许它保持 half-finished state。

然而，并非所有系统都遵循这种哲学。特别是，具有 *leaderless replication* 的 data store（参见["无主（无领导者）复制"](/ch6#sec_replication_leaderless)）更多地基于 "best effort" 工作，可以总结为："数据库将尽其所能，如果遇到 error，它不会撤消已经完成的操作"。因此，从 error 中恢复是应用程序的责任。

error 不可避免地会发生，但许多软件开发人员更愿意只考虑 happy path，而不是 error handling 的复杂性。例如，流行的 ORM（object-relational mapping）框架，如 Rails 的 ActiveRecord 和 Django，不会 retry aborted transaction：error 通常导致 exception 冒泡到 stack 中，因此任何用户输入都被丢弃，用户收到错误消息。这是一种遗憾，因为 abort 的全部意义是启用 safe retry。

尽管 retry aborted transaction 是一种简单有效的 error-handling 机制，但它并不完美：

* 如果事务实际上成功了，但在服务器尝试向客户端确认成功提交时网络中断（因此从客户端的角度来看超时），那么重试事务会导致它被执行两次——除非你有额外的应用程序级去重机制。
* 如果错误是由于过载或并发事务之间的高争用，重试事务会使问题变得更糟，而不是更好。为了避免这种反馈循环，你可以限制重试次数，使用指数退避，并以不同的方式处理与过载相关的错误与其他错误（参见["当过载系统无法恢复时"](/ch2#sidebar_metastable)）。
* 仅在 transient error 后 retry 才值得（例如，由于 deadlock、isolation violation、临时网络中断和 failover）；在 permanent error 后（例如，constraint violation）retry 将毫无意义。
* 如果事务在数据库之外也有副作用，即使事务被中止，这些副作用也可能发生。例如，如果你正在发送电子邮件，你不会希望每次重试事务时都再次发送电子邮件。如果你想确保几个不同的系统一起提交或中止，two-phase commit可以提供帮助（我们将在["two-phase commit (2PC)"](#sec_transactions_2pc)中讨论这个问题）。
* 如果客户端进程在重试时崩溃，它试图写入数据库的任何数据都会丢失。

> [!CAUTION] Wenbo 注
> 数据库负责的是 transaction 语义：发现 constraint violation、deadlock、serialization failure、connection failure 等情况时，它可以 abort/rollback，保证不会留下 half-finished state。但“接下来怎么办”通常还是 application-level concern：应用要 catch error，判断它是 transient 还是 permanent，决定是否 retry、返回什么用户提示、是否记录 audit log、是否触发补偿流程。
>
> *happy path* 指的是“一切都成功”的主流程：请求进来、验证通过、写数据库成功、commit 成功、返回成功。只写 happy path 的代码，就是假设没有 timeout、没有 deadlock、没有 duplicate request、没有 partial failure、没有 constraint violation。现实系统里这些 failure path 不处理好，transaction 再强也只能保证数据库内部不半成品，不能自动替应用恢复业务语义。
>
> `retry aborted transaction` 适合处理 *transient error*，例如 deadlock、serialization failure、短暂网络抖动、leader failover。更合适的做法不是无限 retry，而是：只 retry 明确可重试的错误；设置最大 retry 次数；使用 exponential backoff + jitter；让整个 operation 尽量 idempotent；并在日志/metrics 里记录 retry 原因。这样 retry 是一个受控恢复机制，而不是把系统压得更糟的循环。
>
> 对 *permanent error* 不应该 retry，例如 foreign key violation、unique constraint violation、余额不足、用户无权限、输入格式不合法。这类错误 retry 一百次也不会变好，应该转成明确的 business error 返回给 caller，或者要求用户修改输入。
>
> 最棘手的是 *unknown outcome*：比如数据库已经 commit 成功，但返回 commit result 时网络断了，client 以为 timeout。此时盲目 retry 可能把操作执行两次。更稳妥的策略是给业务操作分配 idempotency key / request id / operation id，并在数据库里用 unique constraint 记录它；retry 时先查这个 operation 是否已经完成。支付、下单、发券、扣库存这类场景通常都需要这种 application-level 去重。
>
> 如果 transaction 之外还有 side effect，例如发送 email、调用 payment gateway、发布 message，通常不要在数据库 transaction 中直接做这些外部动作。更常见的做法是 *transactional outbox*：在同一个 DB transaction 里写业务数据和 outbox event，commit 后由后台 worker 可靠地发送 event；发送端和消费端都用 idempotency 做去重。这样比“失败就简单 retry 整个函数”更可控。



## Weak  Levels（弱隔离级别） {#sec_transactions_isolation_levels}

如果两个 transaction 不访问相同的数据，或者都是 read-only 的，它们可以安全地 parallel 运行，因为它们互不依赖。仅当一个 transaction 读取另一个 transaction concurrently 修改的数据时，或者当两个 transaction 尝试同时修改相同数据时，才会出现 concurrency 问题（race condition）。

并发错误很难通过测试发现，因为这些错误只有在时机不巧时才会触发。这种时机问题可能非常罕见，通常难以重现。并发也很难推理，特别是在大型应用程序中，你不一定知道代码的其他部分正在访问数据库。如果只有一个用户，应用程序开发就已经够困难了；有许多并发用户会让情况变得更加困难，因为任何数据都可能在任何时候意外地发生变化。
Isolation
出于这个原因，数据库长期以来一直试图通过提供 *transaction isolation* 来向应用程序开发人员隐藏 concurrency 问题。理论上，isolation 应该让你的生活更轻松，让你假装没有 concurrency 发生：*serializable* isolation 意味着数据库保证 transaction 具有与 *serial* 运行（一次一个，没有任何 concurrency）相同的效果。

在实践中，isolation 不幸并不那么简单。serializable isolation 有 performance cost，许多数据库不愿意支付这个代价[^10]。因此，系统通常使用较弱的 isolation levels，这些级别可以防止*某些* concurrency 问题，但不是全部。这些 isolation levels 更难理解，它们可能导致微妙的错误，但它们在实践中仍然被使用[^29]。

由弱事务隔离引起的并发错误不仅仅是理论问题。它们已经导致了巨额资金损失[^30] [^31] [^32]，引发了金融审计师的调查[^33]，并导致客户数据损坏[^34]。对此类问题披露的一个流行评论是"如果你正在处理金融数据，请使用 ACID 数据库！"——但这没有抓住重点。即使许多流行的关系数据库系统（通常被认为是"ACID"）使用弱隔离，因此它们不一定能防止这些错误发生。

--------

> [!NOTE]
> 顺便说一句，银行系统的大部分依赖于通过安全 FTP 交换的文本文件[^35]。在这种情况下，拥有审计跟踪和一些人为级别的欺诈预防措施实际上比 ACID 属性更重要。

--------

这些例子还强调了一个重要观点：即使并发问题在正常操作中很少见，你也必须考虑攻击者故意向你的 API 发送大量高度并发请求以故意利用并发错误的可能性[^30]。因此，为了构建可靠和安全的应用程序，你必须确保系统地防止此类错误。

在本节中，我们将研究实践中使用的几种 weak（non-serializable）isolation levels，并详细讨论哪些 race condition 可以发生、哪些不能发生，以便你可以决定哪个级别适合你的应用程序。完成后，我们将详细讨论 serializable（参见["serializable"](#sec_transactions_serializability)）。我们对 isolation levels 的讨论将是非正式的，使用示例。如果你想要严格定义和属性分析，可以在学术文献中找到它们[^36] [^37] [^38] [^39]。

### read committed {#sec_transactions_read_committed}

最基本的 transaction isolation level 是 *read committed*。它提供两个 guarantee：

1. 从数据库读取时，你只会看到已经提交的数据（没有*dirty read*）。
2. 写入数据库时，你只会覆盖已经提交的数据（没有*dirty write*）。

某些数据库支持更弱的 isolation level，称为 *read uncommitted*。它防止 dirty write，但不防止 dirty read。让我们更详细地讨论这两个 guarantee。

#### No Dirty Read {#no-dirty-reads}

想象一个事务已经向数据库写入了一些数据，但事务尚未提交或中止。另一个事务能看到那个未提交的数据吗？如果能，这称为*dirty read*[^3]。

在 read committed isolation level 下运行的 transaction 必须防止 dirty read。这意味着 transaction 的任何 write 只有在该 transaction commit 时才对其他人可见（然后它的所有 write 立即变得可见）。这在[图 8-4](#fig_transactions_read_committed) 中说明，其中用户 1 已设置 *x* = 3，但用户 2 的 *get x* 仍返回旧值 2，因为用户 1 尚未 commit。

<a id="fig_transactions_read_committed"></a>

图 8-4. 没有dirty read：用户 2 只有在用户 1 的事务提交后才能看到 x 的新值。

<img src="../../static/fig/ddia_0804.png" alt="图 8-4. 没有dirty read：用户 2 只有在用户 1 的事务提交后才能看到 x 的新值。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

有几个原因说明为什么防止 dirty read 是有用的：

* 如果事务需要更新多行，dirty read意味着另一个事务可能看到某些更新但不是其他更新。例如，在[图 8-2](#fig_transactions_read_uncommitted) 中，用户看到新的未读电子邮件但没有看到更新的计数器。这是电子邮件的dirty read。看到数据库处于部分更新状态会让用户感到困惑，并可能导致其他事务做出错误的决定。
* 如果事务中止，它所做的任何写入都需要回滚（如[图 8-3](#fig_transactions_atomicity)）。如果数据库允许dirty read，这意味着事务可能看到后来被回滚的数据——即从未实际提交到数据库的数据。任何读取未提交数据的事务也需要被中止，导致称为*cascading abort*的问题。

#### No Dirty Write {#sec_transactions_dirty_write}

如果两个事务并发尝试更新数据库中的同一行会发生什么？我们不知道写入将以什么顺序发生，但我们通常假设后面的写入会覆盖前面的写入。

然而，如果前面的 write 是尚未 committed transaction 的一部分，因此后面的 write 覆盖了一个 uncommitted value，会发生什么？这称为 *dirty write*[^36]。在 read committed isolation level 下运行的 transaction 必须防止 dirty write，通常通过延迟第二个 write，直到第一个 write 所属的 transaction 已 commit 或 abort。

通过防止 dirty write，这个 isolation level 避免了某些类型的 concurrency 问题：

* 如果事务更新多行，dirty write可能导致糟糕的结果。例如，考虑[图 8-5](#fig_transactions_dirty_writes)，它说明了一个二手车销售网站，两个人 Aaliyah 和 Bryce 同时尝试购买同一辆车。购买汽车需要两次数据库写入：网站上的列表需要更新以反映买家，销售发票需要发送给买家。在[图 8-5](#fig_transactions_dirty_writes) 的情况下，销售被授予 Bryce（因为他对 `listings` 表执行了获胜的更新），但发票被发送给 Aaliyah（因为她对 `invoices` 表执行了获胜的更新）。read committed防止了这种事故。
* 然而，read committed *不*防止[图 8-1](#fig_transactions_increment) 中两个 counter increment 之间的 race condition。在这种情况下，第二个 write 发生在第一个 transaction commit 之后，所以它不是 dirty write。它仍然是不正确的，但原因不同：在["防止丢失更新"](#sec_transactions_lost_update)中，我们将讨论如何使此类 counter increment 安全。

<a id="fig_transactions_dirty_writes"></a>

图 8-5. 有了dirty write，来自不同事务的冲突写入可能会混在一起。

<img src="../../static/fig/ddia_0805.png" alt="图 8-5. 有了dirty write，来自不同事务的冲突写入可能会混在一起。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

> [!CAUTION] Wenbo 注
> 这张图里有两个 transaction，都想买同一辆 listing `1234`。Aaliyah 的 transaction 先把 `listings.buyer` 写成 `Aaliyah`，但还没有 commit；这时 Bryce 的 transaction 又把同一条 listing 写成 `Bryce`，相当于覆盖了 Aaliyah 尚未 commit 的 write。这就是第一处 *dirty write*。
>
> 后半段又反过来了：Bryce 先把 `invoices.recipient` 写成 `Bryce`，但还没 commit；随后 Aaliyah 把同一张 invoice 的 recipient 写成 `Aaliyah`，覆盖了 Bryce 尚未 commit 的 write。这是第二处 dirty write。两个 transaction 最后都 commit，于是数据库留下一个拼接出来的结果：listing 显示买家是 Bryce，但 invoice 却发给 Aaliyah。
>
> 关键点是，这里不是 dirty read，因为图里没有哪个 transaction 读取了另一个 transaction 的 uncommitted data；问题在于 write 直接覆盖了对方尚未 commit 的 write。read committed 至少会防止这种情况：当一个 transaction 写了某个 row 后，其他 transaction 要写同一个 row 必须等它 commit 或 abort，不能把两个 transaction 的不同部分混成一个不对应任何真实业务操作的最终状态。

#### Implementing Read Committed {#sec_transactions_read_committed_impl}

read committed 是一个非常流行的 isolation level。它是 Oracle Database、PostgreSQL、SQL Server 和许多其他数据库中的默认设置[^10]。

最常见的是，数据库通过使用 row-level lock 来防止 dirty write：当 transaction 想要修改特定 row（或 document、其他 object）时，它必须首先获取该 row 的 lock。然后它必须持有该 lock，直到 transaction commit 或 abort。任何给定 row 只能有一个 transaction 持有 lock；如果另一个 transaction 想要写入同一 row，它必须等到第一个 transaction commit 或 abort 后才能获取 lock 并继续。这种 locking 由数据库在 read committed mode（或更强的 isolation level）下自动完成。

我们如何防止dirty read？一种选择是使用相同的锁，并要求任何想要读取行的事务短暂地获取锁，然后在读取后立即再次释放它。这将确保在行具有脏的、未提交的值时无法进行读取（因为在此期间锁将由进行写入的事务持有）。

然而，要求读锁的方法在实践中效果不佳，因为一个长时间运行的写事务可以强制许多其他事务等待，直到长时间运行的事务完成，即使其他事务只读取并且不向数据库写入任何内容。这会损害只读事务的响应时间，并且对可操作性不利：应用程序一个部分的减速可能会由于等待锁而在应用程序的完全不同部分产生连锁效应。

尽管如此，在某些数据库中使用锁来防止dirty read，例如 IBM Db2 和 Microsoft SQL Server 在 `read_committed_snapshot=off` 设置中[^29]。

防止dirty read的更常用方法是[图 8-4](#fig_transactions_read_committed) 中说明的方法：对于每个被写入的行，数据库记住旧的已提交值和当前持有写锁的事务设置的新值。当事务正在进行时，任何其他读取该行的事务都只是被给予旧值。只有当新值被提交时，事务才会切换到读取新值（有关更多详细信息，请参见["multi-version concurrency control (MVCC)"](#sec_transactions_snapshot_impl)）。

### Snapshot Isolation 与 Repeatable Read {#sec_transactions_snapshot_isolation}

如果你肤浅地看待 read committed isolation，你可能会以为它已经做了 transaction 需要做的一切：它允许 abort（atomicity 所需），它防止读取 transaction 的 incomplete result，并且它防止 concurrent write 混淆。确实，这些是有用功能，比没有 transaction 的系统能获得的 guarantee 要强得多。

然而，使用这个 isolation level 时，仍然有很多方式可能出现 concurrency error。例如，[图 8-6](#fig_transactions_item_many_preceders) 说明了 read committed 可能发生的问题。

<a id="fig_transactions_item_many_preceders"></a>

图 8-6. read skew：Aaliyah 观察到数据库处于不一致状态。

<img src="../../static/fig/ddia_0806.png" alt="图 8-6. read skew：Aaliyah 观察到数据库处于不一致状态。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

> [!CAUTION] Wenbo 注
> 这张图里有两个并发 transaction：Aaliyah 在读自己的两个账户余额，另一个 Transfer transaction 正在把 `100` 美元从 account 2 转到 account 1。初始状态是两个账户各 `500`，总额应该一直是 `1000`。
>
> 时间线的交错点在这里：Aaliyah 先读 account 1，此时 transfer 还没有把 `+100` 写进去，所以她看到 `500`。随后 transfer 把 account 1 更新为 `600`，又把 account 2 更新为 `400` 并 commit。接着 Aaliyah 再读 account 2，看到的是已经转出后的 `400`。于是她把两次 query 的结果合起来看，就得到 `500 + 400 = 900`，仿佛有 `100` 美元消失了。
>
> 这不是 dirty read：Aaliyah 读到的 `500` 和 `400` 都可以是已经 committed 的值。问题在于这两个值来自数据库的两个不同时间点：account 1 是 transfer 之前的旧世界，account 2 是 transfer 之后的新世界。read committed 只保证“每次 read 不读未提交数据”，但不保证“同一个 transaction 内多次 read 来自同一个 consistent snapshot”。这类跨时间点拼出来的不一致视图就是 *read skew* / *nonrepeatable read*。

假设 Aaliyah 在银行有 1,000 美元的储蓄，分成两个账户，每个 500 美元。现在一笔事务从她的一个账户转账 100 美元到另一个账户。如果她不幸在该事务处理的同时查看她的账户余额列表，她可能会看到一个账户余额在收款到达之前（余额为 500 美元），另一个账户在转出之后（新余额为 400 美元）。对 Aaliyah 来说，现在她的账户总共只有 900 美元——似乎 100 美元凭空消失了。

这种 anomaly 称为 *read skew*，它是 *nonrepeatable read* 的一个例子：如果 Aaliyah 在 transaction 结束时再次读取账户 1 的余额，她会看到与之前 query 中看到的不同的值（600 美元）。read skew 在 read committed isolation 下被认为是可接受的：Aaliyah 看到的账户余额确实是在她读取它们时已 committed 的。

--------

> [!NOTE]
> 术语*偏斜*不幸地被重载了：我们之前在*具有热点的不平衡工作负载*的意义上使用它（参见["倾斜负载和缓解热点"](/ch7#sec_sharding_skew)），而这里它意味着*时序异常*。

--------

在 Aaliyah 的情况下，这不是一个持久的问题，因为如果她几秒钟后重新加载在线银行网站，她很可能会看到一致的账户余额。然而，某些情况不能容忍这种临时的不一致性：

备份
: 进行备份需要复制整个数据库，对于大型数据库可能需要几个小时。在备份过程运行期间，写入将继续对数据库进行。因此，你最终可能会得到备份的某些部分包含较旧版本的数据，而其他部分包含较新版本。如果你需要从这样的备份恢复，不一致性（如消失的钱）将变成永久性的。

分析查询和完整性检查
: 有时，你可能想要运行扫描数据库大部分的查询。此类查询在分析中很常见（参见["分析与运营系统"](/ch1#sec_introduction_analytics)），或者可能是定期完整性检查的一部分，以确保一切正常（监控数据损坏）。如果这些查询在不同时间点观察数据库的不同部分，它们很可能返回无意义的结果。

*Snapshot isolation*[^36] 是解决这个问题的最常见方法。其思想是每个 transaction 从数据库的 *consistent snapshot* 读取：也就是说，transaction 看到 transaction 开始时数据库中已 committed 的所有数据。即使数据随后被另一个 transaction 更改，每个 transaction 也只能看到该特定时间点的旧数据。

> [!CAUTION] Wenbo 注
> snapshot isolation 不是在 transaction 开始时真的复制一份完整数据库，那样成本太高。它更像是给 transaction 记下一个“开始时间点”，之后这个 transaction 的所有 read 都按照这个时间点去挑数据版本：在它开始之前已经 committed 的版本可见；在它开始之后才 commit 的版本不可见；已经 abort 的版本永远不可见。
>
> 以图 8-6 为例，如果 Aaliyah 的查询 transaction 在 transfer commit 之前开始，那么它的 snapshot 就固定在“两个账户都是 `500`”的时间点。即使 transfer 后来把 account 1 改成 `600`、account 2 改成 `400` 并 commit，Aaliyah 在同一个 transaction 里继续 read 时，数据库仍然会给她旧版本：account 1 是 `500`，account 2 也是 `500`。如果她的 transaction 是在 transfer commit 之后才开始，那么她会看到新版本：`600` 和 `400`。但她不会在同一个 snapshot 里看到 `500 + 400` 这种跨时间点拼出来的状态。
>
> 数据库通常用 *MVCC* 做这件事：同一行可以同时保留多个 committed versions，每个 version 带着创建它、删除它的 transaction ID 或 timestamp。read 时不加读锁，而是按 snapshot 的可见性规则选择“对我这个时间点可见”的版本；update 时通常创建新版本，而不是直接覆盖旧版本。等没有任何活跃 transaction 还需要旧版本时，后台 garbage collection 再把旧版本清掉。
>
> 所以 snapshot isolation 的核心是：read 看到稳定的一致快照，writer 可以继续写新版本，reader 和 writer 通常互不阻塞。不过它主要解决 read skew / nonrepeatable read 这类读视图不一致问题，并不等于 serializable；后面会看到 write skew 仍然可能发生。

snapshot isolation对于长时间运行的只读查询（如备份和分析）来说是一个福音。如果查询操作的数据在查询执行的同时发生变化，很难推理查询的含义。当事务可以看到数据库的一致快照（冻结在特定时间点）时，理解起来就容易得多。

snapshot isolation 是一个流行功能：它的变体受到 PostgreSQL、使用 InnoDB storage engine 的 MySQL、Oracle、SQL Server 等支持，尽管详细行为因系统而异[^29] [^40] [^41]。某些数据库，如 Oracle、TiDB 和 Aurora DSQL，甚至选择 snapshot isolation 作为它们的最高 isolation level。

#### Multi-Version Concurrency Control (MVCC) {#sec_transactions_snapshot_impl}

与read committed隔离一样，snapshot isolation的实现通常使用写锁来防止dirty write（参见["实现read committed"](#sec_transactions_read_committed_impl)），这意味着进行写入的事务可以阻止写入同一行的另一个事务的进度。但是，读取不需要任何锁。从性能的角度来看，snapshot isolation的一个关键原则是*读者永远不会阻塞写者，写者永远不会阻塞读者*。这允许数据库在一致快照上处理长时间运行的读查询，同时正常处理写入，两者之间没有任何锁争用。

为了实现snapshot isolation，数据库使用了我们在[图 8-4](#fig_transactions_read_committed) 中看到的防止dirty read机制的泛化。数据库必须潜在地保留每行的几个不同的已提交版本，而不是每行的两个版本（已提交版本和被覆盖但尚未提交的版本），因为各种正在进行的事务可能需要在不同时间点看到数据库的状态。因为它并排维护一行的多个版本，所以这种技术被称为*MVCC*（MVCC）。

[图 8-7](#fig_transactions_mvcc) 说明了 PostgreSQL 中如何实现基于 MVCC 的snapshot isolation[^40] [^42] [^43]（其他实现类似）。当事务启动时，它被赋予一个唯一的、始终递增的事务 ID（`txid`）。每当事务向数据库写入任何内容时，它写入的数据都用写入者的事务 ID 标记。（准确地说，PostgreSQL 中的事务 ID 是 32 位整数，因此它们在大约 40 亿个事务后溢出。清理过程执行清理以确保溢出不会影响数据。）

<a id="fig_transactions_mvcc"></a>

图 8-7. 使用MVCC实现snapshot isolation。

<img src="../../static/fig/ddia_0807.png" alt="图 8-7. 使用MVCC实现snapshot isolation。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />

> [!CAUTION] Wenbo 注
> 这张图是在解释 MVCC 如何让 transaction 12 看到一个稳定的 snapshot。图里 transaction 12 先开始，所以它的 snapshot 时间点早于 transaction 13。之后 transaction 13 执行转账：把 account 1 从 `500` 改成 `600`，把 account 2 从 `500` 改成 `400`，最后 commit。
>
> MVCC 的关键是 update 不直接覆盖原 row，而是把 update 拆成两件事：把旧版本标记为 deleted，再插入一个新版本。比如 account 1 原来的 `balance = 500` 是 `inserted_by = 3`，transaction 13 更新它时，不是原地改成 `600`，而是把旧版本标成 `deleted_by = 13`，再插入一个 `inserted_by = 13, balance = 600` 的新版本。account 2 同理：旧版本 `500` 被标成 `deleted_by = 13`，新版本 `400` 由 transaction 13 插入。
>
> 现在看 transaction 12 为什么仍然读到两个 `500`。对 transaction 12 来说，transaction 13 是“在我开始之后才发生的 transaction”，所以 13 做的所有 effect 都不可见：`inserted_by = 13` 的新版本不可见，因此 `600` 和 `400` 都不能读；旧版本虽然有 `deleted_by = 13`，但这个 delete 对 transaction 12 也不可见，所以旧的 `500` 仍然可见。
>
> 因此，即使 transaction 13 在 transaction 12 第二次 read 之前已经 commit，transaction 12 读 account 2 时也不会突然看到 `400`。它会继续按照自己开始时的 snapshot 读旧版本 `500`。这就是 snapshot isolation 避免图 8-6 里 `500 + 400` read skew 的具体机制：不是阻塞 writer，而是保留多个版本，让 reader 选择对自己 snapshot 可见的版本。

表中的每一行都有一个 `inserted_by` 字段，包含将此行插入表中的事务的 ID。此外，每行都有一个 `deleted_by` 字段，最初为空。如果事务删除一行，该行实际上不会从数据库中删除，而是通过将 `deleted_by` 字段设置为请求删除的事务的 ID 来标记为删除。在稍后的某个时间，当确定没有事务可以再访问已删除的数据时，数据库中的垃圾收集过程会删除任何标记为删除的行并释放它们的空间。

更新在内部被转换为删除和插入[^44]。例如，在[图 8-7](#fig_transactions_mvcc) 中，事务 13 从账户 2 中扣除 100 美元，将余额从 500 美元更改为 400 美元。`accounts` 表现在实际上包含账户 2 的两行：余额为 500 美元的行被事务 13 标记为已删除，余额为 400 美元的行由事务 13 插入。

行的所有版本都存储在同一个数据库堆中（参见["在索引中存储值"](/ch4#sec_storage_index_heap)），无论写入它们的事务是否已提交。同一行的版本形成一个链表，从最新版本到最旧版本或相反，以便查询可以在内部迭代行的所有版本[^45] [^46]。

#### 观察一致快照的可见性规则 {#sec_transactions_mvcc_visibility}

当事务从数据库读取时，事务 ID 用于决定它可以看到哪些行版本以及哪些是不可见的。通过仔细定义可见性规则，数据库可以向应用程序呈现数据库的一致快照。这大致如下工作[^43]：

1. 在每个事务开始时，数据库列出当时正在进行（尚未提交或中止）的所有其他事务。这些事务所做的任何写入都被忽略，即使事务随后提交。这确保我们看到一个不受另一个事务提交影响的一致快照。
2. 具有较晚事务 ID（即在当前事务开始后开始，因此不包括在正在进行的事务列表中）的事务所做的任何写入都被忽略，无论这些事务是否已提交。
3. 中止事务所做的任何写入都被忽略，无论该中止何时发生。这样做的好处是，当事务中止时，我们不需要立即从存储中删除它写入的行，因为可见性规则会将它们过滤掉。垃圾收集过程可以稍后删除它们。
4. 所有其他写入对应用程序的查询可见。

这些规则适用于行的插入和删除。在[图 8-7](#fig_transactions_mvcc) 中，当事务 12 从账户 2 读取时，它看到 500 美元的余额，因为 500 美元余额的删除是由事务 13 进行的（根据规则 2，事务 12 无法看到事务 13 进行的删除），而 400 美元余额的插入尚不可见（根据相同的规则）。

换句话说，如果以下两个条件都为真，则行是可见的：

* 在读者事务开始时，插入该行的事务已经提交。
* 该行未标记为删除，或者如果是，请求删除的事务在读者事务开始时尚未提交。

长时间运行的事务可能会长时间继续使用快照，继续读取（从其他事务的角度来看）早已被覆盖或删除的值。通过永远不更新原地的值，而是在每次更改值时插入新版本，数据库可以提供一致的快照，同时只产生很小的开销。

<a id="sec_transactions_snapshot_indexes"></a>

#### Indexes 与 Snapshot Isolation {#indexes-and-snapshot-isolation}

索引如何在多版本数据库中工作？最常见的方法是每个索引条目指向与该条目匹配的行的一个版本（最旧或最新版本）。每个行版本可能包含对下一个最旧或下一个最新版本的引用。使用索引的查询必须迭代行以找到可见的行，并且值与查询要查找的内容匹配。当垃圾收集删除不再对任何事务可见的旧行版本时，相应的索引条目也可以被删除。

许多实现细节影响MVCC的性能[^45] [^46]。例如，如果同一行的不同版本可以适合同一页面，PostgreSQL 有避免索引更新的优化[^40]。其他一些数据库避免存储修改行的完整副本，而只存储版本之间的差异以节省空间。

CouchDB、Datomic 和 LMDB 使用另一种方法。尽管它们也使用 B 树（参见["B 树"](/ch4#sec_storage_b_trees)），但它们使用*不可变*（写时复制）变体，在更新时不会覆盖树的页面，而是创建每个修改页面的新副本。父页面，直到树的根，被复制并更新以指向其子页面的新版本。任何不受写入影响的页面都不需要复制，并且可以与新树共享[^47]。

使用不可变 B 树，每个写事务（或事务批次）都会创建一个新的 B 树根，特定的根是创建时数据库的一致快照。不需要基于事务 ID 过滤行，因为后续写入无法修改现有的 B 树；它们只能创建新的树根。这种方法还需要后台进程进行压缩和垃圾收集。

#### Snapshot Isolation、Repeatable Read 和命名混淆 {#snapshot-isolation-repeatable-read-and-naming-confusion}

MVCC 是数据库常用的实现技术，通常用于实现snapshot isolation。然而，不同的数据库有时使用不同的术语来指代同一件事：例如，snapshot isolation在 PostgreSQL 中称为"repeatable read"，在 Oracle 中称为"serializable"[^29]。有时不同的系统使用相同的术语来表示不同的东西：例如，虽然在 PostgreSQL 中"repeatable read"意味着snapshot isolation，但在 MySQL 中它意味着比snapshot isolation更弱一致性的 MVCC 实现[^41]。

这种 naming confusion 的原因是 SQL 标准没有 snapshot isolation 的概念，因为该标准基于 System R 1975 年的 isolation level 定义[^3]，而 snapshot isolation 当时还没有被发明。相反，它定义了 repeatable read，表面上看起来类似于 snapshot isolation。PostgreSQL 将其 snapshot isolation level 称为 "repeatable read"，因为它符合标准的要求，因此他们可以声称符合标准。

不幸的是，SQL 标准对 isolation level 的定义是有缺陷的：它模糊、不精确，而且不像标准应该的那样独立于 implementation[^36]。即使几个数据库实现了 repeatable read，它们实际提供的 guarantee 也有很大差异，尽管表面上是标准化的[^29]。研究文献中有 repeatable read 的正式定义[^37] [^38]，但大多数 implementation 不满足该正式定义。最重要的是，IBM Db2 使用 "repeatable read" 来指代 serializable[^10]。

因此，没有人真正知道repeatable read意味着什么。

### Preventing Lost Updates（防止丢失更新） {#sec_transactions_lost_update}

到目前为止，我们讨论的read committed和snapshot isolation级别主要是关于只读事务在并发写入存在的情况下可以看到什么的保证。我们大多忽略了两个事务并发写入的问题——我们只讨论了dirty write（参见["没有dirty write"](#sec_transactions_dirty_write)），这是可能发生的一种特定类型的写-写冲突。

并发写入事务之间还可能发生其他几种有趣的冲突。其中最著名的是*丢失更新*问题，在[图 8-1](#fig_transactions_increment) 中以两个并发计数器递增的例子说明。

如果应用程序从数据库读取某个 value，修改它，然后写回修改后的 value（*read-modify-write cycle*），就会出现 lost update 问题。如果两个 transaction concurrently 执行此操作，其中一个 modification 可能会丢失，因为第二个 write 不包括第一个 modification。（我们有时说后面的 write *overwrite* 了前面的 write。）这种 pattern 出现在各种不同场景中：

* 递增计数器或更新账户余额（需要读取当前值，计算新值，并写回更新的值）
* 对复杂值进行本地更改，例如，向 JSON 文档中的列表添加元素（需要解析文档，进行更改，并写回修改后的文档）
* 两个用户同时编辑 wiki 页面，每个用户通过将整个页面内容发送到服务器来保存他们的更改，覆盖数据库中当前的任何内容

因为这是一个如此常见的问题，已经开发了各种解决方案[^48]。

#### Atomic Write Operations {#atomic-write-operations}

许多数据库提供 atomic update operations，消除了在应用程序代码中实现 read-modify-write cycle 的需要。如果你的代码可以用这些操作来表达，它们通常是最好的解决方案。例如，以下语句在大多数 relational database 中是 concurrency-safe 的：

```sql
UPDATE counters SET value = value + 1 WHERE key = 'foo';
```

类似地，文档数据库（如 MongoDB）提供原子操作来对 JSON 文档的一部分进行本地修改，Redis 提供原子操作来修改数据结构（如优先级队列）。并非所有写入都可以轻松地用原子操作来表达——例如，对 wiki 页面的更新涉及任意文本编辑，可以使用["CRDT 和操作转换"](/ch6#sec_replication_crdts)中讨论的算法来处理——但在可以使用原子操作的情况下，它们通常是最佳选择。

atomic operation 通常通过在读取 object 时对其进行 exclusive lock 来实现，以便在应用 update 之前没有其他 transaction 可以读取它。另一种选择是简单地强制所有 atomic operation 在单个线程上执行。

不幸的是，ORM（object-relational mapping）框架很容易意外生成执行 unsafe read-modify-write cycle 的代码，而不是使用数据库提供的 atomic operation[^49] [^50] [^51]。这可能是难以通过测试发现的微妙错误来源。

#### Explicit Locking {#explicit-locking}

如果数据库的内置 atomic operation 不提供必要功能，另一个防止 lost update 的选项是应用程序显式 lock 要更新的 object。然后应用程序可以执行 read-modify-write cycle；如果任何其他 transaction 尝试 concurrently update 或 lock 同一 object，它将被迫等到第一个 read-modify-write cycle 完成。

例如，考虑一个多人游戏，其中几个玩家可以同时移动同一个棋子。在这种情况下，原子操作可能不够，因为应用程序还需要确保玩家的移动遵守游戏规则，这涉及一些你无法合理地作为数据库查询实现的逻辑。相反，你可以使用锁来防止两个玩家同时移动同一个棋子，如[例 8-1](#fig_transactions_select_for_update) 所示。

{{< figure id="fig_transactions_select_for_update" title="例 8-1. 显式锁定行以防止丢失更新" class="w-full my-4" >}}

```sql
BEGIN TRANSACTION;

SELECT * FROM figures
    WHERE name = 'robot' AND game_id = 222
    FOR UPDATE; ❶

-- 检查移动是否有效，然后更新
-- 前一个 SELECT 返回的棋子的位置。
UPDATE figures SET position = 'c4' WHERE id = 1234;

COMMIT;
```

❶：`FOR UPDATE` 子句表示数据库应该对此查询返回的所有行进行锁定。

这是有效的，但要正确执行，你需要仔细考虑你的 application logic。很容易忘记在代码中的某个地方添加必要的 lock，从而引入 race condition。

此外，如果你 lock 多个 object，则存在 deadlock 风险，其中两个或多个 transaction 正在等待彼此释放 lock。许多数据库会自动检测 deadlock，并 abort 涉及的 transaction 之一，以便系统可以取得进展。你可以在应用程序级别通过 retry aborted transaction 来处理这种情况。

#### Automatically Detecting Lost Updates {#automatically-detecting-lost-updates}

atomic operation 和 lock 是通过强制 read-modify-write cycle 按顺序发生来防止 lost update 的方法。另一种选择是允许它们 parallel 执行，如果 transaction manager 检测到 lost update，则 abort transaction 并强制它 retry read-modify-write cycle。

这种方法的一个优点是数据库可以与snapshot isolation一起有效地执行此检查。实际上，PostgreSQL 的repeatable read、Oracle 的serializable和 SQL Server 的snapshot isolation级别会自动检测何时发生丢失的更新并中止有问题的事务。然而，MySQL/InnoDB 的repeatable read不检测丢失的更新[^29] [^41]。一些作者[^36] [^38] 认为数据库必须防止丢失的更新才能提供snapshot isolation，因此根据这个定义，MySQL 不提供snapshot isolation。

丢失更新检测是一个很好的功能，因为它不需要应用程序代码使用任何特殊的数据库功能——你可能忘记使用锁或原子操作从而引入错误，但丢失更新检测会自动发生，因此不太容易出错。但是，你还必须在应用程序级别重试中止的事务。

#### Conditional Write（Compare-and-Set） {#sec_transactions_compare_and_set}

在不提供 transaction 的数据库中，你有时会发现一个 *conditional write* 操作，它可以通过仅在 value 自你上次读取以来未更改时才允许 update 来防止 lost update（之前在["Single-Object Write"](#sec_transactions_single_object)中提到）。如果 current value 与你之前读取的不匹配，则 update 无效，必须 retry read-modify-write cycle。它是许多 CPU 支持的 atomic *compare-and-set* 或 *compare-and-swap*（CAS）指令的数据库等价物。

例如，为了防止两个用户同时更新同一个 wiki 页面，你可以尝试类似这样的操作，期望仅当页面内容自用户开始编辑以来没有更改时才进行更新：

```sql
-- 这可能安全也可能不安全，取决于数据库实现
UPDATE wiki_pages SET content = 'new content'
    WHERE id = 1234 AND content = 'old content';
```

如果内容已更改并且不再匹配 `'old content'`，则此 update 将无效，因此你需要检查 update 是否生效并在必要时 retry。你也可以使用在每次 update 时递增的 version number column，并且仅在当前 version number 未更改时才应用 update，而不是比较完整内容。这种方法有时称为 *optimistic locking*[^52]。

请注意，如果另一个事务并发修改了 `content`，则根据 MVCC 可见性规则，新内容可能不可见（参见["观察一致快照的可见性规则"](#sec_transactions_mvcc_visibility)）。MVCC 的许多实现对此场景有可见性规则的例外，其中其他事务写入的值对 `UPDATE` 和 `DELETE` 查询的 `WHERE` 子句的评估可见，即使这些写入在快照中不可见。

#### Conflict Resolution 与 Replication {#conflict-resolution-and-replication}

在复制数据库中（参见[第 6 章](/ch6#ch_replication)），防止丢失的更新具有另一个维度：由于它们在多个节点上有数据副本，并且数据可能在不同节点上并发修改，因此需要采取一些额外的步骤来防止丢失的更新。

lock 和 conditional write 操作假设有一个最新的数据副本。然而，具有 multi-leader 或 leaderless replication 的数据库通常允许多个 write concurrently 发生并异步复制它们，因此它们不能保证有一个最新的数据副本。因此，基于 lock 或 conditional write 的技术在此上下文中不适用。（我们将在["线性一致性"](/ch10#sec_consistency_linearizability)中更详细地重新讨论这个问题。）

相反，如["处理冲突写入"](/ch6#sec_replication_write_conflicts)中所讨论的，此类复制数据库中的常见方法是允许并发写入创建值的多个冲突版本（也称为*兄弟节点*），并使用应用程序代码或特殊数据结构在事后解决和合并这些版本。

如果 update 是 *commutative*（也就是说，你可以在不同 replica 上以不同顺序应用它们，仍然得到相同结果），merge conflicting values 可以防止 lost update。例如，increment counter 或向 set 添加元素是 commutative operation。这就是 CRDT 背后的想法，我们在["CRDT 和操作转换"](/ch6#sec_replication_crdts)中遇到过。然而，某些操作（如 conditional write）不能成为 commutative。

另一方面，*last write wins*（LWW）这种 conflict resolution 方法容易丢失 update，如["最后写入胜利（丢弃并发写入）"](/ch6#sec_replication_lww)中所讨论的。不幸的是，LWW 是许多 replicated database 中的默认值。

### Write Skew 与 Phantom Read {#sec_transactions_write_skew}

在前面的部分中，我们看到了 *dirty write* 和 *lost update*，这是当不同 transaction concurrently 尝试写入相同 object 时可能发生的两种 race condition。为了避免 data corruption，需要防止这些 race condition：要么由数据库自动防止，要么通过 lock 或 atomic write operation 等手动保护措施。

然而，这并不是 concurrent writes 之间可能发生的潜在 race condition 列表的结尾。在本节中，我们将看到一些更微妙的 conflict 示例。

首先，想象这个例子：你正在为医生编写一个应用程序来管理他们在医院的值班班次。医院通常试图在任何时候都有几位医生值班，但绝对必须至少有一位医生值班。医生可以放弃他们的班次（例如，如果他们自己生病了），前提是该班次中至少有一位同事留在值班[^53] [^54]。

现在想象 Aaliyah 和 Bryce 是特定班次的两位值班医生。两人都感觉不舒服，所以他们都决定请假。不幸的是，他们碰巧大约在同一时间点击了下班的按钮。接下来发生的事情如[图 8-8](#fig_transactions_write_skew) 所示。

<a id="fig_transactions_write_skew"></a>

图 8-8. write skew导致应用程序错误的示例。

<img src="../../static/fig/ddia_0808.png" alt="图 8-8. write skew导致应用程序错误的示例。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


在每个事务中，你的应用程序首先检查当前是否有两个或更多医生在值班；如果是，它假设一个医生下班是安全的。由于数据库使用snapshot isolation，两个检查都返回 `2`，因此两个事务都继续到下一阶段。Aaliyah 更新她自己的记录让自己下班，Bryce 同样更新他自己的记录。两个事务都提交，现在没有医生值班。你至少有一个医生值班的要求被违反了。

#### Write Skew 的特征 {#characterizing-write-skew}

这种 anomaly 称为 *write skew*[^36]。它既不是 dirty write，也不是 lost update，因为两个 transaction 正在更新两个不同的 object（分别是 Aaliyah 和 Bryce 的值班记录）。这里发生 conflict 不太明显，但这绝对是一个 race condition：如果两个 transaction 一个接一个地运行，第二个医生将被阻止下班。异常行为只有在 transaction concurrently 运行时才可能。

你可以将write skew视为丢失更新问题的概括。如果两个事务读取相同的对象，然后更新其中一些对象（不同的事务可能更新不同的对象），就会发生write skew。在不同事务更新同一对象的特殊情况下，你会得到dirty write或丢失更新异常（取决于时机）。

我们看到有各种不同的方法可以防止丢失的更新。对于write skew，我们的选择更受限制：

* 原子单对象操作没有帮助，因为涉及多个对象。
* 不幸的是，你在某些snapshot isolation实现中发现的丢失更新的自动检测也没有帮助：write skew在 PostgreSQL 的repeatable read、MySQL/InnoDB 的repeatable read、Oracle 的serializable或 SQL Server 的snapshot isolation级别中不会自动检测到[^29]。自动防止write skew需要真正的serializable隔离（参见["serializable"](#sec_transactions_serializability)）。
* 某些数据库允许你配置 constraint，然后由数据库 enforce，例如 unique constraint、foreign key constraint 或对特定值的限制。但是，为了指定至少有一个医生必须值班，你需要一个涉及多个 object 的 constraint。大多数数据库没有对此类 constraint 的内置支持，但你可能能够使用 trigger 或 materialized view 实现它们，如["Consistency（一致性）"](#sec_transactions_acid_consistency)中所讨论的[^12]。
* 如果你不能使用 serializable isolation level，在这种情况下，第二好的选择可能是显式 lock transaction 所依赖的 row。在医生示例中，你可以编写如下内容：

    ```sql
    BEGIN TRANSACTION;

    SELECT * FROM doctors
        WHERE on_call = true
        AND shift_id = 1234 FOR UPDATE; ❶

    UPDATE doctors
       SET on_call = false
       WHERE name = 'Aaliyah'
       AND shift_id = 1234;

    COMMIT;
    ```

❶：和以前一样，`FOR UPDATE` 告诉数据库锁定此查询返回的所有行。

#### Write Skew 的更多例子 {#more-examples-of-write-skew}

write skew起初可能看起来是一个深奥的问题，但一旦你意识到它，你可能会注意到更多可能发生的情况。以下是更多示例：

会议室预订系统
: 假设你想强制同一会议室在同一时间不能有两个预订[^55]。当有人想要预订时，你首先检查是否有任何冲突的预订（即，具有重叠时间范围的同一房间的预订），如果没有找到，你就创建会议（参见[例 8-2](#fig_transactions_meeting_rooms)）。
    
    {{< figure id="fig_transactions_meeting_rooms" title="例 8-2. 会议室预订系统试图避免重复预订（在snapshot isolation下不安全）" class="w-full my-4" >}}
    
    ```sql
    BEGIN TRANSACTION;
    
    -- 检查是否有任何现有预订与中午 12 点到 1 点的时间段重叠
    SELECT COUNT(*) FROM bookings
    WHERE room_id = 123 AND
    end_time > '2025-01-01 12:00' AND start_time < '2025-01-01 13:00';
    
    -- 如果前一个查询返回零：
    INSERT INTO bookings (room_id, start_time, end_time, user_id)
    VALUES (123, '2025-01-01 12:00', '2025-01-01 13:00', 666);
    
    COMMIT;
    ```

     不幸的是，snapshot isolation不会阻止另一个用户并发插入冲突的会议。为了保证你不会出现调度冲突，你再次需要serializable隔离。

多人游戏
: 在[例 8-1](#fig_transactions_select_for_update) 中，我们使用锁来防止丢失的更新（即，确保两个玩家不能同时移动同一个棋子）。但是，锁不会阻止玩家将两个不同的棋子移动到棋盘上的同一位置，或者可能做出违反游戏规则的其他移动。根据你要执行的规则类型，你可能能够使用唯一约束，但否则你很容易受到write skew的影响。

声明用户名
: 在每个用户都有唯一用户名的网站上，两个用户可能同时尝试使用相同的用户名创建账户。你可以使用事务来检查名称是否被占用，如果没有，使用该名称创建账户。但是，就像前面的例子一样，这在snapshot isolation下是不安全的。幸运的是，唯一约束在这里是一个简单的解决方案（尝试注册用户名的第二个事务将由于违反约束而被中止）。

防止重复消费
: 允许用户花钱或积分的服务需要检查用户不会花费超过他们拥有的。你可以通过在用户账户中插入暂定支出项目，列出账户中的所有项目，并检查总和是否为正来实现这一点。有了write skew，可能会发生两个支出项目并发插入，它们一起导致余额变为负数，但没有任何事务注意到另一个。

#### 导致 Write Skew 的 Phantom Read {#sec_transactions_phantom}

所有这些例子都遵循类似的模式：

1. `SELECT` 查询通过搜索匹配某些搜索条件的行来检查是否满足某些要求（至少有两个医生值班，该房间在该时间没有现有预订，棋盘上的位置还没有另一个棋子，用户名尚未被占用，账户中仍有钱）。
2. 根据第一个查询的结果，应用程序代码决定如何继续（也许继续操作，或者向用户报告错误并中止）。
3. 如果应用程序决定继续，它会向数据库进行写入（`INSERT`、`UPDATE` 或 `DELETE`）并提交事务。

 此写入的效果改变了步骤 2 决策的前提条件。换句话说，如果你在提交写入后重复步骤 1 的 `SELECT` 查询，你会得到不同的结果，因为写入改变了匹配搜索条件的行集（现在少了一个医生值班，会议室现在已为该时间预订，棋盘上的位置现在被移动的棋子占据，用户名现在被占用，账户中的钱现在更少）。

步骤可能以不同的顺序发生。例如，你可以先进行写入，然后进行 `SELECT` 查询，最后根据查询结果决定是中止还是提交。

在医生值班示例的情况下，步骤 3 中被修改的行是步骤 1 中返回的行之一，因此我们可以通过锁定步骤 1 中的行（`SELECT FOR UPDATE`）来使事务安全并避免write skew。但是，其他四个示例是不同的：它们检查*不存在*匹配某些搜索条件的行，而写入*添加*了匹配相同条件的行。如果步骤 1 中的查询不返回任何行，`SELECT FOR UPDATE` 就无法附加锁[^56]。

这种效果，也就是一个 transaction 中的 write 改变另一个 transaction 中 search query 的结果，称为 *phantom read*[^4]。snapshot isolation 避免了 read-only query 中的 phantom read，但在我们讨论的 read-write transaction 中，phantom read 可能导致特别棘手的 write skew。ORM 生成的 SQL 也容易出现 write skew[^50] [^51]。

#### Materializing Conflicts {#materializing-conflicts}

如果phantom read的问题是没有对象可以附加锁，也许我们可以在数据库中人为地引入一个锁对象？

例如，在会议室预订情况下，你可以想象创建一个时间段和房间的表。此表中的每一行对应于特定时间段（例如，15 分钟）的特定房间。你提前为所有可能的房间和时间段组合创建行，例如，接下来的六个月。

现在，想要创建预订的事务可以锁定（`SELECT FOR UPDATE`）表中对应于所需房间和时间段的行。获取锁后，它可以像以前一样检查重叠的预订并插入新的预订。请注意，附加表不用于存储有关预订的信息——它纯粹是一组锁，用于防止同一房间和时间范围的预订被并发修改。

这种方法称为 *materializing conflicts*，因为它采用 phantom read，并将其转化为存在于数据库中的具体 row set 上的 lock conflict[^14]。不幸的是，弄清楚如何 materialize conflicts 很难且容易出错，而且让 concurrency control 机制泄漏到应用程序 data model 中也很丑。出于这些原因，如果没有其他选择，materializing conflicts 应被视为 last resort。在大多数情况下，serializable isolation level 要好得多。



## Serializable {#sec_transactions_serializability}

在本章中，我们已经看到了几个容易出现 race condition 的 transaction 示例。某些 race condition 被 read committed 和 snapshot isolation level 所防止，但其他的则没有。我们遇到了一些特别棘手的 write skew 和 phantom read 示例。这是一个令人沮丧的情况：

* isolation level 很难理解，并且在不同数据库中的实现不一致，例如 "repeatable read" 的含义差异很大。
* 如果你查看应用程序代码，很难判断在特定 isolation level 下运行是否安全，特别是在大型应用程序中，你可能不知道所有可能 concurrently 发生的事情。
* 没有好的工具来帮助我们检测 race condition。原则上，static analysis 可能有所帮助[^33]，但研究技术尚未进入实际使用。测试 concurrency 问题很困难，因为它们通常是 nondeterministic 的：只有在时机不巧时才会出现问题。

这不是一个新问题：自 1970 年代引入 weak isolation levels 以来一直如此[^3]。一直以来，研究人员的答案都很简单：使用 *serializable* isolation！

serializable isolation 是最强的 isolation level。它保证即使 transaction 可能 parallel 执行，最终结果也与它们 *serially* 执行（一次一个，没有任何 concurrency）相同。因此，数据库保证如果 transaction 在单独运行时行为正确，那么在 concurrently 运行时它们继续保持正确。换句话说，数据库防止了*所有*可能的 race condition。

但如果 serializable isolation 比 weak isolation levels 的混乱要好得多，那为什么不是每个人都在使用它？要回答这个问题，我们需要查看实现 serializable 的选项，以及它们的 performance 如何。今天提供 serializable 的大多数数据库使用以下三种技术之一，我们将在本章的其余部分探讨：

* 字面上 serial execution of transactions（参见["实际串行执行"](#sec_transactions_serial)）
* two-phase locking（参见["two-phase locking (2PL)"](#sec_transactions_2pl)），几十年来这是唯一可行的选择
* optimistic concurrency control 技术，如 serializable snapshot isolation（参见["Serializable Snapshot Isolation（SSI）"](#sec_transactions_ssi)）

### 实际串行执行 {#sec_transactions_serial}

避免并发问题的最简单方法是完全消除并发：在单个线程上按串行顺序一次执行一个事务。通过这样做，我们完全回避了检测和防止事务之间冲突的问题：所产生的隔离根据定义是serializable的。

尽管这似乎是一个显而易见的想法，但直到 2000 年代，数据库设计者才决定执行事务的单线程循环是可行的[^57]。如果在过去 30 年中多线程并发被认为是获得良好性能的必要条件，那是什么改变使得单线程执行成为可能？

两个发展导致了这种重新思考：

* RAM 变得足够便宜，对于许多用例，现在可以将整个活动数据集保存在内存中（参见["将所有内容保存在内存中"](/ch4#sec_storage_inmemory)）。当事务需要访问的所有数据都在内存中时，事务的执行速度比必须等待从磁盘加载数据要快得多。
* 数据库设计者意识到 OLTP 事务通常很短，只进行少量读写（参见["分析与运营系统"](/ch1#sec_introduction_analytics)）。相比之下，长时间运行的分析查询通常是只读的，因此它们可以在串行执行循环之外的一致快照上运行（使用snapshot isolation）。

串行执行事务的方法在 VoltDB/H-Store、Redis 和 Datomic 等中实现[^58] [^59] [^60]。为单线程执行设计的系统有时可以比支持并发的系统性能更好，因为它可以避免锁定的协调开销。但是，其吞吐量限于单个 CPU 核心。为了充分利用该单线程，事务需要以不同于传统形式的方式构建。

#### 将 Transaction 封装在 Stored Procedure 中 {#encapsulating-transactions-in-stored-procedures}

在数据库的早期，意图是数据库事务可以包含整个用户活动流程。例如，预订机票是一个多阶段过程（搜索路线、票价和可用座位；决定行程；预订行程中每个航班的座位；输入乘客详细信息；付款）。数据库设计者认为，如果整个过程是一个事务，以便可以原子地提交，那将是很好的。

不幸的是，人类做决定和响应的速度非常慢。如果数据库事务需要等待用户的输入，数据库需要支持潜在的大量并发事务，其中大多数是空闲的。大多数数据库无法有效地做到这一点，因此几乎所有 OLTP 应用程序都通过避免在事务中交互式地等待用户来保持事务简短。在 Web 上，这意味着事务在同一 HTTP 请求中提交——事务不跨越多个请求。新的 HTTP 请求开始新的事务。

即使人类已经从关键路径中移除，事务仍然以交互式客户端/服务器风格执行，一次一个语句。应用程序进行查询，读取结果，可能根据第一个查询的结果进行另一个查询，依此类推。查询和结果在应用程序代码（在一台机器上运行）和数据库服务器（在另一台机器上）之间来回发送。

在这种交互式事务风格中，大量时间花在应用程序和数据库之间的网络通信上。如果你要在数据库中禁止并发并一次只处理一个事务，吞吐量将是可怕的，因为数据库将大部分时间都在等待应用程序为当前事务发出下一个查询。在这种数据库中，为了获得合理的性能，必须并发处理多个事务。

因此，具有 single-threaded serial transaction processing 的系统不允许 interactive multi-statement transaction。相反，应用程序必须将自己限制为包含单个 statement 的 transaction，或者提前将整个 transaction code 作为 *stored procedure* 提交给数据库[^61]。

interactive transaction 和 stored procedure 之间的差异如[图 8-9](#fig_transactions_stored_proc) 所示。前提是 transaction 所需的所有数据都在 memory 中，stored procedure 可以非常快速地执行，而无需等待任何 network 或 disk I/O。

<a id="fig_transactions_stored_proc"></a>

图 8-9. interactive transaction 和 stored procedure 之间的差异（使用[图 8-8](#fig_transactions_write_skew)的示例 transaction）。

![图 8-9. interactive transaction 和 stored procedure 之间的差异（使用[图 8-8](#fig_transactions_write_skew)的示例 transaction）。](../../static/fig/ddia_0809.png)

#### Stored Procedure 的利弊 {#sec_transactions_stored_proc_tradeoffs}

stored procedure 在 relational database 中已经存在了一段时间，自 1999 年以来一直是 SQL 标准（SQL/PSM）的一部分。它们因各种原因获得了一些不好的声誉：

* 传统上，每个数据库供应商都有自己的 stored procedure language（Oracle 有 PL/SQL，SQL Server 有 T-SQL，PostgreSQL 有 PL/pgSQL 等）。这些语言没有跟上 general-purpose programming language 的发展，因此从今天的角度来看，它们看起来相当丑陋和过时，并且缺乏大多数 programming language 中的 library ecosystem。
* 在数据库中运行的代码很难管理：与应用程序服务器相比，调试更困难，版本控制和部署更尴尬，测试更棘手，并且难以与监控的指标收集系统集成。
* 数据库通常比 application server 对 performance 更敏感，因为单个 database instance 通常由许多 application server 共享。数据库中编写不当的 stored procedure（例如，使用大量 memory 或 CPU time）可能比 application server 中等效的糟糕代码造成更多麻烦。
* 在允许 tenant 编写自己的 stored procedure 的 multi-tenant system 中，在与 database kernel 相同的 process 中执行 untrusted code 是一个 security risk[^62]。

然而，这些问题可以克服。stored procedure 的现代实现已经放弃了 PL/SQL，而是使用现有的 general-purpose programming language：VoltDB 使用 Java 或 Groovy，Datomic 使用 Java 或 Clojure，Redis 使用 Lua，MongoDB 使用 Javascript。

stored procedure 在 application logic 无法轻松嵌入其他地方时也很有用。例如，使用 GraphQL 的应用程序可能通过 GraphQL proxy 直接公开其数据库。如果 proxy 不支持复杂的 validation logic，你可以使用 stored procedure 将此类 logic 直接嵌入数据库中。如果数据库不支持 stored procedure，你必须在 proxy 和数据库之间部署 validation service。

使用 stored procedure 和 in-memory data，在单个线程上执行所有 transaction 变得可行。当 stored procedure 不需要等待 I/O 并避免其他 concurrency control 机制的 overhead 时，它们可以在单个线程上实现相当好的 throughput。

VoltDB 还使用 stored procedure 进行 replication：它不是将 transaction 的 write 从一个节点复制到另一个节点，而是在每个 replica 上执行相同的 stored procedure。因此，VoltDB 要求 stored procedure 是 *deterministic*（在不同节点上运行时，它们必须产生相同结果）。例如，如果 transaction 需要使用当前日期和时间，它必须通过特殊的 deterministic API 来实现（有关 deterministic operation 的更多详细信息，请参见["持久执行和工作流"](/ch5#sec_encoding_dataflow_workflows)）。这种方法称为 *state machine replication*，我们将在[第 10 章](/ch10#ch_consistency)中回到它。

#### 分片 {#sharding}

serial execution of transactions 使 concurrency control 变得简单得多，但将数据库的 transaction throughput 限制为单台机器上单个 CPU 核心的速度。read-only transaction 可以使用 snapshot isolation 在其他地方执行，但对于具有 high write throughput 的应用程序，single-threaded transaction processor 可能成为严重瓶颈。

为了扩展到多个 CPU 核心和多个节点，你可以对数据进行分片（参见[第 7 章](/ch7#ch_sharding)），VoltDB 支持这一点。如果你可以找到一种对数据集进行分片的方法，使每个事务只需要读取和写入单个分片内的数据，那么每个分片可以有自己的事务处理线程，独立于其他分片运行。在这种情况下，你可以给每个 CPU 核心分配自己的分片，这允许你的事务吞吐量与 CPU 核心数量线性扩展[^59]。

但是，对于需要访问多个 shard 的任何 transaction，数据库必须协调它所涉及的所有 shard 之间的 transaction。stored procedure 需要在所有 shard 上同步执行，以确保整个系统 serializable。

由于 cross-shard transaction 具有额外的 coordination overhead，因此它们比 single-shard transaction 慢得多。VoltDB 报告的 cross-shard write throughput 约为每秒 1,000 次，这比其 single-shard throughput 低几个数量级，并且无法通过添加更多机器来增加[^61]。最近的研究探索了使 multi-shard transaction 更具 scalability 的方法[^63]。

transaction 是否可以是 single-shard 的，很大程度上取决于应用程序使用的数据结构。简单的 key-value data 通常可以很容易地 shard，但具有多个 secondary index 的数据可能需要大量 cross-shard coordination（参见["分片和二级索引"](/ch7#sec_sharding_secondary_indexes)）。

#### 串行执行总结 {#summary-of-serial-execution}

串行执行事务已成为在某些约束条件下实现serializable隔离的可行方法：

* 每个事务必须小而快，因为只需要一个缓慢的事务就可以阻止所有事务处理。
* 它最适合活动数据集可以适合内存的情况。很少访问的数据可能会移到磁盘，但如果需要在单线程事务中访问，系统会变得非常慢。
* 写入吞吐量必须足够低，可以在单个 CPU 核心上处理，否则事务需要分片而不需要跨分片协调。
* 跨分片事务是可能的，但它们的吞吐量很难扩展。

### two-phase locking (2PL) {#sec_transactions_2pl}

大约 30 年来，数据库中只有一种广泛使用的serializable算法：*two-phase locking*（2PL），有时称为*强严格two-phase locking*（SS2PL），以区别于 2PL 的其他变体。


--------

> [!TIP] 2PL 不是 2PC

Two-phase *locking* (2PL) and two-phase *commit* (2PC) are two very different things. 2PL provides serializable isolation, while 2PC provides atomic commit in distributed databases (see ["two-phase commit (2PC)"](#sec_transactions_2pc)). To avoid confusion, it is best to treat them as completely independent concepts and ignore the unfortunate similarity in their names.

--------

我们之前看到锁通常用于防止dirty write（参见["没有dirty write"](#sec_transactions_dirty_write)）：如果两个事务并发尝试写入同一对象，锁确保第二个写入者必须等到第一个完成其事务（中止或提交）后才能继续。

two-phase locking类似，但使锁要求更强。只要没有人写入，多个事务就可以并发读取同一对象。但是一旦有人想要写入（修改或删除）对象，就需要独占访问：

* 如果事务 A 已读取对象而事务 B 想要写入该对象，B 必须等到 A 提交或中止后才能继续。（这确保 B 不能在 A 背后意外地更改对象。）
* 如果事务 A 已写入对象而事务 B 想要读取该对象，B 必须等到 A 提交或中止后才能继续。（像[图 8-4](#fig_transactions_read_committed) 中那样读取对象的旧版本在 2PL 下是不可接受的。）

在 2PL 中，writer 不仅 block 其他 writer；它们还 block reader，反之亦然。snapshot isolation 有这样的口号：*reader 永远不会 block writer，writer 永远不会 block reader*（参见["multi-version concurrency control (MVCC)"](#sec_transactions_snapshot_impl)），这捕捉了 snapshot isolation 和 two-phase locking 之间的关键区别。另一方面，因为 2PL 提供 serializable，它可以防止前面讨论的所有 race condition，包括 lost update 和 write skew。

#### Implementing Two-Phase Locking {#implementation-of-two-phase-locking}

2PL 由 MySQL（InnoDB）和 SQL Server 中的 serializable isolation level，以及 Db2 中的 repeatable read isolation level 使用[^29]。

读者和写者的阻塞是通过在数据库中的每个对象上有一个锁来实现的。锁可以处于*共享模式*或*独占模式*（也称为*多读者单写者*锁）。锁的使用如下：

* 如果 transaction 想要读取 object，它必须首先以 shared mode 获取 lock。多个 transaction 可以同时以 shared mode 持有 lock，但如果另一个 transaction 已经对该 object 具有 exclusive lock，则这些 transaction 必须等待。
* 如果 transaction 想要写入 object，它必须首先以 exclusive mode 获取 lock。没有其他 transaction 可以同时持有 lock（无论是 shared mode 还是 exclusive mode），因此如果 object 上有任何现有 lock，transaction 必须等待。
* 如果 transaction 首先读取然后写入 object，它可以将其 shared lock 升级为 exclusive lock。升级的工作方式与直接获取 exclusive lock 相同。
* 获取 lock 后，transaction 必须继续持有 lock 直到 transaction 结束（commit 或 abort）。这就是 "two-phase" 名称的来源：第一阶段（transaction 执行时）是获取 lock，第二阶段（transaction 结束时）是释放所有 lock。

由于使用了如此多的 lock，很容易发生 transaction A 等待 transaction B 释放其 lock，反之亦然的情况。这种情况称为 *deadlock*。数据库自动检测 transaction 之间的 deadlock 并 abort 其中一个，以便其他 transaction 可以取得进展。aborted transaction 需要由应用程序 retry。

#### Two-Phase Locking 的性能 {#performance-of-two-phase-locking}

two-phase locking 的主要缺点，也是自 1970 年代以来并非每个人都使用它的原因，是 performance：在 two-phase locking 下，transaction throughput 和 query response time 明显比 weak isolation 下差。

这部分是由于获取和释放所有这些 lock 的 overhead，但更重要的是 concurrency 降低。按设计，如果两个 concurrent transaction 尝试执行任何可能以某种方式导致 race condition 的 operation，其中一个必须等待另一个完成。

例如，如果你有一个需要读取整个 table 的 transaction（例如 backup、analytic query 或 integrity check，如["Snapshot Isolation 与 Repeatable Read"](#sec_transactions_snapshot_isolation)中所讨论的），该 transaction 必须对整个 table 获取 shared lock。因此，read transaction 首先必须等到所有正在 write 该 table 的 in-progress transaction 完成；然后，在读取整个 table 时（对于大表可能需要很长时间），所有想要 write 该 table 的其他 transaction 都被 block，直到大型 read-only transaction commit。实际上，数据库在很长一段时间内无法进行 write。

因此，运行 2PL 的数据库可能具有相当不稳定的 latency；如果 workload 中存在 contention，它们在 high percentile 上可能非常慢（参见["描述性能"](/ch2#sec_introduction_percentiles)）。可能只需要一个 slow transaction，或者一个访问大量数据并获取许多 lock 的 transaction，就会导致系统的其余部分停滞不前。

尽管 deadlock 可能发生在基于 lock 的 read committed isolation level 下，但在 2PL serializable isolation 下（取决于 transaction 的 access pattern）它们发生得更频繁。这可能是一个额外的 performance 问题：当 transaction 由于 deadlock 而被 abort 并 retry 时，它需要重新完成所有 work。如果 deadlock 频繁，这可能意味着大量 wasted effort。

#### Predicate Lock {#predicate-locks}

在前面的 lock 描述中，我们掩盖了一个微妙但重要的细节。在["导致 Write Skew 的 Phantom Read"](#sec_transactions_phantom)中，我们讨论了 *phantom read* 问题：一个 transaction 改变另一个 transaction 的 search query result。具有 serializable isolation 的数据库必须防止 phantom read。

在会议室预订示例中，这意味着如果一个 transaction 已经搜索了某个 time window 内某个 room 的 existing booking（参见[例 8-2](#fig_transactions_meeting_rooms)），另一个 transaction 不允许 concurrently insert 或 update 同一 room 和 time range 的另一个 booking。（concurrently insert 其他 room 的 booking，或同一 room 不影响拟议 booking 的不同时间的 booking 是可以的。）

我们如何实现这一点？从概念上讲，我们需要一个 *predicate lock*[^4]。它的工作方式类似于前面描述的 shared/exclusive lock，但它不属于特定 object（例如 table 中的一行），而是属于匹配某些 search condition 的所有 object，例如：

```
SELECT * FROM bookings
 WHERE room_id = 123 AND
 end_time > '2025-01-01 12:00' AND
 start_time < '2025-01-01 13:00';
```

predicate lock 限制访问如下：

* 如果 transaction A 想要读取匹配某些 condition 的 object，就像在该 `SELECT` query 中一样，它必须在 query condition 上获取 shared-mode predicate lock。如果另一个 transaction B 当前对匹配这些 condition 的任何 object 具有 exclusive lock，A 必须等到 B 释放其 lock 后才允许进行 query。
* 如果 transaction A 想要 insert、update 或 delete 任何 object，它必须首先检查 old value 或 new value 是否匹配任何现有的 predicate lock。如果存在 transaction B 持有的 matching predicate lock，则 A 必须等到 B commit 或 abort 后才能继续。

这里的关键思想是，predicate lock 甚至适用于数据库中尚不存在但将来可能添加的 object（phantom read）。如果 two-phase locking 包括 predicate lock，数据库将防止所有形式的 write skew 和其他 race condition，因此其 isolation 变为 serializable。

#### Index-Range Lock {#sec_transactions_2pl_range}

不幸的是，predicate lock 的 performance 不佳：如果 active transaction 有许多 lock，检查 matching lock 会变得耗时。因此，大多数具有 2PL 的数据库实际上实现了 *index-range locking*（也称为 *gap locking*），这是 predicate locking 的简化近似[^54] [^64]。

通过使 predicate 匹配更大的 object set 来简化 predicate 是安全的。例如，如果你对中午到下午 1 点之间房间 123 的 booking 有 predicate lock，你可以通过 lock 房间 123 在任何时间的 booking 来近似它，或者通过 lock 中午到下午 1 点之间的所有房间（不仅仅是房间 123）来近似它。这是安全的，因为匹配原始 predicate 的任何 write 肯定也会匹配近似。

在房间预订数据库中，你可能在 `room_id` 列上有索引，和/或在 `start_time` 和 `end_time` 上有索引（否则前面的查询在大型数据库上会非常慢）：

* 假设你的 index 在 `room_id` 上，数据库使用此 index 查找房间 123 的 existing booking。现在数据库可以简单地将 shared lock 附加到此 index entry，表示 transaction 已搜索房间 123 的 booking。
* 或者，如果数据库使用基于 time 的 index 查找 existing booking，它可以将 shared lock 附加到该 index 中的 value range，表示 transaction 已搜索与 2025 年 1 月 1 日中午到下午 1 点的 time range 重叠的 booking。

无论哪种方式，search condition 的近似都附加到其中一个 index。现在，如果另一个 transaction 想要 insert、update 或 delete 同一 room 和/或 overlapping time range 的 booking，它将必须 update index 的相同部分。在这样做的过程中，它将遇到 shared lock，并被迫等到 lock 被释放。

这提供了对 phantom read 和 write skew 的有效保护。index-range lock 不如 predicate lock 精确（它们可能 lock 比严格维护 serializable 所需的更大范围的 object），但由于它们的 overhead 要低得多，它们是一个很好的 trade-off。

如果没有合适的 index 可以附加 range lock，数据库可以退回到整个 table 的 shared lock。这对 performance 不利，因为它将阻止所有其他 transaction write table，但这是一个安全的 fallback。

### Serializable Snapshot Isolation（SSI） {#sec_transactions_ssi}

本章描绘了 database concurrency control 的黯淡画面。一方面，我们有 performance 不佳（two-phase locking）或 scalability 不佳（serial execution）的 serializable 实现。另一方面，我们有 performance 良好但容易出现各种 race condition（lost update、write skew、phantom read 等）的 weak isolation levels。serializable isolation 和良好 performance 从根本上是对立的吗？

似乎不是：一种称为 *serializable snapshot isolation*（SSI）的算法提供完全 serializable，与 snapshot isolation 相比只有很小的 performance cost。SSI 相对较新：它于 2008 年首次描述[^53] [^65]。

今天，SSI 和类似算法用于单节点数据库（PostgreSQL 中的 serializable isolation level[^54]、SQL Server 的 in-memory OLTP/Hekaton[^66] 和 HyPer[^67]）、distributed database（CockroachDB[^5] 和 FoundationDB[^8]）以及 embedded storage engine（如 BadgerDB）。

#### Pessimistic 与 Optimistic Concurrency Control {#pessimistic-versus-optimistic-concurrency-control}

two-phase locking 是所谓的 *pessimistic* concurrency control 机制：它基于这样的原则，即如果任何事情可能出错（如另一个 transaction 持有的 lock 所示），最好等到情况再次安全后再做任何事情。它就像 *mutual exclusion*，用于保护多线程编程中的 data structure。

serial execution 在某种意义上是 pessimistic 到极端：它本质上相当于每个 transaction 在 transaction 期间对整个数据库（或数据库的一个 shard）具有 exclusive lock。我们通过使每个 transaction 执行得非常快来补偿 pessimism，因此它只需要短时间持有 "lock"。

相比之下，serializable snapshot isolation 是一种 *optimistic* concurrency control 技术。在这种情况下，optimistic 意味着，如果发生潜在危险的事情，transaction 不会 block，而是继续进行，希望一切都会好起来。当 transaction 想要 commit 时，数据库会检查是否发生了任何不好的事情（即，是否违反了 isolation）；如果是，transaction 将被 abort 并必须 retry。只允许 serializable 的 transaction commit。

optimistic concurrency control 是一个老想法[^68]，其优缺点已经争论了很长时间[^69]。如果存在 high contention（许多 transaction 尝试访问相同的 object），它的 performance 很差，因为这会导致大部分 transaction 需要 abort。如果系统已经接近其 maximum throughput，retry transaction 带来的额外 load 可能会使 performance 变差。

但是，如果有足够的 spare capacity，并且 transaction 之间的 contention 不太高，optimistic concurrency control 技术往往比 pessimistic 技术 performance 更好。commutative atomic operation 可以减少 contention：例如，如果几个 transaction concurrently 想要 increment counter，应用 increment 的顺序无关紧要（只要 counter 在同一 transaction 中没有被读取），因此 concurrent increment 都可以应用而不会发生 conflict。

顾名思义，SSI 基于 snapshot isolation：也就是说，transaction 中的所有 read 都从数据库的 consistent snapshot 进行（参见["Snapshot Isolation 与 Repeatable Read"](#sec_transactions_snapshot_isolation)）。在 snapshot isolation 的基础上，SSI 添加了一种算法来检测 read/write 之间的 serializable conflict，并确定要 abort 哪些 transaction。

#### 基于过时前提的决策 {#decisions-based-on-an-outdated-premise}

当我们之前讨论snapshot isolation中的write skew时（参见["write skew与phantom read"](#sec_transactions_write_skew)），我们观察到一个反复出现的模式：事务从数据库读取一些数据，检查查询结果，并根据它看到的结果决定采取某些行动（写入数据库）。但是，在snapshot isolation下，原始查询的结果在事务提交时可能不再是最新的，因为数据可能在此期间被修改。

换句话说，事务基于*前提*（事务开始时为真的事实，例如，"当前有两名医生值班"）采取行动。后来，当事务想要提交时，原始数据可能已更改——前提可能不再为真。

当应用程序进行查询（例如，"当前有多少医生值班？"）时，数据库不知道应用程序逻辑如何使用该查询的结果。为了安全起见，数据库需要假设查询结果（前提）中的任何更改都意味着该事务中的写入可能无效。换句话说，事务中的查询和写入之间可能存在因果依赖关系。为了提供serializable隔离，数据库必须检测事务可能基于过时前提采取行动的情况，并在这种情况下中止事务。

数据库如何知道查询结果是否可能已更改？有两种情况需要考虑：

* 检测陈旧的 MVCC 对象版本的读取（未提交的写入发生在读取之前）
* 检测影响先前读取的写入（写入发生在读取之后）

#### 检测陈旧的 MVCC 读取 {#detecting-stale-mvcc-reads}

回想一下，snapshot isolation通常由multi-version concurrency control（MVCC；参见["multi-version concurrency control (MVCC)"](#sec_transactions_snapshot_impl)）实现。当事务从 MVCC 数据库中的一致快照读取时，它会忽略在拍摄快照时尚未提交的任何其他事务所做的写入。

在[图 8-10](#fig_transactions_detect_mvcc) 中，事务 43 看到 Aaliyah 的 `on_call = true`，因为事务 42（修改了 Aaliyah 的值班状态）未提交。但是，当事务 43 想要提交时，事务 42 已经提交。这意味着从一致快照读取时被忽略的写入现在已生效，事务 43 的前提不再为真。当写入者插入以前不存在的数据时，事情变得更加复杂（参见["导致write skew的phantom read"](#sec_transactions_phantom)）。我们将在["检测影响先前读取的写入"](#sec_detecting_writes_affect_reads)中讨论为 SSI 检测幻写。

<a id="fig_transactions_detect_mvcc"></a>

图 8-10. 检测事务何时从 MVCC 快照读取过时值。

<img src="../../static/fig/ddia_0810.png" alt="图 8-10. 检测事务何时从 MVCC 快照读取过时值。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


为了防止这种异常，数据库需要跟踪事务由于 MVCC 可见性规则而忽略另一个事务的写入的时间。当事务想要提交时，数据库会检查是否有任何被忽略的写入现在已经提交。如果是，事务必须被中止。

为什么要等到提交？为什么不在检测到陈旧读取时立即中止事务 43？好吧，如果事务 43 是只读事务，它就不需要被中止，因为没有write skew的风险。在事务 43 进行读取时，数据库还不知道该事务是否稍后会执行写入。此外，事务 42 可能还会中止，或者在事务 43 提交时可能仍未提交，因此读取可能最终不是陈旧的。通过避免不必要的中止，SSI 保留了snapshot isolation对从一致快照进行长时间运行读取的支持。

#### 检测影响先前读取的写入 {#sec_detecting_writes_affect_reads}

要考虑的第二种情况是另一个事务在数据被读取后修改数据。这种情况如[图 8-11](#fig_transactions_detect_index_range) 所示。

<a id="fig_transactions_detect_index_range"></a>

图 8-11. 在 serializable snapshot isolation 中，检测一个 transaction 何时修改另一个 transaction 的 read。

<img src="../../static/fig/ddia_0811.png" alt="图 8-11. 在 serializable snapshot isolation 中，检测一个 transaction 何时修改另一个 transaction 的 read。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


在two-phase locking的上下文中，我们讨论了index-range lock（参见["index-range lock"](#sec_transactions_2pl_range)），它允许数据库锁定对匹配某些搜索查询的所有行的访问，例如 `WHERE shift_id = 1234`。我们可以在这里使用类似的技术，除了 SSI 锁不会阻塞其他事务。

在[图 8-11](#fig_transactions_detect_index_range) 中，事务 42 和 43 都在班次 `1234` 期间搜索值班医生。如果 `shift_id` 上有索引，数据库可以使用索引条目 1234 来记录事务 42 和 43 读取此数据的事实。（如果没有索引，可以在表级别跟踪此信息。）此信息只需要保留一段时间：在事务完成（提交或中止）并且所有并发事务完成后，数据库可以忘记它读取的数据。

当事务写入数据库时，它必须在索引中查找最近读取受影响数据的任何其他事务。此过程类似于获取受影响键范围的写锁，但它不是阻塞直到读者提交，而是充当绊线：它只是通知事务它们读取的数据可能不再是最新的。

在[图 8-11](#fig_transactions_detect_index_range) 中，事务 43 通知事务 42 其先前的读取已过时，反之亦然。事务 42 首先提交，并且成功：尽管事务 43 的写入影响了 42，但 43 尚未提交，因此写入尚未生效。但是，当事务 43 想要提交时，来自 42 的冲突写入已经提交，因此 43 必须中止。

#### Serializable Snapshot Isolation 的性能 {#performance-of-serializable-snapshot-isolation}

与往常一样，许多工程细节会影响算法在实践中的工作效果。例如，一个权衡是跟踪事务读写的粒度。如果数据库详细跟踪每个事务的活动，它可以精确地确定哪些事务需要中止，但簿记开销可能变得很大。不太详细的跟踪速度更快，但可能导致比严格必要更多的事务被中止。

在某些情况下，事务读取被另一个事务覆盖的信息是可以的：根据发生的其他情况，有时可以证明执行结果仍然是serializable的。PostgreSQL 使用这一理论来减少不必要中止的数量[^14] [^54]。

与 two-phase locking 相比，serializable snapshot isolation 的主要优点是一个 transaction 不需要 block 等待另一个 transaction 持有的 lock。与 snapshot isolation 一样，writer 不会 block reader，反之亦然。这种设计原则使 query latency 更可预测且变化更少。特别是，read-only query 可以在 consistent snapshot 上运行而无需任何 lock，这对于 read-heavy workload 非常有吸引力。

与 serial execution 相比，serializable snapshot isolation 不限于单个 CPU 核心的 throughput：例如，FoundationDB 将 serializable conflict detection 分布在多台机器上，允许它扩展到非常高的 throughput。即使数据可能 sharded 在多台机器上，transaction 也可以在多个 shard 中 read 和 write 数据，同时确保 serializable isolation。

与非 serializable snapshot isolation 相比，检查 serializable violation 的需要引入了一些 performance overhead。这些 overhead 有多大是一个争论的问题：有些人认为 serializable check 不值得[^70]，而其他人认为 serializable 的 performance 现在已经很好，不再需要使用较弱的 snapshot isolation[^67]。

中止率显著影响 SSI 的整体性能。例如，长时间读取和写入数据的事务可能会遇到冲突并中止，因此 SSI 要求读写事务相当短（长时间运行的只读事务是可以的）。但是，SSI 对慢事务的敏感性低于two-phase locking或串行执行。

## 分布式事务 {#sec_transactions_distributed}

前几节重点讨论了 isolation 的 concurrency control，也就是 ACID 中的 I。我们看到的算法适用于单节点和 distributed database：尽管在使 concurrency control algorithm 可扩展方面存在挑战（例如，为 SSI 执行 distributed serializable check），但 distributed concurrency control 的高层思想与单节点 concurrency control 相似[^8]。

Consistency 和 durability 在转向 distributed transaction 时也没有太大变化。但是，atomicity 需要更多关注。

对于在单个数据库节点执行的 transaction，atomicity 通常由 storage engine 实现。当 client 要求数据库节点 commit transaction 时，数据库使 transaction 的 write durable（通常在 write-ahead log 中；参见["使 B 树可靠"](/ch4#sec_storage_btree_wal)），然后将 commit record 附加到磁盘上的 log。如果数据库在此过程中 crash，transaction 将在节点重新启动时从 log 中恢复：如果 commit record 在 crash 前成功写入磁盘，则 transaction 被认为已 commit；如果没有，该 transaction 的任何 write 都将 rollback。

因此，在单个节点上，事务提交关键取决于数据持久写入磁盘的*顺序*：首先是数据，然后是提交记录[^22]。事务提交或中止的关键决定时刻是磁盘完成写入提交记录的时刻：在那一刻之前，仍然可能中止（由于崩溃），但在那一刻之后，事务已提交（即使数据库崩溃）。因此，是单个设备（连接到特定节点的特定磁盘驱动器的控制器）使提交成为原子的。

但是，如果多个节点参与 transaction 会怎样？例如，也许你在 sharded database 中有 multi-object transaction，或者有 global secondary index（其中 index entry 可能与 primary data 在不同的节点上；参见["分片和二级索引"](/ch7#sec_sharding_secondary_indexes)）。大多数 "NoSQL" distributed data store 不支持此类 distributed transaction，但各种 distributed relational database 支持。

在这些情况下，仅向所有节点发送提交请求并在每个节点上独立提交事务是不够的。如[图 8-12](#fig_transactions_non_atomic) 所示，提交可能在某些节点上成功，在其他节点上失败：

* 某些节点可能检测到约束违规或冲突，需要中止，而其他节点能够成功提交。
* 某些提交请求可能在网络中丢失，最终由于超时而中止，而其他提交请求通过。
* 某些节点可能在提交记录完全写入之前崩溃并在恢复时回滚，而其他节点成功提交。

<a id="fig_transactions_non_atomic"></a>

图 8-12. 当事务涉及多个数据库节点时，它可能在某些节点上提交，在其他节点上失败。

<img src="../../static/fig/ddia_0812.png" alt="图 8-12. 当事务涉及多个数据库节点时，它可能在某些节点上提交，在其他节点上失败。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


如果某些节点提交事务而其他节点中止它，节点之间就会变得不一致。一旦事务在一个节点上提交，如果后来发现它在另一个节点上被中止，就不能撤回了。这是因为一旦数据被提交，它在*read committed*或更强的隔离下对其他事务可见。例如，在[图 8-12](#fig_transactions_non_atomic) 中，当用户 1 注意到其在数据库 1 上的提交失败时，用户 2 已经从数据库 2 上的同一事务读取了数据。如果用户 1 的事务后来被中止，用户 2 的事务也必须被还原，因为它基于被追溯声明不存在的数据。

更好的方法是确保参与事务的节点要么全部提交，要么全部中止，并防止两者的混合。确保这一点被称为*atomic commit*问题。

### two-phase commit (2PC) {#sec_transactions_2pc}

two-phase commit是一种跨多个节点实现原子事务提交的算法。它是分布式数据库中的经典算法[^13] [^71] [^72]。2PC 在某些数据库内部使用，也以 *XA 事务*[^73] 的形式提供给应用程序（例如，Java 事务 API 支持），或通过 WS-AtomicTransaction 用于 SOAP Web 服务[^74] [^75]。

2PC 的基本流程如[图 8-13](#fig_transactions_two_phase_commit) 所示。与单节点事务的单个提交请求不同，2PC 中的提交/中止过程分为两个阶段（因此得名）。

<a id="fig_transactions_two_phase_commit"></a>

图 8-13. two-phase commit (2PC)的成功执行。

<img src="../../static/fig/ddia_0813.png" alt="图 8-13. two-phase commit (2PC)的成功执行。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


2PC 使用一个通常不会出现在单节点事务中的新组件：*coordinator*（也称为*事务管理器*）。coordinator通常作为请求事务的同一应用程序进程中的库实现（例如，嵌入在 Java EE 容器中），但它也可以是单独的进程或服务。此类coordinator的示例包括 Narayana、JOTM、BTM 或 MSDTC。

使用 2PC 时，分布式事务从应用程序在多个数据库节点上正常读写数据开始。我们称这些数据库节点为事务中的*participant*。当应用程序准备提交时，coordinator开始第 1 阶段：它向每个节点发送*准备*请求，询问它们是否能够提交。然后coordinator跟踪participant的响应：

* 如果所有participant回复"是"，表示他们准备提交，那么coordinator在第 2 阶段发出*提交*请求，提交实际发生。
* 如果任何participant回复"否"，coordinator在第 2 阶段向所有节点发送*中止*请求。

这个过程有点像西方文化中的传统婚礼仪式：牧师分别询问新娘和新郎是否愿意嫁给对方，通常从两人那里得到"我愿意"的答案。在收到两个确认后，牧师宣布这对夫妇为夫妻：事务已提交，这个快乐的事实向所有参加者广播。如果新娘或新郎没有说"是"，仪式就被中止了[^76]。

#### 系统性的承诺 {#a-system-of-promises}

从这个简短的描述中，可能不清楚为什么 two-phase commit 能确保 atomicity，而跨多个节点的 one-phase commit 却不能。prepare 和 commit request 在 two-phase 情况下同样容易丢失。是什么让 2PC 不同？

要理解它为什么有效，我们必须更详细地分解这个过程：

1. 当应用程序想要开始分布式事务时，它从coordinator请求事务 ID。此事务 ID 是全局唯一的。
2. 应用程序在每个participant上开始单节点事务，并将全局唯一的事务 ID 附加到单节点事务。所有读写都在这些单节点事务之一中完成。如果在此阶段出现任何问题（例如，节点崩溃或请求超时），coordinator或任何participant都可以中止。
3. 当应用程序准备提交时，coordinator向所有participant发送准备请求，标记有全局事务 ID。如果这些请求中的任何一个失败或超时，coordinator向所有participant发送该事务 ID 的中止请求。
4. 当participant收到准备请求时，它确保它可以在任何情况下明确提交事务。

 这包括将所有事务数据写入磁盘（崩溃、电源故障或磁盘空间不足不是稍后拒绝提交的可接受借口），并检查任何冲突或约束违规。通过向coordinator回复"是"，节点承诺在请求时无错误地提交事务。换句话说，participant放弃了中止事务的权利，但没有实际提交它。
5. 当coordinator收到所有准备请求的响应时，它对是否提交或中止事务做出明确决定（仅当所有participant投票"是"时才提交）。coordinator必须将该决定写入其磁盘上的事务日志，以便在随后崩溃时知道它是如何决定的。这称为*commit point*。
6. 一旦coordinator的决定被写入磁盘，提交或中止请求就会发送给所有participant。如果此请求失败或超时，coordinator必须永远重试，直到成功。没有回头路：如果决定是提交，那么必须执行该决定，无论需要多少次重试。如果participant在此期间崩溃，事务将在恢复时提交——因为participant投票"是"，它在恢复时不能拒绝提交。

因此，该协议包含两个关键的"不归路"：当 participant 投票"是"时，它承诺自己肯定能够稍后 commit（尽管 coordinator 仍可能选择 abort）；一旦 coordinator 做出决定，该决定是不可撤销的。这些承诺确保了 2PC 的 atomicity。（单节点 atomic commit 将这两个事件合并为一个：将 commit record 写入 transaction log。）

回到婚姻比喻，在说"我愿意"之前，你和你的新娘/新郎有自由通过说"不行！"（或类似的话）来中止事务。但是，在说"我愿意"之后，你不能撤回该声明。如果你在说"我愿意"后晕倒，没有听到牧师说"你们现在是夫妻"，这并不改变事务已提交的事实。当你稍后恢复意识时，你可以通过向牧师查询你的全局事务 ID 的状态来了解你是否已婚，或者你可以等待牧师下一次重试提交请求（因为重试将在你失去意识期间继续）。

#### coordinator故障 {#coordinator-failure}

我们已经讨论了如果participant之一或网络在 2PC 期间失败会发生什么：如果任何准备请求失败或超时，coordinator将中止事务；如果任何提交或中止请求失败，coordinator将无限期地重试它们。但是，如果coordinator崩溃会发生什么就不太清楚了。

如果coordinator在发送准备请求之前失败，participant可以安全地中止事务。但是一旦participant收到准备请求并投票"是"，它就不能再单方面中止——它必须等待coordinator回复事务是提交还是中止。如果coordinator此时崩溃或网络失败，participant除了等待别无他法。participant在此状态下的事务称为*in-doubt*或*不确定*。

这种情况如[图 8-14](#fig_transactions_2pc_crash) 所示。在这个特定的例子中，coordinator实际上决定提交，数据库 2 收到了提交请求。但是，coordinator在向数据库 1 发送提交请求之前崩溃了，因此数据库 1 不知道是提交还是中止。即使超时在这里也没有帮助：如果数据库 1 在超时后单方面中止，它将与已提交的数据库 2 不一致。同样，单方面提交也不安全，因为另一个participant可能已中止。

<a id="fig_transactions_2pc_crash"></a>

图 8-14. coordinator在participant投票“是”后崩溃。数据库 1 不知道是提交还是中止。

<img src="../../static/fig/ddia_0814.png" alt="图 8-14. coordinator在participant投票“是”后崩溃。数据库 1 不知道是提交还是中止。" style="display: block; margin: 1rem auto; width: 100%; max-width: 720px;" />


没有coordinator的消息，participant无法知道是提交还是中止。原则上，participant可以相互通信，了解每个participant如何投票并达成某种协议，但这不是 2PC 协议的一部分。

2PC 完成的唯一方法是等待coordinator恢复。这就是为什么coordinator必须在向participant发送提交或中止请求之前将其提交或中止决定写入磁盘上的事务日志：当coordinator恢复时，它通过读取其事务日志来确定所有in-doubt事务的状态。coordinator日志中没有提交记录的任何事务都将中止。因此，2PC 的commit point归结为coordinator上的常规单节点atomic commit。

#### Three-Phase Commit {#three-phase-commit}

由于 2PC 可能会卡住等待coordinator恢复，因此two-phase commit被称为*阻塞*atomic commit协议。可以使atomic commit协议*非阻塞*，以便在节点失败时不会卡住。但是，在实践中使其工作并不那么简单。

作为 2PC 的替代方案，已经提出了一种称为 *three-phase commit*（3PC）的算法[^13] [^77]。但是，3PC 假设网络具有 bounded delay，节点具有 bounded response time；在大多数具有 unbounded network delay 和 process pause 的实际系统中（参见[第 9 章](/ch9#ch_distributed)），它无法保证 atomicity。

实践中更好的解决方案是用容错共识协议替换单节点coordinator。我们将在[第 10 章](/ch10#ch_consistency)中看到如何做到这一点。

### 跨不同系统的分布式事务 {#sec_transactions_xa}

分布式事务和two-phase commit的声誉参差不齐。一方面，它们被认为提供了一个重要的安全保证，否则很难实现；另一方面，它们因导致操作问题、扼杀性能并承诺超过它们可以提供的东西而受到批评[^78] [^79] [^80] [^81]。许多云服务由于它们引起的操作问题而选择不实现分布式事务[^82]。

某些分布式事务的实现会带来沉重的性能损失。two-phase commit固有的大部分性能成本是由于崩溃恢复所需的额外磁盘强制（`fsync`）和额外的网络往返。

但是，与其直接否定分布式事务，我们应该更详细地研究它们，因为从中可以学到重要的教训。首先，我们应该准确说明"分布式事务"的含义。两种完全不同类型的分布式事务经常被混淆：

数据库内部分布式事务
: 某些分布式数据库（即，在其标准配置中使用复制和分片的数据库）支持该数据库节点之间的内部事务。例如，YugabyteDB、TiDB、FoundationDB、Spanner、VoltDB 和 MySQL Cluster 的 NDB 存储引擎都有这样的内部事务支持。在这种情况下，参与事务的所有节点都运行相同的数据库软件。

异构分布式事务
: 在*异构*事务中，participant是两个或多个不同的技术：例如，来自不同供应商的两个数据库，甚至是非数据库系统（如消息代理）。跨这些系统的分布式事务必须确保atomic commit，即使系统在底层可能完全不同。

数据库内部事务不必与任何其他系统兼容，因此它们可以使用任何协议并应用特定于该特定技术的优化。因此，数据库内部分布式事务通常可以很好地工作。另一方面，跨异构技术的事务更具挑战性。

#### exactly-once消息处理 {#sec_transactions_exactly_once}

异构分布式事务允许以强大的方式集成各种系统。例如，当且仅当处理消息的数据库事务成功提交时，来自消息队列的消息才能被确认为已处理。这是通过在单个事务中原子地提交消息确认和数据库写入来实现的。有了分布式事务支持，即使消息代理和数据库是在不同机器上运行的两种不相关的技术，这也是可能的。

如果 message delivery 或 database transaction 失败，两者都会 abort，因此 message broker 可以稍后安全地 redeliver message。因此，通过 atomically commit message 及其处理副作用，我们可以确保 message 在效果上 *exactly once* 被处理，即使在成功之前需要几次 retry。abort 会丢弃 partially completed transaction 的任何 side effect。这被称为 *exactly-once semantics*。

但是，只有当受事务影响的所有系统都能够使用相同的atomic commit协议时，这种分布式事务才有可能。例如，假设处理消息的副作用是发送电子邮件，而电子邮件服务器不支持two-phase commit：如果消息处理失败并重试，可能会发生电子邮件被发送两次或更多次。但是，如果处理消息的所有副作用在事务中止时都会回滚，那么处理步骤可以安全地重试，就好像什么都没有发生一样。

我们将在本章后面回到exactly-once语义的主题。让我们首先看看允许此类异构分布式事务的atomic commit协议。

#### XA 事务 {#xa-transactions}

*X/Open XA*（*eXtended Architecture* 的缩写）是跨异构技术实现two-phase commit的标准[^73]。它于 1991 年推出并得到广泛实现：XA 受到许多传统关系数据库（包括 PostgreSQL、MySQL、Db2、SQL Server 和 Oracle）和消息代理（包括 ActiveMQ、HornetQ、MSMQ 和 IBM MQ）的支持。

XA 不是网络协议——它只是用于与事务coordinator接口的 C API。此 API 的绑定存在于其他语言中；例如，在 Java EE 应用程序的世界中，XA 事务使用 Java 事务 API（JTA）实现，而 JTA 又由许多使用 Java 数据库连接（JDBC）的数据库驱动程序和使用 Java 消息服务（JMS）API 的消息代理驱动程序支持。

XA 假设你的应用程序使用网络驱动程序或客户端库与participant数据库或消息服务进行通信。如果驱动程序支持 XA，这意味着它调用 XA API 来确定操作是否应该是分布式事务的一部分——如果是，它将必要的信息发送到数据库服务器。驱动程序还公开回调，coordinator可以通过回调要求participant准备、提交或中止。

事务coordinator实现 XA API。该标准没有指定应该如何实现它，但在实践中，coordinator通常只是加载到发出事务的应用程序的同一进程中的库（而不是单独的服务）。它跟踪事务中的participant，在要求他们准备后收集participant的响应（通过驱动程序的回调），并使用本地磁盘上的日志来跟踪每个事务的提交/中止决定。

如果应用程序进程崩溃，或者运行应用程序的机器死机，coordinator也随之消失。任何准备但未提交事务的participant都陷入in-doubt。由于coordinator的日志在应用程序服务器的本地磁盘上，该服务器必须重新启动，coordinator库必须读取日志以恢复每个事务的提交/中止结果。然后，coordinator才能使用数据库驱动程序的 XA 回调来要求participant提交或中止（视情况而定）。数据库服务器无法直接联系coordinator，因为所有通信都必须通过其客户端库。

#### in-doubt时持有锁 {#holding-locks-while-in-doubt}

为什么我们如此关心 transaction 陷入 in-doubt？系统的其余部分不能继续工作，忽略最终会被清理的 in-doubt transaction 吗？

问题在于 *locking*。如["read committed"](#sec_transactions_read_committed)中所讨论的，database transaction 通常对它们修改的任何 row 进行 row-level exclusive lock，以防止 dirty write。此外，如果你想要 serializable isolation，使用 two-phase locking 的数据库还必须对 transaction *读取*的任何 row 进行 shared lock。

数据库在 transaction commit 或 abort 之前不能释放这些 lock（如[图 8-13](#fig_transactions_two_phase_commit) 中的阴影区域所示）。因此，使用 two-phase commit 时，transaction 必须在 in-doubt 期间保持 lock。如果 coordinator 崩溃并需要 20 分钟才能重新启动，这些 lock 将保持 20 分钟。如果 coordinator 的 log 由于某种原因完全丢失，这些 lock 将永远保持，或者至少直到管理员手动解决情况。

当这些 lock 被持有时，没有其他 transaction 可以修改这些 row。根据 isolation level，其他 transaction 甚至可能被阻止读取这些 row。因此，其他 transaction 不能简单地继续自己的业务：如果它们想访问相同的数据，就会被 block。这可能导致你的应用程序的大部分变得 unavailable，直到 in-doubt transaction 得到解决。

#### 从coordinator故障中恢复 {#recovering-from-coordinator-failure}

理论上，如果 coordinator 崩溃并重新启动，它应该从 log 中干净地恢复其状态并解决任何 in-doubt transaction。但是，在实践中，*orphaned* in-doubt transaction 确实会发生[^83] [^84]：也就是说，coordinator 由于某种原因（例如，由于 software bug 导致 transaction log 丢失或损坏）无法决定结果的 transaction。这些 transaction 无法自动解决，因此它们永远留在数据库中，持有 lock 并 block 其他 transaction。

即使重新启动 database server 也无法解决此问题，因为 2PC 的正确实现必须即使在 restart 时也保留 in-doubt transaction 的 lock（否则它将冒着违反 atomicity guarantee 的风险）。这是一个棘手的情况。

唯一的出路是管理员手动决定是 commit 还是 rollback transaction。管理员必须检查每个 in-doubt transaction 的 participant，确定是否有任何 participant 已经 commit 或 abort，然后将相同的结果应用于其他 participant。解决问题可能需要大量手动工作，并且很可能需要在严重 production outage 期间、在高压力和时间压力下完成（否则，为什么 coordinator 会处于如此糟糕的状态？）。

许多 XA 实现都有一个名为 *heuristic decision* 的紧急出口：允许 participant 在没有 coordinator 明确决定的情况下单方面决定 abort 或 commit in-doubt transaction[^73]。明确地说，这里的 *heuristic* 是*可能破坏 atomicity* 的委婉说法，因为 heuristic decision 违反了 two-phase commit 中的 promise system。因此，heuristic decision 仅用于摆脱灾难性情况，而不用于常规使用。

#### XA 事务的问题 {#problems-with-xa-transactions}

单节点 coordinator 是整个系统的 single point of failure，使其成为 application server 的一部分也有问题，因为 coordinator 在其本地磁盘上的 log 成为 durable system state 的关键部分，与数据库本身一样重要。

原则上，XA transaction 的 coordinator 可以是 high-availability 且 replicated 的，就像我们对任何其他重要数据库的期望一样。不幸的是，这仍然不能解决 XA 的一个根本问题，即它没有为 transaction 的 coordinator 和 participant 提供直接相互通信的方式。它们只能通过调用 transaction 的 application code 以及调用 participant 的 database driver 进行通信。

即使coordinator被复制，应用程序代码也将是单点故障。解决这个问题需要完全重新设计应用程序代码的运行方式，使其复制或可重启，这可能看起来类似于持久执行（参见["持久执行和工作流"](/ch5#sec_encoding_dataflow_workflows)）。但是，实践中似乎没有任何工具实际采用这种方法。

另一个问题是，由于 XA 需要与各种数据系统兼容，它必然是 lowest common denominator。例如，它无法检测跨不同系统的 deadlock（因为这需要系统交换有关每个 transaction 正在等待哪些 lock 的标准化协议），并且它不适用于 SSI（参见["Serializable Snapshot Isolation（SSI）"](#sec_transactions_ssi)），因为这需要跨不同系统识别 conflict 的协议。

这些问题在某种程度上是跨 heterogeneous technology 执行 transaction 所固有的。但是，保持几个 heterogeneous data system 彼此 consistent 仍然是一个真实而重要的问题，因此我们需要为其找到不同的解决方案。这可以做到，我们将在下一节和["派生数据与分布式事务"](/ch13#sec_future_derived_vs_transactions)中看到。

### 数据库内部的分布式事务 {#sec_transactions_internal}

如前所述，跨多个异构存储技术的分布式事务与系统内部的分布式事务之间存在很大差异——即，参与节点都是运行相同软件的同一数据库的分片。此类内部分布式事务是"NewSQL"数据库的定义特征，例如 CockroachDB[^5]、TiDB[^6]、Spanner[^7]、FoundationDB[^8] 和 YugabyteDB。某些消息代理（如 Kafka）也支持内部分布式事务[^85]。

这些系统中的许多使用 two-phase commit 来确保写入多个 shard 的 transaction 具备 atomicity，但它们不会遇到与 XA transaction 相同的问题。原因是，由于它们的 distributed transaction 不需要与任何其他 technology interface，它们避免了 lowest common denominator trap：这些系统的设计者可以自由使用更可靠、更快的更好 protocol。

XA 的最大问题可以通过以下方式解决：

* replicated coordinator，如果 primary coordinator 崩溃，自动 fail over 到另一个 coordinator node；
* 允许 coordinator 和 data shard 直接通信，而不通过 application code；
* replicate participating shard，以减少由于 shard 中的 fault 而必须 abort transaction 的风险；以及
* 将 atomic commit protocol 与支持 cross-shard deadlock detection 和 consistent read 的 distributed concurrency control protocol 耦合。

consensus algorithm 通常用于 replicate coordinator 和 database shard。我们将在[第 10 章](/ch10#ch_consistency)中看到如何使用 consensus algorithm 实现 distributed transaction 的 atomic commit。这些算法通过自动从一个 node fail over 到另一个 node 来 tolerate fault，无需任何人工干预，同时继续 guarantee strong consistency property。

为 distributed transaction 提供的 isolation level 取决于系统，但跨 shard 的 snapshot isolation 和 serializable snapshot isolation 都是可能的。有关其工作原理的详细信息，请参见本章末尾引用的论文。

#### 再谈 Exactly-Once 消息处理 {#exactly-once-message-processing-revisited}

我们在["exactly-once 消息处理"](#sec_transactions_exactly_once)中看到，distributed transaction 的一个重要 use case 是确保某些 operation exactly once 地生效，即使在 processing 过程中发生 crash 并且需要 retry。如果你可以跨 message broker 和数据库 atomically commit transaction，则当且仅当成功处理 message 并且从 processing 产生的 database write 被 commit 时，你可以向 broker 确认 message。

但是，你实际上不需要这样的 distributed transaction 来实现 exactly-once semantics。另一种方法如下，它只需要数据库中的 transaction：

1. 假设每条消息都有唯一的 ID，并且在数据库中有一个已处理消息 ID 的表。当你开始从代理处理消息时，你在数据库上开始一个新事务，并检查消息 ID。如果数据库中已经存在相同的消息 ID，你知道它已经被处理，因此你可以向代理确认消息并丢弃它。
2. 如果消息 ID 尚未在数据库中，你将其添加到表中。然后你处理消息，这可能会导致在同一事务中对数据库进行额外的写入。完成处理消息后，你提交数据库上的事务。
3. 一旦数据库事务成功提交，你就可以向代理确认消息。
4. 一旦消息成功确认给代理，你知道它不会再次尝试处理相同的消息，因此你可以从数据库中删除消息 ID（在单独的事务中）。

如果消息处理器在提交数据库事务之前崩溃，事务将被中止，消息代理将重试处理。如果它在提交后但在向代理确认消息之前崩溃，它也将重试处理，但重试将在数据库中看到消息 ID 并丢弃它。如果它在确认消息后但在从数据库中删除消息 ID 之前崩溃，你将有一个旧的消息 ID 留下，除了占用一点存储空间外不会造成任何伤害。如果在数据库事务中止之前发生重试（如果消息处理器和数据库之间的通信中断，这可能会发生），消息 ID 表上的唯一性约束应该防止两个并发事务插入相同的消息 ID。

因此，实现 exactly-once processing 只需要数据库中的 transaction：跨数据库和 message broker 的 atomicity 对于此 use case 不是必需的。在数据库中记录 message ID 使 message processing 具备 *idempotence*，因此可以安全地 retry message processing 而不会重复其 side effect。stream processing framework（如 Kafka Streams）中使用类似方法来实现 exactly-once semantics，我们将在["容错"](/ch12#sec_stream_fault_tolerance)中看到。

但是，数据库内的 internal distributed transaction 对此类 pattern 的 scalability 仍然有用：例如，它们允许 message ID 存储在一个 shard 上，而 message processing 更新的 primary data 存储在其他 shard 上，并确保跨这些 shard 的 transaction commit 具有 atomicity。



## 总结 {#summary}

事务是一个抽象层，允许应用程序假装某些并发问题和某些类型的硬件和软件故障不存在。大量错误被简化为简单的*事务中止*，应用程序只需要重试。

在本章中，我们看到了许多事务有助于防止的问题示例。并非所有应用程序都容易受到所有这些问题的影响：具有非常简单的访问模式的应用程序（例如，仅读取和写入单个记录）可能可以在没有事务的情况下管理。但是，对于更复杂的访问模式，事务可以大大减少你需要考虑的潜在错误情况的数量。

没有 transaction，各种 error scenario（进程崩溃、网络中断、停电、磁盘已满、意外 concurrency 等）意味着数据可能以各种方式变得 inconsistent。例如，denormalized data 很容易与 source data 失去同步。没有 transaction，很难推理复杂的 interleaved access 对数据库可能产生的影响。

在本章中，我们特别深入地探讨了 concurrency control。我们讨论了几种广泛使用的 isolation levels，特别是 *read committed*、*snapshot isolation*（有时称为 *repeatable read*）和 *serializable*。我们通过讨论各种 race condition 的示例来描述这些 isolation levels，总结在 [表 8-1](#tab_transactions_isolation_levels) 中：

{{< figure id="tab_transactions_isolation_levels" title="表 8-1. 各种 isolation level 可能发生的 anomaly 总结" class="w-full my-4" >}}

| isolation level | dirty read | read skew | phantom read | lost update | write skew |
|------|------|------|------|-------|------|
| read uncommitted | ✗ 可能 | ✗ 可能 | ✗ 可能 | ✗ 可能  | ✗ 可能 |
| read committed | ✓ 防止 | ✗ 可能 | ✗ 可能 | ✗ 可能  | ✗ 可能 |
| snapshot isolation | ✓ 防止 | ✓ 防止 | ✓ 防止 | ? 视情况 | ✗ 可能 |
| serializable | ✓ 防止 | ✓ 防止 | ✓ 防止 | ✓ 防止  | ✓ 防止 |

dirty read
: 一个 client 在另一个 client 的 write commit 之前读取它们。read committed isolation level 和更强的级别防止 dirty read。

dirty write
: 一个 client 覆盖另一个 client 已写入但尚未 commit 的数据。几乎所有 transaction implementation 都防止 dirty write。

read skew
: client 在不同时间点看到数据库的不同部分。某些 read skew 的情况也称为 *nonrepeatable read*。这个问题最常通过 snapshot isolation 防止，它允许 transaction 从对应于特定时间点的 consistent snapshot 读取。它通常使用 *MVCC* 实现。

lost update
: 两个 client concurrently 执行 read-modify-write cycle。一个覆盖另一个的 write 而不 merge 其 change，因此数据丢失。某些 snapshot isolation 实现会自动防止此 anomaly，而其他实现需要 manual lock（`SELECT FOR UPDATE`）。

write skew
: transaction 读取某些内容，根据它看到的 value 做出 decision，并将 decision 写入数据库。但是，在进行 write 时，decision 的 premise 不再为真。只有 serializable isolation 才能防止此 anomaly。

phantom read
: transaction 读取匹配某些 search condition 的 object。另一个 client 进行影响该 search result 的 write。snapshot isolation 防止直接的 phantom read，但 write skew 上下文中的 phantom read 需要特殊处理，例如 index-range lock。

weak isolation levels 可以防止某些 anomaly，但让你（应用程序开发人员）手动处理其他 anomaly，例如使用 explicit locking。只有 serializable isolation 可以防止所有这些问题。我们讨论了实现 serializable transaction 的三种不同方法：

serial execution of transactions
: 如果你可以使每个 transaction 执行得非常快（通常通过使用 stored procedure），并且 transaction throughput 足够低，可以在单个 CPU 核心上处理，或者可以按 shard 分开处理，这是一个简单有效的选择。

two-phase locking
: 几十年来，这一直是实现 serializable 的标准方法，但许多应用程序由于其 performance 不佳而避免使用它。

serializable snapshot isolation（SSI）
: 一种相对较新的算法，避免了前面方法的大部分缺点。它使用 optimistic approach，允许 transaction 在不 blocking 的情况下进行。当 transaction 想要 commit 时，它会被检查；如果 execution 不 serializable，它将被 abort。

最后，我们研究了当 transaction 分布在多个节点上时如何实现 atomicity，使用的是 two-phase commit。如果这些节点都运行相同的数据库软件，distributed transaction 可以很好地工作；但跨不同 storage technology（使用 XA transaction）时，2PC 是有问题的：它对 coordinator 和驱动 transaction 的应用程序代码中的故障非常敏感，并且与 concurrency control 机制的交互很差。幸运的是，idempotence 可以确保 exactly-once semantics，而无需跨不同 storage technology 的 atomic commit，我们将在后面的章节中看到更多相关内容。

本章中的示例使用了 relational data model。但是，如["为什么需要 Multi-Object Transaction"](#sec_transactions_need)中所讨论的，无论使用哪种 data model，transaction 都是有价值的数据库功能。



### 参考


[^1]: Steven J. Murdoch. [What went wrong with Horizon: learning from the Post Office Trial](https://www.benthamsgaze.org/2021/07/15/what-went-wrong-with-horizon-learning-from-the-post-office-trial/). *benthamsgaze.org*, July 2021. Archived at [perma.cc/CNM4-553F](https://perma.cc/CNM4-553F)
[^2]: Donald D. Chamberlin, Morton M. Astrahan, Michael W. Blasgen, James N. Gray, W. Frank King, Bruce G. Lindsay, Raymond Lorie, James W. Mehl, Thomas G. Price, Franco Putzolu, Patricia Griffiths Selinger, Mario Schkolnick, Donald R. Slutz, Irving L. Traiger, Bradford W. Wade, and Robert A. Yost. [A History and Evaluation of System R](https://dsf.berkeley.edu/cs262/2005/SystemR.pdf). *Communications of the ACM*, volume 24, issue 10, pages 632–646, October 1981. [doi:10.1145/358769.358784](https://doi.org/10.1145/358769.358784)
[^3]: Jim N. Gray, Raymond A. Lorie, Gianfranco R. Putzolu, and Irving L. Traiger. [Granularity of Locks and Degrees of Consistency in a Shared Data Base](https://citeseerx.ist.psu.edu/pdf/e127f0a6a912bb9150ecfe03c0ebf7fbc289a023). in *Modelling in Data Base Management Systems: Proceedings of the IFIP Working Conference on Modelling in Data Base Management Systems*, edited by G. M. Nijssen, pages 364–394, Elsevier/North Holland Publishing, 1976. Also in *Readings in Database Systems*, 4th edition, edited by Joseph M. Hellerstein and Michael Stonebraker, MIT Press, 2005. ISBN: 978-0-262-69314-1
[^4]: Kapali P. Eswaran, Jim N. Gray, Raymond A. Lorie, and Irving L. Traiger. [The Notions of Consistency and Predicate Locks in a Database System](https://jimgray.azurewebsites.net/papers/On%20the%20Notions%20of%20Consistency%20and%20Predicate%20Locks%20in%20a%20Database%20System%20CACM.pdf?from=https://research.microsoft.com/en-us/um/people/gray/papers/On%20the%20Notions%20of%20Consistency%20and%20Predicate%20Locks%20in%20a%20Database%20System%20CACM.pdf). *Communications of the ACM*, volume 19, issue 11, pages 624–633, November 1976. [doi:10.1145/360363.360369](https://doi.org/10.1145/360363.360369)
[^5]: Rebecca Taft, Irfan Sharif, Andrei Matei, Nathan VanBenschoten, Jordan Lewis, Tobias Grieger, Kai Niemi, Andy Woods, Anne Birzin, Raphael Poss, Paul Bardea, Amruta Ranade, Ben Darnell, Bram Gruneir, Justin Jaffray, Lucy Zhang, and Peter Mattis. [CockroachDB: The Resilient Geo-Distributed SQL Database](https://dl.acm.org/doi/pdf/10.1145/3318464.3386134). At *ACM SIGMOD International Conference on Management of Data* (SIGMOD), pages 1493–1509, June 2020. [doi:10.1145/3318464.3386134](https://doi.org/10.1145/3318464.3386134)
[^6]: Dongxu Huang, Qi Liu, Qiu Cui, Zhuhe Fang, Xiaoyu Ma, Fei Xu, Li Shen, Liu Tang, Yuxing Zhou, Menglong Huang, Wan Wei, Cong Liu, Jian Zhang, Jianjun Li, Xuelian Wu, Lingyu Song, Ruoxi Sun, Shuaipeng Yu, Lei Zhao, Nicholas Cameron, Liquan Pei, and Xin Tang. [TiDB: a Raft-based HTAP database](https://www.vldb.org/pvldb/vol13/p3072-huang.pdf). *Proceedings of the VLDB Endowment*, volume 13, issue 12, pages 3072–3084. [doi:10.14778/3415478.3415535](https://doi.org/10.14778/3415478.3415535)
[^7]: James C. Corbett, Jeffrey Dean, Michael Epstein, Andrew Fikes, Christopher Frost, JJ Furman, Sanjay Ghemawat, Andrey Gubarev, Christopher Heiser, Peter Hochschild, Wilson Hsieh, Sebastian Kanthak, Eugene Kogan, Hongyi Li, Alexander Lloyd, Sergey Melnik, David Mwaura, David Nagle, Sean Quinlan, Rajesh Rao, Lindsay Rolig, Dale Woodford, Yasushi Saito, Christopher Taylor, Michal Szymaniak, and Ruth Wang. [Spanner: Google’s Globally-Distributed Database](https://research.google/pubs/pub39966/). At *10th USENIX Symposium on Operating System Design and Implementation* (OSDI), October 2012.
[^8]: Jingyu Zhou, Meng Xu, Alexander Shraer, Bala Namasivayam, Alex Miller, Evan Tschannen, Steve Atherton, Andrew J. Beamon, Rusty Sears, John Leach, Dave Rosenthal, Xin Dong, Will Wilson, Ben Collins, David Scherer, Alec Grieser, Young Liu, Alvin Moore, Bhaskar Muppana, Xiaoge Su, and Vishesh Yadav. [FoundationDB: A Distributed Unbundled Transactional Key Value Store](https://www.foundationdb.org/files/fdb-paper.pdf). At *ACM International Conference on Management of Data* (SIGMOD), June 2021. [doi:10.1145/3448016.3457559](https://doi.org/10.1145/3448016.3457559)
[^9]: Theo Härder and Andreas Reuter. [Principles of Transaction-Oriented Database Recovery](https://citeseerx.ist.psu.edu/pdf/11ef7c142295aeb1a28a0e714c91fc8d610c3047). *ACM Computing Surveys*, volume 15, issue 4, pages 287–317, December 1983. [doi:10.1145/289.291](https://doi.org/10.1145/289.291)
[^10]: Peter Bailis, Alan Fekete, Ali Ghodsi, Joseph M. Hellerstein, and Ion Stoica. [HAT, not CAP: Towards Highly Available Transactions](https://www.usenix.org/system/files/conference/hotos13/hotos13-final80.pdf). At *14th USENIX Workshop on Hot Topics in Operating Systems* (HotOS), May 2013.
[^11]: Armando Fox, Steven D. Gribble, Yatin Chawathe, Eric A. Brewer, and Paul Gauthier. [Cluster-Based Scalable Network Services](https://people.eecs.berkeley.edu/~brewer/cs262b/TACC.pdf). At *16th ACM Symposium on Operating Systems Principles* (SOSP), October 1997. [doi:10.1145/268998.266662](https://doi.org/10.1145/268998.266662)
[^12]: Tony Andrews. [Enforcing Complex Constraints in Oracle](https://tonyandrews.blogspot.com/2004/10/enforcing-complex-constraints-in.html). *tonyandrews.blogspot.co.uk*, October 2004. Archived at [archive.org](https://web.archive.org/web/20220201190625/https%3A//tonyandrews.blogspot.com/2004/10/enforcing-complex-constraints-in.html)
[^13]: Philip A. Bernstein, Vassos Hadzilacos, and Nathan Goodman. [*Concurrency Control and Recovery in Database Systems*](https://www.microsoft.com/en-us/research/people/philbe/book/). Addison-Wesley, 1987. ISBN: 978-0-201-10715-9, available online at [*microsoft.com*](https://www.microsoft.com/en-us/research/people/philbe/book/).
[^14]: Alan Fekete, Dimitrios Liarokapis, Elizabeth O’Neil, Patrick O’Neil, and Dennis Shasha. [Making Snapshot Isolation Serializable](https://www.cse.iitb.ac.in/infolab/Data/Courses/CS632/2009/Papers/p492-fekete.pdf). *ACM Transactions on Database Systems*, volume 30, issue 2, pages 492–528, June 2005. [doi:10.1145/1071610.1071615](https://doi.org/10.1145/1071610.1071615)
[^15]: Mai Zheng, Joseph Tucek, Feng Qin, and Mark Lillibridge. [Understanding the Robustness of SSDs Under Power Fault](https://www.usenix.org/system/files/conference/fast13/fast13-final80.pdf). At *11th USENIX Conference on File and Storage Technologies* (FAST), February 2013.
[^16]: Laurie Denness. [SSDs: A Gift and a Curse](https://laur.ie/blog/2015/06/ssds-a-gift-and-a-curse/). *laur.ie*, June 2015. Archived at [perma.cc/6GLP-BX3T](https://perma.cc/6GLP-BX3T)
[^17]: Adam Surak. [When Solid State Drives Are Not That Solid](https://www.algolia.com/blog/engineering/when-solid-state-drives-are-not-that-solid). *blog.algolia.com*, June 2015. Archived at [perma.cc/CBR9-QZEE](https://perma.cc/CBR9-QZEE)
[^18]: Hewlett Packard Enterprise. [Bulletin: (Revision) HPE SAS Solid State Drives - Critical Firmware Upgrade Required for Certain HPE SAS Solid State Drive Models to Prevent Drive Failure at 32,768 Hours of Operation](https://support.hpe.com/hpesc/public/docDisplay?docId=emr_na-a00092491en_us). *support.hpe.com*, November 2019. Archived at [perma.cc/CZR4-AQBS](https://perma.cc/CZR4-AQBS)
[^19]: Craig Ringer et al. [PostgreSQL’s handling of fsync() errors is unsafe and risks data loss at least on XFS](https://www.postgresql.org/message-id/flat/CAMsr%2BYHh%2B5Oq4xziwwoEfhoTZgr07vdGG%2Bhu%3D1adXx59aTeaoQ%40mail.gmail.com). Email thread on pgsql-hackers mailing list, *postgresql.org*, March 2018. Archived at [perma.cc/5RKU-57FL](https://perma.cc/5RKU-57FL)
[^20]: Anthony Rebello, Yuvraj Patel, Ramnatthan Alagappan, Andrea C. Arpaci-Dusseau, and Remzi H. Arpaci-Dusseau. [Can Applications Recover from fsync Failures?](https://www.usenix.org/conference/atc20/presentation/rebello) At *USENIX Annual Technical Conference* (ATC), July 2020.
[^21]: Thanumalayan Sankaranarayana Pillai, Vijay Chidambaram, Ramnatthan Alagappan, Samer Al-Kiswany, Andrea C. Arpaci-Dusseau, and Remzi H. Arpaci-Dusseau. [Crash Consistency: Rethinking the Fundamental Abstractions of the File System](https://dl.acm.org/doi/pdf/10.1145/2800695.2801719). *ACM Queue*, volume 13, issue 7, pages 20–28, July 2015. [doi:10.1145/2800695.2801719](https://doi.org/10.1145/2800695.2801719)
[^22]: Thanumalayan Sankaranarayana Pillai, Vijay Chidambaram, Ramnatthan Alagappan, Samer Al-Kiswany, Andrea C. Arpaci-Dusseau, and Remzi H. Arpaci-Dusseau. [All File Systems Are Not Created Equal: On the Complexity of Crafting Crash-Consistent Applications](https://www.usenix.org/system/files/conference/osdi14/osdi14-paper-pillai.pdf). At *11th USENIX Symposium on Operating Systems Design and Implementation* (OSDI), October 2014.
[^23]: Chris Siebenmann. [Unix’s File Durability Problem](https://utcc.utoronto.ca/~cks/space/blog/unix/FileSyncProblem). *utcc.utoronto.ca*, April 2016. Archived at [perma.cc/VSS8-5MC4](https://perma.cc/VSS8-5MC4)
[^24]: Aishwarya Ganesan, Ramnatthan Alagappan, Andrea C. Arpaci-Dusseau, and Remzi H. Arpaci-Dusseau. [Redundancy Does Not Imply Fault Tolerance: Analysis of Distributed Storage Reactions to Single Errors and Corruptions](https://www.usenix.org/conference/fast17/technical-sessions/presentation/ganesan). At *15th USENIX Conference on File and Storage Technologies* (FAST), February 2017.
[^25]: Lakshmi N. Bairavasundaram, Garth R. Goodson, Bianca Schroeder, Andrea C. Arpaci-Dusseau, and Remzi H. Arpaci-Dusseau. [An Analysis of Data Corruption in the Storage Stack](https://www.usenix.org/legacy/event/fast08/tech/full_papers/bairavasundaram/bairavasundaram.pdf). At *6th USENIX Conference on File and Storage Technologies* (FAST), February 2008.
[^26]: Bianca Schroeder, Raghav Lagisetty, and Arif Merchant. [Flash Reliability in Production: The Expected and the Unexpected](https://www.usenix.org/conference/fast16/technical-sessions/presentation/schroeder). At *14th USENIX Conference on File and Storage Technologies* (FAST), February 2016.
[^27]: Don Allison. [SSD Storage – Ignorance of Technology Is No Excuse](https://blog.korelogic.com/blog/2015/03/24). *blog.korelogic.com*, March 2015. Archived at [perma.cc/9QN4-9SNJ](https://perma.cc/9QN4-9SNJ)
[^28]: Gordon Mah Ung. [Debunked: Your SSD won’t lose data if left unplugged after all](https://www.pcworld.com/article/427602/debunked-your-ssd-wont-lose-data-if-left-unplugged-after-all.html). *pcworld.com*, May 2015. Archived at [perma.cc/S46H-JUDU](https://perma.cc/S46H-JUDU)
[^29]: Martin Kleppmann. [Hermitage: Testing the ‘I’ in ACID](https://martin.kleppmann.com/2014/11/25/hermitage-testing-the-i-in-acid.html). *martin.kleppmann.com*, November 2014. Archived at [perma.cc/KP2Y-AQGK](https://perma.cc/KP2Y-AQGK)
[^30]: Todd Warszawski and Peter Bailis. [ACIDRain: Concurrency-Related Attacks on Database-Backed Web Applications](http://www.bailis.org/papers/acidrain-sigmod2017.pdf). At *ACM International Conference on Management of Data* (SIGMOD), May 2017. [doi:10.1145/3035918.3064037](https://doi.org/10.1145/3035918.3064037)
[^31]: Tristan D’Agosta. [BTC Stolen from Poloniex](https://bitcointalk.org/index.php?topic=499580). *bitcointalk.org*, March 2014. Archived at [perma.cc/YHA6-4C5D](https://perma.cc/YHA6-4C5D)
[^32]: bitcointhief2. [How I Stole Roughly 100 BTC from an Exchange and How I Could Have Stolen More!](https://www.reddit.com/r/Bitcoin/comments/1wtbiu/how_i_stole_roughly_100_btc_from_an_exchange_and/) *reddit.com*, February 2014. Archived at [archive.org](https://web.archive.org/web/20250118042610/https%3A//www.reddit.com/r/Bitcoin/comments/1wtbiu/how_i_stole_roughly_100_btc_from_an_exchange_and/)
[^33]: Sudhir Jorwekar, Alan Fekete, Krithi Ramamritham, and S. Sudarshan. [Automating the Detection of Snapshot Isolation Anomalies](https://www.vldb.org/conf/2007/papers/industrial/p1263-jorwekar.pdf). At *33rd International Conference on Very Large Data Bases* (VLDB), September 2007.
[^34]: Michael Melanson. [Transactions: The Limits of Isolation](https://www.michaelmelanson.net/posts/transactions-the-limits-of-isolation/). *michaelmelanson.net*, November 2014. Archived at [perma.cc/RG5R-KMYZ](https://perma.cc/RG5R-KMYZ)
[^35]: Edward Kim. [How ACH works: A developer perspective — Part 1](https://engineering.gusto.com/how-ach-works-a-developer-perspective-part-1-339d3e7bea1). *engineering.gusto.com*, April 2014. Archived at [perma.cc/7B2H-PU94](https://perma.cc/7B2H-PU94)
[^36]: Hal Berenson, Philip A. Bernstein, Jim N. Gray, Jim Melton, Elizabeth O’Neil, and Patrick O’Neil. [A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf). At *ACM International Conference on Management of Data* (SIGMOD), May 1995. [doi:10.1145/568271.223785](https://doi.org/10.1145/568271.223785)
[^37]: Atul Adya. [Weak Consistency: A Generalized Theory and Optimistic Implementations for Distributed Transactions](https://pmg.csail.mit.edu/papers/adya-phd.pdf). PhD Thesis, Massachusetts Institute of Technology, March 1999. Archived at [perma.cc/E97M-HW5Q](https://perma.cc/E97M-HW5Q)
[^38]: Peter Bailis, Aaron Davidson, Alan Fekete, Ali Ghodsi, Joseph M. Hellerstein, and Ion Stoica. [Highly Available Transactions: Virtues and Limitations](https://www.vldb.org/pvldb/vol7/p181-bailis.pdf). At *40th International Conference on Very Large Data Bases* (VLDB), September 2014.
[^39]: Natacha Crooks, Youer Pu, Lorenzo Alvisi, and Allen Clement. [Seeing is Believing: A Client-Centric Specification of Database Isolation](https://www.cs.cornell.edu/lorenzo/papers/Crooks17Seeing.pdf). At *ACM Symposium on Principles of Distributed Computing* (PODC), pages 73–82, July 2017. [doi:10.1145/3087801.3087802](https://doi.org/10.1145/3087801.3087802)
[^40]: Bruce Momjian. [MVCC Unmasked](https://momjian.us/main/writings/pgsql/mvcc.pdf). *momjian.us*, July 2014. Archived at [perma.cc/KQ47-9GYB](https://perma.cc/KQ47-9GYB)
[^41]: Peter Alvaro and Kyle Kingsbury. [MySQL 8.0.34](https://jepsen.io/analyses/mysql-8.0.34). *jepsen.io*, December 2023. Archived at [perma.cc/HGE2-Z878](https://perma.cc/HGE2-Z878)
[^42]: Egor Rogov. [PostgreSQL 14 Internals](https://postgrespro.com/community/books/internals). *postgrespro.com*, April 2023. Archived at [perma.cc/FRK2-D7WB](https://perma.cc/FRK2-D7WB)
[^43]: Hironobu Suzuki. [The Internals of PostgreSQL](https://www.interdb.jp/pg/). *interdb.jp*, 2017.
[^44]: Rohan Reddy Alleti. [Internals of MVCC in Postgres: Hidden costs of Updates vs Inserts](https://medium.com/%40rohanjnr44/internals-of-mvcc-in-postgres-hidden-costs-of-updates-vs-inserts-381eadd35844). *medium.com*, March 2025. Archived at [perma.cc/3ACX-DFXT](https://perma.cc/3ACX-DFXT)
[^45]: Andy Pavlo and Bohan Zhang. [The Part of PostgreSQL We Hate the Most](https://www.cs.cmu.edu/~pavlo/blog/2023/04/the-part-of-postgresql-we-hate-the-most.html). *cs.cmu.edu*, April 2023. Archived at [perma.cc/XSP6-3JBN](https://perma.cc/XSP6-3JBN)
[^46]: Yingjun Wu, Joy Arulraj, Jiexi Lin, Ran Xian, and Andrew Pavlo. [An empirical evaluation of in-memory multi-version concurrency control](https://vldb.org/pvldb/vol10/p781-Wu.pdf). *Proceedings of the VLDB Endowment*, volume 10, issue 7, pages 781–792, March 2017. [doi:10.14778/3067421.3067427](https://doi.org/10.14778/3067421.3067427)
[^47]: Nikita Prokopov. [Unofficial Guide to Datomic Internals](https://tonsky.me/blog/unofficial-guide-to-datomic-internals/). *tonsky.me*, May 2014.
[^48]: Daniil Svetlov. [A Practical Guide to Taming Postgres Isolation Anomalies](https://dansvetlov.me/postgres-anomalies/). *dansvetlov.me*, March 2025. Archived at [perma.cc/L7LE-TDLS](https://perma.cc/L7LE-TDLS)
[^49]: Nate Wiger. [An Atomic Rant](https://nateware.com/2010/02/18/an-atomic-rant/). *nateware.com*, February 2010. Archived at [perma.cc/5ZYB-PE44](https://perma.cc/5ZYB-PE44)
[^50]: James Coglan. [Reading and writing, part 3: web applications](https://blog.jcoglan.com/2020/10/12/reading-and-writing-part-3/). *blog.jcoglan.com*, October 2020. Archived at [perma.cc/A7EK-PJVS](https://perma.cc/A7EK-PJVS)
[^51]: Peter Bailis, Alan Fekete, Michael J. Franklin, Ali Ghodsi, Joseph M. Hellerstein, and Ion Stoica. [Feral Concurrency Control: An Empirical Investigation of Modern Application Integrity](http://www.bailis.org/papers/feral-sigmod2015.pdf). At *ACM International Conference on Management of Data* (SIGMOD), June 2015. [doi:10.1145/2723372.2737784](https://doi.org/10.1145/2723372.2737784)
[^52]: Jaana Dogan. [Things I Wished More Developers Knew About Databases](https://rakyll.medium.com/things-i-wished-more-developers-knew-about-databases-2d0178464f78). *rakyll.medium.com*, April 2020. Archived at [perma.cc/6EFK-P2TD](https://perma.cc/6EFK-P2TD)
[^53]: Michael J. Cahill, Uwe Röhm, and Alan Fekete. [Serializable Isolation for Snapshot Databases](https://www.cs.cornell.edu/~sowell/dbpapers/serializable_isolation.pdf). At *ACM International Conference on Management of Data* (SIGMOD), June 2008. [doi:10.1145/1376616.1376690](https://doi.org/10.1145/1376616.1376690)
[^54]: Dan R. K. Ports and Kevin Grittner. [Serializable Snapshot Isolation in PostgreSQL](https://drkp.net/papers/ssi-vldb12.pdf). At *38th International Conference on Very Large Databases* (VLDB), August 2012.
[^55]: Douglas B. Terry, Marvin M. Theimer, Karin Petersen, Alan J. Demers, Mike J. Spreitzer and Carl H. Hauser. [Managing Update Conflicts in Bayou, a Weakly Connected Replicated Storage System](https://pdos.csail.mit.edu/6.824/papers/bayou-conflicts.pdf). At *15th ACM Symposium on Operating Systems Principles* (SOSP), December 1995. [doi:10.1145/224056.224070](https://doi.org/10.1145/224056.224070)
[^56]: Hans-Jürgen Schönig. [Constraints over multiple rows in PostgreSQL](https://www.cybertec-postgresql.com/en/postgresql-constraints-over-multiple-rows/). *cybertec-postgresql.com*, June 2021. Archived at [perma.cc/2TGH-XUPZ](https://perma.cc/2TGH-XUPZ)
[^57]: Michael Stonebraker, Samuel Madden, Daniel J. Abadi, Stavros Harizopoulos, Nabil Hachem, and Pat Helland. [The End of an Architectural Era (It’s Time for a Complete Rewrite)](https://vldb.org/conf/2007/papers/industrial/p1150-stonebraker.pdf). At *33rd International Conference on Very Large Data Bases* (VLDB), September 2007.
[^58]: John Hugg. [H-Store/VoltDB Architecture vs. CEP Systems and Newer Streaming Architectures](https://www.youtube.com/watch?v=hD5M4a1UVz8). At *Data @Scale Boston*, November 2014.
[^59]: Robert Kallman, Hideaki Kimura, Jonathan Natkins, Andrew Pavlo, Alexander Rasin, Stanley Zdonik, Evan P. C. Jones, Samuel Madden, Michael Stonebraker, Yang Zhang, John Hugg, and Daniel J. Abadi. [H-Store: A High-Performance, Distributed Main Memory Transaction Processing System](https://www.vldb.org/pvldb/vol1/1454211.pdf). *Proceedings of the VLDB Endowment*, volume 1, issue 2, pages 1496–1499, August 2008.
[^60]: Rich Hickey. [The Architecture of Datomic](https://www.infoq.com/articles/Architecture-Datomic/). *infoq.com*, November 2012. Archived at [perma.cc/5YWU-8XJK](https://perma.cc/5YWU-8XJK)
[^61]: John Hugg. [Debunking Myths About the VoltDB In-Memory Database](https://dzone.com/articles/debunking-myths-about-voltdb). *dzone.com*, May 2014. Archived at [perma.cc/2Z9N-HPKF](https://perma.cc/2Z9N-HPKF)
[^62]: Xinjing Zhou, Viktor Leis, Xiangyao Yu, and Michael Stonebraker. [OLTP Through the Looking Glass 16 Years Later: Communication is the New Bottleneck](https://www.vldb.org/cidrdb/papers/2025/p17-zhou.pdf). At *15th Annual Conference on Innovative Data Systems Research* (CIDR), January 2025.
[^63]: Xinjing Zhou, Xiangyao Yu, Goetz Graefe, and Michael Stonebraker. [Lotus: scalable multi-partition transactions on single-threaded partitioned databases](https://www.vldb.org/pvldb/vol15/p2939-zhou.pdf). *Proceedings of the VLDB Endowment* (PVLDB), volume 15, issue 11, pages 2939–2952, July 2022. [doi:10.14778/3551793.3551843](https://doi.org/10.14778/3551793.3551843)
[^64]: Joseph M. Hellerstein, Michael Stonebraker, and James Hamilton. [Architecture of a Database System](https://dsf.berkeley.edu/papers/fntdb07-architecture.pdf). *Foundations and Trends in Databases*, volume 1, issue 2, pages 141–259, November 2007. [doi:10.1561/1900000002](https://doi.org/10.1561/1900000002)
[^65]: Michael J. Cahill. [Serializable Isolation for Snapshot Databases](https://ses.library.usyd.edu.au/bitstream/handle/2123/5353/michael-cahill-2009-thesis.pdf). PhD Thesis, University of Sydney, July 2009. Archived at [perma.cc/727J-NTMP](https://perma.cc/727J-NTMP)
[^66]: Cristian Diaconu, Craig Freedman, Erik Ismert, Per-Åke Larson, Pravin Mittal, Ryan Stonecipher, Nitin Verma, and Mike Zwilling. [Hekaton: SQL Server’s Memory-Optimized OLTP Engine](https://www.microsoft.com/en-us/research/wp-content/uploads/2013/06/Hekaton-Sigmod2013-final.pdf). At *ACM SIGMOD International Conference on Management of Data* (SIGMOD), pages 1243–1254, June 2013. [doi:10.1145/2463676.2463710](https://doi.org/10.1145/2463676.2463710)
[^67]: Thomas Neumann, Tobias Mühlbauer, and Alfons Kemper. [Fast Serializable Multi-Version Concurrency Control for Main-Memory Database Systems](https://db.in.tum.de/~muehlbau/papers/mvcc.pdf). At *ACM SIGMOD International Conference on Management of Data* (SIGMOD), pages 677–689, May 2015. [doi:10.1145/2723372.2749436](https://doi.org/10.1145/2723372.2749436)
[^68]: D. Z. Badal. [Correctness of Concurrency Control and Implications in Distributed Databases](https://ieeexplore.ieee.org/abstract/document/762563). At *3rd International IEEE Computer Software and Applications Conference* (COMPSAC), November 1979. [doi:10.1109/CMPSAC.1979.762563](https://doi.org/10.1109/CMPSAC.1979.762563)
[^69]: Rakesh Agrawal, Michael J. Carey, and Miron Livny. [Concurrency Control Performance Modeling: Alternatives and Implications](https://people.eecs.berkeley.edu/~brewer/cs262/ConcControl.pdf). *ACM Transactions on Database Systems* (TODS), volume 12, issue 4, pages 609–654, December 1987. [doi:10.1145/32204.32220](https://doi.org/10.1145/32204.32220)
[^70]: Marc Brooker. [Snapshot Isolation vs Serializability](https://brooker.co.za/blog/2024/12/17/occ-and-isolation.html). *brooker.co.za*, December 2024. Archived at [perma.cc/5TRC-CR5G](https://perma.cc/5TRC-CR5G)
[^71]: B. G. Lindsay, P. G. Selinger, C. Galtieri, J. N. Gray, R. A. Lorie, T. G. Price, F. Putzolu, I. L. Traiger, and B. W. Wade. [Notes on Distributed Databases](https://dominoweb.draco.res.ibm.com/reports/RJ2571.pdf). IBM Research, Research Report RJ2571(33471), July 1979. Archived at [perma.cc/EPZ3-MHDD](https://perma.cc/EPZ3-MHDD)
[^72]: C. Mohan, Bruce G. Lindsay, and Ron Obermarck. [Transaction Management in the R\* Distributed Database Management System](https://cs.brown.edu/courses/csci2270/archives/2012/papers/dtxn/p378-mohan.pdf). *ACM Transactions on Database Systems*, volume 11, issue 4, pages 378–396, December 1986. [doi:10.1145/7239.7266](https://doi.org/10.1145/7239.7266)
[^73]: X/Open Company Ltd. [Distributed Transaction Processing: The XA Specification](https://pubs.opengroup.org/onlinepubs/009680699/toc.pdf). Technical Standard XO/CAE/91/300, December 1991. ISBN: 978-1-872-63024-3, archived at [perma.cc/Z96H-29JB](https://perma.cc/Z96H-29JB)
[^74]: Ivan Silva Neto and Francisco Reverbel. [Lessons Learned from Implementing WS-Coordination and WS-AtomicTransaction](https://www.ime.usp.br/~reverbel/papers/icis2008.pdf). At *7th IEEE/ACIS International Conference on Computer and Information Science* (ICIS), May 2008. [doi:10.1109/ICIS.2008.75](https://doi.org/10.1109/ICIS.2008.75)
[^75]: James E. Johnson, David E. Langworthy, Leslie Lamport, and Friedrich H. Vogt. [Formal Specification of a Web Services Protocol](https://www.microsoft.com/en-us/research/publication/formal-specification-of-a-web-services-protocol/). At *1st International Workshop on Web Services and Formal Methods* (WS-FM), February 2004. [doi:10.1016/j.entcs.2004.02.022](https://doi.org/10.1016/j.entcs.2004.02.022)
[^76]: Jim Gray. [The Transaction Concept: Virtues and Limitations](https://jimgray.azurewebsites.net/papers/thetransactionconcept.pdf). At *7th International Conference on Very Large Data Bases* (VLDB), September 1981.
[^77]: Dale Skeen. [Nonblocking Commit Protocols](https://www.cs.utexas.edu/~lorenzo/corsi/cs380d/papers/Ske81.pdf). At *ACM International Conference on Management of Data* (SIGMOD), April 1981. [doi:10.1145/582318.582339](https://doi.org/10.1145/582318.582339)
[^78]: Gregor Hohpe. [Your Coffee Shop Doesn’t Use Two-Phase Commit](https://www.martinfowler.com/ieeeSoftware/coffeeShop.pdf). *IEEE Software*, volume 22, issue 2, pages 64–66, March 2005. [doi:10.1109/MS.2005.52](https://doi.org/10.1109/MS.2005.52)
[^79]: Pat Helland. [Life Beyond Distributed Transactions: An Apostate’s Opinion](https://www.cidrdb.org/cidr2007/papers/cidr07p15.pdf). At *3rd Biennial Conference on Innovative Data Systems Research* (CIDR), January 2007.
[^80]: Jonathan Oliver. [My Beef with MSDTC and Two-Phase Commits](https://blog.jonathanoliver.com/my-beef-with-msdtc-and-two-phase-commits/). *blog.jonathanoliver.com*, April 2011. Archived at [perma.cc/K8HF-Z4EN](https://perma.cc/K8HF-Z4EN)
[^81]: Oren Eini (Ahende Rahien). [The Fallacy of Distributed Transactions](https://ayende.com/blog/167362/the-fallacy-of-distributed-transactions). *ayende.com*, July 2014. Archived at [perma.cc/VB87-2JEF](https://perma.cc/VB87-2JEF)
[^82]: Clemens Vasters. [Transactions in Windows Azure (with Service Bus) – An Email Discussion](https://learn.microsoft.com/en-gb/archive/blogs/clemensv/transactions-in-windows-azure-with-service-bus-an-email-discussion). *learn.microsoft.com*, July 2012. Archived at [perma.cc/4EZ9-5SKW](https://perma.cc/4EZ9-5SKW)
[^83]: Ajmer Dhariwal. [Orphaned MSDTC Transactions (-2 spids)](https://www.eraofdata.com/posts/2008/orphaned-msdtc-transactions-2-spids/). *eraofdata.com*, December 2008. Archived at [perma.cc/YG6F-U34C](https://perma.cc/YG6F-U34C)
[^84]: Paul Randal. [Real World Story of DBCC PAGE Saving the Day](https://www.sqlskills.com/blogs/paul/real-world-story-of-dbcc-page-saving-the-day/). *sqlskills.com*, June 2013. Archived at [perma.cc/2MJN-A5QH](https://perma.cc/2MJN-A5QH)
[^85]: Guozhang Wang, Lei Chen, Ayusman Dikshit, Jason Gustafson, Boyang Chen, Matthias J. Sax, John Roesler, Sophie Blee-Goldman, Bruno Cadonna, Apurva Mehta, Varun Madan, and Jun Rao. [Consistency and Completeness: Rethinking Distributed Stream Processing in Apache Kafka](https://dl.acm.org/doi/pdf/10.1145/3448016.3457556). At *ACM International Conference on Management of Data* (SIGMOD), June 2021. [doi:10.1145/3448016.3457556](https://doi.org/10.1145/3448016.3457556)
