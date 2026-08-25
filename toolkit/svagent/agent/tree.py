# -*- coding: utf-8 -*-
"""建造顺序第 3 项：**会话树** —— journal + HEAD + checkout + 裁决。

创作者 2026-08-23 拍板进第一版。他推翻了我「先做线性回退」的建议，而且他对 ——
我漏看了一个协同效应：

> **做了树，否决记忆的数据结构就自然有了。**
> 每个打了 `rejected` 的分支就是一条负样本，带完整规格特征 + 他的原话。

## 树几乎是免费的，因为难的部分已经在第 1 项做完了

真正的难点从来不是树，是 **checkpoint 的完整性**：一个节点必须能完整恢复
项目状态。只快照 `.svp` 的话，切回旧节点时 `lyrics.txt` 还是别的分支的 ——
状态不一致，而且不报错。第 1 项的全套快照已经解决了它。

所以这一层只剩三件事：一个 `HEAD` 指针、一个 `checkout`、
以及「HEAD 不在叶子上时提交，自然产生分支」。

**与架构文档 §6.5 的一处偏离**：文档说小文件全量复制、只有 wav 走内容寻址。
实现里 `checkpoint.Store` 对**所有**文件都内容寻址 —— 同样的完整性，
少一套按大小分流的特例，实测去重 80%。

## 只追加是**语义上**的，落盘用原子整写

历史不许被改写：`label` 和 `verdict` 不去修改原来那一行，而是**追加一条修订记录**，
读的时候重放。这样任何一行写下去就永远是那个样子。

但落盘不用 `open("a")`。日志只有几 KB，整份原子重写更安全 ——
追加时若中途崩掉，最后一行会是半截 JSON，而「跳过读不懂的最后一行」
是一种安静的数据丢失。这正是第 1 项要防的东西，不能在第 3 项又引进来。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import project as PJ
from . import checkpoint as CP
from . import safewrite as SW

ACCEPTED = "accepted"
REJECTED = "rejected"
VERDICTS = (ACCEPTED, REJECTED)


@dataclass
class Node:
    id: str
    parent: str | None
    ts: float
    label: str                       # **硬要求**：一堆 n0041 对创作者毫无意义
    action: str = ""
    params: dict = field(default_factory=dict)
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)
    verdict: str | None = None
    verdict_note: str = ""
    spec_snapshot: dict = field(default_factory=dict)
    checkpoint: str = ""             # checkpoint.Store 的 cid

    @property
    def when(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.ts))

    @property
    def mark(self) -> str:
        return {ACCEPTED: "✓", REJECTED: "✗"}.get(self.verdict, "·")


class TreeError(Exception):
    pass


@dataclass
class Tree:
    """一首歌的会话树。所有状态都在 `proj.agent_dir` 里的文件上。"""

    proj: PJ.SongProject

    @property
    def _dir(self) -> Path:
        return self.proj.agent_dir

    @property
    def journal_path(self) -> Path:
        return self._dir / "journal.jsonl"

    @property
    def head_path(self) -> Path:
        return self._dir / "HEAD"

    @property
    def store(self) -> CP.Store:
        return CP.Store(self._dir / "checkpoints",
                        guard=SW.Guard(self._dir / "ledger.json"))

    # ---- 日志读写 ----------------------------------------------------
    def _lines(self) -> list[dict]:
        try:
            raw = self.journal_path.read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for i, ln in enumerate(raw.splitlines(), 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError as e:
                # **不许静默跳过。** 读不懂的一行意味着历史坏了，
                # 而带着一半历史继续跑，比停下来更坏。
                raise TreeError(f"{self.journal_path} 第 {i} 行读不懂：{e}")
        return out

    def _append(self, rec: dict) -> None:
        lines = self._lines() + [rec]
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines)
        SW.write_text(self.journal_path, body)

    def n_lines(self) -> int:
        """日志行数。**必须单调增** —— 这是「只追加」的可测形式。"""
        return len(self._lines())

    # ---- 节点 --------------------------------------------------------
    def nodes(self) -> list[Node]:
        """重放日志得到当前的节点表（含修订）。"""
        by_id: dict[str, Node] = {}
        for rec in self._lines():
            if "amend" in rec:
                nd = by_id.get(rec["amend"])
                if nd is None:
                    raise TreeError(f"修订指向不存在的节点 {rec['amend']}")
                for k, v in rec.items():
                    if k != "amend":
                        setattr(nd, k, v)
            else:
                by_id[rec["id"]] = Node(**rec)
        return list(by_id.values())

    def node(self, nid: str) -> Node:
        for nd in self.nodes():
            if nd.id == nid:
                return nd
        raise TreeError(f"没有节点 {nid}")

    def children(self, nid: str | None) -> list[Node]:
        return [n for n in self.nodes() if n.parent == nid]

    def roots(self) -> list[Node]:
        return self.children(None)

    def leaves(self) -> list[Node]:
        parents = {n.parent for n in self.nodes()}
        return [n for n in self.nodes() if n.id not in parents]

    def rejected(self) -> list[Node]:
        """否决记忆的原料：每个被否掉的分支 + 创作者的原话。"""
        return [n for n in self.nodes() if n.verdict == REJECTED]

    # ---- HEAD --------------------------------------------------------
    def head(self) -> str | None:
        try:
            return self.head_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _set_head(self, nid: str | None) -> None:
        SW.write_text(self.head_path, (nid or "") + "\n")

    # ---- 操作 --------------------------------------------------------
    def _next_id(self) -> str:
        return f"n{len(self.nodes()) + 1:04d}"

    def commit(self, label: str, *, action: str = "", params: dict | None = None,
               metrics_before: dict | None = None,
               metrics_after: dict | None = None,
               spec_snapshot: dict | None = None) -> Node:
        """给当前文件状态拍一个节点。父节点 = 当前 HEAD。

        **分支是隐式的**：HEAD 不在叶子上时提交，自然长出一个新分支。
        没有 `branch` 命令，因为不需要。
        """
        if not label.strip():
            raise TreeError("节点必须有可读的 label —— 一堆 n0041 无法导航")
        self._dir.mkdir(parents=True, exist_ok=True)
        parent = self.head()
        nid = self._next_id()
        m = self.store.snapshot(self.proj.sources, label=f"{nid} {label}")
        nd = Node(id=nid, parent=parent, ts=time.time(), label=label.strip(),
                  action=action, params=params or {},
                  metrics_before=metrics_before or {},
                  metrics_after=metrics_after or {},
                  spec_snapshot=spec_snapshot or {}, checkpoint=m.cid)
        self._append(asdict(nd))
        self._set_head(nid)
        return nd

    def checkout(self, nid: str) -> list[Path]:
        """恢复那个节点的全套文件，移动 HEAD。→ 实际写回了哪些文件。

        **切走之前先给当前状态留一个节点**，条件是当前状态与 HEAD 不一致。
        否则一次 checkout 就会无声地冲掉还没提交的改动 —— 与第 1 项
        `--restore` 那条不变量同源。
        """
        nd = self.node(nid)
        if self.is_dirty():
            self.commit("切走之前自动保存", action="autosave")
        touched = self.store.restore(nd.checkpoint)
        self._set_head(nid)
        return touched

    def is_dirty(self) -> bool:
        """当前文件与 HEAD 那个节点的快照是否不同。没有 HEAD 时视为不脏。"""
        h = self.head()
        if h is None:
            return False
        m = self.store.load(self.node(h).checkpoint)
        for s, rec in m.files.items():
            if SW.digest(Path(s)) != rec["hash"]:
                return True
        return False

    def label(self, nid: str, text: str) -> None:
        self.node(nid)                       # 不存在就抛
        if not text.strip():
            raise TreeError("label 不能为空")
        self._append({"amend": nid, "label": text.strip()})

    def annotate(self, nid: str, **fields) -> None:
        """给节点补记信息（度量、改动高亮等）。**同样是追加修订，不改写历史。**

        动作执行时节点必须先建好（否则失败了就没东西可回退），
        但「改完之后的度量」要等动作跑完才有 —— 所以补记。
        """
        self.node(nid)
        allowed = {"metrics_after", "spec_snapshot", "params", "label"}
        bad = set(fields) - allowed
        if bad:
            raise TreeError(f"不允许补记这些字段：{sorted(bad)}")
        self._append({"amend": nid, **fields})

    def verdict(self, nid: str, v: str, note: str = "") -> None:
        """记录裁决。**这是否决记忆的写入口。**"""
        self.node(nid)
        if v not in VERDICTS:
            raise TreeError(f"裁决只能是 {VERDICTS} 之一，收到 {v!r}")
        self._append({"amend": nid, "verdict": v, "verdict_note": note.strip()})

    # ---- 画树 --------------------------------------------------------
    def ascii(self) -> str:
        head = self.head()
        out: list[str] = []

        def walk(nd: Node, prefix: str, last: bool, top: bool) -> None:
            branch = "" if top else ("└─" if last else "├─")
            here = " ← HEAD" if nd.id == head else ""
            note = f"　「{nd.verdict_note}」" if nd.verdict_note else ""
            out.append(f"{prefix}{branch}{nd.mark} {nd.id}  {nd.label}"
                       f"　{nd.when}{note}{here}")
            kids = self.children(nd.id)
            nxt = prefix + ("" if top else ("　　" if last else "│　"))
            for i, k in enumerate(kids):
                walk(k, nxt, i == len(kids) - 1, False)

        for r in self.roots():
            walk(r, "", True, True)
        return "\n".join(out) or "（树是空的，还没有任何节点）"
