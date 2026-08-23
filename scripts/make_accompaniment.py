# -*- coding: utf-8 -*-
"""从旋律模块推导和声进行，生成分轨伴奏 MIDI + 可听预览。

## 为什么走 MIDI 而不是直接生成音频

对齐是这条链上唯一会毁掉前面全部工作的风险。**MIDI 导入是 FL Studio 的原生
能力，时间信息一个 tick 不丢** —— 绕开了「实时 MIDI 录制」那层抖动。
生成模型（Suno / MusicGen）给不了这个保证：它们不会遵守我们 48 小节的段落边界。

分工：这里出精确骨架，FL 里配音源和混音（那是 flstudio-mcp 的强项 ——
它 52 个工具里有 18 个是混音/EQ/压缩/路由，而写音符只有 2 个印度 raga 专用的）。

## 声部不与旋律抢频段

旋律在 MIDI 59–76（B3–E5）。所以：

    贝斯   29–48   压在下面
    垫     41–55   顶音 ≤55，离旋律最低音 59 留 4 个半音（原来顶 60，会打拍）
    琶音   77–88   抬到上面（旋律顶到 76），做"星尘"质感
    副线   67–72   **在旋律的频段内**，所以靠时间避让：只在间奏出现
    打击   GM 通道 10

## 编排有段落起伏，不是 48 小节铺一样的东西

    前奏    垫 + 琶音，无鼓                     —— 留白
    主歌1  垫 + 贝斯，只有闭合镲               —— 第一段主歌最素，给人声空间
    预副1  加底鼓，开始推
    副歌1  全部声部 + 完整鼓组
    间奏    掉到垫 + 琶音 + 副线                 —— 人声缺席，副线接话
    主歌2  比主歌1 多一层琶音
    预副2  同预副1
    副歌2  最满
    尾奏    只剩垫，衰减

用法:
    python scripts/make_accompaniment.py                      # 出 MIDI + 预览音频
    python scripts/make_accompaniment.py --song-module melody_v2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "out"))
sys.stdout.reconfigure(encoding="utf-8")

TPB = 480              # ticks per beat
SR = 44100

# 和弦名 → (贝斯根音, 垫, 琶音, 副线)
#
# 琶音整体抬到 77 以上 —— 旋律顶到 76(E5)，压在它下面会打架。
# 垫的顶音一律 ≤55(G3) —— 旋律最低到 59(B3)，顶音放 60 会与它形成半音/同音打拍。
# 副线在 67–72，那是旋律的地盘，所以它**只在人声缺席的段落**出现。
# 各声部的频段带。声部排列**按根音算出来**，不查表。
#
# 原来是一张 `VOICING` 表，按绝对和弦名（Am/F/C/G…）索引。
# `SongSpec` 一旦换调，就会出现表里没有的和弦（Cm、Ab、Eb…）直接 KeyError。
# 加表项是治不完的 —— 12 个调 × 6 个级数 = 72 项。所以改成计算。
BANDS = {"bass": (36, 48), "pad": (41, 55), "arp": (77, 88),
         "counter": (67, 72)}
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def chord_label(root_pc: int, quality: str) -> str:
    return NOTE_NAMES[root_pc % 12] + ("m" if quality == "minor" else "")


def voicing_for(root_pc: int, quality: str):
    """(根音音级, 大小) → (贝斯, 垫, 琶音, 副线)。任意调都成立。"""
    triad = (0, 4, 7) if quality == "major" else (0, 3, 7)
    pcs = {(root_pc + t) % 12 for t in triad}

    def take(lo, hi, n):
        """取该频段内最低的 n 个**不同音级**的和弦音。"""
        out, seen = [], set()
        for m in range(lo, hi + 1):
            if m % 12 in pcs and m % 12 not in seen:
                out.append(m)
                seen.add(m % 12)
                if len(out) == n:
                    break
        return tuple(out)

    # 贝斯根音取**离目标最近**的那个八度，不是频段内最低的。
    # 取最低会让不同和弦在八度间跳（C 掉到 C2=36），而且减五度推进音
    # 会变成 31 = 43Hz —— 那正是我之前修过的「小音箱上只剩浑浊」。
    lo, hi = BANDS["bass"]
    BASS_TARGET = 43                        # G2，约 98Hz
    roots = [m for m in range(lo, hi + 1) if m % 12 == root_pc % 12]
    bass = (min(roots, key=lambda m: abs(m - BASS_TARGET)) if roots
            else take(lo, hi, 1)[0])
    pad = take(*BANDS["pad"], 3)
    arp = take(*BANDS["arp"], 3)
    cnt = take(*BANDS["counter"], 2)
    if len(cnt) < 2:                  # 副线频段只有 6 个半音，可能装不下两个
        cnt = (pad[-1] + 12, pad[0] + 12) if pad else (69, 72)
    return bass, pad, arp, cnt
# GM 打击音符
KICK, SNARE, CLAP, HAT, OPENHAT, RIDE = 36, 38, 39, 42, 46, 51

# ---------------------------------------------------------------- 律动
#
# **为什么需要这些表**
#
# 2026-08-23 创作者的诊断：**「不是旋律像，而是伴奏，就是那个 4/4 拍的伴奏
# 基本一样」**。实测证实：垫 1 种、贝斯 3 种、琶音 8 种、鼓 13 种节奏型，
# 跨歌**重合 100%** —— 全是硬编码常量，只有音高跟着和弦变。
#
# 而律动是伴奏辨识度的全部来源。所以这些原本写死的模式必须变成每首歌的参数。
#
# **不能指望换音源解决**：`.mid` 里的节奏就是最终的节奏，FL 只给它音色。
#
# 每个模式是 [(拍偏移, 时长, 取和弦第几个音, 力度)]；音序号 None = 全部同时。

PAD_STYLES = {
    "sustain": [(0.0, 4.0, None, 74)],                      # 铺满，最静
    "half":    [(0.0, 1.9, None, 74), (2.0, 1.9, None, 66)],
    "pulse":   [(i * 1.0, 0.9, None, 70 - i * 3) for i in range(4)],
    "offbeat": [(0.5, 1.4, None, 68), (2.5, 1.4, None, 62)],  # 反拍，推着走
}

ARP_FIGURES = {
    "updown": [(i * 0.5, 0.45, i, 54) for i in range(8)],
    "up":     [(i * 0.5, 0.45, i % 3, 54) for i in range(8)],
    "broken": [(0.0, 0.9, 0, 60), (1.0, 0.9, 2, 52),
               (2.0, 0.9, 1, 56), (3.0, 0.9, 2, 50)],
    "pulse16": [(i * 0.25, 0.22, i % 3, 46) for i in range(16)],
    "sparse": [(0.0, 1.8, 2, 58), (2.5, 1.4, 1, 50)],
}

BASS_GROOVES = {
    "1-3":  [(0.0, 1.8, 88), (2.0, 1.3, 76)],               # 原来那一种
    "four": [(i * 1.0, 0.9, 84 - i * 2) for i in range(4)],
    "sync": [(0.0, 1.4, 90), (1.5, 0.9, 74), (3.0, 0.9, 78)],
    "long": [(0.0, 3.8, 84)],
    "push": [(0.0, 0.9, 88), (0.75, 0.7, 72), (2.0, 1.8, 80)],
}

# 鼓：每个密度档给两种以上写法，(底鼓拍, 拍手拍, 镲的分割, 有无叮叮)
DRUM_STYLES = {
    "hat-4":    ((), (), 1.0, False),
    "hat-8":    ((), (), 0.5, False),
    "kick-2":   ((0.0, 2.0), (), 0.5, False),
    "backbeat": ((0.0, 2.0), (1.0, 3.0), 0.5, False),
    "four-fl":  ((0.0, 1.0, 2.0, 3.0), (1.0, 3.0), 0.5, True),
    # 与《宇宙无边无垠》原来的 full 逐事件一致，用作向后兼容的默认
    "ballad":   ((0.0, 2.0), (1.0, 3.0), 0.5, True),
    "half":     ((0.0,), (2.0,), 1.0, True),
    "none":     ((), (), 0.0, False),
}

# 密度档 → 可选的鼓写法。DENSITY 里的 drum 字段现在是**档位**，具体写法由规格挑
DRUM_BY_LEVEL = {
    "none":  ("none",),
    "hat":   ("hat-4", "hat-8", "half"),
    "build": ("kick-2", "backbeat", "hat-8"),
    "full":  ("ballad", "four-fl", "backbeat", "half"),
}

# 每段的编排密度：(垫, 贝斯, 琶音, 鼓型, 副线)
# 鼓型: none / hat / build / full
DENSITY = {
    # 不带编号的键是**回退目标**，供 density_of() 用（《夜曲》这类
    # 只有「主歌/副歌」两段的曲式直接命中这里）
    "主歌":  (True,  True,  True,  "hat",   False),
    "副歌":  (True,  True,  True,  "full",  False),
    "预副":  (True,  True,  True,  "build", False),
    "前奏":  (True,  False, True,  "none",  False),
    "主歌1": (True,  True,  False, "hat",   False),
    "预副1": (True,  True,  True,  "build", False),
    "副歌1": (True,  True,  True,  "full",  False),
    "间奏":  (True,  False, True,  "hat",   True),
    "主歌2": (True,  True,  True,  "hat",   False),
    "预副2": (True,  True,  True,  "build", False),
    "副歌2": (True,  True,  True,  "full",  False),
    "尾奏":  (True,  False, False, "none",  False),
}


def density_of(name: str):
    """段名 → 编排密度。带编号的段落（主歌1/副歌2）回退到不带编号的。

    这样《宇宙无边无垠》的「主歌1」和《夜曲》的「主歌」共用一套规则，
    不必为每首歌各写一张表。
    """
    if name in DENSITY:
        return DENSITY[name]
    stem = name.rstrip("0123456789")
    if stem in DENSITY:
        return DENSITY[stem]
    return DENSITY["主歌"]          # 兜底：最素的那一档


def chord_map(mod):
    """每个小节 → (根音音级, 大小)。段落之间的空白沿用前一个。

    返回音级而不是和弦名 —— 换调之后和弦名会变（Am→Cm），
    但曲式里存的本来就是 (root, quality)，没必要绕一圈名字。
    """
    tonic = (getattr(mod, "KEY_ROOT", 9), getattr(mod, "KEY_QUALITY", "minor"))
    # 行距不能写死 2 —— SongSpec 的 bars_per_line 可以是 4
    bpl = getattr(mod, "BARS_PER_LINE", 2)
    at = {0: tonic}
    for _, bar0, lines in mod.SECTIONS:
        for li, (_, _, ch) in enumerate(lines):
            at[bar0 + li * bpl] = tuple(ch)
    out, cur = {}, tonic
    for b in range(mod.N_BARS):
        cur = at.get(b, cur)
        out[b] = cur
    # 无词段落一律回主和弦。不能靠"沿用前一个"——那会让间奏继承副歌末句的 G
    for b, name in section_map(mod).items():
        if name in ("前奏", "间奏", "尾奏"):
            out[b] = tonic
    return out


def section_map(mod) -> dict[int, str]:
    """每个小节属于哪一段。"""
    out = {}
    # 行距不能写死 2 —— 与 chord_map 用同一个来源
    bpl = getattr(mod, "BARS_PER_LINE", 2)
    for name, bar0, lines in mod.SECTIONS:
        for b in range(bar0, bar0 + len(lines) * bpl):
            out[b] = name
    for b in range(mod.N_BARS):
        if b not in out:
            if b < 4:
                out[b] = "前奏"
            elif b >= mod.N_BARS - 2:
                out[b] = "尾奏"
            else:
                out[b] = "间奏"
    return out


def build_parts(mod):
    """返回 {声部名: [(起拍, 时长拍, MIDI, 力度), ...]}。"""
    ch = chord_map(mod)
    sec = section_map(mod)
    # 律动从歌曲模块读，读不到就用《宇宙无边无垠》原来那套 —— 保证旧歌回归不变
    groove = {
        "pad": getattr(mod, "PAD_STYLE", "sustain"),
        "bass": getattr(mod, "BASS_GROOVE", "1-3"),
        "arp": getattr(mod, "ARP_FIGURE", "updown"),
        "drum": getattr(mod, "DRUM_PICK",
                        {"hat": "hat-4", "build": "kick-2",
                         "full": "ballad", "none": "none"}),
    }
    parts: dict[str, list] = {k: [] for k in
                              ("垫", "贝斯", "琶音", "副线", "鼓")}
    for b in range(mod.N_BARS):
        name = sec[b]
        pad_on, bass_on, arp_on, drum, cnt_on = density_of(name)
        root, pad, arp, cnt = voicing_for(*ch[b])
        t0 = b * 4.0

        quiet = name in ("前奏", "尾奏", "间奏")

        if pad_on:
            for off, dur, _vi, vel in PAD_STYLES[groove["pad"]]:
                for m in pad:
                    parts["垫"].append((t0 + off, dur, m,
                                       vel - (12 if quiet else 0)))
        if bass_on:
            # 同八度（降八度会掉到 F1=43Hz，只剩浑浊）
            for off, dur, vel in BASS_GROOVES[groove["bass"]]:
                parts["贝斯"].append((t0 + off, dur, root, vel))
            if drum in ("build", "full"):
                # 第 4 拍后半下五度，推进下一小节
                parts["贝斯"].append((t0 + 3.5, .4, root - 5, 70))
        if arp_on:
            # 全部在 77 以上，在旋律头顶
            seq = list(arp) + list(arp)[::-1][1:-1]
            for off, dur, vi, vel in ARP_FIGURES[groove["arp"]]:
                parts["琶音"].append((t0 + off, dur, seq[vi % len(seq)], vel))
        if cnt_on:
            # 副线在旋律的地盘上，所以只在人声缺席的段落说话
            parts["副线"].append((t0, 2.0, cnt[0], 66))
            parts["副线"].append((t0 + 2, 2.0, cnt[1], 62))

        # 鼓：DENSITY 给档位，规格给这一档里的具体写法
        style = groove["drum"].get(drum) or DRUM_BY_LEVEL[drum][0]
        kicks, claps, hat_div, ride = DRUM_STYLES[style]
        for k in kicks:
            parts["鼓"].append((t0 + k, 0.4, KICK, 96 if k == 0 else 88))
        for c in claps:
            parts["鼓"].append((t0 + c, 0.4, CLAP, 88))
        if hat_div:
            n_hat = int(round(4.0 / hat_div))
            for i in range(n_hat):
                last = (i == n_hat - 1) and hat_div <= 0.5
                parts["鼓"].append((t0 + i * hat_div, 0.2,
                                   OPENHAT if last else HAT,
                                   48 + (i % 2) * 10))
        if ride:
            parts["鼓"].append((t0, 3.8, RIDE, 40))
    return parts, ch, sec


def reference_backing(mod, mode: str = "ref"):
    """**试听用**的中性垫，不是成品伴奏。

    ## 为什么要和成品伴奏分开

    2026-08-23 创作者提出「要不旋律不加伴奏了，或者加纯鼓声的伴奏？」——
    他的判断对：试听音频的目的是判**旋律**，成品伴奏在这里是干扰项。

    但纯清唱也不行。早先记过的教训（`make_reference_audio.py` 开头）：
    **一条清唱旋律极难判断** —— 听不出它暗含的和声好不好、
    句末落音是悬着还是落定。纯鼓声同样没有和声。

    所以这是两个不同的产物，我原来错在用同一套代码生成：

        试听参考垫  中性、**故意所有候选都一样**、极简、用完就扔
        成品伴奏    有辨识度、每首歌不同、完整（`build_parts`）

    参考垫「所有候选都一样」是**优点**：只要它明显是个参考垫，
    听者就会把全部差异归给旋律。

    模式：
        ref    底鼓打拍 + 每小节一个贝斯长音（推荐：有和声，无律动）
        drums  只有鼓
        none   什么都没有
        full   成品伴奏（= build_parts，用来对比）
    """
    if mode == "full":
        return build_parts(mod)[0]
    parts = {k: [] for k in ("垫", "贝斯", "琶音", "副线", "鼓")}
    if mode == "none":
        return parts
    ch = chord_map(mod)
    for b in range(mod.N_BARS):
        t0 = b * 4.0
        if mode in ("ref", "drums"):
            parts["鼓"].append((t0, 0.4, KICK, 92))
            parts["鼓"].append((t0 + 2, 0.4, KICK, 80))
            for i in range(4):
                parts["鼓"].append((t0 + i, 0.18, HAT, 44))
        if mode == "ref":
            # 一个小节一个长音：和声信息给足，律动信息给零
            root, _pad, _arp, _cnt = voicing_for(*ch[b])
            parts["贝斯"].append((t0, 3.9, root, 78))
    return parts


# GM program（0-indexed）。FL 里你会重新指派音源，这里只给个不至于全是钢琴的默认
PROGRAM = {"垫": 88, "贝斯": 38, "琶音": 98, "副线": 52}

# mido 的 MetaMessage 按 latin-1 编码轨名，中文轨名直接抛 UnicodeEncodeError。
# 换 ASCII 不是妥协 —— FL 的 channel rack 显示 ASCII 也更干净。
MIDI_NAME = {"垫": "Pad", "贝斯": "Bass", "琶音": "Arp",
             "副线": "Counter", "鼓": "Drums"}


def write_midi(parts: dict, bpm: float, path: Path) -> None:
    import mido

    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name="tempo", time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4,
                                 time=0))
    mid.tracks.append(meta)

    for i, (name, evs) in enumerate(parts.items()):
        if not evs:
            continue
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=MIDI_NAME[name],
                                   time=0))
        chan = 9 if name == "鼓" else i
        if name != "鼓":
            tr.append(mido.Message("program_change", channel=chan,
                                   program=PROGRAM[name], time=0))
        # 展成 (tick, 类型, 音高, 力度) 再按时间排序，转成 delta
        raw = []
        for onset, dur, midi, vel in evs:
            on = int(round(onset * TPB))
            off = max(on + 1, int(round((onset + dur) * TPB)))
            raw.append((on, 1, midi, vel))
            raw.append((off, 0, midi, 0))
        raw.sort(key=lambda x: (x[0], x[1]))     # 同刻先关后开，避免叠音
        prev = 0
        for tick, kind, midi, vel in raw:
            msg = "note_on" if kind else "note_off"
            tr.append(mido.Message(msg, channel=chan, note=midi,
                                   velocity=vel, time=tick - prev))
            prev = tick
        mid.tracks.append(tr)
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(path))


# ---------------- 预览音频（写进 FL 之前先用耳朵过一遍） ----------------

def _tone(midi, dur_s, harms, level_db, atk=.01, rel=.08):
    n = max(1, int(dur_s * SR))
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((midi - 69) / 12)
    y = sum(g * np.sin(2 * np.pi * f * k * t)
            for k, g in enumerate(harms, 1) if g)
    a, r = max(1, int(atk * SR)), max(1, int(rel * SR))
    e = np.ones(n)
    if a < n:
        e[:a] = np.linspace(0, 1, a)
    if r < n:
        e[-r:] = np.linspace(1, 0, r)
    return y * e * 10 ** (level_db / 20)


def _noise(dur_s, level_db, decay):
    n = max(1, int(dur_s * SR))
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    return rng.standard_normal(n) * np.exp(-t * decay) * 10 ** (level_db / 20)


TIMBRE = {                     # (泛音, 电平dB, 起音, 释音)
    "垫":   ((1., .30, .14, .06), -30., .35, .60),
    "贝斯": ((1., .40, .10),      -20., .01, .10),
    "琶音": ((1., .18, .05),      -28., .005, .05),
    "副线": ((1., .25, .10),      -27., .20, .40),
}


def render_preview(parts, melody, bpm, n_bars):
    spb = 60.0 / bpm
    buf = np.zeros(int((n_bars * 4 * spb + 2.0) * SR))
    acc = np.zeros_like(buf)

    def add(dst, seg, at_s):
        i = int(at_s * SR)
        j = min(i + seg.size, dst.size)
        if j > i:
            dst[i:j] += seg[: j - i]

    for name, evs in parts.items():
        if name == "鼓":
            for onset, dur, midi, vel in evs:
                lv = -16. if midi == KICK else (-19. if midi in (SNARE, CLAP) else -26.)
                if midi == KICK:
                    seg = _tone(31, .18, (1., .3), lv, .002, .12)
                elif midi in (SNARE, CLAP):
                    seg = _noise(.12, lv, 42.)
                else:
                    seg = _noise(.05, lv, 160.)
                add(acc, seg * (vel / 100), onset * spb)
            continue
        harms, lv, atk, rel = TIMBRE[name]
        for onset, dur, midi, vel in evs:
            add(acc, _tone(midi, dur * spb, harms, lv, atk, rel) * (vel / 90),
                onset * spb)
    mel = np.zeros_like(buf)
    for onset, dur, midi in melody:
        add(mel, _tone(midi, dur * spb, (1., .22, .07), -14., .012, .06),
            onset * spb)
    return acc, mel


def _write_wav(path: Path, y):
    pk = float(np.abs(y).max())
    if pk > .99:
        y = y * (.99 / pk)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), y.astype(np.float32), SR, subtype="PCM_16")
    print(f"  {path.name}　{y.size/SR:.1f}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-module", default="melody_v2")
    a = ap.parse_args()
    mod = __import__(a.song_module)
    tag = a.song_module.replace("melody_", "")

    parts, ch, sec = build_parts(mod)
    notes, _, _ = mod.build()
    melody = [(n.onset_beats, n.duration_beats, n.midi) for n in notes]

    print(f"《宇宙无边无垠》伴奏　{mod.BPM:.0f} BPM · {mod.N_BARS} 小节 · A 小调\n")
    print("段落编排：")
    seen = []
    for b in range(mod.N_BARS):
        if not seen or seen[-1][0] != sec[b]:
            seen.append((sec[b], b, b))
        else:
            seen[-1] = (sec[b], seen[-1][1], b)
    for name, b0, b1 in seen:
        pad, bass, arp, drum, cnt = density_of(name)
        on = [n for n, f in (("垫", pad), ("贝斯", bass), ("琶音", arp),
                             ("副线", cnt)) if f]
        prog, seen_ch = [], None
        for b in range(b0, b1 + 1):
            if ch[b] != seen_ch:
                prog.append(chord_label(*ch[b]))
                seen_ch = ch[b]
        print(f"  {name:5} 第{b0+1:2d}–{b1+1:2d}小节  {'–'.join(prog):14} "
              f"鼓={drum:5}  {' '.join(on)}")
    print("\n各声部音符数与音域：")
    for name, evs in parts.items():
        if not evs:
            continue
        ms = [m for _, _, m, _ in evs]
        rng = ("GM 打击" if name == "鼓"
               else f"MIDI {min(ms)}–{max(ms)}")
        print(f"  {name:5} {len(evs):4d} 个　{rng}")
    lo = min(m for _, _, m in melody)
    hi = max(m for _, _, m in melody)
    print(f"  旋律在 MIDI {lo}–{hi}。垫和贝斯压在它下面、琶音抬到它上面；")
    print(f"  副线在它的频段内，靠**只在人声缺席的段落出现**来避让。")

    out = Path(__file__).resolve().parents[1] / "out" / "listen_yuzhou"
    midi_path = out / f"伴奏_{tag}.mid"
    write_midi(parts, mod.BPM, midi_path)
    print(f"\nMIDI 写出　{midi_path}")

    # 旋律参考单独出一份。混进伴奏文件容易在 FL 里顺手挂上音源，
    # 变成给人声叠一层合成器 —— 人声在 SynthV 里，这份只作编曲时的定位参照
    ref_path = out / f"旋律参考_{tag}.mid"
    write_midi({"副线": [(o, d, m, 80) for o, d, m in melody]},
               mod.BPM, ref_path)
    print(f"旋律参考　　{ref_path}（编曲定位用，别挂音源）")

    acc, mel = render_preview(parts, melody, mod.BPM, mod.N_BARS)
    print("预览音频：")
    _write_wav(out / f"伴奏预览_{tag}.wav", acc)
    _write_wav(out / f"伴奏加旋律_{tag}.wav", acc * .85 + mel)
    print(f"\n先听「伴奏加旋律_{tag}.wav」判编排，再把 MIDI 导入 FL 配音源")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
