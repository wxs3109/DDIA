---
title: "5. 编码与演化：学习总结"
weight: 106
breadcrumbs: false
---

本章的核心不是“哪种 serialization format 更省空间”，而是：**当 data format、schema、service API 和系统部署节奏都在变化时，如何让不同版本的代码继续互相读懂对方的数据。**

换句话说，encoding 是系统之间的契约；evolution 是契约如何安全变化。

## 1. 一句话主线

data-intensive applications 必然会演化：字段会增加、schema 会变化、service 会升级、client 和 server 不会同时更新。为了支持 rolling upgrade 和长期演进，系统里的数据必须同时考虑 **backward compatibility** 和 **forward compatibility**。

本章先讨论几类 encoding formats 如何支持 schema evolution，再把这些 encoding 放回不同 dataflow 场景中：database、REST/RPC service、workflow engine、message broker 和 distributed actor framework。

可以把全章主线压成一条链：

```text
data structure in memory
-> encoding into bytes
-> decoding by another process/version
-> compatibility across old/new code
-> evolvable system architecture
```

## 2. 全章概念地图

本章反复围绕三组关系展开。

| 关系 | 问题 | 本章关注点 |
| --- | --- | --- |
| memory object vs byte sequence | 内存里的 object 如何变成可存储、可传输的 bytes | encoding、decoding、serialization、marshalling |
| old code vs new code | 新旧版本能不能互相读懂数据 | backward compatibility、forward compatibility、schema evolution |
| writer vs reader | 谁写出 bytes，谁负责读 bytes | writer schema、reader schema、field tags、schema registry |

最重要的判断是：**compatibility 不是 format 自己孤立拥有的属性，而是 writer 和 reader 之间的关系。**

例如：

```text
old writer -> new reader  = backward compatibility
new writer -> old reader  = forward compatibility
```

这里的 “backward / forward” 不要按时间线死记，而要按代码版本视角理解：new code 回头读 old data，是 backward compatibility；old code 提前遇到 future data，是 forward compatibility。

## 3. 为什么 encoding 会影响 evolvability

程序在内存中使用 objects、structs、lists、hash maps、trees 等数据结构。但这些结构依赖进程内地址、指针和语言运行时，不能直接写到磁盘或发给另一个进程。

所以系统必须做两件事：

```text
encoding: in-memory data structure -> byte sequence
decoding: byte sequence -> in-memory data structure
```

这一步看似只是技术细节，但它决定了后续系统能不能演化：

- 如果 encoding 和某个 programming language 强绑定，跨语言和长期存储会很困难。
- 如果 format 不保留 unknown fields，old code 读写 new data 时可能丢字段。
- 如果 schema evolution 没有规则，rolling upgrade 时新旧节点可能互相读不懂。
- 如果 service API 没有兼容性策略，provider 和 client 就必须同步升级。

所以本章不是单纯比较 JSON、Protocol Buffers、Avro 的体积，而是在问：**这些 bytes 将来由谁读？读的时候 schema 是否已经变了？旧代码遇到新字段会怎么做？**

## 4. Backward Compatibility 与 Forward Compatibility

两个 compatibility 是本章最核心的地基。

| 概念 | 直观解释 | 典型场景 |
| --- | --- | --- |
| **backward compatibility** | new code 可以读 old code 写的数据 | 服务端升级后读取历史数据库记录 |
| **forward compatibility** | old code 可以读 new code 写的数据 | rolling upgrade 中旧节点读取新节点写入的数据 |

backward compatibility 通常更容易，因为写 new code 的人知道 old format 长什么样，可以显式处理旧数据。

forward compatibility 更难，因为它要求 old code 在不知道 future fields 的情况下仍然能工作。常见策略是：

- old reader 忽略不认识的新字段；
- old reader 在重写数据时保留 unknown fields；
- new fields 要设计成 optional 或有 default value；
- 删除字段和修改字段类型要非常谨慎。

图 5-1 想强调的风险是：old code 读到 new code 写入的记录后，如果更新并写回，但没有保留 unknown fields，就可能把 new fields 丢掉。这是 forward compatibility 的典型陷阱。

## 5. Language-Specific Formats：方便但危险

Java `java.io.Serializable`、Python `pickle`、Ruby `Marshal` 这类 language-specific formats 很方便，因为它们能直接保存和恢复语言里的 object。

但它们通常不适合作为长期数据格式或跨系统协议：

