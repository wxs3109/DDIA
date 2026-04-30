"""
wal.py — B-Tree 的 Write-Ahead Log

DDIA ch4 说：
  "为了使数据库对崩溃具有弹性，B 树实现通常包括磁盘上的额外数据结构：
   预写日志（WAL）。这是一个仅追加文件，每个 B 树修改必须在应用于树
   本身的页之前写入其中。当数据库在崩溃后恢复时，此日志用于将 B 树
   恢复到一致状态。"

─── B-Tree WAL 与 LSM WAL 的区别 ───────────────────────────

LSM WAL 记录的是逻辑操作（PUT key value / DEL key），
因为 LSM 的 MemTable 是纯内存结构，WAL 是它在磁盘上的影子。

B-Tree WAL 记录的是物理操作（某个页写成了什么内容），
因为 B-Tree 直接原地覆盖磁盘页，写到一半崩溃会留下损坏的页。
WAL 让我们在重启时知道"这个页应该是什么样子"。

─── WAL 记录格式 ────────────────────────────────────────────

数据记录（每改一页写一条）：
  [4B magic=0xB7EE_D47A]  页记录魔数
  [4B page_id           ]
  [PAGE_SIZE bytes      ]  页的完整内容（固定大小）

提交标记（一次多页操作全部写完后写一条）：
  [4B magic=0xB7EE_C0FF]  commit 魔数

─── 原子性保证 ──────────────────────────────────────────────

单页操作（如简单 put 更新已有 key）本来是原子的，但 split/merge
涉及 3+ 页，必须作为一个整体原子提交。我们用 commit marker 实现：

写入流程（多页操作）：
  1. 把所有要改的页依次追加为 WAL 数据记录（不 fsync）
  2. 追加 commit marker，然后 fsync WAL
  3. 把所有页写入数据库文件，fsync 数据库文件

重放流程：
  扫描 WAL，把数据记录收集到 pending 缓冲；
  遇到 commit marker 时，把 pending 里的页批量写入 DB 文件（已提交）；
  遇到文件末尾或损坏时，丢弃 pending（未提交的部分操作）。

─── 正常关闭 vs 崩溃 ────────────────────────────────────────

正常关闭（close）：
  1. 所有数据已写入 DB 文件并 fsync
  2. 截断 WAL（清空）
  3. 下次打开时 WAL 为空，跳过 replay

崩溃：
  WAL 未截断，包含一批完整提交记录（和可能的残缺尾部）。
  下次打开时 replay 把已提交页写回 DB 文件，残缺尾部被丢弃。
"""

import os
import struct
from pathlib import Path

from .page import PAGE_SIZE, Page

# 两种 WAL 记录的魔数，用于区分页记录和提交标记
_MAGIC_PAGE   = 0xB7EED47A
_MAGIC_COMMIT = 0xB7EEC0FF

# 页记录：magic(4B) + page_id(4B) + PAGE_SIZE bytes
_PAGE_HDR   = struct.Struct(">II")

# 提交标记：只有 magic(4B)
_COMMIT_HDR = struct.Struct(">I")


class WAL:
    def __init__(self, path: Path):
        self.path = path
        self._f = open(path, "ab")

    def begin_batch(self, pages: list[Page]) -> None:
        """
        原子地把一批页变更记录到 WAL，然后写 commit marker 并 fsync。
        调用者在此之后再把页写入 DB 文件。

        单页操作也走这条路径（batch 大小为 1），保持接口统一。
        """
        # 1. 写所有页记录（不单独 fsync，等 commit marker 一起落盘）
        for page in pages:
            data = page.serialize()
            self._f.write(_PAGE_HDR.pack(_MAGIC_PAGE, page.page_id))
            self._f.write(data)

        # 2. 写 commit marker，再 fsync 一次性落盘
        #    这一步成功 = 整批变更已持久化，replay 时会应用
        self._f.write(_COMMIT_HDR.pack(_MAGIC_COMMIT))
        self._f.flush()
        os.fsync(self._f.fileno())

    def close(self, checkpoint: bool = True) -> None:
        """
        正常关闭。checkpoint=True 时截断 WAL（已安全落盘，不再需要）。
        崩溃路径不会调用 close，WAL 留在磁盘供下次 replay。
        """
        if checkpoint:
            self._f.close()
            with open(self.path, "wb"):  # 截断为 0 字节
                pass
        else:
            self._f.close()

    @staticmethod
    def replay(wal_path: Path, db_path: Path) -> None:
        """
        崩溃恢复：重放 WAL 中所有已提交的批次，把页写回数据库文件。

        扫描逻辑：
          - 读页记录，积累到 pending dict（page_id -> bytes）
          - 读到 commit marker -> 把 pending 写入 DB，清空 pending
          - 读到残缺数据或文件末尾 -> 丢弃 pending（未提交）
        """
        if not wal_path.exists() or wal_path.stat().st_size == 0:
            return

        # 如果 DB 文件不存在（首次崩溃恢复），先创建
        db_path.touch()

        pending: dict[int, bytes] = {}  # page_id -> serialized page bytes

        with open(wal_path, "rb") as wf:
            committed_batches: list[dict[int, bytes]] = []

            while True:
                magic_raw = wf.read(4)
                if len(magic_raw) < 4:
                    break  # 文件末尾，残缺记录，丢弃 pending

                (magic,) = struct.unpack(">I", magic_raw)

                if magic == _MAGIC_PAGE:
                    # 读 page_id + 页内容
                    pid_raw = wf.read(4)
                    if len(pid_raw) < 4:
                        break
                    (page_id,) = struct.unpack(">I", pid_raw)
                    page_data = wf.read(PAGE_SIZE)
                    if len(page_data) < PAGE_SIZE:
                        break  # 页内容不完整，丢弃
                    pending[page_id] = page_data

                elif magic == _MAGIC_COMMIT:
                    # 整批已提交，记录下来
                    committed_batches.append(dict(pending))
                    pending = {}

                else:
                    break  # 未知魔数，数据损坏，停止

        if not committed_batches:
            return

        # 把所有已提交批次的页写回 DB 文件
        with open(db_path, "r+b") as df:
            for batch in committed_batches:
                for page_id, page_data in batch.items():
                    offset = page_id * PAGE_SIZE
                    df.seek(0, 2)
                    if df.tell() < offset + PAGE_SIZE:
                        # 文件不够长，扩展
                        df.seek(offset)
                        df.write(b"\x00" * PAGE_SIZE)
                    df.seek(offset)
                    df.write(page_data)
            df.flush()
            os.fsync(df.fileno())
