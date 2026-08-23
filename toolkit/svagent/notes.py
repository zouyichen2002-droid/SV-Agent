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

from dataclasses import dataclass, field

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


# ---------------------------------------------------------------------------
# 歌词分配：用字起音切分音符
# ---------------------------------------------------------------------------

@dataclass
class LyricFit:
    """歌词分配的结果与账目。每一项都要能对上，不允许有"去哪了不知道"的字。"""
    notes: list[Note]
    n_chars_in: int = 0
    assigned: int = 0            # 拿到音符的字
    dropped_no_note: int = 0     # 无音高证据，进缺口清单
    dropped_too_short: int = 0   # 拆开会造出 <min_ms 的碎片，放弃拆
    splits: int = 0              # 因字起音而拆开的音符数
    melisma: int = 0             # 没有字、承接前一个字的音符（歌词写 "-"）
    gaps: list[tuple[float, str]] = field(default_factory=list)  # (时刻, 字)

    @property
    def assign_rate(self) -> float:
        return self.assigned / self.n_chars_in if self.n_chars_in else 0.0

    def summary(self) -> str:
        return (f"字 {self.n_chars_in} → 分配 {self.assigned}"
                f"（{100*self.assign_rate:.1f}%）  "
                f"无音高证据丢弃 {self.dropped_no_note}  "
                f"拆分受最短时长限制丢弃 {self.dropped_too_short}\n"
                f"  音符 {len(self.notes)} 个：因字起音拆出 {self.splits} 个，"
                f"承接前字（歌词 '-'）{self.melisma} 个")


def assign_lyrics(ns: list[Note], char_times: list[tuple[float, str]], *,
                  min_ms: float = 85.0, onset_tol_s: float = 0.085,
                  melisma_lyric: str = "-") -> LyricFit:
    """把字按起音分配到音符上，必要时**在字起音处把音符拆开**。

    为什么必须拆：实测（《潮声回响》主唱 stem，300 个已对齐的字）

      字起音落在音符起音 ±85ms      59.0%
      字起音落在**音符内部**        26.3%   ← 一个长音符跨了多个字
      字起音落在**无音符的空隙**    14.7%   ← 该字没有音高证据

    第二类占四分之一，不拆就有四分之一的字挂不上音符。第三类不拆也解决不了 ——
    那是真的没有证据，按项目原则**不给音符**，进缺口清单交给耳朵，不虚构。

    没有字的音符歌词写 `-`（SynthV 里表示承接前一个音节），而不是留 `la`：
    留 `la` 会在拖腔处多唱出一个音节。
    """
    notes = sorted((Note(n.onset_s, n.duration_s, n.midi, n.lyric, n.evidence_frac,
                         n.midi_median, n.n_sources, n.spread_cents) for n in ns),
                   key=lambda n: n.onset_s)
    fit = LyricFit(notes=notes, n_chars_in=len(char_times))
    min_s = min_ms / 1000.0
    owner: dict[int, str] = {}      # note id(index) -> 字

    for t, ch in sorted(char_times):
        # 1) 起音附近已有音符 → 直接挂上
        best, bd = -1, 1e9
        for i, n in enumerate(notes):
            d = abs(n.onset_s - t)
            if d < bd:
                best, bd = i, d
        if bd <= onset_tol_s and best not in owner:
            owner[best] = ch
            fit.assigned += 1
            continue
        # 2) 落在某个音符内部 → 在该处拆开
        host = next((i for i, n in enumerate(notes)
                     if n.onset_s < t < n.end_s), -1)
        if host >= 0:
            n = notes[host]
            left = t - n.onset_s
            right = n.end_s - t
            if left >= min_s and right >= min_s:
                tail = Note(t, right, n.midi, ch, n.evidence_frac,
                            n.midi_median, n.n_sources, n.spread_cents)
                n.duration_s = left
                notes.insert(host + 1, tail)
                owner = {(i + 1 if i > host else i): v for i, v in owner.items()}
                owner[host + 1] = ch
                fit.splits += 1
                fit.assigned += 1
                continue
            # 拆不动：若宿主还没被占用，就整个给它
            if host not in owner:
                owner[host] = ch
                fit.assigned += 1
            else:
                fit.dropped_too_short += 1
                fit.gaps.append((t, ch))
            continue
        # 3) 空隙里，没有音高证据 → 不写
        fit.dropped_no_note += 1
        fit.gaps.append((t, ch))

    for i, n in enumerate(notes):
        if i in owner:
            n.lyric = owner[i]
        else:
            n.lyric = melisma_lyric
            fit.melisma += 1
    fit.notes = notes
    return fit


