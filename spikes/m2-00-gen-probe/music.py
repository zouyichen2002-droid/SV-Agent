# -*- coding: utf-8 -*-
"""探针的乐理部分：和弦解析、配和声、拍 → 秒、渲染钢琴试听、写 .svp。

**不重写 M0 验证过的部件**：
- 钢琴渲染器、WAV 写出 → `spikes/m0-01-piano-preview/renderers.py`（gm.dls，固定增益，不逐文件归一化）
- `.svp` 模板、声库引用、音符字段 → `spikes/m0-04-svp/make_test_svp.py`

伴奏是最朴素的柱式和弦 + 根音，只为托住和声 —— 这一批评的是旋律、和声、节奏，不是编曲。
"""
from __future__ import annotations

import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "m0-01-piano-preview"))
sys.path.insert(0, os.path.join(HERE, "..", "m0-04-svp"))

import renderers          # noqa: E402  M0-01
import make_test_svp      # noqa: E402  M0-04

BEATS_PER_BAR = 4
MEL_VEL, CHORD_VEL, BASS_VEL = 100, 62, 78     # 和 M0-01 标准样本一致：MASTER 是按它定的

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
QUALITIES = {
    "": [0, 4, 7], "m": [0, 3, 7], "min": [0, 3, 7],
    "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "M7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10], "min7": [0, 3, 7, 10], "mmaj7": [0, 3, 7, 11],
    "dim": [0, 3, 6], "dim7": [0, 3, 6, 9], "m7b5": [0, 3, 6, 10],
    "aug": [0, 4, 8], "+": [0, 4, 8],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "sus": [0, 5, 7], "7sus4": [0, 5, 7, 10],
    "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9],
    "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14],
    "9": [0, 4, 7, 10, 14], "m9": [0, 3, 7, 10, 14], "maj9": [0, 4, 7, 11, 14],
    # 09-28 第一次真跑后补：常见的扩展写法，免得把合法和弦判成「写错」、逼模型把和弦改简单
    "maj": [0, 4, 7], "M": [0, 4, 7], "add2": [0, 2, 4, 7], "2": [0, 2, 4, 7], "madd2": [0, 2, 3, 7],
    "69": [0, 4, 7, 9, 14], "m69": [0, 3, 7, 9, 14], "11": [0, 4, 7, 10, 14, 17], "m11": [0, 3, 7, 10, 14, 17],
    "13": [0, 4, 7, 10, 14, 21], "maj13": [0, 4, 7, 11, 14, 21], "add11": [0, 4, 7, 17],
    "7b9": [0, 4, 7, 10, 13], "7#9": [0, 4, 7, 10, 15], "7#11": [0, 4, 7, 10, 18], "7b13": [0, 4, 7, 10, 20],
    "maj7#11": [0, 4, 7, 11, 18], "9sus4": [0, 5, 7, 10, 14], "sus2sus4": [0, 2, 5, 7],
    "°": [0, 3, 6], "°7": [0, 3, 6, 9], "ø": [0, 3, 6, 10], "ø7": [0, 3, 6, 10], "m7-5": [0, 3, 6, 10],
    "aug7": [0, 4, 8, 10], "+7": [0, 4, 8, 10], "7+5": [0, 4, 8, 10], "7b5": [0, 4, 6, 10],
}
_CHORD = re.compile(r"^([A-G])([#b]?)([A-Za-z0-9+#°ø\-]*)(?:/([A-G])([#b]?))?$")


def pitch_class(letter: str, accidental: str) -> int:
    return (PC[letter] + {"#": 1, "b": -1, "": 0}[accidental]) % 12


def _normalize(symbol: str) -> str:
    """「Am(add9)」→「Amadd9」、「C6/9」→「C69」、全角括号、多余空格。只改写法，不改和弦。"""
    s = symbol.strip().replace(" ", "").replace("（", "(").replace("）", ")")
    s = s.replace("6/9", "69").replace("(", "").replace(")", "")
    return s


