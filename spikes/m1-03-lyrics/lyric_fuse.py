# -*- coding: utf-8 -*-
"""歌词落位 v2（10-06《公主》，创作者「midi 识别可以，但是歌词落位有很大问题」）：音一个不动，字按时间 + 听到的拼音一起放。

原来（lyric_align.align）：整首歌词的拼音和「只靠听写」扒出来的拼音做一次全局对齐。听写在有效果器、唱得快的地方整段听错，
歌词又大段重复（副歌里有两个短句各唱四遍）→ 对齐整段滑一格、整行对不上被拿掉
（《公主》第 23、24、34 行明明唱了，被当成没唱；0:51 那句的后半句被跳过、1:58 那句的最后两个字滑到 2:07）。

这里多一个裁判：Vocal2Midi「给原歌词」模式（HubertFA 按字强制对齐）给每个字一个时间 —— 它重切的音不用（09-29 创作者：音准优先），只拿时间：
1. 锚点：歌词逐字和强制对齐留下的字做最长公共子序列，对上的字拿它的起音时间；它漏掉的字（会漏整句）按前后锚点插值
2. 歌词逐字和音做单调对齐（DP）：一个字配一个音的代价 = 时间差（锚点的字看得重、插值的字看得轻）+ 听到的拼音不一样再加一点；
   字没地方放、音不配字各有代价
3. 结果写成 lyric_align.align 一样的 (歌词第几个字, 第几个音, 类别)，后面的补空位 / 拆音 / 拖音（repair_lyrics.repair）照旧
4. 整行不放（09-30 规矩 1）改成看这一行有多少字「放上了、而且有凭据」（是锚点，或听到的就是这个字 / 近似音）

《刽子手》（创作者 09-30 手改过的那版当裁判：他那里带字的 273 个音，同一时间同一个字）：原来 240、这里 241；
《公主》：原来 8 行整行不放（其中 3 行明明唱了）、一串串「-」，这里那 3 行都放上了。参数是在这两首上挑的（《刽子手》在一大片参数里都是 237–241，不挑也差不多）。

    notes：[(起, 长, 音分, 拼音)]（排好序）；aligned：给原歌词那版的音（同样的格式）；pys：歌词逐字拼音
"""
from __future__ import annotations

import lyric_align as A

W_T, W_T_INTERP = 4.0, 0.5            # 每差 1 秒的代价：锚点的字 / 插值的字
MISMATCH, MISMATCH_INTERP = 0.6, 0.8  # 听到的拼音和这个字不一样（近似音算一半）
SKIP_CHAR, SKIP_NOTE = 1.5, 0.25      # 字没地方放 / 音不配字（写成拖音）
T_MAX, T_MAX_INTERP = 0.6, 3.0        # 离得比这远就不配
INTERP_STEP = 0.3                     # 头尾没锚点的字：一个字按 0.3 秒往外推


def _lcs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    out, i, j = [], 0, 0
    while i < n and j < m:
        if a[i] == b[j]:
            out.append((i, j))
            i, j = i + 1, j + 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def anchors(pys: list[str], aligned: list[tuple]) -> tuple[list[float | None], list[bool]]:
    """→ (每个字的时间, 是不是锚点)。没有一个锚点时全是 None。"""
    al = [(n[0], n[3]) for n in aligned if n[3] not in ("-", "", "SP", "AP", "+")]
    t: list[float | None] = [None] * len(pys)
    anch = [False] * len(pys)
    for i, j in _lcs(pys, [c for _, c in al]):
        t[i], anch[i] = al[j][0], True
    idx = [i for i in range(len(pys)) if anch[i]]
    for i in range(len(pys)):
        if anch[i] or not idx:
            continue
        lo = max((k for k in idx if k < i), default=None)
        hi = min((k for k in idx if k > i), default=None)
        if lo is not None and hi is not None:
            t[i] = t[lo] + (t[hi] - t[lo]) * (i - lo) / (hi - lo)
        elif lo is not None:
            t[i] = t[lo] + INTERP_STEP * (i - lo)
        else:
            t[i] = t[hi] - INTERP_STEP * (hi - i)
    return t, anch


SPLIT_TIME_MAX_GAP = 2.0              # 不是锚点的字：前后两个锚点相隔不超过这么久，插出来的时间才拿去切音


def split_times(t: list, anch: list[bool]) -> list:
    """给 repair_lyrics.repair(times=) 用：锚点的字用它的时间；不是锚点的，前后锚点挨得近（≤ SPLIT_TIME_MAX_GAP）才用插出来的时间，否则 None。"""
    idx = [i for i, a in enumerate(anch) if a]
    out = []
    for i, x in enumerate(t):
        if anch[i]:
            out.append(x)
            continue
        lo = max((k for k in idx if k < i), default=None)
        hi = min((k for k in idx if k > i), default=None)
        out.append(x if lo is not None and hi is not None and t[hi] - t[lo] <= SPLIT_TIME_MAX_GAP else None)
    return out


