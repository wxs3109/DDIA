# 第 2 章知识梳理：定义非功能性需求

## 一句话主线

第二章回答的是：一个数据系统除了“能做什么”之外，还必须怎样才算“做得好”。核心维度是四个：performance、reliability、scalability、maintainability。

## 1. 本章在讲什么

功能性需求回答“系统要提供哪些功能”。

非功能性需求回答“系统要以什么质量提供这些功能”。本章重点讨论四类非功能性需求：

- performance：系统是否足够快。
- reliability：系统出错时是否仍能持续正确工作。
- scalability：负载增长时，系统是否能通过增加资源维持性能。
- maintainability：系统是否容易理解、运维和演进。

这四者不是彼此独立的标签，而是系统设计中的长期约束。后续章节讨论数据库、日志、复制、分片、流处理时，都会反复回到这些目标。

## 2. 案例主线：社交网络首页时间线

本章先用社交网络的 home timeline 作为案例，把抽象概念落到具体系统里。

### 2.1 最直观的做法

用户发帖后，读取某个用户首页时，系统再去查询其关注对象最近的帖子并排序返回。

这个方案实现简单，但读取成本高。如果客户端持续 polling，系统会承受巨量重复查询。

### 2.2 优化思路

系统可以把帖子“推”给追随者的时间线缓存，而不是每次读时临时算出结果。

这里引出几个关键术语：

- fan-out：一个请求触发多个下游操作，请求数量被放大的现象。
- materialization：预先计算并持续更新结果，而不是读取时现算。
- materialized view：被预先维护好的查询结果。

### 2.3 核心权衡

时间线物化提升了读性能，但把成本转移到了写路径。大多数工程优化都不是“免费提速”，而是把成本从一端挪到另一端。

### 2.4 案例要说明的本质

同一个系统往往同时面对：

- 读写路径的权衡。
- 普通用户与极端用户的不均匀分布。
- 平均情况与尾部情况的差异。
- 功能正确与系统承压能力的同时要求。

## 3. Performance：如何描述“快”

### 3.1 两个基本指标

- throughput：单位时间内可处理的请求数或数据量。
- response time：用户感知到一次请求完成所需的总时间。

两者通常相互关联。吞吐量逼近系统上限时，queueing 会让响应时间急剧变差。

### 3.2 延迟相关概念

- response time：客户端看到的总耗时。
- service time：服务端主动处理请求的时间。
- queueing delay：请求等待资源的时间。
- latency：请求未被主动处理、处于等待或传播中的时间。
- network latency：请求与响应在网络中传播的时间。

本章强调：系统慢，很多时候不是“算得慢”，而是“等得久”。

### 3.3 为什么不能只看平均值

平均值容易掩盖坏体验。真正决定用户感受的，往往是 percentiles：

- median 或 p50：一半请求快于它，一半慢于它。
- p95、p99、p999：帮助观察慢请求和尾部风险。
- tail latency：高百分位延迟，直接影响实际体验。

当一个用户请求依赖多个后端调用时，tail-latency amplification 会让整体体验显著恶化。只要某个子请求变慢，整个终端请求都可能被拖慢。

### 3.4 过载时的典型失败模式

系统接近极限时，会出现：

- queueing 上升。
- 超时重试增多。
- retry storm。
- metastable failure。

常见保护手段包括：

- exponential backoff
- circuit breaker
- token bucket
- load shedding
- backpressure

### 3.5 监控里的落地方式

percentiles 经常被写进 service level objective 和 service level agreement。也就是说，性能不是抽象感觉，而是要被量化、被承诺、被监控的。

## 4. Reliability：如何描述“稳”

### 4.1 reliability 不是“永不出错”

可靠性真正的含义是：即使出现问题，系统仍能持续提供正确服务。

书中区分了两个概念：

- fault：某个 component 出了问题。
- failure：整个 system 无法继续提供所需服务。

也就是说，局部 fault 不一定要升级成全局 failure。

### 4.2 fault-tolerant 的含义

如果系统能在部分组件损坏时继续服务，它就是 fault-tolerant。反之，不能失去的关键部件就是 single point of failure。

这里的关键不是“绝不坏”，而是“坏了以后系统怎么继续工作”。

### 4.3 故障的来源

本章把故障来源拆成三类：

- 硬件故障：磁盘、内存、机器、网络设备损坏。
- 软件故障：隐藏 bug、边缘条件、异常交互、资源耗尽。
- 人为错误：配置失误、错误发布、错误操作。

一个非常重要的判断是：软件故障往往比硬件故障更难，因为它们经常具有关联性，可能一出问题就同时影响很多节点。

### 4.4 对可靠性的正确态度

提升可靠性不只是买更贵的硬件，还包括：

- 冗余
- 自动故障切换
- fault injection
- chaos engineering
- 渐进发布与快速回滚
- property-based testing
- blameless postmortem

本章特别强调：组织是否能从事故中学习，也是 reliability 的一部分。

## 5. Scalability：如何描述“能长大”

### 5.1 scalability 不是一个绝对标签

“某系统可伸缩”这句话本身信息量不够。更好的问题是：

