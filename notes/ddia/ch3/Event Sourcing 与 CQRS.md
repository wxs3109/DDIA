# Event Sourcing 与 CQRS

本 note 对应 DDIA 第 3 章的 `Event Sourcing 与 CQRS` section。这个 section 的核心不是介绍一种新的查询语言，而是在讨论一种更特殊的数据建模方式：**写入时只记录发生过的 event，把 event log 当作 source of truth，然后从 event log 派生出多个面向读取优化的 materialized view。**

它和前面讨论的 `relational model`、`document model`、`graph model` 的关系是：前面那些模型通常是“数据以什么形式写入，也以什么形式查询”；而 `event sourcing` 刻意把 write model 和 read model 分开。

## 为什么需要把写模型和读模型分开

在很多系统里，一种数据表示很难同时满足所有查询需求。例如会议管理系统里，业务状态可能由很多动作共同决定：

- 会议开放注册。
- 个人参会者注册并付款。
- 公司批量购买座位。
- 公司把座位分配给员工。
- 预订被取消。
- 场地容量改变。
- 座位被保留给 speaker、sponsor、volunteer。

如果你只维护一张“当前 bookings 表”，每次 command 来了就直接 update 当前状态，那么读取当前可用座位很方便；但你会丢失很多“为什么变成这样”的上下文。比如你看到 `bookings.active = false`，但不知道它是用户取消、支付失败、管理员撤销，还是会议被改期导致。

`event sourcing` 换了一个角度：不要首先存“当前状态长什么样”，而是先存“发生了什么”。当前状态、报表、仪表盘、打印名单、可用座位数量，都从这些 event 推导出来。

## event log 是为了写数据优化的吗

是的，但要准确理解这里的“写优化”。

`event log` 的写入方式通常是 append-only：每次发生一个业务事实，就把一个 event 追加到 log 末尾，而不是到处 update 多张当前状态表。append-only write 通常简单、快速，也更容易保留完整历史。

例如：

```json
{"event_id": 1, "type": "RegistrationOpened", "conference_id": "ddia-2026", "capacity": 300, "time": "2026-04-01T09:00:00Z"}
{"event_id": 2, "type": "SeatReserved", "reservation_id": "r1", "user_id": "u1", "conference_id": "ddia-2026", "time": "2026-04-02T10:00:00Z"}
{"event_id": 3, "type": "PaymentReceived", "reservation_id": "r1", "amount": 499, "currency": "USD", "time": "2026-04-02T10:01:00Z"}
{"event_id": 4, "type": "ReservationCancelled", "reservation_id": "r1", "reason": "user_request", "time": "2026-04-03T12:00:00Z"}
```

这些 event 是按顺序追加的。写入时不需要立刻把所有查询场景需要的表都更新到完美形态；可以先把事实记录下来，再让下游 `projection` / `materialized view` 去消费。

但这不表示 event sourcing 写起来没有成本。真正的 command 在变成 event 之前仍然要验证，例如是否还有座位、用户是否有权限取消、支付是否有效。只是验证通过以后，系统写入的是一个 immutable event，而不是直接把所有 read model 当作 source of truth 去改。

## event log 是“按时间顺序记录操作，逐步 update”吗

接近，但要区分 `command`、`event` 和 `state update`。

`command` 是用户或外部系统请求系统做某事，例如：

```text
ReserveSeat(user_id=u1, conference_id=ddia-2026)
CancelReservation(reservation_id=r1)
```

`command` 不是事实，它可能失败。比如座位已经满了，`ReserveSeat` 就不能成功。

`event` 是 command 被验证并执行以后产生的事实，通常用过去时命名：

```text
SeatReserved
ReservationCancelled
PaymentReceived
ConferenceCapacityChanged
```

`state update` 是 materialized view 消费 event 以后产生的结果。例如 `SeatReserved` 会让 `available_seats` 减 1，`ReservationCancelled` 会让 `available_seats` 加 1，`PaymentReceived` 会让某个 reservation 的 payment status 变成 paid。

所以 event log 不是简单记录“我要 update 某列为某值”的操作日志，而是记录业务层面的事实。更好的 event 是：

```text
ReservationCancelled(reservation_id=r1, reason=user_request)
```

而不是：

```text
UPDATE bookings SET active = false WHERE id = r1
```

前者保留了业务语义，后者只是数据库层面的变化。

> [!NOTE] Wenbo 注
> 可以把 event log 理解为“业务事实的时间线”，不是普通数据库 WAL 那种物理 redo log。WAL 关心如何恢复数据库页；event sourcing 的 event log 关心业务世界发生了什么。