def fuse_ops(pys: list[str], notes: list[tuple], aligned: list[tuple]) -> tuple[list[tuple], list[bool]]:
    """→ (ops，和 lyric_align.align 一样：(i 歌词, j 音, 类别)，按顺序；每个字是不是锚点)。"""
    t, anch = anchors(pys, aligned)
    m, n = len(pys), len(notes)
    INF = float("inf")
    D = [[INF] * (n + 1) for _ in range(m + 1)]
    B: list[list[str | None]] = [[None] * (n + 1) for _ in range(m + 1)]
    D[0][0] = 0.0
    for j in range(1, n + 1):
        D[0][j], B[0][j] = D[0][j - 1] + SKIP_NOTE, "n"
    for i in range(1, m + 1):
        D[i][0], B[i][0] = D[i - 1][0] + SKIP_CHAR, "c"
        ti = t[i - 1]
        wt, mm, tmax = (W_T, MISMATCH, T_MAX) if anch[i - 1] else (W_T_INTERP, MISMATCH_INTERP, T_MAX_INTERP)
        for j in range(1, n + 1):
            best, how = D[i - 1][j] + SKIP_CHAR, "c"
            if D[i][j - 1] + SKIP_NOTE < best:
                best, how = D[i][j - 1] + SKIP_NOTE, "n"
            if ti is not None and abs(ti - notes[j - 1][0]) <= tmax:
                k = A.kind(pys[i - 1], notes[j - 1][3])
                c = D[i - 1][j - 1] + wt * abs(ti - notes[j - 1][0]) + (0 if k == "一样" else mm / 2 if k == "近似" else mm)
                if c < best:
                    best, how = c, "m"
            D[i][j], B[i][j] = best, how
    ops: list[tuple] = []
    i, j = m, n
    while i > 0 or j > 0:
        h = B[i][j]
        if h == "m":
            ly = notes[j - 1][3]
            ops.append((i - 1, j - 1, "补空位" if ly in ("-", "") else A.kind(pys[i - 1], ly)))
            i, j = i - 1, j - 1
        elif h == "c":
            ops.append((i - 1, None, "只在A"))
            i -= 1
        else:
            ops.append((None, j - 1, "只在B"))
            j -= 1
    return ops[::-1], anch


def line_rates(lines: list[str], ops: list[tuple], anch: list[bool]) -> list[float]:
    """每行有多少字放上了、而且有凭据（强制对齐的锚点，或听写听到的就是这个字 / 近似音）。"""
    owner = [li for li, ln in enumerate(lines) for _ in ln]
    good = [0] * len(lines)
    for i, j, k in ops:
        if i is not None and j is not None and (anch[i] or k in ("一样", "近似")):
            good[owner[i]] += 1
    return [good[li] / max(1, len(ln)) for li, ln in enumerate(lines)]


def selftest() -> list[str]:
    """造一段：音 = 歌词逐字（听写有一段整段听错）、强制对齐漏掉中间一句 → 字都该回到自己的音上。"""
    fails = []
    pys = ["a", "b", "c", "d", "e", "f", "g", "h"]
    notes = [(k * 0.5, 0.4, 6000.0, ly) for k, ly in enumerate(["a", "b", "x", "y", "z", "f", "g", "h"])]   # c d e 听错
    aligned = [(k * 0.5 + 0.03, 0.4, 6000.0, ly) for k, ly in enumerate(pys) if ly not in ("d", "e")]       # 漏了 d e
    ops, anch = fuse_ops(pys, notes, aligned)
    got = {j: i for i, j, _ in ops if i is not None and j is not None}
    if got != {k: k for k in range(8)}:
        fails.append(f"听错一段 + 强制对齐漏字：该一字一音，实际 {got}")
    if anch != [True, True, True, False, False, True, True, True]:
        fails.append(f"锚点不对：{anch}")
    rates = line_rates(["abcd", "efgh"], ops, anch)
    if rates != [0.75, 0.75]:
        fails.append(f"整行凭据比例不对：{rates}")
    # 一句没唱（没有音、强制对齐也没给时间）→ 不该硬塞到别的音上
    ops, anch = fuse_ops(pys + ["p", "q", "r"], notes, aligned)
    placed = {i for i, j, _ in ops if i is not None and j is not None}
    if placed & {8, 9, 10}:
        fails.append(f"没唱的字被塞到音上：{sorted(placed & {8, 9, 10})}")
    return fails


if __name__ == "__main__":
    print(selftest())
