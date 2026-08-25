# -*- coding: utf-8 -*-
"""建造顺序第 8 项：诊断层的验收测试。

## 验收标准点名的两条

    三个诉求各有一个**已知答案**的场景，诊断必须指对层
    **置信度低时必须问，而不是猜**

架构文档 §4 特别强调第二条比准确率重要：
「一个会说『我不确定』的诊断层是可用的，一个自信瞎猜的不是。」

所以这份测试里，**「它拒绝回答」的用例比「它答对了」的用例还多**。
那不是覆盖不足，那是这一层的设计。

## 已知答案怎么造

在沙盒里人为破坏某一层（压掉副歌音区 / 抹掉音高微调），
然后断言诊断指向那一层。破坏是可控的，所以答案是已知的。
"""
from __future__ import annotations

import json
import shutil
import statistics as st
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import project as PJ                # noqa: E402
from svagent.agent import diagnose as DG         # noqa: E402
from svagent.agent import metrics as MT          # noqa: E402
from svagent.agent import segments as SG         # noqa: E402
from svagent.compose.lyricfile import parse      # noqa: E402

SLUG = "_diag_sandbox"


@pytest.fixture
def proj(tmp_path):
    src = PJ.load("xiaofeng")
    d = tmp_path / "song"
    d.mkdir()
    svp = d / "t.svp"
    shutil.copyfile(src.lyrics, d / "lyrics.txt")
    shutil.copyfile(src.svp, svp)
    for a in ("mid", "wav"):
        s = getattr(src, a)
        if s.exists():
            shutil.copyfile(s, d / s.name)
    cfg = PJ.SONGS / SLUG
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "project.json").write_text(json.dumps({
        "title": "诊断沙盒", "svp": str(svp), "bpm": src.bpm,
        "form": [[n, b] for n, b in src.form],
        "lyrics": str(d / "lyrics.txt"),
        "mid": str(d / src.mid.name), "wav": str(d / src.wav.name),
    }, ensure_ascii=False), encoding="utf-8")
    try:
        yield PJ.load(SLUG)
    finally:
        shutil.rmtree(cfg, ignore_errors=True)


def _edit(p, fn):
    d = json.loads(p.svp.read_text(encoding="utf-8-sig"))
    fn(d)
    p.svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _lead_group(d):
    lib = {g["uuid"]: g for g in d["library"]}
    tr = next(t for t in d["tracks"] if t["name"].startswith("主旋律"))
    return lib[tr["groups"][0]["groupID"]]


def _spans(p):
    vs, _ = parse(p.lyrics)
    return SG.spans(vs[next(iter(vs))])


def _drop_chorus(p):
    """已知答案：把副歌压回主歌音区 → 病在**旋律层**。"""
    sp = {s.name: s for s in _spans(p)}

    def fn(d):
        g = _lead_group(d)
        ns = sorted(g["notes"], key=lambda n: n["onset"])
        verse = [s for k, s in sp.items() if k.startswith("主歌")]
        vmed = st.median(n["pitch"] for s in verse for n in ns[s.i0:s.i1])
        for k, s in sp.items():
            if not k.startswith("副歌"):
                continue
            seg = ns[s.i0:s.i1]
            shift = int(round(st.median(n["pitch"] for n in seg) - vmed))
            for n in seg:
                n["pitch"] -= shift
        g["notes"] = ns
    _edit(p, fn)


def _strip_pitchdelta(p):
    """已知答案：抹掉音高微调 → 病在**调教层**。"""
    def fn(d):
        for g in d["library"]:
            (g.get("parameters") or {}).pop("pitchDelta", None)
    _edit(p, fn)


# =========================================================================
# 一、诉求识别
# =========================================================================

def test_三类诉求认得出来():
    assert DG.intent_of("副歌不够爆") == DG.CHORUS_WEAK
    assert DG.intent_of("听着有点机械") == DG.MECHANICAL
    assert DG.intent_of("太像上一首了") == DG.SIMILAR


def test_认不出来就返回None_不硬套最近的():
    """硬套一个最近的意图 = 自信瞎猜，正是这一层要避免的。"""
    for c in ("总觉得哪儿不对", "再改改", "", "副歌不够爆而且太像上一首"):
        assert DG.intent_of(c) is None, c


# =========================================================================
# 二、指对层（验收判据第一条）
# =========================================================================

def test_副歌被压平时诊断指向旋律层(proj):
    """已知答案：我亲手压掉了副歌音区。"""
    assert MT.collect(proj)                       # 破坏前基线可读
    _drop_chorus(proj)

    d = DG.diagnose(proj, "副歌不够爆")
    assert not d.should_ask, d.ask
    assert d.hypotheses, "指标明明坏了却没提假设"
    top = d.hypotheses[0]
    assert top.layer == "旋律", f"指错层了：{top.layer}"
    assert top.metric == "contour_lift"
    assert top.action == "adjust_spec"


def test_抹掉音高微调时诊断指向调教层(proj):
    """已知答案：我亲手删了 pitchDelta。"""
    _strip_pitchdelta(proj)

    d = DG.diagnose(proj, "听着有点机械")
    assert not d.should_ask, d.ask
    top = d.hypotheses[0]
    assert top.layer == "调教", f"指错层了：{top.layer}"
    assert top.metric == "pitch_delta_density"
    assert top.action == "tune"


