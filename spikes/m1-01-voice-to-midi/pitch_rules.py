# -*- coding: utf-8 -*-
"""拿原唱的音高（pyin）改扒出来的音（10-08《那些我恐惧至极的事》创作者手改 r03 之后，他说「都加上」）。

1. octave_up：扒出来的音比原唱低一个八度 → 往上改（只往上）。
   这首副歌里同一组长音三遍 GAME 都扒成 D4、原唱是 D5：往上改的 7 处 7 处对（6 处和他改的一样，1 处八度对、差半音）；
   往下改的 3 处全错（都在两位歌手叠唱那段，pyin 抓到的是另一个低的声音）→ 只往上。
   《公主》：10 处里 8 处和他的定稿一样、2 处他删了或改成了别的、0 处改错；《刽子手》0 处触发。
   紧跟着的拖音（「-」、和它原来同音高、首尾相接）一起改。
2. split_tail：长音的结尾滑到另一个音、稳在那里 → 从变化的那一刻拆开，后一段写拖音「-」、音高用结尾那个音。
   他在这首里有 9 处这样拆（「er」G4 后面接 F4 那种）：规矩拆的 5 处和他的一样、0 处错、漏 3 处；《公主》错 1 处、漏 1 处。
   条件：音 ≥ 0.4 秒、整个音有声 ≥ 60%；结尾 0.18 秒稳（标准差 < 0.6 半音），而且离这个音的前半段、离这个音本身都 ≥ 1.5 半音
   （只比前半段会把「开头往上兜、结尾回到本音」的也拆了 —— 第一版这样错了一半）；拆出来两段都 ≥ 0.15 秒。

pyin 整首算一次（16 kHz、10 ms 一帧），两条规矩共用。notes：[(起, 长, 音分, 字)]。

接进 song_round 后（10-08）十首回归：念唱和别的音不变；往上改八度另外 4 处（《夜舞》2 处和照钢琴谱改的一样）；
音尾拆音另外 6 处，有对照的 3 处里 2 处音高对、但拆出来的后一段其实是下一个字（前面的字已经错位一格），1 处拆错 —— 不稳，先留着、看创作者听了怎么说。
《影子小姐》（10-09）：往上改八度 1 处（和 pyin 一致，他没改回去），音尾拆音 0 处。
"""
from __future__ import annotations

import numpy as np

UP_MIN_VOICED, UP_TOL = 0.6, 0.8                     # 规矩 1：中段有声 ≥ 60%、和高一个八度差 ≤ 0.8 半音
TAIL_MIN_LEN, TAIL_SEC, TAIL_JUMP, TAIL_STD, TAIL_MIN_PART = 0.4, 0.18, 1.5, 0.6, 0.15
_cache: dict[str, tuple] = {}
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"     # noqa: E731
_N = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
name = lambda p: f"{_N[p % 12]}{p // 12 - 1}"         # noqa: E731


