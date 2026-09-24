# -*- coding: utf-8 -*-
"""建造顺序第 7 项：**诊断的原料** —— 把「太平」变成可测的数。

## 为什么 `contour_range` 与 `dynamic_span` 必须分开

架构文档 §6：**「音高平」和「力度平」修法不同** ——
前者改 `spec.register` 或轮廓，后者改 `TuneCfg`。合成一个数就无法归因，
而归因正是诊断层存在的理由。

## 阈值的来历，以及它错在哪

**第一版**是拿《晓风残月》校的：那首已经通过创作者验收、八项检查
0 finding，所以「任何把它判为太平的阈值都是错的」。当时还专门写了一段
解释，说副歌句内极差只有 3「却不平，因为起伏来自音区抬升」。

**2026-09-06 推翻。** 创作者说「我并不满意其实，还是要从真正的歌曲中
学习」。拿 POP909 的 593 首真歌一比（见 `svagent/reference.py`）：

    指标            我们    旧阈值   真歌p10  真歌中位   我们的百分位
    全曲音高极差    15.00    12.0    14.0     18.0     第 12.1
    每句极差中位     3.00     2.0     5.0      8.5     **第 0.3**
    和弦贴合度       0.70     0.45    0.53     0.74     第 39.5

**593 首里只有 2 首比我们平。** 那段「只有 3 却不平」的解释是在为缺陷
辩护 —— 根因是 `spec._register_for` 里一个 `min` 把副歌音区截成了
3 个半音（已修，见 `tests/test_spec.py`）。修完句极差中位 3.0 → 7.5，
百分位 0.3 → 36。

**校准原则因此改写：**

> 旧：阈值不许把已验收的作品判为不合格。
> 新：**阈值对齐真歌的分布。我们达不到，就是达不到。**

旧原则的漏洞在于它默认了「已验收 = 好」。一旦创作者的验收标准本身
还在成长，这条原则就会把当时的水平**焊死成地板**，
于是检查结构上不可能告诉我们「离专业还差多少」—— 它没见过专业。

下面这些阈值**尚未按新原则收紧**：生成器刚够到真歌的第 36 百分位，
此刻就把阈值提到 p10 会让每一首歌都被拦住。**先让生成器有能力，
再收阈值** —— 设一个必然失败的判据不是严格，是把流程堵死。

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


class NoLead(RuntimeError):
    """工程里还没有主旋律轨。**这是新歌的必经状态，不是错误。**"""


def _lead(proj: PJ.SongProject):
    """读回主旋律与段落结构。**用 step3 那一个实现，不重写。**

    ## 为什么要把异常类型换掉

    `S3.read_lead` 是给命令行用的，没有主旋律时 `raise SystemExit` ——
    那在脚本里是对的（退出码）。但它在库里被调用时，`SystemExit` 继承的是
    **`BaseException` 不是 `Exception`**，于是下面每一个 `except Exception`
    都接不住它。

    后果：`set_lyrics` 之后、`gen_melody` 之前（每首歌的必经状态），
    `metrics.collect` 抛 `SystemExit` 一路穿到 HTTP 处理线程，
    线程死掉、**连响应都不发**。创作者看到的是「✗ Failed to fetch」，
    零解释。2026-09-18 按「全程只聊天」跑《海边的雨》时撞上的。

    下面那些 `except Exception` 全都是**写了却结构性打不响**的防护 ——
    作者本来就打算接住这种情况。所以在这里归一化，
    让那些防护开始真的生效，而不是逐个改成 `except BaseException`
    （那会顺手吞掉 Ctrl-C）。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import step3_melody as S3

    from ..compose import lyricfile as LF
    vs, _probs = LF.parse(proj.lyrics)
    try:
        ver = LF.first_version(vs, proj.lyrics)
    except LF.LyricsEmpty as e:
        raise NoLead(str(e)) from e
    try:
        return S3.read_lead(proj.svp, ver, proj.form), ver
    except S3.NoLead as e:
        raise NoLead(str(e)) from e


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
    if n_all == 0:
        # **还没走到调教那一步 ≠ 调教得不好。** 三色纪律：
        # 0 点是「不知道」，不是「很机械」。端到端跑新歌时暴露的 ——
        # 第 3 步刚做完就看见两个红叉，看着像出了问题，其实只是还没到。
        d = "还没调教过（步骤 5）—— **不知道**，不是「很机械」"
        return [Metric("pitch_delta_density", "音高微调密度", None, 0.5,
                       " 点/音符", MIN, "", d),
                Metric("tuning_density", "调教点密度", None, 2.5,
                       " 点/音符", MIN, "", d)]
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
