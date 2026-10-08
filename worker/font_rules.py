# -*- coding: utf-8 -*-
r"""字体的死规矩（创作者 10-04：「宋体不行，以后都不要宋体」「定死规矩不要宋体」；创作记忆 g24）。

字幕、标题、署名、封面字一律不用宋体 —— 思源宋体 / Noto Serif、中易宋体 SimSun、华文宋体 / 华文中宋、仿宋、新细明体 / 细明体、
日文的明朝体（Mincho）这一类衬线字都算。出片前查一遍用到的字体名，碰到就报错、不出片（不悄悄换别的字体）。
    python font_rules.py            # 自检
"""
from __future__ import annotations

import re
import sys

SONG = re.compile(r"宋|仿宋|明体|明朝|细明|Song|SimSun|STSong|STZhongsong|FangSong|Serif|Mincho|MingLiU|Ming\b", re.I)


def is_song(name: str | None) -> bool:
    """字体名是不是宋体一类（「Sans Serif」这种无衬线的名字不算）。"""
    n = (name or "").strip()
    if not n or re.search(r"sans", n, re.I):
        return False
    return bool(SONG.search(n))


def check(names, where: str = "") -> None:
    bad = sorted({n.strip() for n in names if is_song(n)})
    if bad:
        raise ValueError(f"不许用宋体（创作者定死的规矩，创作记忆 g24）：{'、'.join(bad)}" + (f"（{where}）" if where else ""))


def ass_fonts(text: str) -> set[str]:
    """ASS 里用到的字体名：样式行的 Fontname + 每句里的 \fn 覆盖。"""
    names = set()
    for line in text.splitlines():
        if line.startswith("Style:"):
            parts = line[6:].split(",")
            if len(parts) > 1:
                names.add(parts[1].strip())
    names |= {m.strip() for m in re.findall(r"\\fn([^\\}]+)", text)}
    return names


def check_ass(text: str, where: str = "") -> None:
    check(ass_fonts(text), where)


def selftest() -> list[str]:
    fails = []
    for n in ("Noto Serif SC", "Noto Serif SC Black SV", "SimSun", "NSimSun", "宋体", "华文中宋", "STZhongsong", "STSong", "FangSong", "仿宋",
              "Source Han Serif SC", "MingLiU", "PMingLiU", "新细明体", "Yu Mincho", "MS Mincho"):
        if not is_song(n):
            fails.append(f"该拦没拦：{n}")
    for n in ("Microsoft YaHei", "ZCOOL KuaiLe", "MaShanZheng", "Yuji Syuku", "Noto Sans SC", "Noto Sans SC Black SV", "Yu Gothic", "Segoe UI",
              "STXingkai", "KaiTi", "STKaiti", "Microsoft Sans Serif", "SimHei", "快乐体", "Aa霸道楷"):
        if is_song(n):
            fails.append(f"不该拦的拦了：{n}")
    ass = "Style: Lyric,Microsoft YaHei,76,&H0\nDialogue: 0,0:00:01.00,0:00:02.00,FX,,0,0,0,,{\\fnNoto Serif SC\\b0}字"
    if ass_fonts(ass) != {"Microsoft YaHei", "Noto Serif SC"}:
        fails.append(f"ASS 里的字体没读对：{ass_fonts(ass)}")
    try:
        check_ass(ass, "自检")
        fails.append("ASS 里有思源宋体却没报错")
    except ValueError:
        pass
    return fails


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    f = selftest()
    print("自检：", "通过" if not f else f)
    raise SystemExit(1 if f else 0)
