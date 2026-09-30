# -*- coding: utf-8 -*-
"""从人声分轨里只留「正中间」的声音：主唱一般放正中，叠唱 / 和声常往左右铺开（《潮声回响》：没叠唱的主歌左右相关 0.98，
叠唱多的 1:56–2:02 只有 0.26）。每个时刻、每个频率上左右一样（幅度、相位都一样）的留下，不一样的压掉。

    相似度 = 2·Re(L·R*) / (|L|² + |R|²)    —— 1 = 正中间；往一边偏、或者左右相位不一样都会变小
    遮罩 = ((相似度 − 下限) / (1 − 下限))²，截在 0–1；输出 = 遮罩 × (L + R) / 2

不用下载任何模型；缺点：叠唱和主唱落在同一个频率上时，那一格也会被压一点（有点「水声」）。叠唱要是也放正中，这个办法对它没用。
自检：造的「正中一个音 + 只在左边一个音」，输出里正中那个要留下（损失 < 1 dB）、左边那个要压掉（≥ 20 dB）。

    python center_extract.py <人声.wav> <输出.wav> [下限，默认 0.6]
"""
from __future__ import annotations

import pathlib
import sys

import librosa
import numpy as np
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
N_FFT, HOP = 4096, 1024


def center(L: np.ndarray, R: np.ndarray, floor: float = 0.6) -> np.ndarray:
    SL, SR = librosa.stft(L, n_fft=N_FFT, hop_length=HOP), librosa.stft(R, n_fft=N_FFT, hop_length=HOP)
    sim = 2 * np.real(SL * np.conj(SR)) / (np.abs(SL) ** 2 + np.abs(SR) ** 2 + 1e-12)
    mask = np.clip((sim - floor) / (1 - floor), 0, 1) ** 2
    return librosa.istft(mask * (SL + SR) / 2, hop_length=HOP, length=len(L)).astype(np.float32)


def selftest() -> list[str]:
    sr = 22050
    t = np.arange(sr * 3) / sr
    mid = 0.3 * np.sin(2 * np.pi * 440 * t)
    left = 0.3 * np.sin(2 * np.pi * 660 * t)
    out = center((mid + left).astype(np.float32), mid.astype(np.float32))
    spec = np.abs(np.fft.rfft(out[sr:2 * sr]))
    f = np.fft.rfftfreq(sr, 1 / sr)
    band = lambda hz: spec[(f > hz - 5) & (f < hz + 5)].max()                               # noqa: E731
    ref = np.abs(np.fft.rfft(mid[sr:2 * sr]))
    keep_db = 20 * np.log10(band(440) / ref[(f > 435) & (f < 445)].max())
    kill_db = 20 * np.log10(band(660) / (np.abs(np.fft.rfft(left[sr:2 * sr]))[(f > 655) & (f < 665)].max() / 2))
    fails = []
    if keep_db < -1.0:
        fails.append(f"正中那个音损失了 {-keep_db:.1f} dB")
    if kill_db > -20.0:
        fails.append(f"只在左边的那个音只压了 {-kill_db:.1f} dB")
    return fails


def main(src: str, dst: str, floor: str = "0.6") -> int:
    fails = selftest()
    print("自检：", "通过（正中的留下、只在一边的压掉 ≥ 20 dB）" if not fails else fails)
    if fails:
        return 1
    if pathlib.Path(dst).exists():
        raise SystemExit(f"{dst} 已经有了")
    y, sr = sf.read(src, dtype="float32")
    out = center(y[:, 0], y[:, 1], float(floor))
    sf.write(dst, np.stack([out, out], axis=1), sr, subtype="PCM_16")
    e = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)                                    # noqa: E731
    print(f"写出 {dst}：原来 {e((y[:, 0] + y[:, 1]) / 2):.1f} dB → 只留正中 {e(out):.1f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
