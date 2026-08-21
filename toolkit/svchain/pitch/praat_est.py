"""Praat / parselmouth（自相关族）。

选它做交叉验证的对象，是因为它和 CREPE / RMVPE 不是同一个算法族：
神经估计器的失败模式（八度错、训练语料偏置）与自相关的失败模式（次谐波锁定、
清音段丢失）不一样。同族互验会一起错。

已知风险：交接文件记载 pyin（差分函数族，与自相关同源）在这份素材上会锁三次
次谐波（139.9–140.6s 处把 68.90 半音报成 50.00）。Praat 很可能继承这个弱点 ——
如果它继承了，那说明整个自相关族在这份素材上不可用，这本身是要记档的结论。
"""
from __future__ import annotations

import numpy as np

from .base import PitchTrack, to_grid


class PraatEstimator:
    name = "praat-ac"
    family = "autocorr"

    def __init__(self, silence_threshold: float = 0.03,
                 voicing_threshold: float = 0.45,
                 octave_cost: float = 0.01,
                 octave_jump_cost: float = 0.35,
                 voiced_unvoiced_cost: float = 0.14):
        self.kw = dict(silence_threshold=silence_threshold,
                       voicing_threshold=voicing_threshold,
                       octave_cost=octave_cost,
                       octave_jump_cost=octave_jump_cost,
                       voiced_unvoiced_cost=voiced_unvoiced_cost)

    @property
    def cache_params(self) -> dict:
        return dict(self.kw)

    def estimate(self, y: np.ndarray, sr: int, n_frames: int,
                 fmin: float = 70.0, fmax: float = 900.0,
                 hop_s: float = 0.010) -> PitchTrack:
        import parselmouth

        snd = parselmouth.Sound(np.ascontiguousarray(y, dtype=np.float64), sampling_frequency=sr)
        p = snd.to_pitch_ac(time_step=hop_s, pitch_floor=fmin, pitch_ceiling=fmax, **self.kw)
        arr = p.selected_array
        src_f0 = arr["frequency"].astype(np.float64)
        src_st = arr["strength"].astype(np.float64)
        src_f0[src_f0 <= 0] = np.nan  # Praat 用 0 表示无声
        f0, conf = to_grid(p.xs(), src_f0, src_st, n_frames, hop_s)
        return PitchTrack(self.name, self.family, hop_s, f0, conf,
                          {"fmin": fmin, "fmax": fmax, **self.kw})
