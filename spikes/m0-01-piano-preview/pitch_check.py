# -*- coding: utf-8 -*-
"""音准检查：渲染器出来的音高，和乐谱上写的一样吗？

「能播」不等于「音准对」。gm.dls 的基准音、微调、采样率换算里任何一处写错，
旋律都会整体跑调、移调或差八度 —— 文件照样能播，你也未必第一耳就听出来。

## 两级检查 —— 因为第一版的检查器自己有偏置

第一版只用 YIN（按波形的周期性测音高），把 gm.dls 判了红：60–67 整个分区 +11 音分、
最低音区 +18。换第二种独立测法（FFT 直接找基频那根谱线）一对照：**同样这些音，
基频偏差都在 ±0.5 音分以内**（只有最低一个分区 −3.5）。

原因：真钢琴的弦是非谐的 —— 高泛音比整数倍略高。YIN 看的是整个波形的周期性，
会被这些偏高的泛音往上拽。代码合成钢琴（基频按公式精确生成）上同样看得到：
YIN 测出 +1.5～+7，FFT 测出 ≤ 0.3。**是检查器的偏置，不是采样的问题。**

所以分两级：
  粗查  YIN，搜索范围放宽到 ÷2.2～×2.2，容差 ±50 音分 —— 专抓移调、差八度这类大错。
        范围必须放宽：太窄的话，差八度会被当成「在范围内找到了次谐波」，反而报绿。
  细查  FFT 基频谱线（±50 音分窗内，抛物线插值），容差 ±10 音分 —— 抓整体跑调。
        峰落在窗边上 → 灰（基频太弱，测不了），不算绿。

测试音覆盖样本用到的全部音区（36–74），外加 gm.dls 每两个分区的交界处 ——
交界处最容易选错采样。每个音单独渲染 1.2 秒，取 0.15–0.9 秒那一段测。

## 先证明检查会响（PRD §12 纪律一：只报绿的检查不算检查）

注入三个故意写错的渲染器，都必须全部报红：
  unity+1      基准音偏一个半音   → 粗查红，应在 −100 附近
  no_sr_ratio  忘了采样率换算     → 粗查红，22050 Hz 的采样按 44100 Hz 放，应在 +1200 附近
  detune+15    整体偏高 15 音分   → 粗查会放过（15 < 50），细查必须红，应在 +15 附近
"""
from __future__ import annotations

import sys
import warnings

import numpy as np

import renderers

SR = renderers.SR
TOL_COARSE, TOL_FINE = 50.0, 10.0
TEST_PITCHES = [36, 38, 39, 43, 44, 45, 47, 48, 50, 51, 52, 55, 57, 59,
                60, 62, 64, 65, 67, 68, 69, 71, 72, 74, 75, 81, 82, 84]


def _segment(rend, pitch):
    audio = rend.render([(0.0, 1.2, pitch, 100)])
    f_exp = 440.0 * 2 ** ((pitch - 69) / 12)
    return audio[int(0.15 * SR):int(0.9 * SR)].astype(np.float32), f_exp


def yin_cents(rend, pitch):
    """粗查：YIN 测基频中位数 → 与乐谱音高差多少音分。"""
    import librosa

    seg, f_exp = _segment(rend, pitch)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f0 = librosa.yin(seg, fmin=f_exp / 2.2, fmax=min(f_exp * 2.2, SR / 4),
                         sr=SR, frame_length=8192)
    return 1200 * np.log2(float(np.median(f0)) / f_exp)


def fft_cents(rend, pitch):
    """细查：FFT 里直接找基频那根谱线。只看第一泛音，不受高泛音非谐的影响。"""
    seg, f_exp = _segment(rend, pitch)
    n = 1 << 18   # 补零到 262144 点：谱线间隔 0.17 Hz，再抛物线插值
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    idx = np.where((freqs >= f_exp * 2 ** (-0.5 / 12)) & (freqs <= f_exp * 2 ** (0.5 / 12)))[0]
    k = idx[np.argmax(spec[idx])]
    if k in (idx[0], idx[-1]):
        return float("nan")
    a, b, c = np.log(spec[k - 1:k + 2] + 1e-12)
    f = (k + 0.5 * (a - c) / (a - 2 * b + c)) * SR / n
    return 1200 * np.log2(f / f_exp)


