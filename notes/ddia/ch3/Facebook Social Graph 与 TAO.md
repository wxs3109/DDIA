# Facebook Social Graph 与 TAO

这份 note 是 [图数据模型](图数据模型.md) 的补充，专门讲 Facebook 的 social graph 和 TAO。它不是 DDIA 第 3 章正文的完整展开，而是围绕一个问题：**如果 Facebook 的 social graph 底层可以用 relational database 存 object / association，那么它如何避免在线查询时陷入不确定数量的 join / recursive traversal？**

简短答案是：Facebook 没有让 MySQL 直接承担任意 graph query。它把 social graph 的常见访问模式抽象成 `object` 和 `association` API，在 MySQL 之上构建 TAO 作为 distributed graph store / caching layer，把在线请求限制为低延迟、已知形状、bounded 的 association lookup。更复杂的推荐、搜索、ranking、feed 生成则由上层服务、缓存、预计算和 offline / nearline pipeline 共同完成。

## 1. Facebook 的问题不是“能不能存 graph”

用 relational database 存 graph 并不难。你可以用一张 `objects` 表存 user、post、comment、photo、page、group、event；再用一张 `associations` 表存 object 之间的关系：

```sql
CREATE TABLE objects (
    id bigint PRIMARY KEY,
    type text,
    attributes jsonb
);

CREATE TABLE associations (
    source_id bigint REFERENCES objects(id),
    assoc_type text,
    target_id bigint REFERENCES objects(id),
    created_at timestamptz,
    attributes jsonb,
    PRIMARY KEY (source_id, assoc_type, target_id)
);

CREATE INDEX associations_by_target
    ON associations (target_id, assoc_type, source_id);
```

这已经很像本章的 `property graph`：

- `objects` 类似 `vertex`。
- `associations` 类似 `edge`。
- `assoc_type` 类似 edge `label`。
- `attributes` 类似 properties。

真正的问题是 **online query pattern**。如果产品请求经常要求“沿着多种 relationship 走不确定数量的跳”，直接用 SQL 会变成很多 join，甚至 recursive CTE。比如：

```text
从 viewer 出发：friend -> group membership -> post -> comments -> commenter -> mutual friends
```

这类查询如果让 MySQL query planner 临时处理，会遇到几个问题：

1. join 数量可能不固定。
2. 中间结果可能爆炸，例如一个 celebrity / popular page / viral post 有巨大 fanout。
3. 每个用户的 graph neighborhood 差异很大，查询成本难以预测。
4. Facebook 的读流量极高，单靠数据库执行复杂 join 很难稳定维持低延迟。

所以 Facebook 的核心思路不是“让 relational database 自动做 graph traversal”，而是：**把 graph access 做成受控的 service API，并让缓存和数据分布围绕这些 API 优化。**

## 2. TAO 的核心抽象：object 和 association

TAO 论文把 Facebook 的 social graph 抽象成两类数据：`object` 和 `association` [1]。

`object` 是有 ID 和属性的实体，例如：

- user
- page
- post
- comment
- photo
- event
- group

`association` 是两个 object 之间的有类型、有方向的关系，例如：

- user likes post
- user comments on post
- user is member of group
- user is friend with user
- photo is tagged with user
- post is authored by user

对应到本章术语：

| TAO | graph model |
| --- | --- |
| `object` | `vertex` |
| `association` | `edge` |
| association type | edge `label` |
| object fields | vertex `properties` |
| association fields | edge `properties` |

例如：

```text
(user:100 Wenbo) -[:FRIEND]-> (user:200 Alice)
(user:200 Alice) -[:LIKES]-> (post:9001)
(post:9001) -[:AUTHORED_BY]-> (user:300 Bob)
(user:100 Wenbo) -[:MEMBER_OF]-> (group:42 DDIA)
(post:9001) -[:POSTED_IN]-> (group:42 DDIA)
```

TAO 的重点不是提供类似 Cypher 的任意 pattern matching，而是提供 object / association 的基本操作，例如：

- 读取一个 object 的字段。
- 更新一个 object。
- 创建或删除 association。
- 查询某个 object 的某类 outgoing association list。
- 查询两个 object 之间是否存在某类 association。
- 查询 association count。

这些操作非常贴近 Facebook 产品的高频访问模式。

## 3. TAO 如何避免“不确定 join”

TAO 避免不确定 join 的关键是：**不把任意 traversal 当作在线数据库查询接口暴露。**

也就是说，应用不会向 TAO 发一个类似这样的请求：

```text
从 Wenbo 出发，任意走 5 跳，找到所有满足复杂 predicate 的节点。
```

TAO 更像是支持一组 bounded graph access primitives：

```text
get object(100)
get associations(source=100, type=FRIEND, limit=500)
get associations(source=42, type=POSTED_IN, limit=50)
association exists(source=100, type=LIKES, target=9001)
association count(source=9001, type=COMMENT)
```

复杂产品功能会被拆成多个已知形状的 lookup。例如一个 feed / recommendation 请求可以大致分解成：