def notes_from_chars(char_times: list[tuple[float, str]], f0_hz: np.ndarray,
                     hop_s: float, *, n_agree: np.ndarray | None = None,
                     min_ms: float = 85.0, max_s: float = 1.70,
                     tail_s: float = 0.60,
                     min_evidence_frac: float = 0.35,
                     smooth_ms: float = 150.0,
                     split_min_ms: float = 140.0,
                     melisma_lyric: str = "-") -> tuple[list[Note], list, dict]:
    """**字定边界、音高取证据**。这是正确的构建方向。

    先按音高造音符再把字塞进去是错的：实测那样做只有 65–70% 的字能挂上音符，
    其余因为「拆出的片段短于 85ms」或「宿主音符已被占用」被丢掉 ——
    而丢掉的原因全在构建方式，不在素材。

    反过来：

      音符 k 的跨度 = [第 k 个字的起音, 第 k+1 个字的起音)，上限 max_s
      音符 k 的音高 = 该跨度**中段 60%** 上音高证据的中位（ADR-0001 已确证的做法）
      跨度内证据不足 → **不产出音符**，该字进缺口清单

    这样每个字最多一个音符、几何天然正确（不重叠、边界即字界），
    且**没有任何一个音符的音高是猜的** —— 上一次失败的直接原因是
    21% 的音符从邻居抄音高，这里结构上不可能发生。

    `split_min_ms` 以上的音符若内部音高有明显变化（拖腔），再拆成多个，
    后续音符歌词写 `-`（SynthV 里表示承接前一个音节）。
    """
    ct = sorted(char_times)
    out: list[Note] = []
    gaps: list[tuple[float, str]] = []
    stat = {"chars": len(ct), "with_note": 0, "no_evidence": 0,
            "too_short": 0, "melisma_split": 0}
    midi_all = hz_to_midi(f0_hz)
    sm = _rolling_median(midi_all, int(round(smooth_ms / 1000 / hop_s)))

    for k, (t, ch) in enumerate(ct):
        end = ct[k + 1][0] if k + 1 < len(ct) else t + tail_s
        end = min(end, t + max_s)
        if (end - t) * 1000 < min_ms:
            stat["too_short"] += 1
            gaps.append((t, ch))
            continue
        i0, i1 = int(round(t / hop_s)), min(int(round(end / hop_s)), f0_hz.size)
        if i1 <= i0:
            stat["too_short"] += 1
            gaps.append((t, ch))
            continue
        span = midi_all[i0:i1]
        ev = float(np.isfinite(span).mean())
        if ev < min_evidence_frac:
            stat["no_evidence"] += 1
            gaps.append((t, ch))
            continue

        # 中段 60% 取中位
        lo = i0 + int((i1 - i0) * 0.2)
        hi = i1 - int((i1 - i0) * 0.2)
        core = midi_all[lo:hi] if hi > lo else span
        core = core[np.isfinite(core)]
        if core.size == 0:
            stat["no_evidence"] += 1
            gaps.append((t, ch))
            continue
        ns_ = 0.0
        if n_agree is not None:
            w = n_agree[i0:i1]
            w = w[w > 0]
            ns_ = float(w.mean()) if w.size else 0.0

        # 拖腔：跨度够长且内部平滑音高分成了不同半音，就再拆
        pieces: list[tuple[int, int, float]] = []
        if (end - t) * 1000 >= split_min_ms:
            q = np.where(np.isfinite(sm[i0:i1]), np.round(sm[i0:i1]), np.nan)
            runs = [(a, b, v) for a, b, v in _runs_of(q)
                    if (b - a) * hop_s * 1000 >= min_ms]
            if len(runs) >= 2:
                pieces = [(i0 + a, i0 + b, v) for a, b, v in runs]
        if not pieces:
            pieces = [(i0, i1, float(np.median(core)))]

        for j, (a, b, val) in enumerate(pieces):
            c2 = midi_all[a + int((b - a) * 0.2): b - int((b - a) * 0.2)]
            c2 = c2[np.isfinite(c2)]
            med = float(np.median(c2)) if c2.size else float(val)
            out.append(Note(
                onset_s=a * hop_s,
                duration_s=(b - a) * hop_s,
                midi=int(round(med)),
                lyric=ch if j == 0 else melisma_lyric,
                evidence_frac=float(np.isfinite(midi_all[a:b]).mean()),
                midi_median=med,
                n_sources=ns_,
                spread_cents=float(np.percentile(c2, 75) - np.percentile(c2, 25)) * 100
                if c2.size > 3 else 0.0,
            ))
        stat["with_note"] += 1
        stat["melisma_split"] += max(0, len(pieces) - 1)

    # 几何收尾：消重叠只截前一个的尾，不拉长任何音符
    out.sort(key=lambda n: n.onset_s)
    for i in range(len(out) - 1):
        ov = out[i].end_s - out[i + 1].onset_s
        if ov > 0:
            out[i].duration_s = max(min_ms / 1000, out[i].duration_s - ov)
    return out, gaps, stat


