# -*- coding: utf-8 -*-
"""动作层的薄入口。**逻辑全在 `svagent.agent.tools` 里。**

用法:
    python E:/sv-bridge/scripts/act.py                        # 列出动作池
    python E:/sv-bridge/scripts/act.py --schema gen_harmony   # 看某个动作的参数
    python E:/sv-bridge/scripts/act.py verify_alignment       # 跑一个动作
    python E:/sv-bridge/scripts/act.py tune --params '{"scale": 0.8}'
    python E:/sv-bridge/scripts/act.py --tools                # 导给模型的 tools 数组
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import session as S                # noqa: E402
from svagent.agent import budget as BD         # noqa: E402
from svagent.agent import tools as T           # noqa: E402

BADGE = {T.READY: "✓ 可用", T.PARTIAL: "◐ 部分", T.NEEDS_MODEL: "· 待接模型"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", nargs="?", help="要跑的动作名")
    ap.add_argument("--params", default="{}", help="JSON 参数")
    ap.add_argument("--schema", metavar="动作名", help="打印某个动作的参数表")
    ap.add_argument("--tools", action="store_true", help="打印导给模型的 tools")
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--max-actions", type=int, default=8)
    a = ap.parse_args()

    if a.tools:
        print(json.dumps(T.to_mistral_tools(), ensure_ascii=False, indent=2))
        return 0

    if a.schema:
        act = T.BY_NAME.get(a.schema)
        if act is None:
            print(f"✗ 没有 {a.schema!r}。可用：{sorted(T.BY_NAME)}")
            return 2
        print(f"{act.name}　{BADGE[act.status]}\n  {act.desc}")
        if act.note:
            print(f"  注：{act.note}")
        print(f"  写文件：{'是' if act.writes else '否（只读）'}"
              f"　钩子：{', '.join(act.hooks) or '无'}")
        print(json.dumps(act.schema, ensure_ascii=False, indent=2))
        return 0

    sess = S.Session()
    proj = sess.proj
    if not a.action:
        print(f"{proj.slug}｜{proj.title}　动作池 {len(T.ACTIONS)} 个"
              f"（导给模型 {len(T.to_mistral_tools())} 个）\n")
        for act in T.ACTIONS:
            print(f"  {BADGE[act.status]:<10}{act.name:<18}{act.desc}")
            if act.note:
                print(f"{'':<28}注：{act.note}")
        print("\n看参数：--schema <动作名>　　跑：act.py <动作名> --params '{...}'")
        return 0

    try:
        params = json.loads(a.params)
    except ValueError as e:
        print(f"✗ --params 不是合法 JSON：{e}")
        return 2

    bud = BD.Budget(seconds=a.budget, max_actions=a.max_actions,
                    stop_file=proj.stop_file)
    try:
        sess.budget = bud
        r = sess.act(a.action, params)
    except T.ToolError as e:
        print(f"✗ {e}")
        return 2
    except BD.BudgetExhausted as e:
        print(f"■ {e}")
        return 3

    print(r.report())
    if not r.ok or not r.hooks_ok:
        print("\n回退：python E:/sv-bridge/scripts/tree.py --checkout <上一个节点>")
    return 0 if (r.ok and r.hooks_ok) else 4


if __name__ == "__main__":
    raise SystemExit(main())
