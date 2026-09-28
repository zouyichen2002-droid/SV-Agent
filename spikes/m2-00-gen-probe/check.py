# -*- coding: utf-8 -*-
"""候选的检查：硬检查（不过就不渲染）+ 建议性的数（只报数，不判好坏）+ 约束词执行情况。

- **硬检查**只管「结构对不对」：格式、小节数、网格、重叠、跨小节线、音高范围、和弦写法、拖腔接不接得上。
  它不说好不好听 —— PRD §2：指标挡得住「明显不行」，挡不住「平庸」。
- **建议性的数**（音域、时值种类、切分、气口……）只是量出来给你参考，R03 允许保留没过建议性检查的候选。
- **自检**：先拿一份手写的合法样本，注入 9 种已知缺陷，每一种都必须被抓到、合法样本不许误报
  （PRD §12 纪律一）。自检不过，整次探针不跑。
"""
from __future__ import annotations

import copy
import math
import re

import music

BARS = 16
GRID = 0.25
PITCH_MIN, PITCH_MAX = 48, 84          # 硬边界 C3–C6：超出多半是写错了八度
ADVISED = (57, 76)                     # 提示词里要求的 A3–E5
MIN_SUNG = 8                           # 16 小节里少于 8 个字，基本等于没写
KEYS = {"C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B"}
EPS = 1e-9


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _on_grid(x: float) -> bool:
    return abs(x / GRID - round(x / GRID)) < 1e-6


def _cjk(ch: str) -> bool:
    return isinstance(ch, str) and len(ch) == 1 and "一" <= ch <= "鿿"