1. 查 viewer 的 friends、followed pages、groups。
2. 查这些对象最近产生的 posts / activities。
3. 查 posts 的 author、like count、comment count、privacy metadata。
4. 交给 ranking service 排序。
5. 对结果再做 privacy check、hydration、dedup。

这不是一个数据库里的“大查询”，而是多个服务调用和缓存 lookup 组成的 pipeline。这样做牺牲了任意 declarative graph query 的灵活性，但换来了低延迟、可预测性和可缓存性。

> [!NOTE] Wenbo 注
> 可以把 TAO 理解为：“我们承认数据是 graph，但在线服务不要随便跑 graph query。在线服务只做少数高频、可缓存、可限流的 graph access；复杂路径和 ranking 交给专门系统处理。”这和本章的 Cypher / SPARQL 思路不同：Cypher / SPARQL 更强调声明式表达 graph pattern，TAO 更强调工程上可控的 object / association API。

## 4. 为什么 association list 是一等公民

在 social graph 里，最常见的访问不是任意 SQL join，而是“给定一个 object，取它某种类型的关联列表”。例如：

- 某个 user 的 friends。
- 某个 post 的 comments。
- 某个 post 的 likers。
- 某个 group 的 members。
- 某个 user 加入的 groups。
- 某个 photo tagged 的 users。

这些都可以看成：

```text
source object + association type -> ordered target object list
```

TAO 因此围绕 association list 优化。很多 association list 可以缓存；一些 list 需要排序、分页、计数；一些 list 的 fanout 很大，需要特殊处理。与其让数据库每次通过 join 临时拼路径，不如把这些 association list 做成系统的一等访问对象。

这和 relational join table 的区别很微妙：

- relational join table 是通用表示。
- TAO association list 是产品访问模式驱动的服务抽象。

底层可能仍有类似 table 的存储，但上层 API 已经变成 graph-oriented access。

## 5. 底层为什么还能用 MySQL

TAO 论文说明，Facebook social graph 的 durable storage 建在 sharded MySQL 之上 [1]。这看起来有点反直觉：既然是 graph，为什么还用 MySQL？

原因是 MySQL 在这里主要承担的是可靠持久化和局部查询，不是直接执行任意 graph traversal。TAO 层负责：

- 缓存 hot objects 和 hot association lists。
- 把请求 route 到正确 shard。
- 处理 read-after-write、cache invalidation、replication。
- 给应用提供 graph-style API。

粗略结构是：

```text
Application services
    -> TAO API
    -> TAO cache / routing / consistency layer
    -> sharded MySQL persistent storage
```

MySQL 的角色更像 storage engine / source of truth，而不是 graph query engine。

这个设计也符合大型互联网系统的常见规律：底层存储不一定暴露最终的数据模型；真正面向业务访问模式的抽象常常在服务层、缓存层和派生数据层完成。

## 6. cache 为什么如此关键

Facebook 的 social graph 是 read-heavy workload。用户刷 feed、打开 profile、看 comments、看 likes、检查权限，都会产生大量 graph reads。TAO 因此必须高度依赖 cache。

Facebook 另有论文专门讲它们如何大规模使用 memcache [2]。虽然 memcache 论文不是 TAO 论文，但它说明了 Facebook 的整体工程背景：在海量读请求下，cache 不是附属优化，而是系统架构的核心部分。

TAO 里的 cache 需要处理几个问题：

1. hot object / hot association list 会被频繁读取。
2. 写入后要让相关 cache 失效或更新。
3. 跨 data center replication 会带来一致性延迟。
4. 某些对象的 fanout 极端大，例如明星用户、热门 post、热门 page。

因此 TAO 不是简单的 `SELECT ... FROM associations` 包装。它是围绕 Facebook graph workload 建的缓存和分布式访问系统。

## 7. 那多跳查询怎么办

TAO 适合低延迟 object / association lookup，但 Facebook 产品当然也需要多跳逻辑，例如：

- People You May Know。
- Graph Search。
- News Feed ranking。
- Ads targeting。
- Page / group / event recommendation。

这些通常不会简单地作为一个在线递归 SQL 查询执行。更常见的处理方式是：

1. **bounded online traversal**：在线请求只走少数几跳，并且每一步 limit fanout。
2. **precomputation**：提前计算候选集，例如 mutual friends、可能认识的人、热门内容。
3. **ranking service**：把 graph features 作为排序特征，而不是把所有逻辑塞进数据库查询。
4. **search index**：把适合搜索的 graph 信息放进专门的 index。
5. **offline / nearline pipeline**：用批处理或流处理更新推荐候选、计数、摘要和索引。

Facebook 曾经公开过 `Unicorn`，一个用于搜索 social graph 的系统 [3]。它服务的问题就更接近“在 social graph 上做搜索”，而不是 TAO 这种低延迟 object / association store。这个分工很重要：

- TAO：服务高频、低延迟、受控形状的 graph reads / writes。
- Unicorn / search / ranking systems：服务更复杂的 graph search 和 retrieval。
- Feed / recommendation pipelines：服务预计算、排序、个性化。

