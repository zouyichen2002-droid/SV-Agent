# -*- coding: utf-8 -*-
"""把自修复的产物渲染成音频，让创作者判断代价函数有没有缺维度。

## 为什么必须听这一次

[ADR-0010](../specs/adr/0010-self-repair-loop.md) 只证明了 findings 归零，
**没有证明好听**。ADR-0006 的教训正是「所有量化门槛全过而人耳判否」。

判据是这个对比：

    原始版    0 findings，已被创作者验收
    修复版    0 findings，但是循环自己搜出来的另一条路径

**两者都是 0 findings。如果修复版明显更难听，就说明代价函数缺维度。**
这是唯一能验证这件事的办法。

三条音频用**同一条伴奏**，唯一的变量是旋律 —— 否则对比不干净。
旋律用正弦，不用声库：判旋律走向时正弦更清楚，也不必等 SynthV 渲染。

用法:
    python scripts/repair_listen.py                 # 8 与 24 两档
    python scripts/repair_listen.py --faults 16 --seed 3
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "out"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from make_accompaniment import _write_wav, build_parts, render_preview
from repair_demo import inject
from svagent.compose.checks import CheckCfg, note_name
from svagent.compose.repair import Ctx, cost, repair

OUT = ROOT / "out" / "listen_repair"


def as_melody(notes):
    return [(n.onset_beats, n.duration_beats, n.midi) for n in notes]


def render(parts, notes, mod, path: Path, mel_gain=1.0):
    acc, mel = render_preview(parts, as_melody(notes), mod.BPM, mod.N_BARS)
    _write_wav(path, acc * 0.85 + mel * mel_gain)


def describe_diff(orig, new, limit=14):
    diffs = [(a.index, a.midi, b.midi, a.lyric)
             for a, b in zip(orig, new) if a.midi != b.midi]
    tdiffs = [(a.index, a.duration_beats, b.duration_beats)
              for a, b in zip(orig, new)
              if abs(a.duration_beats - b.duration_beats) > 1e-9]
    return diffs, tdiffs


def run_one(mod, notes, ctx, parts, n_faults, seed):
    broken, _ = inject(notes, random.Random(seed), n_faults, ctx.cfg)
    res = repair(broken, ctx)
    tag = f"{n_faults}缺陷_种子{seed}"
    print(f"\n=== {tag} ===")
    print(f"  findings {len(res.initial)} → {len(res.final)}　"
          f"代价 {cost(res.initial):.0f} → {cost(res.final):.0f}　"
          f"接受 {res.accepted_steps} 次修复")

    diffs, tdiffs = describe_diff(notes, res.notes)
    print(f"  与原始版相比：{len(diffs)} 个音符换了音高，"
          f"{len(tdiffs)} 个换了时长")
    for i, a, b, ly in diffs[:14]:
        d = b - a
        print(f"     #{i:3d}「{ly}」{note_name(a)}→{note_name(b)}  {d:+d} 半音")
    if len(diffs) > 14:
        print(f"     …还有 {len(diffs)-14} 个")

    render(parts, broken, mod, OUT / f"打坏_{tag}.wav")
    render(parts, res.notes, mod, OUT / f"修复_{tag}.wav")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-module", default="melody_v2")
    ap.add_argument("--faults", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    mod = __import__(a.song_module)
    notes, phrases, text = mod.build()
    ctx = Ctx(text=text, key_root=mod.KEY_ROOT, quality=mod.KEY_QUALITY,
              phrases=phrases, cfg=CheckCfg())
    parts, _, _ = build_parts(mod)

    print(f"《宇宙无边无垠》{len(notes)} 音符　"
          f"原始 {len(ctx.check(notes))} findings（已验收）")
    print("三条音频共用同一条伴奏，唯一变量是旋律。")

    print("\n=== 原始版（对照组）===")
    render(parts, notes, mod, OUT / "原始_已验收.wav")

    cases = ([(a.faults, a.seed)] if a.faults is not None
             else [(8, 42), (24, 0)])
    results = []
    for nf, sd in cases:
        results.append(((nf, sd), run_one(mod, notes, ctx, parts, nf, sd or 0)))

    print("\n" + "=" * 62)
    print("听的顺序：")
    print(f"  1. {OUT / '原始_已验收.wav'}")
    for (nf, sd), r in results:
        print(f"  2. {OUT / ('修复_%d缺陷_种子%d.wav' % (nf, sd or 0))}"
              f"　（{len(r.initial)} findings 修到 {len(r.final)}）")
    zero = [c for c, r in results if r.converged]
    print(f"\n判据：收敛到 0 的那 {len(zero)}/{len(results)} 档，"
          "与原始版**分数完全相同**。")
    print("如果它们明显更难听 —— 那就是代价函数缺维度，需要补检查项。")
    for c, r in results:
        if not r.converged:
            print(f"  注意：{c[0]} 缺陷那档**没有收敛**，还剩 {len(r.final)} 个。"
                  "它不是干净的对照组，只是压力测试。")
    print("「打坏_*.wav」是修复前的样子，想听循环解决了什么就放它。")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
