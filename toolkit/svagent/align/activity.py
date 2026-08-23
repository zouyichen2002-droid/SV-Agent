"""把声学信号变成「在唱 / 没在唱」的区段。

**关键约束：这条链只用声学信号，完全不看 LRC 时间戳。** 否则拿它去验 LRC 偏移
就是循环论证 —— 和交接文件 §5.4 点名的「用 f0 定音高再用同一 f0 评分」同一类错误。

## 为什么不能用音高证据图当活动掩码（实测教训）

第一版直接把阶段 1 的音高证据图当"在唱"，结果闭运算 250ms 后 188.8s / 229s 都算活动，
最长一段 31.48s，逐行偏移搜索的目标函数全程平顶（δ 不确定度中位 = 整个搜索范围 1.5s）。

根因：**音高证据图回答的是"这一帧有没有可信音高"，不是"这一帧有没有人在唱"。
器乐也有音高**，crepe / rmvpe 照样跟得很稳。

## 用什么

两条 stem 的能量。人声 stem 的**绝对电平**是最干净的判据（带标签锚点实测）：

| 段 | vocals stem rms 中位 |
|---|---|
| 在唱（6 段） | −14.6 … −21.6 dB |
| 无唱（间奏/尾奏） | −27.1 … −31.9 dB |
| 静音 | −72 dB |

单用 vocals/no_vocals 的**能量比**不够：间奏的 75 分位 +3.87dB 高过高潮句的中位
+0.75dB（Demucs 的器乐渗漏）。两个一起用才分得开。

阈值由带标签锚点扫出来（`rms >= -23dB` 且 `ratio >= +2dB`）：
活动 135.1s（对照「410 字 × 0.34 s/字 = 139s」的上界）、70 段、
在唱锚点命中 83.6%、无唱锚点误报 7.1%，分离度 +76.5 个百分点。

**已知局限**：这条判据依赖 Demucs 自己的分离判决，所以它对 f0 估计器与 LRC 独立，
**但对分离器不独立**。最差的一个无唱锚点仍有 19% 误报。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _close(mask: np.ndarray, n: int) -> np.ndarray:
    """闭运算：先膨胀再腐蚀，填掉 <n 帧的洞。"""
    if n <= 0:
        return mask.copy()
    return ~_open(~mask, n)


def _open(mask: np.ndarray, n: int) -> np.ndarray:
    """开运算：去掉 <n 帧的孤立真值。"""
    if n <= 0:
        return mask.copy()
    out = mask.copy()
    for lo, hi in _runs(mask):
        if hi - lo < n:
            out[lo:hi] = False
    return out


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """连续 True 的 [起, 止) 区间。"""
    if mask.size == 0:
        return []
    d = np.diff(mask.astype(np.int8))
    starts = list(np.flatnonzero(d == 1) + 1)
    ends = list(np.flatnonzero(d == -1) + 1)
    if mask[0]:
        starts.insert(0, 0)
    if mask[-1]:
        ends.append(mask.size)
    return list(zip(starts, ends))


@dataclass
class ActivityMask:
    """在唱与否的逐帧掩码 + 区段边界。"""

    hop_s: float
    mask: np.ndarray
    close_s: float
    open_s: float

    @property
    def segments(self) -> list[tuple[float, float]]:
        return [(lo * self.hop_s, hi * self.hop_s) for lo, hi in _runs(self.mask)]

    @property
    def onsets(self) -> np.ndarray:
        """区段起点（秒）。"""
        return np.array([lo * self.hop_s for lo, _ in _runs(self.mask)])

    @property
    def offsets(self) -> np.ndarray:
        return np.array([hi * self.hop_s for _, hi in _runs(self.mask)])

    def duration_in(self, t0: float, t1: float) -> float:
        i0 = max(0, int(round(t0 / self.hop_s)))
        i1 = min(self.mask.size, int(round(t1 / self.hop_s)))
        if i1 <= i0:
            return 0.0
        return float(self.mask[i0:i1].sum()) * self.hop_s

    def fraction_in(self, t0: float, t1: float) -> float:
        i0 = max(0, int(round(t0 / self.hop_s)))
        i1 = min(self.mask.size, int(round(t1 / self.hop_s)))
        if i1 <= i0:
            return 0.0
        return float(self.mask[i0:i1].mean())

    def nearest_onset(self, t: float, window_s: float) -> tuple[float, bool]:
        """离 t 最近的区段起点。找不到就返回 (t, False)。"""
        o = self.onsets
        if o.size == 0:
            return t, False
        k = int(np.argmin(np.abs(o - t)))
        if abs(o[k] - t) <= window_s:
            return float(o[k]), True
        return t, False

    def __repr__(self) -> str:
        segs = self.segments
        tot = sum(b - a for a, b in segs)
        return (f"<ActivityMask {len(segs)} 段 合计 {tot:.1f}s "
                f"占 {100*self.mask.mean():.1f}% 闭{self.close_s*1000:.0f}ms "
                f"开{self.open_s*1000:.0f}ms>")


def frame_energy_db(y: np.ndarray, hop: int, n_frames: int,
                    win: int = 800) -> np.ndarray:
    """逐帧能量（dB），帧中心对齐到 k*hop。win 默认 50ms。"""
    pad = win // 2
    yp = np.pad(np.asarray(y, dtype=np.float64), (pad, pad))
    idx = np.clip(np.arange(win)[None, :] + hop * np.arange(n_frames)[:, None],
                  0, yp.size - 1)
    return 10.0 * np.log10((yp[idx] ** 2).mean(axis=1) + 1e-12)


def from_stems(vocals: np.ndarray, no_vocals: np.ndarray, hop: int, hop_s: float,
               n_frames: int, *, rms_db_min: float = -23.0,
               ratio_db_min: float = 2.0, win: int = 800,
               close_s: float = 0.25, open_s: float = 0.08,
               extra: np.ndarray | None = None) -> ActivityMask:
    """人声活动检测：vocals stem 绝对电平 + vocals/no_vocals 能量比。

    阈值由带标签锚点扫出来，见模块 docstring。`extra` 可以再 AND 一层条件
    （例如音高证据），实测会把段数从 70 打碎到 93、命中从 83.6% 降到 79.8%，
    默认不用。
    """
    n = min(vocals.size, no_vocals.size)
    ev = frame_energy_db(vocals[:n], hop, n_frames, win)
    en = frame_energy_db(no_vocals[:n], hop, n_frames, win)
    m = (ev >= rms_db_min) & ((ev - en) >= ratio_db_min)
    if extra is not None:
        e = np.asarray(extra, dtype=bool)
        if e.size < n_frames:
            e = np.pad(e, (0, n_frames - e.size))
        m &= e[:n_frames]
    m = _close(m, int(round(close_s / hop_s)))
    m = _open(m, int(round(open_s / hop_s)))
    return ActivityMask(hop_s, m, close_s, open_s)


def from_evidence(has_evidence: np.ndarray, hop_s: float,
                  close_s: float = 0.15, open_s: float = 0.08) -> ActivityMask:
    """证据图 → 活动掩码。

    `close_s` 默认 150ms：汉语演唱里字与字之间的证据空洞多在百毫秒量级，
    比这更大的空洞是真的气口或真的没有证据，不该补。
    `open_s` 默认 80ms：短于一个最短音符（85ms，见 gates.stage4）的孤立点是噪声。
    """
    m = np.asarray(has_evidence, dtype=bool)
    m = _close(m, int(round(close_s / hop_s)))
    m = _open(m, int(round(open_s / hop_s)))
    return ActivityMask(hop_s, m, close_s, open_s)
