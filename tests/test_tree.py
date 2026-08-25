# -*- coding: utf-8 -*-
"""建造顺序第 3 项：会话树的验收测试。

## 验收标准点名的三条

    建 3 分支 → 逐个 checkout → state.inspect() 与当时一致
    journal 行数单调增
    同一 wav 在 blobs 里只存一份

前两条在这里测。第三条第 1 项已经测过（`test_相同内容只存一份`），
这里再从树的角度测一次 —— 因为树会拍很多快照，去重失效的代价在这一层才显现。

## 这一层最容易出的错

**切回旧节点时状态只恢复一半。** 表现是：`.svp` 是旧的、`lyrics.txt` 是新的，
文件都能打开、SynthV 照样能唱，但这个组合**从未真实存在过**。
所以每个 checkout 之后都要逐文件比对，不能只看 `.svp`。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import project as PJ              # noqa: E402
from svagent.agent import safewrite as SW      # noqa: E402
from svagent.agent import tree as TR           # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """一个最小项目：三个源文件都在临时目录里。"""
    ly, svp, mid = (tmp_path / n for n in ("lyrics.txt", "x.svp", "x.mid"))
    ly.write_bytes(b"lyrics v0")
    svp.write_bytes(b"svp v0")
    mid.write_bytes(b"mid v0")
    p = PJ.SongProject(slug="t_tree", title="t", lyrics=ly, svp=svp, bpm=66.0,
                       form=[("主歌1", 8)], mid=mid, wav=tmp_path / "x.wav")
    monkeypatch.setattr(type(p), "agent_dir",
                        property(lambda s: tmp_path / ".agent"))
    monkeypatch.setattr(type(p), "sources",
                        property(lambda s: [s.lyrics, s.svp, s.mid]))
    return p


def _state(p: PJ.SongProject) -> dict:
    """全套文件的内容指纹 —— 「状态」在这一层就是这个。"""
    return {f.name: SW.digest(f) for f in p.sources}


# =========================================================================
# 提交与分支
# =========================================================================

def test_节点必须有可读标签(proj):
    """一堆 n0041 对创作者毫无意义 —— 架构文档 §6.5 的硬要求。"""
    t = TR.Tree(proj)
    with pytest.raises(TR.TreeError):
        t.commit("   ")


def test_分支是隐式的(proj):
    """没有 branch 命令：HEAD 不在叶子上时提交，自然长出分支。"""
    t = TR.Tree(proj)
    base = t.commit("基线")
    proj.svp.write_bytes(b"svp A")
    a = t.commit("方案 A")

    t.checkout(base.id)                  # 回到基线
    proj.svp.write_bytes(b"svp B")
    b_ = t.commit("方案 B")

    assert a.parent == base.id and b_.parent == base.id
    assert {n.id for n in t.children(base.id)} == {a.id, b_.id}
    assert t.head() == b_.id


def test_journal行数单调增(proj):
    """只追加的可测形式。修订也是追加，不是改写。"""
    t = TR.Tree(proj)
    counts = [t.n_lines()]
    n1 = t.commit("一")
    counts.append(t.n_lines())
    t.label(n1.id, "改个名")
    counts.append(t.n_lines())
    t.verdict(n1.id, TR.REJECTED, "太满了")
    counts.append(t.n_lines())
    assert counts == sorted(counts) and len(set(counts)) == len(counts), counts


def test_改名和裁决不改写历史那一行(proj):
    """原始那条记录必须一字不变地留在日志里。"""
    t = TR.Tree(proj)
    n1 = t.commit("原名")
    first = t.journal_path.read_text(encoding="utf-8").splitlines()[0]
    t.label(n1.id, "新名")
    t.verdict(n1.id, TR.ACCEPTED)
    assert t.journal_path.read_text(encoding="utf-8").splitlines()[0] == first
    assert json.loads(first)["label"] == "原名"
    assert t.node(n1.id).label == "新名"          # 重放之后是新的


# =========================================================================
# checkout —— 这一项最容易只恢复一半
# =========================================================================

def test_三个分支逐个checkout状态都要与当时一致(proj):
    """验收标准点名的那一条。**逐文件比对，不能只看 svp。**"""
    t = TR.Tree(proj)
    base = t.commit("基线")
    want = {}

    for tag in ("A", "B", "C"):
        t.checkout(base.id)
        proj.svp.write_bytes(f"svp {tag}".encode())
        proj.lyrics.write_bytes(f"lyrics {tag}".encode())
        proj.mid.write_bytes(f"mid {tag}".encode())
        nd = t.commit(f"方案 {tag}")
        want[nd.id] = _state(proj)

    for nid, snap in want.items():
        t.checkout(nid)
        assert _state(proj) == snap, f"{nid} 恢复出来的状态和当时不一样"
        assert t.head() == nid


def test_切走之前会自动保存未提交的改动(proj):
    """一次 checkout 不许无声冲掉还没提交的东西 —— 与第 1 项同源的不变量。"""
    t = TR.Tree(proj)
    base = t.commit("基线")
    proj.svp.write_bytes("还没提交的改动".encode("utf-8"))
    hand = _state(proj)

    t.checkout(base.id)
    assert proj.svp.read_bytes() == b"svp v0"

    auto = [n for n in t.nodes() if n.action == "autosave"]
    assert len(auto) == 1, "没有自动保存那个节点"
    t.checkout(auto[0].id)
    assert _state(proj) == hand, "自动保存的节点没存住那份改动"


def test_干净的时候checkout不产生多余节点(proj):
    t = TR.Tree(proj)
    a = t.commit("一")
    proj.svp.write_bytes(b"svp B")
    t.commit("二")
    n_before = len(t.nodes())
    t.checkout(a.id)
    assert len(t.nodes()) == n_before, "状态与 HEAD 一致时不该再存一份"


def test_is_dirty认得出手改(proj):
    t = TR.Tree(proj)
    t.commit("基线")
    assert t.is_dirty() is False
    proj.lyrics.write_bytes("创作者改的".encode("utf-8"))
    assert t.is_dirty() is True


# =========================================================================
# 裁决 = 否决记忆的写入口
# =========================================================================

def test_裁决只收两个值(proj):
    t = TR.Tree(proj)
    n1 = t.commit("一")
    with pytest.raises(TR.TreeError):
        t.verdict(n1.id, "maybe")


def test_被否决的分支带着原话留下来(proj):
    """每个 rejected 节点就是一条负样本 —— 否决记忆的数据结构。"""
    t = TR.Tree(proj)
    n1 = t.commit("重生成副歌", action="gen_melody",
                  params={"scope": ["副歌1"]},
                  spec_snapshot={"调": "G 小调", "音区": [59, 76]})
    t.verdict(n1.id, TR.REJECTED, "太满了")

    bad = t.rejected()
    assert len(bad) == 1
    assert bad[0].verdict_note == "太满了"
    assert bad[0].spec_snapshot["调"] == "G 小调", "规格特征没留住，否决无法泛化"


def test_对不存在的节点操作要报错(proj):
    t = TR.Tree(proj)
    for fn in (lambda: t.node("n9999"),
               lambda: t.label("n9999", "x"),
               lambda: t.verdict("n9999", TR.ACCEPTED),
               lambda: t.checkout("n9999")):
        with pytest.raises(TR.TreeError):
            fn()


# =========================================================================
# 健壮性
# =========================================================================

def test_日志坏了要报错而不是带着半部历史继续跑(proj):
    t = TR.Tree(proj)
    t.commit("一")
    t.journal_path.write_text(
        t.journal_path.read_text("utf-8") + "{ 这不是 json\n", encoding="utf-8")
    with pytest.raises(TR.TreeError):
        t.nodes()


def test_很多快照也不该把磁盘吃光(proj):
    """树会拍很多快照。内容没变时增量必须是 0。"""
    t = TR.Tree(proj)
    t.commit("一")
    b1 = t.store.blob_bytes()
    for i in range(8):
        t.checkout(t.nodes()[0].id)
        t.commit(f"重复 {i}")
    assert t.store.blob_bytes() == b1, "内容一样却涨了 blob"


def test_画出来的树要标出HEAD和裁决(proj):
    t = TR.Tree(proj)
    base = t.commit("基线")
    proj.svp.write_bytes(b"A")
    a = t.commit("方案 A")
    t.verdict(a.id, TR.REJECTED, "太满了")
    t.checkout(base.id)
    proj.svp.write_bytes(b"B")
    t.commit("方案 B")

    s = t.ascii()
    assert "← HEAD" in s and s.count("← HEAD") == 1
    assert "✗" in s and "太满了" in s
    assert "方案 A" in s and "方案 B" in s


# =========================================================================
# 集成：验收标准的原话是「state.inspect() 与当时一致」，不是「文件一致」。
# 用《晓风残月》的副本跑一遍真的观察函数 —— 沙盒里做，真工程不碰。
# =========================================================================

def test_真项目上三分支checkout后state_inspect与当时一致(tmp_path):
    """建 3 分支 → 逐个 checkout → `state.inspect()` 逐步一致。

    比文件哈希更严的地方在于：它走的是创作者真正看见的那个函数。
    只恢复一半的状态在这里会表现为「某一步的证据对不上」。
    """
    from svagent.agent import state as ST

    src = PJ.load("xiaofeng")
    d = tmp_path / "song"
    d.mkdir()
    svp, mid, wav = d / "t.svp", d / "t_伴奏.mid", d / "t_伴奏.wav"
    shutil.copyfile(src.lyrics, d / "lyrics.txt")
    for s, t_ in ((src.svp, svp), (src.mid, mid), (src.wav, wav)):
        if s.exists():
            shutil.copyfile(s, t_)

    slug = "_tree_sandbox"
    cfg = PJ.SONGS / slug
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "project.json").write_text(json.dumps({
        "title": "树沙盒", "svp": str(svp), "bpm": src.bpm,
        "form": [[n, b] for n, b in src.form],
        "lyrics": str(d / "lyrics.txt"), "mid": str(mid), "wav": str(wav),
    }, ensure_ascii=False), encoding="utf-8")

    def observe(p):
        st = ST.inspect(p)
        return [(s.n, s.done, tuple(s.evidence), tuple(s.blockers))
                for s in st.steps]

    try:
        p = PJ.load(slug)
        t = TR.Tree(p)
        base = t.commit("基线")
        want = {}
        for tag, edit in (("删了一句歌词", lambda: p.lyrics.write_bytes(
                              p.lyrics.read_bytes()[:-40])),
                          ("动了伴奏 MIDI", lambda: p.mid.write_bytes(
                              p.mid.read_bytes() + b"\x00")),
                          ("挪走了伴奏音频", lambda: p.wav.unlink())):
            t.checkout(base.id)
            edit()
            nd = t.commit(tag)
            want[nd.id] = (tag, observe(p))

        assert len({json.dumps(v[1], default=str) for v in want.values()}) == 3, \
            "三个分支观察结果居然一样 —— 这个测试没造出差异，等于空跑"

        for nid, (tag, snap) in want.items():
            t.checkout(nid)
            assert observe(p) == snap, f"{nid}（{tag}）恢复后 state.inspect() 不一致"
    finally:
        shutil.rmtree(cfg, ignore_errors=True)