## event log 的目的：source of truth 与 derived data

你的理解是对的：event log 的一个重要目的，是保存足够原始、足够完整的业务事实，让系统可以从它派生出多种不同的 `derived data`。

这些 derived data 可以服务不同读场景：

- 给用户看的 reservation status。
- 给组织者看的 dashboard。
- 给财务看的 revenue report。
- 给门口工作人员打印 badge 的 attendee list。
- 给运营看的 cancellation rate aggregation。

这些 view 可以使用不同的数据模型：

- relational table。
- document。
- key-value cache。
- search index。
- in-memory structure。
- analytics table。

这就是它和 ETL / data warehouse 的相似之处：先有一个 source of truth，再从中派生出为不同查询优化的数据表示。

但 event sourcing 更强调两点：

1. event log 不只是分析用的历史记录，而是业务系统的 source of truth。
2. event 的顺序很重要，因为当前状态是按顺序 replay event 得到的。

## 什么是 materialized view

`materialized view` 在这里也叫 `projection` 或 `read model`。它是从 event log 计算出来、并实际存储下来的读取优化结果。

它和普通 `view` 的区别是：

- 普通 SQL `view` 通常只是保存 query definition，查询时再计算。
- `materialized view` 是把计算结果存下来，读取时直接查结果。

例如 event log 里有：

```text
ConferenceCapacitySet(capacity=300)
SeatReserved(reservation_id=r1)
SeatReserved(reservation_id=r2)
ReservationCancelled(reservation_id=r1)
```

一个 `available_seats` materialized view 可以维护成：

```text
capacity = 300
reserved_active_count = 1
available_seats = 299
```

另一个 `attendee_badge_list` materialized view 可以维护成：

```text
reservation_id | user_name | badge_status
r2             | Alice     | ready_to_print
```

第三个 `organizer_dashboard` materialized view 可以维护成：

```text
paid_count = 1
cancelled_count = 1
revenue_usd = 499
```

同一个 event log 可以派生多个 materialized view，因为不同读场景关心的数据形状不同。

> [!NOTE] Wenbo 注
> `materialized view` 的关键是“结果已经算好并存下来”。它不是 source of truth，而是 cache / projection / read model。坏了可以删掉重建；落后了可以继续消费 event catch up；但用户读的时候通常就是读它，因为它快。

## CQRS 是什么

`CQRS` 是 `Command Query Responsibility Segregation`，意思是把写入路径和读取路径分开设计。

在传统 CRUD 系统里，同一套 table 往往既负责写，也负责读：

```text
write: UPDATE bookings SET ...
read:  SELECT ... FROM bookings JOIN ...
```

在 event sourcing + CQRS 风格里：

```text
command -> validation -> append event -> update projections/materialized views -> query read models
```

写入侧关心：

- command 是否有效。
- 业务 invariant 是否满足。
- 生成什么 event。
- event 是否按正确顺序持久化。

读取侧关心：

- 用户界面需要什么形状的数据。
- 查询是否足够快。
- 是否需要 denormalized read model。
- 是否可以接受 projection 稍微延迟。

CQRS 不要求一定使用 event sourcing；你可以只分离 command model 和 query model。但 event sourcing 经常和 CQRS 一起出现，因为 event log 很自然可以派生多个 read model。

## 重新理解 star schema 和 fact table

书中说 event sourcing 和 `star schema` 里的 `fact table` 有相似之处，因为两者都记录“过去发生的事件”。

先回忆 `star schema`：它常用于 data warehouse。中间是一张很大的 `fact table`，周围是一圈 `dimension table`。

例如零售数据仓库：

```text
fact_sales
- sale_id
- product_id
- store_id
- customer_id
- date_id
- quantity
- price
```

周围的 dimension table：

```text
dim_product(product_id, brand, category, size)
dim_store(store_id, city, region)
dim_customer(customer_id, age_group, segment)
dim_date(date_id, day, month, holiday_flag)
```

`fact table` 的每一行通常代表一个发生过的业务事件，例如“一次销售”。这和 event log 有点像：都是过去发生的 event 集合。

但差异也很重要：

| 对比 | event log | star schema fact table |
| --- | --- | --- |
| 主要用途 | OLTP / business source of truth | analytics / data warehouse |
| 顺序是否重要 | 通常很重要 | 通常不重要，是无序集合 |
| 事件类型 | 可以有很多 type，每种 schema 不同 | 通常同一 fact table schema 固定 |
| 是否驱动当前状态 | 是，replay event 得到 current state | 通常用于分析，不是业务当前状态 source of truth |
| 是否 append-only | 通常 append-only | 通常也是追加历史事实，但可能被 ETL 修正 |

