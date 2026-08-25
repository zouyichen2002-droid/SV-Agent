# -*- coding: utf-8 -*-
"""会话树的薄入口。**逻辑全在 `svagent.agent.tree` 里。**

用法:
    python E:/sv-bridge/scripts/tree.py                        # 画树
    python E:/sv-bridge/scripts/tree.py --commit "调教前的基线"
    python E:/sv-bridge/scripts/tree.py --checkout n0003
    python E:/sv-bridge/scripts/tree.py --label n0003 "副歌抬高三度"
    python E:/sv-bridge/scripts/tree.py --verdict n0003 rejected "太满了"
    python E:/sv-bridge/scripts/tree.py --rejected             # 否决记忆
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import project as PJ            # noqa: E402
from svagent.agent import tree as TR         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", metavar="标签", help="给当前状态存一个节点")
    ap.add_argument("--checkout", metavar="ID", help="回到某个节点")
    ap.add_argument("--label", nargs=2, metavar=("ID", "文本"))
    ap.add_argument("--verdict", nargs="+",
                    metavar="ID accepted|rejected [原话]")
    ap.add_argument("--rejected", action="store_true", help="列出被否决的分支")
    a = ap.parse_args()

    proj = PJ.current()
    t = TR.Tree(proj)

    try:
        if a.commit:
            nd = t.commit(a.commit)
            print(f"新节点　{nd.id}　{nd.label}"
                  + (f"　父 {nd.parent}" if nd.parent else "　（根）"))
        if a.checkout:
            touched = t.checkout(a.checkout)
            print(f"回到 {a.checkout}，写回 {len(touched)} 个文件"
                  if touched else f"回到 {a.checkout}：文件本来就一致")
            for p in touched:
                print(f"  {p}")
        if a.label:
            t.label(a.label[0], a.label[1])
            print(f"{a.label[0]} 改名为「{a.label[1]}」")
        if a.verdict:
            nid, v = a.verdict[0], a.verdict[1]
            note = " ".join(a.verdict[2:])
            t.verdict(nid, v, note)
            print(f"{nid} 裁决为 {v}" + (f"：「{note}」" if note else ""))
    except TR.TreeError as e:
        print(f"✗ {e}")
        return 2

    if a.rejected:
        bad = t.rejected()
        print(f"\n{len(bad)} 个被否决的分支：" if bad else "\n还没有被否决的分支。")
        for n in bad:
            print(f"  {n.id}　{n.label}"
                  + (f"　「{n.verdict_note}」" if n.verdict_note else ""))
            if n.spec_snapshot:
                print(f"      规格 {n.spec_snapshot}")
        return 0

    print(f"\n{proj.slug}｜{proj.title}　会话树"
          + ("　**有未提交的改动**" if t.is_dirty() else ""))
    print(t.ascii())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