def track(vocal_wav: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """→ (每帧时间, 每帧音高（MIDI，没声是 nan）, 每帧有没有声)。同一个文件只算一次。"""
    if vocal_wav not in _cache:
        import librosa
        y, sr = librosa.load(vocal_wav, sr=16000, mono=True)
        f0, voiced, _ = librosa.pyin(y, fmin=70, fmax=1200, sr=sr, frame_length=1024, hop_length=160)
        midi = librosa.hz_to_midi(f0)
        _cache[vocal_wav] = (np.arange(len(midi)) * 160 / sr, midi, voiced & ~np.isnan(midi))
    return _cache[vocal_wav]


def octave_up(notes: list[tuple], trk: tuple) -> tuple[list[tuple], list[str]]:
    T, mid, ok = trk
    order = sorted(range(len(notes)), key=lambda k: notes[k][0])
    out, log, moved = list(notes), [], set()
    for idx, k in enumerate(order):
        s, d, c, ly = notes[k]
        if ly in ("-", ""):
            continue
        m = (T >= s + 0.15 * d) & (T <= s + 0.85 * d)
        v = mid[m & ok]
        if len(v) < 3 or len(v) / max(1, m.sum()) < UP_MIN_VOICED:
            continue
        p = int(round(c / 100))
        if abs(float(np.median(v)) - p - 12) > UP_TOL:
            continue
        out[k] = (s, d, c + 1200.0, ly)
        moved.add(k)
        tail = []
        end = s + d
        for j in order[idx + 1:]:                       # 紧跟着的拖音一起往上
            s2, d2, c2, ly2 = notes[j]
            if ly2 not in ("-", "") or abs(s2 - end) > 0.03 or int(round(c2 / 100)) != p:
                break
            out[j] = (s2, d2, c2 + 1200.0, ly2)
            tail.append(j)
            end = s2 + d2
        log.append(f"{fmt(s)}「{ly}」{name(p)} → {name(p + 12)}（原唱中段在 {float(np.median(v)):.1f}）"
                   + (f"，后面 {len(tail)} 个拖音一起" if tail else ""))
    return out, log


def split_tail(notes: list[tuple], trk: tuple) -> tuple[list[tuple], list[str]]:
    T, mid, ok = trk
    out, log = [], []
    for s, d, c, ly in sorted(notes):
        if ly in ("-", "") or d < TAIL_MIN_LEN:
            out.append((s, d, c, ly))
            continue
        m = (T >= s) & (T < s + d)
        seg, sok = mid[m], ok[m]
        if len(seg) == 0 or sok.mean() < 0.6:
            out.append((s, d, c, ly))
            continue
        half = len(seg) // 2
        head = seg[:half][sok[:half]]
        tn = int(round(TAIL_SEC * 100))
        tail = seg[-tn:][sok[-tn:]]
        p = c / 100
        if len(head) < 5 or len(tail) < 0.6 * tn:
            out.append((s, d, c, ly))
            continue
        h, tl = float(np.median(head)), float(np.median(tail))
        if abs(tl - h) < TAIL_JUMP or abs(tl - p) < TAIL_JUMP or float(np.std(tail)) >= TAIL_STD:
            out.append((s, d, c, ly))
            continue
        # 从后往前找：结尾那个音一直稳着的那段从哪一帧开始
        ts = T[m]
        cut = len(seg) - 1
        while cut > 0 and (not sok[cut - 1] or abs(seg[cut - 1] - tl) <= 0.7):
            cut -= 1
        t = float(ts[cut])
        if t - s < TAIL_MIN_PART or s + d - t < TAIL_MIN_PART:
            out.append((s, d, c, ly))
            continue
        q = int(round(tl))
        out += [(s, t - s, c, ly), (t, s + d - t, float(q * 100), "-")]
        log.append(f"{fmt(s)}「{ly}」{name(int(round(p)))} 结尾滑到 {name(q)} → 在 {fmt(t)} 拆开，后一段写「-」（{s + d - t:.2f} 秒）")
    return out, log


def selftest() -> list[str]:
    """造一段音高轨：① 原唱高一个八度的音 → 往上、后面的拖音跟着；低一个八度的不往下；② 结尾滑走的拆开，开头兜一下的不拆。"""
    fails = []
    T = np.arange(0, 6, 0.01)
    mid = np.full(len(T), np.nan)
    ok = np.zeros(len(T), bool)

    def sing(a, b, p):
        m = (T >= a) & (T < b)
        mid[m], ok[m] = p, True
    sing(0.0, 0.5, 74.0)          # 扒成 62、原唱 74 → 往上
    sing(0.5, 0.8, 74.0)          # 紧跟的拖音
    sing(1.0, 1.5, 55.0)          # 扒成 67、原唱 55（低一个八度）→ 不往下
    sing(2.0, 2.4, 67.0); sing(2.4, 2.8, 65.0)       # 「er」G4 后面滑到 F4 → 拆
    sing(3.0, 3.2, 63.0); sing(3.2, 3.8, 67.0)       # 开头从 D#4 兜上来、结尾回到 G4 → 不拆
    trk = (T, mid, ok)
    notes = [(0.0, 0.5, 6200.0, "a"), (0.5, 0.3, 6200.0, "-"), (1.0, 0.5, 6700.0, "b"), (2.0, 0.8, 6700.0, "c"), (3.0, 0.8, 6700.0, "d")]
    up, log = octave_up(notes, trk)
    if [round(n[2]) for n in up] != [7400, 7400, 6700, 6700, 6700] or len(log) != 1:
        fails.append(f"往上改八度不对：{[round(n[2]) for n in up]} {log}")
    sp, log = split_tail(notes, trk)
    got = [(round(n[0], 2), round(n[2]), n[3]) for n in sp if 1.9 < n[0] < 4]
    if got != [(2.0, 6700, "c"), (2.4, 6500, "-"), (3.0, 6700, "d")] or len(log) != 1:
        fails.append(f"音尾拆音不对：{got} {log}")
    return fails


if __name__ == "__main__":
    print(selftest())
