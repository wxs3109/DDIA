---
title: "1. 数据系统架构中的权衡：学习总结"
weight: 102
breadcrumbs: false
---

# Chapter 1 学习总结：数据系统架构中的权衡

本章的核心不是某个具体数据库或云产品，而是一套判断框架：data systems 没有绝对最优解，只有围绕 workload、团队能力、成本、可靠性、合规和用户权益做出的 trade-offs。

## 1. 主线

data-intensive applications 的主要难点不是 CPU 计算，而是数据管理：如何存储和处理大量数据，如何处理数据变化，如何在故障和并发下保持 consistency，如何让服务保持 available，以及如何把多个专用系统可靠组合起来。

典型 data infrastructure 组件：

| 组件 | 作用 |
|---|---|
| **database** | 持久化数据，支持后续读取 |
| **cache** | 保存昂贵操作结果，加速读取 |
| **search index** | 支持关键词搜索和复杂过滤 |
| **stream processing** | 事件或数据变化发生后立即处理 |
| **batch processing** | 定期处理累积的大量数据 |

核心判断：小规模时通用系统通常足够；规模、查询模式和组织需求复杂后，系统会逐渐 specialized。

## 2. 概念地图

- **transactional systems / OLTP**：面向用户请求，低延迟 point query，写入当前状态，通常包含 system of record。
- **analytical systems / OLAP**：面向 BI、analytics、machine learning，大范围扫描和聚合，通常属于 derived data systems。
- **cloud vs self-hosted**：成本模型、运维责任边界、控制力和 lock-in 风险不同。
- **distributed vs single-node**：分布式带来 fault tolerance、scalability、latency 优势，也带来网络故障、一致性和 observability 成本。
- **law / ethics / society**：privacy regulation、right to be forgotten、data minimization 会反过来塑造系统架构。

## 3. Backend 与 Stateless 服务

本书主要关注 **backend development** 和 **data infrastructure**。

- **frontend**：浏览器或移动端代码，主要处理单个用户交互。
- **backend**：处理所有用户请求，通过 HTTP 或 WebSocket 暴露服务，读写数据库，并集成 cache、message queue 等系统。
- **stateless**：backend 应用代码通常不在请求之间保留上下文。跨请求需要保留的信息必须写入客户端或服务器端 data infrastructure。

backend 的数据问题更复杂，因为它代表所有用户维护共享数据，同时还要处理并发、权限、可用性和 consistency。

## 4. Transactional Systems vs Analytical Systems

**transactional systems** 面向用户或业务操作，由 backend services 和数据基础设施组成，负责创建、读取和修改业务数据。

**analytical systems** 面向 business analysts、data scientists、analytics engineers，主要读取 transactional systems 的数据副本，用于 BI、报表、探索分析、machine learning 和产品决策。

| 维度 | **OLTP** | **OLAP** |
|---|---|---|
| 典型目标 | 支撑线上业务操作 | 支撑分析和决策 |
| 读取模式 | point query，按 key 读少量记录 | 扫描大量记录并聚合 |
| 写入模式 | 创建、更新、删除单条或少量记录 | batch import、ETL、event stream |
| 查询形态 | 应用代码预定义的固定查询 | 分析师可写 ad hoc query |
| 数据含义 | 当前最新状态 | 随时间变化的历史事件 |
| 主要用户 | 终端用户、后端服务 | 内部分析师、data scientists |
| 主要风险 | 延迟、并发、权限、线上稳定性 | 查询成本、数据建模、数据新鲜度 |

OLTP 系统通常不允许用户直接跑任意 SQL，因为这会带来权限风险和性能风险。OLAP 系统则通常支持自由探索，因此更适合任意 SQL、dashboard 和 visualization 工具。

有些系统使用 OLAP 风格聚合查询，但嵌入在线产品中，例如实时风控、实时推荐、用户行为分析。这类场景称为 **product analytics** 或 **real-time analytics**，代表系统包括 Pinot、Druid、ClickHouse。

## 5. Data Warehouse、Data Lake 与 Lakehouse

**data warehouse** 是为分析查询准备的独立数据库。它接收来自多个 OLTP 系统的数据副本，让分析师可以查询，而不会影响线上事务系统。

不直接查询 OLTP 数据库的原因：

- 数据分散在多个 transactional systems，形成 **data silos**；
- OLTP schema 和存储布局不适合分析；
- 分析查询昂贵，会拖慢线上服务；
- 安全和合规上可能不允许分析用户直接访问生产数据库。

