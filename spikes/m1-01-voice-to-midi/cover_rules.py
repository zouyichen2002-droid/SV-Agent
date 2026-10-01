# -*- coding: utf-8 -*-
"""翻唱第一版的三条新规矩 —— 创作者 09-30 改《刽子手》r02 以后说的：

1.「不用严格每个词都要落位」：一行歌词和听写几乎对不上（对上的字不到 1/4）→ 这行整行不放、拿掉以后重新对齐其余的，列给创作者。
   r02 就是把主唱没唱的行硬对到旁边真唱的音上、把真字挤走（1:24、3:03）。依据：《刽子手》要拿掉的行对上的都是 0（正好是他没放的那些），
   《潮声回响》≤ 0.18（2:11–2:35 那段回声句为主），《傍晚》每行都唱、最低 0.8 —— 门槛 0.25 在中间的空档里。
2.「长音可以截成两段，后一段用韵母 e/o/u」：
   - 一个字被 GAME 切成同音高、紧挨着的两段（后一段没字）→ 后一段写这个字的韵母（创作者改的 lu→u、wo→o）
   - 切成三段以上 → 并回一个（他把 1:24 那串同音高的碎片并成了一个 2.18 秒的长音）
   - 单个音 ≥ 3 秒 → 从中间截成两段，后一段写韵母（他截了 6.46 秒的；2.18 秒的没截；《傍晚》终稿 2.24 / 2.7 秒的也没截）
   - 韵母只写单个元音 a / o / e / i / u（取韵母最后那个元音：uo→o、ou→u、ai→i）；鼻音收尾（an、ang……）、zhi chi shi ri zi ci si 的 i、ü 不写，
     这些后一段照旧用「-」、长音也不截（截开会把鼻音唱到中间去）
   - 音高变了的接续（往上 / 往下滑）照旧用「-」—— 他留下的 18 个「-」里 17 个是这种
3.「念唱部分（音符基本相同或者同一句中只有 1-2 个音不一样，类似 C C C D C C C D）识别为吟唱，写成同一句中只有少数几个音不一样；
   这也是主旋律的一部分，类似 rap」：
   一句（音和音之间空 ≤ 0.25 秒）里带字的音 ≥ 6 个、占整句 ≥ 70%（《刽子手》第 1 行 8/11）、带字的音长中位 ≤ 0.6 拍；
   只拿带字的音算（拖音、写成韵母的接续不算）：主音取出现最多的那个音高
   （一样多取离中位近的、再一样取高的）；离主音 ≥ 2 个半音的算「不一样的」，每 8 个音最多 2 个才算念唱 ——
   念唱就把离主音 1 个半音的（GAME 把同一个念唱音扒抖了）拉回主音，离得远的那几个照留；拖音跟着前一个字，句首的归主音。
   两个音交替的（《刽子手》齐唱第 1 遍 A4 / G4 各一半，pyin 量出来两个音都是真的）不算念唱、不动。

只动音高和字、并 / 截音，不动起音（吸格线在后面）。每条都列改了哪些音。
"""
from __future__ import annotations

import re
import statistics

LINE_MIN_MATCH = 0.25
LONG_SPLIT_SEC = 3.0
CONTIG = 0.03
CHANT_GAP, CHANT_MIN_NOTES, CHANT_SYLLABIC, CHANT_MAX_BEATS = 0.25, 6, 0.7, 0.6
INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"                                   # noqa: E731


# ---------- 1. 对不上的行不放 ----------
def line_match(lines: list[str], ops: list[tuple]) -> list[float]:
    """每行歌词里，和听写对上（一样 / 近似）的字占多少。ops 是 lyric_align.align 的结果 (i 歌词, j 音, 类别)。"""
    owner = [li for li, ln in enumerate(lines) for _ in ln]
    good = [0] * len(lines)
    for i, j, k in ops:
        if i is not None and j is not None and k in ("一样", "近似"):
            good[owner[i]] += 1
    return [good[li] / max(1, len(ln)) for li, ln in enumerate(lines)]


def drop_unsung(lines: list[str], rates: list[float]) -> tuple[list[int], list[int]]:
    """→ (留下的行号, 拿掉的行号)，从 0 数。"""
    keep = [li for li, r in enumerate(rates) if r >= LINE_MIN_MATCH]
    return keep, [li for li in range(len(lines)) if li not in keep]


