# -*- coding: utf-8 -*-
"""FL 工程（`.flp`）的**事件级**读写。与 `svp.py` 平级：直写文件，不走桥。

## 为什么是事件级，不是语义级

`.flp` 里插件的状态是**不透明的二进制块**（事件 213，实测最大一块 28494 字节，
那是 FPC 连采样引用）。要保住创作者挂好的音源，**不需要看懂那块，只需要别碰它**。

所以这个模块只做一件事：把文件切成 `(事件 id, 载荷)` 的序列，
改想改的那一条，其余原样拼回去。这与 `agent/segments.py` 的做法同源 ——
区域外的元素**传同一个对象**，不复制、不重建。

试过 PyFLP 2.2.1，**在创作者的真工程上不安全**：
在 3.11+ 上要打补丁才 import 得进来；`test2.flp` 读回写丢 16 字节
（播放列表事件 80 字节，它只认 32/60）；`Project_test1.flp` 长度不变但哈希变了，
且读通道直接 IndexError；两个文件的 BPM 都读成 None。所以自己写。

## 格式

    "FLhd" + 长度(u32) + 头部        头部 = format(i16) nChannels(u16) PPQ(u16)
    "FLdt" + 长度(u32) + 事件序列

    事件 id 0-63    → 后跟 1 字节
            64-127  → 后跟 2 字节
            128-191 → 后跟 4 字节
            192-255 → 后跟 varint 长度 + 该长度数据

## 唯一的地基判据

**读出来再拼回去必须逐字节相同。** 做不到就说明没读懂这个格式，
一切基于它的写入都不可信。`tests/test_flp.py` 拿真工程验这条。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

# ---- 事件 id ------------------------------------------------------------
# 都是实测认出来的，不是查表抄的：
#   224 → test2.flp 里这块 16512 字节，而 PyFLP 独立数出 688 个音符，
#         16512 / 688 = 24，且首音解出 pos=0 rack=2 key=86，
#         与 PyFLP 报的「D7，通道 2」吻合
#   201/203 → 解 UTF-16 出来正是 'FLEX' 与 'Harmo Pad'
E_NOTES = 224           # 一个 pattern 的全部音符
E_PLUGIN = 201          # 插件内部名，如 FLEX / FPC
E_PRESET = 203          # 通道/音色名，如 Harmo Pad
E_PLUGIN_DATA = 213     # 插件状态（不透明二进制）

# **配器三件套。** 任何操作之后这三类必须逐字节不变，否则音源就丢了。
ORCH = frozenset({E_PLUGIN, E_PRESET, E_PLUGIN_DATA})

NOTE_SIZE = 24

# 音符 24 字节里，**已交叉验证**的四个字段（与 PyFLP 独立读数吻合）：
N_POS, N_RACK, N_LEN, N_KEY = 0, 6, 8, 12
# 未验证含义、一律从样板音符原样沿用的字节：4-5、7、16-20、22-23。
# 21 看着是力度（同一声部内随音变化，范围 0-127），但**没有第二来源佐证**，
# 所以只在明确要求时才写它。
N_VEL = 21


class FlpError(Exception):
    pass


# =========================================================================
# 事件层
# =========================================================================

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def _put_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def parse(data: bytes) -> tuple[bytes, list[tuple[int, bytes]]]:
    """→ (头部字节, [(事件 id, 载荷), ...])"""
    if data[:4] != b"FLhd":
        raise FlpError("不是 FLP：开头不是 FLhd")
    hlen = struct.unpack("<I", data[4:8])[0]
    head = data[:8 + hlen]
    i = 8 + hlen
    if data[i:i + 4] != b"FLdt":
        raise FlpError("缺 FLdt 数据块")
    dlen = struct.unpack("<I", data[i + 4:i + 8])[0]
    i += 8
    end = i + dlen
    if end != len(data):
        raise FlpError(f"FLdt 声明 {dlen} 字节，实际剩 {len(data) - i} —— 文件被截断？")

    evs: list[tuple[int, bytes]] = []
    while i < end:
        eid = data[i]
        i += 1
        if eid < 64:
            n = 1
        elif eid < 128:
            n = 2
        elif eid < 192:
            n = 4
        else:
            n, i = _varint(data, i)
        evs.append((eid, data[i:i + n]))
        i += n
    return head, evs


def build(head: bytes, evs) -> bytes:
    body = bytearray()
    for eid, payload in evs:
        body.append(eid)
        if eid >= 192:
            body += _put_varint(len(payload))
        body += payload
    return bytes(head) + b"FLdt" + struct.pack("<I", len(body)) + bytes(body)


@dataclass
class Doc:
    """一份解开的 FL 工程。`path` 只作报错提示用。"""
    head: bytes
    events: list
    path: Path | None = None

    @property
    def ppq(self) -> int:
        return struct.unpack("<hHH", self.head[8:14])[2]

    @property
    def n_channels(self) -> int:
        return struct.unpack("<hHH", self.head[8:14])[1]

    def to_bytes(self) -> bytes:
        return build(self.head, self.events)


def read(path) -> Doc:
    path = Path(path)
    head, evs = parse(path.read_bytes())
    return Doc(head, evs, path)


# =========================================================================
# 语义层：只认音符与配器，别的一概不解释
# =========================================================================

def _text(payload: bytes) -> str:
    try:
        return payload.decode("utf-16-le").rstrip("\x00")
    except UnicodeDecodeError:
        return ""


def instruments(doc: Doc) -> list[tuple[str, str]]:
    """→ [(插件, 音色名), ...]，按工程里的出现顺序。

    FL 是先写插件名（201）再写音色名（203），所以配对靠顺序。
    """
    out, cur = [], None
    for eid, payload in doc.events:
        if eid == E_PLUGIN:
            s = _text(payload)
            if s.strip():
                cur = s
        elif eid == E_PRESET and cur:
            s = _text(payload)
            if s.strip():
                out.append((cur, s))
                cur = None
    return out


def notes_blob(doc: Doc) -> bytes:
    for eid, payload in doc.events:
        if eid == E_NOTES:
            return payload
    raise FlpError(f"{doc.path.name if doc.path else '这个工程'} 里没有音符事件"
                   f"（id={E_NOTES}）—— 它不能当模板")


def n_notes(blob: bytes) -> int:
    return len(blob) // NOTE_SIZE


def note_at(blob: bytes, k: int) -> dict:
    b = blob[k * NOTE_SIZE:(k + 1) * NOTE_SIZE]
    return {"pos": struct.unpack_from("<I", b, N_POS)[0],
            "rack": b[N_RACK],
            "length": struct.unpack_from("<I", b, N_LEN)[0],
            "key": struct.unpack_from("<I", b, N_KEY)[0],
            "vel": b[N_VEL]}


def channel_counts(blob: bytes) -> dict[int, int]:
    out: dict[int, int] = {}
    for k in range(n_notes(blob)):
        ch = blob[k * NOTE_SIZE + N_RACK]
        out[ch] = out.get(ch, 0) + 1
    return dict(sorted(out.items()))


def prototypes(blob: bytes) -> dict[int, bytes]:
    """每条通道留一个样板音符。**未验证含义的字节靠它原样沿用** ——
    与其猜那些位是什么，不如抄一份确定能用的。"""
    proto: dict[int, bytes] = {}
    for k in range(n_notes(blob)):
        b = blob[k * NOTE_SIZE:(k + 1) * NOTE_SIZE]
        proto.setdefault(b[N_RACK], b)
    return proto


def make_note(proto: bytes, *, pos: int, rack: int, length: int,
              key: int, vel: int | None = None) -> bytes:
    b = bytearray(proto)
    struct.pack_into("<I", b, N_POS, max(0, int(pos)))
    b[N_RACK] = rack
    struct.pack_into("<I", b, N_LEN, max(1, int(length)))
    struct.pack_into("<I", b, N_KEY, int(key))
    if vel is not None:
        b[N_VEL] = min(127, max(0, int(vel)))
    return bytes(b)


def replace_notes(doc: Doc, blob: bytes) -> Doc:
    """换掉音符事件，**其余事件传同一个对象**（不复制、不重建）。"""
    return Doc(doc.head,
               [(i, blob if i == E_NOTES else p) for i, p in doc.events],
               doc.path)


# =========================================================================
# 不变量：配器不许动
# =========================================================================

def orch_signature(doc: Doc) -> list[tuple[int, bytes]]:
    return [(i, p) for i, p in doc.events if i in ORCH]


def assert_orch_intact(before: Doc, after: Doc) -> None:
    """**这是这个模块存在的理由。** 配器一旦被改，创作者手挂的音源就丢了，
    而且 FL 打开时只会安静地变成别的声音 —— 又一个不报错的错误。"""
    a, b = orch_signature(before), orch_signature(after)
    if a == b:
        return
    # **报差在哪，不报差几个。** 「15 → 15 个」这种话等于什么都没说 ——
    # 数量相同而内容不同，正是这个项目一直在防的那类假信息。
    if len(a) != len(b):
        why = f"事件个数 {len(a)} → {len(b)}"
    else:
        bad = [f"第{k}个 id={a[k][0]} {len(a[k][1])}→{len(b[k][1])}字节"
               if a[k][1] != b[k][1] else ""
               for k in range(len(a))]
        bad = [x for x in bad if x]
        why = f"{len(bad)}/{len(a)} 个内容变了：" + "；".join(bad[:3])
    raise FlpError(
        f"配器事件被改动了（{why}）—— 这是 bug，不许写盘。"
        f"音源块是创作者手挂出来的，丢了只能他重挂一遍")


# =========================================================================
# 两个高层操作
# =========================================================================

def midi_parts(path) -> tuple[list[tuple[str, list]], int]:
    """读伴奏 MIDI → ([(声部名, [(起点tick, 音高, 时值tick, 力度), ...]), ...], 每拍tick)

    只取有音符的音轨。空音轨（通常是 tempo map）不占声部序号，
    否则声部与通道的对应会整体错位一格 —— 那种错听得出来但查不出来。
    """
    import mido
    mid = mido.MidiFile(str(path))
    parts = []
    for ti, tr in enumerate(mid.tracks):
        name, t, on, notes = "", 0, {}, []
        for m in tr:
            t += m.time
            if m.type == "track_name":
                name = m.name
            elif m.type == "note_on" and m.velocity > 0:
                on.setdefault(m.note, []).append((t, m.velocity))
            elif m.type == "note_off" or (m.type == "note_on" and not m.velocity):
                if on.get(m.note):
                    st, v = on[m.note].pop(0)
                    notes.append((st, m.note, t - st, v))
        if notes:
            parts.append((name or f"track{ti}", notes))
    return parts, mid.ticks_per_beat


def splice_midi(template, midi, *, mapping: dict[int, int] | None = None
                ) -> tuple[bytes, dict]:
    """把伴奏 MIDI 的音符装进一份**已配好音源**的工程。

    `mapping` 是 {声部序号: 通道号}。不给就按顺序发牌 ——
    第 i 个声部给第 i 条通道。

    → (新工程字节, 报告)。**不写盘** —— 写盘要走 Guard，那是动作层的事。
    """
    doc = read(template)
    base = notes_blob(doc)
    proto = prototypes(base)
    chans = sorted(proto)
    if not chans:
        raise FlpError(f"{Path(template).name} 里一条带音符的通道都没有")

    parts, tpb = midi_parts(midi)
    scale = doc.ppq / tpb

    recs = []
    used: dict[str, int] = {}
    for idx, (pname, notes) in enumerate(parts):
        ch = mapping.get(idx) if mapping else None
        if ch is None:
            ch = chans[idx % len(chans)]
        if ch not in proto:
            raise FlpError(f"通道 {ch} 在模板里没有样板音符，装不进去。"
                           f"模板有音符的通道：{chans}")
        used[pname] = ch
        for st, key, dur, vel in notes:
            recs.append((int(round(st * scale)), ch,
                         make_note(proto[ch], pos=round(st * scale), rack=ch,
                                   length=round(dur * scale), key=key, vel=vel)))
    # 按位置排序，贴合 FL 自己的写法
    recs.sort(key=lambda r: (r[0], r[1]))
    blob = b"".join(r[2] for r in recs)

    out = replace_notes(doc, blob)
    assert_orch_intact(doc, out)
    return out.to_bytes(), {
        "template": str(template), "midi": str(midi),
        "notes_before": n_notes(base), "notes_after": len(recs),
        "ppq": doc.ppq, "midi_tpb": tpb,
        "part_to_channel": used,
        "channels": channel_counts(blob),
        "instruments": [f"{p}／{n}" for p, n in instruments(out)],
    }


def remap_racks(base: bytes, remap: dict[int, int]) -> tuple[bytes, int]:
    """只改 rack 字节，→ (新 blob, 搬动数)。

    **单独抽出来，是为了让下面那条自检有东西可验。** 揉在 `reorchestrate`
    里面时，自检比的是同一段代码刚构造出的字节 —— 那个循环结构上
    只可能碰 rack，于是检查永远不会响，和「只报 0 的检查」是一回事。
    分开之后它验的是一个**可以被替换的单元**的输出，注入缺陷才测得出来。
    """
    b = bytearray(base)
    moved = 0
    for k in range(n_notes(base)):
        off = k * NOTE_SIZE + N_RACK
        new = remap.get(b[off])
        if new is not None and new != b[off]:
            b[off] = new
            moved += 1
    return bytes(b), moved


def assert_only_rack_changed(base: bytes, blob: bytes) -> None:
    """换配器的全部意义在于**单一变量**。音高时值力度一旦也变了，
    创作者听到差别时就无法归因 —— 那这次试验就白做了。"""
    if len(base) != len(blob):
        raise FlpError(f"音符数变了（{n_notes(base)} → {n_notes(blob)}）"
                       f"—— 换配器不该增删音符")
    for k in range(n_notes(base)):
        s = k * NOTE_SIZE
        if (base[s:s + N_RACK] != blob[s:s + N_RACK]
                or base[s + N_RACK + 1:s + NOTE_SIZE]
                != blob[s + N_RACK + 1:s + NOTE_SIZE]):
            raise FlpError(f"第 {k} 个音符除通道外还被改了 —— 这是 bug。"
                           f"换配器必须是单一变量，否则差别归不了因")


def reorchestrate(src, remap: dict[int, int]) -> tuple[bytes, dict]:
    """换配器：**只改「哪条通道来演」，音符本身一个字节都不动。**

    `remap` 是 {原通道: 新通道}，没列出的不动。

    这是单一变量实验 —— 音高、位置、时值、力度逐字节保持，
    所以听出来的任何差别都只可能来自音色。**能归因，才能迭代。**
    """
    doc = read(src)
    base = notes_blob(doc)
    blob, moved = remap_racks(base, remap)
    assert_only_rack_changed(base, blob)

    out = replace_notes(doc, blob)
    assert_orch_intact(doc, out)
    return out.to_bytes(), {
        "src": str(src), "remap": {str(k): v for k, v in remap.items()},
        "notes": n_notes(base), "moved": moved,
        "before": channel_counts(base), "after": channel_counts(blob),
        "instruments": [f"{p}／{n}" for p, n in instruments(out)],
    }
