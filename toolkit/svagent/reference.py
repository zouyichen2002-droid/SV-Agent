# -*- coding: utf-8 -*-
"""参考曲分析：**拿真歌重新校准我们的判据**。

## 为什么要有这个模块

`agent/metrics.py` 第 10 行写着：阈值是拿《晓风残月》校出来的 ——
「任何把它判为不合格的阈值都是错的」。那条原则**默认了已验收的作品是好的**。

2026-09-05 创作者说：「完全忘记之前我们编写的那些歌曲，因为我并不满意其实，
还是要从真正的歌曲中学习」。推论很直接：

> **检查全过，是因为阈值照着我们自己的水平校的。
> 它结构上不可能告诉我们「离专业水准还差多少」—— 它没见过专业水准。**

所以这里读真歌，算**同一批指标**，把分布拿出来。

## 硬约束：复用，不重写

`chord_fit_ratios` 直接从 `compose.checks` 拿。**两个实现算同一件事，
迟早算出两个不同的数，而且两边都不报错** —— 这个项目为此栽过五次。
真歌的数和我们的数必须出自同一段代码，否则「对比」本身是假的。

## 一处必须标明的不可比

`contour_line`（每句极差）在我们的歌里**按歌词行**切句，
POP909 没有歌词，只能**按休止**切。**这是两种切法。**
两者的句长分布接近时才谈得上比较 —— 所以 `measure()` 会把句数与
句长中位一起报出来，让这件事可被检查，而不是埋在数字里。

## 数据集不进仓库

POP909 是 909 首商业流行歌的 MIDI 转录：转录本身 MIT，
底下的作品版权在原权利人。**路径从外面传**，这里只读。
引用要求见其 README（ISMIR 2020）。
"""
from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field
from pathlib import Path

from .compose.checks import Note, Phrase, chord_fit_ratios

# 音名 → 音级。POP909 的和弦标注用 `B:maj` `Gb:maj` `C#:min` 这种写法
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# 休止多长算「断句」。八分音符在 129BPM 下约 0.23 拍，
# 半拍以上的空当基本就是换气 —— 这个值影响 contour_line，所以显式写出来
LINE_GAP_BEATS = 0.5
MIN_LINE_NOTES = 2          # 少于两个音的「句」算不出极差


def _pitch_class(name: str) -> int | None:
    name = name.strip()
    if not name or name[0] not in _PC:
        return None
    pc = _PC[name[0]]
    for ch in name[1:]:
        if ch == "#":
            pc += 1
        elif ch == "b":
            pc -= 1
        else:
            break
    return pc % 12


def _quality(q: str) -> str:
    """→ "major" / "minor"。

    `chord_fit_ratios` 只认三和弦（大 0-4-7 / 小 0-3-7），
    所以七和弦、挂留和弦都要归到最近的那一类。**这是有损的**，
    但对「旋律音落不落在和弦上」这个问题影响很小：
    七音与挂留音本来就不在三和弦里，归哪边都算「不贴合」。
    """
    q = q.lower()
    return "minor" if ("min" in q or "dim" in q) else "major"


@dataclass
class Ref:
    """一首参考曲，切成能喂给我们自己那套指标的形状。"""
    id: str
    source: str
    notes: list[Note]
    phrases: list[Phrase] = field(default_factory=list)
    lines: list[tuple[int, int]] = field(default_factory=list)
    key: str = ""
    bpm: float | None = None
    n_accomp: int = 0            # 伴奏音符数，用来看编配密度


# =========================================================================
# POP909
# =========================================================================

def _tempo_map(mid) -> list[tuple[int, int]]:
    """→ [(tick, 微秒每拍)]。POP909 的速度是人工标注的曲线，可能有多段。"""
    import mido
    out, t = [], 0
    for msg in mid.tracks[0]:
        t += msg.time
        if msg.type == "set_tempo":
            out.append((t, msg.tempo))
    return out or [(0, 500000)]


def _tick_to_sec(tick: int, tmap, tpb: int) -> float:
    sec, last_tick, last_tempo = 0.0, 0, tmap[0][1]
    for tt, tempo in tmap:
        if tt >= tick:
            break
        sec += (tt - last_tick) / tpb * (last_tempo / 1e6)
        last_tick, last_tempo = tt, tempo
    return sec + (tick - last_tick) / tpb * (last_tempo / 1e6)


