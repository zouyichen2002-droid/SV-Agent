# -*- coding: utf-8 -*-
"""回归检查：《傍晚》人声扒谱 r05 是创作者认可的基线 —— 改了代码之后，从同样的输入重算，必须和基线逐个音一模一样。

创作者 09-29 听 r05：「太棒了，这版基本没问题了！剩下有限个可以创作者手改！这版最好保护一下」。
基线放在 E:/sv-agent-data/probes/m1-01-voice-to-midi/rounds/r05/基线_只读/（只读；清单 manifest.json 里有每个文件的校验码）。

重算的链子（从存下来的中间结果起，几秒钟；GAME / basic-pitch 本身重跑逐字节一样，09-28 验过）：
  r01 的 MIDI（Vocal2Midi 只听写）→ 按创作者的歌词修歌词（只改字，repair_lyrics）→ r04
  → 挑八度（pick_octave.pick）→ r05
每一步都和基线比：起止时间、音高、歌词逐个一样才算过。先查基线文件的校验码有没有变（被改过就停）。

    E:/sv-agent-data/envs/vocal2midi/Scripts/python.exe regress_r05.py
改代码后结果本来就该变（比如换了更好的规则）→ 这里会报不一样：先让创作者听新的，他认了再换基线，不要悄悄改基线。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
sys.path.insert(0, str(HERE.parent / "m1-03-lyrics"))
import compare_notes as C  # noqa: E402
import eval_lyrics as E  # noqa: E402
import pick_octave as P  # noqa: E402
import repair_lyrics as RL  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
BASE = pathlib.Path("E:/sv-agent-data/probes/m1-01-voice-to-midi/rounds/r05/基线_只读")
R01_MID = "E:/sv-agent-data/probes/m1-01-voice-to-midi/m1-01_v2m_asr.mid"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def diff(a: list, b: list, label: str) -> list[str]:
    a, b = sorted(tuple(x) for x in a), sorted(tuple(x) for x in b)
    if len(a) != len(b):
        return [f"{label}：音数 {len(a)} ≠ 基线 {len(b)}"]
    out = []
    for k, (x, y) in enumerate(zip(a, b)):
        if abs(x[0] - y[0]) > 1e-6 or abs(x[1] - y[1]) > 1e-6 or abs(x[2] - y[2]) > 1e-6 or x[3] != y[3]:
            out.append(f"{label} 第 {k + 1} 个音：重算 {x} · 基线 {y}")
            if len(out) >= 5:
                break
    return out


def main() -> int:
    man = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
    bad = [f for f, h in man["基线文件的校验码"].items() if sha(BASE / f) != h]
    if bad:
        print("基线文件被改过，停：", bad)
        return 1
    print("基线文件校验码：一致")
    chars, pys = E.text_pinyin(man["输入"]["歌词"]["路径"])
    r04, _ = RL.repair(E.load(R01_MID), chars, pys)
    fails = diff(r04, json.loads((BASE / "r04_notes.json").read_text(encoding="utf-8")), "r04（修歌词）")
    r05, *_ = P.pick(sorted(tuple(x) for x in r04))
    fails += diff(r05, json.loads((BASE / "r05_notes.json").read_text(encoding="utf-8")), "r05（挑八度）")
    print("回归：", "通过（重算的 r04、r05 和基线逐个音一模一样）" if not fails else "不一样 ——")
    for f in fails:
        print("  ✗", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
