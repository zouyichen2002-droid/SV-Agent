# -*- coding: utf-8 -*-
"""生成参考音频：click + 和声垫 + 低音，以及「旋律 + 参考」的试听混音。

## 为什么必须有这个

一条清唱旋律**极难判断** —— 听不出它暗含的和声好不好、句末落音是悬着还是落定。
所以修正后的链路里，「创作者试听」这一步要配一条参考音频：
创作者把它像音频轨一样拖进 SynthV，就能让声库的旋律和参考一起放。

这一步成本几乎为零，但它是「不满意就回炉」和「白做三步」的分界。

两个产出：

  参考_click和声_<song>.wav   click + 和声垫 + 低音。**拖进 SynthV 用这个**
  试听_旋律和参考_<song>.wav  上面那条 + 旋律正弦。写进 SV 之前先用这个过一遍耳

和声垫刻意压在旋律下方一个八度左右（旋律 E4–E5，垫在 MIDI 41–60），
避免和旋律抢频段、也避免听不清旋律的音高。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

SR = 44100


def hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def env_adsr(n: int, atk: float, rel: float, sr: int = SR) -> np.ndarray:
    a = max(1, int(atk * sr))
    r = max(1, int(rel * sr))
    e = np.ones(n)
    if a < n:
        e[:a] = np.linspace(0, 1, a)
    if r < n:
        e[-r:] = np.linspace(1, 0, r)
    return e


def tone(midi: float, dur_s: float, harmonics=(1.0,), level_db=-20.0,
         atk=0.01, rel=0.05) -> np.ndarray:
    n = max(1, int(dur_s * SR))
    t = np.arange(n) / SR
    y = np.zeros(n)
    for k, g in enumerate(harmonics, start=1):
        if g:
            y += g * np.sin(2 * np.pi * hz(midi) * k * t)
    return y * env_adsr(n, atk, rel) * (10 ** (level_db / 20))


def click(accent: bool) -> np.ndarray:
    """短促的打点。重音用更高的频率。"""
    dur = 0.03
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 2400.0 if accent else 1400.0
    y = np.sin(2 * np.pi * f * t) * np.exp(-t * 260.0)
    return y * (10 ** ((-13.0 if accent else -19.0) / 20))


def add(buf: np.ndarray, seg: np.ndarray, at_s: float) -> None:
    i = int(at_s * SR)
    j = min(i + seg.size, buf.size)
    if j > i:
        buf[i:j] += seg[: j - i]


def render(bpm: float, n_bars: int, chords: list[tuple[int, tuple[int, ...]]],
           melody: list[tuple[float, float, int]] | None = None):
    """chords: [(起始小节, (MIDI 三音)), ...]；melody: [(起拍, 时长拍, MIDI), ...]"""
    spb = 60.0 / bpm                      # 每拍秒数
    total = n_bars * 4 * spb + 1.0
    ref = np.zeros(int(total * SR))
    mel = np.zeros_like(ref)

    # click：每拍一下，每小节第一拍重音
    for b in range(n_bars * 4):
        add(ref, click(b % 4 == 0), b * spb)

    # 和声垫 + 低音
    for k, (bar0, triad) in enumerate(chords):
        bar1 = chords[k + 1][0] if k + 1 < len(chords) else n_bars
        t0 = bar0 * 4 * spb
        dur = (bar1 - bar0) * 4 * spb
        for m in triad:
            add(ref, tone(m, dur, harmonics=(1.0, 0.28, 0.12),
                          level_db=-27.0, atk=0.12, rel=0.35), t0)
        add(ref, tone(triad[0] - 12, dur, harmonics=(1.0, 0.35),
                      level_db=-22.0, atk=0.04, rel=0.25), t0)

    if melody:
        for onset_b, dur_b, midi in melody:
            add(mel, tone(midi, dur_b * spb, harmonics=(1.0, 0.22, 0.07),
                          level_db=-15.0, atk=0.012, rel=0.06), onset_b * spb)
    return ref, mel


def write(path: Path, y: np.ndarray) -> None:
    pk = float(np.abs(y).max())
    if pk > 0.99:
        y = y * (0.99 / pk)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), y.astype(np.float32), SR, subtype="PCM_16")
    print(f"  {path.name}　{y.size/SR:.1f}s")


# 各和弦的三音，压在旋律下方（旋律 59–76，垫在 41–60）
TRIAD = {"Am": (45, 52, 57), "F": (41, 48, 53),
         "C": (48, 55, 60), "G": (43, 50, 55)}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-module", default="melody_v2")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "out"))
    mod = __import__(a.song_module)
    BPM = mod.BPM
    n_bars = getattr(mod, "N_BARS", 10)

    notes, _, _ = mod.build()
    melody = [(n.onset_beats, n.duration_beats, n.midi) for n in notes]

    # 和声进行从曲式里推：每句 2 小节一个和弦；段落之间的空白沿用前一个和弦
    if hasattr(mod, "SECTIONS"):
        name_of = {v: k for k, v in
                   (("Am", mod.Am), ("F", mod.F), ("C", mod.C), ("G", mod.G))}
        chords = [(0, TRIAD["Am"])]           # 前奏
        for _, bar0, lines in mod.SECTIONS:
            for li, (_, _, ch) in enumerate(lines):
                chords.append((bar0 + li * 2, TRIAD[name_of[ch]]))
        chords.append((n_bars - 2, TRIAD["Am"]))   # 尾奏
        chords = sorted({b: t for b, t in chords}.items())
    else:
        chords = [(0, TRIAD["Am"]), (2, TRIAD["F"]), (4, TRIAD["C"]),
                  (6, TRIAD["Am"]), (8, TRIAD["Am"])]
    ref, mel = render(BPM, n_bars, chords, melody)

    out = Path(__file__).resolve().parents[1] / "out" / "listen_yuzhou"
    print(f"{a.song_module}　{BPM:.0f} BPM · {n_bars} 小节 · "
          f"{len(chords)} 个和弦段")
    print("和声垫压在 MIDI 41–60，旋律在 64–76，不抢频段\n")
    tag = a.song_module.replace("melody_", "")
    write(out / f"参考_click和声_{tag}.wav", ref)
    write(out / f"试听_旋律和参考_{tag}.wav", ref * 0.72 + mel)
    print(f"\n全部在 {out}")
    print("拖进 SynthV 的是「参考_click和声.wav」；写进 SV 之前先听「试听_旋律和参考」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
