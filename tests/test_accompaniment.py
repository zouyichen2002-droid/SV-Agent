# -*- coding: utf-8 -*-
"""伴奏生成器的编排判据 —— **这些是听得出来但测不出来的东西**。

## 为什么现在才有这个文件

《风筝线》验收之后创作者说「鼓声伴奏很奇怪」。拆开一看是三处编排硬伤：
主歌 18 个小节只有一条镲（没有底鼓，跟不上拍）、副歌每小节都撞一下叮叮
（而且时值 3.8 拍几乎占满整格）、全曲零加花。

**当时 236 个测试全绿。** 因为没有一条在看伴奏的实际内容 ——
既有的测试查的是幂等、不重叠、不越界这些结构性质，
而「每小节都撞镲」在结构上完全合法。

修完之后又栽了一次：`sec` 是 dict，第一版写成 `enumerate(sec)`，
拿到的是键不是段名，于是每个小节都被判成段落起点 ——
叮叮照旧每小节响、加花一次都轮不到，**241 个测试仍然全绿**。
是把输出数字拉出来比对才发现的。

所以这个文件存在的理由只有一条：**让编排错误也能被测试抓到。**
每条判据都配一条「注入这个缺陷 → 必须报出来」。
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "toolkit"))

import make_accompaniment as MA        # noqa: E402
import step4_accompaniment as S4       # noqa: E402

KICK, CLAP, HAT, OPENHAT, RIDE = 36, 39, 42, 46, 51
# C 小调的 i–VI–III–VII
PROG = [(0, "minor"), (8, "major"), (3, "major"), (10, "major")]


def make_song(form=None, drum_pick=None):
    form = form or json.loads(
        (ROOT / "songs" / "zhuimeng" / "project.json").read_text(encoding="utf-8")
    )["form"]
    secs, b = [], 0
    for name, nb in form:
        secs.append((name, b, [("", "", PROG[i % 4]) for i in range(nb // 2)]))
        b += nb
    song = S4.Song(secs, 0, "minor", 66.0, b)
    song.DRUM_PICK = drum_pick or {"hat": "hat-8", "build": "backbeat",
                                   "full": "hat-16", "none": "none"}
    return song


def drums_by_bar(parts):
    out = collections.defaultdict(set)
    for t, _d, m, _v in parts["鼓"]:
        out[int(t // 4)].add(m)
    return out


@pytest.fixture(scope="module")
def built():
    song = make_song()
    parts, _ch, sec = MA.build_parts(song)
    return song, parts, sec


# =========================================================================
# 音区：低频不许两个持续声部挤在一起
# =========================================================================

def test_低音与和声垫不重叠(built):
    """手册：「低频区两个同时发声的音至少隔一个纯五度」。

    旧表 bass 36–48、pad 41–55 重叠 7 个半音 —— 那是「低频糊成一团」的来源。
    """
    _song, parts, _sec = built
    bass = [m for _t, _d, m, _v in parts["贝斯"]]
    pad = [m for _t, _d, m, _v in parts["垫"]]
    assert min(pad) > max(bass), (
        f"和声垫最低 {min(pad)} 没高过低音最高 {max(bass)} —— 低频会糊")


def test_各声部依次向上不交叉(built):
    """贝斯 < 垫 < 琶音。交叉了就说明分带表被改坏了。"""
    _song, parts, _sec = built
    lo = {k: min(m for _t, _d, m, _v in v)
          for k, v in parts.items() if v and k != "鼓"}
    assert lo["贝斯"] < lo["垫"] < lo["琶音"]


def test_分带表本身不许重叠():
    """**直接验表**，不经过生成。表错了，每一首歌都错。"""
    b = MA.BANDS
    assert b["bass"][1] < b["pad"][0], "bass 与 pad 的频段带重叠"
    assert b["pad"][1] < b["arp"][0], "pad 与 arp 的频段带重叠"


# =========================================================================
# 鼓：三处硬伤各配一条
# =========================================================================

def test_有鼓的小节都得有底鼓或拍手(built):
    """**创作者「跟不上拍」的那条。**

    手册的检验法是「跟着打拍子，打不下去的地方就是烂的」——
    光一条镲，人听不出第 1 拍在哪。旧版这样的小节有 18 个。
    """
    _song, parts, _sec = built
    bad = [b for b, ks in drums_by_bar(parts).items()
           if HAT in ks and KICK not in ks and CLAP not in ks]
    assert not bad, f"{len(bad)} 个小节只有镲，没有底鼓也没有拍手：{bad[:8]}"


def test_叮叮只在段落起点(built):
    """镲是**段落起点的重音**，不是每小节的常驻件。旧版 16 次，每小节一下。"""
    _song, parts, sec = built
    starts = {b for b in sec if b == 0 or sec[b - 1] != sec[b]}
    hits = [b for b, ks in drums_by_bar(parts).items() if RIDE in ks]
    assert hits, "一次叮叮都没有 —— 段落起点失去了标记"
    off = [b for b in hits if b not in starts]
    assert not off, f"{len(off)} 次叮叮不在段落起点：{off[:8]}"


def test_叮叮次数远少于小节数(built):
    """就算都落在起点，数量也该是个位数。**这条是上一条的独立佐证** ——
    段落判断整体错位时，上一条可能被绕过去。"""
    _song, parts, _sec = built
    n_ride = sum(1 for _t, _d, m, _v in parts["鼓"] if m == RIDE)
    n_bars = len(drums_by_bar(parts))
    assert n_ride <= n_bars // 4, f"叮叮 {n_ride} 次 / {n_bars} 小节，太密了"


def test_有加花而且落在乐句末(built):
    """手册：加花 3–4 小节一次，用来推情绪。旧版一次都没有。"""
    _song, parts, _sec = built
    fills = [t for t, _d, m, _v in parts["鼓"]
             if m == CLAP and 3.2 <= (t % 4) < 4.0]
    assert fills, "全曲零加花 —— 两段逐小节相同，机械"
    assert all((t % 4) >= 3.0 for t in fills), "加花不在小节的第 4 拍上"


def test_十六分镲要分级给力度(built):
    """**全一样响就是机器打的。** 参考曲实测正拍 15%、反拍 10%。"""
    _song, parts, _sec = built
    vels = {v for _t, _d, m, v in parts["鼓"] if m == HAT}
    assert len(vels) >= 3, f"闭镲只有 {len(vels)} 种力度：{sorted(vels)}"


# =========================================================================
# 反向：把缺陷塞回去，上面的判据必须报出来
# =========================================================================

def test_注入每小节撞镲必须报出来(monkeypatch):
    """把段落判断打回「每个小节都是起点」—— 正是那个 dict/list 的 bug。

    注入必须**精准**：第一版把段名换成 `seg0/seg1`，结果连密度查表都不匹配，
    一个鼓音符都没生成，n_ride=0 反而让判据看起来没抓到。
    **注入错了地方的反向测试，跟没有反向测试一样。**
    所以这里交替用两个真段名 —— 密度照样解析成「副歌」，但每小节都换段。
    """
    song = make_song()
    monkeypatch.setattr(
        MA, "section_map",
        lambda mod: {b: ("副歌1" if b % 2 == 0 else "副歌2")
                     for b in range(mod.N_BARS)})
    parts, _ch, _sec = MA.build_parts(song)

    n_ride = sum(1 for _t, _d, m, _v in parts["鼓"] if m == RIDE)
    n_bars = len(drums_by_bar(parts))
    assert n_bars > 0, "注入之后没有鼓 —— 注入点选错了，这条测不到东西"
    assert n_ride > n_bars // 4, "注入了缺陷，叮叮却没变密 —— 判据抓不到它"


def test_注入没底鼓的鼓型必须报出来(monkeypatch):
    """把 hat 档改回「底鼓拍为空」，那 18 个小节就该回来。"""
    song = make_song()
    monkeypatch.setitem(MA.DRUM_STYLES, "hat-8", ((), (), 0.5, False))
    parts, _ch, _sec = MA.build_parts(song)
    bad = [b for b, ks in drums_by_bar(parts).items()
           if HAT in ks and KICK not in ks and CLAP not in ks]
    assert bad, "注入了缺陷，却没有出现「只有镲」的小节 —— 判据是摆设"


def test_注入分带重叠必须报出来(monkeypatch):
    """把 pad 拉回旧值，重叠判据必须炸。"""
    monkeypatch.setitem(MA.BANDS, "pad", (41, 55))
    with pytest.raises(AssertionError, match="重叠"):
        test_分带表本身不许重叠()


# =========================================================================
# 同位置同音高不许有两个音符
# =========================================================================

def test_鼓没有重影音符(built):
    """**加花撞上常驻律动那次的回归测试。**

    第一版把加花的第一下放在 3.0 拍，而 backbeat 的拍手本来就在 3.0 ——
    同一位置同一音高写了两个音符。step4 自己的回读复验报了「Drums 不一致」，
    但那条信息藏在一大段输出里，很容易当成环境问题划过去。
    这里把它变成一条独立、直白的判据。
    """
    seen = collections.Counter((round(t, 4), m)
                               for t, _d, m, _v in parts_of(built)["鼓"])
    dup = [k for k, n in seen.items() if n > 1]
    assert not dup, f"{len(dup)} 处重影（同位置同音高两个音符）：{dup[:6]}"


def test_所有声部都没有重影音符(built):
    _song, parts, _sec = built
    for name, notes in parts.items():
        seen = collections.Counter((round(t, 4), m) for t, _d, m, _v in notes)
        dup = [k for k, n in seen.items() if n > 1]
        assert not dup, f"{name} 有 {len(dup)} 处重影：{dup[:4]}"


def parts_of(built):
    _song, parts, _sec = built
    return parts


def test_注入重影必须报出来(monkeypatch):
    """把加花挪回 3.0，重影判据必须炸。"""
    monkeypatch.setattr(MA, "FILL",
                        [(3.0, 0.15, CLAP, 62)] + list(MA.FILL))
    song = make_song()
    parts, _ch, sec = MA.build_parts(song)
    seen = collections.Counter((round(t, 4), m) for t, _d, m, _v in parts["鼓"])
    assert any(n > 1 for n in seen.values()), "注入了重影却没被发现"
