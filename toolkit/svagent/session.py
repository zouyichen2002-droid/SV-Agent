# -*- coding: utf-8 -*-
"""建造顺序第 9 项：**库边界** —— 一个 `Session`，所有能力挂在它上面。

## 为什么要这一层

架构文档 §11 第 9 项的原话：**让「换 orchestrator」变成换前端。**

在它之前，六个入口脚本各自 `sys.path.insert` + 直接 import 那七八个
agent 模块。每加一个前端（第 10 项的 Mistral 循环、将来的 Web、
Claude Code 的斜杠命令）都要把这套拼装重来一遍 ——
而拼装重来一遍就是「两个实现」的温床，这个项目已经栽过五次。

所以收成一个对象：

    s = Session()            # 或 Session("xiaofeng")
    s.state()  s.safety()  s.metrics()  s.facts()  s.tree()
    s.act(...)  s.diagnose(...)  s.trial(...)  s.dashboard()

**前端只准调这些方法。** 前端之间的差别只应该是「怎么显示」，
不应该是「算的是什么」。

## 每个方法都必须能序列化

因为验收判据是「同一操作经库调用与经 CLI 调用结果相同」。
不能序列化就没法比 —— 所以每样东西都配一个 `to_json()`，
CLI 的 `--json` 直接打印它。**这不是为了好看，是为了可验证。**

## Session 不缓存任何东西

`state()` 每次现算，`metrics()` 每次现算。和 `state.inspect` 那条规则
一样：真相在文件里。一个会缓存的 Session 就是又一个会漂移的真相源。
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from . import dashboard as DB
from . import project as PJ
from .agent import budget as BD
from .agent import diagnose as DG
from .agent import facts as FA
from .agent import metrics as MT
from .agent import safety as SF
from .agent import state as ST
from .agent import tools as TL
from .agent import tree as TR


class Session:
    """一首歌的一次工作会话。**唯一的公开入口。**"""

    def __init__(self, slug: str | None = None, *,
                 budget: BD.Budget | None = None):
        self.proj = PJ.load(slug) if slug else PJ.current()
        self.budget = budget or BD.Budget(stop_file=self.proj.stop_file)

    # ---- 观察（每次现算，不缓存） -------------------------------------
    def state(self) -> ST.ProjectState:
        return ST.inspect(self.proj)

    def safety(self) -> SF.SafetyState:
        return SF.inspect(self.proj, budget=self.budget)

    def metrics(self) -> list[MT.Metric]:
        return MT.collect(self.proj)

    def facts(self) -> list[FA.Result]:
        """约束清单。**读报告，不跑复验。**

        观察和动作要分开：复验会 spawn 子进程、写 200 次文件、
        而且 mtime 那条本身带随机性（73/100 vs 77/100）——
        把它塞进「观察」会让**同一次观察两次结果不同**，
        于是「库与 CLI 结果相同」这条判据永远过不了。

        仪表盘早就是读报告的。这里跟它统一 ——
        两个前端看的必须是同一个东西，这正是这一层存在的理由。
        """
        return FA.results_from_report()

    def verify_facts(self, costs=(FA.FAST,)) -> list[FA.Result]:
        """真的去复验一遍并落盘。**这是动作，不是观察。**"""
        rs = FA.verify(costs=costs)
        FA.save_report(rs)
        return rs

    def checks(self):
        return ST.check_melody(self.proj)

    @property
    def tree(self) -> TR.Tree:
        return TR.Tree(self.proj)

    # ---- 动作 --------------------------------------------------------
    def actions(self) -> list[TL.Action]:
        return TL.ACTIONS

    def tools_for_model(self) -> list[dict]:
        """第 10 项要的 tools 数组。**前端不自己拼 schema。**"""
        return TL.to_mistral_tools()

    def act(self, name: str, params: dict | None = None) -> TL.ToolResult:
        return TL.Runner(self.proj, budget=self.budget).run(name, params)

    def ask(self, text: str, *, auto_rounds: int = 1,
            max_actions: int = 8, client=None):
        """**模型驱动的一轮。** 第 10 项的入口，也是最后一个前端。

        它和别的方法一样只是 Session 的一个方法 —— 这正是第 9 项
        「换 orchestrator 就是换前端」那句话的兑现。
        """
        from .agent import loop as LP
        return LP.run(self, text, client=client, auto_rounds=auto_rounds,
                      max_actions=max_actions, budget=self.budget)

    def llm_usage(self) -> dict:
        """模型用量。**读报告** —— 观察不发请求。"""
        from . import llm as LM
        return LM.load_usage()

    # ---- 诊断 --------------------------------------------------------
    def diagnose(self, complaint: str, *, floor: float = 0.5) -> DG.Diagnosis:
        return DG.diagnose(self.proj, complaint, floor=floor)

    def plan(self, d: DG.Diagnosis) -> str:
        return DG.plan(d)

    def trial(self, hypotheses, *, parallel: bool = True) -> list[DG.Trial]:
        return DG.trial(self.proj, hypotheses, parallel=parallel)

    # ---- 会话树 ------------------------------------------------------
    def commit(self, label: str, **kw) -> TR.Node:
        return self.tree.commit(label, **kw)

    def checkout(self, node_id: str) -> list[Path]:
        return self.tree.checkout(node_id)

    def verdict(self, node_id: str, v: str, note: str = "") -> None:
        self.tree.verdict(node_id, v, note)

    # ---- 前端产物 ----------------------------------------------------
    def dashboard(self, *, live: bool = False) -> Path:
        return DB.write(self.state(), refresh_s=5, live=live)

    # ---- 序列化：**验收判据靠它** -------------------------------------
    def to_json(self, what: str) -> dict:
        """把一次观察序列化。CLI 的 `--json` 直接打印这个。

        判据是「同一操作经库调用与经 CLI 调用结果相同」——
        不能序列化就没法比。
        """
        if what == "state":
            st = self.state()
            return {"slug": self.proj.slug, "title": self.proj.title,
                    "n_done": st.n_done,
                    "steps": [{"n": s.n, "name": s.name, "who": s.who,
                               "done": s.done, "evidence": list(s.evidence),
                               "blockers": list(s.blockers),
                               "waits_for": s.waits_for} for s in st.steps]}
        if what == "safety":
            sf = self.safety()
            return {"worst": sf.worst,
                    "lamps": [{"name": l.name, "ok": l.ok,
                               "detail": l.detail, "hint": l.hint}
                              for l in sf.lamps],
                    "files": [[p.name, v] for p, v in sf.files]}
        if what == "metrics":
            return {"metrics": [{"name": m.name, "label": m.label,
                                 "value": m.value, "threshold": m.threshold,
                                 "ok": m.ok, "detail": m.detail}
                                for m in self.metrics()]}
        if what == "facts":
            return {"facts": [{"id": r.fact.id, "ok": r.ok,
                               "detail": r.detail} for r in self.facts()]}
        if what == "tree":
            t = self.tree
            return {"head": t.head(), "dirty": t.is_dirty(),
                    "nodes": [asdict(n) for n in t.nodes()]}
        if what == "actions":
            return {"actions": [{"name": a.name, "status": a.status,
                                 "writes": a.writes, "hooks": list(a.hooks),
                                 "schema": a.schema} for a in self.actions()]}
        if what == "checks":
            return {"findings": [{"kind": f.kind, "severity": f.severity,
                                  "where": f.where, "detail": f.detail}
                                 for f in self.checks()]}
        raise ValueError(f"不认识的 what={what!r}。可用："
                         "state / safety / metrics / facts / tree / "
                         "actions / checks")


def diagnosis_json(d: DG.Diagnosis) -> dict:
    """诊断的序列化。**放在库里** —— 两个前端各写一遍必然分叉。"""
    return {"complaint": d.complaint, "intent": d.intent,
            "ask": d.ask, "confidence": d.confidence,
            "hypotheses": [{"layer": h.layer, "metric": h.metric,
                            "why": h.why, "action": h.action,
                            "params": h.params,
                            "deviation": round(h.deviation, 6)}
                           for h in d.hypotheses]}


def trials_json(ts: list[DG.Trial]) -> dict:
    return {"trials": [{"layer": t.hypothesis.layer,
                        "action": t.hypothesis.action,
                        "metric": t.hypothesis.metric, "ok": t.ok,
                        "before": t.before, "after": t.after,
                        "improvement": t.improvement,
                        "regressed": t.regressed} for t in ts]}
