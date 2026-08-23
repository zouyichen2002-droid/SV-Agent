"""自修复循环：生成 → 检查 → 修复 → 再检查，直到 0 finding 或收敛。

## 为什么这是 agent，而前面那些是 workflow

workflow 的每一步由作者写死。这个循环**自己决定下一步改哪个音符**，
判据是七项检查给出的代价函数。它是一个受确定性目标约束的**搜索**，
不是一串固定动作。

我们有一个别处很少见的东西：**可程序化的奖励信号**。
七项检查把「这段旋律有没有问题」变成一个可以求最小值的数。
LLM 生成的旋律可以被这个信号反复约束，直到通过 —— 而不是让模型自由发挥。

## 三条设计约束，缺一条循环就不可信

1. **回归守卫**：一次修复必须让总代价**严格下降**，否则回退。
   修 `leap` 很容易顺手制造一个 `scale` 越界；没有守卫就会左右横跳。
2. **不可修就拉黑，不重试**：修不动的 finding 记下来跳过，避免死循环。
   `count` 就属于这类 —— 字数与音符数不符是结构问题，挪音高解决不了。
3. **全过程可审计**：每一次尝试（接受/拒绝/原因）都进 history。
   「初始 N findings → 0，M 轮迭代，零人工干预」这句话必须有逐步证据。

## 修复只动音高与时长，绝不增删音符或改歌词

这是刻意的边界。增删音符会破坏 `count`、打乱 `phrases` 的下标、
让 `prosody` 的字组对不上 —— 一次修复可能引发三处坍塌。
把搜索空间限制在「已有音符的音高和时长」上，`count` 和 prosody 的
block 分支就**永远不会被修复动作引入**。

改歌词是另一条路（换同义词修倒字），代价更高，留给上层的生成器。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .checks import (MAJOR, MINOR, CheckCfg, Finding, Note, Phrase,
                     note_name, run_all)

# 代价权重。block 必须压倒一切 —— 它是「不能交付」，warn 只是「值得看一眼」。
SEVERITY_COST = {"block": 100.0, "warn": 10.0, "info": 1.0}

# 这些 kind 靠挪音高/时长修不了，直接拉黑
UNFIXABLE_KINDS = {"count"}


def cost(findings: list[Finding]) -> float:
    """总代价。prosody 的 score 叠加进去，让循环优先修更严重的倒字。"""
    return sum(SEVERITY_COST[f.severity] + f.score for f in findings)


# ---------------------------------------------------------------- 音高工具

def scale_pcs(key_root: int, quality: str) -> tuple[int, ...]:
    base = MAJOR if quality == "major" else MINOR
    return tuple((key_root + d) % 12 for d in base)


def snap_in_key(midi: int, key_root: int, quality: str,
                lo: int, hi: int, *, prefer: int = 0) -> int | None:
    """把 midi 移到最近的调内音，并夹在 [lo, hi] 内。

    `prefer` 为 +1/-1 时优先往该方向找 —— 修 `leap` 时需要指定方向，
    否则「最近」可能把音符移到跳进的另一侧，问题原地不动。
    """
    pcs = scale_pcs(key_root, quality)
    best, best_d = None, 1e9
    for cand in range(lo, hi + 1):
        if cand % 12 not in pcs:
            continue
        d = abs(cand - midi)
        if prefer and (cand - midi) * prefer < 0:
            d += 100          # 反方向重罚，但不禁止（免得无解）
        if d < best_d:
            best, best_d = cand, d
    return best


def chord_tones(root: int, quality: str) -> tuple[int, ...]:
    triad = (0, 4, 7) if quality == "major" else (0, 3, 7)
    return tuple((root + t) % 12 for t in triad)


def nearest_chord_tone(midi: int, root: int, quality: str,
                       lo: int, hi: int) -> int | None:
    pcs = chord_tones(root, quality)
    cands = [c for c in range(lo, hi + 1) if c % 12 in pcs]
    return min(cands, key=lambda c: abs(c - midi)) if cands else None


# ---------------------------------------------------------------- 上下文

@dataclass
class Ctx:
    text: str
    key_root: int
    quality: str
    phrases: list[Phrase]
    cfg: CheckCfg

    def check(self, notes: list[Note]) -> list[Finding]:
        return run_all(notes, self.text, self.key_root, self.quality,
                       self.phrases, self.cfg)

    def phrase_of_note(self, idx: int) -> Phrase | None:
        for ph in self.phrases:
            if ph.note_from <= idx < ph.note_to:
                return ph
        return None


# ---------------------------------------------------------------- 修复策略
#
# 每个策略拿到 (notes 的副本, finding, ctx)，返回若干**候选**改法。
# 循环会逐个试，取第一个能让总代价下降的。返回多个候选很重要 ——
# 「把 a 抬上去」和「把 b 压下来」都能修一个跳进，但对邻近音符的影响不同。

def _fix_range(notes: list[Note], f: Finding, ctx: Ctx) -> list[list[Note]]:
    cfg = ctx.cfg
    out = []
    for i in f.targets:
        if not (0 <= i < len(notes)):
            continue
        cur = notes[i].midi
        # 越界：先按八度拉回，八度关系保留旋律轮廓
        cands = []
        for oct_shift in (12, -12, 24, -24):
            m = cur + oct_shift
            if cfg.range_lo <= m <= cfg.range_hi:
                cands.append(m)
        # 贴边或八度不够：往音域中心方向找最近的调内音
        mid = (cfg.range_lo + cfg.range_hi) // 2
        m = snap_in_key(cur, ctx.key_root, ctx.quality,
                        cfg.range_lo + cfg.range_edge_semitones,
                        cfg.range_hi - cfg.range_edge_semitones,
                        prefer=1 if cur < mid else -1)
        if m is not None:
            cands.append(m)
        for m in cands:
            c = copy.deepcopy(notes)
            c[i].midi = m
            out.append(c)
    return out


def _fix_leap(notes: list[Note], f: Finding, ctx: Ctx) -> list[list[Note]]:
    if len(f.targets) != 2:
        return []
    ia, ib = f.targets
    if not (0 <= ia < len(notes) and 0 <= ib < len(notes)):
        return []
    cfg = ctx.cfg
    a, b = notes[ia].midi, notes[ib].midi
    d = b - a
    step = -1 if d > 0 else 1        # 把跳进压小的方向
    out = []
    # 候选 1：把后一个音往回收，收到刚好不超阈值
    target_b = a + (cfg.leap_max_semitones * (1 if d > 0 else -1))
    m = snap_in_key(target_b, ctx.key_root, ctx.quality,
                    cfg.range_lo, cfg.range_hi, prefer=step)
    if m is not None and m != b:
        c = copy.deepcopy(notes); c[ib].midi = m; out.append(c)
    # 候选 2：把前一个音往后一个方向靠
    target_a = b - (cfg.leap_max_semitones * (1 if d > 0 else -1))
    m = snap_in_key(target_a, ctx.key_root, ctx.quality,
                    cfg.range_lo, cfg.range_hi, prefer=-step)
    if m is not None and m != a:
        c = copy.deepcopy(notes); c[ia].midi = m; out.append(c)
    # 候选 3：两个各让一半
    half = abs(d) // 2
    c = copy.deepcopy(notes)
    ma = snap_in_key(a + half * (1 if d > 0 else -1), ctx.key_root,
                     ctx.quality, cfg.range_lo, cfg.range_hi)
    mb = snap_in_key(b - half * (1 if d > 0 else -1), ctx.key_root,
                     ctx.quality, cfg.range_lo, cfg.range_hi)
    if ma is not None and mb is not None:
        c[ia].midi, c[ib].midi = ma, mb
        out.append(c)
    return out


def _fix_scale(notes: list[Note], f: Finding, ctx: Ctx) -> list[list[Note]]:
    out = []
    for i in f.targets:
        if not (0 <= i < len(notes)):
            continue
        for prefer in (0, 1, -1):
            m = snap_in_key(notes[i].midi, ctx.key_root, ctx.quality,
                            ctx.cfg.range_lo, ctx.cfg.range_hi, prefer=prefer)
            if m is not None and m != notes[i].midi:
                c = copy.deepcopy(notes); c[i].midi = m; out.append(c)
    return out


def _fix_cadence(notes: list[Note], f: Finding, ctx: Ctx) -> list[list[Note]]:
    if not f.targets:
        return []
    i = f.targets[0]
    if not (0 <= i < len(notes)):
        return []
    ph = ctx.phrase_of_note(i)
    if ph is None or ph.chord_root is None:
        return []
    out = []
    m = nearest_chord_tone(notes[i].midi, ph.chord_root, ph.chord_quality,
                           ctx.cfg.range_lo, ctx.cfg.range_hi)
    if m is not None and m != notes[i].midi:
        c = copy.deepcopy(notes); c[i].midi = m; out.append(c)
    # 备选：同一个和弦音的上下八度，轮廓差别很大，值得都试
    for alt in (m - 12 if m else None, m + 12 if m else None):
        if alt and ctx.cfg.range_lo <= alt <= ctx.cfg.range_hi:
            c = copy.deepcopy(notes); c[i].midi = alt; out.append(c)
    return out


def _fix_phrase(notes: list[Note], f: Finding, ctx: Ctx) -> list[list[Note]]:
    """乐句内缺口：把前一个音符的时长拉长，把洞填上。"""
    if len(f.targets) != 2:
        return []
    ia, ib = f.targets
    if not (0 <= ia < len(notes) and 0 <= ib < len(notes)):
        return []
    c = copy.deepcopy(notes)
    c[ia].duration_beats = round(notes[ib].onset_beats
                                 - notes[ia].onset_beats, 6)
    return [c] if c[ia].duration_beats > 0 else []


def _fix_prosody(notes: list[Note], f: Finding, ctx: Ctx) -> list[list[Note]]:
    """倒字：调整这个字与相邻音符的走向。

    只动音高，不动歌词。改词（换同义词）是更强的手段，但那要动
    `text`，会连带影响 count 与字组划分 —— 交给上层生成器。
    """
    if not f.targets:
        return []
    cfg = ctx.cfg
    out = []
    first, last = f.targets[0], f.targets[-1]
    nxt = last + 1
    # 候选：把下一个字的首音往本字靠，削掉那个触发倒字的音程
    if 0 <= nxt < len(notes):
        d = notes[nxt].midi - notes[last].midi
        if d:
            for shrink in (2, 4):
                tgt = notes[last].midi + (max(0, abs(d) - shrink)
                                          * (1 if d > 0 else -1))
                m = snap_in_key(tgt, ctx.key_root, ctx.quality,
                                cfg.range_lo, cfg.range_hi)
                if m is not None and m != notes[nxt].midi:
                    c = copy.deepcopy(notes); c[nxt].midi = m; out.append(c)
    # 候选：字内多音符时，把内部走向压平（拖腔内的音高反转最伤）
    if last > first:
        c = copy.deepcopy(notes)
        for k in range(first + 1, last + 1):
            c[k].midi = c[first].midi
        out.append(c)
    return out


STRATEGIES = {
    "range": _fix_range,
    "leap": _fix_leap,
    "scale": _fix_scale,
    "cadence": _fix_cadence,
    "phrase": _fix_phrase,
    "prosody": _fix_prosody,
}


# ---------------------------------------------------------------- 循环

@dataclass
class Step:
    iteration: int
    finding: str
    accepted: bool
    reason: str
    cost_before: float
    cost_after: float
    change: str = ""


@dataclass
class Result:
    notes: list[Note]
    steps: list[Step] = field(default_factory=list)
    initial: list[Finding] = field(default_factory=list)
    final: list[Finding] = field(default_factory=list)
    blacklisted: list[str] = field(default_factory=list)

    @property
    def converged(self) -> bool:
        return not self.final

    @property
    def accepted_steps(self) -> int:
        return sum(1 for s in self.steps if s.accepted)


def _describe(before: list[Note], after: list[Note]) -> str:
    diffs = []
    for a, b in zip(before, after):
        if a.midi != b.midi:
            diffs.append(f"#{a.index} {note_name(a.midi)}→{note_name(b.midi)}")
        elif abs(a.duration_beats - b.duration_beats) > 1e-9:
            diffs.append(f"#{a.index} 时长 {a.duration_beats:g}→"
                         f"{b.duration_beats:g} 拍")
    return "，".join(diffs) or "（无变化）"


def repair(notes: list[Note], ctx: Ctx, *, max_iters: int = 40) -> Result:
    """迭代修复到 0 finding 或无法再改进。"""
    cur = copy.deepcopy(notes)
    res = Result(notes=cur, initial=ctx.check(cur))
    blacklist: set[tuple] = set()

    for it in range(1, max_iters + 1):
        fs = ctx.check(cur)
        if not fs:
            break
        # 挑还没拉黑的最严重的一个（run_all 已按 severity → score 排好）
        target = None
        for f in fs:
            key = (f.kind, f.where, f.detail)
            if key in blacklist or f.kind in UNFIXABLE_KINDS:
                continue
            target = f
            break
        if target is None:
            break

        c0 = cost(fs)
        cands = STRATEGIES.get(target.kind, lambda *_: [])(cur, target, ctx)
        best = None
        for cand in cands:
            c1 = cost(ctx.check(cand))
            # 回归守卫：必须严格下降。相等也拒绝 —— 否则会在等价解之间打转
            if c1 < c0 - 1e-9 and (best is None or c1 < best[0]):
                best = (c1, cand)

        key = (target.kind, target.where, target.detail)
        if best is None:
            blacklist.add(key)
            res.steps.append(Step(it, str(target), False,
                                  f"{len(cands)} 个候选都没能降低总代价"
                                  if cands else "没有可用的修复策略",
                                  c0, c0))
            res.blacklisted.append(str(target))
            continue

        c1, cand = best
        res.steps.append(Step(it, str(target), True, "总代价下降",
                              c0, c1, _describe(cur, cand)))
        cur = cand

    res.notes = cur
    res.final = ctx.check(cur)
    return res
