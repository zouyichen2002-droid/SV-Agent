# -*- coding: utf-8 -*-
"""参考曲分析的验收 —— **这一层的产出会改写别处的阈值，所以它自己必须先站得住。**

## 为什么这个文件重要

`reference.py` 算出来的分布，是用来推翻 `metrics.py` 里那些阈值的。
如果它算错了，后果不是「少一个功能」，是**把整套判据往错的方向搬**。

所以判据集中在两件事：

1. **和我们自己那套用的是同一个实现**（`chord_fit_ratios`）——
   两个实现算同一件事，迟早算出两个不同的数而且两边都不报错
2. **切句方式不同这件事必须暴露在数据里**，不能埋掉。
   我们按歌词行切，POP909 只能按休止切；`measure()` 一并报出句数与句长，
   就是为了让「可比不可比」是可检查的，而不是靠我在文档里保证
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import reference as RF               # noqa: E402
from svagent.compose.checks import Note, Phrase   # noqa: E402

POP909 = Path(r"E:\潮声回响\POP909-Dataset-master\POP909-Dataset-master\POP909")
needs_data = pytest.mark.skipif(
    not POP909.exists(), reason="POP909 不在这台机器上")


# =========================================================================
# 不依赖数据集的部分
# =========================================================================

@pytest.mark.parametrize("name,pc", [
    ("C", 0), ("C#", 1), ("Db", 1), ("D", 2), ("E", 4),
    ("F#", 6), ("Gb", 6), ("A", 9), ("Bb", 10), ("B", 11)])
def test_音名解析(name, pc):
    assert RF._pitch_class(name) == pc


def test_不认识的音名返回None而不是瞎猜():
    """**猜一个音级出来，会让整首歌的和弦贴合度悄悄算错。**"""
    assert RF._pitch_class("H") is None
    assert RF._pitch_class("") is None


@pytest.mark.parametrize("q,expect", [
    ("maj", "major"), ("maj7", "major"), ("7", "major"), ("sus4", "major"),
    ("min", "minor"), ("min7", "minor"), ("dim", "minor")])
def test_和弦性质归到三和弦(q, expect):
    """七和弦/挂留归到最近的三和弦。**有损，但注释里写明了为什么可接受。**"""
    assert RF._quality(q) == expect


def test_和弦贴合用的是同一个实现():
    """**这条是这个文件的核心。**

    `measure()` 必须调 `compose.checks.chord_fit_ratios`，
    不能自己再写一遍。自己写一遍的话，真歌的 0.74 和我们的 0.70
    就不是同一个东西算出来的 —— 而「对比」正是这个模块存在的全部理由。
    """
    import inspect
    src = inspect.getsource(RF.measure)
    assert "chord_fit_ratios" in src
    # 而且必须是从 compose.checks 导入的那个
    assert RF.chord_fit_ratios.__module__.endswith("compose.checks")


def test_分布给的是分位不是一个数():
    """阈值落在哪个分位是取舍，**不该由这个模块替创作者定死**。"""
    rows = [{"contour_line": float(v)} for v in range(1, 101)]
    d = RF.distribution(rows, ("contour_line",))["contour_line"]
    assert set(d) >= {"n", "min", "p10", "p25", "median", "p75", "p90", "max"}
    assert d["n"] == 100 and d["min"] == 1.0
    assert d["p10"] < d["median"] < d["p90"]


def test_空输入不炸也不假装有值():
    assert RF.distribution([], ("contour_line",))["contour_line"] is None


def test_音符太少时明说而不是给0():
    ref = RF.Ref(id="t", source="test", notes=[])
    assert RF.measure(ref)["error"]


# =========================================================================
# 依赖数据集
# =========================================================================

@needs_data
def test_读得出一首歌():
    ref = RF.load_pop909(POP909 / "001")
    assert ref.notes and ref.phrases and ref.lines
    assert ref.key and ref.bpm
    assert ref.n_accomp > 0, "PIANO 轨没读到 —— 伴奏密度就无从比较"


@needs_data
def test_旋律轨不能和伴奏轨搞混():
    """**MELODY 是人声旋律，PIANO 是伴奏。** 拿错轨的话，
    「真歌的旋律有多起伏」会变成「真歌的钢琴有多起伏」，
    数字照样出得来，而且看起来完全合理。"""
    ref = RF.load_pop909(POP909 / "001")
    assert len(ref.notes) < ref.n_accomp, (
        "旋律音符比伴奏还多 —— 大概率读错了轨")


@needs_data
def test_切句结果与我们的歌同量级():
    """**这条是「可比性」的凭据，不是文档里的一句保证。**

    我们的歌是 20 句 / 每句 9 字。POP909 按休止切，如果切出来是
    3 句或者每句 100 音，那 `contour_line` 就没法跟我们的比。
    """
    m = RF.measure(RF.load_pop909(POP909 / "001"))
    assert 10 <= m["n_lines"] <= 60, f"切出 {m['n_lines']} 句，不在合理范围"
    assert 4 <= m["line_len_median"] <= 20, (
        f"句长中位 {m['line_len_median']} 音，与我们的 9 字不同量级")


@needs_data
def test_跑一批不会因为单首坏掉而中断():
    """**读不了的歌要记下来，不能静默跳过** —— 少算几首会让分布偏移。"""
    rows = RF.survey(POP909, limit=5)
    assert len(rows) == 5
    assert all("id" in r for r in rows)
