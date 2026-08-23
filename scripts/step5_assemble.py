# -*- coding: utf-8 -*-
"""工作流步骤 5：伴奏进 SynthV + 对齐验证 + 基础调教。

## 顺序不能反

    1. 先验对齐 —— 对不上就别往下走，后面全是白做
    2. 再看电平与频段平衡
    3. 最后把音频挂进工程 + 调教

## 对齐怎么验

互相关，而不是逐音符峰值配对（漏检/多检都会毁掉结论）：

    期望起音包络   ← 从伴奏 MIDI 的事件算（每个事件一个力度加权脉冲）
    实测起音包络   ← 对 FL 渲染的音频算谱通量
    互相关         → 峰值位置就是全局偏移

**必须自校准。** 谱通量检测天然把起音测晚（窗跨 23ms），音源自身的 attack
也算进来。所以同时对**同一套伴奏事件的正弦渲染**（构造上样本级对齐）
做一次同样的测量，两者相减才是 FL 那边的真实偏移。
实测这个偏置有 +12ms 量级 —— 不校准就会让创作者去修我的测量误差。

**偏移与漂移分开报**：

    偏移（常量）   → FL 渲染带前置静音，可修（在 SV 里挪音频轨）
    漂移（随时间）→ tempo 不一致，**挪音频轨修不了**，必须回 FL 重渲

用法:
    python scripts/step5_assemble.py                     # 只验，不碰工程
    python scripts/step5_assemble.py --write --closed    # 挂音频轨进工程
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import soundfile as sf

import step3_melody as S3
import step4_accompaniment as S4
from make_accompaniment import build_parts
from svagent import svp_build as SB
from svagent.compose.checks import note_name
from svagent.compose.lyricfile import parse
from svagent.compose.melodize import chord_of
from verify_alignment import OK_MS, WARN_MS, best_lag, onset_envelope

AUDIO = S3.PROJECT.with_name(S3.PROJECT.stem + "_伴奏.wav")
SR = 44100
DRIFT_OK_MS = 5.0


def parts_of_project(bpm: float):
    """重建这首歌的伴奏事件（与 step4 写 MIDI 时同一套）。"""
    ver = parse(S3.LYRICS)[0][next(iter(parse(S3.LYRICS)[0]))]
    lead_name, notes, sections = S3.read_lead(S3.PROJECT, ver, S3.FORM)
    kr, kq, kname = S3.infer_key([n.midi for n in notes])
    conv = []
    for sec_name, bar0, lines in sections:
        out = []
        for text, syls, chord in lines:
            _pcs, root, q = chord_of(chord, kr)
            out.append((text, syls, (root, q)))
        conv.append((sec_name, bar0, out))
    song = S4.Song(conv, kr, kq, bpm, S3.N_BARS)
    parts, _ch, _sec = build_parts(song)
    return lead_name, notes, kname, parts


def expected_env(parts, n_frames: int, spf: float, bpm: float) -> np.ndarray:
    """伴奏事件 → 力度加权的起音脉冲序列。"""
    spb = 60.0 / bpm
    env = np.zeros(n_frames)
    for _name, evs in parts.items():
        for onset_b, _dur, _midi, vel in evs:
            f = int(round(onset_b * spb / spf))
            if 0 <= f < n_frames:
                env[f] += vel / 100.0
    return env - env.mean()


def sine_render(parts, bpm: float, n_bars: int) -> np.ndarray:
    """同一套事件的正弦渲染。**构造上样本级对齐**，用作检测器零点。"""
    spb = 60.0 / bpm
    y = np.zeros(int((n_bars * 4 * spb + 2.0) * SR))
    for name, evs in parts.items():
        for onset_b, dur_b, midi, vel in evs:
            n = max(1, int(dur_b * spb * SR))
            t = np.arange(n) / SR
            if name == "鼓":
                rng = np.random.default_rng(int(midi))
                seg = rng.standard_normal(n) * np.exp(-t * 60.0)
            else:
                f = 440.0 * 2 ** ((midi - 69) / 12)
                a = np.minimum(1.0, t / 0.008) * np.exp(-t * 1.2)
                seg = np.sin(2 * np.pi * f * t) * a
            i = int(onset_b * spb * SR)
            j = min(i + n, y.size)
            if j > i:
                y[i:j] += seg[: j - i] * (vel / 100.0) * 0.1
    return y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bpm", type=float, default=S3.SONG_BPM)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--closed", action="store_true")
    a = ap.parse_args()

    if not AUDIO.exists():
        print(f"✗ 找不到伴奏音频 {AUDIO}")
        return 1

    lead_name, notes, kname, parts = parts_of_project(a.bpm)
    ps = [n.midi for n in notes]
    exp_s = S3.N_BARS * 4 * 60.0 / a.bpm
    y, sr = sf.read(str(AUDIO), always_2d=True)
    mono = y.mean(axis=1).astype(np.float32)
    print(f"工程　{S3.PROJECT}")
    print(f"旋律　{lead_name}　{len(notes)} 音符"
          f"　{note_name(min(ps))}-{note_name(max(ps))}　{kname}")
    print(f"伴奏　{AUDIO.name}　{len(mono)/sr:.2f}s"
          f"（期望 {exp_s:.2f}s + 混响尾巴）")
    n_ev = sum(len(v) for v in parts.values())
    print(f"　　　伴奏事件 {n_ev} 个，用作期望起音包络\n")

    print("=" * 70)
    print("对齐验证")
    print("=" * 70)
    meas, spf = onset_envelope(mono, sr)
    exp = expected_env(parts, len(meas), spf, a.bpm)
    raw, cor = best_lag(exp, meas, spf)

    # 自校准：同一套事件的正弦渲染，构造上样本级对齐
    cal = sine_render(parts, a.bpm, S3.N_BARS)
    cmeas, cspf = onset_envelope(cal.astype(np.float32), SR)
    cexp = expected_env(parts, len(cmeas), cspf, a.bpm)
    bias, bcor = best_lag(cexp, cmeas, cspf)
    lag = raw - bias

    print(f"  原始互相关　{raw:+.1f} ms（相关峰 {cor:.3f}）")
    print(f"  检测器偏置　{bias:+.1f} ms（正弦渲染自校准，相关峰 {bcor:.3f}）")
    print(f"  **实际偏移　{lag:+.1f} ms**")
    if abs(lag) <= OK_MS:
        print("    ✓ 听不出来，音频轨放 0 秒即可")
    elif abs(lag) <= WARN_MS:
        early = lag > 0
        print(f"    ⚠ 伴奏比人声{'早' if early else '晚'} {abs(lag):.0f} ms，"
              f"在 SV 里把音频轨往{'后' if early else '前'}挪同样的量")
    else:
        print("    ✗ 偏移过大，先查 FL 导出有没有前置静音")
    if cor < 0.15:
        print("    ⚠ 相关峰很低，这个数字不可信")

    print("\n  分段（判断是偏移还是漂移）：")
    third = len(meas) // 3
    seg = []
    for i, nm in enumerate(("前 1/3", "中 1/3", "后 1/3")):
        s0, s1 = i * third, (i + 1) * third
        L, c = best_lag(exp[s0:s1], meas[s0:s1], spf)
        seg.append(L)
        print(f"    {nm}　{L - bias:+7.1f} ms（相关峰 {c:.3f}）")
    spread = max(seg) - min(seg)
    print(f"\n  三段极差 {spread:.1f} ms")
    if spread <= DRIFT_OK_MS:
        print("    ✓ 无漂移 —— tempo 一致")
    else:
        print("    ✗ 有漂移 —— tempo 不一致，**挪音频轨修不了**，回 FL 重渲")

    ok_align = abs(lag) <= WARN_MS and spread <= DRIFT_OK_MS and cor >= 0.15
    print("\n" + ("✓ 对齐通过" if ok_align else "✗ 对齐没通过，不要往下走"))
    if not ok_align:
        return 2

    print("\n" + "=" * 70)
    print("电平与频段")
    print("=" * 70)
    pk = 20 * np.log10(max(1e-9, float(np.abs(mono).max())))
    rms = 20 * np.log10(max(1e-9, float(np.sqrt((mono ** 2).mean()))))
    N, HOP = 2048, 512
    w = np.hanning(N)
    idx = np.arange(N)[None, :] + HOP * np.arange((len(mono) - N) // HOP)[:, None]
    S = np.abs(np.fft.rfft(mono[idx] * w, axis=1)) ** 2
    f = np.fft.rfftfreq(N, 1 / sr)
    tot = S.sum() or 1.0
    band = {"<250": (0, 250), "250-4k": (250, 4000), ">4k": (4000, sr / 2)}
    print(f"  peak {pk:.1f} dB　rms {rms:.1f} dB")
    for nm, (lo, hi) in band.items():
        pct = 100 * S[:, (f >= lo) & (f < hi)].sum() / tot
        print(f"  {nm:8} {pct:5.1f}%")
    if pk > -0.5:
        print("  ⚠ peak 贴顶，归一化可能没关")

    if not a.write:
        print("\n没有 --write，不碰工程文件。")
        return 0
    if not a.closed:
        print(f"\n✗ 暂不修改工程：没有确认已在 SynthV 里关闭 "
              f"{S3.PROJECT.name}。确认后加 --closed。")
        return 4
    if S3.synthv_running():
        print("\n✗ 检测到 SynthV 仍在运行，先退出它。")
        return 4

    print("\n" + "=" * 70)
    print("挂音频轨进工程")
    print("=" * 70)
    back = SB.read_back(S3.PROJECT)
    bk = S3.backup(S3.PROJECT)
    if bk:
        print(f"  已备份 → {bk}")
    b = SB.Builder(SB.load_template(S3.TEMPLATE), bpm=a.bpm)
    Q = SB.QUARTER_BLICKS
    for name, ns in back.items():
        gain = 0.0 if name.startswith("主旋律") else -5.0
        b.add_vocal(name, [dict(n) for n in ns], gain_db=gain)
        print(f"  保留 {name}　{len(ns)} 音符")
    b.add_audio("伴奏", SB.AudioTrack(str(AUDIO), len(mono) / sr, a.bpm),
                gain_db=-3.0)
    print(f"  新增 伴奏（音频轨）　{len(mono)/sr:.1f}s")
    saved = b.save(S3.PROJECT, force=True)
    print(f"\n工程写出　{saved}　{saved.stat().st_size} B"
          f"　{len(b.proj['tracks'])} 条轨")
    chk = SB.read_back(saved)
    allok = all(len(chk.get(k, [])) == len(v) for k, v in back.items())
    print(f"  {'✓' if allok else '✗'} 人声轨回读音符数一致")
    print(f"\n打开 {saved}，人声 + 伴奏应该同时响。")
    return 0 if allok else 3


if __name__ == "__main__":
    raise SystemExit(main())
