# -*- coding: utf-8 -*-
"""测这首歌的调，写进工程「调式音阶」（SynthV 钢琴卷帘上的音阶参考线，只影响显示，不动音）。

创作者 10-07 改《公主》r02 时自己把调式音阶设成了 G 和声小调（模板里原来是 E 自然小调）→「两个都加上」：生成工程时自动设。
两个裁判一起投票：旋律（扒出来的音，按时长）和伴奏（整首 chroma）各自对 24 个调的轮廓（Krumhansl）算相关，加起来最高的那个。
小调再分自然 / 和声：导音（升 7 级）比降 7 级多 → 和声小调。
《公主》：旋律 G 小调 0.58、伴奏 D 大调 / G 小调并列 0.68 → 合起来 G 小调；F# 比 F 多 → 和声小调（和创作者设的一样）。
整首只设一个：中途转调（《公主》最后一段副歌升到 A 小调）不另设。

SynthV 工程里见过的写法：{"type": "Major" | "NaturalMinor" | "HarmonicMinor", "root": "C" | "E" | "G"}；
带升号的根音照钢琴卷帘的写法写成 "C#"、"F#"（还没在 SynthV 里打开核过）。
"""
from __future__ import annotations

import numpy as np

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def melody_hist(notes: list[tuple]) -> np.ndarray:
    """notes：[(起, 长, 音分, 字)] → 12 个音级各唱了多久。"""
    h = np.zeros(12)
    for _, d, c, _ in notes:
        h[int(round(c / 100)) % 12] += max(d, 0.0)
    return h


def accomp_hist(wav: str) -> np.ndarray:
    import librosa
    y, sr = librosa.load(wav, sr=22050, mono=True)
    return librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=2048).sum(axis=1)


def _corr(h: np.ndarray, prof: np.ndarray) -> float:
    if h.sum() <= 0 or np.std(h) == 0:
        return 0.0
    return float(np.corrcoef(h, prof)[0, 1])


def detect(hists: list[np.ndarray]) -> dict:
    """→ {"type", "root", "得分", "说明"}；hists 是各个裁判的音级分布（旋律、伴奏），每个调把各裁判的相关加起来比。"""
    best = None
    for k in range(12):
        for mode, prof in (("Major", MAJ), ("Minor", MIN)):
            s = sum(_corr(h, np.roll(prof, k)) for h in hists)
            if best is None or s > best[0]:
                best = (s, k, mode)
    s, k, mode = best
    if mode == "Major":
        typ, cn = "Major", "大调"
    else:
        tot = sum(h / h.sum() for h in hists if h.sum() > 0)
        raised, flat = tot[(k + 11) % 12], tot[(k + 10) % 12]
        typ, cn = ("HarmonicMinor", "和声小调") if raised > flat else ("NaturalMinor", "自然小调")
    return {"type": typ, "root": NAMES[k], "得分": round(s, 2), "说明": f"{NAMES[k]} {cn}"}


def selftest() -> list[str]:
    fails = []
    c_major = np.zeros(12)
    for pc, w in ((0, 5), (2, 3), (4, 4), (5, 3), (7, 5), (9, 3), (11, 2)):
        c_major[pc] = w
    if (r := detect([c_major]))["type"] != "Major" or r["root"] != "C":
        fails.append(f"C 大调认成了 {r}")
    g_harm = np.zeros(12)                       # G 和声小调：G A A# C D D# F#，F# 比 F 多
    for pc, w in ((7, 6), (9, 3), (10, 4), (0, 3), (2, 5), (3, 3), (6, 3), (5, 0.5)):
        g_harm[pc] = w
    if (r := detect([g_harm, g_harm]))["type"] != "HarmonicMinor" or r["root"] != "G":
        fails.append(f"G 和声小调认成了 {r}")
    g_nat = g_harm.copy()
    g_nat[6], g_nat[5] = 0.5, 3
    if (r := detect([g_nat]))["type"] != "NaturalMinor" or r["root"] != "G":
        fails.append(f"G 自然小调认成了 {r}")
    return fails


if __name__ == "__main__":
    print(selftest())
