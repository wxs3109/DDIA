# SQL 表数据如何映射到 B-tree

这篇 note 解释一个很容易卡住的点：SQL 里的 `table`、`row`、`column` 是逻辑模型；而数据库底层真正操作的是 `page`、`row bytes`、`B-tree key`、`pointer` 或 `row location`。B-tree 不是把 SQL 表“原样画成一棵树”，而是把某个被索引的 column value 当成 key，用它来快速定位对应的 row。

## SQL table 是逻辑视图

在 SQL 里，我们定义一张表：

```sql
CREATE TABLE users (
    id bigint PRIMARY KEY,
    email text,
    name text
);
```

从应用视角看，`users` 表由 rows 和 columns 组成：

```text
id   email            name
251  a@example.com    Alice
252  b@example.com    Bob
253  c@example.com    Carol
```

但这只是逻辑层。数据库真正存储时，会把每一行编码成内部格式，例如：

```text
(id=251, email='a@example.com', name='Alice') -> row bytes
```

这些 `row bytes` 会被放进磁盘上的 `page` 里。很多数据库不是一行一行从磁盘读，而是按 page 读，例如 PostgreSQL 默认 8 KB page，MySQL InnoDB 默认 16 KB page。一个 page 里可能装很多 rows。

所以 SQL 层说的是：

```text
table -> rows -> columns
```

storage engine 层看到的是：

```text
file -> pages -> row bytes -> fields
```

## B-tree index 是 key 到 row 的映射

B-tree 的作用是让数据库不用扫描整张表，而是能按某个 key 快速找到目标 row。

如果我们用 `id` 建索引，B-tree entry 可以粗略理解为：

```text
key   = 251
value = 这一行在哪里，或者这一行本身
```

也就是说，B-tree 负责维护一个有序映射：

```text
251 -> row for Alice
252 -> row for Bob
253 -> row for Carol
```

查询：

```sql
SELECT * FROM users WHERE id = 251;
```

底层路径大概是：

```text
1. query planner 发现 WHERE id = 251 可以使用 id index
2. storage engine 从 B-tree root page 开始查找 key = 251
3. 沿着 key range 找到 leaf page
4. 在 leaf page 里找到对应 entry
5. 根据 entry 取出 full row 或 row location
6. executor 把 row 解码成 SQL 结果
```

所以，SQL 查询里的 `WHERE id = 251` 在 storage engine 里会变成一次 B-tree key lookup。

## 普通 index：key 指向 row location

很多数据库会把表数据本身放在一个独立的 `heap file` 里。`heap file` 可以理解为“按某种物理顺序存 row 的地方”，它不一定按 primary key 排序。

在这种设计里，B-tree index 通常不是直接存完整 row，而是存 row 的位置：

```text
B-tree index on users.id

key = 251
value = heap page / row slot / row id
```

查询时先查 B-tree，再根据 row location 去 heap file 取完整 row：

```text
B-tree:    id=251 -> page 42, slot 7
heap file: page 42, slot 7 -> full row
```

这就是很多数据库里常说的“通过 index 找到 row，再回表取数据”。

PostgreSQL 就更接近这种模型：table rows 主要在 heap table 里，B-tree index entry 指向 heap tuple 的位置。

## Clustered index：B-tree 的 leaf node 直接存 full row

另一种设计是 `clustered index`。这时表数据本身就存放在 B-tree 里，通常按 index key 的顺序组织。

以 MySQL InnoDB 为例，table 的 `primary key` 默认就是 `clustered index`：

```sql
CREATE TABLE users (
    id bigint PRIMARY KEY,
    email text,
    name text
) ENGINE = InnoDB;
```

InnoDB 的 clustered B-tree 可以粗略理解为：

```text
key = id
value = full row
```

leaf node 里不是简单的 pointer，而是完整 row：

```text
clustered index on users.id

251 -> (id=251, email='a@example.com', name='Alice')
252 -> (id=252, email='b@example.com', name='Bob')
253 -> (id=253, email='c@example.com', name='Carol')
```

查询：

```sql
SELECT * FROM users WHERE id = 251;
```

路径就是：

```text
clustered index: id -> full row
```

这也是为什么 `clustered index` 很重要：它不是额外放在旁边的一本索引，而是表的实际物理组织方式。

## Secondary index：另一个入口，但通常不直接存 full row

如果我们再给 `email` 建一个 index：

```sql
CREATE INDEX users_email_idx ON users (email);
```

