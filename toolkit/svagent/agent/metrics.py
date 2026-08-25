# -*- coding: utf-8 -*-
"""建造顺序第 7 项：**诊断的原料** —— 把「太平」变成可测的数。

## 为什么 `contour_range` 与 `dynamic_span` 必须分开

架构文档 §6：**「音高平」和「力度平」修法不同** ——
前者改 `spec.register` 或轮廓，后者改 `TuneCfg`。合成一个数就无法归因，
而归因正是诊断层存在的理由。

## 阈值是**实测校准**出来的，不是拍的

《晓风残月》已经通过创作者验收、其余八项 0 finding。任何把它判为
「太平」的阈值都是错的 —— 那不是严格，是假阳性。实测：

    全曲极差        15 半音
    每句极差中位    3 半音        ← 副歌句内只有 3，看着很「平」
    副歌−主歌音区   +10.5 半音    ← 但整段抬高了 10.5，所以并不平
    响度曲线跨度    4.60 dB

**副歌句内极差只有 3 却不平**，说明这首歌的起伏来自音区抬升而不是
句内轮廓。所以三个子指标都要报，不能只报一个 ——
只看句内极差会把它误判成平。

## 三色，不是两色

调教还没写的时候，`dynamic_span` 是 **None（不知道）**，不是 0（很平）。
这跟安全面板的灰灯是同一条：不许拿一个数字冒充「我知道」。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import project as PJ

ROOT = Path(__file__).resolve().parents[3]

MIN, MAX = "min", "max"


@dataclass
class Metric:
    name: str
    label: str
    value: float | None                # None = 还没有可判断的依据
    threshold: float | None
    unit: str = ""
    direction: str = MIN               # min = 低于阈值就报警
    means: str = ""                    # 这个数不达标意味着什么、该改哪
    detail: str = ""

    @property
    def ok(self) -> bool | None:
        if self.value is None or self.threshold is None:
            return None
        return (self.value >= self.threshold if self.direction == MIN
                else self.value <= self.threshold)

    @property
    def color(self) -> str:
        return "on" if self.ok else ("off" if self.ok is False else "unknown")

    def show(self) -> str:
        if self.value is None:
            return "—"
        v = f"{self.value:.2f}".rstrip("0").rstrip(".")
        t = ("" if self.threshold is None
             else f"（{'≥' if self.direction == MIN else '≤'} {self.threshold:g}）")
        return f"{v}{self.unit}{t}"


def _lead(proj: PJ.SongProject):
    """读回主旋律与段落结构。**用 step3 那一个实现，不重写。**"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import step3_melody as S3

    from ..compose.lyricfile import parse
    vs, _probs = parse(proj.lyrics)
    ver = vs[next(iter(vs))]
    return S3.read_lead(proj.svp, ver, proj.form), ver


# =========================================================================
# contour_range —— 音高的起伏
# =========================================================================

def contour(proj: PJ.SongProject) -> list[Metric]:
    try:
        (_name, notes, sections), _ver = _lead(proj)
    except Exception as e:
        return [Metric("contour_range", "音高起伏", None, None,
                       detail=f"读不到主旋律：{type(e).__name__}")]
    if len(notes) < 2:
        return [Metric("contour_range", "音高起伏", None, None,
                       detail="音符太少")]

    allp = [n.midi for n in notes]
    line_ranges, sec_pitch, idx = [], {}, 0
    for sec, _bar, lines in sections:
        for _text, syls, _chord in lines:
            seg = notes[idx: idx + len(syls)]
            idx += len(syls)
            if len(seg) >= 2:
                ps = [n.midi for n in seg]
                line_ranges.append(max(ps) - min(ps))
                sec_pitch.setdefault(sec, []).extend(ps)

    def med_of(prefix):
        vals = [st.median(ps) for k, ps in sec_pitch.items()
                if k.startswith(prefix)]
        return st.median(vals) if vals else None

    verse, chorus = med_of("主歌"), med_of("副歌")
    lift = (chorus - verse) if (verse is not None and chorus is not None) else None

    return [
        Metric("contour_overall", "全曲音高极差", float(max(allp) - min(allp)),
               12.0, " 半音", MIN,
               "整首都挤在一个窄音区里。改 `spec.register` 或换轮廓",
               f"{min(allp)}–{max(allp)}"),
        Metric("contour_line", "每句极差中位", float(st.median(line_ranges))
               if line_ranges else None, 2.0, " 半音", MIN,
               "每句都在原地打转。改轮廓（`CONTOURS`）比改音区更对症",
               f"{len(line_ranges)} 句，最小 {min(line_ranges) if line_ranges else '—'}"
               f"，最大 {max(line_ranges) if line_ranges else '—'}"),
        Metric("contour_lift", "副歌−主歌音区", float(lift) if lift is not None
               else None, 5.0, " 半音", MIN,
               "副歌没有抬起来，所以不够爆。用 `adjust_spec` 的 register_shift",
               f"主歌 {verse:.0f} → 副歌 {chorus:.0f}"
               if lift is not None else "缺主歌或副歌"),
    ]


