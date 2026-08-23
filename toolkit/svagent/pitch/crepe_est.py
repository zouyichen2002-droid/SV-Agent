"""torchcrepe（CREPE，神经族）。

不用 torchcrepe 自带的 load（它依赖 torchaudio.load，本机需要 torchcodec 才能用），
一律从外部喂 tensor。
"""
from __future__ import annotations

import numpy as np
import torch

from .base import PitchTrack, n_frames_for


class CrepeEstimator:
    name = "torchcrepe"
    family = "neural"

    def __init__(self, model: str = "full", batch_size: int = 512,
                 device: str = "cpu", conf_floor: float = 0.0):
        self.model = model
        self.batch_size = batch_size
        self.device = device
        self.conf_floor = conf_floor

    @property
    def cache_params(self) -> dict:
        return {"model": self.model, "conf_floor": self.conf_floor}

    def estimate(self, y: np.ndarray, sr: int, n_frames: int,
                 fmin: float = 70.0, fmax: float = 900.0,
                 hop_s: float = 0.010) -> PitchTrack:
        import torchcrepe

        hop = round(sr * hop_s)
        a = torch.from_numpy(np.ascontiguousarray(y, dtype=np.float32))[None]
        f0, per = torchcrepe.predict(
            a, sr, hop_length=hop, fmin=fmin, fmax=fmax, model=self.model,
            batch_size=self.batch_size, device=self.device, return_periodicity=True,
        )
        f0 = f0.squeeze(0).cpu().numpy().astype(np.float64)
        per = per.squeeze(0).cpu().numpy().astype(np.float64)

        # torchcrepe 原生 hop 就是我们的 hop，帧中心对齐，长度可能差 1
        f0 = _fit(f0, n_frames, np.nan)
        per = _fit(per, n_frames, 0.0)
        f0 = np.where(per >= self.conf_floor, f0, np.nan) if self.conf_floor > 0 else f0
        # CREPE 从不输出「无声」，它总给一个 f0 —— 越界值当无效
        f0 = np.where((f0 >= fmin) & (f0 <= fmax), f0, np.nan)
        return PitchTrack(self.name, self.family, hop_s, f0, per,
                          {"model": self.model, "fmin": fmin, "fmax": fmax})


def _fit(a: np.ndarray, n: int, pad) -> np.ndarray:
    if a.size == n:
        return a
    if a.size > n:
        return a[:n]
    return np.concatenate([a, np.full(n - a.size, pad)])
