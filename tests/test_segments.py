# -*- coding: utf-8 -*-
"""建造顺序第 6 项：按段落取音符 —— `gen_melody(scope)` 与 `pick` 的验收。

## 验收标准点名的两条

    只重生成副歌时，主歌音符**逐字段不变**
    `pick` 后目标段落与源节点**逐字段相同**

两条都是「逐字段」，不是「听起来一样」。所以断言比的是原始 dict，
不是任何归一化之后的东西。

## 为什么这一项是关键

架构文档 §5：**局部修改是归因的前提。** 整首重生成之后，创作者说
「好听了」时无法判断改善来自哪一处 —— 诊断层（第 8 项）就拿不到
可归因的信号，「诊断 → 假设 → 度量」整条链会断。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import project as PJ                # noqa: E402
from svagent import svp_build as SB              # noqa: E402
from svagent.agent import segments as SG         # noqa: E402
from svagent.agent import tools as T             # noqa: E402
from svagent.agent import tree as TR             # noqa: E402
from svagent.compose.lyricfile import parse      # noqa: E402

SLUG = "_seg_sandbox"


@pytest.fixture
def proj(tmp_path):
    src = PJ.load("xiaofeng")
    d = tmp_path / "song"
    d.mkdir()
    svp, mid, wav = d / "t.svp", d / "t_伴奏.mid", d / "t_伴奏.wav"
    shutil.copyfile(src.lyrics, d / "lyrics.txt")
    for s, t_ in ((src.svp, svp), (src.mid, mid), (src.wav, wav)):
        if s.exists():
            shutil.copyfile(s, t_)
    cfg = PJ.SONGS / SLUG
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "project.json").write_text(json.dumps({
        "title": "段落沙盒", "svp": str(svp), "bpm": src.bpm,
        "form": [[n, b] for n, b in src.form],
        "lyrics": str(d / "lyrics.txt"), "mid": str(mid), "wav": str(wav),
    }, ensure_ascii=False), encoding="utf-8")
    try:
        yield PJ.load(SLUG)
    finally:
        shutil.rmtree(cfg, ignore_errors=True)


def _ver(p):
    vs, _ = parse(p.lyrics)
    return vs[next(iter(vs))]


def _lead(p):
    b = SB.read_back(p.svp)
    k = next(x for x in b if x.startswith("主旋律"))
    return sorted(b[k], key=lambda n: n["onset"])


# =========================================================================
# 一、段落归属
# =========================================================================

def test_段落区间必须铺满整首(proj):
    """有缝隙就意味着某些音符不属于任何段落 —— 那些音符谁也改不到。"""
    sp = SG.spans(_ver(proj))
    assert sp[0].i0 == 0
    for a, b in zip(sp, sp[1:]):
        assert a.i1 == b.i0, f"{a.name} 与 {b.name} 之间有缝"
    assert sp[-1].i1 == len(_lead(proj)), "段落总长与工程音符数不一致"


def test_按前缀匹配(proj):
    sp = SG.spans(_ver(proj))
    assert [s.name for s in SG.match(sp, "副歌")] == ["副歌1", "副歌2"]
    assert [s.name for s in SG.match(sp, ["副歌2"])] == ["副歌2"]


def test_一个都没命中要报错(proj):
    """「我改了副歌」和「我什么都没改」必须区分得开。"""
    with pytest.raises(ValueError) as e:
        SG.match(SG.spans(_ver(proj)), "没有这个段")
    assert "副歌1" in str(e.value)


def test_小节范围来自曲式(proj):
    assert SG.bars_of(proj.form, "副歌1") == (17, 24)
    assert SG.bars_of(proj.form, "不存在") is None


# =========================================================================
# 二、拼接
# =========================================================================

def test_区间外的音符是同一个对象(proj):
    """不是「相等」，是**同一个对象** —— 不重新构造就不可能算错。"""
    cur = _lead(proj)
    new = [dict(n, pitch=n["pitch"] + 2) for n in cur]
    out, rep = SG.splice(cur, new, "副歌", _ver(proj), proj.form)
    sp = SG.spans(_ver(proj))
    for s in sp:
        if s.name.startswith("副歌"):
            continue
        for i in range(s.i0, s.i1):
            assert out[i] is cur[i], f"{s.name} 第 {i} 个音符被重新构造了"
    assert rep.n_replaced == 70 and rep.n_kept == 106


def test_新段落会平移到旧起点(proj):
    cur = _lead(proj)
    new = [dict(n, onset=n["onset"] + 12345678) for n in cur]
    out, rep = SG.splice(cur, new, "副歌1", _ver(proj), proj.form)
    sp = {s.name: s for s in SG.spans(_ver(proj))}
    i0 = sp["副歌1"].i0
    assert out[i0]["onset"] == cur[i0]["onset"], "没有对齐到旧起点"
    assert rep.span_delta_beats["副歌1"] == 0.0


def test_跨度变化要报出来(proj):
    """曲式假设不成立时要看得见，而不是变成一处静音或一处重叠。"""
    cur = _lead(proj)
    new = [dict(n, duration=n["duration"] * 2) for n in cur]
    _out, rep = SG.splice(cur, new, "副歌1", _ver(proj), proj.form)
    assert rep.span_delta_beats["副歌1"] > 0


def test_音符数不同要拒绝(proj):
    cur = _lead(proj)
    with pytest.raises(ValueError) as e:
        SG.splice(cur, cur[:-1], "副歌", _ver(proj))
    assert "不同源" in str(e.value)


def test_unchanged_outside_会响(proj):
    """只会返回 True 的判据，比没有判据更坏。"""
    cur = _lead(proj)
    out, _ = SG.splice(cur, [dict(n, pitch=n["pitch"] + 2) for n in cur],
                       "副歌", _ver(proj))
    assert SG.unchanged_outside(cur, out, "副歌", _ver(proj)) is True
    out[0] = dict(out[0], pitch=out[0]["pitch"] + 1)      # 动一下主歌
    assert SG.unchanged_outside(cur, out, "副歌", _ver(proj)) is False


def test_两种载体都能拼(proj):
    """`.svp` 的 dict 与 melodize 的 Note 对象共用同一个拼接实现。"""
    from svagent.compose.checks import Note
    cur = [Note(i, i * 1.0, 1.0, 60, "字") for i in range(176)]
    new = [Note(i, i * 1.0, 1.0, 72, "字") for i in range(176)]
    out, rep = SG.splice(cur, new, "副歌1", _ver(proj), proj.form)
    sp = {s.name: s for s in SG.spans(_ver(proj))}
    s = sp["副歌1"]
    assert all(out[i].midi == 72 for i in range(s.i0, s.i1))
    assert out[0] is cur[0]
    assert rep.n_replaced == s.n_notes


# =========================================================================
# 三、端到端：验收标准的两条原话
# =========================================================================

def test_只重生成副歌时主歌逐字段不变(proj):
    """**验收判据第一条。** 走真的 `gen_melody`，不是直接调 splice。"""
    before = _lead(proj)
    r = T.Runner(proj, deep_metrics=False).run(
        "gen_melody", {"scope": ["副歌"], "specs": 6, "seeds": 2})
    assert r.ok, r.error
    after = _lead(proj)

    changed = {s.name for s in SG.spans(_ver(proj))
               if before[s.i0:s.i1] != after[s.i0:s.i1]}
    assert changed == {"副歌1", "副歌2"}, f"改动范围不对：{changed}"
    assert r.node, "局部重生成也要留节点"
    hl = TR.Tree(proj).node(r.node).metrics_after or {}
    assert hl.get("sections") == ["副歌1", "副歌2"], hl
    assert hl.get("bars", {}).get("副歌1") == [17, 24], hl


def test_pick之后目标段落与源节点逐字段相同(proj):
    """**验收判据第二条。**"""
    t = TR.Tree(proj)
    base = t.commit("原版")
    base_notes = _lead(proj)

    r1 = T.Runner(proj, deep_metrics=False).run(
        "gen_melody", {"scope": ["副歌"], "specs": 6, "seeds": 2})
    assert r1.ok, r1.error
    assert _lead(proj) != base_notes

    r2 = T.Runner(proj, deep_metrics=False).run(
        "pick", {"from_node": base.id, "sections": ["副歌"]})
    assert r2.ok, r2.error

    got = _lead(proj)
    for s in SG.match(SG.spans(_ver(proj)), "副歌"):
        assert got[s.i0:s.i1] == base_notes[s.i0:s.i1], \
            f"{s.name} 与源节点不是逐字段相同"


def test_改了音符就丢弃调教_但不许丢得安静(proj):
    """曲线按时间锚定：音符换了还留着，等于把颤音挂在错的字上 ——
    比丢了更难发现。所以规则是**丢弃**。

    但丢弃必须看得见：`delta` 里要出现 `tuning_points` 从 1224 掉到 0。
    这个项目里「安静地少了点东西」是最贵的一类错误。
    """
    from svagent.agent import idem as ID
    assert ID.content_stats(proj.svp)["tuning_points"] > 0

    r = T.Runner(proj, deep_metrics=False).run(
        "gen_melody", {"scope": ["副歌"], "specs": 4, "seeds": 1})
    assert r.ok, r.error
    assert ID.content_stats(proj.svp)["tuning_points"] == 0
    d = r.delta.get("tuning_points")
    assert d and d["after"] == 0 and d["change"] < 0, \
        f"调教丢了却没进 delta：{r.delta}"


def test_只改和声时主旋律的调教要保住(proj):
    """`--keep-melody` 那条路径音符没变，调教必须原样搬回来。"""
    from svagent.agent import idem as ID
    before = ID.content_stats(proj.svp)["tuning_points"]
    r = T.Runner(proj, deep_metrics=False).run(
        "gen_harmony", {"kind": ["下三度"], "sections": ["副歌"]})
    assert r.ok, r.error
    after = ID.content_stats(proj.svp)["tuning_points"]
    assert after > 0, "主旋律音符没变，调教不该被清空"
    assert after <= before


def test_pick不碰别的轨和混音(proj):
    t = TR.Tree(proj)
    base = t.commit("原版")
    d0 = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    T.Runner(proj, deep_metrics=False).run(
        "gen_melody", {"scope": ["副歌1"], "specs": 4, "seeds": 1})
    T.Runner(proj, deep_metrics=False).run(
        "pick", {"from_node": base.id, "sections": ["副歌1"]})
    d1 = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    for a, b in zip(d0["tracks"], d1["tracks"]):
        if a["name"].startswith("主旋律"):
            continue
        assert a.get("mixer") == b.get("mixer"), f"{a['name']} 的混音被动了"


def test_pick指向不存在的节点要报错(proj):
    r = T.Runner(proj, deep_metrics=False).run(
        "pick", {"from_node": "n9999", "sections": ["副歌"]})
    assert r.ok is False and "n9999" in r.error


def test_局部重生成必须锁在现有调上(proj):
    """2026-08-25 实测：不锁调时把别的调的副歌拼进来，写后钩子当场报
    19 个 finding（其中 scale 13）。锁调之后同样参数 0 finding。

    这条断言的是**结果的调性不变** —— 比断言「findings 为 0」更直接，
    因为 findings 为 0 也可能是候选池碰巧躲开了。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import step3_melody as S3

    before = _lead(proj)
    kr0, kq0, kn0 = S3.infer_key([n["pitch"] for n in before])

    r = T.Runner(proj, deep_metrics=False).run(
        "gen_melody", {"scope": ["副歌"], "specs": 8, "seeds": 2})
    assert r.ok, r.error

    after = _lead(proj)
    kr1, kq1, kn1 = S3.infer_key([n["pitch"] for n in after])
    assert (kr1, kq1) == (kr0, kq0), f"调性从 {kn0} 变成了 {kn1}"


def test_局部重生成后八项检查要过(proj):
    """默认候选池下应当 0 finding。**这是写后钩子的活儿，这里只是钉住它。**"""
    r = T.Runner(proj, deep_metrics=False).run(
        "gen_melody", {"scope": ["副歌"], "specs": 24, "seeds": 3})
    assert r.ok, r.error
    h = next(x for x in r.hooks if x.name == "checks")
    assert h.ok, h.detail
