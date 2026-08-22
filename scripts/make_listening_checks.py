# -*- coding: utf-8 -*-
"""生成可听的对照文件，让人用耳朵验阶段 1/2 的结论。

不需要 SynthV，也不需要桥 —— 这一层的结论本来就不依赖它们。

产出（全部 44.1kHz 立体声，左=干声参考，右=本项目算出来的东西）：

  01_音高证据.wav     右声道 = 证据层的 f0 合成正弦。**没有证据的地方是静音。**
                      听点：正弦跟不跟得住唱；静音处是不是真的听不出音高
  02_人声活动.wav     右声道 = 被活动检测判为「在唱」的干声，其余静音
                      听点：有没有把在唱的段掐掉；有没有把器乐渗漏当成唱
  03_逐行起点.wav     右声道 = 每行起点的 click。高音 click = 校正后，低音 = LRC 原值
                      听点：高音 click 是不是落在该行第一个字上
  04_定点抽查/        三个具体断言的短片段，不用听整首
      trap_139.9s     交接文件记「pyin 锁三次次谐波，正确 68.90 被报成 50.00」
                      证据层给 69.00。听点：这里唱的是不是那个高音
      fail_L03_40.5s  阶段2 超线行，残差 340ms
      fail_L35_164.8s 阶段2 超线行，残差 460ms（高潮句，stem 质量已知最差）

用法: python scripts/make_listening_checks.py [song_id]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svchain import config
from svchain.align import stage1, stage2

SR_OUT = 44100
EXCERPTS = [
    ("trap_139.9s_应为MIDI69", 137.5, 143.0),
    ("fail_L03_40.5s_残差340ms", 38.0, 45.0),
    ("fail_L35_164.8s_残差460ms", 162.0, 170.5),
]


def upsample_hold(x: np.ndarray, hop_s: float, n_out: int, sr: int) -> np.ndarray:
    """10ms 栅格 → 采样率栅格，最近邻保持（不插值：f0 在八度跳变处插值会造假值）。"""
    idx = np.minimum((np.arange(n_out) / sr / hop_s).astype(np.int64), x.size - 1)
    return x[idx]


def synth_tone(f0_hz: np.ndarray, hop_s: float, n_out: int, sr: int,
               level_db: float = -20.0, fade_ms: float = 8.0) -> np.ndarray:
    """按 f0 合成连续相位正弦；f0 为 NaN 处静音，边界加淡入淡出避免爆音。"""
    f = upsample_hold(f0_hz, hop_s, n_out, sr)
    gate = np.isfinite(f).astype(np.float64)
    f = np.nan_to_num(f, nan=0.0)
    # 相位累积，保证频率变化处不断相
    phase = np.cumsum(2 * np.pi * f / sr)
    y = np.sin(phase)
    # 门控做平滑，避免开关爆音
    k = max(1, int(sr * fade_ms / 1000))
    ker = np.ones(k) / k
    gate = np.convolve(gate, ker, mode="same")
    return (y * gate * (10 ** (level_db / 20))).astype(np.float32)


def gate_audio(y: np.ndarray, mask: np.ndarray, hop_s: float, sr: int,
               fade_ms: float = 10.0) -> np.ndarray:
    g = upsample_hold(mask.astype(np.float64), hop_s, y.size, sr)
    k = max(1, int(sr * fade_ms / 1000))
    g = np.convolve(g, np.ones(k) / k, mode="same")
    return (y * g).astype(np.float32)


def clicks(times_s: list[float], n_out: int, sr: int, freq: float = 2000.0,
           level_db: float = -14.0, dur_ms: float = 12.0) -> np.ndarray:
    out = np.zeros(n_out, dtype=np.float64)
    n = int(sr * dur_ms / 1000)
    t = np.arange(n) / sr
    burst = np.sin(2 * np.pi * freq * t) * np.exp(-t * 400.0)
    for ts in times_s:
        i = int(ts * sr)
        if 0 <= i < n_out - n:
            out[i:i + n] += burst
    return (out * (10 ** (level_db / 20))).astype(np.float32)


def write_stereo(path: Path, left: np.ndarray, right: np.ndarray, sr: int) -> None:
    n = min(left.size, right.size)
    a = np.stack([left[:n], right[:n]], axis=1)
    peak = float(np.abs(a).max())
    if peak > 0.99:
        a = a * (0.99 / peak)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), a, sr, subtype="PCM_16")
    print(f"  写出 {path.name}  {n/sr:.1f}s")


def main() -> int:
    song_id = sys.argv[1] if len(sys.argv) > 1 else "chaosheng"
    cfg = config.load()
    song = cfg.song(song_id)
    song.require("vocals", "no_vocals", "lyrics")
    P, A = cfg.pitch, cfg.align
    out_dir = Path(__file__).resolve().parents[1] / "out" / f"listen_{song_id}"

    # --- 参考声道：原始 44.1kHz 干声，下混单声道 ---
    ref, sr_ref = sf.read(str(song.vocals), always_2d=True)
    ref = ref.mean(axis=1)
    if sr_ref != SR_OUT:
        raise SystemExit(f"干声是 {sr_ref}Hz，本脚本按 {SR_OUT} 写出，需要先重采样")
    n_out = ref.size
    ref = (ref / max(1e-9, np.abs(ref).max()) * 0.6).astype(np.float32)

    # --- 阶段 1/2：统一从 pipeline 取，避免两个入口各自拼装 ---
    s1 = stage1(cfg, song)
    em = s1.evidence
    print(f"证据覆盖 {100*em.coverage():.1f}%")

    print("\n生成对照文件：")
    tone = synth_tone(em.f0_hz, P.hop_s, n_out, SR_OUT)
    write_stereo(out_dir / "01_音高证据.wav", ref, tone, SR_OUT)

    # --- 阶段 2：活动检测 + 逐行起点 ---
    s2 = stage2(cfg, song, s1)
    write_stereo(out_dir / "02_人声活动.wav", ref,
                 gate_audio(ref.astype(np.float64), s2.activity.mask,
                            P.hop_s, SR_OUT),
                 SR_OUT)
    mains = s2.main_offsets
    rate, gd = s2.rate_s_per_char, s2.global_delta_s
    hi = clicks([o.corrected_t_s for o in mains], n_out, SR_OUT, 2200.0, -14.0)
    lo = clicks([o.line.t_s for o in mains], n_out, SR_OUT, 700.0, -20.0)
    write_stereo(out_dir / "03_逐行起点.wav", ref, hi + lo, SR_OUT)
    print(f"  （高音 click = 校正后起点，低音 = LRC 原值；全局偏移 {gd:+.3f}s，"
          f"速率 {rate:.3f}s/字）")

    # --- 定点抽查 ---
    print("\n定点抽查片段：")
    ex_dir = out_dir / "04_定点抽查"
    for name, t0, t1 in EXCERPTS:
        i0, i1 = int(t0 * SR_OUT), int(t1 * SR_OUT)
        i1 = min(i1, n_out)
        write_stereo(ex_dir / f"{name}.wav", ref[i0:i1], tone[i0:i1], SR_OUT)

    print(f"\n全部写在 {out_dir}")
    print("out/ 已被 .gitignore 排除，不会进库。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