例如 event sourcing 中：

```text
SeatReserved(r1)
ReservationCancelled(r1)
```

顺序不能反。如果先取消再预订，语义就不一样。fact table 里的销售记录则通常可以按任意顺序聚合。

## 优点：为什么这种方式有吸引力

### 1. event 解释了为什么发生变化

直接 update 当前状态通常只看到结果，看不到原因：

```sql
UPDATE bookings SET active = false WHERE id = 4001;
```

event sourcing 记录的是业务事实：

```text
ReservationCancelled(reservation_id=4001, reason=user_request)
```

这对调试、审计、理解业务流程都更友好。

### 2. materialized view 可以重建

因为 materialized view 是从 event log 派生出来的，所以理论上可以删除它，然后从头 replay event log 重新计算。

这在两类场景很有用：

- projection 代码有 bug，修复后可以重放 event 得到正确 view。
- 新增一个读场景，可以从旧 event log 构建新的 materialized view。

例如一开始只有 attendee list，后来想新增 revenue dashboard，就可以写一个新的 projection 从历史 event 中计算 revenue。

### 3. 可以有多个 read model

同一份 event log 可以派生多个读模型。每个 read model 都可以为自己的查询优化，甚至可以 denormalized。

这和前面章节的 normalization / denormalization 思路接上了：event log 是 source of truth，materialized view 可以为了读取性能而 denormalized；如果 view 坏了，可以从 source of truth 重建。

### 4. 容易支持新功能和审计

只要旧 event 保留，新功能可以通过添加新 event type 或新 projection 来演进。

event log 也天然是 audit log：你能看到系统里发生过什么、什么时候发生、由谁触发。

### 5. 减少不可逆操作

传统数据库里，一旦直接 update / delete，想恢复旧状态可能很难。event sourcing 里通常通过追加补偿 event 表达变化，例如取消预订不是删除原来的 `SeatReserved`，而是追加 `ReservationCancelled`。

这让系统更容易解释历史，也更容易重建不同时间点的状态。

## 缺点和边界

### 1. 外部信息会破坏可重放性

如果 projection 处理 event 时依赖外部数据，就可能无法 deterministic replay。

例如 event 里有 499 USD，某个 materialized view 要换算成人民币。如果 replay 时去查“当前汇率”，那今天 replay 和明天 replay 会得到不同结果。

解决方式通常是：

- event 里记录当时使用的 exchange rate。
- 或者有一个可按历史时间查询、结果稳定的 exchange-rate table。

核心原则是：replay 同一批 event，应该得到同样的 materialized view。

### 2. personal data 和 immutable event log 有冲突

event sourcing 喜欢 immutable event，但隐私法规或用户请求可能要求删除 personal data。这里就会出现张力。

如果 event log 是每个用户单独一份，删除某个用户的 log 相对简单。但如果一个 event log 混合了很多用户的事件，删除某个人的数据会影响整个 log 的可重放性。

常见缓解方式包括：

- event 中尽量不直接存 personal data，只存 user ID。
- personal data 存在单独 profile store，event 引用它。
- 对 personal data 加密，删除 key 让数据不可恢复。
- 设计 redaction event 或 tombstone，但这会让 replay 逻辑更复杂。

### 3. replay 不能重复外部副作用

重建 materialized view 时，你不希望重新发送邮件、重新扣款、重新调用外部 API。

所以 projection 代码要区分：

- 纯粹计算 read model 的逻辑，可以 replay。
- 外部 side effect，例如发邮件、扣款、发短信，必须有幂等控制或不能在 replay 中执行。

## 删除中间 event 会不会让后面崩掉

这是你问的最关键问题之一。答案是：**可能会影响后续 materialized view，但不一定“崩掉”；取决于 event 之间有没有依赖，以及系统如何设计 deletion / redaction。**

先看简单 aggregation：

```text
+10
+20
-5
```

如果删除中间的 `+20`，重新 replay 后结果会从 25 变成 5。这不会崩，只是结果改变了。

但很多业务 event 不是独立数值，而有因果依赖：

```text
SeatReserved(reservation_id=r1)
PaymentReceived(reservation_id=r1)
ReservationCancelled(reservation_id=r1)
RefundIssued(reservation_id=r1)
```