def check(rend):
    """→ [(音高, 粗查音分, 细查音分, 绿/红/灰)]"""
    rows = []
    for p in TEST_PITCHES:
        y = yin_cents(rend, p)
        f = fft_cents(rend, p) if abs(y) <= TOL_COARSE else float("nan")
        if abs(y) > TOL_COARSE or (not np.isnan(f) and abs(f) > TOL_FINE):
            v = "红"
        elif np.isnan(f):
            v = "灰"
        else:
            v = "绿"
        rows.append((p, y, f, v))
    return rows


def overall(rows):
    vs = {r[3] for r in rows}
    return "红" if "红" in vs else ("灰" if "灰" in vs else "绿")


class _Broken(renderers.GmDlsPiano):
    """故意写错的 gm.dls 渲染器 —— 只用来证明检查会响。"""

    def __init__(self, defect):
        self.defect = defect

    def load(self):
        super().load()
        fix = {
            "unity+1":     lambda a, b, u, f, g, sr, s, lp: (a, b, u + 1, f, g, sr, s, lp),
            "no_sr_ratio": lambda a, b, u, f, g, sr, s, lp: (a, b, u, f, g, SR, s, lp),
            "detune+15":   lambda a, b, u, f, g, sr, s, lp: (a, b, u, f + 15, g, sr, s, lp),
        }[self.defect]
        self.regions = [fix(*r) for r in self.regions]
        return self


def main():
    print(f"{len(TEST_PITCHES)} 个测试音 · 粗查 YIN ±{TOL_COARSE:g} 音分 · 细查 FFT 基频 ±{TOL_FINE:g} 音分\n")

    print("── 先证明检查会响（注入缺陷，必须全部报红）──")
    ok = True
    for defect, col, expect in [("unity+1", 1, -100), ("no_sr_ratio", 1, 1200), ("detune+15", 2, 15)]:
        rows = check(_Broken(defect).load())
        n_red = sum(r[3] == "红" for r in rows)
        med = float(np.nanmedian([r[col] for r in rows]))
        fired = n_red == len(rows) and abs(med - expect) < max(5, abs(expect) * 0.1)
        ok &= fired
        print(f"  {defect:12s} 红 {n_red:2d}/{len(rows)}  {'粗查' if col == 1 else '细查'}中位 {med:+8.1f}"
              f"（预期 {expect:+d}）→ {'会响 ✓' if fired else '失灵 ✗'}")
    if not ok:
        print("\n检查本身失灵，下面的结果不可信。")
        sys.exit(1)

    print("\n── 真渲染器 ──")
    for name, cls in renderers.RENDERERS.items():
        rend = cls().load()
        rows = check(rend)
        fine = np.array([r[2] for r in rows])
        coarse = np.array([r[1] for r in rows])
        print(f"  {name:9s} {overall(rows)}  细查最大 |误差| {np.nanmax(np.abs(fine)):4.1f} 音分"
              f"  粗查最大 |误差| {np.max(np.abs(coarse)):4.1f}  灰 {sum(r[3] == '灰' for r in rows)} 个")
        for p, y, f, v in rows:
            if v != "绿":
                print(f"      {v} MIDI {p}: 粗查 {y:+.1f}  细查 {f:+.1f}")
        if name == "gmdls":
            for klo, khi, unity, fn, *_ in rend.regions:
                sel = [r for r in rows if klo <= r[0] <= khi]
                if sel:
                    print(f"      键 {klo:3d}-{khi:3d}（基准音 {unity:3d}，微调 {fn:+d}）"
                          f"  细查 {np.nanmean([r[2] for r in sel]):+5.1f}"
                          f"  粗查 {np.mean([r[1] for r in sel]):+5.1f}")


if __name__ == "__main__":
    main()
