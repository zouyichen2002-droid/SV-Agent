# -*- coding: utf-8 -*-
"""M1-03：创作者给的歌词 → 只剩要唱的字（去掉标题、段落标签、标点）。

创作者 09-29：「翻唱的时候我会主动和你说歌词，这样你就可能主动去修改歌词」。粘过来的歌词常带
《标题》、主歌 / 副歌 / 桥段 / 尾声 这类段落标签和「——」—— 这些不是要唱的字，不去掉会被当歌词对进去。

规则：整行是《…》的去掉；整行只是一个段落标签的去掉（中英文常见的都认，也认「副歌1」「[Chorus]」这种）；
其余每行留汉字和英文词，标点、空格、破折号都不算字。保留分行（一行 ≈ 一句）。

    python clean_lyrics.py <歌词.txt>    → 打印清理后的每一行和总字数
"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
SECTION = re.compile(r"^[\[\(（【]?\s*(前奏|主歌|预副歌|导歌|副歌|桥段|间奏|尾声|结尾|独白|rap|说唱|"
                     r"intro|verse|pre-?chorus|chorus|bridge|interlude|outro|hook)\s*[0-9一二三四五AaBb]*\s*[\]\)）】]?\s*[:：]?\s*$",
                     re.I)


def clean_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or re.fullmatch(r"《[^》]*》", s) or SECTION.match(s):
            continue
        kept = "".join(re.findall(r"[㐀-䶿一-鿿]|[A-Za-z']+", s))
        if kept:
            out.append(kept)
    return out


def selftest() -> list[str]:
    sample = "《测试》\n主歌\n春天 来了\n[Chorus]\n副歌2：\n花开 满园——  \nVerse 1\n小河 流水\n"
    got = clean_lines(sample)
    want = ["春天来了", "花开满园", "小河流水"]
    return [] if got == want else [f"清理不对：{got}（应 {want}）"]


if __name__ == "__main__":
    fails = selftest()
    print("自检：", "通过" if not fails else fails)
    if fails:
        raise SystemExit(1)
    lines = clean_lines(open(sys.argv[1], encoding="utf-8").read())
    for ln in lines:
        print(f"  {len(ln):2d} 字  {ln}")
    print(f"共 {len(lines)} 行、{sum(len(l) for l in lines)} 字")