如果你删除中间的 `PaymentReceived`，后面的 `RefundIssued` 可能就失去依据：为什么退款？退给谁？退多少钱？如果你删除 `SeatReserved`，后面的付款、取消、退款都可能变成 dangling event。

所以 event sourcing 里通常不鼓励随便物理删除中间 event。更常见的做法是追加新的 correction / compensation event：

```text
ReservationCorrected(...)
ReservationCancelled(...)
PersonalDataRedacted(user_id=u1)
```

如果必须满足“用户要求删除 personal data”，更稳的设计是不要让 event log 直接包含大量 personal data，而是：

```text
SeatReserved(reservation_id=r1, user_id=u1)
```

用户姓名、邮箱、电话存在 profile store。用户要求删除时，删除 profile store 里的 personal data，event log 里只剩不可识别或已匿名化的 ID。这样很多 aggregate 仍然可以 replay，比如总报名人数、收入、取消率；但不能再恢复用户个人身份。

如果法规或业务要求连 user_id 也必须删除，那就需要 redaction 策略。redaction 之后的 event log 不再是原始完整历史，而是一个经过隐私处理的历史。系统需要确保 projection 能处理 redacted event，例如把用户显示为 deleted user，或跳过某些个人化 view。

> [!NOTE] Wenbo 注
> materialized view 基于时序 aggregation 时，删除中间 event 的正确心智模型是“从头重新算会得到另一个历史版本的结果”。如果后续 event 依赖被删 event，系统不会自动知道怎么解释，除非你设计了 correction / redaction 规则。所以 event sourcing 的难点不是 aggregation 本身，而是事件语义、依赖关系和隐私删除策略。

## event log 是不是“原始数据”

可以说 event log 保存的是业务系统层面的原始事实，但不是未经处理的所有输入。

例如用户点击“预订座位”这个原始 HTTP request 不是最终 event。系统需要验证座位是否可用、支付是否成功、用户是否符合条件。验证通过后写入的 `SeatReserved` 才是 event log 中的事实。

所以 event log 不是 raw request dump，而是 validated business facts。

这点很重要：构建 materialized view 的消费者不应该拒绝 event。因为 event 已经是事实了；如果消费者处理不了，那是 consumer / projection 的 bug，而不是 event 无效。

## 实现方式

event sourcing 可以建立在很多存储系统上：

- 专门的 event store，例如 EventStoreDB。
- PostgreSQL 上的 event table，例如 MartenDB。
- message broker / log，例如 Kafka。
- 普通 database table，只要能保证 append、order、durability。

真正重要的要求是：所有 materialized view 必须以 event log 中相同的顺序处理 event。顺序错了，状态就可能错。

例如：

```text
SeatReserved(r1)
ReservationCancelled(r1)
```

和：

```text
ReservationCancelled(r1)
SeatReserved(r1)
```

语义完全不同。

在分布式系统中，全局顺序、分区顺序、跨 shard 事件顺序都很难，我们会在后面章节看到更多。

## 和其他模型的关系

`event sourcing` 不是替代 relational / document / graph 的万能模型。它更像是一种 source-of-truth 建模方式。

你仍然可以从 event log 派生出：

- relational read model。
- document read model。
- graph read model。
- search index。
- analytics fact table。
- in-memory cache。

它适合复杂业务流程、审计要求强、需要重建 read model、需要多个读视图的系统。

它不适合所有场景。如果业务只是简单 CRUD，例如维护一个用户偏好设置表，event sourcing 可能引入过多复杂性。你需要额外处理 projection lag、schema evolution、event versioning、replay、side effect、privacy deletion 等问题。

## 本节核心 takeaway

`event sourcing` 的核心是：把每次有效状态变化记录成 immutable event，把 event log 当作 source of truth。

`CQRS` 的核心是：把 write side 和 read side 分开；write side 负责验证 command 并追加 event，read side 负责维护面向查询优化的 materialized view。

`materialized view` 是从 event log 派生并存储下来的 read model。它不是 source of truth，可以重建；但重建要求 event 足够完整、顺序正确、projection deterministic。

`fact table` 和 event log 都像“过去事件的集合”，但 fact table 主要用于 analytics，通常无序、schema 固定；event log 通常用于业务 source of truth，顺序重要、event type 可以多样。

删除中间 event 不一定会让系统崩，但会改变 replay 结果，并可能破坏后续 event 的语义依赖。实际系统通常通过 compensation event、redaction、外置 personal data、加密删除等方式处理，而不是随便物理删除历史中间项。
