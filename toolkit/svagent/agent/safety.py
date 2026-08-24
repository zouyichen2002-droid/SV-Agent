# -*- coding: utf-8 -*-
"""第 1 项的观察函数：五盏灯现在什么颜色。

## 为什么单独一个模块

`state.inspect()` 回答「这首歌走到第几步」，这里回答「这套机制现在安不安全」。
两者都是**观察**，都从文件现算、不缓存，但问的是不同的问题。
合进一个函数会让六步状态和五盏灯互相牵连 —— 歌没写完不代表写入机制不安全。

## 灯有三色，不是两色

    绿   有依据说它是好的
    红   有依据说它出问题了
    灰   **还没有可判断的依据**

第三种是必须的。`fl_ping` 那次我把「拿不到心跳」当成「配置错了」，
让创作者去修一个不存在的问题。**「不知道」要画成「不知道」**，
不许拿一盏绿灯冒充。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import project as PJ
from . import budget as BD
from . import checkpoint as CP
from . import safewrite as SW

# 建造顺序第 1 项的五件事，顺序与架构文档一致
LAMP_ORDER = ("原子写", "哈希校验", "全套快照", "可中断", "循环超时")

# 校验结果的中文说法。**放在库里**，这样 CLI 和仪表盘说的是同一句话 ——
# 两个前端各自翻译，迟早出现「一个说被改了、一个说没取基线」。
VERDICT_ZH = {
    SW.CLEAN: "与我上次写入一致",
    SW.EXTERNAL: "被外部修改",
    SW.UNTRACKED: "没取过基线",
    SW.MISSING: "不存在",
}


@dataclass
class Lamp:
    name: str
    ok: bool | None          # True 绿 / False 红 / None 灰
    detail: str
    hint: str = ""           # 红灯时该怎么办

    @property
    def color(self) -> str:
        return "on" if self.ok else ("off" if self.ok is False else "unknown")


@dataclass
class SafetyState:
    proj: PJ.SongProject
    lamps: list[Lamp]
    files: list[tuple[Path, str]] = field(default_factory=list)
    checkpoints: list[CP.Manifest] = field(default_factory=list)

    @property
    def worst(self) -> str:
        if any(l.ok is False for l in self.lamps):
            return "off"
        return "on" if all(l.ok for l in self.lamps) else "unknown"

    def report(self) -> str:
        mark = {"on": "✓", "off": "✗", "unknown": "·"}
        out = []
        for l in self.lamps:
            out.append(f"  {mark[l.color]} {l.name}　{l.detail}")
            if l.hint:
                out.append(f"      → {l.hint}")
        return "\n".join(out)


def guard_of(proj: PJ.SongProject) -> SW.Guard:
    return SW.Guard(proj.agent_dir / "ledger.json")


def store_of(proj: PJ.SongProject) -> CP.Store:
    return CP.Store(proj.agent_dir / "checkpoints", guard=guard_of(proj))


def autosnap(proj: PJ.SongProject, why: str) -> CP.Manifest:
    """任何**可能丢失当前内容**的操作之前，先拍一张。

    去重让这几乎免费（内容没变就是 0 字节增量），
    而「回滚把我还没存过的改动冲掉了」是不可逆的。
    这条不对称就是这个函数存在的全部理由。
    """
    return store_of(proj).snapshot(proj.sources, label=f"自动 · {why}")


def rollback(proj: PJ.SongProject, cid: str):
    """回滚到某个快照。**先把当前状态存下来**，再覆盖。

    → (自动快照, 实际写回的文件)
    """
    snap = autosnap(proj, f"回滚到 {cid} 之前")
    return snap, store_of(proj).restore(cid)


def adopt(proj: PJ.SongProject):
    """把当前内容记成基线。**有外部改动时先自动拍快照并如实报告。**

    → (被采纳的外部改动, 自动快照或 None, 记了几个文件)

    `--adopt` 是唯一会销毁「这个文件被外部改过」这个信号的操作。
    所以它必须说清楚自己在采纳什么 —— 否则创作者跑完它，
    就再也没有机会知道刚才发生过什么。
    """
    g = guard_of(proj)
    ext = [p for p, v in g.status(proj.sources) if v == SW.EXTERNAL]
    snap = autosnap(proj, "采纳外部改动之前") if ext else None
    n = 0
    for f in proj.sources:
        if f.exists():
            g.record(f)
            n += 1
    return ext, snap, n


def watched_dirs(proj: PJ.SongProject) -> list[Path]:
    """临时文件可能落在哪 —— 就是我们会写入的每个目录。"""
    return sorted({p.parent for p in proj.sources} | {proj.agent_dir})


def inspect(proj: PJ.SongProject | None = None,
            budget: BD.Budget | None = None) -> SafetyState:
    proj = proj or PJ.current()
    guard, store = guard_of(proj), store_of(proj)
    lamps: list[Lamp] = []

    # ---- 1 原子写 ----------------------------------------------------
    junk = SW.stale_tmps(watched_dirs(proj))
    lamps.append(Lamp(
        "原子写", not junk,
        "无残留临时文件" if not junk else f"{len(junk)} 个崩溃残留",
        "" if not junk else f"跑 safety.py --sweep 清掉：{junk[0].name} …"))

    # ---- 2 哈希校验 --------------------------------------------------
    files = guard.status(proj.sources)
    ext = [p for p, v in files if v == SW.EXTERNAL]
    tracked = [p for p, v in files if v == SW.CLEAN]
    if ext:
        lamps.append(Lamp(
            "哈希校验", False,
            f"{len(ext)} 个文件被外部修改：" + "、".join(p.name for p in ext),
            "我不会覆盖它们。确认你的改动要保留就跑 --adopt 重新取基线；"
            "要丢掉就先回滚。"))
    elif tracked:
        lamps.append(Lamp("哈希校验", True,
                          f"{len(tracked)} 个文件与我上次写入一致"))
    else:
        lamps.append(Lamp("哈希校验", None, "还没有任何文件取过基线",
                          "跑 safety.py --adopt 把当前内容记成基线"))

    # ---- 3 全套快照 --------------------------------------------------
    cps = store.list()
    if cps:
        logical = sum(m.total_bytes for m in cps)
        actual = store.blob_bytes()
        saved = 1 - actual / logical if logical else 0.0
        lamps.append(Lamp(
            "全套快照", True,
            f"{len(cps)} 个快照　实占 {actual / 1e6:.0f} MB／"
            f"逻辑 {logical / 1e6:.0f} MB　去重省了 {saved:.0%}"))
    else:
        lamps.append(Lamp("全套快照", None, "还没有快照",
                          "跑 safety.py --snapshot 拍一个"))

    # ---- 4 可中断 ----------------------------------------------------
    stop = proj.stop_file
    lamps.append(Lamp(
        "可中断", not stop.exists(),
        "未请求停止" if not stop.exists() else "你已请求停止",
        "" if not stop.exists() else f"删掉 {stop.name} 或跑 --resume 才会继续"))

    # ---- 5 循环超时 --------------------------------------------------
    # **没有循环在跑的时候，这盏灯只能是灰的。** 机制已实现、测试已过，
    # 但「它现在有没有在守着预算」这件事此刻无从判断 —— 不许拿绿灯冒充。
    if budget is not None:
        s = budget.status()
        lamps.append(Lamp("循环超时", s["remaining"] > 0,
                          f"已用 {s['elapsed']:.0f}s／{s['seconds']:.0f}s　"
                          f"动作 {s['n_actions']}／{s['max_actions']}"))
    else:
        lamps.append(Lamp(
            "循环超时", None,
            f"没有循环在跑（默认 {BD.Budget.seconds:.0f}s／"
            f"{BD.Budget.max_actions} 个动作）",
            "第 5 项把工具层接上之后这盏灯才会亮"))

    return SafetyState(proj=proj, lamps=lamps, files=files, checkpoints=cps)
