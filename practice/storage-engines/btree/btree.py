"""
btree.py — B-Tree 核心实现

DDIA ch4 核心描述：
  - B 树把数据库分解为固定大小的页（4 KiB），原地覆盖更新。
  - 一个页被指定为根；查找从根开始，沿子页引用逐层向下。
  - n 个 key 把内部页分成 n+1 个子范围，引用之间的 key 是边界。
  - 叶页存实际 key-value；叶页满了触发 split，中间 key 上推父页。
  - split 可以一路传播到根；根 split 时创建新根，树高 +1。
  - 删除 key 后若页太空，与兄弟页合并或向兄弟借 key。

─── ORDER（阶）的含义 ────────────────────────────────────────

我们使用"最小度"定义（与 CLRS 教材一致）：
  ORDER = t，则：
  - 非根页最少有 t-1 个 key
  - 任何页最多有 2t-1 个 key
  - 内部页最多有 2t 个子页

ORDER=2 是最小合法 B-Tree（即 2-3-4 树的变体）。
演示用 ORDER=2，这样插入很少的 key 就能触发 split，便于观察。

─── 数据库文件布局 ──────────────────────────────────────────

文件 db.bin：
  [page_0: PAGE_SIZE bytes]  永远是根页（根 split 时就地更新根）
  [page_1: PAGE_SIZE bytes]
  [page_2: PAGE_SIZE bytes]
  ...

page_id * PAGE_SIZE = 该页在文件中的字节偏移。

─── 操作概览 ────────────────────────────────────────────────

get(key)：
  从根出发，在每个内部页二分查找正确的子页引用，
  直到叶页，再在叶页线性扫描找 key。

put(key, value)：
  1. 从根出发找到目标叶页（同时记录沿途路径）
  2. 把 key 插入叶页（保持有序）
  3. 如果叶页超出容量，触发 split：
     a. 把叶页从中间一分为二
     b. 中间 key 上推到父页
     c. 父页若也满了，继续向上 split
     d. 若根 split，创建新根，树高 +1

delete(key)：
  1. 找到包含 key 的叶页并删除
  2. 如果叶页 key 数量低于下限（t-1），需要"再平衡"：
     a. 先尝试从兄弟页借一个 key（rotation）
     b. 借不到则与兄弟页合并（merge），同时从父页删一个 key
     c. 父页若也低于下限，继续向上再平衡

─── 多页操作的原子性 ────────────────────────────────────────

split/merge 涉及 2-4 页同时修改，中途崩溃会留下结构不一致的树。
我们通过 WAL batch commit 保证原子性：
  1. 把本次操作所有要改的页收集到列表
  2. 调用 WAL.begin_batch(pages) 一次性写入 WAL 并 fsync
  3. 再把每页写入 DB 文件（并 fsync）
  4. 重放时只有 commit marker 之前的完整批次才会被应用

这样崩溃场景只有两种结果：
  a. commit marker 未写 -> replay 丢弃整批，树回到操作前状态
  b. commit marker 已写 -> replay 把所有页都写回，树到达操作后状态
"""

import os
from pathlib import Path
from typing import Optional

from .page import PAGE_SIZE, Page
from .wal import WAL

# 演示用小阶数，方便快速触发 split/merge
ORDER = 2  # 每页最多 2*ORDER-1 = 3 个 key；非根页最少 ORDER-1 = 1 个 key

# 根页永远在 page_id=0
ROOT_PAGE_ID = 0


