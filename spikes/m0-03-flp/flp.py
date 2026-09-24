# -*- coding: utf-8 -*-
"""最小的 .flp 读取器：只认结构，不认含义。

.flp 是 FL Studio 的工程文件，**格式没有官方公开文档**。下面的结构来自社区的逆向
（PyFLP 等项目），所以每一条都要用 FL 自己的输出去核对，不能直接当真：

    "FLhd" · 长度(4 字节，= 6) · 格式(2) · 通道数(2) · PPQ(2)
    "FLdt" · 长度(4 字节) · 一串事件

    每个事件 = 1 字节编号 + 值。值有多长，由编号的范围决定：
        0  –  63   1 字节
        64 – 127   2 字节
        128 – 191  4 字节
        192 – 255  变长：先是一个长度（每字节 7 位，最高位 = 后面还有），再是那么多字节

**自带一个结构检查**：事件必须恰好读完 FLdt 声明的长度，一个字节不多不少。
规则理解错了的话，读着读着就会错位，最后对不上 —— 所以 `structure_ok` 是真依据，不是装饰。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class Event:
    id: int
    size: int      # 值占几个字节（变长事件 = 数据长度）
    value: int     # 定长事件的值；变长事件记为数据长度
    at: int        # 值在文件里从第几个字节开始 —— 写回时用


@dataclass
class Flp:
    format: int
    channels: int
    ppq: int
    events: list
    structure_ok: bool
    raw: bytes


def read(path) -> Flp:
    b = open(path, "rb").read()
    if b[:4] != b"FLhd":
        raise ValueError(f"{path}: 不是 .flp（开头不是 FLhd）")
    hlen = struct.unpack_from("<I", b, 4)[0]
    fmt, nch, ppq = struct.unpack_from("<hHH", b, 8)
    pos = 8 + hlen
    if b[pos:pos + 4] != b"FLdt":
        raise ValueError(f"{path}: 头部之后不是 FLdt")
    dlen = struct.unpack_from("<I", b, pos + 4)[0]
    pos += 8
    end = pos + dlen
    events = []
    while pos < end:
        eid = b[pos]
        pos += 1
        if eid < 64:
            events.append(Event(eid, 1, b[pos], pos))
            pos += 1
        elif eid < 128:
            events.append(Event(eid, 2, struct.unpack_from("<H", b, pos)[0], pos))
            pos += 2
        elif eid < 192:
            events.append(Event(eid, 4, struct.unpack_from("<I", b, pos)[0], pos))
            pos += 4
        else:
            n, shift = 0, 0
            while True:
                c = b[pos]
                pos += 1
                n |= (c & 0x7F) << shift
                shift += 7
                if not c & 0x80:
                    break
            events.append(Event(eid, n, n, pos))
            pos += n
    return Flp(fmt, nch, ppq, events, pos == end == len(b), b)


def with_value(flp: Flp, event: Event, new_value: int) -> bytes:
    """返回改了一个定长事件的值之后的**新字节串**。不改原文件，不改长度。"""
    if event.id >= 192:
        raise ValueError("只改定长事件")
    fmt = {1: "<B", 2: "<H", 4: "<I"}[event.size]
    out = bytearray(flp.raw)
    struct.pack_into(fmt, out, event.at, new_value)
    return bytes(out)
