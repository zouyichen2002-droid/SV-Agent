# -*- coding: utf-8 -*-
"""M1-03：按拼音把两串歌词对齐（全局对齐，Needleman–Wunsch），能处理字多音少 / 字少音多（漂移）。

用在两处：
1. 创作者给的歌词 ↔ 终稿唱的（看两者本来就差在哪，「改对」以谁为准要先弄清）
2. 创作者给的歌词 ↔ 扒谱每个音的听写拼音（给每个音换上歌词里的字；多出来的音、没地方放的字都标出来）

打分：拼音一样 +3；近似（前后鼻音 in/ing、en/eng、an/ang，平翘舌 z/zh、c/ch、s/sh，n/l）+1；不一样 −1；
一边空着（漂移）−2 —— 空着比换字贵，字数一样时它宁可逐字换，不会乱插空；字数不一样时空位落在最像的地方，不会摊开。

自检（不过就不用）：完全一样 → 全「一样」；少一个 / 多一个 → 空位正好在那一个；lin↔ling → 「近似」；
中间连少 5 个字 → 5 个空位都落在那一段。
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")
MATCH, NEAR, DIFF, GAP = 3, 1, -1, -2


def _norm(p: str) -> str:
    p = p.lower().strip()
    for a in ("zh", "ch", "sh"):
        if p.startswith(a):
            p = a[0] + p[2:]
    if p.startswith("l"):
        p = "n" + p[1:]
    if p.endswith("ng") and len(p) > 2:
        p = p[:-1]
    return p


def kind(a: str, b: str) -> str:
    if a == b:
        return "一样"
    return "近似" if _norm(a) == _norm(b) else "不一样"


SLOT_FILL, SLOT_FILL_SHORT, SLOT_KEEP, SLOT_MIN_SEC = 1, -1, 0, 0.15


def align(A: list[str], B: list[str], b_dur: list[float] | None = None) -> list[tuple[int | None, int | None, str]]:
    """→ [(A 的下标或 None, B 的下标或 None, 一样 / 近似 / 不一样 / 补空位 / 只在A / 只在B)]，按顺序。

    B 里标成「-」的是**空位**（这个音没配上字）：给了 b_dur（每个 B 的时长，秒）时 ——
    放一个 A 的字进去 +1（太短的碎音 < 0.15 秒 −1），空位一直空着 0（拖音本来就可以没字）。"""
    n, m = len(A), len(B)
    slot = [b == "-" for b in B] if b_dur is not None else [False] * m
    sc = {"一样": MATCH, "近似": NEAR, "不一样": DIFF}

    def pair(i: int, j: int) -> tuple[int, str]:
        if slot[j]:
            return (SLOT_FILL if b_dur[j] >= SLOT_MIN_SEC else SLOT_FILL_SHORT), "补空位"
        k = kind(A[i], B[j])
        return sc[k], k
    gap_b = [SLOT_KEEP if slot[j] else GAP for j in range(m)]
    S = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0] = i * GAP
    for j in range(1, m + 1):
        S[0][j] = S[0][j - 1] + gap_b[j - 1]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            S[i][j] = max(S[i - 1][j - 1] + pair(i - 1, j - 1)[0], S[i - 1][j] + GAP, S[i][j - 1] + gap_b[j - 1])
    out, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and S[i][j] == S[i - 1][j - 1] + pair(i - 1, j - 1)[0]:
            out.append((i - 1, j - 1, pair(i - 1, j - 1)[1]))
            i, j = i - 1, j - 1
        elif i > 0 and S[i][j] == S[i - 1][j] + GAP:
            out.append((i - 1, None, "只在A"))
            i -= 1
        else:
            out.append((None, j - 1, "只在B"))
            j -= 1
    return out[::-1]


def selftest() -> list[str]:
    fails = []
    a = "chun tian lai le hua kai man yuan xiao he liu shui".split()
    if any(k != "一样" for _, _, k in align(a, a)):
        fails.append("完全一样却有不一样的")
    b = a[:4] + a[5:]
    ops = align(a, b)
    if [x for x in ops if x[2] == "只在A"] != [(4, None, "只在A")]:
        fails.append(f"少一个：{[x for x in ops if x[2] != '一样']}")
    c = a[:6] + ["la"] + a[6:]
    if [x[1] for x in align(a, c) if x[2] == "只在B"] != [6]:
        fails.append("多一个：空位不在第 7 个")
    if kind("lin", "ling") != "近似" or kind("zhi", "zi") != "近似" or kind("lin", "ni") != "不一样":
        fails.append("近似判错")
    long_a = a * 3
    long_b = long_a[:12] + long_a[17:]
    gaps = [x[0] for x in align(long_a, long_b) if x[2] == "只在A"]
    if len(gaps) != 5 or max(gaps) - min(gaps) > 6:
        fails.append(f"中间连少 5 个：空位 {gaps}")
    # 空位：三个字配成「字1 字1 -」（真实遇到过的形状）→ 一样 / 换字 / 补空位
    ops = align(["de", "xiao", "he"], ["de", "de", "-"], [0.66, 0.34, 0.35])
    if [k for *_, k in ops] != ["一样", "不一样", "补空位"]:
        fails.append(f"字1 字1 -：{ops}")
    # 两个字配成「字1 -(0.05 秒碎音) -(0.81 秒)」→ 第二个字放进长的那个，碎音留「-」
    ops = align(["liu", "shui"], ["liu", "-", "-"], [0.47, 0.05, 0.81])
    if [(i, j, k) for i, j, k in ops] != [(0, 0, "一样"), (None, 1, "只在B"), (1, 2, "补空位")]:
        fails.append(f"碎音：{ops}")
    # 空位旁边没有多出来的字 → 空位留着（真拖音）
    ops = align(["hua", "kai"], ["hua", "-", "kai"], [0.4, 0.5, 0.4])
    if [k for *_, k in ops] != ["一样", "只在B", "一样"]:
        fails.append(f"真拖音被填了：{ops}")
    return fails


if __name__ == "__main__":
    f = selftest()
    print("自检：", "通过（一样 / 少一个 / 多一个 / 近似 / 连少 5 个 / 空位三种）" if not f else f)