- 它们绑定特定 programming language 和 runtime object model。
- 它们经常隐含 class name、module path、constructor、private fields 等语言细节。
- 它们可能在 decoding 时实例化任意 class，带来 arbitrary code execution 风险。
- 它们通常不认真处理 schema evolution。
- 它们的 encoded representation 经常臃肿且性能一般。

所以这类 format 更适合短期、内部、同语言、可信输入场景，例如临时 cache 或本地 checkpoint。跨服务、跨组织、长期存储时应优先考虑 JSON、Protocol Buffers、Avro 等语言无关格式。

## 6. JSON、XML、CSV：通用但语义不够强

JSON、XML、CSV 的优势是开放、通用、人类可读、生态广，尤其适合 Web API 和跨组织数据交换。

但它们的问题是：**文本 format 本身通常只给出浅层结构，很多业务语义要靠 schema 或应用代码补上。**

典型问题包括：

- number 精度不明确，例如 JavaScript `Number` 无法精确表示大于 $2^{53}$ 的整数；
- binary data 需要 Base64，体积约增加 33%；
- CSV 没有内建 schema，列含义、空值、编码、转义规则都靠外部约定；
- JSON/XML Schema 能表达很多约束，但复杂度也高。

JSON Schema 可以把“数据长什么样”和“数据要满足什么约束”写成另一份 JSON。例如它不仅可以说 `port` 是 integer，还可以说它必须在 1 到 65535 之间。

这里容易混淆的是：**JSON data 和 JSON Schema 是两份东西。** JSON data 是业务数据，JSON Schema 是用 JSON 写出来的数据说明书和验证规则。

## 7. Open Content Model 与 Closed Content Model

JSON Schema 里一个重要但容易忽略的点是 content model。

| 模型 | 含义 | 影响 |
| --- | --- | --- |
| **open content model** | schema 没列出的字段也允许出现 | 更利于 forward compatibility，但可能让错误字段溜进去 |
| **closed content model** | 只允许 schema 显式列出的字段 | 更严格，但更容易破坏 forward compatibility |

JSON Schema 默认是 open content model，也就是 `additionalProperties: true`。这有利于 old reader 忽略 future fields，但也意味着 schema 更像是在定义“哪些值不合法”，而不是完全定义“只允许哪些内容”。

如果你把 `additionalProperties: false` 打开，就进入 closed content model。这样可以抓住拼错字段名、额外字段等错误，但 rolling upgrade 和跨版本演化会更敏感。

## 8. MessagePack：更像 Binary JSON

MessagePack、CBOR、BSON 等 binary JSON variants 的目标是把 JSON/XML 风格的数据模型编码得更紧凑、更快解析。

但它们通常仍保留 JSON-like data model：objects、arrays、strings、numbers。它们不强制 schema，所以 encoded data 里仍然需要包含 field names。

这就是 MessagePack 和 Protocol Buffers 的关键区别：

```text
MessagePack:      "userName" -> "Martin"
Protocol Buffers: field 1    -> "Martin"
```

MessagePack 可以省掉一些文本语法开销，但不能像 schema-driven binary formats 那样省掉字段名。因此它比 JSON 更紧凑，但通常不会像 Protocol Buffers 或 Avro 那么紧凑。

## 9. Protocol Buffers：Field Tags 是长期契约

Protocol Buffers 是 schema-driven binary encoding。它不会在 encoded data 里写字段名，而是写 field tag。

例如 schema 中：

```protobuf
message Person {
  string user_name = 1;
  int64 favorite_number = 2;
  repeated string interests = 3;
}
```

encoded data 里不会写 `user_name`，而是写 field tag `1`。reader 必须拿着同一份 `.proto` schema 才知道 `1` 代表 `user_name`。

这带来两个结果：

- compactness 很好，因为字段名不需要反复写入每条消息；
- field tag 变成长期兼容性的核心，不能随便改、不能复用。

Protocol Buffers 的 schema evolution 规则可以这样记：

- 可以 rename field，因为 encoded data 不引用 field name；
- 不能改 field tag，因为历史数据里的 tag 已经代表旧含义；
- 可以 add new field，只要使用新的 tag；
- old code 可以跳过 unknown tags，因此支持 forward compatibility；
- new code 读 old data 时，新字段缺失就用 default value；
- delete field 后，旧 tag 应该 reserved，避免未来误用；
- type changes 要谨慎，可能出现 truncation 或 interpretation mismatch。

Protocol Buffers 的核心 trade-off 是：**用人工维护 field tags 换取紧凑编码、跨语言 code generation 和清晰的 evolution rules。**