这就是 `secondary index`，因为它不是表的 primary key，也通常不是表数据的主存储结构。

在 InnoDB 里，secondary index 的 leaf node 通常存 secondary key 和 primary key：

```text
users_email_idx:
'a@example.com' -> 251
'b@example.com' -> 252
'c@example.com' -> 253
```

而 clustered index 存 full row：

```text
clustered index:
251 -> full row for Alice
252 -> full row for Bob
253 -> full row for Carol
```

查询：

```sql
SELECT * FROM users WHERE email = 'a@example.com';
```

执行路径大概是：

```text
1. 先查 secondary index users_email_idx
2. 找到 email = 'a@example.com' 对应的 primary key: 251
3. 再用 primary key = 251 回到 clustered index
4. 从 clustered index leaf node 取出 full row
```

也就是：

```text
secondary index: email -> id
clustered index: id -> full row
```

这回答了一个常见疑问：查询不是固定“先查 primary index”或“先查 secondary index”。数据库会根据 `WHERE` 条件选择入口。

```text
WHERE id = 251                 -> 直接查 primary / clustered index
WHERE email = 'a@example.com'  -> 先查 email secondary index，再回 primary / clustered index
WHERE name = 'Alice'           -> 如果 name 没 index，可能 full table scan
```

## SELECT 几列不等于底层只读几列

另一个容易混淆的点是：

```sql
SELECT email FROM users WHERE id = 251;
```

SQL 结果只需要 `email` 这一列，但 row-oriented database 底层通常还是按 row/page 读取。也就是说，storage engine 可能会把包含这行的整个 page 读进内存，再从 row bytes 里解析出 `email`。

在 row-oriented storage 里，数据布局像这样：

```text
page 42:
  row 1: id, email, name, age, city, ...
  row 2: id, email, name, age, city, ...
  row 3: id, email, name, age, city, ...
```

如果查询只需要 `email`，数据库最终只会把 `email` 返回给你；但 I/O 上可能已经读入了整行所在的 page。那些不需要的 columns 不参与最终计算，但它们跟着 row/page 一起被读到了内存里。

这就是 row-oriented storage 在分析查询里低效的原因之一。比如 fact table 有 100 多列，但查询只需要 `date_key`、`product_sk`、`quantity`：

```sql
SELECT dim_date.weekday, dim_product.category, SUM(fact_sales.quantity)
FROM fact_sales
JOIN dim_date ON fact_sales.date_key = dim_date.date_key
JOIN dim_product ON fact_sales.product_sk = dim_product.product_sk
WHERE dim_date.year = 2024
  AND dim_product.category IN ('Fresh fruit', 'Candy')
GROUP BY dim_date.weekday, dim_product.category;
```

row-oriented database 可能需要读取大量完整 rows，再从中抽出少数几列。column-oriented storage 的优势正好相反：它把同一列的数据放在一起，所以可以只读取查询需要的 columns。

## Covering index 是一个重要例外

如果 index 本身已经包含查询需要的所有 columns，数据库就可以只读 index，不回表读取完整 row。这叫 `covering index`。

例如：

```sql
CREATE INDEX users_email_name_idx ON users (email, name);

SELECT name FROM users WHERE email = 'a@example.com';
```

如果 `users_email_name_idx` 里已经有 `email` 和 `name`，数据库可能只读这个 index：

```text
users_email_name_idx: email -> name
```

这时就不需要再去 heap file 或 clustered index 取 full row。

但代价是 index 变大，写入更慢，因为每次 insert/update/delete 都要维护更多 index entries。`covering index` 是典型的 read optimization，用额外空间和写入成本换读取速度。

## 总结心智模型

可以把 SQL table 到 B-tree 的映射记成四层：

```text
SQL logical layer:
  table -> rows -> columns

storage layout:
  file -> pages -> row bytes

B-tree index:
  indexed column value -> row location / primary key / full row

query execution:
  SQL predicate -> index lookup -> row fetch -> filter/join/aggregate -> result
```

不同数据库的关键差异在于 B-tree 的 value 存什么：

```text
heap-table design:
  primary/secondary index -> heap row location

InnoDB clustered design:
  primary key / clustered index -> full row
  secondary index -> primary key

covering index:
  index -> enough columns to answer query directly
```

所以最核心的一句话是：SQL 表的数据会被编码成 rows/pages；B-tree 用某个 indexed column 的值作为 key，把它映射到 row location、primary key，或者 full row。查询时，数据库不是“按 SQL 表格样子”查，而是在这些物理结构之间跳转。
