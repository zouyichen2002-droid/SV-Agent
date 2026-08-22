"""从音高证据图构建音符（阶段 4 的最小可用版本）。

**当前范围限于验证用途**：只做「音高 + 时长」，歌词一律用中性音节。
逐字歌词要等阶段 3（CTC 逐字对齐）过了才写 —— 上一次失败的可闻缺陷正是
21% 的音符没有声学证据、歌词从邻居抄，不能再重复。

沿用交接文件 §6.1 已确证的做法：

- 音高取音符**中段 60%** 的中位（避开边界过渡区），优于全跨度
- 时长下限 85ms、上限 1.70s
- **不做网格量化**（16 分音符 snap 实测 64.9% vs 不 snap 66.7%，量化让结果变差）
- 消重叠不能写成 `duration = max(下限, 间隙)`，间隙小于下限时反而造出重叠

新增的一条：**没有证据的帧不产出音符**，直接留空。缺口进清单交给耳朵。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .pitch.base import hz_to_midi


@dataclass
class Note:
    onset_s: float
    duration_s: float
    midi: int
    lyric: str = "la"
    evidence_frac: float = 1.0      # 本音符跨度内有证据帧的比例
    midi_median: float = 0.0        # 未取整的中位，看离整数多远
    n_sources: float = 0.0          # 平均有几个估计器确认
    spread_cents: float = 0.0       # 中段内未平滑音高的四分位距

    @property
    def end_s(self) -> float:
        return self.onset_s + self.duration_s

    @property
    def cents_off(self) -> float:
        """离最近半音的偏差。绝对值大说明这个音本来就在音分之间（滑音/转音）。"""
        return (self.midi_median - self.midi) * 100.0


def _rolling_median(x: np.ndarray, k: int) -> np.ndarray:
    """NaN 感知的滑动中位。k 为奇数帧数。"""
    if k <= 1:
        return x.copy()
    if k % 2 == 0:
        k += 1
    half = k // 2
    pad = np.pad(x, (half, half), constant_values=np.nan)
    out = np.full(x.size, np.nan)
    for i in range(x.size):
        w = pad[i:i + k]
        w = w[np.isfinite(w)]
        if w.size:
            out[i] = np.median(w)
    return out


def _runs_of(vals: np.ndarray) -> list[tuple[int, int, float]]:
    """把整数序列切成 (起, 止, 值) 的连续段；NaN 处断开。"""
    out: list[tuple[int, int, float]] = []
    i = 0
    n = vals.size
    while i < n:
        if not np.isfinite(vals[i]):
            i += 1
            continue
        j = i + 1
        while j < n and np.isfinite(vals[j]) and vals[j] == vals[i]:
            j += 1
        out.append((i, j, float(vals[i])))
        i = j
    return out


def build(f0_hz: np.ndarray, hop_s: float, t0: float, t1: float, *,
          n_agree: np.ndarray | None = None,
          smooth_ms: float = 150.0,
          min_ms: float = 85.0,
          max_s: float = 1.70,
          bridge_gap_ms: float = 80.0,
          max_spread_cents: float = 100.0,
          max_quant_err_cents: float = 50.0,
          min_evidence_frac: float = 0.60,
          merge_gap_ms: float = 60.0,
          lyric: str = "la") -> tuple[list[Note], list[tuple[float, float]], dict]:
    """返回 (音符列表, 无证据缺口列表, 剔除统计)。

    `smooth_ms` 默认 150ms：颤音典型是 5–6Hz、±0.5–1 半音，不先平滑的话
    取整后的半音会来回翻，把一个长音切成一串碎音符。

    三道剔除，都是"这一段不构成一个稳定音符"而不是"猜一个"：

    - `max_spread_cents` —— 中段内未平滑音高的四分位距超过 1 个半音，
      说明这是滑音/转音的过渡段，不是稳定音。实测不加这条会把过渡帧
      当成 90ms 的短音符写出去，其量化半音离实际内容差到 245 音分。
    - `max_quant_err_cents` —— 量化后的半音离中段中位超过半个半音，同上。
    - `min_evidence_frac` —— 跨度内有证据的帧太少，不写。
    """
    i0 = max(0, int(round(t0 / hop_s)))
    i1 = min(f0_hz.size, int(round(t1 / hop_s)))
    seg = f0_hz[i0:i1]
    if seg.size == 0:
        return [], [], {}
    midi = hz_to_midi(seg)

    # 桥接短空洞：<bridge_gap_ms 的证据缺口用线性填（只填空洞，不外推）
    bg = int(round(bridge_gap_ms / 1000 / hop_s))
    filled = midi.copy()
    ok = np.isfinite(midi)
    if bg > 0 and ok.any():
        idx = np.flatnonzero(ok)
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= bg + 1:
                filled[a + 1:b] = np.linspace(midi[a], midi[b], b - a + 1)[1:-1]

    sm = _rolling_median(filled, int(round(smooth_ms / 1000 / hop_s)))
    quant = np.where(np.isfinite(sm), np.round(sm), np.nan)

    notes: list[Note] = []
    dropped = {"太短": 0, "滑音过渡（中段散布过大）": 0,
               "量化误差过大": 0, "证据不足": 0}
    for a, b, val in _runs_of(quant):
        dur = (b - a) * hop_s
        if dur * 1000 < min_ms:
            dropped["太短"] += 1
            continue
        # 中段 60% 取中位
        lo = a + int((b - a) * 0.2)
        hi = b - int((b - a) * 0.2)
        core = filled[lo:hi] if hi > lo else filled[a:b]
        core = core[np.isfinite(core)]
        if core.size == 0:
            continue
        ev = float(np.isfinite(midi[a:b]).mean())
        med = float(np.median(core))
        spread = float(np.percentile(core, 75) - np.percentile(core, 25)) * 100.0
        if spread > max_spread_cents:
            dropped["滑音过渡（中段散布过大）"] += 1
            continue
        if abs(med - val) * 100.0 > max_quant_err_cents:
            dropped["量化误差过大"] += 1
            continue
        if ev < min_evidence_frac:
            dropped["证据不足"] += 1
            continue
        ns = 0.0
        if n_agree is not None:
            w = n_agree[i0 + a:i0 + b]
            w = w[w > 0]
            ns = float(w.mean()) if w.size else 0.0
        notes.append(Note(
            onset_s=t0 + a * hop_s,
            duration_s=min(dur, max_s),
            midi=int(val),
            lyric=lyric,
            evidence_frac=ev,
            midi_median=med,
            n_sources=ns,
            spread_cents=spread,
        ))

    # 同音高、间隔很小的相邻音符合并（剔除过渡帧后常留下同音高的两截）
    merged: list[Note] = []
    for nt in notes:
        if (merged and merged[-1].midi == nt.midi
                and nt.onset_s - merged[-1].end_s <= merge_gap_ms / 1000
                and (nt.end_s - merged[-1].onset_s) <= max_s):
            prev = merged[-1]
            prev.duration_s = nt.end_s - prev.onset_s
            prev.evidence_frac = min(prev.evidence_frac, nt.evidence_frac)
            prev.spread_cents = max(prev.spread_cents, nt.spread_cents)
        else:
            merged.append(nt)
    notes = merged

    # 消重叠：只截前一个音符的尾，不去拉长任何音符
    for k in range(len(notes) - 1):
        overlap = notes[k].end_s - notes[k + 1].onset_s
        if overlap > 0:
            notes[k].duration_s = max(min_ms / 1000, notes[k].duration_s - overlap)

    gaps: list[tuple[float, float]] = []
    okm = np.isfinite(midi)
    i = 0
    while i < okm.size:
        if okm[i]:
            i += 1
            continue
        j = i
        while j < okm.size and not okm[j]:
            j += 1
        if (j - i) * hop_s >= 0.15:
            gaps.append((t0 + i * hop_s, t0 + j * hop_s))
        i = j
    return notes, gaps, dropped


def summarize(notes: list[Note], gaps: list[tuple[float, float]]) -> str:
    if not notes:
        return "没有音符"
    d = np.array([n.duration_s for n in notes])
    p = np.array([n.midi for n in notes])
    co = np.array([abs(n.cents_off) for n in notes])
    sp = np.array([n.spread_cents for n in notes])
    ev = np.array([n.evidence_frac for n in notes])
    ov = sum(1 for k in range(len(notes) - 1)
             if notes[k].end_s > notes[k + 1].onset_s + 1e-9)
    return (f"{len(notes)} 个音符  时长 {d.min()*1000:.0f}–{d.max()*1000:.0f}ms"
            f"（中位 {np.median(d)*1000:.0f}ms）  音高 MIDI {p.min()}–{p.max()}\n"
            f"  离半音偏差 |中位| {np.median(co):.0f} 音分  最大 {co.max():.0f} 音分\n"
            f"  中段散布 中位 {np.median(sp):.0f} 音分  最大 {sp.max():.0f} 音分\n"
            f"  证据占比 中位 {np.median(ev):.2f}  最差 {ev.min():.2f}\n"
            f"  重叠对数 {ov}   短于 85ms {int((d*1000 < 84.9).sum())}\n"
            f"  无证据缺口 {len(gaps)} 处，合计 "
            f"{sum(b-a for a,b in gaps):.2f}s")
