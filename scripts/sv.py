# -*- coding: utf-8 -*-
"""SV-Agent 的统一薄 CLI。**逻辑一行都不在这里。**

每个子命令只做三件事：解析参数 → 调 `Session` 的一个方法 → 打印。
出现任何计算就是错的 —— 那意味着库里少了一个方法，
而下一个前端（第 10 项的 Mistral 循环）会把同样的计算再写一遍。

**每个子命令都有 `--json`**，打印的是 `Session.to_json()` 的原物。
验收判据「同一操作经库调用与经 CLI 调用结果相同」就靠它成立：
两边比的是同一个字典。

用法:
    python E:/sv-bridge/scripts/sv.py state
    python E:/sv-bridge/scripts/sv.py safety --json
    python E:/sv-bridge/scripts/sv.py tree
    python E:/sv-bridge/scripts/sv.py metrics
    python E:/sv-bridge/scripts/sv.py facts
    python E:/sv-bridge/scripts/sv.py actions
    python E:/sv-bridge/scripts/sv.py act tune --params '{"scale": 0.8}'
    python E:/sv-bridge/scripts/sv.py why "副歌不够爆"
    python E:/sv-bridge/scripts/sv.py dash --open
    python E:/sv-bridge/scripts/sv.py --song xiaofeng state
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
from svagent.agent import budget as BD          # noqa: E402
from svagent.agent import diagnose as DG        # noqa: E402
from svagent.agent import facts as FA           # noqa: E402
from svagent.agent import metrics as MT         # noqa: E402
from svagent.agent import tools as TL           # noqa: E402

BADGE = {TL.READY: "✓ 可用", TL.PARTIAL: "◐ 部分", TL.NEEDS_MODEL: "· 待接模型"}


def _out(obj, as_json: bool, text: str) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str)
          if as_json else text)


def main() -> int:
    ap = argparse.ArgumentParser(prog="sv", description="SV-Agent 统一入口")
    ap.add_argument("--song", help="歌的 slug，默认看 SVAGENT_SONG")
    ap.add_argument("--json", action="store_true", help="打印机器可读的原物")
    # **`--json` 两处都认。** 只放顶层的话 `sv state --json` 会报错，
    # 而那正是所有人第一次会打的写法 —— 让工具去迁就手指，不是反过来。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        help="打印机器可读的原物")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, help_ in (("state", "六步状态"), ("safety", "安全五盏灯"),
                        ("metrics", "指标"), ("facts", "环境约束"),
                        ("tree", "会话树"), ("actions", "动作池"),
                        ("checks", "八项检查")):
        sub.add_parser(name, help=help_, parents=[common])

    p_act = sub.add_parser("act", help="跑一个动作", parents=[common])
    p_act.add_argument("name")
    p_act.add_argument("--params", default="{}")

    p_why = sub.add_parser("why", help="诊断一句诉求（默认只提案，不动手）",
                           parents=[common])
    p_why.add_argument("complaint")
    p_why.add_argument("--trial", action="store_true")
    p_why.add_argument("--floor", type=float, default=0.5)

    p_facts = [x for x in sub.choices if x == "facts"]        # noqa: F841
    sub.choices["facts"].add_argument(
        "--verify", action="store_true",
        help="真的跑一遍复验并落盘（这是动作，不是观察）")
    sub.choices["facts"].add_argument(
        "--all", action="store_true", help="连 slow 与 network 一起复验")

    p_dash = sub.add_parser("dash", help="生成仪表盘", parents=[common])
    p_dash.add_argument("--open", action="store_true")

    p_ci = sub.add_parser("commit", help="给当前状态存一个会话树节点",
                          parents=[common])
    p_ci.add_argument("label")

    p_co = sub.add_parser("checkout", help="回到某个节点", parents=[common])
    p_co.add_argument("node_id")

    a = ap.parse_args()
    s = S.Session(a.song, budget=BD.Budget(seconds=300, max_actions=8,
                                           stop_file=None))
    s.budget.stop_file = s.proj.stop_file

    if a.cmd == "facts" and getattr(a, "verify", False):
        costs = ((FA.FAST, FA.SLOW, FA.NETWORK) if a.all else (FA.FAST,))
        s.verify_facts(costs=costs)

    if a.cmd in ("state", "safety", "metrics", "facts", "tree",
                 "actions", "checks"):
        obj = s.to_json(a.cmd)
        text = {
            "state": lambda: s.state().report(),
            "safety": lambda: s.safety().report(),
            "metrics": lambda: MT.report(s.metrics()),
            "facts": lambda: "\n".join(
                f"  {'✅' if r.ok else ('❌' if r.ok is False else '—')} "
                f"{r.fact.id} {r.fact.domain:<6}{r.detail}"
                for r in s.facts()),
            "tree": lambda: s.tree.ascii(),
            "actions": lambda: "\n".join(
                f"  {BADGE[x.status]:<10}{x.name:<18}{x.desc}"
                for x in s.actions()),
            "checks": lambda: (f"  {len(obj['findings'])} finding\n"
                               + "\n".join(f"    {f['kind']} {f['severity']} "
                                           f"{f['where']} {f['detail']}"
                                           for f in obj["findings"])),
        }[a.cmd]()
        _out(obj, a.json, text)
        return 0

    if a.cmd == "act":
        try:
            params = json.loads(a.params)
        except ValueError as e:
            print(f"✗ --params 不是合法 JSON：{e}")
            return 2
        try:
            r = s.act(a.name, params)
        except TL.ToolError as e:
            print(f"✗ {e}")
            return 2
        except BD.BudgetExhausted as e:
            print(f"■ {e}")
            return 3
        _out(r.to_json(), a.json, r.report())
        return 0 if (r.ok and r.hooks_ok) else 4

    if a.cmd == "why":
        d = s.diagnose(a.complaint, floor=a.floor)
        obj = S.diagnosis_json(d)
        text = d.report() + "\n\n" + "=" * 68 + "\n" + s.plan(d)
        if a.trial and not d.should_ask:
            ts = s.trial(d.hypotheses)
            obj |= S.trials_json(ts)
            text += "\n\n" + "=" * 68 + "\n" + DG.report_trials(ts)
            best = DG.pick(ts)
            obj["chosen"] = None if best is None else best.hypothesis.action
            DG.save_report(d, ts, best)
        else:
            DG.save_report(d)
        _out(obj, a.json, text)
        return 0

    if a.cmd == "dash":
        p = s.dashboard()
        _out({"path": str(p), "bytes": p.stat().st_size}, a.json,
             f"仪表盘　{p}　{p.stat().st_size} B")
        if a.open:
            import os
            os.startfile(str(p))          # noqa: S606  Windows only
        return 0

    if a.cmd == "commit":
        nd = s.commit(a.label)
        _out({"id": nd.id, "parent": nd.parent, "label": nd.label}, a.json,
             f"新节点　{nd.id}　{nd.label}")
        return 0

    if a.cmd == "checkout":
        touched = s.checkout(a.node_id)
        _out({"node": a.node_id, "files": [str(x) for x in touched]}, a.json,
             f"回到 {a.node_id}，写回 {len(touched)} 个文件")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
