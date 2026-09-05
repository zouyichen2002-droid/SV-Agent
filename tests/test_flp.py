# -*- coding: utf-8 -*-
"""`.flp` 事件级读写的验收 —— 直写 FL 工程，创作者不再逐条挂音源。

## 地基判据只有一条

**读出来再拼回去必须逐字节相同。** 做不到就说明没读懂这个格式，
后面所有写入都是在拿创作者的工程赌博。PyFLP 2.2.1 正是败在这里：
`test2.flp` 读回写丢 16 字节，`Project_test1.flp` 长度不变但哈希变了。

## 每条检查都配一条「注入缺陷 → 必须报出来」

项目的硬规矩：**只报 0 的检查不算检查。** 所以下面每个不变量都成对出现 ——
一条验正常情况通过，一条把缺陷塞进去验它真的会响。
没有第二条的话，一个永远返回 True 的断言看起来和一个正确的断言一模一样。

## 为什么用真工程而不是构造的样例

配器块（事件 213，最大一块 28494 字节）是 FLEX 与 FPC 的真实状态，
构造不出来也没必要构造。真文件缺席时这些测试**跳过而不是假装通过** ——
灰不是绿，没有依据就不要冒充有依据。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import flp as FL                     # noqa: E402
from svagent import project as PJ                 # noqa: E402
from svagent.agent import tools as TL             # noqa: E402

# 创作者的真工程。**不在时跳过**，不构造替身。
REAL = [Path(r"E:\潮声回响\test2\test2.flp"),
        Path(r"E:\潮声回响\Project_test1\Project_test1.flp")]
HAVE = [p for p in REAL if p.exists()]
TEMPLATE = next((p for p in HAVE if p.name == "test2.flp"), None)
MIDI = Path(r"E:\潮声回响\追逐梦想_伴奏.mid")

needs_real = pytest.mark.skipif(not HAVE, reason="创作者的 FL 工程不在这台机器上")
needs_tmpl = pytest.mark.skipif(TEMPLATE is None, reason="缺 test2.flp 模板")
needs_midi = pytest.mark.skipif(not MIDI.exists(), reason="缺伴奏 MIDI")


# =========================================================================
# 地基：往返
# =========================================================================

@needs_real
@pytest.mark.parametrize("path", HAVE, ids=lambda p: p.name)
def test_往返逐字节相同(path):
    """**整个模块的地基。** 这条过不了，别的都不用看。"""
    raw = path.read_bytes()
    assert FL.read(path).to_bytes() == raw


def test_varint_往返():
    for n in (0, 1, 63, 127, 128, 255, 16383, 16384, 1 << 20):
        buf = FL._put_varint(n)
        assert FL._varint(buf, 0) == (n, len(buf))


def test_事件长度规则():
    """id 决定载荷长度。**这四段边界写错了，解析会整体错位而不报错。**"""
    head = b"FLhd" + struct.pack("<I", 6) + struct.pack("<hHH", 0, 1, 96)
    evs = [(0, b"\x01"), (63, b"\x02"),          # 1 字节
           (64, b"\x03\x04"), (127, b"\x05\x06"),  # 2 字节
           (128, b"\x07" * 4), (191, b"\x08" * 4),  # 4 字节
           (192, b"hello"), (255, b"")]            # varint
    assert FL.parse(FL.build(head, evs)) == (head, evs)


def test_不是flp要报错():
    with pytest.raises(FL.FlpError):
        FL.parse(b"NOTFLP" + b"\x00" * 20)


def test_截断要报错():
    """长度字段说的比实际多 —— **必须当场炸，不许静默少读几个事件。**"""
    head = b"FLhd" + struct.pack("<I", 6) + struct.pack("<hHH", 0, 1, 96)
    good = FL.build(head, [(0, b"\x01")])
    with pytest.raises(FL.FlpError):
        FL.parse(good[:-1])


# =========================================================================
# 读语义
# =========================================================================

@needs_tmpl
def test_读得出音源和音符():
    doc = FL.read(TEMPLATE)
    ins = FL.instruments(doc)
    assert [n for _p, n in ins] == ["Harmo Pad", "Acoustic Bass 1",
                                    "Crystal", "Choir Aahs", "FPC"]
    blob = FL.notes_blob(doc)
    assert FL.n_notes(blob) == 688
    assert FL.channel_counts(blob) == {0: 144, 1: 104, 2: 76, 3: 4, 4: 360}


@needs_tmpl
def test_首音与独立读数吻合():
    """PyFLP 独立读出「首音 D7、通道 2」。**两个实现对得上才算读懂。**"""
    n = FL.note_at(FL.notes_blob(FL.read(TEMPLATE)), 0)
    assert (n["pos"], n["rack"], n["key"]) == (0, 2, 86)   # 86 = D7


def test_没有音符事件的工程要报错():
    head = b"FLhd" + struct.pack("<I", 6) + struct.pack("<hHH", 0, 1, 96)
    doc = FL.Doc(head, [(FL.E_PLUGIN, "FLEX".encode("utf-16-le"))], None)
    with pytest.raises(FL.FlpError, match="没有音符事件"):
        FL.notes_blob(doc)


# =========================================================================
# 不变量：配器不许动（**每条都配一条注入**）
# =========================================================================

@needs_tmpl
def test_配器不变时不报():
    doc = FL.read(TEMPLATE)
    FL.assert_orch_intact(doc, FL.replace_notes(doc, FL.notes_blob(doc)))


@needs_tmpl
@pytest.mark.parametrize("eid", [FL.E_PLUGIN_DATA, FL.E_PLUGIN, FL.E_PRESET])
def test_注入配器改动必须报出来(eid):
    """**这是本文件最重要的一条。**

    配器块被改而没人发现，后果是 FL 打开时安静地变成别的声音 ——
    不报错、不崩溃、只是音源没了。这正是这个项目一直在防的那类失败。
    """
    doc = FL.read(TEMPLATE)
    bad = FL.Doc(doc.head,
                 [(i, b"\x00" * len(p) if i == eid else p)
                  for i, p in doc.events], doc.path)
    with pytest.raises(FL.FlpError, match="配器事件被改动"):
        FL.assert_orch_intact(doc, bad)


@needs_tmpl
def test_报错要说清差在哪不是差几个():
    """「15 → 15 个」等于什么都没说。**数量相同而内容不同**时，
    报数量就是在提供假信息 —— 这个项目为此栽过一次。"""
    doc = FL.read(TEMPLATE)
    bad = FL.Doc(doc.head,
                 [(i, b"\x00" * len(p) if i == FL.E_PLUGIN_DATA else p)
                  for i, p in doc.events], doc.path)
    with pytest.raises(FL.FlpError) as ei:
        FL.assert_orch_intact(doc, bad)
    msg = str(ei.value)
    assert "内容变了" in msg and "id=213" in msg


# =========================================================================
# 拼接
# =========================================================================

@needs_tmpl
@needs_midi
def test_拼接保住全部音源():
    data, rep = FL.splice_midi(TEMPLATE, MIDI)
    assert len(rep["instruments"]) == 5
    before = FL.orch_signature(FL.read(TEMPLATE))
    after = FL.orch_signature(FL.Doc(*FL.parse(data)))
    assert before == after            # **逐字节，不是逐个数**


@needs_tmpl
@needs_midi
def test_拼接后音符是新歌的():
    """音符数可能碰巧一样（两首歌结构相同），**所以比内容不比数量。**"""
    data, _ = FL.splice_midi(TEMPLATE, MIDI)
    old = FL.notes_blob(FL.read(TEMPLATE))
    new = FL.notes_blob(FL.Doc(*FL.parse(data)))
    assert old != new


@needs_tmpl
@needs_midi
def test_拼接产物能再解析():
    data, _ = FL.splice_midi(TEMPLATE, MIDI)
    doc = FL.Doc(*FL.parse(data))
    assert FL.build(doc.head, doc.events) == data


@needs_tmpl
@needs_midi
def test_指定通道超出范围要报错():
    with pytest.raises(FL.FlpError, match="没有样板音符"):
        FL.splice_midi(TEMPLATE, MIDI, mapping={0: 99})


# =========================================================================
# 换配器
# =========================================================================

@needs_tmpl
def test_换配器只动通道字节(tmp_path):
    src = tmp_path / "s.flp"
    src.write_bytes(TEMPLATE.read_bytes())
    base = FL.notes_blob(FL.read(src))
    data, rep = FL.reorchestrate(src, {0: 3, 3: 0})
    new = FL.notes_blob(FL.Doc(*FL.parse(data)))

    assert rep["moved"] == 148                       # 144 + 4
    assert rep["after"][3] == 144 and rep["after"][0] == 4
    for k in range(FL.n_notes(base)):
        s = k * FL.NOTE_SIZE
        assert base[s:s + FL.N_RACK] == new[s:s + FL.N_RACK]
        assert (base[s + FL.N_RACK + 1:s + FL.NOTE_SIZE]
                == new[s + FL.N_RACK + 1:s + FL.NOTE_SIZE])


@needs_tmpl
def test_换配器不碰配器块(tmp_path):
    src = tmp_path / "s.flp"
    src.write_bytes(TEMPLATE.read_bytes())
    data, _ = FL.reorchestrate(src, {0: 2})
    assert (FL.orch_signature(FL.read(src))
            == FL.orch_signature(FL.Doc(*FL.parse(data))))


@needs_tmpl
def test_空映射等于原样(tmp_path):
    src = tmp_path / "s.flp"
    src.write_bytes(TEMPLATE.read_bytes())
    data, rep = FL.reorchestrate(src, {})
    assert rep["moved"] == 0
    assert data == src.read_bytes()


@needs_tmpl
@pytest.mark.parametrize("field,label", [
    (FL.N_KEY, "音高"), (FL.N_POS, "位置"), (FL.N_LEN, "时值")])
def test_换配器动了别的字节必须报出来(tmp_path, monkeypatch, field, label):
    """**单一变量被破坏时必须炸。**

    第一版把重映射和自检揉在一起，结果自检比的是同一段代码刚写出的字节 ——
    结构上永远不会响。测试写出来跑一遍才发现：**一个不会响的检查，
    和一个正确的检查，在测试报告上长得一模一样。**
    """
    src = tmp_path / "s.flp"
    src.write_bytes(TEMPLATE.read_bytes())
    real = FL.remap_racks

    def sabotage(base, remap):
        blob, moved = real(base, remap)
        b = bytearray(blob)
        b[field] = (b[field] + 1) % 128        # 偷偷改第一个音符的别的字段
        return bytes(b), moved

    monkeypatch.setattr(FL, "remap_racks", sabotage)
    with pytest.raises(FL.FlpError, match="除通道外还被改了"):
        FL.reorchestrate(src, {0: 3})


@needs_tmpl
def test_换配器增删了音符必须报出来(tmp_path, monkeypatch):
    src = tmp_path / "s.flp"
    src.write_bytes(TEMPLATE.read_bytes())
    real = FL.remap_racks
    monkeypatch.setattr(
        FL, "remap_racks",
        lambda base, remap: (real(base, remap)[0][:-FL.NOTE_SIZE], 0))
    with pytest.raises(FL.FlpError, match="音符数变了"):
        FL.reorchestrate(src, {0: 3})


# =========================================================================
# 接进动作池之后：**写了文件就必须入账**
# =========================================================================

def test_产物在sources里():
    """**回归测试。** 第一版漏了这条，后果是：`build_flp` 写出了 105879 字节，
    动作却报 `ok=True` 且钩子一个没跑 —— 没入账、没快照、没有回退点。

    `sources` 决定指纹，指纹不变就跳过钩子与提交。产物不在里面，
    等于这个动作在系统的记账之外偷偷改了盘。
    **唯一的破绽是钩子列表是空的，不专门看就发现不了。**
    """
    p = PJ.load("xiaofeng")
    assert p.acc_flp in p.sources


def test_产物与创作者的工程是两个文件():
    """覆盖 `flp` 等于把创作者手挂的配器与编排冲掉。"""
    p = PJ.load("xiaofeng")
    assert p.flp is None or p.acc_flp != p.flp


def test_两个动作都挂了flp钩子():
    """没有钩子的写动作 = 写完不知道对不对。"""
    for name in ("build_flp", "reorchestrate"):
        assert "flp" in TL.BY_NAME[name].hooks


def test_flp钩子在配器丢了时报红(tmp_path, monkeypatch):
    """**注入：产出一份没有任何音源的工程，钩子必须报 False。**

    这正是它唯一要抓的事 —— 这种文件在 FL 里能打开、不报错，只是没声音。
    """
    head = struct.pack("<4sI", b"FLhd", 6) + struct.pack("<hHH", 0, 1, 96)
    empty = FL.build(head, [(FL.E_NOTES, b"\x00" * FL.NOTE_SIZE)])
    out = tmp_path / "empty.flp"
    out.write_bytes(empty)

    p = PJ.load("xiaofeng")
    monkeypatch.setattr(type(p), "acc_flp", property(lambda self: out))
    r = TL.HOOKS["flp"](p)
    assert r.ok is False and "配器丢了" in r.detail


def test_flp钩子在文件不存在时是灰不是红(tmp_path, monkeypatch):
    """**灰 ≠ 红。** 还没生成不等于生成错了 —— 三色纪律。"""
    p = PJ.load("xiaofeng")
    monkeypatch.setattr(type(p), "acc_flp",
                        property(lambda self: tmp_path / "nope.flp"))
    assert TL.HOOKS["flp"](p).ok is None