class BTree:
    def __init__(self, db_path: str | Path, wal_path: str | Path | None = None):
        self.db_path  = Path(db_path)
        self.wal_path = Path(wal_path) if wal_path else self.db_path.with_suffix(".wal")

        # 崩溃恢复：先重放 WAL，再打开数据库文件
        WAL.replay(self.wal_path, self.db_path)

        self._wal = WAL(self.wal_path)

        # 如果数据库文件不存在或为空，初始化一个空的叶页作为根
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            self._next_page_id = 1
            root = Page(page_id=ROOT_PAGE_ID, is_leaf=True)
            self._write_pages([root])
        else:
            # 从文件大小推断下一个可用页号
            self._next_page_id = self.db_path.stat().st_size // PAGE_SIZE

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        """
        查找 key 对应的 value，不存在返回 None。

        路径：根 -> 内部页（按 key range 选子页）-> 叶页（线性扫描）
        DDIA："一个页被指定为 B 树的根；每当你想在索引中查找一个键时，
               你就从这里开始。"
        """
        node = self._read_page(ROOT_PAGE_ID)

        while not node.is_leaf:
            # 内部页结构：children[0] | keys[0] | children[1] | keys[1] | ...
            # key < keys[i] 则进 children[i]；key >= 所有 keys 则进最后一个 child
            child_idx = self._find_child_idx(node, key)
            node = self._read_page(node.child_ids[child_idx])

        for k, v in zip(node.keys, node.values):
            if k == key:
                return v
        return None

    def put(self, key: str, value: str) -> None:
        """
        插入或更新 key-value。
        如果 key 已存在，就地更新值。
        如果 key 不存在，插入并在必要时触发 split。
        """
        # 沿途记录路径（含每层选择的 child index），split 时需要从叶往根回溯
        path: list[tuple[Page, int]] = []  # (parent_page, child_idx_we_took)
        node = self._read_page(ROOT_PAGE_ID)

        while not node.is_leaf:
            child_idx = self._find_child_idx(node, key)
            path.append((node, child_idx))
            node = self._read_page(node.child_ids[child_idx])

        # 情况 1：key 已存在，原地更新
        for i, k in enumerate(node.keys):
            if k == key:
                node.values[i] = value
                self._write_pages([node])
                return

        # 情况 2：key 不存在，有序插入
        self._insert_into_leaf(node, key, value)

        if node.n_keys <= 2 * ORDER - 1:
            self._write_pages([node])
            return

        # 叶页已满，触发 split，并沿路径向上传播
        self._split_and_propagate(node, path)

    def delete(self, key: str) -> bool:
        """
        删除 key。返回 True 表示成功，False 表示 key 不存在。
        删除后若页 key 数量低于下限，触发再平衡（借 key 或合并）。
        """
        path: list[tuple[Page, int]] = []
        node = self._read_page(ROOT_PAGE_ID)

        while not node.is_leaf:
            child_idx = self._find_child_idx(node, key)
            path.append((node, child_idx))
            node = self._read_page(node.child_ids[child_idx])

        if key not in node.keys:
            return False

        idx = node.keys.index(key)
        node.keys.pop(idx)
        node.values.pop(idx)
        self._write_pages([node])

        # 根页是叶页时（树只有一层），没有下限限制
        if node.page_id == ROOT_PAGE_ID:
            return True

        if node.n_keys >= ORDER - 1:
            return True

        self._rebalance(node, path)
        return True

    def scan(self) -> list[tuple[str, str]]:
        """
        按 key 升序返回所有 key-value 对。
        利用叶页的 right_sib 指针，直接在叶层横向遍历，不需要回溯父页。
        DDIA："每个叶页可能有对其左右兄弟页的引用，
               这允许按顺序扫描键而无需跳回父页。"
        """
        node = self._read_page(ROOT_PAGE_ID)
        while not node.is_leaf:
            node = self._read_page(node.child_ids[0])

        result = []
        while True:
            for k, v in zip(node.keys, node.values):
                result.append((k, v))
            if node.right_sib == -1:
                break
            node = self._read_page(node.right_sib)
        return result

    def close(self) -> None:
        """
        正常关闭：截断 WAL。
        下次打开时 WAL 为空，跳过 replay，区别于崩溃后的重启。
        """
        self._wal.close(checkpoint=True)

    # ── split 相关 ────────────────────────────────────────────────────────────

    def _split_and_propagate(
        self, node: Page, path: list[tuple[Page, int]]
    ) -> None:
        """
        从 node 开始向上 split，直到某个祖先页不满，或分裂到根。

        DDIA："如果页中没有足够的空闲空间来容纳新键，则页被分成两个
               半满的页，并更新父页以说明键范围的新细分。"
        """
        while node.n_keys > 2 * ORDER - 1:
            if not path:
                self._split_root(node)
                return
            parent, child_idx = path.pop()
            node = self._split_node(node, parent, child_idx)

    def _split_node(self, node: Page, parent: Page, child_idx: int) -> Page:
        """
        把 node（叶页或内部页）从中间一分为二，把中间 key 上推到 parent。
        返回 parent（供调用方继续检查 parent 是否也满了）。

        分割点 mid = ORDER - 1（0-indexed）

        叶页分割（keys 共 2t 个，t=ORDER=2，刚插入后已是 2t=4 个）：
          原始：  [k0, k1, k2, k3]  values=[v0,v1,v2,v3]
          左页：  [k0]              values=[v0]            保留前 mid=1 个
          右页：  [k1,k2,k3]       values=[v1,v2,v3]      从 mid 开始
          上推：  k1（右页最小 key，同时保留在右页，叶页 key 不能移走）

        内部页分割（keys 共 2t 个）：
          原始：  [k0,k1,k2,k3]  children=[c0,c1,c2,c3,c4]
          左页：  [k0]           children=[c0,c1]
          右页：  [k2,k3]        children=[c2,c3,c4]
          上推：  k1（真正移走，不在左右页里）

        child_idx 是 node 在 parent.children 中的下标，
        用它直接插入 parent，避免按 key 重新搜索（分界 key 重复时会出错）。
        """
        mid = ORDER - 1

        right = Page(page_id=self._alloc_page_id(), is_leaf=node.is_leaf)

        if node.is_leaf:
            pushed_up_key = node.keys[mid]
            right.keys   = node.keys[mid:]
            right.values = node.values[mid:]
            node.keys    = node.keys[:mid]
            node.values  = node.values[:mid]

            # 维护叶页链表：node <-> right <-> node.right_sib
            right.right_sib = node.right_sib
            right.left_sib  = node.page_id
            if node.right_sib != -1:
                old_right = self._read_page(node.right_sib)
                old_right.left_sib = right.page_id
                # old_right 也要写入，纳入同一批次
            node.right_sib = right.page_id

        else:
            pushed_up_key = node.keys[mid]
            right.keys    = node.keys[mid + 1:]
            right.values  = node.values[mid + 1:]
            node.keys     = node.keys[:mid]
            node.values   = node.values[:mid + 1]

        # 用 child_idx 直接定位插入位置，不重新搜索
        # parent.values[child_idx] 已经是 node（左页），在其右边插入 right
        parent.keys.insert(child_idx, pushed_up_key)
        parent.values.insert(child_idx + 1, str(right.page_id))

        # 收集本次操作所有变更页，原子写入
        dirty = [node, right, parent]
        if node.is_leaf and node.right_sib != -1 and right.right_sib != -1:
            # old_right 的 left_sib 也改了，纳入同一批次
            old_right_page = self._read_page(right.right_sib)
            old_right_page.left_sib = right.page_id
            dirty.append(old_right_page)

        self._write_pages(dirty)
        return parent

    def _split_root(self, root: Page) -> None:
        """
        根页满时的特殊处理。
        把根内容移到两个新子页，根变成只有一个 key 的内部页。

        DDIA："当根被分割时，我们在它上面创建一个新根。"
        我们保持根永远在 page_id=0，把内容复制到新页而非改根的 page_id。
        """
        mid = ORDER - 1

        left = Page(page_id=self._alloc_page_id(), is_leaf=root.is_leaf)

        if root.is_leaf:
            pushed_up_key = root.keys[mid]
            left.keys   = root.keys[:mid]
            left.values = root.values[:mid]

            right = Page(page_id=self._alloc_page_id(), is_leaf=True)
            right.keys   = root.keys[mid:]
            right.values = root.values[mid:]

            left.right_sib  = right.page_id
            right.left_sib  = left.page_id

        else:
            pushed_up_key = root.keys[mid]
            left.keys   = root.keys[:mid]
            left.values = root.values[:mid + 1]

            right = Page(page_id=self._alloc_page_id(), is_leaf=False)
            right.keys   = root.keys[mid + 1:]
            right.values = root.values[mid + 1:]

        root.is_leaf = False
        root.keys    = [pushed_up_key]
        root.values  = [str(left.page_id), str(right.page_id)]

        self._write_pages([left, right, root])

    # ── delete 再平衡 ─────────────────────────────────────────────────────────

    def _rebalance(
        self, node: Page, path: list[tuple[Page, int]]
    ) -> None:
        """
        删除后若页 key 数 < ORDER-1，尝试从兄弟借 key；借不到则合并。
        DDIA："删除键（可能需要合并节点）更复杂。"

        path 里的 child_idx 是"我们沿哪个 child 下去的"，
        即 node 在 parent.children 中的下标，直接用于定位兄弟。
        """
        while node.page_id != ROOT_PAGE_ID and node.n_keys < ORDER - 1:
            parent, my_idx = path.pop()
            child_ids = parent.child_ids

            # 优先尝试从右兄弟借
            if my_idx < len(child_ids) - 1:
                right_sib = self._read_page(child_ids[my_idx + 1])
                if right_sib.n_keys > ORDER - 1:
                    self._rotate_left(node, parent, right_sib, my_idx)
                    return

            # 再尝试从左兄弟借
            if my_idx > 0:
                left_sib = self._read_page(child_ids[my_idx - 1])
                if left_sib.n_keys > ORDER - 1:
                    self._rotate_right(node, parent, left_sib, my_idx)
                    return

            # 两边都借不到，合并
            if my_idx < len(child_ids) - 1:
                right_sib = self._read_page(child_ids[my_idx + 1])
                self._merge(node, parent, right_sib, my_idx)
            else:
                left_sib = self._read_page(child_ids[my_idx - 1])
                self._merge(left_sib, parent, node, my_idx - 1)

            node = parent

        # 根页变成 0 个 key 的内部页时，把唯一子页提升为新根
        root = self._read_page(ROOT_PAGE_ID)
        if not root.is_leaf and root.n_keys == 0:
            only_child = self._read_page(root.child_ids[0])
            root.is_leaf = only_child.is_leaf
            root.keys    = only_child.keys
            root.values  = only_child.values
            self._write_pages([root])

    def _rotate_left(
        self, node: Page, parent: Page, right_sib: Page, my_idx: int
    ) -> None:
        """
        从右兄弟借一个 key（向左旋转）：
          parent.keys[my_idx]  下沉到 node 最右
          right_sib.keys[0]    上升到 parent.keys[my_idx]
          right_sib.children[0] 移给 node 最右 child（内部页）
        """
        if node.is_leaf:
            node.keys.append(right_sib.keys.pop(0))
            node.values.append(right_sib.values.pop(0))
            parent.keys[my_idx] = right_sib.keys[0]
        else:
            node.keys.append(parent.keys[my_idx])
            node.values.append(right_sib.values.pop(0))
            parent.keys[my_idx] = right_sib.keys.pop(0)

        self._write_pages([node, parent, right_sib])

    def _rotate_right(
        self, node: Page, parent: Page, left_sib: Page, my_idx: int
    ) -> None:
        """
        从左兄弟借一个 key（向右旋转）：
          parent.keys[my_idx-1]  下沉到 node 最左
          left_sib.keys[-1]      上升到 parent.keys[my_idx-1]
          left_sib.children[-1]  移给 node 最左 child（内部页）
        """
        if node.is_leaf:
            node.keys.insert(0, left_sib.keys.pop())
            node.values.insert(0, left_sib.values.pop())
            parent.keys[my_idx - 1] = node.keys[0]
        else:
            node.keys.insert(0, parent.keys[my_idx - 1])
            node.values.insert(0, left_sib.values.pop())
            parent.keys[my_idx - 1] = left_sib.keys.pop()

        self._write_pages([node, parent, left_sib])

    def _merge(
        self, left: Page, parent: Page, right: Page, left_idx: int
    ) -> None:
        """
        把 right 合并进 left，从 parent 删掉分界 key 和 right 的引用。

        叶页合并：left.kv + right.kv，维护叶页链表。
        内部页合并：left.kv + parent 分界 key + right.kv + right children。
        """
        dirty = [left, parent]

        if left.is_leaf:
            left.keys   += right.keys
            left.values += right.values
            left.right_sib = right.right_sib
            if right.right_sib != -1:
                far_right = self._read_page(right.right_sib)
                far_right.left_sib = left.page_id
                dirty.append(far_right)
        else:
            separator = parent.keys[left_idx]
            left.keys   += [separator] + right.keys
            left.values += right.values

        parent.keys.pop(left_idx)
        parent.values.pop(left_idx + 1)

        self._write_pages(dirty)

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _find_child_idx(self, node: Page, key: str) -> int:
        """
        在内部页里找 key 应该走第几个 child（0-indexed）。

          children[0] | keys[0] | children[1] | keys[1] | ... | children[n]
          key < keys[0]           -> children[0]
          keys[i-1] <= key < keys[i] -> children[i]
          key >= keys[n-1]        -> children[n]
        """
        for i, k in enumerate(node.keys):
            if key < k:
                return i
        return len(node.keys)

    def _insert_into_leaf(self, leaf: Page, key: str, value: str) -> None:
        """有序插入到叶页，保持 keys 升序。"""
        for i, k in enumerate(leaf.keys):
            if key < k:
                leaf.keys.insert(i, key)
                leaf.values.insert(i, value)
                return
        leaf.keys.append(key)
        leaf.values.append(value)

    # ── 页 I/O ────────────────────────────────────────────────────────────────

    def _alloc_page_id(self) -> int:
        """分配一个新页号（递增），实际写入在 _write_pages 时发生。"""
        pid = self._next_page_id
        self._next_page_id += 1
        return pid

    def _read_page(self, page_id: int) -> Page:
        """从数据库文件读取指定页。"""
        offset = page_id * PAGE_SIZE
        with open(self.db_path, "rb") as f:
            f.seek(offset)
            data = f.read(PAGE_SIZE)
        return Page.deserialize(page_id, data)

    def _write_pages(self, pages: list[Page]) -> None:
        """
        原子地把一批页写入 WAL（commit marker + fsync），
        再逐页写入数据库文件并 fsync。

        DDIA："B 树的基本底层写操作是用新数据覆盖磁盘上的页。"

        写入顺序：
          1. WAL batch commit（所有页 + commit marker + fsync）
          2. DB 文件写入 + fsync
        崩溃在步骤 1 之前：WAL 无 commit marker，replay 丢弃，树不变。
        崩溃在步骤 1 之后：WAL 有 commit marker，replay 把所有页写回。
        """
        # 步骤 1：WAL batch commit
        self._wal.begin_batch(pages)

        # 步骤 2：写入 DB 文件（文件不存在时先创建）
        if not self.db_path.exists():
            self.db_path.touch()
        with open(self.db_path, "r+b") as f:
            for page in pages:
                data   = page.serialize()
                offset = page.page_id * PAGE_SIZE

                f.seek(0, 2)
                if f.tell() < offset + PAGE_SIZE:
                    # 新页超出当前文件末尾，先扩展
                    f.seek(offset)
                    f.write(b"\x00" * PAGE_SIZE)

                f.seek(offset)
                f.write(data)

            f.flush()
            os.fsync(f.fileno())

    def print_tree(self) -> None:
        """调试用：BFS 打印整棵树的结构。"""
        from collections import deque
        q: deque[tuple[int, int]] = deque([(ROOT_PAGE_ID, 0)])
        current_level = -1
        while q:
            pid, level = q.popleft()
            if level != current_level:
                current_level = level
                print(f"\n  Level {level}:", end="")
            page = self._read_page(pid)
            print(f"  {page}", end="")
            if not page.is_leaf:
                for child_id in page.child_ids:
                    q.append((child_id, level + 1))
        print()
