"""从主旋律生成**人声和声轨**（同一个声库唱，不是乐器）。

## 这是什么、不是什么

创作者 2026-08-23 的纠正：**「我说的和声也是星尘的和声，而不是其他音频。
比如：副歌低八度等」**。

我原先做的是乐器和弦垫（音频轨），错了。和声是**另一条人声轨**：
同样的歌词、不同的音高，和主旋律同时唱。他自己的《世末歌者》工程里
就有两条名叫「和声」的轨，各 411 个音符（主唱 576），
音符更少正说明**和声只覆盖部分段落**，不是全曲跟唱。

## 和声的音高怎么定

四种，都在调内 —— 和声唱出调外音是硬伤，比不加和声糟得多。

| 类型 | 做法 | 特点 |
|---|---|---|
| `低八度` | 主旋律 − 12 | 最稳，一定协和；但副歌高位减 12 会掉出舒适音域 |
| `下三度` | 调内下移 2 个音级 | 最常用，厚度与清晰度平衡 |
| `上三度` | 调内上移 2 个音级 | 明亮；副歌本来就高时容易顶出音域 |
| `下六度` | 调内下移 5 个音级 | 比下三度更开，适合宽的副歌 |

**调内移动而不是固定半音数**：小调里「三度」在不同音级上是 3 或 4 个半音，
按固定半音平移必然出调。所以在音阶序列上按**音级**移动。

## 音域是硬约束

星尘舒适区 MIDI 57–78。和声移完出界就按八度拉回；拉不回就换类型。
**出界的和声比没有和声糟** —— 女声在音域外唱长音会发虚，而和声本来是垫厚度的。

## 只覆盖选定段落

默认只在副歌。全曲跟唱会让主旋律失去焦点，也是业余感最常见的来源。
"""
from __future__ import annotations

from dataclasses import dataclass

from .checks import CheckCfg, Note, Phrase
from .melodize import scale_pitches

HARMONY_TYPES = ("低八度", "下三度", "上三度", "下六度")
# 音级位移（调内），低八度单独处理
_STEPS = {"下三度": -2, "上三度": +2, "下六度": -5}


def diatonic_shift(midi: int, key_root: int, quality: str, steps: int,
                   lo: int = 36, hi: int = 96) -> int:
    """在调内音阶上移动 `steps` 个音级。

    **不能按固定半音平移** —— 小调里三度在不同音级上是 3 或 4 个半音，
    固定平移必然产生调外音。
    """
    pitches = scale_pitches(key_root, quality, lo, hi)
    if not pitches:
        return midi
    if midi in pitches:
        i = pitches.index(midi)
    else:
        i = min(range(len(pitches)), key=lambda k: abs(pitches[k] - midi))
    j = max(0, min(len(pitches) - 1, i + steps))
    return pitches[j]


# 音程用不了时的备选顺序。下三度最通用，所以放第一
FALLBACK_ORDER = ("下三度", "下六度", "上三度", "低八度")


def _shift(midi: int, kind: str, key_root: int, quality: str) -> int:
    if kind == "低八度":
        return midi - 12
    return diatonic_shift(midi, key_root, quality, _STEPS[kind])


def _place(src: int, kind: str, key_root: int, quality: str,
           lo: int, hi: int) -> tuple[int, str] | None:
    """给一个音选和声音高。返回 (音高, 实际用的音程) 或 None。

    ## 为什么不能「按八度拉回」

    原来的实现是：算出的和声音出了舒适区就按八度拉回。**这是错的** ——
    副歌在 67–76 时，低八度得到 55，拉回来正好是 67，
    **和原音同音**。同音齐唱不是和声，是加倍，听起来只是主旋律变厚一点，
    创作者会觉得「和声没生效」。

    正确做法是**换音程**：按 FALLBACK_ORDER 依次试，
    要求既在舒适区（还要避开贴边）又不与原音同高。
    一个音程都用不上就返回 None —— 宁可这个音没有和声，
    也不要一个假和声。
    """
    order = [kind] + [k for k in FALLBACK_ORDER if k != kind]
    for k in order:
        tgt = _shift(src, k, key_root, quality)
        if lo <= tgt <= hi and tgt != src:
            return tgt, k
    return None


