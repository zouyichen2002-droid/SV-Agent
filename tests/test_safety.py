# -*- coding: utf-8 -*-
"""建造顺序第 1 项的验收测试：原子写 · 哈希校验 · 全套快照 · 可中断 · 超时。

## 这一项为什么必须靠测试验，不能靠跑一遍看

这五件的失败模式**全都是安静的**：

    写到一半崩了      → 文件看起来存在，打开才知道是坏的
    默默盖掉手改      → 没有任何报错，创作者过几天才发现改动没了
    只存改动的文件    → checkout 出一个从未存在过的混合状态
    中途被掐          → 留下半成品，下一轮从坏状态起步

「跑一次看输出」对这五件一律无效 —— 输出全都是正常的。
所以判据必须是断言，而且**每条都要有反向测试**
（`specs/testing-and-acceptance.md` §2「检查会响」）。

## 杀进程那条为什么要重复 20 次

原子性是概率性暴露的：单次成功什么都证明不了，因为杀在无关时刻也会通过。
所以子进程先写好「我开始写了」的信号，父进程再在随机毫秒后杀 ——
把杀点稳定地落在写入窗口里，重复 20 次。
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent.agent import budget as B          # noqa: E402
from svagent.agent import checkpoint as CP     # noqa: E402
from svagent.agent import safewrite as SW      # noqa: E402

OLD = b"OLD" * 400_000          # 1.2 MB
NEW_SIZE = 24 * 1024 * 1024     # 24 MB，写起来够久，杀得进去

CHILD = f"""
import sys, pathlib
sys.path.insert(0, {str(ROOT / "toolkit")!r})
from svagent.agent import safewrite as SW
target, ready = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
data = b"N" * {NEW_SIZE}
ready.write_bytes(b"1")
SW.write_bytes(target, data)
"""


# =========================================================================
# 一、原子写
# =========================================================================

def test_写入过程中被杀_文件绝不是半成品(tmp_path):
    """20 次随机时刻 kill。目标要么是完整旧内容，要么是完整新内容。"""
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    target = tmp_path / "t.bin"
    rng = random.Random(20260823)
    outcomes = {"old": 0, "new": 0}

    for i in range(20):
        target.write_bytes(OLD)
        ready = tmp_path / f"ready{i}"
        proc = subprocess.Popen([sys.executable, str(script),
                                 str(target), str(ready)])
        t0 = time.monotonic()
        while not ready.exists() and time.monotonic() - t0 < 10:
            time.sleep(0.001)
        time.sleep(rng.uniform(0.0, 0.030))
        proc.kill()
        proc.wait(timeout=10)

        data = target.read_bytes()
        if data == OLD:
            outcomes["old"] += 1
        elif len(data) == NEW_SIZE and data == b"N" * NEW_SIZE:
            outcomes["new"] += 1
        else:
            pytest.fail(f"第 {i + 1} 次：目标是半成品，{len(data)} 字节")

    # 握手保证了子进程确实开始写了，所以「结局是旧内容」= 杀在了 replace 之前，
    # 正是要测的那个窗口。一次都没落进去，这条测试就是空跑的。
    print()
    print(f"    20 次随机时刻 kill：完整旧内容 {outcomes['old']} 次，"
          f"完整新内容 {outcomes['new']} 次，半成品 0 次")
    assert outcomes["old"] > 0, f"从没杀进写入窗口，测试无效：{outcomes}"


def test_崩溃残留会被扫出来并清掉(tmp_path):
    """正常情况下临时文件应当是零。非零就是出过事，仪表盘要能看见。"""
    (tmp_path / f"x.svp{SW.TMP_SUFFIX}999").write_bytes(b"half")
    assert len(SW.stale_tmps([tmp_path])) == 1
    assert len(SW.sweep_tmps([tmp_path])) == 1
    assert SW.stale_tmps([tmp_path]) == []


def test_正常写完不留临时文件(tmp_path):
    SW.write_bytes(tmp_path / "a.txt", b"hello")
    assert SW.stale_tmps([tmp_path]) == []


def test_写入失败也要清掉临时文件(tmp_path):
    """异常路径同样不许留残骸 —— 包括 Ctrl-C。"""
    class Boom(bytes):
        pass
    target = tmp_path / "a.bin"
    with pytest.raises(TypeError):
        SW.write_bytes(target, object())     # type: ignore[arg-type]
    assert SW.stale_tmps([tmp_path]) == []


# =========================================================================
# 二、哈希校验
# =========================================================================

@pytest.fixture
def guard(tmp_path):
    return SW.Guard(tmp_path / "ledger.json")


def test_四种状态必须分得开(tmp_path, guard):
    """「没跟踪过」和「没被改过」混成一个 bool，就是假装知道其实不知道的事。"""
    p = tmp_path / "x.svp"
    assert guard.verify(p) == SW.MISSING

    p.write_bytes(b"creator wrote this")
    assert guard.verify(p) == SW.UNTRACKED

    guard.write(p, b"agent wrote this", force=True)
    assert guard.verify(p) == SW.CLEAN

    p.write_bytes(b"creator edited in SynthV")
    assert guard.verify(p) == SW.EXTERNAL

    p.unlink()
    assert guard.verify(p) == SW.MISSING


def test_手改之后写入被拒(tmp_path, guard):
    """这是这一项最核心的一条：**拒绝，不是提醒。**"""
    p = tmp_path / "x.svp"
    guard.write(p, b"v1", force=True)
    hand = "创作者在 SynthV 里改的".encode("utf-8")
    p.write_bytes(hand)

    with pytest.raises(SW.ExternalEdit) as e:
        guard.write(p, b"v2")
    assert "被改过" in str(e.value)
    assert p.read_bytes() == hand, "拒绝之后文件必须原封不动"


def test_force_能强写并重新记账(tmp_path, guard):
    p = tmp_path / "x.svp"
    guard.write(p, b"v1", force=True)
    p.write_bytes(b"hand edited")
    guard.write(p, b"v2", force=True)
    assert p.read_bytes() == b"v2"
    assert guard.verify(p) == SW.CLEAN


def test_账本坏了不许静默放行(tmp_path):
    """账本读不出来时必须退回「不知道」，而不是当成「没被改过」。"""
    led = tmp_path / "ledger.json"
    p = tmp_path / "x.svp"
    g1 = SW.Guard(led)
    g1.write(p, b"v1", force=True)

    led.write_text("{ 这不是 json", encoding="utf-8")
    g2 = SW.Guard(led)
    assert g2.verify(p) == SW.UNTRACKED


def test_账本跨进程有效(tmp_path):
    """agent 重启之后仍然认得出创作者的手改。"""
    led = tmp_path / "ledger.json"
    p = tmp_path / "x.svp"
    SW.Guard(led).write(p, b"v1", force=True)
    assert SW.Guard(led).verify(p) == SW.CLEAN
    p.write_bytes(b"edited")
    assert SW.Guard(led).verify(p) == SW.EXTERNAL


def test_两个Guard实例不许互相盖掉记录(tmp_path):
    """2026-08-24：账本缓存在内存里，后 flush 的那个把前一个的记录整片盖掉。

    `guard_of(proj)` 每次造一个新实例，所以两个实例同时活着是常态。
    缓存 = 又一个「安静地不一致」，正是这一项要防的。
    """
    led = tmp_path / "ledger.json"
    a, b_ = tmp_path / "a.svp", tmp_path / "b.svp"
    a.write_bytes(b"A")
    b_.write_bytes(b"B")

    g1, g2 = SW.Guard(led), SW.Guard(led)      # 同时活着
    g1.record(a)
    g2.record(b_)                              # 缓存版会在这里丢掉 a
    assert g1.verify(a) == SW.CLEAN, "g2 的写入把 g1 记的 a 冲掉了"
    assert g2.verify(b_) == SW.CLEAN


def test_同长度的改动也要抓到(tmp_path, guard):
    """按内容哈希，不按大小。改一个字节也算改。"""
    p = tmp_path / "x.svp"
    guard.write(p, b"AAAA", force=True)
    p.write_bytes(b"AAAB")
    assert guard.verify(p) == SW.EXTERNAL


def test_大文件的指纹不读内容但小文件读(tmp_path):
    small = tmp_path / "s.bin"
    small.write_bytes(b"x" * 100)
    assert SW.fingerprint(small) == SW.digest(small)

    big = tmp_path / "b.bin"
    big.write_bytes(b"x" * (SW.HASH_MAX_BYTES + 1))
    assert SW.fingerprint(big) != SW.digest(big)
    assert ":" in SW.fingerprint(big)


# =========================================================================
# 三、全套快照
# =========================================================================

def _song(tmp_path):
    a, b_, c = (tmp_path / n for n in ("lyrics.txt", "x.svp", "big.wav"))
    a.write_bytes(b"lyrics v1")
    b_.write_bytes(b"svp v1")
    c.write_bytes(b"W" * 2_000_000)
    return [a, b_, c]


def test_快照是全套_回滚不产生混合状态(tmp_path):
    """只改一个文件，回滚必须把**所有**文件恢复到当时的样子。"""
    files = _song(tmp_path)
    st = CP.Store(tmp_path / ".cp")
    st.snapshot(files, label="第一版")

    files[0].write_bytes(b"lyrics v2")
    files[1].write_bytes(b"svp v2")
    st.restore("c001")
    assert files[0].read_bytes() == b"lyrics v1"
    assert files[1].read_bytes() == b"svp v1"


def test_相同内容只存一份(tmp_path):
    """33 MB 的伴奏不会因为拍了十次快照就变成 330 MB。"""
    files = _song(tmp_path)
    st = CP.Store(tmp_path / ".cp")
    st.snapshot(files)
    n1, b1 = st.blob_count(), st.blob_bytes()
    for _ in range(5):
        st.snapshot(files)
    assert st.blob_count() == n1, "内容没变，blob 数不该涨"
    assert st.blob_bytes() == b1


def test_只有变了的内容才新增blob(tmp_path):
    files = _song(tmp_path)
    st = CP.Store(tmp_path / ".cp")
    st.snapshot(files)
    n1 = st.blob_count()
    files[0].write_bytes(b"lyrics v2")
    st.snapshot(files)
    assert st.blob_count() == n1 + 1


def test_回滚会删掉当时不存在的文件(tmp_path):
    """留着它等于回到一个「当时没有、现在有」的状态 —— 正是全套要防的。"""
    files = _song(tmp_path)
    later = tmp_path / "伴奏.mid"
    st = CP.Store(tmp_path / ".cp")
    st.snapshot(files + [later])          # later 此刻不存在

    later.write_bytes(b"mid v1")
    st.restore("c001")
    assert not later.exists()


def test_回滚之后账本要跟上(tmp_path):
    """否则下一次写入会把 agent 自己回滚出来的内容误判成创作者手改。"""
    files = _song(tmp_path)
    g = SW.Guard(tmp_path / "ledger.json")
    st = CP.Store(tmp_path / ".cp", guard=g)
    for f in files:
        g.record(f)
    st.snapshot(files)

    files[1].write_bytes(b"svp v2")
    assert g.verify(files[1]) == SW.EXTERNAL
    st.restore("c001")
    assert g.verify(files[1]) == SW.CLEAN


# -------------------------------------------------------------------------
# 2026-08-24 创作者实跑暴露的两个「安静地丢东西」：
#   一、--adopt 吞掉了「这个文件被外部改过」的信号，一个字都没说
#   二、--restore 无声地冲掉了创作者当时的版本，而它从没被快照存过
# 不变量：**任何可能丢失当前内容的操作之前，必须先有一张快照。**
# -------------------------------------------------------------------------

def _proj(tmp_path, monkeypatch):
    """一个最小的真项目 —— autosnap 要靠 proj.sources 和 proj.agent_dir。"""
    from svagent import project as PJ
    ly, svp = tmp_path / "lyrics.txt", tmp_path / "x.svp"
    ly.write_bytes(b"lyrics v1")
    svp.write_bytes(b"svp v1")
    proj = PJ.SongProject(
        slug="t_safe", title="t", lyrics=ly, svp=svp, bpm=66.0,
        form=[("主歌1", 8)], mid=tmp_path / "x.mid", wav=tmp_path / "x.wav")
    monkeypatch.setattr(type(proj), "agent_dir",
                        property(lambda s: tmp_path / ".agent"))
    monkeypatch.setattr(type(proj), "sources",
                        property(lambda s: [s.lyrics, s.svp]))
    return proj


def test_回滚之前必须先存下当前状态(tmp_path, monkeypatch):
    """创作者在 SynthV 里改的东西，不许被一条 --restore 无声冲掉。"""
    import svagent.agent.safety as SF
    proj = _proj(tmp_path, monkeypatch)
    SF.store_of(proj).snapshot(proj.sources, label="原版")

    hand = "创作者在 SynthV 里改的".encode("utf-8")
    proj.svp.write_bytes(hand)
    snap, touched = SF.rollback(proj, "c001")

    assert proj.svp.read_bytes() == b"svp v1", "回滚要生效"
    # 关键：他那个版本必须还找得回来
    SF.store_of(proj).restore(snap.cid)
    assert proj.svp.read_bytes() == hand, f"{snap.cid} 里没存住创作者的版本"


def test_采纳外部改动必须如实报告并先拍快照(tmp_path, monkeypatch):
    """--adopt 是唯一销毁「被外部改过」这个信号的操作，所以它必须先说清楚。"""
    import svagent.agent.safety as SF
    proj = _proj(tmp_path, monkeypatch)
    g = SF.guard_of(proj)
    for f in proj.sources:
        g.record(f)

    proj.svp.write_bytes(b"hand edited")
    ext, snap, n = SF.adopt(proj)

    assert ext == [proj.svp], "必须指名是哪个文件被改过"
    assert snap is not None, "采纳之前必须先拍快照"
    assert n == 2
    assert g.verify(proj.svp) == SW.CLEAN


def test_没有外部改动时adopt不白拍快照(tmp_path, monkeypatch):
    import svagent.agent.safety as SF
    proj = _proj(tmp_path, monkeypatch)
    ext, snap, _n = SF.adopt(proj)
    assert ext == [] and snap is None


def test_blob不见了要报错而不是悄悄跳过(tmp_path):
    files = _song(tmp_path)
    st = CP.Store(tmp_path / ".cp")
    m = st.snapshot(files)
    h = m.files[str(files[0])]["hash"]
    st._blob_path(h).unlink()
    files[0].write_bytes(b"changed")
    with pytest.raises(FileNotFoundError):
        st.restore("c001")


def test_临时文件不算进blob统计(tmp_path):
    files = _song(tmp_path)
    st = CP.Store(tmp_path / ".cp")
    st.snapshot(files)
    n = st.blob_count()
    junk = st._blobs / "aa" / f"deadbeef{SW.TMP_SUFFIX}"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"half")
    assert st.blob_count() == n


# =========================================================================
# 四、可中断 + 超时
# =========================================================================

def test_停止文件优先于一切(tmp_path):
    """创作者的意思优先于任何预算数字。"""
    stop = tmp_path / B.STOP_NAME
    bud = B.Budget(seconds=0.0, max_actions=0, stop_file=stop)
    stop.write_text("")
    with pytest.raises(B.Stopped):
        bud.check()


def test_三种退出分开报(tmp_path):
    """混成一个「跑完了」，就分不清「做完了」和「被掐了」。"""
    stop = tmp_path / B.STOP_NAME
    with pytest.raises(B.TimedOut):
        B.Budget(seconds=0.0, max_actions=8, stop_file=stop).check()
    with pytest.raises(B.ActionLimit):
        B.Budget(seconds=300, max_actions=0, stop_file=stop).check()
    stop.write_text("")
    with pytest.raises(B.Stopped):
        B.Budget(seconds=300, max_actions=8, stop_file=stop).check()


def test_预算够的时候不打断(tmp_path):
    bud = B.Budget(seconds=300, max_actions=8, stop_file=tmp_path / B.STOP_NAME)
    for _ in range(8):
        bud.check()
        bud.spend()
    with pytest.raises(B.ActionLimit):
        bud.check()


def test_动作数只在做完之后记(tmp_path):
    """中途崩了不算，否则一个失败的动作会白吃一格预算。"""
    bud = B.Budget(stop_file=tmp_path / B.STOP_NAME)
    bud.check()
    assert bud.n_actions == 0
    bud.spend()
    assert bud.n_actions == 1


def test_收工要清掉停止文件(tmp_path):
    """否则下一轮一起手就被上一次的停止掐死。"""
    stop = tmp_path / B.STOP_NAME
    stop.write_text("")
    bud = B.Budget(stop_file=stop)
    assert bud.clear_stop() is True
    assert not stop.exists()
    assert bud.clear_stop() is False


def test_三种退出都是同一个基类(tmp_path):
    """循环要能一把捞住「正常出口」，而不是把它们当异常错误处理。"""
    for exc in (B.Stopped, B.TimedOut, B.ActionLimit):
        assert issubclass(exc, B.BudgetExhausted)


def test_状态给仪表盘的字段齐全(tmp_path):
    s = B.Budget(stop_file=tmp_path / B.STOP_NAME).status()
    for k in ("elapsed", "remaining", "n_actions", "max_actions",
              "stop_requested", "stop_file"):
        assert k in s
