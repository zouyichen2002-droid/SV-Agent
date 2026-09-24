# -*- coding: utf-8 -*-
"""速度存在 .flp 的哪里？—— 不预设答案，让 FL 当裁判。

1. 每个样本工程：让 FL 用命令行导出 MIDI，读出 FL 认定的速度（裁判）
2. 读 .flp 的全部事件，找值等于「速度 × 1000 / × 100 / × 10 / × 1」的定长事件
3. **在所有样本里都对得上**的事件编号 = 速度事件
   样本的速度必须各不相同，否则「对上了」可能只是巧合（v1 的两首歌恰好都是 66 BPM）

样本全是 FL 自带的模板和演示曲的**拷贝**，放在 out/（不进仓库，第三方内容）。
FL 的结果缓存在 out/oracle.json，重跑不必再启动 FL。

用法：python find_tempo.py
"""
from __future__ import annotations

import json
import os
import shutil
from collections import Counter

import flp
import fl_cli

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "samples")
CACHE = os.path.join(HERE, "out", "oracle.json")
TPL = r"G:\FL Studio\Data\Templates"
DEMO = r"G:\FL Studio\Data\Demo projects\Demo songs"

SOURCES = [
    TPL + r"\Empty\Empty.flp",
    TPL + r"\Advanced\Electronic\Breakbeat.flp",
    TPL + r"\Advanced\Electronic\Chillout.flp",
    TPL + r"\Advanced\Electronic\Drum & Bass.flp",
    TPL + r"\Advanced\Electronic\Dubstep.flp",
    TPL + r"\Advanced\Electronic\EDM-House.flp",
    TPL + r"\Advanced\Electronic\Trap.flp",
    TPL + r"\Advanced\Instrumental\Funk.flp",
    TPL + r"\Advanced\Instrumental\Jazz.flp",
    TPL + r"\Advanced\Instrumental\Metal.flp",
    DEMO + r"\Ookay - Thief.flp",
    DEMO + r"\Edlan & Ella Noël - Song For You.flp",
    DEMO + r"\Mehdi Ebrahiminejad - Never Out.flp",
]
SCALES = [1000, 100, 10, 1]


def local_name(src):
    rel = os.path.relpath(src, TPL if src.startswith(TPL) else DEMO)
    tag = "tpl" if src.startswith(TPL) else "demo"
    return tag + "_" + "".join(c if c.isascii() and c.isalnum() else "_" for c in os.path.splitext(rel)[0]) + ".flp"


def oracle():
    """→ {本地文件名: {"bpm": [...], "ppq": int, "seconds": float}}，有缓存就用缓存。"""
    os.makedirs(OUT, exist_ok=True)
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    for src in SOURCES:
        name = local_name(src)
        if name in cache:
            continue
        dst = os.path.join(OUT, name)
        shutil.copyfile(src, dst)
        mid, dt = fl_cli.export_midi(dst)
        ppq, bpms = fl_cli.midi_tempo(mid)
        cache[name] = {"bpm": bpms, "ppq": ppq, "seconds": round(dt, 1)}
        print(f"  FL 报：{name:45s} {bpms[0] if bpms else '—':>10} BPM · {dt:5.1f} 秒")
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return cache


def main():
    print("── 裁判：让 FL 导出 MIDI，读出它认定的速度 ──")
    cache = oracle()

    print("\n── 每个样本 ──")
    hits = {s: Counter() for s in SCALES}   # 缩放倍数 → 事件编号 → 在几个样本里对上
    usable = 0
    usable_tempos = set()
    for name, o in cache.items():
        f = flp.read(os.path.join(OUT, name))
        bpms = o["bpm"]
        distinct = sorted({round(b, 3) for b in bpms})
        note = "" if len(distinct) == 1 else f"  ⚠ MIDI 里有 {len(distinct)} 种速度（{distinct[0]}–{distinct[-1]}），可能有速度自动化"
        print(f"  {name:45s} FL {bpms[0]:9.4f} BPM · PPQ flp {f.ppq:3d} / midi {o['ppq']:3d}"
              f" · 事件 {len(f.events):5d} · 结构 {'对' if f.structure_ok else '错'}{note}")
        if not f.structure_ok or len(distinct) != 1:
            continue
        usable += 1
        usable_tempos.add(round(bpms[0], 3))
        for s in SCALES:
            target = round(bpms[0] * s)
            ids = {e.id for e in f.events if e.id < 192 and e.value == target}
            hits[s].update(ids)

    print(f"\n── 结论：{usable} 个可用样本（排除了结构错或带速度自动化的），"
          f"{len(usable_tempos)} 种不同速度 {sorted(usable_tempos)} ──")
    for s in SCALES:
        everywhere = [i for i, c in hits[s].items() if c == usable]
        print(f"  值 = 速度 × {s:<4d}：所有样本里都对得上的事件编号 → {everywhere or '无'}")


if __name__ == "__main__":
    main()