## 10. Avro：Writer Schema 与 Reader Schema

Avro 也是 schema-driven binary encoding，但它和 Protocol Buffers 的设计重点不同。Avro 没有 field tags，encoded data 更像是按 schema 顺序写出的一串 values。

这意味着 Avro decoding 必须知道写入时使用的 **writer schema**。reader 还会使用自己期望的 **reader schema**。如果两者不同，Avro 做 **schema resolution**。

Avro 的核心模型是：

```text
writer schema: 写数据时使用的 schema
reader schema: 读数据时应用代码期望的 schema
schema resolution: reader 对照两份 schema，把 old/new fields 对齐
```

Avro schema resolution 的关键规则：

- fields 按 field name 匹配，不按位置匹配；
- writer schema 有、reader schema 没有的 field 会被忽略；
- reader schema 有、writer schema 没有的 field 必须有 default value；
- field order 可以变；
- 某些 type changes 可以转换，但要满足 Avro 的兼容规则。

这和 Protocol Buffers 的差别可以这样记：

| 格式 | 字段如何识别 | 演化核心 |
| --- | --- | --- |
| **Protocol Buffers** | field tag | tag 不能改、不能复用 |
| **Avro** | field name + writer/reader schema resolution | reader 必须知道 writer schema |

Avro 更适合 dynamically generated schema，例如从 relational database schema 自动生成 Avro schema 做数据导出。因为它不需要管理员手动维护 column 到 field tag 的映射。

## 11. Avro 中的 Schema Evolution 规则

Avro 中判断 compatibility 时，一定要把 writer/reader 和 old/new 对齐。

| 场景 | writer schema | reader schema | 兼容性 |
| --- | --- | --- | --- |
| new code reads old data | old schema | new schema | backward compatibility |
| old code reads new data | new schema | old schema | forward compatibility |

为了保持兼容性，新增或删除字段时通常要求字段有 default value。

新增字段的问题发生在 backward compatibility 上：new reader 读 old writer 写的数据时，old data 没有新字段，所以 new schema 必须知道怎么补 default value。

删除字段的问题发生在 forward compatibility 上：old reader 读 new writer 写的数据时，old reader 可能还期待那个字段。如果 old reader 无法补 default value，就会失败。

一句话记忆：**新增字段时，麻烦在 new code 读 old data；删除字段时，麻烦在 old code 读 new data。**

Avro 的另一个重要点是 `null` 不是默认允许的。要允许 `null`，必须显式使用 union type，例如：

```avro
union { null, long } favoriteNumber = null;
```

这比“一切默认 nullable”啰嗦，但能让 schema 更清楚地表达哪些字段真的可以缺失。

## 12. Writer Schema 从哪里来

Avro decoding 需要 writer schema，但不能每条记录都附带完整 schema，因为 schema 可能比数据本身还大。

常见做法按场景不同：

| 场景 | writer schema 获取方式 |
| --- | --- |
| 大文件 | 文件头只写一次 writer schema，例如 Avro object container file |
| 数据库单条记录 | 每条记录带 schema version，reader 去 schema registry 查对应 schema |
| 网络连接 | 连接建立时协商 schema version，连接期间复用 |

schema registry 的作用不只是“存 schema”，还可以：

- 作为文档；
- 阻止破坏 compatibility 的 schema change；
- 让 producer 和 consumer 不必把完整 schema 附在每条消息里；
- 支持多版本数据长期共存。

## 13. Schema-Driven Binary Formats 的共同优势

Protocol Buffers 和 Avro 这样的 schema-driven formats 不是只为了省空间，它们提供的是一整套工程能力：

- encoded data 更 compact，因为字段名可以省略；
- schema 是长期可维护的 documentation；
- code generation 可以给 static types 提供编译期检查；
- schema registry 可以在部署前检查 compatibility；
- schema evolution 给 rolling upgrade 提供规则基础。

它们的代价是：

- 人类不能直接读 bytes；
- 调试需要 schema 和 decoder；
- schema 管理本身变成工程流程的一部分；
- 对开放 Web API 来说，JSON/OpenAPI 的可读性和普适性仍然很有价值。

## 14. 格式选型总览

