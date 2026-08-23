# -*- coding: utf-8 -*-
"""识别 RMVPE 前向里那些「权重形状分辨不出来」的选择。

权重是纯 state_dict。`load_state_dict(strict=True)` 能保证**层的形状**对，
但保证不了三件事，因为它们不改变任何张量的形状：

  1. `concat_order`  —— decoder 里 上采样结果 与 skip 连接 的拼接先后
  2. `flatten_mode`  —— (B,3,T,128) 摊平成 GRU 输入 384 维时，通道在外还是频率在外
  3. `input_layout`  —— mel 送进 unet 时时间轴放行还是放列（128 和 T 都能被 32 整除，
                        两种都不报错）

写错这三个中任何一个，模型都**照样跑、照样输出一个单峰的显著图**，只是数值是错的。
这正是 ADR-0001 里点名的最危险失败类型：不抛异常，静默给出偏掉的结果。

**判据（完全自洽，不借任何其它估计器）**：
把同一段真实歌声按倍率 r 重采样，音高必然位移 `1200·log2(r)` 音分。
若模型正确且输出轴是等间距 cents bin，则

    Δbin(r) = 1200·log2(r) / 每bin音分

对多个 r，斜率必须是**同一个常数**。斜率随 r 漂移 = 配置错。
配套看峰值显著度：喂对的模型在干净人声上应该给出高置信峰。

用法: python scripts/identify_rmvpe_forward.py [song_id]
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import config
from svagent.audio import load_mono
from svagent.pitch.rmvpe_arch import E2E
from svagent.pitch.rmvpe_est import RmvpeEstimator

# 覆盖 ±1 个八度的重采样倍率
FACTORS = [0.5, 0.63, 0.79, 1.26, 1.587, 2.0]
SEG = (23.6, 53.6)   # 确定在唱的一段主歌


def lsq(x, y):
    """闭式一元最小二乘。不用 np.polyfit —— 它走 LAPACK，在已加载 torch 的进程里 abort。"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    if sxx == 0:
        return float("nan"), float("nan"), float("nan")
    a = float(((x - xm) * (y - ym)).sum() / sxx)
    b = float(ym - a * xm)
    r = y - (a * x + b)
    return a, b, float(np.sqrt((r ** 2).mean()))


def resample(y: np.ndarray, factor: float) -> np.ndarray:
    n = int(y.size / factor)
    s = np.arange(n) * factor
    i0 = np.floor(s).astype(np.int64)
    i1 = np.minimum(i0 + 1, y.size - 1)
    f = (s - i0).astype(np.float32)
    return ((1 - f) * y[i0] + f * y[i1]).astype(np.float32)


def peak(sal: np.ndarray, half: int = 4):
    b0 = np.argmax(sal, axis=1)
    pad = np.pad(sal, ((0, 0), (half, half)))
    idx = (b0 + half)[:, None] + np.arange(-half, half + 1)[None, :]
    w = pad[np.arange(sal.shape[0])[:, None], idx]
    ws = w.sum(axis=1)
    c = np.divide((w * (idx - half)).sum(axis=1), ws, out=b0.astype(np.float64), where=ws > 0)
    return c, sal.max(axis=1)


def main() -> int:
    song_id = sys.argv[1] if len(sys.argv) > 1 else "chaosheng"
    cfg = config.load()
    song = cfg.song(song_id)
    song.require("vocals")
    P = cfg.pitch

    y = load_mono(song.vocals, P.sr)
    seg = y[int(SEG[0] * P.sr):int(SEG[1] * P.sr)]
    print(f"探针片段 {SEG[0]:.1f}–{SEG[1]:.1f}s（{seg.size/P.sr:.1f}s 真实歌声）")
    print(f"重采样倍率 {FACTORS}  → 音高位移 "
          f"{[round(1200*np.log2(f), 1) for f in FACTORS]} 音分\n")

    sd = torch.load(cfg.model("rmvpe"), map_location="cpu", weights_only=True)
    front = RmvpeEstimator(cfg.model("rmvpe"))   # 只用它的 _mel

    combos = list(itertools.product(("up_first", "skip_first"),
                                   ("channel_major", "freq_major"),
                                   ("time_rows", "time_cols")))
    print(f"{'concat':<11}{'flatten':<15}{'layout':<11}"
          f"{'斜率均值':>9}{'斜率标准差':>11}{'线性残差':>9}{'峰值均值':>9}")
    print("-" * 76)
    results = []
    for concat, flat, layout in combos:
        m = E2E(4, 1, (2, 2), concat_order=concat, flatten_mode=flat, input_layout=layout)
        m.load_state_dict(sd, strict=True)
        m.eval()

        def run(a):
            mel = front._mel(a, P.sr)
            T = mel.shape[-1]
            pad = (T + 31) // 32 * 32 - T
            if pad:
                mel = torch.nn.functional.pad(mel, (0, pad))
            with torch.no_grad():
                sal = m(mel.unsqueeze(0))[0, :T].numpy()
            return peak(sal)

        b0, c0 = run(seg)
        k0 = c0 > 0.3
        if k0.sum() < 100:
            print(f"{concat:<11}{flat:<15}{layout:<11}   基准高置信帧不足 "
                  f"({int(k0.sum())})  峰值均值 {c0.mean():.3f}")
            continue
        ref = float(np.median(b0[k0]))
        slopes, shifts, dbins = [], [], []
        for fac in FACTORS:
            b1, c1 = run(resample(seg, fac))
            k1 = c1 > 0.3
            if k1.sum() < 100:
                continue
            d = float(np.median(b1[k1])) - ref
            sh = 1200.0 * np.log2(fac)
            if abs(d) > 1e-6:
                slopes.append(sh / d)
                shifts.append(sh)
                dbins.append(d)
        if len(slopes) < 4:
            print(f"{concat:<11}{flat:<15}{layout:<11}   有效倍率不足 ({len(slopes)})")
            continue
        a, _, r = lsq(dbins, shifts)
        sl = np.array(slopes)
        print(f"{concat:<11}{flat:<15}{layout:<11}"
              f"{sl.mean():9.3f}{sl.std():11.3f}{r:9.1f}{c0.mean():9.3f}")
        results.append((float(sl.std()), concat, flat, layout, float(sl.mean()),
                        a, r, float(c0.mean()), list(zip(FACTORS, dbins))))

    if not results:
        print("\n全部配置都拿不到足够高置信帧 —— 问题不在这三个开关。")
        return 1

    results.sort()
    print("\n=== 斜率最稳定的配置 ===")
    for std, concat, flat, layout, mean, a, r, cm, det in results[:3]:
        print(f"  {concat} / {flat} / {layout}")
        print(f"    斜率 {mean:.3f} ± {std:.3f} 音分/bin（拟合 {a:.3f}，残差 {r:.1f} 音分）"
              f"  峰值均值 {cm:.3f}")
        print("    逐倍率 Δbin: " + "  ".join(f"x{f}→{d:+.2f}" for f, d in det))
    print("\n判读：若最优配置的斜率标准差仍 >1 音分/bin，或峰值均值 <0.6，"
          "说明问题不在这三个开关，需要继续往别处找。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
