# -*- coding: utf-8 -*-
"""建造顺序第 1 项的第三件：**checkpoint 全套快照 + blobs 去重**。

## 为什么必须是「全套」，不是「只存改动的」

会话树（第 3 项）要能 checkout 到任意节点。如果 checkpoint 只存
「这一步改了的文件」，checkout 一个旧节点时，没被这一步改过的文件会保持
**当前**内容 —— 于是得到一个从未真实存在过的混合状态，而且不报错。

这和原子写是同一类问题：**不完整，但看起来完整。**
所以两件必须一起做，这也是它们同属第 1 项的原因。

## 去重让「全套」变得便宜

伴奏 wav 33 MB。真按「全套 = 全拷」，几十个 checkpoint 就是几个 GB。
但它在整个创作过程里只会变几次。所以按内容寻址：

    blobs/<hash 前2位>/<hash>     同样的内容只存一份
    <cid>.json                    manifest：文件名 → 哈希

第二次快照如果什么都没改，增量是 0 字节。

## restore 也走原子写，并且更新账本

回滚是写文件。写文件就必须原子，否则 checkout 到一半崩掉会毁掉工程。
而且回滚之后这些文件确实是 agent 写的，账本要跟上 ——
否则下一次写入会误判成「创作者改过」。
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import safewrite as SW


@dataclass
class Manifest:
    cid: str
    ts: float
    label: str
    note: str
    files: dict          # 文件绝对路径 → {"hash":…, "size":…}

    @property
    def when(self) -> str:
        return time.strftime("%m-%d %H:%M:%S", time.localtime(self.ts))

    @property
    def total_bytes(self) -> int:
        return sum(f["size"] for f in self.files.values())

    def describe(self) -> str:
        return (f"{self.cid}　{self.when}　{len(self.files)} 个文件 "
                f"{self.total_bytes / 1e6:.1f} MB"
                + (f"　{self.label}" if self.label else ""))


@dataclass
class Store:
    """一首歌的 checkpoint 仓库。"""

    root: Path
    guard: SW.Guard | None = None
    _blobs: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self._blobs = self.root / "blobs"

    # ---- blob 层 -----------------------------------------------------
    def _blob_path(self, h: str) -> Path:
        return self._blobs / h[:2] / h

    def put(self, path: Path) -> str | None:
        """把一个文件收进 blob 库。→ 内容哈希。已存在就不重复写。"""
        h = SW.digest(path)
        if h is None:
            return None
        dst = self._blob_path(h)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            # 先落临时文件再 replace —— blob 库里不许出现半个文件，
            # 否则它会顶着一个正确的哈希名，而内容是残缺的
            tmp = dst.with_name(dst.name + SW.TMP_SUFFIX)
            shutil.copyfile(path, tmp)
            tmp.replace(dst)
        return h

    def blob_count(self) -> int:
        return sum(1 for _ in self._blobs.rglob("*")
                   if _.is_file() and SW.TMP_SUFFIX not in _.name)

    def blob_bytes(self) -> int:
        return sum(f.stat().st_size for f in self._blobs.rglob("*")
                   if f.is_file() and SW.TMP_SUFFIX not in f.name)

    # ---- manifest 层 -------------------------------------------------
    def _next_cid(self) -> str:
        n = len(list(self.root.glob("c*.json")))
        return f"c{n + 1:03d}"

    def snapshot(self, paths, *, label: str = "", note: str = "") -> Manifest:
        """把给的这批文件**全部**收一遍。不存在的文件如实记成缺失。"""
        self.root.mkdir(parents=True, exist_ok=True)
        files: dict = {}
        for p in paths:
            p = Path(p)
            h = self.put(p)
            if h is None:
                files[str(p)] = {"hash": None, "size": 0}
            else:
                files[str(p)] = {"hash": h, "size": p.stat().st_size}
        m = Manifest(self._next_cid(), time.time(), label, note, files)
        SW.write_json(self.root / f"{m.cid}.json", {
            "cid": m.cid, "ts": m.ts, "label": m.label,
            "note": m.note, "files": m.files})
        return m

    def load(self, cid: str) -> Manifest:
        d = json.loads((self.root / f"{cid}.json").read_text("utf-8"))
        return Manifest(d["cid"], d["ts"], d.get("label", ""),
                        d.get("note", ""), d["files"])

    def list(self) -> list[Manifest]:
        return [self.load(p.stem) for p in sorted(self.root.glob("c*.json"))]

    def restore(self, cid: str) -> list[Path]:
        """把 manifest 里的每个文件写回去。→ 实际写了哪些。

        **manifest 里记成缺失的文件，会被删掉。** 留着它等于回到一个
        「当时没有、现在有」的混合状态 —— 正是全套快照要防的那件事。
        """
        m = self.load(cid)
        touched: list[Path] = []
        for s, rec in m.files.items():
            p = Path(s)
            if rec["hash"] is None:
                if p.exists():
                    p.unlink()
                    if self.guard:
                        self.guard.forget(p)
                    touched.append(p)
                continue
            blob = self._blob_path(rec["hash"])
            if not blob.exists():
                raise FileNotFoundError(f"{cid} 引用的 blob 不见了：{rec['hash']}")
            if SW.digest(p) == rec["hash"]:
                continue                      # 已经是这个内容，不动
            SW.write_bytes(p, blob.read_bytes())
            if self.guard:
                self.guard.record(p)
            touched.append(p)
        return touched