| 格式 | 主要优点 | 主要代价 | 典型场景 |
| --- | --- | --- | --- |
| **JSON** | 人类可读、Web 友好、跨语言 | 类型语义弱、体积大、schema optional | public API、配置、调试友好数据交换 |
| **XML** | 历史生态强、schema 能力强 | 冗长、复杂 | 老系统集成、文档型协议 |
| **CSV** | 简单、工具支持好 | 没有 schema、嵌套能力弱、转义容易错 | 表格导入导出、简单批量交换 |
| **MessagePack** | JSON-like 但更紧凑 | 仍常保留 field names，schema evolution 弱 | 想保留 JSON 模型但减少体积 |
| **Protocol Buffers** | compact、fast、codegen、RPC 友好 | field tags 要长期维护 | internal services、gRPC、跨语言 RPC |
| **Avro** | compact、schema resolution 强、适合动态 schema | reader 需要 writer schema | data pipelines、Kafka、batch files、schema registry |

粗略口诀：**public interface 先想 JSON/OpenAPI；internal high-performance RPC 常用 Protocol Buffers/gRPC；data pipeline 和 event stream 常用 Avro + schema registry；临时同语言对象别轻易外传。**

## 15. Dataflow Pattern 1：Database

在 database dataflow 中，writer 是写数据库的进程，reader 是之后读取数据库的进程。即使只有一个应用，也可以把数据库看作：**向未来的自己发送消息。**

这里 backward compatibility 很重要，因为未来版本的代码要能读过去写下的数据。

但在 rolling upgrade 中，也会出现 forward compatibility：new code 写入数据库，old code 还没下线，又读到了这条记录。

database 场景有一个重要事实：**data outlives code**。代码几分钟就能升级完，但五年前写入的数据可能仍然在数据库里。

简单 schema changes，例如新增 nullable column，许多 relational databases 可以不重写历史数据；读取旧行时给缺失列补 `NULL`。

复杂 schema changes 就困难得多，例如：

```text
users(id, name, phone)

->

users(id, name)
user_phones(user_id, phone)
```

这类变化不是简单 add/drop field，而是数据结构重组，通常需要 backfill、dual write、compatibility layer、分阶段 cutover。它们很难同时让 old code 和 new code 都看到完全合理的数据。

## 16. Archival Storage：重编码是机会

backup、snapshot、data warehouse import 这类 archival storage 场景通常会复制大量数据。既然已经在复制，就可以顺便把数据重编码成统一的最新 schema。

这和在线数据库不同：在线数据库里历史记录可能保留多种旧 encoding；而 data dump 通常可以导出成一个一致的 schema。

Avro object container file 很适合这种一次写入、多次读取的大文件。Parquet 这类 column-oriented formats 则适合 analytics，因为它们能高效扫描部分列、做压缩和聚合。

## 17. Dataflow Pattern 2：REST 与 RPC

service dataflow 中有两股方向相反的数据：

```text
request:  client writes -> server reads
response: server writes -> client reads
```

这导致 compatibility 要分方向看。书里简化假设是：server 先升级，client 后升级。

因此需要：

- request backward compatibility：new server 能读 old client 发来的 request；
- response forward compatibility：old client 能读 new server 返回的 response。

REST 的核心不是“用了 HTTP 就是 REST”，而是：用 URL 标识 resources，用 HTTP methods 表达操作，用 HTTP headers 处理 caching、authentication、content negotiation，用 body 承载 representation。

OpenAPI 的作用是把 REST/JSON API 的 endpoint、request、response、schema、version、documentation 写成机器可读的 service definition。它让 client SDK、文档、测试工具和 compatibility checks 更容易自动化。

gRPC 则通常使用 Protocol Buffers 定义 service 和 messages，更适合内部服务之间的高性能、强 schema RPC。

## 18. RPC 的真正问题：Location Transparency 的错觉

RPC 的吸引力是让 remote call 看起来像 local function call：

```python
result = user_service.get_user(123)
```

但本章批评的是这种 **location transparency** 的错觉，而不是说“永远不要用 RPC”。

remote call 和 local call 的本质差异包括：

- network request 可能 timeout，而 timeout 后你不知道对方是否已经处理；
- retry 可能导致副作用重复执行；
- latency 更高且波动大；
- 参数和返回值必须 encoding/decoding；
- client/server 可能使用不同 language 和 type system；
- partial failure 是常态，而不是异常。

所以正确心态是：**可以用 RPC，但要把它当作 unreliable network boundary，而不是普通函数调用。**

这也连接到后面的 durable execution 和 idempotency：只要有 network retry，就要问“重复执行是否安全”。

## 19. Load Balancer、Service Discovery、Service Mesh

