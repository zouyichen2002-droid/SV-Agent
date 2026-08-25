# -*- coding: utf-8 -*-
"""诊断层的薄入口。**逻辑全在 `svagent.agent.diagnose` 里。**

用法:
    python E:/sv-bridge/scripts/diagnose.py "副歌不够爆"          # 只诊断 + 提案
    python E:/sv-bridge/scripts/diagnose.py "副歌不够爆" --trial  # 并行试三个假设
    python E:/sv-bridge/scripts/diagnose.py "副歌不够爆" --trial --apply

**默认不动手。** `propose_before_act = True`（架构 §8）：
先给提案，创作者点头了再加 --trial / --apply。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import project as PJ                # noqa: E402
from svagent.agent import diagnose as DG         # noqa: E402
from svagent.agent import tools as TL            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("complaint", help="一句话诉求，如「副歌不够爆」")
    ap.add_argument("--trial", action="store_true",
                    help="并行试所有假设（各自在隔离副本里，真工程不动）")
    ap.add_argument("--apply", action="store_true",
                    help="把胜出的那个应用到真工程（会在会话树上留节点）")
    ap.add_argument("--floor", type=float, default=0.5, help="置信度下限")
    ap.add_argument("--min-improvement", type=float, default=0.15)
    a = ap.parse_args()

    proj = PJ.current()
    d = DG.diagnose(proj, a.complaint, floor=a.floor)
    print(d.report())
    print()
    print("=" * 68)
    print(DG.plan(d))

    if d.should_ask or not a.trial:
        DG.save_report(d)
        if not d.should_ask:
            print("\n（加 --trial 让我并行试一遍，真工程不动）")
        return 0

    print()
    print("=" * 68)
    trials = DG.trial(proj, d.hypotheses)
    print(DG.report_trials(trials))

    best = DG.pick(trials, min_improvement=a.min_improvement)
    print()
    if best is None:
        print(f"✗ 没有一个假设达到最小改善 {a.min_improvement}，"
              "或者都有退步。**什么都不做**比乱改一个好。")
        DG.save_report(d, trials, None)
        return 0

    h = best.hypothesis
    print(f"✓ 胜出：{h.layer}层　{h.action}　"
          f"{h.metric} {best.before:g} → {best.after:g}"
          f"（{best.improvement:+g}）")
    if not a.apply:
        print("\n（加 --apply 才会写进真工程）")
        DG.save_report(d, trials, best)
        return 0

    r = TL.Runner(proj).run(h.action, h.params)
    print()
    print(r.report())
    DG.save_report(d, trials, best)
    return 0 if r.ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
