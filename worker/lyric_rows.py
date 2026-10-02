# -*- coding: utf-8 -*-
r"""歌词的「单位唱的时间」和「一句拆成几行」（v3 视频，2026-10-02）：成片的特效字幕（lyric_fx.py）和剪映草稿（jianying_draft.py）共用。
只用 Python 自带的东西（video 环境里没有 fontTools，所以从 lyric_fx.py 里拿出来单放）。
"""
from __future__ import annotations


def unit_times(units: list[dict]) -> list[tuple[float, float]]:
    """每个单位什么时候唱：没时间的跟下一个有时间的一起亮（时长 0）；后面都没有就跟前一个的结尾。"""
    t: list = [(u["开始"], u["结束"]) if u["开始"] is not None else None for u in units]
    nxt = None
    for i in range(len(t) - 1, -1, -1):
        if t[i] is None:
            t[i] = (nxt, nxt) if nxt is not None else None
        else:
            nxt = t[i][0]
    prev = 0.0
    for i in range(len(t)):
        if t[i] is None:
            t[i] = (prev, prev)
        prev = t[i][1]
    return t


def phrase_rows(ln: dict, times: list[tuple[float, float]], lang: str) -> list[list[int]]:
    """一句拆成几行（参考里「一直到 / 雨幕 漫上她的 / 白裙裾」）：在唱的停顿处断 —— 原文的空格、两个字之间空了 0.18 秒以上、前一个字拖了 0.5 秒以上。
    然后：只有 1 个单位的行并到停顿小的那一边；超过 6 个的行从里面最大的停顿断开（两段都至少 2 个）；
    行数最多 max(3, 单位数 ÷ 5 取上整)，多了就并停顿最小、并完不超过 6 个的相邻两行（10-02 第一版先断长行再并单字行，并完又超长了）。"""
    units = ln["单位"]
    n = len(units)
    if n <= 1:
        return [list(range(n))]
    brk = set()
    if lang != "en":                                  # 英文词之间本来就是空格，不算
        lens = [len(u["文字"].replace(" ", "")) for u in units]
        ends = [sum(lens[:i + 1]) for i in range(n)]  # 第 i 个单位在原文（去掉空格）里到第几个字为止
        pos = 0
        for ch in ln["文字"]:
            if ch.isspace():
                if pos in ends[:-1]:
                    brk.add(ends.index(pos))
                continue
            pos += 1
    gap = [times[i + 1][0] - times[i][1] for i in range(n - 1)]
    for i in range(n - 1):
        if gap[i] > 0.18 or times[i][1] - times[i][0] > 0.5:
            brk.add(i)
    rows, cur = [], []
    for i in range(n):
        cur.append(i)
        if i in brk:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    g = lambda r: gap[r[-1]] if r[-1] < n - 1 else 9e9       # 这一行后面的停顿
    while len(rows) > 1 and min(len(r) for r in rows) == 1:   # 1 个单位的行：并到停顿小的那一边
        i = next(m for m, r in enumerate(rows) if len(r) == 1)
        left = g(rows[i - 1]) if i > 0 else 9e9
        right = g(rows[i]) if i + 1 < len(rows) else 9e9
        if left <= right:
            rows[i - 1] += rows.pop(i)
        else:
            single = rows.pop(i)                      # 拿掉以后，后一行就在 i 这个位置
            rows[i] = single + rows[i]
    out = []
    stack = list(rows)
    while stack:                                       # 超过 6 个：从最大的停顿断开，两段都至少 2 个
        r = stack.pop(0)
        if len(r) <= 6:
            out.append(r)
            continue
        j = max(range(2, len(r) - 1), key=lambda m: gap[r[m - 1]])
        stack[:0] = [r[:j], r[j:]]
    rows = out
    cap = max(3, -(-n // 5))                           # 按每行 5 个算行数上限（17 个字就允许 4 行；限 3 行时 17 个字并出过 8 个一行）
    while len(rows) > cap:                             # 行太多：并停顿最小、并完不超过 6 个的相邻两行（都超就并停顿最小的）
        pairs = [m for m in range(len(rows) - 1) if len(rows[m]) + len(rows[m + 1]) <= 6] or list(range(len(rows) - 1))
        i = min(pairs, key=lambda m: g(rows[m]))
        rows[i] += rows.pop(i + 1)
    return rows
