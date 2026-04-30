# DDIA 术语翻译约定

这个文件合并了 `books/ddia/glossary.md` 中已有术语和第 5 章新增术语。每行给出英文术语和中文意思；分组表示正文翻译时的处理策略。

原则：如果中文读起来像硬造词、会遮蔽英文社区里的常用说法，或容易和相近概念混淆，正文保留英文，中文只作解释或索引。如果中文自然、稳定、不会损失辨识度，则正文可直接用中文。

## 正文只保留英文：专有名词、缩写、格式、协议、产品

| English | 中文意思 |
|---|---|
| ActiveMQ | 开源消息代理 |
| Airflow | 工作流/数据编排框架 |
| Akka | actor 与分布式系统框架 |
| Amazon Kinesis | AWS 流数据服务 |
| Apache Kafka | 分布式事件流/日志系统 |
| Apache Thrift | 跨语言服务定义与二进制编码框架 |
| Apicurio Registry | 模式注册表产品 |
| API | 应用程序接口 |
| ASN.1 | 抽象语法标记一，模式定义语言 |
| AsyncAPI | 面向异步消息 API 的描述规范 |
| Avro | Apache Avro，二进制编码格式 |
| Avro IDL | Avro 接口定义语言 |
| Azure Service Bus | Azure 托管消息服务 |
| BER | 基本编码规则 |
| BISON | 一种二进制 JSON 编码格式 |
| BJSON | 一种二进制 JSON 编码格式 |
| BPMN | 业务流程模型和标记法 |
| BPEL | 业务流程执行语言 |
| BSON | Binary JSON，二进制 JSON 格式 |
| Camunda | 工作流/BPMN 引擎 |
| CAP theorem | CAP 定理 |
| Cap'n Proto | 零拷贝序列化格式 |
| CBOR | Concise Binary Object Representation，紧凑二进制对象表示 |
| Confluent Schema Registry | Confluent 的模式注册表 |
| CORBA | 公共对象请求代理架构 |
| CSV | 逗号分隔值格式 |
| Dagster | 数据编排框架 |
| DCOM | 分布式组件对象模型 |
| DER | 可分辨编码规则 |
| DNS | 域名系统 |
| EJB | Enterprise JavaBeans |
| Enterprise JavaBeans | Java 企业组件模型 |
| Erlang/OTP | Erlang 的并发与分布式系统平台 |
| Espresso | LinkedIn 的分布式文档存储 |
| ETL | Extract-Transform-Load，提取、转换、加载 |
| Fast Infoset | XML 的二进制编码格式 |
| FastAPI | Python Web 服务框架 |
| FlatBuffers | 零拷贝序列化格式 |
| Google Cloud Pub/Sub | Google Cloud 托管消息服务 |
| gRPC | 基于 Protocol Buffers 的 RPC 框架 |
| Hadoop | 分布式存储与批处理生态 |
| HAProxy | 软件负载均衡器 |
| Hessian | 一种二进制 Web 服务协议/编码格式 |
| HornetQ | 开源消息代理 |
| HTTP | 超文本传输协议 |
| Istio | 服务网格实现 |
| Java RMI | Java 远程方法调用 |
| JDBC | Java 数据库连接 API |
| JSON | JavaScript Object Notation |
| JSON Schema | JSON 模式规范 |
| Kubernetes | 容器编排平台 |
| Linkerd | 服务网格实现 |
| MessagePack | 一种二进制 JSON 编码格式 |
| NATS | 开源消息系统 |
| Nginx | Web 服务器与软件负载均衡器 |
| OAuth | 授权协议 |
| ODBC | 开放数据库连接 API |
| OLAP | Online Analytic Processing，在线分析处理 |
| OLTP | Online Transaction Processing，在线事务处理 |
| OpenAPI | Web API 描述规范，原 Swagger |
| Orkes | 工作流编排平台 |
| Orleans | 分布式 actor 框架 |
| Parquet | 面向分析的列式文件格式 |
| Prefect | 数据/工作流编排框架 |
| Protocol Buffers | Google 的二进制编码格式 |
| protobuf | Protocol Buffers 的常用简称 |
| RabbitMQ | 开源消息代理 |
| Restate | 持久化执行框架 |
| REST | 表述性状态转移 |
| RESTful | 符合 REST 风格的 |
| RPC | Remote Procedure Call，远程过程调用 |
| SDK | 软件开发工具包 |
| Smile | 一种二进制 JSON 编码格式 |
| SOAP | 简单对象访问协议 |
| Spring Boot | Java 服务框架 |
| SSL/TLS | 安全传输协议 |
| Swagger | OpenAPI 的旧称及相关工具生态 |
| Temporal | 持久化执行/工作流框架 |
| TIBCO | 商业消息中间件厂商/产品生态 |
| UBJSON | Universal Binary JSON |
| URI | 统一资源标识符 |
| URL | 统一资源定位符 |
| WAL | write-ahead log，预写日志 |
| WBXML | WAP Binary XML |
| Web service | 基于 Web/HTTP 的服务接口 |
| WebSphere | IBM 企业中间件产品 |
| webMethods | 企业集成与消息中间件产品 |
| WS-* | SOAP 相关 Web 服务规范族 |
| X.509 | 公钥证书标准 |
| XML | 可扩展标记语言 |
| XML Schema | XML 模式规范 |
| YAML | 人类可读的数据序列化格式 |

## 正文只保留英文：中文译名别扭或容易误导