- 在什么样的负载下？
- 哪一类资源先成为瓶颈？
- 增加多少资源后，性能能改善多少？
- 成本是否合理？

scalability 永远要和具体 workload 一起讨论。

### 5.2 描述负载时要看什么

常见描述方式包括：

- 每秒请求数
- 每天新增数据量
- 同时在线用户数
- 读写比
- 缓存命中率
- 单用户数据规模

系统是否扛得住增长，取决于增长的是哪一个维度，而不是一个模糊的“变大”。

### 5.3 三类经典架构

- shared-memory architecture：多线程/多进程共享一台机器内存。
- shared-disk architecture：多台机器共享同一组磁盘。
- shared-nothing architecture：每个节点拥有自己的 CPU、RAM、磁盘，通过网络协作。

其中 shared-nothing architecture 是现代大规模分布式系统最常见的方向，因为它更适合 scaling out。

### 5.4 本章给出的原则

- 追求独立的小组件。
- 优先明确负载特征，再谈扩展方案。
- 不存在 silver bullet。
- 扩展能力必须和成本一起评估。

## 6. Maintainability：如何描述“能长期活下去”

本章把 maintainability 拆成三个子目标。

### 6.1 可运维性

系统应该帮助运维人员完成工作，而不是把复杂性全压给人。良好的运维体验通常依赖：

- 清晰监控
- 自动化
- 回滚机制
- 可观测性
- 渐进发布

但自动化不是终点。自动化越深，越需要高水平团队处理边缘情况。

### 6.2 简单性

复杂系统会拖慢理解、修改、排障和协作。本章把复杂性分成：

- essential complexity：问题本身不可消除的复杂性。
- accidental complexity：实现方式、工具限制带来的额外复杂性。

管理复杂度最重要的手段是 abstraction。好的抽象会隐藏细节、减少重复、降低认知负担。

### 6.3 可演化性

需求、组织和业务都会持续变化。一个系统是否容易演进，取决于：

- 是否松耦合。
- 是否具备清晰边界。
- 是否能局部修改而不牵动全局。
- 是否建立在良好抽象之上。

本章用 evolvability 来描述这种“适应变化的能力”。

## 7. 四个主题之间的关系

这四个目标不能割裂理解：

- performance 不好，系统即使功能正确，用户也无法接受。
- reliability 不够，性能再高也没有意义。
- scalability 不足，系统在增长后会失去原有 performance 和 reliability。
- maintainability 差，系统即使短期可用，长期也会越来越脆弱。

可以把它们理解成系统设计的四个长期质量轴，而不是四个独立 checklist。

## 8. 高频术语清单

### 性能相关

- throughput
- response time
- service time
- queueing delay
- latency
- network latency
- head-of-line blocking
- distribution
- outliers
- jitter
- mean
- arithmetic mean
- percentiles
- median
- p50 / p95 / p99 / p999
- tail latency
- tail-latency amplification
- service level objective
- service level agreement

### 可靠性相关

- reliability
- fault
- failure
- fault-tolerant
- single point of failure
- exactly-once semantics
- fault injection
- chaos engineering
- availability zone
- rolling upgrade
- blameless postmortem

### 可伸缩性相关

- scalability
- scalable
- linear scalability
- scaling up
- scaling out
- shared-memory architecture
- shared-disk architecture
- shared-nothing architecture
- silver bullet

### 可维护性相关

- maintainability
- abstraction
- essential complexity
- accidental complexity
- design patterns
- domain-driven design
- agile
- evolvability
- big ball of mud
- legacy

## 9. 复习时最值得记住的 10 个判断

1. 非功能性需求决定的是系统质量，不是附属要求。
2. 系统慢，往往是 queueing 导致的，不只是计算慢。
3. 平均值不足以描述用户体验，percentiles 更关键。
4. 高并发系统最怕尾部延迟放大。
5. reliability 不是不出错，而是出错时仍能继续服务。
6. 局部 fault 不应轻易升级成全局 failure。
7. scalability 必须和具体 workload 绑定讨论。
8. 没有通用 silver bullet，架构必须贴合应用特征。
9. maintainability 是长期成本问题，不是“代码风格问题”。
10. 好系统不是只在今天能跑，而是三年后还能被理解、扩展和修复。

## 10. 可直接拿去复习的思考题

1. 为什么平均响应时间不能代表用户真实体验？
2. 什么情况下应该关注 p99，而不是只看 p50？
3. fault 和 failure 的区别是什么？
4. 为什么软件故障通常比硬件故障更难处理？
5. 什么叫 scalable？为什么它不能脱离 workload 单独讨论？
6. shared-nothing architecture 为什么适合大规模系统？
7. maintainability 为什么会直接影响未来的 reliability 和 delivery speed？

## 11. 最终归纳

第二章并不是在讲某一种具体数据库或某一种架构，而是在建立一套判断系统优劣的语言。后面全书的很多技术细节，本质上都可以回到这四个问题来评价：它是否提升了 performance，是否增强了 reliability，是否支持 scalability，是否改善了 maintainability。