典型导入过程是 **ETL**：

```text
extract -> transform -> load
```

也可能采用 **ELT**：先 load 到目标系统，再 transform。

**hybrid transactional/analytical processing**（HTAP）尝试在一个系统内同时支持 OLTP 和 OLAP。它适合同时需要低延迟单条读写和大范围分析扫描的应用，例如欺诈检测。但 HTAP 不会完全取代 data warehouse，因为大型组织通常有很多独立 transactional databases，而分析侧需要统一整合它们。

**data lake** 是集中式数据存储库，保存各种可能对分析有用的数据副本。它不强制统一文件格式或关系模型，可以存储结构化记录、Avro、Parquet、文本、图像、视频、sensor readings、feature vectors、sparse matrices 等。重要思想是 **sushi principle**：raw data is better。

**data lakehouse** 在 data lake 的文件存储之上增加 query execution engine 和 metadata layer，使其既能支持 data science，又能支持 data warehouse 风格的 SQL 查询。代表技术包括 Apache Hive、Spark SQL、Presto、Trino。

分析系统正在从周期性文件处理走向更实时的数据流：**data pipelines** 泛化 ETL，**stream processing** 秒级响应事件，**reverse ETL** 把分析结果回写到事务型系统，**data products** 将分析结果产品化，例如上线的 machine learning model。

## 6. Systems of Record 与 Derived Data Systems

**system of record** 也叫 **source of truth**，保存某类数据的 canonical version。新事实首先写入这里。如果其他系统与它不一致，以 system of record 为准。通常它的数据表示更接近 **normalized**，每个事实只表达一次。

**derived data systems** 保存由其他数据转换、聚合、索引、训练或缓存而来的结果。它们是 **redundant** 的，但可以提高读取性能或支持新的访问模式。

典型 derived data 包括：cache、search index、denormalized value、materialized view、transformed dataset、machine learning model。

关键判断：数据库产品本身不是天然的 system of record 或 derived data system。区别来自它在应用架构中的职责。真正重要的问题是：哪些数据是权威数据？哪些数据可以从权威数据重新构建？当源数据变化时，派生数据如何同步更新？

## 7. Cloud Services vs Self-Hosted

是否使用 cloud service，本质是决定哪些能力自己构建和运维，哪些能力外包给供应商。

```text
custom software + self-operated
-> self-hosted open source / commercial software
-> IaaS 上自己部署
-> managed cloud service
-> SaaS
```

Cloud 的优势：

- 对未知系统，managed service 通常更快上手；
- 不需要自己承担底层系统管理；
- 云厂商具备专业运维经验；
- 适合负载波动大的场景；
- 可以按需扩缩计算资源；
- **metered billing** 让成本与使用量更相关。

Cloud 的代价：

- 控制力下降，缺功能时只能等待供应商；
- outage 时只能等待恢复；
- 内部日志、指标、调试能力有限；
- 服务涨价、下线、API 变化会造成 vendor lock-in；
- 数据安全与隐私依赖供应商；
- 仍然需要运维，只是运维重点变化。

Self-hosted 更适合团队已有运维经验、workload 可预测、对性能或硬件有强定制需求、需要避免 vendor lock-in，或长期资源利用率高的场景。代价是团队要承担容量规划、升级、补丁、故障恢复、监控和安全维护。

## 8. Cloud-Native Architecture

**cloud-native** 系统不是简单地把传统软件放到虚拟机上，而是利用云服务的底层能力重新设计系统。

传统 self-hosted 软件通常依赖通用资源：CPU、RAM、filesystem、IP network。cloud-native 服务则会基于低层云服务构建高层能力，例如用 **object storage** 存大文件，用专用服务管理小对象或数据库块，在 object storage 之上构建 data warehouse 或 query engine。

**storage-compute separation** 是 cloud-native 架构的重要趋势：storage 和 compute 独立扩缩，本地磁盘更多被视为临时 cache，而非永久存储。好处是弹性更强、资源利用率更高；代价是更多网络传输和分布式系统问题。

cloud-native 服务通常是 **multi-tenant**：多个客户共享底层硬件和服务。它提高硬件利用率和可伸缩性，但必须防止一个客户影响其他客户的性能或安全。

## 9. Operations in the Cloud Era

传统角色包括 **database administrators**（DBA）和 **system administrators**（sysadmins）。现代组织更多采用 **DevOps** 和 **site reliability engineering**（SRE）理念，把开发和运维责任结合起来。

