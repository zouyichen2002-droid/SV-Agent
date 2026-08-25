# -*- coding: utf-8 -*-
"""环境事实清单的薄入口。**逻辑全在 `svagent.agent.facts` 里。**

用法:
    python E:/sv-bridge/scripts/facts.py             # 复验（只跑 fast）
    python E:/sv-bridge/scripts/facts.py --all       # 连 slow 和 network 一起跑
    python E:/sv-bridge/scripts/facts.py --write     # 重新生成 specs/facts.md
    python E:/sv-bridge/scripts/facts.py --prompt    # 打印给模型看的那一版
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent.agent import facts as F         # noqa: E402

MARK = {True: "✅", False: "❌", None: "—"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="连 slow（要渲染音频）和 network（吃一次限流配额）一起跑")
    ap.add_argument("--write", action="store_true", help="重新生成 specs/facts.md")
    ap.add_argument("--prompt", action="store_true", help="打印给模型看的版本")
    a = ap.parse_args()

    if a.prompt:
        print(F.for_prompt())
        return 0

    costs = (F.FAST, F.SLOW, F.NETWORK) if a.all else (F.FAST,)
    from svagent import session as S
    rs = S.Session().verify_facts(costs=costs)
    for r in rs:
        print(f"  {MARK[r.ok]} {r.fact.id} {r.fact.domain:<6}{r.detail}")
    s = F.summary(rs)
    print(f"\n共 {s['total']} 条：{s['verified']} 条复验通过 · "
          f"{s['failed']} 条失败 · {s['skipped']} 条跳过 · "
          f"{s['unverifiable']} 条不可自动复验")
    if not a.all:
        print("  （加 --all 连 slow 与 network 一起跑）")

    if a.write:
        p = F.write_markdown(results=rs)
        print(f"\n已重新生成 {p}")
    return 2 if s["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
