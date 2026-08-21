"""音高估计器的公共接口与帧栅格对齐。

设计要点：
- 所有估计器输出到**同一条 10ms 帧栅格**上，否则无法逐帧比较。
- 无声帧一律 NaN，不用 0 —— 0 会在 log 域变成 -inf 并污染统计。
- 每个估计器自报 `family`（算法族）。跨族一致比同族一致更有说服力：
  两个都在相近语料上训练的神经估计器可能共享同一种失败模式（例如八度错），
  自相关族与神经族的失败模式不同。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


def hz_to_cents(f0: np.ndarray, ref_hz: float = 10.0) -> np.ndarray:
    out = np.full_like(f0, np.nan, dtype=np.float64)
    ok = np.isfinite(f0) & (f0 > 0)
    out[ok] = 1200.0 * np.log2(f0[ok] / ref_hz)
    return out


def hz_to_midi(f0: np.ndarray) -> np.ndarray:
    out = np.full_like(f0, np.nan, dtype=np.float64)
    ok = np.isfinite(f0) & (f0 > 0)
    out[ok] = 69.0 + 12.0 * np.log2(f0[ok] / 440.0)
    return out


@dataclass
class PitchTrack:
    """一条对齐到公共栅格的 f0 轨迹。"""

    name: str
    family: str  # "neural" | "autocorr" | "difference" ...
    hop_s: float
    f0_hz: np.ndarray      # (N,) 无声处 NaN
    confidence: np.ndarray  # (N,) 0..1，语义由估计器自定，仅用于同一估计器内部比较
    params: dict

    @property
    def times(self) -> np.ndarray:
        return np.arange(self.f0_hz.size) * self.hop_s

    @property
    def voiced(self) -> np.ndarray:
        return np.isfinite(self.f0_hz)

    @property
    def cents(self) -> np.ndarray:
        return hz_to_cents(self.f0_hz)

    @property
    def midi(self) -> np.ndarray:
        return hz_to_midi(self.f0_hz)

    def gated(self, min_conf: float) -> "PitchTrack":
        f = self.f0_hz.copy()
        f[self.confidence < min_conf] = np.nan
        return PitchTrack(self.name, self.family, self.hop_s, f, self.confidence,
                          {**self.params, "min_conf": min_conf})

    def __repr__(self) -> str:
        v = int(self.voiced.sum())
        return (f"<PitchTrack {self.name}({self.family}) {self.f0_hz.size}帧 "
                f"有声{v}({100*v/max(1,self.f0_hz.size):.1f}%)>")


class Estimator(Protocol):
    name: str
    family: str

    def estimate(self, y: np.ndarray, sr: int, n_frames: int) -> PitchTrack:
        """y 为单声道 float32；返回长度恰为 n_frames 的轨迹。"""
        ...


def n_frames_for(n_samples: int, sr: int, hop_s: float) -> int:
    """公共栅格的帧数：帧中心落在 k*hop 上，k=0..N-1。"""
    hop = round(sr * hop_s)
    return n_samples // hop + 1


def to_grid(src_times: np.ndarray, src_f0: np.ndarray, src_conf: np.ndarray,
            n_frames: int, hop_s: float, max_gap_s: float | None = None
            ) -> tuple[np.ndarray, np.ndarray]:
    """把估计器原生时间轴上的值搬到公共栅格。

    用最近邻而不是线性插值 —— f0 在八度跳变处线性插值会造出物理上不存在的中间值。
    超过 max_gap_s（默认半个 hop）没有源帧的位置置 NaN，不外推。
    """
    if max_gap_s is None:
        max_gap_s = hop_s * 0.5 + 1e-9
    tgt = np.arange(n_frames) * hop_s
    f0 = np.full(n_frames, np.nan)
    conf = np.zeros(n_frames)
    if src_times.size == 0:
        return f0, conf
    idx = np.searchsorted(src_times, tgt)
    idx = np.clip(idx, 1, src_times.size - 1) if src_times.size > 1 else np.zeros_like(idx)
    left = np.clip(idx - 1, 0, src_times.size - 1)
    right = np.clip(idx, 0, src_times.size - 1)
    pick = np.where(np.abs(src_times[left] - tgt) <= np.abs(src_times[right] - tgt), left, right)
    near = np.abs(src_times[pick] - tgt) <= max_gap_s
    f0[near] = src_f0[pick[near]]
    conf[near] = src_conf[pick[near]]
    return f0, conf
