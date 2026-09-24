# -*- coding: utf-8 -*-
"""比对：我们写进 .svp 的（spec.json） vs SynthV 读出来的（<工程>.dump.json）。

逐项比：速度、拍号、轨道数、音符数，以及每个音的起点、时值、音高、歌词。
**全部精确相等**才算绿 —— 起点和时值是整数 blick，差 1 都不行；速度允许 1e-9 的浮点误差。

**先证明检查会响**：拿标准答案造一份「SynthV 读得一模一样」的假输出，必须判绿；
再改坏三处（速度 98、第 3 个音的歌词、第 5 个音的起点 +1 blick），必须恰好报出这三处。
检查自己不会响的话，真比对的结果不可信。

用法：python compare.py                 只跑自检
      python compare.py <dump.json>     自检 + 真比对
"""
from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "out", "spec.json")


def diff(spec, dump):
    """→ 不一致的地方（列表）。空列表 = 完全一致。"""
    bad = []
    tempos = dump.get("tempo", [])
    if len(tempos) != 1 or tempos[0]["position"] != 0 or abs(tempos[0]["bpm"] - spec["bpm"]) > 1e-9:
        bad.append(f"速度：要 1 个标记 @0 = {spec['bpm']}，SynthV 读出 {tempos}")
    meters = dump.get("meter", [])
    if len(meters) != 1 or [meters[0]["numerator"], meters[0]["denominator"]] != spec["meter"]:
        bad.append(f"拍号：要 {spec['meter']}，SynthV 读出 {meters}")
    tracks = dump.get("tracks", [])
    if len(tracks) != 1:
        bad.append(f"轨道数：要 1，SynthV 读出 {len(tracks)}")
        return bad
    want, got = spec["notes"], tracks[0]["notes"]
    if len(want) != len(got):
        bad.append(f"音符数：要 {len(want)}，SynthV 读出 {len(got)}")
    for i, (a, b) in enumerate(zip(want, got), 1):
        for k in ("onset", "duration", "pitch", "lyrics"):
            if a[k] != b[k]:
                bad.append(f"第 {i} 个音的 {k}：要 {a[k]!r}，SynthV 读出 {b[k]!r}")
    return bad


def fake_dump(spec):
    return {"tempo": [{"position": 0, "bpm": spec["bpm"]}],
            "meter": [{"position": 0, "numerator": spec["meter"][0], "denominator": spec["meter"][1]}],
            "tracks": [{"name": "M0 测试", "notes": copy.deepcopy(spec["notes"])}]}


def selftest(spec):
    same = diff(spec, fake_dump(spec))
    broken = fake_dump(spec)
    broken["tempo"][0]["bpm"] = 98
    broken["tracks"][0]["notes"][2]["lyrics"] = "错"
    broken["tracks"][0]["notes"][4]["onset"] += 1
    caught = diff(spec, broken)
    ok = same == [] and len(caught) == 3
    print(f"自检：一模一样 → {len(same)} 处不一致（应为 0）；改坏 3 处 → 报出 {len(caught)} 处（应为 3）"
          f" → {'检查会响 ✓' if ok else '检查失灵 ✗'}")
    for c in caught:
        print(f"      {c}")
    return ok


def main():
    spec = json.load(open(SPEC, encoding="utf-8"))
    if not selftest(spec):
        sys.exit(1)
    if len(sys.argv) > 1:
        dump = json.loads(open(sys.argv[1], "rb").read().decode("utf-8"))
        bad = diff(spec, dump)
        print(f"\n真比对（{os.path.basename(sys.argv[1])}）：{'绿 —— 完全一致' if not bad else f'红 —— {len(bad)} 处不一致'}")
        for b in bad:
            print(f"  ✗ {b}")


if __name__ == "__main__":
    main()