def parse_chord(symbol: str) -> tuple[int, list[int], int]:
    """「F#m7b5」「C/E」→ (根音音级, 各音相对根音的半音数, 低音音级)。认不出就抛 ValueError。"""
    m = _CHORD.match(_normalize(symbol)) if isinstance(symbol, str) else None
    if not m or m.group(3) not in QUALITIES:
        raise ValueError(f"和弦写法认不出：{symbol!r}")
    root = pitch_class(m.group(1), m.group(2))
    bass = pitch_class(m.group(4), m.group(5)) if m.group(4) else root
    return root, QUALITIES[m.group(3)], bass


def voicing(symbol: str) -> tuple[int, list[int]]:
    """→ (低音 MIDI, 和弦音 MIDI)。和弦音压在 48–59，低音在 36–47，不和旋律（57–76）抢位置。"""
    root, intervals, bass = parse_chord(symbol)
    tones = sorted({48 + ((root + iv - 48) % 12) for iv in intervals})
    return 36 + ((bass - 36) % 12), tones


def notes_in_beats(cand: dict) -> list[tuple[float, float, int, int, str]]:
    """候选 → [(起拍, 时值拍, 音高, 力度, 声部)]。拍位置按全曲算：第 n 小节从 (n-1)×4 拍开始。"""
    out = []
    bars = cand["bars"]
    for b in bars:
        b0 = (b["bar"] - 1) * BEATS_PER_BAR
        for st, du, p, _ in b["melody"]:
            out.append((b0 + st, du, p, MEL_VEL, "melody"))
        chords = b["chords"]
        last = b["bar"] == len(bars)
        segments = [(0, 4, chords[0])] if len(chords) == 1 else [(0, 2, chords[0]), (2, 2, chords[1])]
        for s0, sd, sym in segments:
            bass, tones = voicing(sym)
            out.append((b0 + s0, sd, bass, BASS_VEL, "bass"))
            hits = [(s0, sd)] if (last or sd == 2) else [(s0, 2), (s0 + 2, 2)]
            for h0, hd in hits:
                for p in tones:
                    out.append((b0 + h0, hd, p, CHORD_VEL, "chord"))
    return sorted(out)


def seconds_per_beat(cand: dict) -> float:
    return 60.0 / cand["bpm"]


def music_seconds(cand: dict) -> float:
    return len(cand["bars"]) * BEATS_PER_BAR * seconds_per_beat(cand)


def render_wav(cand: dict, path: str, piano) -> dict:
    """渲染钢琴试听 → {秒数, 峰值, RMS, 削波}。拍 → 秒只在这里换算一次（PRD §10.1）。"""
    spb = seconds_per_beat(cand)
    notes = [(t * spb, d * spb, p, v) for t, d, p, v, _ in notes_in_beats(cand)]
    audio = piano.render(notes)
    peak, rms, clipped = renderers.write_wav(path, audio)
    return {"seconds": len(audio) / renderers.SR, "peak_db": peak, "rms_db": rms, "clipped": clipped}


def build_svp(cand: dict, label: str, render_dir: str, database: dict) -> dict:
    """只放人声旋律和歌词（伴奏不进 .svp）。拖腔的「-」原样写进 SynthV 的歌词。"""
    q = make_test_svp.QUARTER
    d = make_test_svp.template()
    d["uuid"] = str(uuid.uuid4())
    d["time"]["tempo"] = [{"position": 0, "bpm": cand["bpm"]}]
    d["time"]["meter"] = [{"index": 0, "numerator": 4, "denominator": 4}]
    tr = d["tracks"][0]
    tr["name"] = f"探针 {label}"
    tr["mainRef"]["database"] = database
    notes = []
    for b in cand["bars"]:
        b0 = (b["bar"] - 1) * BEATS_PER_BAR
        for st, du, p, ly in b["melody"]:
            notes.append(make_test_svp.note(round((b0 + st) * q), round(du * q), p, ly))
    tr["mainGroup"]["notes"] = notes
    d["renderConfig"].update(destination=render_dir, filename=label)
    return d