所以 Facebook 的答案不是“一个数据库解决所有 graph 问题”，而是把 social graph 拆成多个系统职责。

## 8. 和本章 `property graph` 的关系

TAO 和本章的 `property graph` 很像，但不是同一个层次的东西。

相似点：

- 都把数据看成 object / vertex 和 association / edge。
- 都支持多种 edge type。
- 都强调从某个 vertex 出发找邻接关系。

不同点：

- `property graph database` 通常会提供 query language，例如 Cypher。
- TAO 更像 production social graph storage API，不提供任意 declarative graph pattern matching。
- `property graph` 是数据模型；TAO 是围绕 Facebook workload 建的 distributed system。
- 本章更关心数据模型和查询语言表达能力；TAO 更关心低延迟、高吞吐、缓存、一致性和跨数据中心部署。

可以总结成：

```text
DDIA graph model:
    How should we model relationship-rich data?

Cypher / SPARQL / Datalog:
    How should we express graph queries?

Facebook TAO:
    How do we serve a massive social graph workload in production?
```

## 9. 一个具体请求如何走

假设 Facebook 要渲染某条 post，页面上需要显示：

- post 内容。
- author 信息。
- viewer 是否 liked。
- like count。
- 前几条 comments。
- viewer 是否有权限看到。

用 graph 视角看，这涉及：

```text
(post) -[:AUTHORED_BY]-> (user)
(viewer) -[:LIKES]-> (post)?
(post) -[:HAS_COMMENT]-> (comment)
(comment) -[:AUTHORED_BY]-> (user)
(viewer) -[:MEMBER_OF]-> (group)?
(post) -[:POSTED_IN]-> (group)?
```

如果全塞进一条 SQL，可能是一堆 join。TAO-style 的系统更可能做成几类 lookup：

```text
get object(post_id)
get association(post_id, AUTHORED_BY)
association exists(viewer_id, LIKES, post_id)
association count(post_id, LIKED_BY)
get associations(post_id, HAS_COMMENT, limit=20)
get objects(comment_author_ids)
privacy service checks viewer against post privacy metadata
```

每一步都小、明确、可缓存、可限流。整体功能仍然复杂，但复杂性从数据库 join planner 转移到了服务编排、缓存、ranking 和产品逻辑里。

## 10. takeaway

Facebook 的 social graph 说明了一件很重要的事：**graph model 和 graph database 不是一回事。**

Facebook 的数据显然是 graph-shaped：用户、内容、地点、事件、群组之间有大量关系。但它没有简单选择一个通用 graph database 来处理所有查询，而是在 MySQL 之上构建 TAO，把高频 graph access 抽象成 object / association API。

这种设计绕开了 relational database 在不确定路径 traversal 上的弱点：不让在线请求自由发起任意多跳 join，而是把访问限制为受控的 association lookup，并通过 cache、分片、复制、预计算、搜索索引和 ranking pipeline 来支撑复杂产品功能。

对 DDIA 第 3 章来说，Facebook 是一个很好的提醒：选择 data model 不只是选择“怎么存”，也是选择“允许什么查询以什么成本发生”。

## 参考文献

[1] Nathan Bronson, Zach Amsden, George Cabrera, Prasad Chakka, Peter Dimov, Hui Ding, Jack Ferris, Anthony Giardullo, Sachin Kulkarni, Harry Li, Mark Marchukov, Dmitri Petrov, Lovro Puzar, Yee Jiun Song, and Venkat Venkataramani. [TAO: Facebook's Distributed Data Store for the Social Graph](https://www.usenix.org/conference/atc13/technical-sessions/presentation/bronson). USENIX Annual Technical Conference, 2013.

[2] Rajesh Nishtala, Hans Fugal, Steven Grimm, Marc Kwiatkowski, Herman Lee, Harry C. Li, Ryan McElroy, Mike Paleczny, Daniel Peek, Paul Saab, David Stafford, Tony Tung, and Venkateshwaran Venkataramani. [Scaling Memcache at Facebook](https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala). NSDI, 2013.

[3] Michael Curtiss, Iain Becker, Tudor Bosman, Sergey Doroshenko, Lucian Grijincu, Tom Jackson, Sandhya Kunnatur, Soren Lassen, Philip Pronin, Sriram Sankar, Guillaume Shen, Gintaras Woss, Chusheng Yang, and Ning Zhang. [Unicorn: A System for Searching the Social Graph](https://www.vldb.org/pvldb/vol6/p1150-curtiss.pdf). Proceedings of the VLDB Endowment, 2013.

[4] Dhruba Borthakur et al. [Apache Hadoop Goes Realtime at Facebook](https://www.usenix.org/conference/nsdi11/apache-hadoop-goes-realtime-facebook). NSDI, 2011.

[5] Doug Beaver, Sanjeev Kumar, Harry C. Li, Jason Sobel, and Peter Vajgel. [Finding a Needle in Haystack: Facebook's Photo Storage](https://www.usenix.org/legacy/event/osdi10/tech/full_papers/Beaver.pdf). OSDI, 2010.