service communication 不只需要 encoding，还需要找到对方在哪里，并把 traffic 分散到多个 instances 上。

| 概念 | 解决的问题 | 典型方式 |
| --- | --- | --- |
| **load balancer** | 把请求分配到多个 service instances | hardware LB、Nginx、HAProxy |
| **DNS** | 用 domain name 找到 IP | 多个 A records、DNS round-robin |
| **service discovery system** | 动态跟踪健康 service endpoints | registry、heartbeat、metadata |
| **service mesh** | 把 load balancing、TLS、retries、observability 下沉到 proxy/sidecar | Istio、Linkerd、Envoy sidecar |

DNS 简单，但缓存和 TTL 让它不适合特别动态的实例变化。service discovery system 更像“活的服务通讯录”，可以返回健康 endpoints 和 metadata，例如 zone、shard、datacenter。

service mesh 则更进一步：每个 service instance 旁边部署 sidecar proxy。业务代码不直接处理 TLS、retry、timeout、tracing，而是把这些交给本地 sidecar。

service mesh 的 trade-off 是复杂度：多了 proxy hop、control plane、policy、certificate、debug surface。小系统未必值得用。

## 20. Dataflow Pattern 3：Workflow Engine 与 Durable Execution

workflow 是一组 task/activity 组成的业务流程，例如支付系统中：

```text
check_fraud -> debit_credit_card -> deposit_to_bank
```

workflow engine 负责调度 task、决定在哪里执行、失败后如何重试、并发度如何控制。常见角色包括：

- orchestrator：决定 task 何时执行；
- executor：实际执行 task/activity。

durable execution 的目标是让长流程在故障后能恢复，并尽量提供 **exactly-once semantics**。它的关键不是“永不重跑代码”，而是：**记录执行历史，重跑时把已经成功的 activity 结果回放出来，只继续执行没完成的部分。**

例如信用卡已经扣款成功，但 worker 崩溃了。恢复后 framework 再次跑到 `debit_credit_card` 时，不应该真的再扣一次，而应该返回历史里记录的 `success(txn_id=...)`。

durable execution 依赖两个重要前提。

第一，external APIs 最好 idempotent。尤其是支付、发货、发券、转账这类有 side effect 的调用，应该带 **idempotency key**：

```text
charge(order_id=O123, amount=100, idempotency_key=payment_O123)
```

这样第三方系统可以识别“这是同一笔业务动作的 retry”，而不是两笔独立扣款。

第二，workflow code 必须 deterministic。给定同样 input 和 execution history，replay 时必须走出同样 control flow，并在同样位置发出同样 activity calls。

因此 workflow code 里直接使用 `random.random()`、`datetime.now()` 或随意重排 activity 顺序，都可能让 replay history 和代码路径对不上。

## 21. Dataflow Pattern 4：Message Broker

event-driven architecture 使用 event/message 作为进程间通信方式。和 RPC 不同，sender 通常不等待 receiver 立即处理，而是把 message 交给 message broker。

message broker 的作用包括：

- buffering：receiver 暂时不可用时先存住 message；
- redelivery：consumer 崩溃后重新投递；
- decoupling：sender 不需要知道 receiver 的 IP 地址；
- fan-out：同一 message 可以发给多个 subscribers；
- asynchronous communication：sender 发送后继续做别的事。

常见模式有两种：

| 模式 | 含义 |
| --- | --- |
| **queue** | 一个 message 交给一个 consumer 处理 |
| **topic** | 一个 message 发布给所有 subscribers |

message broker 本身通常只处理 bytes，不强制业务 data model。因此消息 format 仍然要自己选：JSON、Protocol Buffers、Avro 都可以。大型系统常把 Avro/Protobuf 和 schema registry 配在一起，检查 producer/consumer 的 compatibility。

如果 consumer 读取 message 后重新发布到另一个 topic，也要注意保留 unknown fields，否则可能复现图 5-1 的 forward compatibility 问题。

## 22. Dataflow Pattern 5：Distributed Actor Framework

Actor model 是一种并发编程模型：每个 actor 有自己的 local state，一次处理一条 message，通过 send/receive messages 与其他 actor 交互。它避免了多个线程直接共享 mutable state 时的 lock、race condition、deadlock 问题。

distributed actor framework 把 actor model 扩展到多台机器。无论两个 actors 在同一进程、同一机器还是不同节点上，开发者看到的都是“给 actor 发 message”。如果目标 actor 在远端，framework 负责 encoding、network transport、routing 和 decoding。

