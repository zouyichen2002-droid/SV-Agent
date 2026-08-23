# -*- coding: utf-8 -*-
"""验证 FL 渲染出来的伴奏与作曲的时间对齐。

## 为什么这是整条链最后一个、也是最关键的检查

ADR-0008 选「代码合成 MIDI」的唯一理由是 tick 级对齐。但那只证明了
**MIDI 文件内部**是准的。中间还隔着两层没被验证的东西：

    我们的 .mid  →  FL 导入语义  →  FL 渲染  →  拖进 SynthV 当音频轨

FL 导入可能加起始偏移、渲染可能带前置静音、tempo 可能被改。
任何一环错半拍，前面五步（词/旋律/检查/写入 SV/伴奏）全部作废，
而且**无法靠后期补救**。ADR-0008 的「什么证据会推翻它」第二条就是这个。

## 方法：不做逐个音符的峰值检测，做互相关

逐个检测起音再配对很脆（漏检、多检、鼓和垫的起音混在一起）。
这里换个做法：

1. 从 `melody_v2` + `make_accompaniment` 算出**每个伴奏音符的确切起点**，
   按力度加权造一条「期望起音包络」
2. 对渲染音频算谱通量（spectral flux）得到「实测起音包络」
3. **互相关**两条包络，峰值位置就是全局偏移

互相关用的是全曲几百个音符的共同证据，个别漏检不影响结论。

## 偏移和漂移是两种不同的故障，必须分开报

    偏移（constant lag）  → FL 渲染带了前置静音，或导入时整体挪了位
                            **可修**：在 SynthV 里把音频轨往反方向挪同样的量
    漂移（lag 随时间变）  → tempo 不一致
                            **不可修**：必须回 FL 改 tempo 重新渲染

所以脚本把前 1/3、中 1/3、后 1/3 各算一次。三段偏移一致 = 只有偏移；
逐段变大 = 有漂移。

## 分辨率

hop 256 @ 44100 Hz = 5.8 ms/帧，再对相关峰做抛物线插值取亚帧精度。
所以报出来的数字在 ±1 ms 量级可信，不要拿它讨论 0.1 ms。

用法:
    python scripts/verify_alignment.py <FL渲染的伴奏.wav>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "out"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

HOP = 256
NFFT = 1024

# 判据。来源：一个八分音符在 76 BPM 下是 395ms，人耳对节奏偏移的
# 察觉阈值在 10–20ms 量级（低频更宽容）。所以：
OK_MS = 10.0          # 10ms 以内：听不出来
WARN_MS = 25.0        # 25ms 以内：可修（在 SV 里挪音频轨）
DRIFT_OK_MS = 5.0     # 三段之间的偏移差；超过就是 tempo 不一致


def onset_envelope(y: np.ndarray, sr: int) -> tuple[np.ndarray, float]:
    """谱通量。返回 (包络, 每帧秒数)。"""
    w = np.hanning(NFFT).astype(np.float32)
    n = 1 + (len(y) - NFFT) // HOP
    if n < 8:
        raise SystemExit("音频太短")
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    S = np.abs(np.fft.rfft(y[idx] * w, axis=1))
    # 半波整流的一阶差分 —— 只要能量上升，不要下降
    flux = np.diff(S, axis=0, prepend=S[:1])
    env = np.maximum(flux, 0.0).sum(axis=1)
    env -= env.mean()
    return env.astype(np.float64), HOP / sr


def expected_envelope(n_frames: int, spf: float) -> np.ndarray:
    """从作曲算期望起音包络：每个伴奏音符起点打一个力度加权的脉冲。"""
    import melody_v2 as mod
    from make_accompaniment import build_parts
    parts, _, _ = build_parts(mod)
    spb = 60.0 / mod.BPM
    env = np.zeros(n_frames)
    for name, evs in parts.items():
        for onset_b, _dur, _midi, vel in evs:
            f = int(round(onset_b * spb / spf))
            if 0 <= f < n_frames:
                env[f] += vel / 100.0
    env -= env.mean()
    return env


def best_lag(a: np.ndarray, b: np.ndarray, spf: float,
             max_ms: float = 400.0) -> tuple[float, float]:
    """b 相对 a 的最佳滞后（毫秒）与归一化相关峰值。"""
    m = int(round(max_ms / 1000.0 / spf))
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    na = np.linalg.norm(a) or 1.0
    nb = np.linalg.norm(b) or 1.0
    lags = np.arange(-m, m + 1)
    cor = np.empty(len(lags))
    for i, L in enumerate(lags):
        if L >= 0:
            cor[i] = float(np.dot(a[L:], b[:n - L]))
        else:
            cor[i] = float(np.dot(a[:n + L], b[-L:]))
    cor /= (na * nb)
    k = int(np.argmax(cor))
    # 抛物线插值取亚帧精度
    frac = 0.0
    if 0 < k < len(cor) - 1:
        y0, y1, y2 = cor[k - 1], cor[k], cor[k + 1]
        den = y0 - 2 * y1 + y2
        if abs(den) > 1e-12:
            frac = 0.5 * (y0 - y2) / den
    return (lags[k] + frac) * spf * 1000.0, float(cor[k])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("render", help="FL 导出的伴奏 wav")
    a = ap.parse_args()
    p = Path(a.render).resolve()
    if not p.exists():
        raise SystemExit(f"找不到 {p}")

    y, sr = sf.read(str(p), always_2d=True)
    y = y.mean(axis=1).astype(np.float32)
    import melody_v2 as mod
    exp_s = mod.N_BARS * 4 * 60.0 / mod.BPM

    print(f"渲染文件　{p}")
    print(f"  {sr} Hz · {len(y)/sr:.2f}s"
          f"（期望 {exp_s:.2f}s + 混响尾巴）\n")

    meas, spf = onset_envelope(y, sr)
    exp = expected_envelope(len(meas), spf)
    print(f"帧长 {spf*1000:.2f}ms　共 {len(meas)} 帧"
          f"　期望起音脉冲 {int((exp > exp.mean()).sum())} 个\n")

    raw, cor = best_lag(exp, meas, spf)

    # 检测器有系统性偏置：谱通量把起音测晚（NFFT=1024 的窗跨 23ms），
    # 音源自身的 attack 也算进来。实测我自己**样本级对齐**的合成预览
    # 也报 +12.0ms —— 那就是纯偏置。
    # 所以拿它当基准自校准。不校准就会让用户去修我的测量误差（差点发生）。
    bias, bias_src = 0.0, None
    calib = (Path(__file__).resolve().parents[1] / "out" / "listen_yuzhou"
             / "伴奏预览_v2.wav")
    if calib.exists():
        cy, csr = sf.read(str(calib), always_2d=True)
        cmeas, cspf = onset_envelope(cy.mean(axis=1).astype(np.float32), csr)
        cexp = expected_envelope(len(cmeas), cspf)
        bias, _ = best_lag(cexp, cmeas, cspf)
        bias_src = calib.name

    lag = raw - bias
    print("=" * 62)
    print(f"原始互相关　{raw:+.1f} ms　（相关峰 {cor:.3f}）")
    if bias_src:
        print(f"检测器偏置　{bias:+.1f} ms"
              f"　（用 {bias_src} 自校准 —— 它构造上样本级对齐）")
    print(f"**实际偏移　{lag:+.1f} ms**")

    # 正负号的定义（靠负对照确定，不靠推理）：
    # 把渲染人为延后 50ms，报数从 +10.4 变 −40.4。所以
    #   lag > 0  → 伴奏比人声**早**，音频轨要往**后**（右）挪
    #   lag < 0  → 伴奏比人声**晚**，音频轨要往**前**（左）挪
    if abs(lag) <= OK_MS:
        print("  ✓ 听不出来，直接放 0 秒即可")
    elif abs(lag) <= WARN_MS:
        early = lag > 0
        print(f"  ⚠ 伴奏比人声{'早' if early else '晚'} {abs(lag):.0f} ms。"
              f"在 SynthV 里把音频轨往{'后（右）' if early else '前（左）'}"
              f"挪 {abs(lag):.0f} ms")
    else:
        print("  ✗ 偏移过大。先查 FL 导出有没有前置静音")
    if cor < 0.15:
        print("  ⚠ 相关峰很低，这个偏移数字不可信 —— "
              "可能渲染的不是这首伴奏，或者音源起音太软测不到")

    # 分三段看漂移
    print("\n分段（判断是偏移还是漂移）：")
    third = len(meas) // 3
    seg = []
    for i, name in enumerate(("前 1/3", "中 1/3", "后 1/3")):
        s0, s1 = i * third, (i + 1) * third
        L, c = best_lag(exp[s0:s1], meas[s0:s1], spf)
        seg.append(L)
        print(f"  {name}　{L:+7.1f} ms　（相关峰 {c:.3f}）")
    spread = max(seg) - min(seg)
    print(f"\n三段极差 {spread:.1f} ms")
    if spread <= DRIFT_OK_MS:
        print("  ✓ 无漂移 —— tempo 一致，偏移是常量，可修")
    else:
        print("  ✗ 有漂移 —— tempo 不一致。**挪音频轨修不了**，"
              "回 FL 确认 tempo 是 76 后重新渲染")

    print("\n" + "=" * 62)
    ok = abs(lag) <= WARN_MS and spread <= DRIFT_OK_MS and cor >= 0.15
    print("✓ 对齐可用。把这个 wav 拖进 SynthV 当音频轨，就是成品。" if ok
          else "✗ 对齐没通过，见上。不要在这个基础上做混音 —— 会白做。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