def test_太像上一首要先问参照曲(proj):
    """**没有参照就判不了**。这一类只能问，第一版不猜。"""
    d = DG.diagnose(proj, "太像上一首了")
    assert d.should_ask and ("参照" in d.ask)


# =========================================================================
# 三、不确定就问（验收判据第二条，比准确率更重要）
# =========================================================================

def test_指标全过时拒绝猜测(proj):
    """《晓风残月》七个指标全过。这时候说「是旋律的问题」就是瞎猜。"""
    for c in ("副歌不够爆", "听着有点机械"):
        d = DG.diagnose(proj, c)
        assert d.should_ask, f"{c} 指标全过却给了假设"
        assert "指标看不出问题" in d.ask
        assert not d.hypotheses


def test_认不出的诉求要问而不是硬猜(proj):
    d = DG.diagnose(proj, "总觉得哪儿不对")
    assert d.should_ask and d.intent is None
    assert DG.SIMILAR in d.ask, "要告诉创作者第一版只敢诊断哪三类"


def test_两个原因分不开时要问(proj):
    """置信度 = 1 − 第二偏离/最偏离。两个偏一样多 → 0 → 必须问。"""
    _drop_chorus(proj)

    def flat_loudness(d):
        g = _lead_group(d)
        pts = g["parameters"]["loudness"]["points"]
        g["parameters"]["loudness"]["points"] = [
            v if i % 2 == 0 else 0.0 for i, v in enumerate(pts)]
    _edit(proj, flat_loudness)

    d = DG.diagnose(proj, "副歌不够爆", floor=0.5)
    assert d.confidence is not None and d.confidence < 0.5, d.confidence
    assert d.should_ask and "不猜" in d.ask


def test_只有一个指标偏离时置信度是满的(proj):
    _drop_chorus(proj)
    d = DG.diagnose(proj, "副歌不够爆")
    assert d.confidence == 1.0 and not d.should_ask


def test_提案在要问的时候明确说不动手(proj):
    d = DG.diagnose(proj, "总觉得哪儿不对")
    assert "不打算动手" in DG.plan(d)


def test_提案要写清楚改哪层依据什么数(proj):
    """看不懂的提案等于没有提案。"""
    _drop_chorus(proj)
    text = DG.plan(DG.diagnose(proj, "副歌不够爆"))
    for must in ("旋律层", "依据", "动作", "adjust_spec", "隔离", "真工程不动"):
        assert must in text, must


# =========================================================================
# 四、并行假设
# =========================================================================

def test_并行试完真工程一个字节没动(proj):
    """**隔离不是为了安全，是为了归因。** 顺带真工程也不会被动。"""
    from svagent.agent import safewrite as SW
    _drop_chorus(proj)
    before = {f.name: SW.digest(f) for f in proj.sources}

    d = DG.diagnose(proj, "副歌不够爆")
    hs = d.hypotheses or [DG.Hypothesis("调教", "dynamic_span", "造一个",
                                        0.5, "tune", {"scale": 1.4})]
    ts = DG.trial(proj, hs, parallel=True)

    assert len(ts) == len(hs)
    assert {f.name: SW.digest(f) for f in proj.sources} == before, \
        "并行试把真工程改了"
    assert not list(PJ.SONGS.glob("_trial_*")), "沙盒没清干净"


def test_退步的假设一律出局():
    """`require_no_regression`：改善不能以别处变坏为代价。"""
    h = DG.Hypothesis("调教", "dynamic_span", "x", 0.5, "tune", {})
    good = DG.Trial(h, True, before=1.0, after=3.0,
                    findings_before=0, findings_after=0)
    bad = DG.Trial(h, True, before=1.0, after=9.0,
                   findings_before=0, findings_after=5)
    assert bad.regressed and not good.regressed
    assert DG.pick([bad, good]) is good, "涨得多但退步的不许当选"


def test_改善不够就一个都不选():
    """`min_improvement`。宁可什么都不做，也不做一个看不出差别的改动。"""
    h = DG.Hypothesis("调教", "dynamic_span", "x", 0.5, "tune", {})
    tiny = DG.Trial(h, True, before=1.0, after=1.05,
                    findings_before=0, findings_after=0)
    assert DG.pick([tiny], min_improvement=0.15) is None


def test_跑不通的假设不参与排序():
    h = DG.Hypothesis("调教", "dynamic_span", "x", 0.5, "tune", {})
    broken = DG.Trial(h, False, error="炸了")
    assert DG.pick([broken]) is None
    assert "跑不通" in DG.report_trials([broken])


def test_并排报告要标出谁退步了():
    h = DG.Hypothesis("旋律", "contour_lift", "x", 0.5, "adjust_spec", {})
    t = DG.Trial(h, True, before=1.0, after=6.0,
                 findings_before=0, findings_after=3)
    s = DG.report_trials([t])
    assert "退步" in s and "出局" in s and "真工程未动" in s