# =========================================================================
# dynamic_span —— 力度的起伏
# =========================================================================

def dynamics(proj: PJ.SongProject) -> list[Metric]:
    try:
        d = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return [Metric("dynamic_span", "响度跨度", None, None,
                       detail=f"读不到工程：{type(e).__name__}")]
    lib = {g.get("uuid"): g for g in (d.get("library") or [])}
    span, n_pts = None, 0
    for t in (d.get("tracks") or []):
        if not str(t.get("name", "")).startswith("主旋律"):
            continue
        for ref in (t.get("groups") or []):
            g = lib.get(ref.get("groupID")) or {}
            pts = ((g.get("parameters") or {}).get("loudness") or {}).get("points") or []
            vals = pts[1::2]
            if vals:
                span = max(vals) - min(vals)
                n_pts = len(vals)
    return [Metric(
        "dynamic_span", "响度跨度", span, 2.0, " dB", MIN,
        "唱得一样响，情绪推不上去。改 `TuneCfg` 的 loudness 幅度，"
        "不是改音高",
        f"{n_pts} 个点" if span is not None
        else "还没调教过 —— **不知道**，不是「很平」")]


def expressiveness(proj: PJ.SongProject) -> list[Metric]:
    """「机械 / 不像人」那条规则的原料：音高微调点数与调教点密度。

    两个都按**每音符**算 —— 绝对点数会随歌的长短变，跨歌不可比，
    而诊断层要拿它和别的版本对照。
    """
    try:
        d = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return [Metric("pitch_delta_density", "音高微调密度", None, 1.0, " 点/音符"),
                Metric("tuning_density", "调教点密度", None, 4.0, " 点/音符")]
    lib = {g.get("uuid"): g for g in (d.get("library") or [])}
    n_notes, n_pd, n_all = 0, 0, 0
    for t in (d.get("tracks") or []):
        if not str(t.get("name", "")).startswith("主旋律"):
            continue
        for ref in (t.get("groups") or []):
            g = lib.get(ref.get("groupID")) or {}
            n_notes += len(g.get("notes") or [])
            for name, v in (g.get("parameters") or {}).items():
                k = len(v.get("points") or []) // 2
                n_all += k
                if name == "pitchDelta":
                    n_pd += k
            for v in (g.get("vocalModes") or {}).values():
                n_all += len(v.get("points") or []) // 2
    if not n_notes:
        return [Metric("pitch_delta_density", "音高微调密度", None, 1.0, " 点/音符"),
                Metric("tuning_density", "调教点密度", None, 4.0, " 点/音符")]
    return [
        Metric("pitch_delta_density", "音高微调密度", n_pd / n_notes, 0.5,
               " 点/音符", MIN,
               "音高全是直线，听着像机器。加 `pitchDelta` —— 滑音、颤音起振",
               f"{n_pd} 点 / {n_notes} 音符"),
        Metric("tuning_density", "调教点密度", n_all / n_notes, 2.5,
               " 点/音符", MIN,
               "整体没调教过，或者调得太稀。跑 `tune`",
               f"{n_all} 点 / {n_notes} 音符"),
    ]


# =========================================================================
# 第九项检查的数值形态
# =========================================================================

def chord_fit(proj: PJ.SongProject) -> list[Metric]:
    from ..compose.checks import CheckCfg, chord_fit_ratios
    from ..compose.melodize import phrases_of
    try:
        (_name, notes, sections), _ver = _lead(proj)
        sys.path.insert(0, str(ROOT / "scripts"))
        import step3_melody as S3
        kr, _kq, _kn = S3.infer_key([n.midi for n in notes])
        ratios = chord_fit_ratios(notes, phrases_of(sections, kr))
    except Exception as e:
        return [Metric("chord_fit", "和弦贴合度", None, None,
                       detail=f"算不了：{type(e).__name__}: {e}")]
    if not ratios:
        return [Metric("chord_fit", "和弦贴合度", None, None, detail="没有乐句")]
    lo = CheckCfg().chord_fit_min
    return [Metric(
        "chord_fit", "和弦贴合度中位", st.median(ratios), 0.45, "", MIN,
        "整句离和声。**按时长加权** —— 短的经过音不算问题",
        f"{len(ratios)} 句，最低 {min(ratios):.0%}，"
        f"低于下限 {lo:.0%} 的有 {sum(1 for r in ratios if r < lo)} 句")]


# =========================================================================
# 汇总
# =========================================================================

def collect(proj: PJ.SongProject | None = None) -> list[Metric]:
    """指标面板读这个。**每个数都来自库里已有的函数，这里不算新东西。**"""
    proj = proj or PJ.current()
    return (contour(proj) + dynamics(proj)
            + expressiveness(proj) + chord_fit(proj))


def report(ms: list[Metric]) -> str:
    mark = {True: "✓", False: "✗", None: "·"}
    return "\n".join(
        f"  {mark[m.ok]} {m.label:<14}{m.show():<22}{m.detail}"
        + (f"\n      → {m.means}" if m.ok is False else "")
        for m in ms)
