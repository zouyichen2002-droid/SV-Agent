# -*- coding: utf-8 -*-
"""建造顺序第 8 项：**诊断层** —— 先测，再猜；不确定就问。

## 这一层和前七项不同：它零实测支撑

前七项做的是「把已知的东西测准」。这一层做的是**用指标猜原因** ——
而指标偏低不一定就是原因。架构文档 §6 因此给它设了三条硬约束：

    第一版只启用三条最有把握的规则   太像上一首 / 机械 / 副歌不够爆
    其余一律走「问」                 宁可多问，不要瞎改
    置信度低于下限也走「问」         confidence = 1 − 第二偏离/最偏离

**「我不知道」是一个合法的、而且经常正确的诊断结论。** 一个会说
「我不确定」的诊断层是可用的，一个自信瞎猜的不是。

## 并行假设：用测量取代排序

架构文档 §1.8 的直接后果。三个假设各自**在隔离的副本里**跑一个动作，
量完再比 —— 不是让谁去猜哪个更好。

隔离是必须的：三个动作跑在同一份工程上会互相叠加，
最后分不清哪个改善来自哪一个。这与「一个假设只准一个动作」
（`actions_per_hypothesis = 1`）是同一条理由：**归因**。

## Plan mode：先提案，再动手

`propose_before_act = True`。提案里必须写清楚：改哪一层、依据哪个数、
打算跑什么动作、期望哪个指标怎么变。**看不懂的提案等于没有提案。**
"""
from __future__ import annotations

import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .. import project as PJ
from . import metrics as MT
from . import state as ST
from . import tools as TL

# 第一版启用的三条规则。**其余一律问。**
SIMILAR, MECHANICAL, CHORUS_WEAK = "太像上一首", "机械", "副歌不够爆"

# 诉求 → 意图。没有模型时按关键词认，认不出就问。
KEYWORDS = {
    SIMILAR: ("像上一首", "太像", "撞了", "重复感", "似曾相识", "一个味"),
    MECHANICAL: ("机械", "不像人", "僵", "电音感", "生硬", "死板", "像机器"),
    CHORUS_WEAK: ("副歌不够", "副歌没", "不够爆", "不够炸", "上不去",
                  "副歌弱", "推不上", "没劲"),
}

# 意图 → 看哪些指标 · 属于哪一层 · 提什么动作
RULES = {
    CHORUS_WEAK: {
        "metrics": ("contour_lift", "dynamic_span"),
        "layer": {"contour_lift": "旋律", "dynamic_span": "调教"},
        "action": {
            "contour_lift": ("adjust_spec", {"register_shift": "副歌=+2"}),
            "dynamic_span": ("tune", {"scale": 1.4}),
        },
    },
    MECHANICAL: {
        "metrics": ("pitch_delta_density", "tuning_density"),
        "layer": {"pitch_delta_density": "调教", "tuning_density": "调教"},
        "action": {
            "pitch_delta_density": ("tune", {"scale": 1.3}),
            "tuning_density": ("tune", {"scale": 1.0}),
        },
    },
    # 太像上一首用的是 uniqueness 四维，需要参照曲。见 _similar_evidence。
}


@dataclass
class Hypothesis:
    layer: str                 # 旋律 / 和声 / 伴奏 / 调教 / 混音
    metric: str
    why: str
    deviation: float           # 偏离度：(阈值−实测)/阈值
    action: str
    params: dict = field(default_factory=dict)

    def describe(self) -> str:
        return (f"{self.layer}层　{self.why}\n"
                f"      → 跑 {self.action} {json.dumps(self.params, ensure_ascii=False)}")


