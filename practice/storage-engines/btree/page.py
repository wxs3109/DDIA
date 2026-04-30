"""
page.py — B-Tree 的基本磁盘单元

DDIA ch4 说：
  "B 树将数据库分解为固定大小的块或页，并可能就地覆盖页。
   页传统上大小为 4 KiB。"

这里我们用一个简化版：每个 Page 固定序列化成 PAGE_SIZE 字节，
页号 * PAGE_SIZE = 该页在数据库文件中的字节偏移。

─── 页内布局 ────────────────────────────────────────────────

叶页（is_leaf=True）：
  存放实际的 key-value 数据。
  keys[i] 对应 values[i]，两者一一配对。

  keys:   ["apple", "banana", "cherry"]
  values: ["red",   "yellow", "red"   ]

内部页（is_leaf=False）：
  不存 value，只存 key 和子页指针（page_id）。
  children 比 keys 多一个，因为 n 个 key 把键空间分成 n+1 段：

  keys:     [200,        300       ]
  children: [page_id_A, page_id_B, page_id_C]
              < 200      200-300    > 300

─── 序列化格式 ──────────────────────────────────────────────

  [1B  is_leaf  ]
  [4B  n_keys   ]  键的数量
  [4B  n_vals   ]  值/子页数量（叶页 == n_keys，内部页 == n_keys+1）
  [4B  left_sib ]  左兄弟页 page_id（-1 表示无），仅叶页使用
  [4B  right_sib]  右兄弟页 page_id（-1 表示无），仅叶页使用
  重复 n_keys 次：
    [4B  key_len][key bytes]
  重复 n_vals 次：
    [4B  val_len][val bytes]   叶页：实际值；内部页：page_id 的十进制字符串
  [剩余字节用 \x00 填充到 PAGE_SIZE]
"""

import struct
from dataclasses import dataclass, field

# 与 DDIA 书中提到的传统页大小一致
PAGE_SIZE = 4096

# 固定头部：is_leaf(1) + n_keys(4) + n_vals(4) + left_sib(4) + right_sib(4)
_HEADER = struct.Struct(">BIIii")  # B=uint8, I=uint32, I=uint32, i=int32, i=int32
_LEN4   = struct.Struct(">I")      # 用于读写每个 key/value 的长度前缀


@dataclass
class Page:
    page_id:   int                   # 页号，决定在文件中的偏移
    is_leaf:   bool                  # True = 叶页，False = 内部页
    keys:      list[str] = field(default_factory=list)
    # 叶页：values[i] 是 keys[i] 对应的值
    # 内部页：values[i] 是第 i 个子页的 page_id（存成字符串）
    values:    list[str] = field(default_factory=list)
    # 叶页专用：指向相邻叶页，支持范围扫描时不必回溯父页
    left_sib:  int = -1
    right_sib: int = -1

    # ── 便捷属性 ──────────────────────────────────────────────────────────────

    @property
    def n_keys(self) -> int:
        return len(self.keys)

    @property
    def child_ids(self) -> list[int]:
        """内部页专用：把 values 解释成 int page_id 列表。"""
        assert not self.is_leaf, "child_ids only valid for internal pages"
        return [int(v) for v in self.values]

    # ── 序列化 ────────────────────────────────────────────────────────────────

    def serialize(self) -> bytes:
        """把 Page 打包成恰好 PAGE_SIZE 字节，准备写入磁盘。"""
        buf = bytearray()

        # 写头部
        buf += _HEADER.pack(
            int(self.is_leaf),
            len(self.keys),
            len(self.values),
            self.left_sib,
            self.right_sib,
        )

        # 写所有 key（前缀 4 字节长度）
        for k in self.keys:
            kb = k.encode()
            buf += _LEN4.pack(len(kb))
            buf += kb

        # 写所有 value / child_id（前缀 4 字节长度）
        for v in self.values:
            vb = v.encode()
            buf += _LEN4.pack(len(vb))
            buf += vb

        # 填充到固定大小
        if len(buf) > PAGE_SIZE:
            raise OverflowError(
                f"Page {self.page_id} serialized to {len(buf)} bytes "
                f"which exceeds PAGE_SIZE={PAGE_SIZE}"
            )
        buf += b"\x00" * (PAGE_SIZE - len(buf))
        return bytes(buf)

    @classmethod
    def deserialize(cls, page_id: int, data: bytes) -> "Page":
        """从磁盘读出的 PAGE_SIZE 字节还原成 Page 对象。"""
        assert len(data) == PAGE_SIZE

        offset = 0
        is_leaf_int, n_keys, n_vals, left_sib, right_sib = _HEADER.unpack_from(data, offset)
        offset += _HEADER.size

        def read_str() -> str:
            nonlocal offset
            (length,) = _LEN4.unpack_from(data, offset)
            offset += _LEN4.size
            s = data[offset: offset + length].decode()
            offset += length
            return s

        keys   = [read_str() for _ in range(n_keys)]
        values = [read_str() for _ in range(n_vals)]

        return cls(
            page_id=page_id,
            is_leaf=bool(is_leaf_int),
            keys=keys,
            values=values,
            left_sib=left_sib,
            right_sib=right_sib,
        )

    # ── 调试打印 ──────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        kind = "Leaf" if self.is_leaf else "Internal"
        if self.is_leaf:
            pairs = ", ".join(f"{k}={v}" for k, v in zip(self.keys, self.values))
            return f"{kind}(id={self.page_id} [{pairs}])"
        else:
            return (
                f"{kind}(id={self.page_id} "
                f"keys={self.keys} children={self.values})"
            )