它和 message broker 的关系可以这样理解：

- message broker 更像独立邮局，应用围绕 queue/topic 发布和消费消息；
- distributed actor framework 更像“actor object model + message routing runtime”，应用围绕 actor identity 发消息；
- 它内部提供了类似 broker 的消息投递能力，但目标是支撑 actor 编程模型，而不是只提供通用 queue/topic 中间件。

对比：

```text
message broker:
order-service -> topic inventory-commands -> inventory-service

distributed actor framework:
OrderActor(O123) -> framework runtime -> InventoryActor(O123)
```

actor model 的 location transparency 比 RPC 更合理一些，因为 actor model 本来就假设 message 可能异步、可能丢失，不像 local function call 那样承诺同步返回。

但 distributed actor framework 仍然不能逃过本章主题：只要 message 跨节点、跨版本流动，就仍然需要 encoding、schema evolution、backward/forward compatibility。

## 23. 几组容易混淆的概念

| 概念 A | 概念 B | 区别 |
| --- | --- | --- |
| **encoding** | **serialization** | 本章使用 encoding 避免和 transaction serializability 混淆；serialization 常作为近义词 |
| **backward compatibility** | **forward compatibility** | backward = new reads old；forward = old reads new |
| **writer schema** | **reader schema** | writer schema 描述 bytes 当初怎么写；reader schema 描述当前代码想读成什么样 |
| **field name** | **field tag** | Avro 主要按 field name 对齐；Protocol Buffers encoded data 主要靠 field tag |
| **REST** | **RPC** | REST 更强调 resources 和 HTTP semantics；RPC 更像调用远程函数 |
| **service discovery** | **load balancing** | discovery 负责找到可用 endpoints；load balancing 负责从 endpoints 中选一个 |
| **message broker** | **distributed actor framework** | broker 是独立消息中间件；actor framework 把消息投递嵌入 actor runtime |
| **idempotency** | **exactly-once semantics** | idempotency 是重复请求结果不变；exactly-once 是系统试图让业务效果只发生一次 |
| **deterministic workflow** | **pure function** | workflow deterministic 重点是 replay 路径一致，不等于所有代码都必须数学上纯 |

## 24. 本章的连接关系

本章看似讲了很多 format 和 architecture，但核心连接很紧。

第一，encoding format 决定 data 在进程边界之外能否被正确解释。只要数据离开当前进程，它就需要一个稳定的 representation。

第二，schema evolution 决定系统能否 rolling upgrade。old/new code 同时存在是大型系统常态，不是例外。

第三，不同 dataflow pattern 只是 writer/reader 关系的不同版本：

| Dataflow | Writer | Reader |
| --- | --- | --- |
| database | 写数据库的进程 | 后续读数据库的进程 |
| REST/RPC request | client | server |
| REST/RPC response | server | client |
| workflow history | workflow framework / activity result recorder | replaying workflow code |
| message broker | producer | consumer |
| actor message | sender actor | receiver actor |

第四，RPC、workflow、message broker 都绕不开 retry 和 partial failure。只要请求可能 timeout，就必须考虑 idempotency、deduplication、compatibility 和 observability。

第五，schema 不只是 validation。它同时是 documentation、code generation input、compatibility contract 和 operational control point。

## 25. 本章真正要带走的判断框架

以后看到一个 data format 或 service API，可以按下面这些问题检查：

1. 这份 data 会不会长期保存？如果会，未来版本怎么读旧数据？
2. producer 和 consumer 会不会独立部署？如果会，old/new versions 如何共存？
3. old reader 遇到 unknown fields 时会忽略、保留，还是报错？
4. new reader 读 old data 缺字段时有没有 default value？
5. schema 是随数据存储、通过 version 查 registry，还是连接时协商？
6. field identity 靠 field name、field tag，还是 position？这些标识能不能安全修改？
7. 这条 message/request 如果 timeout 后 retry，会不会重复产生 side effect？
8. 这个 API 是面向 public clients，还是 internal services？需要优先考虑可读性、生态、性能还是 schema safety？
9. 这套系统是同步 RPC、durable workflow、message broker，还是 actor runtime？它们的 failure model 是否被接口设计显式考虑？

一句话总结：**Chapter 5 讲的是系统演化时的数据契约。encoding 把数据变成 bytes，schema 说明 bytes 的含义，compatibility 允许新旧代码共存，而 dataflow pattern 决定这些契约在 database、service、workflow、message broker 和 actor 之间如何发挥作用。**
