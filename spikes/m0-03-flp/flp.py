# -*- coding: utf-8 -*-
"""最小的 .flp 读取器：只认结构，不认含义。

.flp 是 FL Studio 的工程文件，**格式没有官方公开文档**。下面的结构来自社区的逆向
（PyFLP、flpkit 等项目），所以每一条都要用 FL 自己的输出去核对，不能直接当真：

    "FLhd" · 长度(4 字节，= 6) · 格式(2) · 通道数(2) · PPQ(2)
    "FLdt" · 长度(4 字节) · 一串事件

    每个事件 = 1 字节编号 + 值。值有多长，由编号的范围决定：
        0  –  63   1 字节
        64 – 127   2 字节
        128 – 191  4 字节
        192 – 255  变长：先是一个长度（每字节 7 位，最高位 = 后面还有），再是那么多字节

## 例外：172 号事件只有 1 个字节（2026-09-26 实测抓到）

FL 构建号 5164 以后（FL 2024 后期起，包括你在用的 25.2.5.5319）存的工程里，
多了一个 172 号事件。按上面的规则它该带 4 个字节，实际只带 1 个 ——
按 4 个字节读，从这里开始整个文件都会错位。

依据：
  · flpkit 0.8.1（MIT，2026-09-06）的说明原文：「event 172 is one byte on FL 2026,
    not the classic four」，并说这个大小随 FL 版本变，要按版本实测
  · 本机两个文件（构建 5164 的演示曲《Thief》、构建 5319 你刚存的工程）里，
    172 号事件后面都是 `ac 01 | 01 00 | c0 36 …`：按 1 字节读，下一个是 1 号事件（值 0），
    再下一个是 192 号文字事件（54 字节，「FL Studio 25.2.5.5319.5319」），之后与旧版文件逐个对上
  · 注意：「172 带 3 个字节」在这两个文件上消耗的字节完全一样，分不出来。采用社区在更新版本上的实测

## 结构检查（加强过）

第一版只检查「事件恰好读完 FLdt 声明的长度」—— **这个检查被骗过**：错位之后，
把一段文字拆成了一串「编号 0、值是可打印字符」的假事件，最后又碰巧在文件末尾对齐，照样报「对」。
现在两条都要满足才算结构对：
  · 恰好读完，一个字节不多不少
  · 没有错位的特征：连续 4 个以上「编号 0、值在 32–126」的假事件
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SIZE_OVERRIDES = {172: 1}   # 事件编号 → 值的字节数。见上面「例外」
FAKE_RUN_LIMIT = 4


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
    exact_end: bool      # 恰好读完
    fake_run: int        # 最长的假事件串（错位的特征）
    build: int | None    # 159 号事件：存盘的 FL 构建号
    raw: bytes

    @property
    def structure_ok(self):
        return self.exact_end and self.fake_run < FAKE_RUN_LIMIT


def read(path, overrides=SIZE_OVERRIDES) -> Flp:
    """overrides 传 {} 就是第一版的读法 —— 只用来证明检查会响。"""
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
    run = fake_run = 0
    while pos < end:
        eid = b[pos]
        pos += 1
        size = overrides.get(eid) or (1 if eid < 64 else 2 if eid < 128 else 4 if eid < 192 else None)
        if size is not None:
            value = int.from_bytes(b[pos:pos + size], "little")
            events.append(Event(eid, size, value, pos))
            pos += size
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
        e = events[-1]
        run = run + 1 if (e.id == 0 and 32 <= e.value < 127) else 0
        fake_run = max(fake_run, run)
    build = next((e.value for e in events if e.id == 159), None)
    return Flp(fmt, nch, ppq, events, pos == end == len(b), fake_run, build, b)


def with_value(flp: Flp, event: Event, new_value: int) -> bytes:
    """返回改了一个定长事件的值之后的**新字节串**。不改原文件，不改长度。"""
    if event.id >= 192:
        raise ValueError("只改定长事件")
    out = bytearray(flp.raw)
    out[event.at:event.at + event.size] = new_value.to_bytes(event.size, "little")
    return bytes(out)
