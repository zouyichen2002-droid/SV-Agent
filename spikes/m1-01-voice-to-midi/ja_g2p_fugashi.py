# -*- coding: utf-8 -*-
"""pyopenjtalk 的替身（v3 阶段 3，2026-10-01）：日语歌词的读音用 fugashi + unidic-lite 查。

Vocal2Midi 的日语歌词（LyricFA/tools/JaG2p.py）只用 pyopenjtalk.run_frontend(文本) 返回的每个词的两项：
string（原文）和 pron（片假名读音，长音写「ー」）。Windows 上没有现成的 pyopenjtalk 包；
本机 G:/miniconda/envs/tts-indextts2 里有现成的 fugashi（MeCab）+ unidic-lite，同是 Python 3.11 —— 不用下载。

UniDic 的 pron 和 OpenJTalk 的 pron 是同一类东西（发音形：助词「は」→ ワ、东京 → トーキョー），
参考歌词和听写出来的字都过同一个替身，对齐时两边一致。

    import ja_g2p_fugashi; ja_g2p_fugashi.install()      # 之后 import pyopenjtalk 拿到的就是它
"""
from __future__ import annotations

import os
import sys
import types

DEFAULT_SITE = "G:/miniconda/envs/tts-indextts2/Lib/site-packages"
# unidic-lite 和 OpenJTalk 读法不一样、唱的时候一定是后者的（10-01 自检抓到：私 → ワタクシ）
SUNG = {"私": "ワタシ"}
_tagger = None


def _load(site: str):
    """只从那个环境借 fugashi 和 unidic_lite 两个包：路径临时放最后（本环境有的包优先），借完拿掉。"""
    global _tagger
    if _tagger is not None:
        return _tagger
    if not os.path.isdir(os.path.join(site, "fugashi")) or not os.path.isdir(os.path.join(site, "unidic_lite")):
        raise RuntimeError(f"{site} 里没有 fugashi / unidic_lite（日语歌词要用）")
    sys.path.append(site)
    try:
        import fugashi                                           # noqa: F401
        import unidic_lite
        _tagger = fugashi.Tagger(f'-d "{unidic_lite.DICDIR}"')
    finally:
        sys.path.remove(site)
    return _tagger


def _pron(word) -> str:
    if word.surface in SUNG:
        return SUNG[word.surface]
    f = word.feature
    p = getattr(f, "pron", None)
    if not p or p == "*":
        p = getattr(f, "kana", None)
    return "" if not p or p == "*" else str(p)


def run_frontend(text: str, site: str = DEFAULT_SITE) -> list[dict]:
    tagger = _load(site)
    return [{"string": w.surface, "pron": _pron(w)} for w in tagger(text)]


def g2p(text: str, kana: bool = True, site: str = DEFAULT_SITE) -> str:
    return "".join(d["pron"] or d["string"] for d in run_frontend(text, site))


def install(site: str | None = None) -> None:
    site = site or os.environ.get("SV_JA_G2P_SITE") or DEFAULT_SITE
    _load(site)                                                  # 装不上当场报错，不留到唱到日语那一段
    mod = types.ModuleType("pyopenjtalk")
    mod.run_frontend = lambda text, *_a, **_k: run_frontend(text, site)
    mod.g2p = lambda text, kana=True, *_a, **_k: g2p(text, kana, site)
    mod.__doc__ = "fugashi + unidic-lite 做的 pyopenjtalk 替身（ja_g2p_fugashi.py）"
    sys.modules["pyopenjtalk"] = mod


def selftest() -> list[str]:
    """自己造的短句（不是哪首歌的歌词）：助词は读ワ、长音写ー、汉字有读音。"""
    want = {"私は": "ワタシワ", "東京": "トーキョー", "歌う": "ウタウ"}
    fails = []
    for text, kata in want.items():
        got = "".join(d["pron"] for d in run_frontend(text))
        if got != kata:
            fails.append(f"{text} → {got}（应 {kata}）")
    return fails


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    fails = selftest()
    print("自检：", "通过" if not fails else fails)
    raise SystemExit(1 if fails else 0)
