# -*- coding: utf-8 -*-
r"""歌词视频的逐字时间（v3 视频 · 第一步，2026-10-01）：从 SV 工程里每个音的起止，对回歌词原文，给出每行、每个字什么时候唱。

    中文：音符上是拼音 → 和歌词原文逐字的拼音全局对齐（M1-03 的 lyric_align，修歌词用的同一个）—— 一个单位 = 一个字
    日语：音符上是假名 → 和歌词每行的读音对齐（JaG2p + fugashi 替身，按词切）—— 一个单位 = 一个词
    英文：音符上是整词（后面的音节写 +）→ 和歌词的词对齐 —— 一个单位 = 一个词
    拖音（-）、接续音节（+）、对不上字的音算前一个单位的；歌词里有、音上没有的字跟着下一个字一起亮（时长 0）。
    一个字都没对上的行不出字幕（打印出来：多半是主唱分轨里没有、或者整行被「对不上的行不放」拿掉了）。

工程用创作者最后改好的那份（他在 SV 里改了存盘，这里读到的就是改过的）；歌词用项目里的 素材\歌词_要唱的字.txt。
必须在 vocal2midi 环境里跑（要它的汉字 → 拼音、日语读音）：
    python lyric_timing.py <工程.svp> <歌词.txt> <输出.json> [--language auto|zh|en|ja] [--track 轨名]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
SPIKES = HERE.parent / "spikes"
for sub in ("m1-01-voice-to-midi", "m1-03-lyrics"):
    sys.path.insert(0, str(SPIKES / sub))
sys.path.insert(0, "E:/sv-agent-data/tools/Vocal2Midi")
import compare_notes as C  # noqa: E402
import lyric_align as A  # noqa: E402

CONT = ("-", "+")                                 # 拖音、接续音节：算前一个单位的
NONE = ("", "la", "ら", "SP", "AP", "br")         # 没字的音


def sung_track(d: dict, name: str | None) -> tuple[str, list]:
    """唱的那条：给了轨名用它；没给 → 没静音的音符轨里音最多的那条。"""
    tr = C.tracks(d)
    if name:
        if name not in tr:
            raise SystemExit(f"工程里没有轨「{name}」：{list(tr)}")
        return name, sorted(tr[name])
    muted = {t.get("name") for t in d["tracks"] if t["mainRef"].get("mute") or t.get("mixer", {}).get("mute")}
    cands = [(len(v), k) for k, v in tr.items() if k not in muted and v]
    if not cands:
        raise SystemExit("工程里没有在放的音符轨")
    k = max(cands)[1]
    return k, sorted(tr[k])


def units_zh(lines: list[str]) -> list[dict]:
    from inference.LyricFA.tools.ZhG2p import ZhG2p
    g = ZhG2p("mandarin")
    out = []
    for li, ln in enumerate(lines):
        chars = [c for c in ln if not c.isspace()]
        pys = g.convert("".join(chars)).split()
        if len(pys) != len(chars):
            raise SystemExit(f"第 {li + 1} 行拼音和字数对不上：{len(chars)} 字 / {len(pys)} 个拼音")
        out += [{"行": li, "文字": c, "键": [p]} for c, p in zip(chars, pys)]
    return out


def units_ja(lines: list[str]) -> list[dict]:
    import ja_g2p_fugashi
    ja_g2p_fugashi.install()
    from inference.LyricFA.tools.JaG2p import JaG2p
    g = JaG2p()
    out = []
    for li, ln in enumerate(lines):
        for e in g._get_analysis(ln):
            moras = [m for m in e.get("kana_moras", []) if m]
            if moras:
                out.append({"行": li, "文字": e.get("orig", ""), "键": moras})
    return out


def units_en(lines: list[str]) -> list[dict]:
    return [{"行": li, "文字": w, "键": [w.lower()]} for li, ln in enumerate(lines) for w in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)*", ln)]


def detect(text: str) -> str:
    kana = len(re.findall(r"[\u3041-\u3096\u30a1-\u30fa]", text))
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if kana >= 20 and kana >= 0.2 * (kana + han):
        return "ja"
    if han >= 20:
        return "zh"
    return "en" if latin >= 50 else "zh"


def timing(notes: list, units: list[dict], lang: str) -> dict:
    """notes：[(起音秒, 时值秒, 音分, 歌词)]。→ 每个单位的起止（秒）+ 统计。"""
    # 参考序列：每个单位的每个「键」（中文一个拼音、日语一个假名、英文一个词）；音符序列：有字的音（拖音 / 接续 / 没字的不进来）
    ref, ref_unit = [], []
    for ui, u in enumerate(units):
        for k in u["键"]:
            ref.append(k)
            ref_unit.append(ui)
    keyed = [ni for ni, n in enumerate(notes) if n[3] not in CONT + NONE]
    hyp = [notes[ni][3].lower() if lang == "en" else notes[ni][3] for ni in keyed]
    ops = A.align(ref, hyp)
    # 每个音归哪个单位：对上的（一样 / 近似 / 不一样都算 —— 修过的工程里位置就是对的）；没对上的音、拖音、接续 → 前一个单位
    owner = [None] * len(notes)
    matched_ref = set()
    for i, j, kind in ops:
        if i is not None and j is not None:
            owner[keyed[j]] = ref_unit[i]
            matched_ref.add(i)
    last = None
    for ni in range(len(notes)):
        if owner[ni] is None:
            owner[ni] = last
        else:
            last = owner[ni]
    span = {}
    for ni, (on, du, _c, _ly) in enumerate(notes):
        u = owner[ni]
        if u is None:
            continue
        a, b = span.get(u, (on, on + du))
        span[u] = (min(a, on), max(b, on + du))
    # 下一个单位开始前收住（拖音的尾巴不压到下一个字上）
    order = sorted(span)
    for x, y in zip(order, order[1:]):
        a, b = span[x]
        span[x] = (a, min(b, span[y][0]))
    n_ok = sum(1 for i, j, k in ops if i is not None and j is not None and k == "一样")
    return {"span": span, "对上的键": len(matched_ref), "参考的键": len(ref), "完全一样的": n_ok, "有字的音": len(keyed)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("svp")
    ap.add_argument("lyrics")
    ap.add_argument("out")
    ap.add_argument("--language", default="auto", choices=["auto", "zh", "en", "ja"])
    ap.add_argument("--track", default=None)
    a = ap.parse_args()
    raw = pathlib.Path(a.lyrics).read_text(encoding="utf-8")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    lang = detect(raw) if a.language == "auto" else a.language
    units = {"zh": units_zh, "ja": units_ja, "en": units_en}[lang](lines)
    d = C.load_svp(a.svp)
    track, notes = sung_track(d, a.track)
    t = timing(notes, units, lang)
    out_lines, skipped = [], []
    for li, ln in enumerate(lines):
        us = [(ui, u) for ui, u in enumerate(units) if u["行"] == li]
        timed = [(ui, u) for ui, u in us if ui in t["span"]]
        if not timed:
            skipped.append({"行": li + 1, "文字": ln})
            continue
        items = []
        for ui, u in us:
            s = t["span"].get(ui)
            items.append({"文字": u["文字"], "开始": round(s[0], 3) if s else None, "结束": round(s[1], 3) if s else None})
        out_lines.append({"行": li + 1, "文字": ln, "开始": items and min(x["开始"] for x in items if x["开始"] is not None),
                          "结束": max(x["结束"] for x in items if x["结束"] is not None), "单位": items,
                          "对上": len(timed), "总": len(us)})
    res = {"语言": lang, "工程": str(a.svp), "轨": track, "歌词": str(a.lyrics), "行": out_lines, "没出字幕的行": skipped,
           "统计": {"音": len(notes), **{k: v for k, v in t.items() if k != "span"},
                    "出字幕的行": len(out_lines), "单位": len(units), "有时间的单位": len(t["span"])}}
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    s = res["统计"]
    print(f"{lang}：轨「{track}」{s['音']} 个音；单位 {s['单位']} 个、有时间的 {s['有时间的单位']}；"
          f"出字幕的行 {s['出字幕的行']} / {len(lines)}；键对上 {s['对上的键']} / {s['参考的键']}（完全一样 {s['完全一样的']}）")
    for x in skipped:
        print(f"  没出字幕：第 {x['行']} 行（{len(x['文字'])} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