| English | 中文意思 |
|---|---|
| actor | actor 模型中的并发实体 |
| Actor model | Actor 模型 |
| backpressure | 接收方跟不上时强制发送方降速；也叫 flow control |
| fan-out | 一个上游请求放大成多个下游操作 |
| fault | 组件层面的故障或异常 |
| failure | 系统层面无法提供服务 |
| fault tolerance | 系统容忍 fault 而不演变成 failure 的能力 |
| fault-tolerant | 出现 fault 后仍能继续工作的 |
| flow control | 流量控制；这里常等同 backpressure |
| hot standby | 热备副本 |
| marshalling | 把内存对象整理成可传输/可存储表示；本章作为 encoding 近义词 |
| message-oriented middleware | 面向消息的中间件 |
| queueing delay | 请求因资源忙碌而等待的时间 |
| response time | 用户发出请求到收到响应的总时间 |
| retry storm | 超时重试导致负载继续恶化的恶性循环 |
| tail latency | 延迟分布尾部的高百分位表现 |
| unmarshalling | marshalling 的反向过程；本章作为 decoding 近义词 |

## 正文可以用中文：中文自然、稳定、容易理解

| English | 中文意思 |
|---|---|
| API versioning | API 版本控制 |
| arbitrary code execution | 任意代码执行 |
| asynchronous | 异步 |
| atomic | 原子；并发中指像单一时刻生效，事务中指要么全提交要么全回滚 |
| backward compatibility | 向后兼容性；新代码能读旧数据 |
| batch process | 批处理 |
| binary encoding | 二进制编码 |
| bounded | 有界 |
| byte sequence | 字节序列 |
| Byzantine fault | 拜占庭故障 |
| cache | 缓存 |
| causality | 因果关系 |
| client | 客户端 |
| closed content model | 封闭内容模型 |
| compaction | 压缩/合并；具体按存储语境处理 |
| consensus | 共识 |
| consumer | 消费者 |
| data warehouse | 数据仓库 |
| declarative | 声明式 |
| decoding | 解码 |
| default value | 默认值 |
| denormalize | 反规范化 |
| derived data | 派生数据 |
| deserialization | 反序列化 |
| deterministic | 确定性 |
| distributed | 分布式 |
| distributed actor framework | 分布式 actor 框架 |
| durable | 持久性 |
| durable execution | 持久化执行 |
| dynamically generated schema | 动态生成的模式 |
| encoding | 编码 |
| endpoint | 端点 |
| event | 事件 |
| event broker | 事件代理 |
| event log | 事件日志 |
| event sourcing | 事件溯源 |
| event-driven architecture | 事件驱动架构 |
| exactly-once semantics | 恰好一次语义 |
| executor | 执行器 |
| failover | 故障切换 |
| field tag | 字段标签 |
| follower | 追随者；也称 secondary、read replica 或 hot standby |
| forward compatibility | 向前兼容性；旧代码能读新数据 |
| full-text search | 全文检索 |
| graph | 图 |
| hardware load balancer | 硬件负载均衡器 |
| hash | 哈希 |
| idempotency | 幂等性 |
| idempotent | 幂等 |
| index | 索引 |
| interface definition language | 接口定义语言 |
| isolation | 隔离性 |
| join | 连接 |
| language-specific format | 特定语言的格式 |
| leader | 领导者 |
| linearizable | 线性一致 |
| load balancer | 负载均衡器 |
| load balancing | 负载均衡 |
| locality | 局部性 |
| location transparency | 位置透明性 |
| lock | 锁 |
| log | 日志 |
| materialize | 物化 |
| message | 消息 |
| message broker | 消息代理 |
| message queue | 消息队列 |
| microservices | 微服务 |
| node | 节点 |
| non-deterministic behavior | 非确定性行为 |
| normalized | 规范化 |
| object container file | 对象容器文件 |
| open content model | 开放内容模型 |
| orchestrator | 编排器 |
| partitioning | 分区；在分布式数据分布语境下常与 sharding 相近 |
| percentile | 百分位 |
| primary key | 主键 |
| publish | 发布 |
| queue | 队列 |
| quorum | 法定票数 |
| reader's schema | 读取者模式 |
| rebalance | 再平衡 |
| redelivery | 重新传递 |
| repeated | repeated 修饰符；Protocol Buffers 中表示重复字段 |
| replication | 复制 |
| replication log | 复制日志 |
| rolling upgrade | 滚动升级 |
| schema | 模式 |
| schema evolution | 模式演化 |
| schema migration | 模式迁移 |
| schema registry | 模式注册表 |
| schema resolution | 模式解析 |
| schema-on-read | 读时模式 |
| secondary index | 二级索引 |
| serializable | 可串行化 |
| serialization | 序列化；本书正文优先用 encoding 避免和事务语境混淆 |
| service | 服务 |
| service discovery | 服务发现 |
| service mesh | 服务网格 |
| shared-nothing | 无共享 |
| sharding | 分片 |
| sidecar | 边车 |
| skew | 偏斜 |
| software load balancer | 软件负载均衡器 |
| split brain | 脑裂 |
| staged rollout | 阶段发布 |
| static analysis | 静态分析 |
| stored procedure | 存储过程 |
| stream process | 流处理 |
| subscriber | 订阅者 |
| synchronous | 同步 |
| system of record | 记录系统；权威数据源 |
| tag number | 标签号 |
| throughput | 吞吐量 |
| timeout | 超时 |
| topic | 主题 |
| total order | 全序 |
| transaction | 事务 |
| two-phase commit | 两阶段提交 |
| two-phase locking | 两阶段锁 |
| unbounded | 无界 |
| union type | 联合类型 |
| validation | 验证 |
| variable-length integer | 可变长度整数 |
| workflow | 工作流 |
| workflow engine | 工作流引擎 |
| writer's schema | 写入者模式 |
| zero-copy | 零拷贝 |
