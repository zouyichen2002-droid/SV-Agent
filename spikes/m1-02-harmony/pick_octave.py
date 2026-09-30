# -*- coding: utf-8 -*-
"""r05：Suno 上下两个八度一起唱的地方，GAME 每个音只能挑一个八度、挑得忽上忽下 —— 按旋律的连贯性替它挑。

创作者 09-29 听 r02：「俯瞰中，华灯上」主唱的 fu 对了、kanzhong 错了，叠唱的 fu 错了、kanzhong 对了，
两条一起放「给我一种听感好的错觉」—— 问：结合和声的方法，但怎么让你明白哪个是对的？

**第三版（交的 r05）**：
1. **录音里确认两个八度一起唱的句子（r02 的叠唱检测），整句取上面那个八度** —— 高声部优势：两个八度一起唱，人耳听到的旋律
   一般是上面那个。对得上创作者的判断：1:12–1:16 他说上面对、1:26–1:32 终稿在上；1:56–2:12 终稿主唱在下、上面那条是他的「和声1」
2. 剩下**单独掉下去的音**（录音里没找到另一个八度，但前后都在另一个音区），再按旋律连贯性拉回来：整首歌排成一串找总代价最小的路
   （Viterbi）；相邻两个音跳得越大代价越高（八度跳最贵），隔着休止符便宜些；换一个没有录音证据的音代价 5 —— 只有明显的才换
3. 其余的音一个都不动；音区限制在 GAME 扒到的音域上下 2 个半音以内

前两稿（没交，挪进 rounds\\r05_弃用_*）：
- 第一稿逐音挑（Viterbi，有证据的换 1.5、没证据的换 5，外加附近音区）：换的少的那条路赢 —— 「俯瞰中」GAME 是 G4 A3 B3，
  它把 G4 拉下去凑成 G3（只换一个）而不是把 A3 B3 抬上去；1:27–1:31 那 5 个倒是对了
- 第二稿按句挑（整句取上 / 取下，比和前后接得顺不顺）：副歌前面主歌结尾在 G3、F#3，「接得顺」就把副歌也拉下去了 ——
  主歌转副歌本来就换音区；响度也试了，和创作者的选择对不上（1:12 那里下面反而更响）
**只改八度**：起止时间、歌词一律不动（音准优先 —— 修歌词只改字、不动音；这里是修音，只动八度）。

自检（不过就不写）：造的例子 —— 录音有两个八度、GAME 忽上忽下 → 连成一条；真的大跳（非八度）不动；
中间一个音掉八度、没有录音证据 → 也拉回来；平滑的旋律一个都不动；音域外的不去。
打分：对终稿主唱，八度错几个、F1；每个换了的音都列出来（时间、字、从哪到哪、有没有录音证据）。

    python pick_octave.py <底子音符.json> <版名>
底子默认用 r04（r01 的音 + 按创作者歌词换的字）。工程写在 rounds/<版名>/。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
import compare_notes as C  # noqa: E402
import make_r02 as M  # noqa: E402
import make_round_svp as R  # noqa: E402
import octave_double as O  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
EV_COST, NOEV_COST, RANGE_SLACK = 1.5, 6.0, 2     # 没证据的换一个 6：隔着换气的一次八度跳（≤ 10 × 0.5）不够把两个音一起带走
REG_W, REG_WIN, REG_WIN_WIDE = 0.15, 6.0, 12.0
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"
NAMES = "C C# D D# E F F# G G# A A# B".split()
nm = lambda p: f"{NAMES[p % 12]}{p // 12 - 1}"


def interval_cost(d: int) -> float:
    d = abs(d)
    if d <= 2:
        return 0.0
    if d <= 4:
        return 0.5
    if d <= 5:
        return 1.0
    if d <= 7:
        return 2.0
    if d <= 9:
        return 4.0
    if d <= 11:
        return 7.0
    return 10.0 + 0.5 * (d - 12)


def gap_scale(gap: float) -> float:
    return 1.0 if gap <= 0.5 else (0.5 if gap <= 2.0 else 0.2)


def local_register(notes: list, other: list[int]) -> list[float | None]:
    """每个音附近（前后 6 秒，找不到放宽到 12 秒）只有一个声部的音的中间音高。"""
    import statistics
    ps = [c / 100 for _, _, c, _ in notes]
    out = []
    for k, (s, *_rest) in enumerate(notes):
        reg = None
        for w in (REG_WIN, REG_WIN_WIDE):
            near = [ps[j] for j, n in enumerate(notes) if other[j] == 0 and abs(n[0] - s) <= w]
            if near:
                reg = statistics.median(near)
                break
        out.append(reg)
    return out


def decode(notes: list, other: list[int], lo: int, hi: int) -> tuple[list[int], list[str]]:
    """notes 按时间排好；other[k] = 录音里另一个八度的方向（+12 / −12 / 0）。→ (每个音的新音高, 每个音用的是哪种)"""
    reg = local_register(notes, other)
    cands = []
    for k, (s, d, c, _) in enumerate(notes):
        p = int(round(c / 100))
        pull = (lambda q: REG_W * abs(q - reg[k])) if reg[k] is not None else (lambda q: 0.0)
        opts = [(p, pull(p), "原样")]
        for q in (p + 12, p - 12):
            if lo <= q <= hi:
                ev = other[k] != 0 and q == p + other[k]
                opts.append((q, (EV_COST if ev else NOEV_COST) + pull(q), "有录音证据" if ev else "没有录音证据"))
        cands.append(opts)
    cost = [[o[1] for o in cands[0]]]
    back = [[-1] * len(cands[0])]
    for k in range(1, len(notes)):
        gap = notes[k][0] - (notes[k - 1][0] + notes[k - 1][1])
        g = gap_scale(gap)
        row, brow = [], []
        for q, e, _ in cands[k]:
            best = min(range(len(cands[k - 1])), key=lambda i: cost[-1][i] + g * interval_cost(q - cands[k - 1][i][0]))
            row.append(cost[-1][best] + g * interval_cost(q - cands[k - 1][best][0]) + e)
            brow.append(best)
        cost.append(row)
        back.append(brow)
    i = min(range(len(cost[-1])), key=lambda x: cost[-1][x])
    path = []
    for k in range(len(notes) - 1, -1, -1):
        path.append(cands[k][i])
        i = back[k][i]
    path.reverse()
    return [q for q, _, _ in path], [why for _, _, why in path]


def runs_of(flags: list[bool]) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j + 1 < len(flags) and flags[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def decide_phrases(notes: list, other: list[int], lo: int, hi: int) -> tuple[list[int], list[str]]:
    """第二版（按句）：每一段叠唱只比两个版本 —— 整句取上面那个八度 / 整句取下面那个八度；
    比的是和前后只有一个声部的音接得顺不顺（相邻音跳多大）、句子里自己顺不顺、离附近音区多远。
    只有一个声部的音一个都不动。"""
    ps = [int(round(c / 100)) for _, _, c, _ in notes]
    reg = local_register(notes, other)
    new, why = list(ps), ["原样"] * len(ps)
    for i, j in runs_of([o != 0 for o in other]):
        best = None
        for label, pick in (("整句取上", max), ("整句取下", min)):
            v = [pick(ps[k], ps[k] + other[k]) for k in range(i, j + 1)]
            if any(not (lo <= q <= hi) for q in v):
                continue
            seq = ([new[i - 1]] if i > 0 else []) + v + ([ps[j + 1]] if j + 1 < len(ps) else [])
            idx = ([i - 1] if i > 0 else []) + list(range(i, j + 1)) + ([j + 1] if j + 1 < len(ps) else [])
            cost = sum(gap_scale(notes[b][0] - (notes[a][0] + notes[a][1])) * interval_cost(seq[t + 1] - seq[t])
                       for t, (a, b) in enumerate(zip(idx, idx[1:])))
            cost += sum(REG_W * abs(v[t] - reg[i + t]) for t in range(len(v)) if reg[i + t] is not None)
            if best is None or cost < best[0]:
                best = (cost, label, v)
        if best:
            for t, q in enumerate(best[2]):
                if q != ps[i + t]:
                    new[i + t], why[i + t] = q, best[1]
    return new, why


DIP_MIN, DIP_FIT, DIP_MAXLEN, DIP_GAP = 7, 5, 3, 0.5


def upper_then_fix(notes: list, other: list[int], lo: int, hi: int) -> tuple[list[int], list[str]]:
    """第三版：两个八度一起唱的句子整句取上面那个八度；再把**真正掉下去 / 翘上去的**拉回来 ——
    连续 1–3 个（录音里没另一个八度的）音，前一个和后一个音**都**比它们高（或低）至少 7 个半音、同一句里（间隔 ≤ 0.5 秒），
    挪一个八度后和两边都接得上（差 ≤ 5 个半音）才挪。只有一边不对劲（比如句子边上）的不动 —— 音准优先，没证据不乱改。
    （这一步第一次用整首 Viterbi：会为了接得顺把句子边上的音带走，自检拦下了，改成这条局部规则。）"""
    ps = [int(round(c / 100)) for _, _, c, _ in notes]
    new = [max(ps[k], ps[k] + other[k]) if other[k] else ps[k] for k in range(len(ps))]
    why = ["叠唱整句取上" if other[k] and new[k] != ps[k] else "原样" for k in range(len(ps))]
    free = [other[k] == 0 for k in range(len(ps))]
    gap = lambda a, b: notes[b][0] - (notes[a][0] + notes[a][1])
    k = 1
    while k < len(ps) - 1:
        if not free[k]:
            k += 1
            continue
        done = False
        for L in range(1, DIP_MAXLEN + 1):
            e = k + L - 1
            if e >= len(ps) - 1 or not all(free[k:e + 1]):
                break
            if gap(k - 1, k) > DIP_GAP or gap(e, e + 1) > DIP_GAP or any(gap(t, t + 1) > DIP_GAP for t in range(k, e)):
                break
            run, prev, nxt = new[k:e + 1], new[k - 1], new[e + 1]
            for shift in (12, -12):
                if shift > 0:
                    ok = prev - max(run) >= DIP_MIN and nxt - max(run) >= DIP_MIN
                else:
                    ok = min(run) - prev >= DIP_MIN and min(run) - nxt >= DIP_MIN
                moved = [q + shift for q in run]
                if ok and all(lo <= q <= hi for q in moved) and abs(moved[0] - prev) <= DIP_FIT and abs(moved[-1] - nxt) <= DIP_FIT:
                    for t in range(L):
                        new[k + t], why[k + t] = moved[t], "单独掉下去的，拉回来" if shift > 0 else "单独翘上去的，拉回来"
                    done = True
                    break
            if done:
                k = e + 1
                break
        if not done:
            k += 1
    return new, why


def selftest() -> list[str]:
    fails = []
    mk = lambda ps, step=0.45: [(i * step, 0.4, p * 100.0, "") for i, p in enumerate(ps)]
    # 1. 录音有两个八度、GAME 忽上忽下（G4 A3 B3），后面接着高音区 F#4 G4 → G4 A4 B4
    ns = mk([67, 57, 59, 66, 67])
    got, _ = decode(ns, [-12, 12, 12, 0, 0], 50, 78)
    if got != [67, 69, 71, 66, 67]:
        fails.append(f"忽上忽下没连起来：{got}")
    # 2. 真的大跳（五度 + 六度，不是八度），没有录音证据 → 不动
    ns = mk([60, 67, 64, 72, 71])
    got, _ = decode(ns, [0] * 5, 50, 78)
    if got != [60, 67, 64, 72, 71]:
        fails.append(f"真的大跳被改了：{got}")
    # 3. 中间一个音掉八度（G4 A4 B3 C5 B4），没有录音证据 → 也拉回来
    ns = mk([67, 69, 59, 72, 71])
    got, _ = decode(ns, [0] * 5, 50, 78)
    if got != [67, 69, 71, 72, 71]:
        fails.append(f"掉下去的一个音没拉回来：{got}")
    # 4. 平滑的旋律 → 一个都不动
    ns = mk([60, 62, 64, 65, 67, 65, 64, 62, 60])
    got, _ = decode(ns, [0] * 9, 50, 78)
    if got != [60, 62, 64, 65, 67, 65, 64, 62, 60]:
        fails.append(f"平滑的旋律被改了：{got}")
    # 5. 音域外的不去：最高 70，B3→B4(71) 不许
    ns = mk([67, 69, 59, 69])
    got, _ = decode(ns, [0] * 4, 50, 70)
    if 71 in got:
        fails.append(f"跑到音域外了：{got}")
    # 按句（第二版）：同一句 G4 A3 B3 G4 A3 B3（录音都有另一个八度），后面接高音区 → 整句取上；接低音区 → 整句取下
    phrase = [67, 57, 59, 67, 57, 59]
    oth = [-12, 12, 12, -12, 12, 12]
    got, _ = decide_phrases(mk(phrase + [66, 67]), oth + [0, 0], 45, 80)
    if got[:6] != [67, 69, 71, 67, 69, 71]:
        fails.append(f"按句：后面接高音区没整句取上：{got}")
    got, _ = decide_phrases(mk(phrase + [54, 55]), oth + [0, 0], 45, 80)
    if got[:6] != [55, 57, 59, 55, 57, 59]:
        fails.append(f"按句：后面接低音区没整句取下：{got}")
    got, _ = decide_phrases(mk([60, 62, 64, 72, 71]), [0] * 5, 45, 80)
    if got != [60, 62, 64, 72, 71]:
        fails.append(f"按句：只有一个声部的被动了：{got}")
    # 第三版：叠唱句整句取上（前面接低的主歌、中间换一口气 1.5 秒，也一样）；主歌结尾两个低音不许被带走
    verse = [(0.0, 0.4, 5500.0, ""), (0.45, 0.4, 5400.0, "")]
    chorus = [(2.35 + i * 0.45, 0.4, p * 100.0, "") for i, p in enumerate([67, 57, 59, 67, 57, 59])]
    got, _ = upper_then_fix(verse + chorus, [0, 0, -12, 12, 12, -12, 12, 12], 45, 80)
    if got[2:] != [67, 69, 71, 67, 69, 71] or got[:2] != [55, 54]:
        fails.append(f"第三版：叠唱句没整句取上，或前面的被带走了：{got}")
    # 紧贴着（没有换气）的边上一个低音：也不许为了接得顺被带走 —— 只拉「前后都在另一个音区」的
    got, _ = upper_then_fix(mk([54] + [67, 57, 59]), [0, -12, 12, 12], 45, 80)
    if got[0] != 54:
        fails.append(f"第三版：边上的音被带走了：{got}")
    got, _ = upper_then_fix(mk([67, 69, 71, 67, 57, 71, 69]), [-12, -12, -12, 0, 0, -12, -12], 45, 80)
    if got[4] != 69:
        fails.append(f"第三版：夹在中间单独掉下去的没拉回来：{got}")
    for ps in ([60, 67, 64, 72, 71], [60, 62, 64, 65, 67, 65, 64, 62, 60]):
        got, _ = upper_then_fix(mk(ps), [0] * len(ps), 45, 80)
        if got != ps:
            fails.append(f"第三版：只有一个声部的被动了：{got}")
    return fails


def pick(notes: list, vocal_wav: str | None = None, bp_raw: str | None = None) -> tuple[list, list[int], list[str], list[int]]:
    """只算、不写：→ (挑过八度的音, 新音高, 每个音用的哪种, 录音里另一个八度的方向)。回归检查（regress_r05.py）只调这个。
    vocal_wav / bp_raw 不给就是《傍晚》的（人声分轨、basic-pitch 原样输出）；换歌时传这首的。"""
    import numpy as np
    import soundfile as sf
    y, sr = sf.read(vocal_wav or R.VOCAL_STEM, dtype="float32")
    y = y.mean(axis=1) if y.ndim > 1 else y
    bp = json.loads(pathlib.Path(bp_raw).read_text(encoding="utf-8") if bp_raw else M.BP_RAW.read_text(encoding="utf-8"))
    lower_db = [O.lower_octave_index(y, sr, s, d, O.hz(c)) for s, d, c, _ in notes]
    thr_db = float(np.median([v for v in lower_db if v is not None])) + M.DOWN_MARGIN_DB
    ps = [int(round(c / 100)) for _, _, c, _ in notes]
    lo, hi = min(ps) - RANGE_SLACK, max(ps) + RANGE_SLACK
    direction = [M.decide(*M.octave_candidates(bp, s, d, c), lower_db[k], thr_db, ps[k], lo)
                 for k, (s, d, c, _) in enumerate(notes)]
    flags = M.runs_filter(notes, [x != 0 for x in direction])
    other = [direction[k] // 100 if flags[k] else 0 for k in range(len(notes))]
    new, why = upper_then_fix(notes, other, lo, hi)
    # 录音当第二个裁判（09-30《潮声回响》加的）：只靠前后音判的「单独翘上去的，拉回来」（往下拉），basic-pitch 在那一刻
    # 只听到原来的八度、没听到改后的 → 不拉（这首 1:59.5 的 G5、2:34.8 的 A4 就是被前后音错拉下来的真高音）。
    # 只管往下拉的：往上拉的（单独掉下去的）不管 —— 叠唱段两个八度一起唱，basic-pitch 常只听到响的那个；
    # 《傍晚》1:59.1 那个就是：整句取上以后把掉下去的一个拉上来，录音里只听到下面那个，照这条改回去反而把句子改坏了
    for k, w in enumerate(why):
        if w.startswith("单独翘上去") and new[k] != ps[k]:
            s, d = notes[k][0], notes[k][1]
            seen = {n["pitch"] for n in bp if n["start"] < s + d - 0.02 and n["end"] > s + 0.02}
            if ps[k] in seen and new[k] not in seen:
                new[k], why[k] = ps[k], "原样（录音里只听到原来的八度，不拉）"
    out = [(s, d, float(new[k] * 100 + (c - ps[k] * 100)), ly) for k, (s, d, c, ly) in enumerate(notes)]
    return out, new, why, other


def main(base_json: str, rnd: str) -> int:
    fails = selftest()
    print("自检：", "通过（三稿的例子都测：叠唱句整句取上、单独掉下去的拉回来、真大跳和平滑旋律不动、不出音域）"
          if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    notes = sorted(tuple(x) for x in json.load(open(base_json, encoding="utf-8")))
    out, new, why, other = pick(notes)
    ps = [int(round(c / 100)) for _, _, c, _ in notes]
    changes = [f"{fmt(notes[k][0])}「{notes[k][3]}」{nm(ps[k])} → {nm(new[k])}（{why[k]}）"
               for k in range(len(notes)) if new[k] != ps[k]]
    lead = C.tracks(C.load_svp(M.FINAL))["vocal1"]
    before, after = C.compare(lead, list(notes)), C.compare(lead, out)
    phrases = [f"{fmt(notes[i][0])}–{fmt(notes[j][0] + notes[j][1])}：{next((why[k] for k in range(i, j + 1) if why[k] != '原样'), '原样（GAME 本来就在那个八度）')}"
               for i, j in runs_of([o != 0 for o in other])]
    res = {"叠唱的句子": phrases, "改了八度的音": len(changes),
           "对终稿主唱": {"之前": {k: before[k] for k in ("F1", "扒对（起音+音高）", "八度错误")},
                     "之后": {k: after[k] for k in ("F1", "扒对（起音+音高）", "八度错误")}},
           "逐个": changes}
    for k, v in res.items():
        if k != "逐个":
            print(f"  {k}：{v}")
    print("  逐个：")
    for x in changes:
        print("   ", x)
    M.OUT.mkdir(parents=True, exist_ok=True)
    (M.OUT / f"{rnd}_octave.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (M.OUT / f"{rnd}_notes.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    bad = []
    for wf in (False, True):
        _, f = R.write_round([(f"扒谱 {rnd}（挑过八度）", out)], rnd, wf)
        bad += f
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "E:/sv-agent-data/probes/m1-03-lyrics/r04_notes.json",
                          sys.argv[2] if len(sys.argv) > 2 else "r05"))
