# -*- coding: utf-8 -*-
"""建造顺序第 4 项：环境事实清单的验收测试。

## 这一项的失败形态

一份约束清单最典型的坏法不是「写错了」，是**「写下来之后没人再看一眼」**。
半年后 SynthV 升级、mido 换行为、Mistral 放开限流，清单还理直气壮地
写着老一套 —— 和只报 0 的检查是同一类东西。

所以测试盯两件事：

    每条事实都要有出处（learned 不许空）
    能自动复验的，每次跑测试都要真的复验一遍

写这份清单的当天就靠这条抓到一处记错：我一直以为 mido 构造中文轨名就崩，
实际是 `save()` 才崩（见 F08）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent.agent import facts as F          # noqa: E402


def test_编号唯一():
    ids = [f.id for f in F.FACTS]
    assert len(ids) == len(set(ids)), f"编号重复：{ids}"


def test_每条事实都要有出处():
    """没有出处的断言无法被重新验证，也无法判断它什么时候会失效。"""
    for f in F.FACTS:
        assert f.learned.strip(), f"{f.id} 没写怎么学到的"
        assert f.matters.strip(), f"{f.id} 没写不知道会怎样"
        assert f.claim.strip(), f"{f.id} 没写断言"


def test_至少六条硬约束能自动复验():
    """验收标准要求覆盖已知的六条硬约束。**可复验的越多，清单越不容易烂。**"""
    v = [f for f in F.FACTS if f.verifiable]
    assert len(v) >= 6, f"只有 {len(v)} 条可复验：{[f.id for f in v]}"


def test_所有快速复验必须通过():
    """这是这一项的核心断言：清单说的话，现在还是真的。

    顺手把结果落盘 —— 仪表盘读的是报告，自己不跑复验。
    所以「跑一次测试」就等于「刷新一次约束清单面板」。
    """
    rs = F.verify()
    F.save_report(rs)
    bad = [(r.fact.id, r.detail) for r in rs if r.ok is False]
    assert not bad, "这些事实复验失败（环境变了，或者当初就记错了）：" + str(bad)


def test_报告里缺的事实不许当成通过():
    """仪表盘读报告。报告里没有的必须标成「还没复验过」，不是绿灯。"""
    F.save_report([F.Result(F.FACTS[0], True, "ok")])
    try:
        rs = F.results_from_report()
        assert rs[0].ok is True
        assert all(r.ok is None and "还没复验过" in r.detail for r in rs[1:])
    finally:
        F.save_report(F.verify())          # 复原，别让别的测试看到半份报告


def test_没跑的复验要如实标成没跑():
    """跳过的不许混成「通过」—— 灰的就是灰的。"""
    for r in F.verify():
        if r.fact.check is not None and r.fact.cost != F.FAST:
            assert r.ok is None and "未跑" in r.detail, f"{r.fact.id} 状态不诚实"


def test_复验函数自己炸了要报失败而不是崩掉整个体检(monkeypatch):
    """一条复验出错不该让另外十四条都看不到。"""
    def boom():
        raise RuntimeError("模拟环境坏了")

    # 先量一遍没有坏事实时的基准。**不许写死「6 条通过」** ——
    # 那个数取决于当前是哪首歌（新歌没有人声轨时 F02 报「无从复验」），
    # 第二首歌一建出来这条断言就挂了。断言规则，不断言具体数字。
    base = sum(1 for r in F.verify() if r.ok is True)

    bad = F.Fact("FXX", "测试", "假的", "无", "无", boom, F.FAST)
    monkeypatch.setattr(F, "FACTS", F.FACTS + [bad])
    rs = F.verify()
    hit = [r for r in rs if r.fact.id == "FXX"][0]
    assert hit.ok is False and "复验出错" in hit.detail
    assert sum(1 for r in rs if r.ok is True) == base, "别的事实被带崩了"


def test_给模型看的版本要含每条的编号和断言():
    """**agent 读不到就等于没有** —— 这一项存在的全部理由。"""
    s = F.for_prompt()
    for f in F.FACTS:
        assert f.id in s, f"{f.id} 没进模型上下文"
        assert f.claim[:12] in s


def test_facts_md_必须和源同步():
    """加了事实却忘了重新生成 md，就会得到一份过期的清单。"""
    p = ROOT / "specs" / "facts.md"
    assert p.exists(), "specs/facts.md 还没生成，跑 scripts/facts.py --write"
    text = p.read_text(encoding="utf-8")
    for f in F.FACTS:
        assert f"## {f.id}" in text, f"{f.id} 不在 facts.md 里 —— 忘了重新生成"
    assert text.count("\n## F") == len(F.FACTS), "facts.md 的条数对不上"


# -------------------------------------------------------------------------
# 反向测试：复验器必须真的会响，不是永远返回 True
# -------------------------------------------------------------------------

def test_svp版本复验会响(tmp_path, monkeypatch):
    """把模板换成别的版本号，F01 必须报失败。"""
    fake = tmp_path / "songs" / "_template"
    fake.mkdir(parents=True)
    (fake / "empty_v196.svp").write_text(
        '{"version": 187, "library": [], "tracks": [], "time": {}, '
        '"uuid": "x"}', encoding="utf-8")
    monkeypatch.setattr(F, "ROOT", tmp_path)
    ok, detail = F._v_svp_version()
    assert ok is False and "187" in detail


def test_mido复验会响(monkeypatch):
    """如果 mido 哪天能存中文了，F08 必须报失败并提示可以去掉映射。"""
    import mido

    class FakeMidiFile(mido.MidiFile):
        def save(self, *a, **kw):
            return None                       # 假装存成功了

    monkeypatch.setattr(mido, "MidiFile", FakeMidiFile)
    ok, detail = F._v_mido_latin1()
    assert ok is False and "MIDI_NAME" in detail
