# -*- coding: utf-8 -*-
"""建造顺序第 7 项：两个新指标 + 第九项检查的验收测试。

## 验收标准的原话

    每个指标有敏感度测试（**人为造出「平」必须被测出**）

只会返回「一切正常」的指标，和只报 0 的检查是同一类东西。
所以每个指标都配一条「把它弄平 → 必须报警」的反向测试。

## 更要紧的一条：三个子指标必须**可分离**

架构文档 §6：「音高平」和「力度平」修法不同，合成一个数就无法归因。
所以有两条测试专门造「只有句内平、整体不平」和「只有副歌没抬起来」，
断言**只有对应的那一个指标报警**。分不开的指标对诊断层没有价值。

## 阈值必须让已验收的歌通过

《晓风残月》通过了创作者验收。任何把它判为「太平」的阈值都是错的 ——
那不是严格，是假阳性。所以第一条测试就是基线全绿。
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
sys.path.insert(0, str(ROOT / "scripts"))

from svagent import project as PJ                # noqa: E402
from svagent.agent import metrics as M           # noqa: E402
from svagent.agent import segments as SG         # noqa: E402
from svagent.compose.checks import (CheckCfg, Note, Phrase,   # noqa: E402
                                    check_chord_fit, chord_fit_ratios)
from svagent.compose.lyricfile import parse      # noqa: E402

SLUG = "_metrics_sandbox"


@pytest.fixture
def proj(tmp_path):
    src = PJ.load("xiaofeng")
    d = tmp_path / "song"
    d.mkdir()
    svp = d / "t.svp"
    shutil.copyfile(src.lyrics, d / "lyrics.txt")
    shutil.copyfile(src.svp, svp)
    cfg = PJ.SONGS / SLUG
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "project.json").write_text(json.dumps({
        "title": "指标沙盒", "svp": str(svp), "bpm": src.bpm,
        "form": [[n, b] for n, b in src.form],
        "lyrics": str(d / "lyrics.txt"),
        "mid": str(d / "x.mid"), "wav": str(d / "x.wav"),
    }, ensure_ascii=False), encoding="utf-8")
    try:
        yield PJ.load(SLUG)
    finally:
        shutil.rmtree(cfg, ignore_errors=True)


def _by_name(ms):
    return {m.name: m for m in ms}


def _edit_lead(p, fn):
    """就地改主旋律的音符。`fn(notes) -> notes`。"""
    d = json.loads(p.svp.read_text(encoding="utf-8-sig"))
    lib = {g["uuid"]: g for g in d["library"]}
    tr = next(t for t in d["tracks"] if t["name"].startswith("主旋律"))
    g = lib[tr["groups"][0]["groupID"]]
    g["notes"] = fn(sorted(g["notes"], key=lambda n: n["onset"]))
    p.svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _spans(p):
    vs, _ = parse(p.lyrics)
    return SG.spans(vs[next(iter(vs))])


# =========================================================================
# 一、基线必须全绿
# =========================================================================

def test_已验收的歌五项指标全过(proj):
    """《晓风残月》通过了创作者验收。判它「太平」的阈值就是错的。"""
    ms = M.collect(proj)
    bad = [(m.name, m.show()) for m in ms if m.ok is False]
    assert not bad, f"基线被误判：{bad}"
    assert all(m.value is not None for m in ms), "基线上不该有「不知道」"


def test_基线各项都有余量(proj):
    """卡在阈值上的指标等于没有阈值 —— 噪声就能让它翻面。"""
    for m in M.collect(proj):
        assert m.value >= m.threshold * 1.15, \
            f"{m.label} 只有 {m.value}，阈值 {m.threshold}，余量太薄"


# =========================================================================
# 二、敏感度：造「平」必须被测出
# =========================================================================

def test_整首挤在一个音上_全曲极差要报警(proj):
    _edit_lead(proj, lambda ns: [dict(n, pitch=67) for n in ns])
    ms = _by_name(M.collect(proj))
    assert ms["contour_overall"].ok is False, ms["contour_overall"].show()
    assert ms["contour_line"].ok is False


def test_只有句内平时_只有句内那一项报警(proj):
    """**可分离性的关键测试。** 每句压成一个音，但各句音高不同 ——
    整体极差与副歌抬升都保持住，所以只有「每句极差」该报警。
    """
    sp = _spans(proj)

    def flatten(ns):
        """每句压成一个音，然后**把句间差拉开**保住整体极差。

        只压不拉的话整体极差会从 15 掉到 11 —— 那时 `contour_overall`
        报警是**对的**，测不出可分离性。第一版测试就是这么错的。
        """
        out, med = list(ns), st.median(n["pitch"] for n in ns)
        lo = min(n["pitch"] for n in ns)
        hi = max(n["pitch"] for n in ns)
        flat = []
        for s in sp:
            seg = out[s.i0:s.i1]
            flat.append(st.median(n["pitch"] for n in seg) if seg else med)
        f_lo, f_hi = min(flat), max(flat)
        k = (hi - lo) / (f_hi - f_lo) if f_hi > f_lo else 1.0
        for s, m in zip(sp, flat):
            seg = out[s.i0:s.i1]
            if not seg:
                continue
            pitch = int(round(lo + (m - f_lo) * k))
            out[s.i0:s.i1] = [dict(n, pitch=pitch) for n in seg]
        return out

    _edit_lead(proj, flatten)
    ms = _by_name(M.collect(proj))
    assert ms["contour_line"].ok is False, "句内已经平了却没报"
    assert ms["contour_overall"].ok is True, "整体极差不该被误报"
    assert ms["contour_lift"].ok is True, "副歌抬升不该被误报"


def test_只有副歌没抬起来时_只有抬升那一项报警(proj):
    """**可分离性的另一半。** 句内轮廓不动，只把副歌压回主歌音区。"""
    sp = {s.name: s for s in _spans(proj)}
    verse = [s for k, s in sp.items() if k.startswith("主歌")]
    chorus = [s for k, s in sp.items() if k.startswith("副歌")]

    def drop_chorus(ns):
        out = list(ns)
        vmed = st.median(n["pitch"] for s in verse for n in out[s.i0:s.i1])
        for s in chorus:
            seg = out[s.i0:s.i1]
            cmed = st.median(n["pitch"] for n in seg)
            d = int(round(cmed - vmed))
            out[s.i0:s.i1] = [dict(n, pitch=n["pitch"] - d) for n in seg]
        return out

    _edit_lead(proj, drop_chorus)
    ms = _by_name(M.collect(proj))
    assert ms["contour_lift"].ok is False, "副歌没抬起来却没报"
    assert ms["contour_line"].ok is True, "句内轮廓没动，不该报"


def test_响度曲线压平_响度跨度要报警(proj):
    d = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    lib = {g["uuid"]: g for g in d["library"]}
    tr = next(t for t in d["tracks"] if t["name"].startswith("主旋律"))
    g = lib[tr["groups"][0]["groupID"]]
    pts = g["parameters"]["loudness"]["points"]
    g["parameters"]["loudness"]["points"] = [
        v if i % 2 == 0 else 0.5 for i, v in enumerate(pts)]
    proj.svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    ms = _by_name(M.collect(proj))
    assert ms["dynamic_span"].ok is False
    assert ms["dynamic_span"].value == 0.0


def test_没调教过时响度跨度是不知道而不是零(proj):
    """三色，不是两色。**0 dB 是「很平」，没有曲线是「不知道」。**"""
    d = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    for g in d["library"]:
        g.pop("parameters", None)
    proj.svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    m = _by_name(M.collect(proj))["dynamic_span"]
    assert m.value is None and m.ok is None
    assert "不知道" in m.detail


# =========================================================================
# 三、第九项检查
# =========================================================================

def test_贴合度按时长加权而不是按个数():
    """实测的核心结论：按个数会把已验收的歌判出 4 处问题。

    造一句「一个长和弦音 + 三个短经过音」——
    按个数只有 25%，按时长有 80%。它听起来是贴着和弦的。
    """
    notes = [Note(0, 0.0, 3.2, 60, "一"),      # C，长
             Note(1, 3.2, 0.27, 61, "二"),     # 非和弦音，短
             Note(2, 3.47, 0.27, 62, "三"),
             Note(3, 3.74, 0.26, 63, "四")]
    ph = [Phrase(0, 0, 4, chord_root=0, chord_quality="major")]
    ratio = chord_fit_ratios(notes, ph)[0]
    assert ratio > 0.75, f"时长加权算出来只有 {ratio:.0%}"
    assert not check_chord_fit(notes, ph, CheckCfg()), "不该报警"

    by_count = sum(1 for n in notes if n.midi % 12 in (0, 4, 7)) / len(notes)
    assert by_count < 0.30, "按个数确实会误判 —— 这就是不用它的理由"


def test_整句离和声要被检出():
    """全是非和弦音的长音符 —— 必须报。"""
    notes = [Note(i, i * 1.0, 1.0, 61 + i % 2, "字") for i in range(4)]
    ph = [Phrase(0, 0, 4, chord_root=0, chord_quality="major")]
    fs = check_chord_fit(notes, ph, CheckCfg())
    assert len(fs) == 1 and fs[0].kind == "chord_fit"
    assert fs[0].targets == (0, 1, 2, 3), "要指出是哪些音符"


def test_乐句越界要报告而不是崩():
    """检查器崩掉等于没有检查，比漏报更糟（cadence 那次的教训）。"""
    notes = [Note(0, 0.0, 1.0, 60, "一")]
    ph = [Phrase(0, 0, 99, chord_root=0, chord_quality="major")]
    fs = check_chord_fit(notes, ph, CheckCfg())
    assert len(fs) == 1 and "越界" in fs[0].detail


def test_没有和弦标注的乐句跳过():
    notes = [Note(i, i * 1.0, 1.0, 61, "字") for i in range(4)]
    assert check_chord_fit(notes, [Phrase(0, 0, 4)], CheckCfg()) == []


def test_把一句移到调外_八项检查要响(proj):
    """端到端：改真工程里的一句，`check_melody` 必须报出来。"""
    from svagent.agent import state as ST
    assert len(ST.check_melody(proj)) == 0

    sp = {s.name: s for s in _spans(proj)}
    s = sp["副歌1"]

    def off(ns):
        out = list(ns)
        out[s.i0:s.i1] = [dict(n, pitch=n["pitch"] + 1) for n in out[s.i0:s.i1]]
        return out

    _edit_lead(proj, off)
    fs = ST.check_melody(proj)
    assert fs, "整句移半音之后八项检查却全过 —— 检查没响"