@dataclass
class Diagnosis:
    complaint: str
    intent: str | None
    hypotheses: list[Hypothesis] = field(default_factory=list)
    confidence: float | None = None
    ask: str = ""              # 非空 = **不要猜，去问创作者**
    evidence: list = field(default_factory=list)

    @property
    def should_ask(self) -> bool:
        return bool(self.ask)

    def report(self) -> str:
        out = [f"诉求　「{self.complaint}」"]
        out.append(f"意图　{self.intent or '认不出来'}")
        if self.should_ask:
            out.append(f"\n**不猜，问你**：{self.ask}")
        else:
            out.append(f"置信度　{self.confidence:.2f}"
                       if self.confidence is not None else "置信度　—")
        if self.hypotheses:
            out.append(f"\n{len(self.hypotheses)} 个假设（按偏离度排）：")
            for i, h in enumerate(self.hypotheses, 1):
                out.append(f"  {i}. " + h.describe())
        if self.evidence:
            out.append("\n量到的：")
            for m in self.evidence:
                mark = {True: "✓", False: "✗", None: "·"}[m.ok]
                out.append(f"  {mark} {m.label}　{m.show()}")
        return "\n".join(out)


# =========================================================================
# 诊断
# =========================================================================

def intent_of(complaint: str) -> str | None:
    """诉求 → 意图。**认不出就返回 None**，不硬套一个最近的。"""
    hit = [k for k, words in KEYWORDS.items()
           if any(w in complaint for w in words)]
    return hit[0] if len(hit) == 1 else None


def _similar_evidence(proj):
    """「太像上一首」需要参照曲。**没有参照就老实说没有。**"""
    try:
        import sys
        sys.path.insert(0, str(MT.ROOT / "scripts"))
        sys.path.insert(0, str(MT.ROOT / "out"))
        import melody_v2 as prev
        prev.build()
        return True, "宇宙无边无垠"
    except Exception:
        return False, ""


def diagnose(proj: PJ.SongProject | None = None, complaint: str = "",
             *, floor: float = 0.5, max_hypotheses: int = 3) -> Diagnosis:
    """诉求 + 指标 → 假设。**不确定就问，这是设计而不是缺陷。**"""
    proj = proj or PJ.current()
    intent = intent_of(complaint)
    ms = MT.collect(proj)
    d = Diagnosis(complaint=complaint, intent=intent, evidence=ms)

    if intent is None:
        d.ask = ("这句话我没法可靠地对应到某一层。你指的是哪一段？"
                 "是音高太平、力度太平、还是和声？"
                 f"（第一版只敢自动诊断三类：{SIMILAR} / {MECHANICAL} / "
                 f"{CHORUS_WEAK}）")
        return d

    if intent is SIMILAR or intent == SIMILAR:
        ok, ref = _similar_evidence(proj)
        d.ask = (f"我手上没有可比的参照曲，「{SIMILAR}」判不了。"
                 "把要对比的那首指给我。" if not ok else
                 f"参照曲是《{ref}》吗？还有别的要避开的吗？")
        return d

    rule = RULES[intent]
    by_name = {m.name: m for m in ms}
    devs = []
    for name in rule["metrics"]:
        m = by_name.get(name)
        if m is None or m.ok is not False or not m.threshold:
            continue
        devs.append((m, (m.threshold - m.value) / m.threshold))
    devs.sort(key=lambda x: -x[1])

    if not devs:
        d.ask = (f"你说「{complaint}」，但{intent}对应的指标"
                 f"（{'、'.join(by_name[n].label for n in rule['metrics'] if n in by_name)}）"
                 "都在阈值以上 —— **指标看不出问题**。"
                 "是我测的维度不对，还是你指的是别的段落？")
        return d

    for m, dev in devs[:max_hypotheses]:
        act, params = rule["action"][m.name]
        d.hypotheses.append(Hypothesis(
            layer=rule["layer"][m.name], metric=m.name,
            why=f"{m.label} {m.show()}，偏低 {dev:.0%}",
            deviation=dev, action=act, params=dict(params)))

    d.confidence = 1.0 if len(devs) == 1 else 1.0 - devs[1][1] / devs[0][1]
    if d.confidence < floor:
        d.ask = (f"最像的两个原因分不开（置信度 {d.confidence:.2f} < {floor}）："
                 f"{devs[0][0].label} 与 {devs[1][0].label} 偏离得差不多。"
                 "**这种时候我不猜。** 要么你指一个，要么让我三个都试一遍再比。")
    return d


