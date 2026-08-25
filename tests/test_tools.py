# -*- coding: utf-8 -*-
"""建造顺序第 5 项：工具层的验收测试。

## 验收标准点名的两条

    每个动作有 schema 且能被校验
    任意写入后钩子必然跑（**用故意失败的动作验证**）

第二条是这一层最要紧的不变量。动作可能中途抛异常、可能声称写了却没写、
也可能声称没写却写了。所以钩子的触发条件是**文件真的变了**，
不是动作的自我报告 —— 一个写坏了却没被检查的文件，
正是这个项目最典型的那种安静错误。

## 沙盒

所有会写文件的测试都在《晓风残月》的副本上跑，**真工程一个字节都不碰**。
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
from svagent.agent import budget as BD           # noqa: E402
from svagent.agent import idem as ID             # noqa: E402
from svagent.agent import safewrite as SW        # noqa: E402
from svagent.agent import tools as T             # noqa: E402
from svagent.agent import tree as TR             # noqa: E402

SLUG = "_tools_sandbox"


@pytest.fixture
def proj(tmp_path):
    """《晓风残月》的完整副本 + 自己的 project.json。"""
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
        "title": "工具沙盒", "svp": str(svp), "bpm": src.bpm,
        "form": [[n, b] for n, b in src.form],
        "lyrics": str(d / "lyrics.txt"), "mid": str(mid), "wav": str(wav),
    }, ensure_ascii=False), encoding="utf-8")
    try:
        yield PJ.load(SLUG)
    finally:
        shutil.rmtree(cfg, ignore_errors=True)


# =========================================================================
# 一、schema 与参数校验
# =========================================================================

def test_每个动作都有可用的schema():
    for a in T.ACTIONS:
        assert a.schema.get("type") == "object", a.name
        assert "properties" in a.schema, a.name
        assert a.desc.strip(), f"{a.name} 没写说明 —— 模型看不懂就不会调"
        for k, s in a.schema["properties"].items():
            assert "type" in s or "description" in s, f"{a.name}.{k}"


def test_没接上的动作不导给模型():
    """放一个必然失败的工具进去，只会换来一次浪费的调用。"""
    names = {t["function"]["name"] for t in T.to_mistral_tools()}
    for a in T.ACTIONS:
        assert (a.name in names) == (a.status != T.NEEDS_MODEL), a.name


def test_参数校验会响():
    """只会放行的校验器，比没有校验器更坏。"""
    s = T.BY_NAME["gen_harmony"].schema
    T.validate(s, {"kind": ["低八度"]})                       # 合法
    bad = [
        ({}, "缺少必填"),
        ({"kind": "低八度"}, "应为 array"),
        ({"kind": []}, "至少要"),
        ({"kind": ["八度"]}, "只能是"),
        ({"kind": ["低八度"], "xx": 1}, "不认识的参数"),
    ]
    for params, want in bad:
        with pytest.raises(T.ToolError) as e:
            T.validate(s, params)
        assert want in str(e.value), (params, str(e.value))


def test_数值区间会响():
    s = T.BY_NAME["mix"].schema
    T.validate(s, {"lead_gain": -6.0})
    for params, want in (({"lead_gain": -99}, "不能小于"),
                         ({"lead_gain": 99}, "不能大于"),
                         ({"lead_gain": "响一点"}, "应为 number")):
        with pytest.raises(T.ToolError) as e:
            T.validate(s, params)
        assert want in str(e.value)


def test_布尔不能冒充整数():
    with pytest.raises(T.ToolError):
        T.validate(T.BY_NAME["gen_melody"].schema, {"specs": True})


def test_不存在的动作要报出可用清单():
    with pytest.raises(T.ToolError) as e:
        T.Runner(PJ.load("xiaofeng")).run("gen_masterpiece")
    assert "gen_harmony" in str(e.value)


# =========================================================================
# 二、钩子必然跑 —— 这一项的核心不变量
# =========================================================================

def test_动作失败但写了文件_钩子照样跑(proj, monkeypatch):
    """**验收标准点名的那条。** 用一个写完就抛异常的动作验证。"""
    def 写完就炸(p, params):
        p.lyrics.write_bytes(p.lyrics.read_bytes() + b"x")
        raise RuntimeError("我在写完之后炸了")

    fake = T.Action("炸弹", "测试用", T._obj({}), 写完就炸,
                    ("state", "overlap"))
    monkeypatch.setitem(T.BY_NAME, "炸弹", fake)

    r = T.Runner(proj, deep_metrics=False).run("炸弹")
    assert r.ok is False and "我在写完之后炸了" in r.error
    assert r.changed_files, "文件确实被改了"
    assert {h.name for h in r.hooks} == {"state", "overlap"}, "钩子没跑"
    assert r.node, "失败的写入也要留一个可回退的节点"


def test_动作没写文件就不跑钩子(proj, monkeypatch):
    """钩子看的是文件指纹，不是动作的自我报告。"""
    fake = T.Action("空转", "测试用", T._obj({}),
                    lambda p, params: {"claimed": "我写了！"}, ("state",))
    monkeypatch.setitem(T.BY_NAME, "空转", fake)
    r = T.Runner(proj, deep_metrics=False).run("空转")
    assert r.ok and not r.changed_files and not r.hooks and r.node is None


def test_钩子失败不掩盖_如实报告(proj, monkeypatch):
    """写坏了要看得见。钩子报错不等于动作报错，两个都要如实呈现。"""
    def 写出重叠(p, params):
        d = json.loads(p.svp.read_text(encoding="utf-8-sig"))
        g = d["library"][0]
        ns = g["notes"]
        ns.append(dict(ns[0]))                 # 复制一个 → 必然重叠
        p.svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return {}

    fake = T.Action("造重叠", "测试用", T._obj({}), 写出重叠, ("overlap",))
    monkeypatch.setitem(T.BY_NAME, "造重叠", fake)
    r = T.Runner(proj, deep_metrics=False).run("造重叠")
    assert r.ok is True, "动作本身没抛异常"
    assert r.hooks_ok is False, "但钩子必须报出重叠"
    assert "重叠" in r.hooks[0].detail


# =========================================================================
# 三、写前的三道闸
# =========================================================================

def test_外部改动时拒绝执行(proj, monkeypatch):
    """与第 1 项同一条规矩：不许默默盖掉创作者的手改。"""
    g = SW.Guard(proj.agent_dir / "ledger.json")
    for f in proj.sources:
        if f.exists():
            g.record(f)
    proj.lyrics.write_bytes(proj.lyrics.read_bytes() + b"hand")

    fake = T.Action("会写", "测试用", T._obj({}),
                    lambda p, params: p.svp.write_bytes(b"x"), ())
    monkeypatch.setitem(T.BY_NAME, "会写", fake)
    r = T.Runner(proj, deep_metrics=False).run("会写")
    assert r.ok is False and "被外部改过" in r.error
    assert not r.changed_files, "拒绝之后不许动任何文件"


def test_每个动作之前树上必有可回退节点(proj, monkeypatch):
    fake = T.Action("会写", "测试用", T._obj({}),
                    lambda p, params: p.lyrics.write_bytes(b"new"), ())
    monkeypatch.setitem(T.BY_NAME, "会写", fake)
    t = TR.Tree(proj)
    assert t.head() is None
    r = T.Runner(proj, deep_metrics=False).run("会写")
    nodes = t.nodes()
    assert len(nodes) >= 2, "动作之前应该先有一个基线节点"
    assert nodes[0].action == "autosave"
    t.checkout(nodes[0].id)
    assert proj.lyrics.read_bytes() != b"new", "回退到动作之前"


def test_只读动作不产生节点也不改文件(proj):
    r = T.Runner(proj, deep_metrics=False).run("verify_alignment")
    assert r.ok, r.error
    assert not r.changed_files and r.node is None
    a = r.extra["alignment"]
    assert abs(a["offset_ms"]) <= 10 and a["spread_ms"] <= 5, a


def test_预算用完就抛(proj):
    b = BD.Budget(seconds=300, max_actions=0, stop_file=proj.stop_file)
    with pytest.raises(BD.ActionLimit):
        T.Runner(proj, budget=b).run("verify_alignment")


def test_喊停之后不再执行(proj):
    proj.agent_dir.mkdir(parents=True, exist_ok=True)
    proj.stop_file.write_text("")
    b = BD.Budget(stop_file=proj.stop_file)
    with pytest.raises(BD.Stopped):
        T.Runner(proj, budget=b).run("verify_alignment")


# =========================================================================
# 四、tool_result 必须带数字
# =========================================================================

def test_结果带度量而不只是成功失败(proj, monkeypatch):
    """架构 §2.5 的支点：模型不判断正确性，它只看数字决定下一步。"""
    def 加个音符(p, params):
        d = json.loads(p.svp.read_text(encoding="utf-8-sig"))
        ns = d["library"][0]["notes"]
        n = dict(ns[-1])
        n["onset"] = ns[-1]["onset"] + ns[-1]["duration"] * 4
        ns.append(n)
        p.svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return {}

    fake = T.Action("加音符", "测试用", T._obj({}), 加个音符, ("overlap",))
    monkeypatch.setitem(T.BY_NAME, "加音符", fake)
    r = T.Runner(proj, deep_metrics=False).run("加音符")
    assert r.ok
    assert r.delta["notes"]["change"] == 1, r.delta
    j = r.to_json()
    assert j["delta"]["notes"]["change"] == 1
    assert j["hooks"][0]["name"] == "overlap"


def test_没变的项不进delta():
    """噪声会淹掉信号。"""
    d = T.delta_of({"a": 1, "b": 2}, {"a": 1, "b": 5})
    assert set(d) == {"b"} and d["b"]["change"] == 3


# =========================================================================
# 五、窄逃生口
# =========================================================================

def test_逃生口能改混音器(proj):
    r = T.Runner(proj, deep_metrics=False).run(
        "set_mixer_param", {"track": "和声_低八度",
                            "field": "gainDecibel", "value": -9.0})
    assert r.ok, r.error
    d = json.loads(proj.svp.read_text(encoding="utf-8-sig"))
    got = [t for t in d["tracks"] if t["name"] == "和声_低八度"][0]
    assert got["mixer"]["gainDecibel"] == -9.0
    assert r.extra["notes_unchanged"] is True


def test_逃生口碰不到音符(proj):
    """它窄在这里：碰不到音符 = 碰不到音乐正确性。"""
    before = ID.content_stats(proj.svp)["notes"]
    T.Runner(proj, deep_metrics=False).run(
        "set_mixer_param", {"track": "和声_低八度", "field": "pan", "value": 0.3})
    assert ID.content_stats(proj.svp)["notes"] == before


def test_逃生口拒绝越界字段(proj):
    for field_, want in (("notes", "不在窄逃生口"),
                         ("fx.随便什么.enabled", "未知的 FX")):
        r = T.Runner(proj, deep_metrics=False).run(
            "set_mixer_param",
            {"track": "和声_低八度", "field": field_, "value": 1})
        assert r.ok is False and want in r.error, (field_, r.error)


def test_逃生口对不存在的轨要报出现有轨名(proj):
    r = T.Runner(proj, deep_metrics=False).run(
        "set_mixer_param", {"track": "不存在的轨",
                            "field": "pan", "value": 0.0})
    assert r.ok is False and "主旋律" in r.error


# =========================================================================
# 六、真动作：跑一个最快的写动作，端到端
# =========================================================================

def test_真动作_调教_端到端(proj):
    """跑真的 `tune`，验证整条序列：备份 → 执行 → 钩子 → 节点 → 度量。

    沙盒是成品的副本，调教已经在里面了。所以要**换一个 scale** 才会改出
    不同的内容 —— 否则见下一条。
    """
    r = T.Runner(proj).run("tune", {"scale": 0.6})
    assert r.ok, r.error
    assert r.node, "写动作必须留节点"
    assert any(h.name == "state" for h in r.hooks)
    assert r.metrics_after["tuning_points"] > 0
    t = TR.Tree(proj)
    assert t.node(r.node).action == "tune"
    assert t.node(r.node).params == {"scale": 0.6}


def test_重跑同一个动作不在树上留空节点(proj):
    """2026-08-25 实测发现：`step5_tune` 重写之后**字节完全相同**。

    比第 2 项测到的更强 —— 那里测的是语义幂等，这里是字节级。
    于是执行器判定「文件没变」，不留节点也不跑钩子。**这是对的**：
    一棵长满空节点的树会让「哪一步真的改了东西」变得无法辨认。
    """
    before = SW.digest(proj.svp)
    r = T.Runner(proj, deep_metrics=False).run("tune", {"scale": 1.0})
    assert r.ok, r.error
    assert SW.digest(proj.svp) == before, "沙盒里本来就是 scale=1.0 的调教"
    assert r.node is None and not r.changed_files and not r.hooks