# ---------- 2. 同音高的接续 ----------
def vowel_of(py: str) -> str | None:
    """拼音（不带声调）→ 拖长时后一段写的单个元音；写不了的（鼻音收尾、zhi/chi/shi/ri/zi/ci/si、ü）→ None。"""
    s = re.sub(r"[0-9]", "", (py or "").strip().lower())
    if not s or s in ("-", "+") or not s.isalpha():
        return None
    if re.fullmatch(r"(zh|ch|sh|r|z|c|s)i", s) or "v" in s or "ü" in s:
        return None
    ini = next((p for p in INITIALS if s.startswith(p) and len(s) > len(p)), "")
    fin = s[len(ini):]
    if ini in ("j", "q", "x", "y") and fin.startswith("u"):                     # ju qu xu yu 的 u 是 ü
        return None
    if not fin or fin[-1] not in "aoeiu" or fin.endswith("er"):
        return None
    return fin[-1]


def same_pitch(notes: list[tuple]) -> tuple[list[tuple], list[str]]:
    """notes = [(起音秒, 时值秒, 音分, 字)] 按时间排好。→ (新的音, 改了什么)。"""
    out, log, k = [], [], 0
    notes = sorted(notes)
    while k < len(notes):
        s, d, c, ly = notes[k]
        run = [notes[k]]
        while (k + len(run) < len(notes) and notes[k + len(run)][3] in ("-", "")
               and int(round(notes[k + len(run)][2] / 100)) == int(round(c / 100))
               and notes[k + len(run)][0] - (run[-1][0] + run[-1][1]) < CONTIG):
            run.append(notes[k + len(run)])
        if ly in ("-", "") or len(run) == 1:
            out.append(notes[k])
        elif len(run) == 2:
            v = vowel_of(ly)
            out.append(run[0])
            out.append((run[1][0], run[1][1], run[1][2], v or run[1][3]))
            if v:
                log.append(f"{fmt(run[1][0])}「{ly}」后面同音高的那段写成韵母「{v}」")
        else:
            end = run[-1][0] + run[-1][1]
            out.append((s, end - s, c, ly))
            log.append(f"{fmt(s)}「{ly}」同音高的 {len(run)} 段并成一个（{end - s:.2f} 秒）")
        k += len(run)
    final = []
    for s, d, c, ly in out:
        v = vowel_of(ly) if ly not in ("-", "") else None
        if d >= LONG_SPLIT_SEC and v:
            half = d / 2
            final += [(s, half, c, ly), (s + half, d - half, c, v)]
            log.append(f"{fmt(s)}「{ly}」{d:.2f} 秒的长音截成两段，后一段写「{v}」")
        else:
            final.append((s, d, c, ly))
    return final, log


# ---------- 3. 念唱 ----------
def phrases(notes: list[tuple]) -> list[list[int]]:
    out, cur = [], [0]
    for k in range(1, len(notes)):
        if notes[k][0] - (notes[k - 1][0] + notes[k - 1][1]) > CHANT_GAP:
            out.append(cur)
            cur = []
        cur.append(k)
    out.append(cur)
    return out


def chant(notes: list[tuple], beat_sec) -> tuple[list[tuple], list[str]]:
    """beat_sec(秒) → 那一刻一拍多少秒。→ (新的音, 改了什么)。"""
    notes = sorted(notes)
    out, log = list(notes), []
    for ph in phrases(notes):
        # 只看带字的音（拖音「-」、写成韵母的接续不算）：《刽子手》第 1 行夹着 3 个拖音，一起算就认不出
        sung = [k for k in ph if notes[k][3] not in ("-", "") and vowel_of(notes[k][3]) != notes[k][3]]
        if len(sung) < CHANT_MIN_NOTES or len(sung) < CHANT_SYLLABIC * len(ph):
            continue
        if statistics.median(notes[k][1] for k in sung) > CHANT_MAX_BEATS * beat_sec(notes[ph[0]][0]):
            continue
        ps = {k: int(round(notes[k][2] / 100)) for k in sung}
        vals = list(ps.values())
        cnt = {p: vals.count(p) for p in set(vals)}
        med = statistics.median(vals)
        tone = max(cnt, key=lambda p: (cnt[p], -abs(p - med), p))
        far = [k for k in sung if abs(ps[k] - tone) >= 2]
        if len(far) > len(sung) // 4:
            continue
        changed, last = [], None
        for k in ph:                                              # 带字的：离主音 1 个半音的拉回；拖音：跟着前一个字（句首的归主音）
            p = int(round(out[k][2] / 100))
            if k in ps:
                q = tone if abs(p - tone) == 1 else p
                last = q
            else:
                q = last if last is not None else tone
            if q != p:
                s, d, c, ly = out[k]
                out[k] = (s, d, float(q * 100 + (c - p * 100)), ly)
                changed.append(k)
        if changed:
            log.append(f"{fmt(notes[ph[0]][0])}–{fmt(notes[ph[-1]][0] + notes[ph[-1]][1])} 念唱（带字的 {len(sung)} 个、主音 {tone}）："
                       f"改了音高 {len(changed)} 个，留着不一样的 {len(far)} 个")
    return out, log