运维目标没有变：可靠交付服务、维持稳定生产环境、监控和诊断问题。变化的是关注点。

云时代的运维重点：自动化可重复流程、使用短生命周期的 VM 和服务、支持频繁部署、从事故中学习、保留组织知识、管理服务选择和迁移、从容量规划转向成本规划、从性能优化扩展到成本优化、提前理解 quotas。

结论：cloud 不等于 NoOps。它减少了一部分底层运维，但增加了服务集成、成本治理、observability 和供应商边界管理的工作。

## 10. Distributed Systems vs Single-Node Systems

**distributed systems** 是由多个通过网络通信的 **nodes** 组成的系统。

采用分布式系统的常见动机：多用户天然分布在不同设备、cloud services 之间需要传输数据、fault tolerance / high availability、scalability、降低全球用户 latency、弹性处理波峰波谷、使用专用硬件、满足 data residency、做 sustainability 优化。

分布式系统的代价：

- 网络请求可能失败、超时、重复或部分成功；
- 无法确定请求是否被对方处理，retry 可能不安全；
- 跨网络调用远慢于进程内函数调用；
- 大数据场景下移动数据可能比移动计算更贵；
- 更多 nodes 不一定更快；
- debugging 更困难，需要 observability 和 tracing；
- 多服务各自持有数据库时，跨服务 consistency 变成应用问题。

核心判断：如果单台机器能可靠、经济地完成任务，single-node 通常更简单、更便宜。现代单机硬件和 DuckDB、SQLite、KuzuDB 等单节点数据库让很多 workload 不必过早分布式化。

## 11. Microservices 与 Serverless

**microservices** 是 service-oriented architecture 的一种形式：复杂应用拆成多个有清晰职责的服务，每个服务暴露 API，由独立团队维护。

优点：服务可以独立部署和演进，团队间协调成本降低，每个服务可使用适合自己的硬件和技术，实现细节被 API 隐藏，每个服务通常拥有自己的 database，避免共享数据库成为隐式 API。

代价：部署、监控、日志、告警、容量调整更复杂；本地开发和测试需要运行依赖服务；API 演进困难；跨服务 consistency 难维护。

关键判断：microservices 很大程度是用技术解决组织协作问题。大公司多团队并行时有价值；小团队过早使用可能只是额外复杂度。

**serverless** 或 **function as a service**（FaaS）把更多基础设施管理交给云厂商。云厂商按请求自动分配和回收计算资源，通常按实际使用计费。

优势是更少手动管理实例、自动扩缩、适合波动负载、计费更细。限制是函数执行时间受限、运行环境受限、cold start 可能增加延迟。“serverless” 并不是真的没有服务器，只是用户不直接管理服务器。

## 12. Cloud Computing vs HPC

**high-performance computing**（HPC）或 **supercomputing** 与 cloud computing 都涉及大规模计算，但目标不同。

| 维度 | Cloud Computing | HPC / Supercomputing |
|---|---|---|
| 典型场景 | 在线服务、业务数据系统、高可用请求处理 | 科学计算、天气预报、分子动力学、偏微分方程 |
| 故障处理 | 服务应持续可用，尽量不中断用户 | 常见做法是 checkpoint 后失败重启 |
| 网络与安全 | 多租户、不信任环境，需要隔离、认证、加密 | 用户信任度较高，常用 RDMA、共享内存 |
| 地理分布 | 可跨 region | 通常 nodes 靠近 |
| 本书重点 | 持续可用的数据服务 | 仅作为对比背景 |

## 13. Data Systems、Law 与 Society

数据系统不只服务企业目标，也会影响个人和社会。工程师需要理解基本的法律和伦理约束。

关键概念：

- **GDPR**：赋予个人对数据更强的控制权；
- **CCPA**：加州消费者隐私保护法规；
- **EU AI Act**：约束 AI 对个人数据的使用；
- **right to be forgotten**：用户请求删除个人数据的权利；
- **data minimization** / **Datensparsamkeit**：只收集和保留为明确目的所需的数据。

技术挑战在于：很多数据系统依赖 append-only log、derived data、cache、index、machine learning model。删除 system of record 中的数据还不够，还要考虑它是否已经进入派生数据集。

重要判断：存储数据的成本不只是云账单，还包括泄露风险、合规风险、法律罚款、声誉损害，以及用户可能受到的现实伤害。

## 14. 核心 Trade-Offs