def enforce_geometry(ns: list[Note], *, min_ms: float = 85.0,
                     max_s: float = 1.70) -> tuple[list[Note], dict]:
    """最终几何强制：0 重叠、时长全部在 [min_ms, max_s] 内。

    为什么需要单独一道：上游的字起音已经摊开到 ≥85ms，但
    `int(round(t / hop_s))` 的帧取整会把 85ms 算成 8 帧 = 80ms，
    于是产出 80ms 的音符和少量重叠。**门槛是硬的（gates.stage4：0 重叠、≥85ms），
    不能靠"上游应该已经保证了"来交差。**

    处理顺序刻意固定：先按下一个音符的起音截尾（不拉长任何音符），
    再丢掉截完仍不足 min_ms 的。丢掉的音符如果带字，会被记进 dropped_with_lyric，
    必须上报而不是静默消失。
    """
    out = sorted((n for n in ns), key=lambda n: n.onset_s)
    stat = {"trimmed": 0, "dropped": 0, "dropped_with_lyric": 0, "capped": 0,
            "absorbed_melisma": 0}

    # 带字音符优先保住：若它截尾后不足 min_ms，而紧跟的是承接音符（'-'），
    # 就把那个 '-' 吞掉、占用它的跨度。不这样做的话实测会丢掉 21 个带字音符
    # —— 丢的全是带字的，等于用几何门槛换掉了歌词覆盖率，方向反了。
    i = 0
    while i < len(out) - 1:
        n, m = out[i], out[i + 1]
        if (n.lyric not in ("-", "") and m.lyric == "-"
                and (m.onset_s - n.onset_s) * 1000 < min_ms
                and (m.end_s - n.onset_s) <= max_s):
            n.duration_s = m.end_s - n.onset_s
            del out[i + 1]
            stat["absorbed_melisma"] += 1
            continue
        i += 1

    keep: list[Note] = []
    for i, n in enumerate(out):
        nxt = out[i + 1].onset_s if i + 1 < len(out) else None
        end = n.end_s
        if nxt is not None and end > nxt:
            end = nxt
            stat["trimmed"] += 1
        if end - n.onset_s > max_s:
            end = n.onset_s + max_s
            stat["capped"] += 1
        dur = end - n.onset_s
        if dur * 1000 < min_ms - 1e-9:
            stat["dropped"] += 1
            if n.lyric not in ("-", "la", ""):
                stat["dropped_with_lyric"] += 1
            continue
        n.duration_s = dur
        keep.append(n)
    # 丢掉音符后可能出现"承接"音符没了前驱的情况：'-' 开头是无效的
    for i, n in enumerate(keep):
        if n.lyric == "-" and (i == 0 or keep[i - 1].lyric == ""):
            n.lyric = "la"
    return keep, stat
