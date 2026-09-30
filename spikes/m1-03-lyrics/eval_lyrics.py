# -*- coding: utf-8 -*-
"""M1-03：一份扒谱结果（带歌词的 .mid / .svp）的歌词对不对 —— 两把尺子：

1. 对创作者给的歌词：按拼音全局对齐（lyric_align），数一样 / 近似 / 不一样 / 多出来的音 / 没地方放的字
2. 对终稿：起音对上的音里歌词一样的（compare_notes 的口径）；音符的 F1 一起报，看改歌词有没有把音弄坏

必须在 vocal2midi 环境里跑（要它的汉字 → 拼音）：
    E:/sv-agent-data/envs/vocal2midi/Scripts/python.exe eval_lyrics.py <结果.mid 或 .svp::轨名> [<歌词.txt>]
"""
from __future__ import annotations

import collections
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, "E:/sv-agent-data/tools/Vocal2Midi")
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
import clean_lyrics as L  # noqa: E402
import compare_notes as C  # noqa: E402
import lyric_align as A  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
FINAL = "F:/我的云端硬盘/临时文件3/SV2/傍晚(星尘).svp"
LYRICS = "E:/sv-agent-data/learn/01-傍晚/lyrics_原文.txt"
SKIP = ("-", "", "+", "la")


def text_pinyin(path: str) -> tuple[list[str], list[str]]:
    from inference.LyricFA.tools.ZhG2p import ZhG2p
    g = ZhG2p("mandarin")
    chars, pys = [], []
    for ln in L.clean_lines(open(path, encoding="utf-8").read()):
        p = g.convert(ln).split()
        assert len(p) == len(ln), f"拼音和字数对不上：{ln} → {p}"
        chars += list(ln)
        pys += p
    return chars, pys


def load(arg: str) -> list:
    path, _, name = arg.partition("::")
    tr = C.midi_tracks(path) if path.lower().endswith((".mid", ".midi")) else C.tracks(C.load_svp(path))
    return sorted(tr[name] if name else list(tr.values())[0])


def evaluate(notes: list, lyrics_path: str = LYRICS) -> dict:
    chars, pys = text_pinyin(lyrics_path)
    sung = [n for n in notes if n[3] not in SKIP]
    ops = A.align(pys, [n[3] for n in sung])
    cnt = collections.Counter(k for *_, k in ops)
    m = C.compare(C.tracks(C.load_svp(FINAL))["vocal1"], notes)
    return {"音数": len(notes), "带字的音": len(sung), "歌词字数": len(pys),
            "对你的歌词": {"一样": cnt["一样"], "近似": cnt["近似"], "不一样": cnt["不一样"],
                       "多出来的音（歌词里没有）": cnt["只在B"], "没地方放的字": cnt["只在A"]},
            "对终稿": {"音符 F1": m["F1"], "起音 F1": m["起音 F1"],
                     "歌词一样的 / 起音对上的": f"{m['歌词一样的']} / {m['歌词都有的配对']}"}}


if __name__ == "__main__":
    notes = load(sys.argv[1])
    for k, v in evaluate(notes, sys.argv[2] if len(sys.argv) > 2 else LYRICS).items():
        print(f"  {k}：{v}")