# =========================================================================
# Plan mode：先提案
# =========================================================================

def plan(d: Diagnosis) -> str:
    """提案。**看不懂的提案等于没有提案** —— 所以写清楚改哪层、依据什么数。"""
    if d.should_ask:
        return f"我不打算动手。原因：{d.ask}"
    out = [f"针对「{d.complaint}」，我打算并行试 {len(d.hypotheses)} 个假设，"
           f"**每个只改一处**（改两处就无法归因）：", ""]
    for i, h in enumerate(d.hypotheses, 1):
        out.append(f"  假设 {i}　{h.layer}层")
        out.append(f"    依据　{h.why}")
        out.append(f"    动作　{h.action} "
                   f"{json.dumps(h.params, ensure_ascii=False)}")
        out.append(f"    期望　{h.metric} 上去")
    out += ["", "三个都在**隔离的副本**里跑，量完再比 —— 真工程不动。",
            "选中的那个才会写进真工程，而且会在会话树上留节点。"]
    return "\n".join(out)


# =========================================================================
# 并行假设：在隔离副本里各跑一个动作
# =========================================================================

@dataclass
class Trial:
    hypothesis: Hypothesis
    ok: bool
    error: str = ""
    before: float | None = None
    after: float | None = None
    findings_before: int | None = None
    findings_after: int | None = None
    elapsed_s: float = 0.0

    @property
    def improvement(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before

    @property
    def regressed(self) -> bool:
        """检查项变多了就是退步。**改善不能以别处变坏为代价。**"""
        if self.findings_before is None or self.findings_after is None:
            return False
        return self.findings_after > self.findings_before


def _sandbox(proj: PJ.SongProject, tag: str):
    """把整首歌复制到隔离目录，返回一个临时 slug 的 SongProject。

    **隔离不是为了安全，是为了归因。** 三个动作跑在同一份工程上会叠加，
    最后分不清哪个改善来自哪一个。
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"svagent_{tag}_"))
    d = tmp / "song"
    d.mkdir()
    names = {}
    for attr in ("lyrics", "svp", "mid", "wav"):
        src = getattr(proj, attr)
        dst = d / src.name
        if src.exists():
            shutil.copyfile(src, dst)
        names[attr] = dst
    slug = f"_trial_{tag}_{tmp.name[-6:]}"
    cfg = PJ.SONGS / slug
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "project.json").write_text(json.dumps({
        "title": f"{proj.title}（假设 {tag}）", "svp": str(names["svp"]),
        "bpm": proj.bpm, "form": [[n, b] for n, b in proj.form],
        "lyrics": str(names["lyrics"]), "mid": str(names["mid"]),
        "wav": str(names["wav"]),
    }, ensure_ascii=False), encoding="utf-8")
    return PJ.load(slug), tmp, cfg


def _run_one(proj: PJ.SongProject, h: Hypothesis, tag: str) -> Trial:
    sb, tmp, cfg = _sandbox(proj, tag)
    try:
        before = {m.name: m for m in MT.collect(sb)}
        fb = len(ST.check_melody(sb))
        r = TL.Runner(sb, deep_metrics=False).run(h.action, h.params)
        after = {m.name: m for m in MT.collect(sb)}
        fa = len(ST.check_melody(sb))
        return Trial(h, r.ok, r.error,
                     before.get(h.metric).value if before.get(h.metric) else None,
                     after.get(h.metric).value if after.get(h.metric) else None,
                     fb, fa, r.elapsed_s)
    except Exception as e:
        return Trial(h, False, f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(cfg, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def trial(proj: PJ.SongProject, hypotheses: list[Hypothesis], *,
          parallel: bool = True) -> list[Trial]:
    """每个假设在自己的副本里跑一个动作。→ 按改善排序。"""
    tags = [f"h{i + 1}" for i in range(len(hypotheses))]
    if parallel and len(hypotheses) > 1:
        with ThreadPoolExecutor(max_workers=len(hypotheses)) as ex:
            out = list(ex.map(lambda a: _run_one(proj, a[0], a[1]),
                              zip(hypotheses, tags)))
    else:
        out = [_run_one(proj, h, t) for h, t in zip(hypotheses, tags)]
    return sorted(out, key=lambda t: (t.regressed,
                                      -(t.improvement or -1e9)))


def pick(trials: list[Trial], *, min_improvement: float = 0.15) -> Trial | None:
    """选一个真的变好、而且没让别处变坏的。**都没达标就返回 None。**

    `require_no_regression = True`（架构 §8）：检查项变多的一律出局，
    哪怕目标指标涨了 —— 这条在 `repair.py` 上已经被 24 次扫描验证过。
    """
    for t in trials:
        if not t.ok or t.regressed:
            continue
        imp = t.improvement
        if imp is not None and imp >= min_improvement:
            return t
    return None


def report_trials(trials: list[Trial]) -> str:
    out = ["三个假设并排（真工程未动）：", ""]
    for i, t in enumerate(trials, 1):
        h = t.hypothesis
        mark = "✗" if (not t.ok or t.regressed) else "✓"
        out.append(f"  {mark} {h.layer}层　{h.action} "
                   f"{json.dumps(h.params, ensure_ascii=False)}　{t.elapsed_s:.0f}s")
        if not t.ok:
            out.append(f"      跑不通：{t.error[:120]}")
            continue
        if t.improvement is None:
            out.append(f"      {h.metric} 量不到")
        else:
            out.append(f"      {h.metric}　{t.before:g} → {t.after:g}"
                       f"（{t.improvement:+g}）")
        if t.regressed:
            out.append(f"      **退步**：检查项 {t.findings_before} → "
                       f"{t.findings_after}，出局")
    return "\n".join(out)


# =========================================================================
# 报告：仪表盘读它，自己不跑诊断
# =========================================================================

REPORT_PATH = Path(__file__).resolve().parents[3] / ".agent" / "diagnosis.json"


def save_report(d: Diagnosis, trials: list[Trial] | None = None,
                chosen: Trial | None = None, path: Path | None = None) -> Path:
    """把这一轮落盘。**仪表盘不跑诊断** —— 诊断要跑真动作，几十秒起步，
    而仪表盘每次文件变动都会重新生成。同第 4 项那次的教训。
    """
    import time

    from . import safewrite as SW
    p = Path(path or REPORT_PATH)
    SW.write_json(p, {
        "ts": time.time(), "complaint": d.complaint, "intent": d.intent,
        "ask": d.ask, "confidence": d.confidence,
        "hypotheses": [{"layer": h.layer, "metric": h.metric, "why": h.why,
                        "action": h.action, "params": h.params,
                        "deviation": round(h.deviation, 4)}
                       for h in d.hypotheses],
        "trials": [{"layer": t.hypothesis.layer, "metric": t.hypothesis.metric,
                    "action": t.hypothesis.action, "ok": t.ok,
                    "error": t.error[:200], "before": t.before,
                    "after": t.after, "improvement": t.improvement,
                    "regressed": t.regressed,
                    "findings_before": t.findings_before,
                    "findings_after": t.findings_after,
                    "elapsed_s": round(t.elapsed_s, 1)}
                   for t in (trials or [])],
        "chosen": (None if chosen is None else
                   {"layer": chosen.hypothesis.layer,
                    "action": chosen.hypothesis.action,
                    "metric": chosen.hypothesis.metric,
                    "improvement": chosen.improvement}),
    })
    return p


def load_report(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or REPORT_PATH).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
