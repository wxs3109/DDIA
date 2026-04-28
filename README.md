# System Design Study

Personal learning repo for system design — reading, notes, and Python practice code.

## Structure

```text
books/          原书中文翻译（只读参考）
  ddia/         Designing Data-Intensive Applications, 2nd Ed.

notes/          读书笔记（按书 + 章节）
  ddia/         DDIA 各章笔记，可自由拆分

practice/       代码 / 伪代码练习（按主题）
  storage-engines/
  replication/
  distributed-consensus/
  data-models/
```

## Books

| 书名                                            | 目录                        | 状态   |
| ----------------------------------------------- | --------------------------- | ------ |
| Designing Data-Intensive Applications (2nd Ed.) | [books/ddia/](books/ddia/) | 阅读中 |

## Notes 引用格式

笔记中引用原书章节用相对路径：

```markdown
见 [DDIA ch3 — 图数据模型](../../books/ddia/ch3.md#sec_datamodels_graph)
```

## Practice 文件命名

`practice/<topic>/<concept>.py`，文件头部注明对应原书章节。
