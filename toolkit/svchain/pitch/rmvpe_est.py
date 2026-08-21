"""RMVPE（歌声专用 f0，神经族）。

选它的理由：交接文件 §5.3 记载的三个坑（气声段误判无声、锁次谐波、混叠段跟错声部）
都是"通用语音 f0"在歌声上的典型失效。RMVPE 是在歌声上训的，且输出 360 维音高显著图
而不是单值，能直接给出置信度。

权重是纯 state_dict，架构见 rmvpe_arch.py（从权重形状反推）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from .base import PitchTrack

# ---- 前端参数：由 scripts/calibrate_rmvpe.py 实测确定，不是照约定抄的 ----
# htk=True 是关键。按 Slaney 刻度（librosa 默认）喂，模型照样输出干净的单峰显著图，
# 但音高系统性偏低 ~570 音分 —— 一个不抛异常的静默错误。
# power=2（功率谱）优于 power=1（幅度谱）：正弦误差中位 1.9 vs 3.0 音分，八度错 4.6% vs 6.8%。
MEL = dict(n_fft=1024, win_length=1024, hop_length=160, n_mels=128,
           fmin=30.0, fmax=8000.0, clamp=1e-5, power=2, htk=True, norm="slaney")
N_BINS = 360
CENTS_PER_BIN = 20.0              # 重采样法实测 20.202 ± 0.130（六个倍率，不借其它估计器）
CENTS_BASE = 1997.3796077132352   # 稳健标定实测 1998.6，与此约定值差 +1.2 音分
CENTS_REF_HZ = 10.0               # bin 0 = 10*2^(1997.38/1200) ≈ 31.70 Hz
DOWNSAMPLE = 32   # encoder 5 次 2x 池化 → 时间维必须是 32 的倍数


class RmvpeEstimator:
    name = "rmvpe"
    family = "neural-singing"

    def __init__(self, weights, device: str = "cpu",
                 salience_thred: float = 0.03, chunk_frames: int = 3200,
                 margin_frames: int = 320, mel: dict | None = None,
                 cents_base: float = CENTS_BASE, cents_per_bin: float = CENTS_PER_BIN):
        self.weights = Path(weights)
        self.device = device
        self.thred = salience_thred
        self.chunk_frames = chunk_frames
        self.margin_frames = margin_frames
        # mel 前端与 bin→cents 映射都可覆盖，因为它们是"必须靠实测确定"的量，
        # 不是可以照着文档抄的常数。self_check() 就是用来定它们的。
        self.mel = {**MEL, **(mel or {})}
        self.cents_base = cents_base
        self.cents_per_bin = cents_per_bin
        self._model = None
        self._mel_basis = None
        self._window = None
        self.load_report: dict = {}

    @property
    def cache_params(self) -> dict:
        # mel 前端与映射常数必须进缓存键 —— 改了前端却读到旧缓存，
        # 正是本项目要防的那类静默错误。
        return {**{f"mel_{k}": v for k, v in sorted(self.mel.items())},
                "thred": self.thred,
                "cents_base": self.cents_base,
                "cents_per_bin": self.cents_per_bin}

    # ---------- 模型 ----------
    def _load(self):
        if self._model is not None:
            return self._model
        from .rmvpe_arch import E2E

        m = E2E(n_blocks=4, n_gru=1, kernel_size=(2, 2))
        sd = torch.load(self.weights, map_location="cpu", weights_only=True)
        # strict=True：结构与权重键必须完全一致。缺键会让该层保持随机初始化，
        # 那种失败不报异常、只是静默输出垃圾 —— 是本项目点名要防的失败类型。
        res = m.load_state_dict(sd, strict=True)
        self.load_report = {
            "missing": list(getattr(res, "missing_keys", []) or []),
            "unexpected": list(getattr(res, "unexpected_keys", []) or []),
            "n_keys": len(sd),
            "n_params": sum(p.numel() for p in m.parameters()),
        }
        m.eval().to(self.device)
        self._model = m
        return m

    def _mel(self, y: np.ndarray, sr: int) -> torch.Tensor:
        """log-mel 前端。STFT 与滤波器组都自实现，见 dsp.py 里的理由。"""
        from .dsp import mel_filterbank, stft_mag

        if sr != 16000:
            raise ValueError("RMVPE 只在 16kHz 上有效，收到 %d" % sr)
        p = self.mel
        if self._mel_basis is None:
            self._mel_basis = torch.from_numpy(mel_filterbank(
                sr, p["n_fft"], p["n_mels"], p["fmin"], p["fmax"],
                htk=p.get("htk", False), norm=p.get("norm", "slaney")))
        spec = torch.from_numpy(stft_mag(
            np.ascontiguousarray(y, dtype=np.float32),
            n_fft=p["n_fft"], hop=p["hop_length"], win_length=p["win_length"]))
        if p.get("power", 1) != 1:
            spec = spec ** p["power"]
        mel = self._mel_basis @ spec
        if p.get("gain", 1.0) != 1.0:
            mel = mel * p["gain"]
        return torch.log(torch.clamp(mel, min=p["clamp"]))   # (n_mels, T)

    def _salience(self, mel: torch.Tensor) -> np.ndarray:
        """分块跑网络，只保留每块中段，避免边界效应，也避免一次性吃满内存。"""
        m = self._load()
        T = mel.shape[-1]
        out = np.zeros((T, N_BINS), dtype=np.float32)
        step = self.chunk_frames
        mg = self.margin_frames
        pos = 0
        with torch.no_grad():
            while pos < T:
                lo = max(0, pos - mg)
                hi = min(T, pos + step + mg)
                seg = mel[:, lo:hi]
                n = seg.shape[-1]
                pad = (n + DOWNSAMPLE - 1) // DOWNSAMPLE * DOWNSAMPLE - n
                if pad:
                    seg = torch.nn.functional.pad(seg, (0, pad), mode="constant")
                sal = m(seg.unsqueeze(0).to(self.device))[0, :n].cpu().numpy()
                keep_lo = pos - lo
                take = min(step, T - pos)
                out[pos:pos + take] = sal[keep_lo:keep_lo + take]
                pos += step
        return out

    def _decode(self, sal: np.ndarray, thred: float):
        """argmax 附近 +-4 bin 的显著度加权平均 → cents → Hz。

        不用纯 argmax：那样分辨率被钉在 20 音分（0.2 半音）上，
        对 0.5 半音的一致性判据来说太粗。
        """
        mapping = np.pad(self.cents_per_bin * np.arange(N_BINS) + self.cents_base, (4, 4))
        padded = np.pad(sal, ((0, 0), (4, 4)))
        centre = np.argmax(sal, axis=1) + 4
        idx = centre[:, None] + np.arange(-4, 5)[None, :]
        rows = np.arange(sal.shape[0])[:, None]
        w = padded[rows, idx]
        c = mapping[idx]
        wsum = w.sum(axis=1)
        cents = np.divide((w * c).sum(axis=1), wsum,
                          out=np.zeros_like(wsum), where=wsum > 0)
        conf = sal.max(axis=1)
        f0 = CENTS_REF_HZ * np.power(2.0, cents / 1200.0)
        f0[conf <= thred] = np.nan
        f0[cents <= 0] = np.nan
        return f0.astype(np.float64), conf.astype(np.float64)

    # ---------- 接口 ----------
    def estimate(self, y: np.ndarray, sr: int, n_frames: int,
                 fmin: float = 70.0, fmax: float = 900.0,
                 hop_s: float = 0.010) -> PitchTrack:
        if abs(hop_s - MEL["hop_length"] / sr) > 1e-9:
            raise ValueError("RMVPE 原生 hop 是 %.1fms，配置要的是 %.1fms"
                             % (MEL["hop_length"] / sr * 1000, hop_s * 1000))
        sal = self._salience(self._mel(y, sr))
        f0, conf = self._decode(sal, self.thred)
        f0 = _fit(f0, n_frames, np.nan)
        conf = _fit(conf, n_frames, 0.0)
        f0 = np.where((f0 >= fmin) & (f0 <= fmax), f0, np.nan)
        return PitchTrack(self.name, self.family, hop_s, f0, conf,
                          {"thred": self.thred, "fmin": fmin, "fmax": fmax})

    # ---------- 自检 ----------
    def self_check(self, sr: int = 16000) -> dict:
        """两道验证：strict 加载 + 合成信号的绝对真值。

        合成正弦是**不依赖任何其它估计器**的真值。mel 参数、cents 基准常数、
        解码里的 +-4 bin 加权，任一写错都会在这里显形。
        """
        self._load()
        rep = {"load": dict(self.load_report), "sine": [], "chirp": None}
        dur = 2.0
        t = np.arange(int(sr * dur)) / sr
        for f in (98.0, 110.0, 220.0, 261.6256, 440.0, 523.2511, 659.2551, 880.0):
            # 加少量泛音，纯正弦对 mel 前端偏理想
            y = (0.6 * np.sin(2 * np.pi * f * t)
                 + 0.2 * np.sin(4 * np.pi * f * t)
                 + 0.1 * np.sin(6 * np.pi * f * t)).astype(np.float32)
            tr = self.estimate(y, sr, len(t) // 160 + 1, fmin=60.0, fmax=1200.0)
            core = tr.f0_hz[10:-10]
            v = core[np.isfinite(core)]
            if v.size == 0:
                rep["sine"].append({"true_hz": f, "got_hz": None, "err_cents": None,
                                    "voiced_frac": 0.0})
                continue
            got = float(np.median(v))
            rep["sine"].append({
                "true_hz": f, "got_hz": got,
                "err_cents": 1200.0 * np.log2(got / f),
                "voiced_frac": float(np.isfinite(core).mean()),
            })
        # 线性 chirp：检查时间轴没有整体偏移
        fa, fb = 200.0, 600.0
        ch = np.sin(2 * np.pi * (fa * t + (fb - fa) / (2 * dur) * t ** 2)).astype(np.float32)
        tr = self.estimate(ch, sr, len(t) // 160 + 1, fmin=60.0, fmax=1200.0)
        k = np.isfinite(tr.f0_hz)
        if k.sum() > 20:
            tt = tr.times[k]
            expect = fa + (fb - fa) * tt / dur
            err = 1200.0 * np.log2(tr.f0_hz[k] / expect)
            rep["chirp"] = {"median_err_cents": float(np.median(err)),
                            "p90_abs_cents": float(np.percentile(np.abs(err), 90)),
                            "voiced_frac": float(k.mean())}
        return rep


def _fit(a: np.ndarray, n: int, pad) -> np.ndarray:
    if a.size == n:
        return a
    if a.size > n:
        return a[:n]
    return np.concatenate([a, np.full(n - a.size, pad)])
