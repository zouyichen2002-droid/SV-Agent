# -*- coding: utf-8 -*-
"""自修复循环的可复现演示：把一首干净的歌打坏，看它自己修回来。

## 为什么用「注入缺陷」而不是拿一首坏歌

`melody_v2` 是 0 finding 的已验收作品。往它身上注入**可控数量、可复现**
（固定随机种子）的缺陷，就得到一个**已知答案**的测试：
修复循环应该把 findings 拉回 0，而且不能改动没被打坏的音符。

这比拿一首真正的坏歌强，因为我们知道正确答案是什么。
它同时是这个循环的回归测试 —— 顺带补上了这个项目「零自动化测试」的一角。

用法:
    python scripts/repair_demo.py                 # 默认注入 8 个缺陷
    python scripts/repair_demo.py --faults 20 --seed 7
    python scripts/repair_demo.py --verbose       # 打印每一步
"""
from __future__ import annotations

import argparse
import copy
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "out"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent.compose.checks import CheckCfg, note_name, summarize
from svagent.compose.repair import Ctx, cost, repair


def inject(notes, rng, n_faults, cfg):
    """注入缺陷。只动音高与时长 —— 与修复器的搜索空间一致。"""
    broken = copy.deepcopy(notes)
    log = []
    kinds = ("越界", "调外", "大跳", "缺口")
    idxs = rng.sample(range(1, len(broken) - 1), n_faults)
    for k, i in enumerate(idxs):
        kind = kinds[k % len(kinds)]
        old = broken[i].midi
        if kind == "越界":
            broken[i].midi = old + rng.choice((14, -14))
        elif kind == "调外":
            broken[i].midi = old + 1          # 半音一定出调（A 小调无升号）
        elif kind == "大跳":
            broken[i].midi = old + rng.choice((11, -11))
        else:
            # 缺口：把这个音符的起点往后推。
            # **不能靠缩短前一个音符** —— 句中音符大多只有 0.5 拍，
            # 最多造出 0.25 拍的洞，够不到 1.0 拍的阈值。实测踩过：
            # 声称注入 8 个缺陷，实际只落地 6 个，分项里根本没有 phrase。
            broken[i].onset_beats = round(broken[i].onset_beats + 1.5, 6)
            log.append(f"#{broken[i].index} 起点后移 1.5 拍 → 乐句缺口")
            continue
        log.append(f"#{broken[i].index} {note_name(old)}→"
                   f"{note_name(broken[i].midi)}（{kind}）")
    return broken, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-module", default="melody_v2")
    ap.add_argument("--faults", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    mod = __import__(a.song_module)
    notes, phrases, text = mod.build()
    cfg = CheckCfg()
    ctx = Ctx(text=text, key_root=mod.KEY_ROOT, quality=mod.KEY_QUALITY,
              phrases=phrases, cfg=cfg)

    clean = ctx.check(notes)
    print(f"《宇宙无边无垠》{len(notes)} 音符　原始状态：{len(clean)} findings")
    if clean:
        print("  ⚠ 源歌本身就有 findings，演示的前提不成立")

    rng = random.Random(a.seed)
    broken, log = inject(notes, rng, a.faults, cfg)
    print(f"\n=== 注入 {a.faults} 个缺陷（seed={a.seed}）===")
    for line in log:
        print("  ", line)

    fs0 = ctx.check(broken)
    print(f"\n打坏后：{len(fs0)} findings　总代价 {cost(fs0):.1f}")
    print("  " + summarize(fs0).replace("\n", "\n  "))

    print("\n=== 自修复循环 ===")
    res = repair(broken, ctx)

    if a.verbose:
        for s in res.steps:
            mark = "✓" if s.accepted else "✗"
            print(f"  {mark} 第{s.iteration:2d}轮 代价 {s.cost_before:6.1f}"
                  f"→{s.cost_after:6.1f}　{s.finding}")
            print(f"        {s.change if s.accepted else s.reason}")
    else:
        for s in res.steps:
            if s.accepted:
                print(f"  ✓ 第{s.iteration:2d}轮 {s.cost_before:6.1f}"
                      f"→{s.cost_after:6.1f}　{s.change}")
        for b in res.blacklisted:
            print(f"  ✗ 修不动，已拉黑　{b}")

    print(f"\n=== 结果 ===")
    print(f"  迭代 {len(res.steps)} 轮，其中接受 {res.accepted_steps} 次")
    print(f"  findings {len(res.initial)} → {len(res.final)}")
    print(f"  总代价   {cost(res.initial):.1f} → {cost(res.final):.1f}")

    # 有没有动到不该动的音符？
    touched = sum(1 for a_, b_ in zip(notes, res.notes)
                  if a_.midi != b_.midi
                  or abs(a_.duration_beats - b_.duration_beats) > 1e-9)
    print(f"  与原始干净版相比，{touched}/{len(notes)} 个音符不同"
          f"（注入了 {a.faults} 个缺陷）")

    if res.final:
        print("\n  残留：")
        for f in res.final:
            print("   ", f)

    print("\n" + "=" * 62)
    ok = res.converged
    print("✓ 收敛到 0 finding，全程零人工干预。" if ok
          else f"✗ 未完全收敛，还剩 {len(res.final)} 个。")
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