| 选择 | 得到什么 | 失去或承担什么 |
|---|---|---|
| OLTP 与 OLAP 分离 | 线上稳定性、分析查询性能、跨系统整合 | ETL、数据延迟、数据一致性管理 |
| Data warehouse | 统一关系模型、适合 BI 查询 | 对非结构化和 ML workflow 不够灵活 |
| Data lake | 灵活、便宜、保留 raw data | 治理、metadata、质量控制更难 |
| HTAP | 单系统支持交易和分析 | 架构复杂，未必替代统一分析平台 |
| Cloud service | 快速上线、弹性、托管运维 | 控制力下降、lock-in、调试受限 |
| Self-hosted | 可控、可定制、长期可能更便宜 | 运维负担大，需要专业能力 |
| Cloud-native | 弹性、storage-compute separation、多租户效率 | 网络依赖、复杂度、供应商边界 |
| Distributed system | 可用性、扩展性、地理低延迟 | 网络故障、一致性、observability 成本 |
| Single-node | 简单、便宜、易调试 | 扩展、容错、全球延迟能力有限 |
| Microservices | 团队独立性、服务边界清晰 | 部署、测试、API 演进和数据一致性复杂 |
| Serverless | 自动扩缩、按使用付费 | cold start、运行时限制、平台锁定 |
| Data minimization | 降低风险、符合法规原则 | 未来分析可能少一些历史数据 |

## 15. 关键术语速查

| Term | 简要理解 |
|---|---|
| **data-intensive** | 主要难点在数据管理的应用 |
| **compute-intensive** | 主要难点在大规模计算的系统 |
| **data infrastructure** | database、cache、queue、index、processing system 等基础设施 |
| **OLTP** | 面向低延迟事务操作的系统 |
| **OLAP** | 面向分析扫描和聚合的系统 |
| **point query** | 通过 key 查询少量记录 |
| **ETL / ELT** | 数据抽取、转换、加载流程 |
| **data warehouse** | 面向分析查询的独立数据库 |
| **data lake** | 保存多种原始数据的集中式存储库 |
| **data lakehouse** | 在 data lake 上增加查询和元数据能力的架构 |
| **HTAP** | 同时支持 transactional 和 analytical workload 的系统 |
| **system of record** | 权威数据源，source of truth |
| **derived data system** | 由其他数据派生出的系统 |
| **cloud-native** | 为云服务能力重新设计的架构 |
| **object storage** | 面向大对象文件的云存储服务 |
| **storage-compute separation** | 存储和计算独立扩缩的架构 |
| **multi-tenant** | 多客户共享底层服务和硬件 |
| **DevOps / SRE** | 将开发、运维、可靠性责任结合的实践 |
| **distributed system** | 多个 node 通过网络协作的系统 |
| **observability** | 通过指标、日志、trace 理解系统行为的能力 |
| **tracing** | 跟踪跨服务请求路径和耗时的技术 |
| **microservices** | 由多个独立服务组成的应用架构 |
| **serverless / FaaS** | 云厂商按请求管理代码执行资源的模型 |
| **data minimization** | 只收集和保留必要数据的原则 |

## 16. 复习问题

1. 为什么 OLTP 数据库通常不适合直接给分析师跑任意查询？
2. data warehouse 和 data lake 的根本区别是什么？
3. HTAP 适合什么场景？为什么它不会完全取代 data warehouse？
4. system of record 和 derived data system 的区别为什么重要？
5. cloud service 的核心 trade-off 是什么？
6. storage-compute separation 为什么适合 cloud-native 系统？它引入了什么新问题？
7. 为什么“更多机器”不一定意味着“更快”？
8. microservices 解决的主要是技术问题还是组织问题？
9. serverless 的优势和限制分别是什么？
10. GDPR 的 right to be forgotten 为什么会对 append-only log、cache、index 和 machine learning model 构成挑战？

## 17. 后续阅读时的检查框架

读后续章节时，可以持续问三类问题：

1. **workload 问题**：这个系统主要优化 point query、scan、aggregation、stream，还是 batch？
2. **数据来源问题**：这里的数据是 system of record，还是 derived data？如果源数据变了，它如何更新？
3. **权衡问题**：这个设计在 latency、throughput、cost、operability、consistency、compliance 中优先保护了什么，又牺牲了什么？

本章最重要的收获是：架构判断不是从工具名开始，而是从 workload、数据流、组织边界和风险边界开始。
