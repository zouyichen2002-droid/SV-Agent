# -*- coding: utf-8 -*-
"""规格层：**段落音区的宽度**，判据锚在 593 首真歌上。

## 为什么单独有这个文件

《月亮不靠岸》做完时八项检查 0 finding、七个指标 7/7，但创作者说
「我并不满意」。拿 POP909 的 593 首真歌一比才看出来：

    每句极差中位   真歌 p10 5.0 / 中位 8.5     我们 3.0 —— 第 0.3 百分位

根因是 `_register_for` 里一个 `min`：副歌起点贴着主歌顶端，
再加 9–11 个半音必然撞天花板，于是被截成 4–6。实测副歌音区
**只有 3 个半音宽**，八句的句内极差全是 3。

**当时 286 个测试全绿。** 因为没有一条在看音区有多宽 ——
既有测试查的是幂等、不重叠、检查会响这些性质，
而「副歌只有 3 个半音」在这些性质上完全合法。

## 判据为什么是「宽度优先于抬升」

抬升少 2 个半音，听感是「副歌没起来」；
宽度少 6 个半音，听感是「念经」。后者严重得多，所以撞天花板时
整体下移而不是压缩宽度。
"""
from __future__ import annotations

import random
import statistics as st
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent.compose import spec as SP            # noqa: E402

N_SEEDS = 500
# 星尘舒适音域 57–78（事实 F02）。两端各留 1 个半音的余量
VOICE_LO, VOICE_HI = 57, 78
# 真歌的每句极差 p10 = 5.0（593 首，见 out/pop909_survey.json）。
# 一句要能走出 5 个半音，音区至少得有那么宽 —— 这是下限不是目标
MIN_SPAN = 9


def registers(n=N_SEEDS):
    return [SP._register_for(0, random.Random(s)) for s in range(n)]


# =========================================================================
# 宽度：这次的主症
# =========================================================================

def test_两段的音区宽度都不低于下限():
    """**副歌被截成 3 个半音那次的回归测试。**"""
    bad = []
    for i, r in enumerate(registers()):
        for name, (lo, hi) in r.items():
            if hi - lo < MIN_SPAN:
                bad.append((i, name, hi - lo))
    assert not bad, (f"{len(bad)} 处音区窄于 {MIN_SPAN} 个半音，"
                     f"前几个：{bad[:5]}")


def test_副歌不比主歌窄():
    """副歌是全曲情绪最高的地方，**没有理由比主歌憋屈**。"""
    bad = [(i, r) for i, r in enumerate(registers())
           if (r["副歌"][1] - r["副歌"][0]) < (r["主歌"][1] - r["主歌"][0]) - 2]
    assert not bad, f"{len(bad)} 次副歌比主歌窄 2 个半音以上：{bad[:3]}"


# =========================================================================
# 抬升：不能为了宽度把它牺牲光
# =========================================================================

def test_副歌中心确实高于主歌():
    """宽度优先不等于抬升可以是 0 —— 那样「副歌不够爆」就没救了。"""
    lifts = [((r["副歌"][0] + r["副歌"][1]) / 2
              - (r["主歌"][0] + r["主歌"][1]) / 2) for r in registers()]
    assert min(lifts) >= 3, f"最小抬升只有 {min(lifts)}"
    assert st.median(lifts) >= 5, f"抬升中位只有 {st.median(lifts)}"


# =========================================================================
# 边界：不能唱到声库舒适区外面
# =========================================================================

def test_不越出声库舒适区():
    """星尘 57–78（事实 F02）。**越界不会报错，只会唱得难听。**"""
    bad = []
    for i, r in enumerate(registers()):
        for name, (lo, hi) in r.items():
            if lo < VOICE_LO + 1 or hi > VOICE_HI - 1:
                bad.append((i, name, lo, hi))
    assert not bad, f"{len(bad)} 处越出 {VOICE_LO+1}–{VOICE_HI-1}：{bad[:5]}"


def test_同一个种子出同样的音区():
    """可复现是这条链的基本要求。"""
    a = SP._register_for(0, random.Random(123))
    b = SP._register_for(0, random.Random(123))
    assert a == b


# =========================================================================
# 反向：把旧的截断塞回去，上面的判据必须报出来
# =========================================================================

def test_注入旧的天花板截断必须报出来(monkeypatch):
    """**这条证明上面那些判据不是摆设。**

    旧实现：`chorus_hi = min(chorus_lo + 9..11, 76)`，副歌起点贴着
    主歌顶端，于是宽度被截。塞回去之后，宽度判据必须炸。
    """
    def old(key_root, rng):
        lo_floor, hi_ceil = 59, 76
        verse_lo = rng.choice([lo_floor, lo_floor + 1, lo_floor + 2])
        verse_hi = min(verse_lo + rng.choice([9, 10, 11]), hi_ceil - 4)
        chorus_lo = rng.choice([verse_hi - 2, verse_hi - 1, verse_hi])
        chorus_hi = min(chorus_lo + rng.choice([9, 10, 11]), hi_ceil)
        return {"主歌": (verse_lo, verse_hi), "副歌": (chorus_lo, chorus_hi)}

    monkeypatch.setattr(SP, "_register_for", old)
    with pytest.raises(AssertionError, match="窄于"):
        test_两段的音区宽度都不低于下限()


def test_真歌的下限没有被写错():
    """`MIN_SPAN` 是照真歌 p10 定的。**这个常数写错，整套判据就偏了**，
    所以把出处钉在这里：593 首真歌的每句极差 p10 = 5.0，
    音区至少要能容下它。"""
    survey = ROOT / "out" / "pop909_survey.json"
    if not survey.exists():
        pytest.skip("pop909_survey.json 不在（数据集不进仓库）")
    import json
    rows = json.loads(survey.read_text(encoding="utf-8"))
    good = [r for r in rows if r.get("n_lines", 0) >= 10
            and r.get("line_len_median") and 5 <= r["line_len_median"] <= 20]
    vals = sorted(r["contour_line"] for r in good if r.get("contour_line"))
    p10 = vals[int(len(vals) * .10)]
    assert p10 <= MIN_SPAN, (
        f"真歌 p10 是 {p10}，而 MIN_SPAN 只有 {MIN_SPAN} —— 下限定低了")