def load_pop909(song_dir) -> Ref:
    """读一首 POP909。**MELODY 轨是人声旋律**，PIANO 是伴奏。"""
    import mido
    song_dir = Path(song_dir)
    sid = song_dir.name
    mid = mido.MidiFile(str(song_dir / f"{sid}.mid"))
    tpb = mid.ticks_per_beat
    tmap = _tempo_map(mid)

    def track_notes(name):
        tr = next((t for t in mid.tracks
                   if any(m.type == "track_name" and m.name == name for m in t)),
                  None)
        if tr is None:
            return []
        out, t, on = [], 0, {}
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity > 0:
                on.setdefault(m.note, []).append(t)
            elif m.type == "note_off" or (m.type == "note_on" and not m.velocity):
                if on.get(m.note):
                    out.append((on[m.note].pop(0), t, m.note))
        return sorted(out)

    raw = track_notes("MELODY")
    notes = [Note(index=i, onset_beats=a / tpb, duration_beats=(b - a) / tpb,
                  midi=p, lyric="")
             for i, (a, b, p) in enumerate(raw)]

    # 句：按休止切。**与我们「按歌词行切」不是一回事**，measure() 会报出来
    lines, start = [], 0
    for i in range(1, len(notes)):
        gap = notes[i].onset_beats - (notes[i - 1].onset_beats
                                      + notes[i - 1].duration_beats)
        if gap >= LINE_GAP_BEATS:
            if i - start >= MIN_LINE_NOTES:
                lines.append((start, i))
            start = i
    if len(notes) - start >= MIN_LINE_NOTES:
        lines.append((start, len(notes)))

    # 和弦段 → Phrase。标注是秒，音符是拍，所以要过一次 tempo map
    phrases, pi = [], 0
    sec_of = [_tick_to_sec(a, tmap, tpb) for a, _b, _p in raw]
    ch_file = song_dir / "chord_midi.txt"
    if ch_file.exists():
        for ln in ch_file.read_text(encoding="utf-8").splitlines():
            parts = ln.split()
            if len(parts) < 3 or parts[2] == "N":
                continue
            t0, t1, name = float(parts[0]), float(parts[1]), parts[2]
            root_s, _, qual = name.partition(":")
            root = _pitch_class(root_s)
            if root is None:
                continue
            lo = next((i for i, s in enumerate(sec_of) if s >= t0), None)
            hi = next((i for i, s in enumerate(sec_of) if s >= t1), len(notes))
            if lo is None or hi <= lo:
                continue
            phrases.append(Phrase(index=pi, note_from=lo, note_to=hi,
                                  chord_root=root,
                                  chord_quality=_quality(qual)))
            pi += 1

    key = ""
    kf = song_dir / "key_audio.txt"
    if kf.exists():
        first = kf.read_text(encoding="utf-8").split("\n")[0].split()
        if len(first) >= 3:
            key = first[2]

    bpm = round(60e6 / tmap[0][1], 1) if tmap else None
    return Ref(id=sid, source="pop909", notes=notes, phrases=phrases,
               lines=lines, key=key, bpm=bpm,
               n_accomp=len(track_notes("PIANO")))


# =========================================================================
# 量：**复用我们自己那套**
# =========================================================================

def line_phrases(ref: Ref) -> list[Phrase]:
    """把和弦段**合并到行**上，一行一个乐句。

    ## 为什么必须有这一步

    直接拿 `chord_midi.txt` 的和弦段当乐句是错的：实测 POP909 的和弦段
    **中位只有 3 个音，16% 只有 1 个音**，而我们的乐句是一整行歌词（9 个音）。

    单位差三倍，贴合度就没法比 —— 一个只有 1 个音的「乐句」，
    那个音不是和弦音就是 0.0。第一版这么算出来「真歌 5% 的乐句贴合度为零」，
    差点据此把阈值从 0.30 改掉。**那不是真歌跑调，是我的单位不对。**

    合并规则：一行取**覆盖它时长最多**的那个和弦 —— 与我们「一行歌词
    标一个和弦」的做法对齐。
    """
    out = []
    for pi, (a, b) in enumerate(ref.lines):
        weight: dict[tuple[int, str], float] = {}
        for ph in ref.phrases:
            lo, hi = max(a, ph.note_from), min(b, ph.note_to)
            if hi <= lo or ph.chord_root is None:
                continue
            dur = sum(n.duration_beats for n in ref.notes[lo:hi])
            k = (ph.chord_root, ph.chord_quality)
            weight[k] = weight.get(k, 0.0) + dur
        if not weight:
            continue
        (root, qual), _w = max(weight.items(), key=lambda kv: kv[1])
        out.append(Phrase(index=pi, note_from=a, note_to=b,
                          chord_root=root, chord_quality=qual))
    return out


