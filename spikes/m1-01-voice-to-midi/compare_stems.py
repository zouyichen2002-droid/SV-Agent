# -*- coding: utf-8 -*-
"""比两次分离的结果（例如显卡分的对 CPU 分的）：每条分轨算 差别的信噪比、相关、最大差值。

创作者 10-01：分离换显卡（下 CUDA 版 torch）——「下完先拿《逃跑的天使》比对：显卡分出来的和 CPU 分的要一致，不一致就退回 CPU」。
一致的判据（第一层，波形）：每条分轨 差别信噪比 ≥ 40 dB（差别比信号小 100 倍以上）、相关 ≥ 0.9999。
第二层（结果）另外比：拿显卡分出的主唱跑扒谱，音符和 CPU 版的比（compare_notes）。

    python compare_stems.py <参考分离目录> <新分离目录>
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
SNR_MIN_DB = 40.0
CORR_MIN = 0.9999
STEMS = [
    ("人声", "(vocals)_vocals_mel_band_roformer.wav"),
    ("伴奏", "(other)_vocals_mel_band_roformer.wav"),
    ("主唱", "(Vocals)_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.wav"),
    ("叠唱", "(Instrumental)_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.wav"),
]


def find(d: pathlib.Path, tail: str) -> pathlib.Path:
    hits = [p for p in d.glob("*.wav") if p.name.endswith(tail)]
    if len(hits) != 1:
        raise SystemExit(f"{d} 里以 {tail} 结尾的文件不是正好一个：{[p.name for p in hits]}")
    return hits[0]


def compare(a: np.ndarray, b: np.ndarray) -> dict:
    n = min(len(a), len(b))
    a, b = a[:n].astype(np.float64), b[:n].astype(np.float64)
    diff = a - b
    sig = float(np.sum(a ** 2))
    err = float(np.sum(diff ** 2))
    snr = float("inf") if err == 0 else 10 * np.log10(sig / err)
    corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
    return {"样本差": abs(len(a) - len(b)), "信噪比 dB": round(snr, 1), "相关": round(corr, 6), "最大差": round(float(np.max(np.abs(diff))), 5)}


def main(ref_dir: str, new_dir: str) -> int:
    ref, new = pathlib.Path(ref_dir), pathlib.Path(new_dir)
    bad = []
    for label, tail in STEMS:
        a, sra = sf.read(find(ref, tail))
        b, srb = sf.read(find(new, tail))
        if sra != srb:
            bad.append(f"{label}：采样率不一样 {sra} / {srb}")
            continue
        r = compare(a, b)
        ok = r["信噪比 dB"] >= SNR_MIN_DB and r["相关"] >= CORR_MIN
        print(f"{'ok  ' if ok else 'BAD '} {label}：{r}")
        if not ok:
            bad.append(label)
    print("一致" if not bad else f"不一致：{bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
