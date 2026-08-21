# -*- coding: utf-8 -*-
"""标定 RMVPE 的 mel 前端与 bin→cents 映射。

**为什么必须标定而不是照约定抄常数**：权重是纯 state_dict，前端参数不在里面。
按常见约定写（magnitude 谱 / fmin=30 / 20 音分每 bin / 基准 1997.38），
合成正弦实测系统性偏低 ~570 音分。前向里那三个「权重形状分辨不出来」的选择
已由 `identify_rmvpe_forward.py` 定死（up_first / channel_major / time_rows）。
剩下要定的是 mel 前端和 bin→cents 的两个常数。

**三条证据分别定不同的量，刻意不互相依赖：**

1. **斜率** —— 重采样法。同一段真实歌声按倍率 r 重采样，音高必然位移 1200·log2(r)。
   完全不借其它估计器，且用分布内音频。
2. **截距** —— 斜率固定后只剩一个标量。用 torchcrepe ∩ Praat 一致帧作锚点，
   取 offset 分布的**主模态**（不是均值也不是最小二乘 —— 八度错是离群点，
   最小二乘会被拖走：实测未加稳健化时斜率被拖到 16.4、残差 322 音分）。
3. **旁证** —— 合成正弦的绝对真值。分布外，只在低频段可信，用来独立佐证截距。

前端配置的评分不看拟合残差（会被离群点骗），看三个量：
offset 主模态的紧致度、峰值置信度、对锚点的八度错率。

用法: python scripts/calibrate_rmvpe.py [song_id]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svchain import config, evidence
from svchain.audio import cached_track, load_mono
from svchain.pitch import CrepeEstimator, PraatEstimator, RmvpeEstimator, n_frames_for
from svchain.pitch.base import hz_to_cents

SLOPE = 20.0        # 由 identify_rmvpe_forward.py 的重采样法独立测定（19.78±1.19）
CONF_MIN = 0.30
SEG = (23.6, 53.6)


def peak_bins(sal: np.ndarray, half: int = 4):
    b0 = np.argmax(sal, axis=1)
    pad = np.pad(sal, ((0, 0), (half, half)))
    idx = (b0 + half)[:, None] + np.arange(-half, half + 1)[None, :]
    w = pad[np.arange(sal.shape[0])[:, None], idx]
    ws = w.sum(axis=1)
    c = np.divide((w * (idx - half)).sum(axis=1), ws,
                  out=b0.astype(np.float64), where=ws > 0)
    return c, sal.max(axis=1)


def modal_offset(off: np.ndarray, bin_w: float = 20.0, win: float = 200.0):
    """offset 分布的主模态 + 紧致度。八度错会自成簇，不该影响主模态。"""
    if off.size == 0:
        return float("nan"), float("nan"), 0.0
    edges = np.arange(off.min() - bin_w, off.max() + 2 * bin_w, bin_w)
    hist, _ = np.histogram(off, bins=edges)
    centre = edges[int(np.argmax(hist))] + bin_w / 2
    core = off[np.abs(off - centre) < win]
    if core.size < 10:
        return float("nan"), float("nan"), 0.0
    base = float(np.median(core))
    iqr = float(np.percentile(core, 75) - np.percentile(core, 25))
    return base, iqr, float(core.size / off.size)


def resample(y: np.ndarray, factor: float) -> np.ndarray:
    n = int(y.size / factor)
    s = np.arange(n) * factor
    i0 = np.floor(s).astype(np.int64)
    i1 = np.minimum(i0 + 1, y.size - 1)
    f = (s - i0).astype(np.float32)
    return ((1 - f) * y[i0] + f * y[i1]).astype(np.float32)


def main() -> int:
    song_id = sys.argv[1] if len(sys.argv) > 1 else "chaosheng"
    cfg = config.load()
    song = cfg.song(song_id)
    song.require("vocals")
    P = cfg.pitch

    y = load_mono(song.vocals, P.sr)
    n = n_frames_for(y.size, P.sr, P.hop_s)

    tracks = []
    for est in (CrepeEstimator(model="full"), PraatEstimator()):
        tr, _ = cached_track(cfg.cache_dir, Path(song.vocals), est, P.sr, P.hop_s,
                            n, P.fmin_hz, P.fmax_hz)
        tracks.append(tr)
    em = evidence.build(tracks, P.agree_cents, min_agree=2)
    anchor = hz_to_cents(em.f0_hz)
    anchor_ok = em.has_evidence
    print(f"锚点：torchcrepe ∩ praat-ac 一致帧 {int(anchor_ok.sum())}/{n} "
          f"= {100*anchor_ok.mean():.1f}%（两个不同算法族，±{P.agree_cents:.0f} 音分）")

    base_est = RmvpeEstimator(cfg.model("rmvpe"))
    model = base_est._load()
    print(f"RMVPE {base_est.load_report['n_keys']} 键 / "
          f"{base_est.load_report['n_params']/1e6:.2f}M 参数，strict 加载通过")
    print(f"斜率固定 {SLOPE:.1f} 音分/bin（重采样法独立测定）\n")

    variants = []
    for power in (1, 2):
        for htk in (False, True):
            for norm in ("slaney", None):
                for fmin in (30.0, 0.0):
                    variants.append(dict(power=power, htk=htk, norm=norm,
                                         fmin=fmin, fmax=8000.0))

    print(f"{'配置':<40}{'截距':>9}{'IQR':>7}{'主模态占比':>11}"
          f"{'峰值':>7}{'八度错':>8}{'可用帧':>8}")
    print("-" * 92)
    rows = []
    for v in variants:
        e = RmvpeEstimator(cfg.model("rmvpe"), mel=v)
        e._model = model
        sal = e._salience(e._mel(y, P.sr))
        bins, conf = peak_bins(sal)
        m = min(bins.size, n)
        use = anchor_ok[:m] & (conf[:m] > CONF_MIN)
        label = (f"power={v['power']} htk={int(v['htk'])} "
                 f"norm={'slaney' if v['norm'] else 'none':<6} fmin={v['fmin']:.0f}")
        if use.sum() < 300:
            print(f"{label:<40}   可用帧不足 {int(use.sum())}")
            continue
        off = anchor[:m][use] - SLOPE * bins[:m][use]
        base, iqr, share = modal_offset(off)
        oct_rate = float((np.abs(np.abs(off - base) - 1200.0) < 100).mean())
        print(f"{label:<40}{base:9.1f}{iqr:7.1f}{100*share:10.1f}%"
              f"{conf.mean():7.3f}{100*oct_rate:7.1f}%{int(use.sum()):8d}")
        rows.append((iqr, -conf.mean(), label, base, iqr, share,
                     float(conf.mean()), oct_rate, dict(v)))

    if not rows:
        print("\n没有配置拿到足够可用帧。")
        return 1
    rows.sort()
    print("\n=== 按 offset 紧致度（IQR）排序，前三 ===")
    for _, _, label, base, iqr, share, cm, orate, v in rows[:3]:
        print(f"  {label}")
        print(f"    截距 {base:.2f}  IQR {iqr:.1f} 音分  主模态占 {100*share:.1f}%  "
              f"峰值均值 {cm:.3f}  八度错 {100*orate:.1f}%")

    best = rows[0]
    v_best, base_best = best[8], best[3]
    print(f"\n采用：{best[2]}  截距 {base_best:.2f}")
    print(f"（常见约定值 1997.38，差 {base_best-1997.3796077132352:+.1f} 音分 —— "
          f"说明前端仍与训练时不完全一致，但轴是线性的、可标定的）")

    # ---- 证据1：重采样法复核斜率（用最优前端）----
    e = RmvpeEstimator(cfg.model("rmvpe"), mel=v_best)
    e._model = model
    a = y[int(SEG[0] * P.sr):int(SEG[1] * P.sr)]
    b0, c0 = peak_bins(e._salience(e._mel(a, P.sr)))
    k0 = c0 > CONF_MIN
    ref = float(np.median(b0[k0]))
    print("\n=== 证据1 · 重采样法复核斜率（不借任何估计器）===")
    ss = []
    for fac in (0.5, 0.63, 0.79, 1.26, 1.587, 2.0):
        b1, c1 = peak_bins(e._salience(e._mel(resample(a, fac), P.sr)))
        k1 = c1 > CONF_MIN
        if k1.sum() < 100:
            continue
        d = float(np.median(b1[k1])) - ref
        sh = 1200.0 * np.log2(fac)
        ss.append(sh / d)
        print(f"  x{fac:<6} 期望 {sh:+8.1f} 音分  Δbin {d:+7.2f}  斜率 {sh/d:7.3f}")
    if ss:
        ss = np.array(ss)
        print(f"  斜率 {ss.mean():.3f} ± {ss.std():.3f} 音分/bin（采用 {SLOPE:.1f}）")

    # ---- 证据3：合成正弦旁证 ----
    print("\n=== 证据3 · 合成正弦绝对真值（分布外，只作旁证）===")
    t = np.arange(int(P.sr * 1.5)) / P.sr
    for f in (98.0, 110.0, 146.83, 220.0, 293.66, 440.0):
        tone = (0.5 * (0.6 * np.sin(2 * np.pi * f * t) + 0.2 * np.sin(4 * np.pi * f * t)
                       + 0.1 * np.sin(6 * np.pi * f * t))).astype(np.float32)
        b, c = peak_bins(e._salience(e._mel(tone, P.sr)))
        k = c > 0.2
        if k.sum() < 20:
            print(f"  {f:7.2f}Hz  未检出（峰值均值 {c.mean():.3f}）")
            continue
        got = 10.0 * 2 ** ((SLOPE * float(np.median(b[k])) + base_best) / 1200.0)
        print(f"  {f:7.2f}Hz → {got:7.2f}Hz  误差 {1200*np.log2(got/f):+7.1f} 音分  "
              f"峰值均值 {c.mean():.3f}")

    print("\n把结果写进 toolkit/svchain/pitch/rmvpe_est.py 的 MEL / CENTS_BASE，"
          "并在 specs/adr/ 里记一条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