def measure(ref: Ref) -> dict:
    """算与 `agent/metrics.py` 同名的指标。

    `contour_lift`（副歌−主歌音区）**不在这里** —— 它要曲式标签，
    POP909 没有。硬凑一个代理值会让「和我们的数可比」变成假象。
    """
    if len(ref.notes) < 2:
        return {"id": ref.id, "error": "音符太少"}
    ps = [n.midi for n in ref.notes]
    line_ranges = [max(p) - min(p) for p in
                   ([n.midi for n in ref.notes[a:b]] for a, b in ref.lines)]
    # **按行建乐句**，不用原始和弦段 —— 单位要和我们的「一行歌词」对齐
    ratios = chord_fit_ratios(ref.notes, line_phrases(ref))  # **同一个实现**
    return {
        "id": ref.id, "key": ref.key, "bpm": ref.bpm,
        "n_notes": len(ref.notes), "n_accomp": ref.n_accomp,
        "contour_overall": float(max(ps) - min(ps)),
        "contour_line": float(st.median(line_ranges)) if line_ranges else None,
        "chord_fit": float(st.median(ratios)) if ratios else None,
        # 下面两个不是指标，是**让「切法不同」这件事可被检查**的凭据
        "n_lines": len(ref.lines),
        "line_len_median": (float(st.median([b - a for a, b in ref.lines]))
                            if ref.lines else None),
    }


def survey(root, limit: int | None = None) -> list[dict]:
    """跑一批。**读不了的歌记下来，不静默跳过。**"""
    root = Path(root)
    dirs = sorted(d for d in root.iterdir()
                  if d.is_dir() and d.name.isdigit())
    if limit:
        dirs = dirs[:limit]
    out = []
    for d in dirs:
        try:
            out.append(measure(load_pop909(d)))
        except Exception as e:
            out.append({"id": d.name, "error": f"{type(e).__name__}: {e}"})
    return out


def distribution(rows: list[dict], keys=("contour_overall", "contour_line",
                                         "chord_fit")) -> dict:
    """→ {指标: {n, min, p10, p25, 中位, p75, p90, max}}。

    **给的是分布不是一个数。** 阈值要落在哪个分位，是取舍，
    不该由我一个人在这里定死。
    """
    out = {}
    for k in keys:
        vals = sorted(r[k] for r in rows if r.get(k) is not None)
        if not vals:
            out[k] = None
            continue
        def q(p):
            return vals[min(len(vals) - 1, int(len(vals) * p))]
        out[k] = {"n": len(vals), "min": vals[0], "p10": q(.10),
                  "p25": q(.25), "median": q(.50), "p75": q(.75),
                  "p90": q(.90), "max": vals[-1]}
    return out


# =========================================================================
# 缓存好的调查结果
#
# `survey()` 跑一遍 909 首要几分钟。结果落在 `out/pop909_survey.json`，
# 之后所有「跟真歌比一比」的地方都读它。
#
# **读取口只留这一个。** 第一版 `webapp.py` 自己又读了一遍、自己又筛了一遍，
# 那就是第二个实现 —— 两边算同一件事，迟早算出两个不同的数
# **而且两边都不报错**。这项目为此栽过好几次。
# =========================================================================

SURVEY_JSON = Path(__file__).resolve().parents[2] / "out" / "pop909_survey.json"


def load_survey(path: Path | None = None) -> list[dict]:
    """读缓存的调查结果。**读不到就返回空，不抛异常也不编数。**"""
    import json
    p = path or SURVEY_JSON
    if not p.exists():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def sane_rows(rows: list[dict]) -> list[dict]:
    """滤掉切句明显不对的歌。

    POP909 只能按休止切句，遇上长连奏或密集装饰就会切出「一句 2 个音」
    或者「一句 40 个音」。拿这种句子去定阈值，定出来的是切句算法的性质，
    不是歌的性质。所以要求：**至少 10 句，且句长中位在 5–20 之间**。
    """
    return [r for r in rows
            if r.get("n_lines", 0) >= 10
            and r.get("line_len_median")
            and 5 <= r["line_len_median"] <= 20]


def values_of(rows: list[dict], key: str) -> list[float]:
    """某个指标的全部取值，排好序。"""
    return sorted(r[key] for r in rows if r.get(key) is not None)


def percentile_in(values: list[float], v: float | None) -> float | None:
    """`v` 排在 `values` 的第几百分位。

    **没有值或没有语料一律返回 `None`，不是 0。**
    0 的意思是「垫底」，`None` 的意思是「没依据」—— 三色纪律的灰档。
    """
    if v is None or not values:
        return None
    return sum(1 for x in values if x < v) / len(values) * 100.0


def pick_bpm(rng=None, rows: list[dict] | None = None) -> float:
    """给新歌挑一个速度：**在真歌的四分位距里取**。

    为什么不写死一个默认值 —— 每首新歌都同一个速度，是「怎么一直是
    那几首歌的感觉」的来源之一。为什么不全域随机 —— 真歌 p10 到 p90
    是 60 到 116，两头都有，但极端值更可能是标注问题而不是审美选择。

    语料不在就退回 **74**（909 首的中位，2026-09-18 实测），
    并且**这个数字的出处写在这里**，不是凭感觉定的。
    """
    import random
    r = rng or random.Random()
    bpms = values_of(rows if rows is not None else load_survey(), "bpm")
    if len(bpms) < 20:
        return 74.0
    lo, hi = bpms[len(bpms) // 4], bpms[len(bpms) * 3 // 4]
    return float(round(r.uniform(lo, hi)))