@dataclass
class HarmonyPlan:
    kind: str                      # 见 HARMONY_TYPES
    sections: tuple[str, ...]      # 覆盖哪些段落（按段名前缀匹配）

    def describe(self) -> str:
        return f"{self.kind}（{'/'.join(self.sections)}）"


def harmonize(notes: list[Note], phrases: list[Phrase], sections,
              plan: HarmonyPlan, *, key_root: int, quality: str,
              cfg: CheckCfg | None = None) -> tuple[list[Note], list[str]]:
    """→ (和声音符, 说明/告警列表)。音符下标重新从 0 编号。

    `sections` 是 melodize 返回的 SECTIONS：[(段名, 起始小节, [(词, 音节, 和弦)])]。
    用它算出哪些音符属于要加和声的段落。
    """
    cfg = cfg or CheckCfg()
    lo, hi = cfg.range_lo, cfg.range_hi
    notes_by_index = {n.index: n for n in notes}

    # 段落 → 该段覆盖的音符下标区间。SECTIONS 里每段的音节数就是音符数
    want: set[int] = set()
    idx = 0
    for sec_name, _bar0, lines in sections:
        n_here = sum(len(syls) for _t, syls, _c in lines)
        if any(sec_name.startswith(p) for p in plan.sections):
            want.update(range(idx, idx + n_here))
        idx += n_here

    # 连贴边也避开：贴边的长音女声会发虚，而和声正是拿来垫厚度的
    edge = cfg.range_edge_semitones
    win_lo, win_hi = lo + edge, hi - edge

    notes_out: list[Note] = []
    warns: list[str] = []
    used: dict[str, int] = {}
    dropped = 0
    for i in sorted(want):
        src = notes_by_index.get(i)
        if src is None:
            continue
        got = _place(src.midi, plan.kind, key_root, quality, win_lo, win_hi)
        if got is None:
            dropped += 1
            continue
        tgt, kind_used = got
        used[kind_used] = used.get(kind_used, 0) + 1
        notes_out.append(Note(len(notes_out), src.onset_beats,
                              src.duration_beats, tgt, src.lyric))

    total = len(notes_out) + dropped
    n_planned = used.get(plan.kind, 0)
    if total and n_planned / total < 0.7:
        # 计划的音程大部分用不上，说明这个方案不适合这首歌的音区。
        # 报出来而不是悄悄替换 —— 否则「和声是低八度」这句话就是假的。
        warns.append(
            f"⚠ 计划的「{plan.kind}」只用上 {n_planned}/{total} 个音"
            f"（{100*n_planned/max(1,total):.0f}%），"
            f"实际构成 {'、'.join(f'{k}×{v}' for k, v in sorted(used.items(), key=lambda kv: -kv[1]))}"
            "。这个音程不适合本曲的副歌音区")
    elif len(used) > 1:
        warns.append("音程构成 " + "、".join(
            f"{k}×{v}" for k, v in sorted(used.items(), key=lambda kv: -kv[1])))
    if dropped:
        warns.append(f"{dropped} 个音所有备选音程都出舒适区，已跳过")
    if not notes_out:
        warns.append("和声一个音都没生成 —— 检查 plan.sections 是否匹配段名")
    return notes_out, warns


def pick_plan(i: int, sections_available: list[str]) -> HarmonyPlan:
    """给第 i 版挑一个和声方案。四种类型 × 两种覆盖范围。

    覆盖范围只有两档：只副歌（默认）、副歌+预副（更满）。
    不提供「全曲跟唱」—— 那会让主旋律失去焦点。
    """
    kind = HARMONY_TYPES[i % len(HARMONY_TYPES)]
    wide = (i // len(HARMONY_TYPES)) % 2 == 1
    secs = ("副歌", "预副") if wide else ("副歌",)
    return HarmonyPlan(kind=kind, sections=secs)
