# -*- coding: utf-8 -*-
"""M0-01 的标准样本：16 小节 · 4/4 · 76 BPM · C 大调 · 主旋律 + 和声 + 低音。

PRD §8.1 规定标准样本是「8–16 小节、主旋律与和声、单一固定钢琴音源」。
这里取上限 16 小节、偏慢的 76 BPM —— 音频最长（50.5 秒），是最坏情况。

音符用「拍」记（1 拍 = 1 个四分音符），换算成秒只在 notes_in_seconds() 里做一次
（PRD §10.1：拍位置与实际秒数分开表示，转换规则显式）。
"""
BPM = 76
BEATS_PER_BAR = 4
BARS = 16

# 每小节一个和弦：前 8 小节像主歌，后 8 小节像副歌
CHORDS = ["C", "G", "Am", "Em", "F", "C", "F", "G",
          "C", "G", "Am", "Em", "F", "C", "G", "C"]

# 和弦 → (低音, 三个和弦音)，MIDI 音高。和弦音压在 47–57，不和旋律（60–74）打架
VOICING = {
    "C":  (36, [48, 52, 55]),
    "G":  (43, [47, 50, 55]),
    "Am": (45, [48, 52, 57]),
    "Em": (40, [47, 52, 55]),
    "F":  (41, [48, 53, 57]),
}

# 主旋律：每小节若干 (小节内起拍, 音高, 时值拍数)
MELODY = [
    [(0, 67, 1.5), (1.5, 64, .5), (2, 67, 1), (3, 69, 1)],   # 1  C
    [(0, 67, 2), (2, 62, 1), (3, 64, 1)],                    # 2  G
    [(0, 72, 1.5), (1.5, 71, .5), (2, 69, 1), (3, 64, 1)],   # 3  Am
    [(0, 67, 3)],                                            # 4  Em（最后一拍空）
    [(0, 69, 1.5), (1.5, 67, .5), (2, 65, 1), (3, 69, 1)],   # 5  F
    [(0, 67, 1.5), (1.5, 64, .5), (2, 60, 1), (3, 64, 1)],   # 6  C
    [(0, 62, 1), (1, 65, 1), (2, 69, 1), (3, 72, 1)],        # 7  F
    [(0, 71, 2), (2, 74, 1), (3, 71, 1)],                    # 8  G
    [(0, 67, 1.5), (1.5, 64, .5), (2, 67, 1), (3, 69, 1)],   # 9  C
    [(0, 67, 2), (2, 62, 1), (3, 64, 1)],                    # 10 G
    [(0, 72, 1.5), (1.5, 71, .5), (2, 69, 1), (3, 64, 1)],   # 11 Am
    [(0, 67, 2), (2, 64, 1), (3, 67, 1)],                    # 12 Em
    [(0, 69, 1), (1, 72, 1), (2, 69, 1), (3, 65, 1)],        # 13 F
    [(0, 67, 1.5), (1.5, 64, .5), (2, 64, 1), (3, 62, 1)],   # 14 C
    [(0, 62, 1), (1, 64, 1), (2, 67, 1), (3, 62, 1)],        # 15 G
    [(0, 60, 4)],                                            # 16 C
]

MEL_VEL, CHORD_VEL, BASS_VEL = 100, 62, 78


def notes_in_beats():
    """→ [(起拍, 时值拍, 音高, 力度, 声部)]，按起拍排序。和弦每小节打两下（第 1、3 拍）。"""
    out = []
    for bar in range(BARS):
        b0 = bar * BEATS_PER_BAR
        for t, p, d in MELODY[bar]:
            out.append((b0 + t, d, p, MEL_VEL, "melody"))
        bass, triad = VOICING[CHORDS[bar]]
        last = bar == BARS - 1
        out.append((b0, 4, bass, BASS_VEL, "bass"))
        for hit in ([0] if last else [0, 2]):
            for p in triad:
                out.append((b0 + hit, 4 if last else 2, p, CHORD_VEL, "chord"))
    return sorted(out)


def notes_in_seconds():
    """→ [(起点秒, 时值秒, 音高, 力度)]。拍 → 秒的唯一换算点。"""
    spb = 60.0 / BPM
    return [(t * spb, d * spb, p, v) for t, d, p, v, _ in notes_in_beats()]


def duration_seconds():
    return BARS * BEATS_PER_BAR * 60.0 / BPM


def write_mid(path):
    """同一份音符写成 .mid —— 可以拖进 FL 核对，和 WAV 出自同一份数据。"""
    import mido

    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.Message("program_change", program=0, channel=0, time=0))
    events = []
    for t, d, p, v, _ in notes_in_beats():
        events.append((round(t * tpb), 1, p, v))         # 1 = 按下
        events.append((round((t + d) * tpb), 0, p, 0))   # 0 = 松开；同一刻先松后按
    events.sort()
    now = 0
    for tick, on, p, v in events:
        track.append(mido.Message("note_on" if on else "note_off", note=p,
                                  velocity=v, channel=0, time=tick - now))
        now = tick
    mid.save(path)
