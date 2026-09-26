# -*- coding: utf-8 -*-
"""裁判 3：SynthV 自己写的恢复文件。

SynthV 开着工程时，会自动往
    %APPDATA%\\Dreamtonics\\Synthesizer V Studio 2\\recovery\\<日期>\\<工程名>_<时间>.svp
写一份恢复文件 —— 那就是 **SynthV 眼里的工程**，由它自己序列化出来。

这里找到某个工程最新的那一份，读出**所有**音符组里的音（主音符组 + 轨道引用的音符库组，
按引用的时间偏移和音高偏移换算成绝对位置），交给 compare.py 和 spec.json 比。

为什么需要它：2026-09-26 实测，SynthV 2.2.1 打开我们写的工程后，把主音符组里的 8 个音
挪进了一个新建的音符组。第 1 版导出脚本只读主音符组，读出 0 个音；导出的 WAV 却唱了 7.4 秒。
两个裁判对不上 —— 这份恢复文件是第三个，由 SynthV 自己写，和前两个都独立。

用法：python verify_recovery.py [工程名，默认 m0_04]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import compare

RECOVERY = os.path.join(os.environ["APPDATA"], "Dreamtonics", "Synthesizer V Studio 2", "recovery")


def latest(stem):
    files = glob.glob(os.path.join(RECOVERY, "*", f"{stem}_*.svp"))
    return max(files, key=os.path.getmtime) if files else None


def as_dump(d):
    """把 .svp（SynthV 的文件格式）转成和导出脚本一样的形状：绝对起点、绝对音高。"""
    lib = {g["uuid"]: g for g in d["library"]}
    tracks = []
    for tr in d["tracks"]:
        mref = tr["mainRef"]
        notes = [{"onset": n["onset"] + mref["blickOffset"], "duration": n["duration"],
                  "pitch": n["pitch"] + mref["pitchOffset"], "lyrics": n["lyrics"],
                  "group": tr["mainGroup"]["name"], "main": True} for n in tr["mainGroup"]["notes"]]
        for ref in tr.get("groups", []):
            g = lib.get(ref["groupID"])
            if g is None or ref.get("isInstrumental"):
                continue
            notes += [{"onset": n["onset"] + ref["blickOffset"], "duration": n["duration"],
                       "pitch": n["pitch"] + ref["pitchOffset"], "lyrics": n["lyrics"],
                       "group": g["name"], "main": False} for n in g["notes"]]
        notes.sort(key=lambda n: n["onset"])
        tracks.append({"name": tr["name"], "notes": notes})
    meter = [{"position": m["index"], "numerator": m["numerator"], "denominator": m["denominator"]}
             for m in d["time"]["meter"]]
    return {"tempo": d["time"]["tempo"], "meter": meter, "tracks": tracks}


def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "m0_04"
    path = latest(stem)
    if not path:
        print(f"灰：没有找到 {stem} 的恢复文件（SynthV 还没打开过它？）")
        sys.exit(2)
    spec = json.load(open(compare.SPEC, encoding="utf-8"))
    if not compare.selftest(spec):
        sys.exit(1)
    d = json.loads(open(path, "rb").read().rstrip(b"\x00").decode("utf-8"))
    dump = as_dump(d)
    bad = compare.diff(spec, dump)
    where = sorted({(n["group"], n["main"]) for t in dump["tracks"] for n in t["notes"]})
    print(f"\n恢复文件：{os.path.relpath(path, RECOVERY)}")
    print(f"音符在哪：{['主音符组 ' + g if m else '音符库组 ' + g for g, m in where]}")
    print(f"导出设置：{d['renderConfig']['destination']!r} · {d['renderConfig']['filename']!r}")
    print(f"结果：{'绿 —— 与写进去的完全一致' if not bad else f'红 —— {len(bad)} 处不一致'}")
    for b in bad:
        print(f"  ✗ {b}")


if __name__ == "__main__":
    main()