def hard_errors(c) -> list[str]:
    """→ 错误清单，空 = 结构合法。"""
    if not isinstance(c, dict):
        return ["不是 JSON 对象"]
    errs = []
    if not _num(c.get("bpm")) or not (50 <= c["bpm"] <= 200):
        errs.append(f"bpm 不合法：{c.get('bpm')!r}")
    if c.get("key") not in KEYS:
        errs.append(f"key 不合法：{c.get('key')!r}")
    if c.get("mode") not in ("major", "minor"):
        errs.append(f"mode 不合法：{c.get('mode')!r}")
    bars = c.get("bars")
    if not isinstance(bars, list) or len(bars) != BARS:
        errs.append(f"小节数应为 {BARS}，实际 {len(bars) if isinstance(bars, list) else repr(bars)}："
                    f"只保留 {BARS} 个小节（主歌 1–8、副歌 9–16），多出来的整段删掉，不要前奏、尾奏")
        return errs
    if [b.get("bar") if isinstance(b, dict) else None for b in bars] != list(range(1, BARS + 1)):
        errs.append("小节编号不是 1–16 顺序")
        return errs
    prev_global_end = None
    sung = 0
    for b in bars:
        n = b["bar"]
        chords = b.get("chords")
        if not isinstance(chords, list) or len(chords) not in (1, 2):
            errs.append(f"第 {n} 小节：和弦要 1 或 2 个")
        else:
            for ch in chords:
                try:
                    music.parse_chord(ch)
                except ValueError as e:
                    errs.append(f"第 {n} 小节：{e}")
        mel = b.get("melody")
        if not isinstance(mel, list):
            errs.append(f"第 {n} 小节：melody 不是列表")
            continue
        prev_start, prev_end = 0.0, 0.0
        for i, note in enumerate(mel):
            where = f"第 {n} 小节第 {i + 1} 个音"
            if not (isinstance(note, list) and len(note) == 4):
                errs.append(f"{where}：格式要 [起拍, 时值, 音高, 字]")
                continue
            st, du, p, ly = note
            if not (_num(st) and _num(du)):
                errs.append(f"{where}：起拍、时值要是数")
                continue
            if not (_on_grid(st) and _on_grid(du)) or du < GRID - EPS:
                errs.append(f"{where}：起拍 {st} / 时值 {du} 不在 0.25 拍的网格上")
            if st < -EPS or st >= 4 - EPS:
                errs.append(f"{where}：起拍 {st} 超出小节")
            if st + du > 4 + EPS:
                errs.append(f"{where}：跨小节线（{st} + {du} > 4）")
            if not (isinstance(p, int) and not isinstance(p, bool)) or not (PITCH_MIN <= p <= PITCH_MAX):
                errs.append(f"{where}：音高不合法 {p!r}（要 {PITCH_MIN}–{PITCH_MAX} 的整数）")
            if not (ly == "-" or _cjk(ly)):
                errs.append(f"{where}：歌词要一个汉字或「-」，实际 {ly!r}")
            if i > 0 and st < prev_end - EPS:
                move = f"，或者把这个音挪到 {prev_end} 拍" if prev_end < 4 - EPS else ""
                errs.append(f"{where}（{st} 拍起）和前一个音重叠：前一个音到 {prev_end} 拍才结束 ——"
                            f"把前一个音缩短到 {st - prev_start} 拍{move}")
            g0 = (n - 1) * 4 + st
            if ly == "-" and prev_global_end is None:
                errs.append(f"{where}：拖腔「-」前面没有音可拖 —— 改成一个新字")
            elif ly == "-" and abs(g0 - prev_global_end) > EPS:
                gap = g0 - prev_global_end
                pb, pt = int(prev_global_end // 4) + 1, prev_global_end % 4
                pos = f"第 {pb} 小节 {pt} 拍" if pt > EPS else f"第 {pb - 1} 小节末尾"
                errs.append(f"{where}：拖腔「-」没有紧接着的前一个音 —— 前一个音在{pos}就结束了，"
                            f"中间{'空了' if gap > 0 else '重叠了'} {abs(gap)} 拍：把前一个音的时值{'加长' if gap > 0 else '缩短'} "
                            f"{abs(gap)} 拍，或者把这个音改成一个新字")
            if ly != "-":
                sung += 1
            prev_start = st
            prev_end = st + du
            prev_global_end = g0 + du
    if sung < MIN_SUNG:
        errs.append(f"旋律几乎是空的：只有 {sung} 个字")
    return errs


# ---------------------------------------------------------------- 建议性的数

def _notes(c):
    """→ [(全曲起拍, 时值, 音高, 字, 小节)]"""
    return [((b["bar"] - 1) * 4 + st, du, p, ly, b["bar"]) for b in c["bars"] for st, du, p, ly in b["melody"]]


def _scale(key: str, mode: str) -> set[int]:
    tonic = music.pitch_class(key[0], key[1:] if len(key) > 1 else "")
    steps = [0, 2, 4, 5, 7, 9, 11] if mode == "major" else [0, 2, 3, 5, 7, 8, 10, 9, 11]  # 小调含升 6、7 级
    return {(tonic + s) % 12 for s in steps}


def _bar_rhythm(b) -> tuple:
    return tuple((st, du) for st, du, _, _ in b["melody"])


def is_332(b) -> bool:
    onsets = {st for st, _, _, _ in b["melody"]}
    return {0, 1.5, 3} <= onsets


def syncopations(c) -> int:
    """反拍起、并且拖过下一拍的音（经典切分）。"""
    return sum(1 for g, du, *_ in _notes(c) if abs(g - round(g)) > EPS and g + du > math.ceil(g) + EPS)


def metrics(c) -> dict:
    ns = _notes(c)
    pitches = [p for _, _, p, _, _ in ns]
    verse = [x for x in ns if x[4] <= 8]
    chorus = [x for x in ns if x[4] >= 9]
    gaps = [ns[i + 1][0] - (ns[i][0] + ns[i][1]) for i in range(len(ns) - 1)]
    rests = sum(1 for g in gaps if g >= 0.5 - EPS)
    leaps = [abs(ns[i + 1][2] - ns[i][2]) for i in range(len(ns) - 1)]
    scale = _scale(c["key"], c["mode"])
    rhythms = [_bar_rhythm(b) for b in c["bars"]]
    same_adjacent = sum(1 for i in range(len(rhythms) - 1) if rhythms[i] and rhythms[i] == rhythms[i + 1])
    lyric_notes = "".join(ly for _, _, _, ly, _ in ns if ly != "-")
    lyric_text = re.sub(r"[^一-鿿]", "", "".join(c.get("lyrics") or []))
    return {
        "音符数": len(ns),
        "字数": len(lyric_notes),
        "音域": f"{min(pitches)}–{max(pitches)}（{max(pitches) - min(pitches)} 个半音）",
        "超出 A3–E5 的音": sum(1 for p in pitches if not ADVISED[0] <= p <= ADVISED[1]),
        "时值种类": len({du for _, du, *_ in ns}),
        "切分": syncopations(c),
        "三三二小节": sum(1 for b in c["bars"] if is_332(b)),
        "≥ 半拍的休止": rests,
        "相邻小节节奏完全一样": same_adjacent,
        "最大跳进（半音）": max(leaps) if leaps else 0,
        "调内音占比": round(sum(1 for p in pitches if p % 12 in scale) / len(pitches), 2),
        "主歌每小节音数": round(len(verse) / 8, 2),
        "副歌每小节音数": round(len(chorus) / 8, 2),
        "主歌最高音": max(p for _, _, p, _, _ in verse) if verse else None,
        "副歌最高音": max(p for _, _, p, _, _ in chorus) if chorus else None,
        "歌词和音符对得上": lyric_notes == lyric_text,
        "_lines": len(c.get("lyrics") or []),
    }


CONSTRAINTS = [
    ("至少 4 种时值", lambda m: m["时值种类"] >= 4),
    ("至少两处切分或三三二", lambda m: m["切分"] + m["三三二小节"] >= 2),
    ("句尾留气口", lambda m: m["≥ 半拍的休止"] >= max(1, m["_lines"] - 1)),
    ("相邻小节节奏不重复", lambda m: m["相邻小节节奏完全一样"] == 0),
    ("主歌稀、副歌密", lambda m: m["副歌每小节音数"] > m["主歌每小节音数"]),
    ("副歌最高音更高", lambda m: (m["副歌最高音"] or 0) > (m["主歌最高音"] or 0)),
]


def constraint_report(m: dict) -> list[tuple[str, bool]]:
    return [(name, bool(rule(m))) for name, rule in CONSTRAINTS]


# ---------------------------------------------------------------- 自检

def _base() -> dict:
    bars = []
    for n in range(1, BARS + 1):
        mel = [[0, 1, 64, "啊"], [1, 1, 65, "啊"], [2, 1.5, 67, "啊"], [3.5, 0.5, 69, "-"]]
        bars.append({"bar": n, "chords": ["C"] if n % 2 else ["F", "G7"], "melody": mel})
    return {"title": "自检", "key": "C", "mode": "major", "bpm": 90,
            "lyrics": ["啊" * 48], "bars": bars, "idea": ""}


def _inject(fn):
    c = _base()
    fn(c)
    return c


DEFECTS = [
    ("重叠", lambda c: c["bars"][0]["melody"][1].__setitem__(0, 0.5)),
    ("跨小节线", lambda c: c["bars"][2]["melody"].__setitem__(3, [3.5, 1, 69, "-"])),
    ("音高不合法", lambda c: c["bars"][4]["melody"][0].__setitem__(2, 100)),
    ("小节数", lambda c: c["bars"].pop()),
    ("和弦写法", lambda c: c["bars"][1].__setitem__("chords", ["Hx7"])),
    ("拖腔", lambda c: c["bars"][0]["melody"][0].__setitem__(3, "-")),
    ("网格", lambda c: c["bars"][3]["melody"][0].__setitem__(1, 0.3)),
    ("bpm", lambda c: c.__setitem__("bpm", "fast")),
    ("拖腔", lambda c: c["bars"][5]["melody"].__setitem__(3, [3.75, 0.25, 69, "-"])),
]


def selftest() -> list[str]:
    """→ 失败清单，空 = 检查器可信。"""
    fails = []
    base_errs = hard_errors(_base())
    if base_errs:
        fails.append(f"合法样本被误报：{base_errs[:2]}")
    for keyword, fn in DEFECTS:
        errs = hard_errors(_inject(fn))
        if not any(keyword in e for e in errs):
            fails.append(f"注入「{keyword}」没被抓到：{errs[:2]}")
    m = metrics(_base())
    if m["相邻小节节奏完全一样"] != 15:
        fails.append(f"「相邻小节节奏一样」该是 15，量出 {m['相邻小节节奏完全一样']}")
    if not m["歌词和音符对得上"]:
        fails.append("合法样本的歌词被判成对不上")
    c332 = _inject(lambda c: c["bars"][0].__setitem__("melody", [[0, 1.5, 64, "啊"], [1.5, 1.5, 65, "啊"], [3, 1, 67, "啊"]]))
    if not is_332(c332["bars"][0]) or is_332(_base()["bars"][0]):
        fails.append("三三二识别不对")
    if syncopations(c332) < 1 or syncopations(_base()) != 0:
        fails.append(f"切分识别不对：注入后 {syncopations(c332)}，合法样本 {syncopations(_base())}")
    return fails
