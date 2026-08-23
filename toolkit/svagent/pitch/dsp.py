"""自实现的 STFT 与 mel 滤波器组。

为什么不用 librosa / torch.stft：

1. **librosa 的 mel 默认值会漂移。** 模型的 mel 前端和训练时必须逐参数一致，
   把它绑在第三方库的默认值上，等于把一个静默失效的开关交给依赖升级。
   这里的实现与 librosa 1.0.0 的 `filters.mel(htk=False, norm="slaney")` 逐元素对齐
   （验证见 `verify_against_librosa`）。
2. **`torch.stft` 反复调用会触发 OpenMP 运行时冲突**（本机 libiomp5md 已初始化时
   再去初始化 libomp 直接 abort）。官方给的绕法是设 `KMP_DUPLICATE_LIB_OK=TRUE`，
   但它自己写着"可能静默产生错误结果"——本项目不接受这种代价。
   numpy 的 rfft 走 pocketfft，不带 OpenMP。

`stft_mag` 与 `torch.stft(center=True, pad_mode="reflect", window=hann_window(periodic))`
在 float32 精度内一致（实测最大绝对差 3.8e-06）。
"""
from __future__ import annotations

import numpy as np

_F_MIN = 0.0
_F_SP = 200.0 / 3
_MIN_LOG_HZ = 1000.0
_MIN_LOG_MEL = (_MIN_LOG_HZ - _F_MIN) / _F_SP
_LOGSTEP = np.log(6.4) / 27.0


def hz_to_mel(f, htk: bool = False):
    f = np.asarray(f, dtype=float)
    if htk:
        return 2595.0 * np.log10(1.0 + f / 700.0)
    mels = (f - _F_MIN) / _F_SP
    return np.where(f >= _MIN_LOG_HZ,
                    _MIN_LOG_MEL + np.log(np.maximum(f, 1e-12) / _MIN_LOG_HZ) / _LOGSTEP,
                    mels)


def mel_to_hz(m, htk: bool = False):
    m = np.asarray(m, dtype=float)
    if htk:
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    freqs = _F_MIN + _F_SP * m
    return np.where(m >= _MIN_LOG_MEL,
                    _MIN_LOG_HZ * np.exp(_LOGSTEP * (m - _MIN_LOG_MEL)),
                    freqs)


def mel_filterbank(sr: int, n_fft: int, n_mels: int, fmin: float, fmax: float,
                   htk: bool = False, norm: str | None = "slaney") -> np.ndarray:
    """(n_mels, 1 + n_fft//2) 的三角滤波器组。"""
    fftfreqs = np.linspace(0.0, sr / 2.0, 1 + n_fft // 2)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(fmin, htk), hz_to_mel(fmax, htk),
                                  n_mels + 2), htk)
    fdiff = np.diff(mel_f)
    ramps = np.subtract.outer(mel_f, fftfreqs)
    W = np.zeros((n_mels, fftfreqs.size), dtype=np.float64)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        W[i] = np.maximum(0.0, np.minimum(lower, upper))
    if norm == "slaney":
        W *= (2.0 / (mel_f[2:n_mels + 2] - mel_f[:n_mels]))[:, None]
    elif norm is not None:
        raise ValueError("norm 只支持 'slaney' 或 None，收到 %r" % (norm,))
    return W.astype(np.float32)


def hann_periodic(n: int) -> np.ndarray:
    """与 torch.hann_window(n)（periodic=True）一致。注意 np.hanning 是对称窗，不同。"""
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)


def stft_mag(y: np.ndarray, n_fft: int = 1024, hop: int = 160,
             win_length: int = 1024, center: bool = True) -> np.ndarray:
    """返回幅度谱 (1 + n_fft//2, T)，不是功率谱。"""
    win = hann_periodic(win_length)
    if win_length < n_fft:
        pad = n_fft - win_length
        win = np.pad(win, (pad // 2, pad - pad // 2))
    if center:
        y = np.pad(y, (n_fft // 2, n_fft // 2), mode="reflect")
    n_frames = 1 + (y.size - n_fft) // hop
    if n_frames <= 0:
        return np.zeros((1 + n_fft // 2, 0), dtype=np.float32)
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = y[idx] * win[None, :]
    return np.abs(np.fft.rfft(frames, n=n_fft, axis=1)).T.astype(np.float32)


def verify_against_librosa(sr=16000, n_fft=1024, n_mels=128, fmin=30.0, fmax=8000.0):
    """在没有 torch 的进程里跑，检查 mel 滤波器组与 librosa 一致。"""
    import librosa
    ref = librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=n_mels, fmin=fmin, fmax=fmax)
    mine = mel_filterbank(sr, n_fft, n_mels, fmin, fmax)
    return {"max_abs_diff": float(np.abs(ref - mine).max()),
            "ref_max": float(ref.max()), "shape_match": ref.shape == mine.shape}