def selftest() -> list[str]:
    fails = []
    # 1. 行
    if drop_unsung(["ab", "cd", "ef"], [1.0, 0.1, 0.5]) != ([0, 2], [1]):
        fails.append("对不上的行没拿对")
    # 2. 韵母
    for py, want in (("wo", "o"), ("le", "e"), ("lu", "u"), ("su", "u"), ("kuo", "o"), ("yi", "i"), ("ni", "i"), ("hou", "u"),
                     ("lai", "i"), ("ya", "a"), ("zhang", None), ("shi", None), ("zi", None), ("yu", None), ("ju", None),
                     ("er", None), ("-", None), ("wan", None)):
        if vowel_of(py) != want:
            fails.append(f"韵母不对：{py} → {vowel_of(py)}（应 {want}）")
    got, _ = same_pitch([(0.0, 1.0, 6900.0, "wo"), (1.0, 0.5, 6900.0, "-")])
    if [g[3] for g in got] != ["wo", "o"]:
        fails.append(f"同音高两段：{got}")
    got, _ = same_pitch([(0.0, 0.5, 7400.0, "kuo"), (0.5, 0.3, 7400.0, "-"), (0.8, 0.3, 7400.0, "-"), (1.1, 0.4, 7400.0, "-")])
    if len(got) != 1 or abs(got[0][1] - 1.5) > 1e-9 or got[0][3] != "kuo":
        fails.append(f"同音高四段没并成一个：{got}")
    got, _ = same_pitch([(0.0, 6.4, 7900.0, "wo")])
    if [g[3] for g in got] != ["wo", "o"] or abs(got[1][0] - 3.2) > 1e-9:
        fails.append(f"6.4 秒的长音没截成两段：{got}")
    got, _ = same_pitch([(0.0, 6.4, 7900.0, "zhang"), (7.0, 2.5, 7900.0, "wo")])
    if len(got) != 2:
        fails.append(f"鼻音收尾的长音被截了 / 2.5 秒的被截了：{got}")
    got, _ = same_pitch([(0.0, 0.5, 6900.0, "wo"), (0.5, 0.3, 6700.0, "-")])
    if got[1][3] != "-":
        fails.append(f"音高变了的接续被写成了韵母：{got}")
    # 3. 念唱
    beat = lambda s: 0.4615                                                       # noqa: E731  130 BPM
    mk = lambda ps, d=0.23, ly="la": [(i * d, d, p * 100.0, ly) for i, p in enumerate(ps)]  # noqa: E731
    got, _ = chant(mk([66, 68, 69, 68, 69, 65, 68, 69]), beat)
    if [int(g[2] // 100) for g in got] != [66, 68, 68, 68, 68, 65, 68, 68]:
        fails.append(f"念唱没拉平：{[int(g[2] // 100) for g in got]}")
    two = [69, 69, 69, 67, 67, 69, 68, 69, 67, 67, 69, 67, 67]
    got, _ = chant(mk(two), beat)
    if [int(g[2] // 100) for g in got] != two:
        fails.append("两个音交替的被当成念唱拉平了")
    mel = [67, 63, 60, 67, 69, 68, 72, 75, 79, 75, 72, 67]
    got, _ = chant(mk(mel), beat)
    if [int(g[2] // 100) for g in got] != mel:
        fails.append("旋律被当成念唱了")
    got, _ = chant(mk([66, 68, 69, 68, 69, 65, 68, 69], d=0.9), beat)
    if [int(g[2] // 100) for g in got] != [66, 68, 69, 68, 69, 65, 68, 69]:
        fails.append("长音的句子被当成念唱了")
    got, _ = chant(mk([66, 68, 69, 68, 69, 65, 68, 69], ly="-"), beat)
    if [int(g[2] // 100) for g in got] != [66, 68, 69, 68, 69, 65, 68, 69]:
        fails.append("拖音为主的句子被当成念唱了")
    # 《刽子手》第 1 行那样：句首两个拖音、中间一个拖音，带字的 8 个是念唱 → 带字的拉平、拖音跟前一个字、句首的归主音
    ps1 = [70, 68, 68, 68, 72, 69, 67, 68, 66, 67, 69]
    ly1 = ["-", "-", "da", "di", "da", "-", "du", "de", "ta", "lan", "la"]
    n1 = [(i * 0.12, 0.12, p * 100.0, ly) for i, (p, ly) in enumerate(zip(ps1, ly1))]
    got, _ = chant(n1, beat)
    if [int(g[2] // 100) for g in got] != [68, 68, 68, 68, 72, 72, 68, 68, 66, 68, 68]:
        fails.append(f"夹着拖音的念唱没认对：{[int(g[2] // 100) for g in got]}")
    return fails


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    f = selftest()
    print("自检：", "通过" if not f else f)
