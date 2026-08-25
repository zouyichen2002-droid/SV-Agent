# -*- coding: utf-8 -*-
"""第 1 项的薄入口：看五盏灯、取基线、拍快照、回滚、喊停。

**逻辑全在 `svagent.agent.safety` 里**，这个文件只解析参数、调库、打印。

用法:
    python E:/sv-bridge/scripts/safety.py                 # 看五盏灯
    python E:/sv-bridge/scripts/safety.py --adopt         # 把当前内容记成基线
    python E:/sv-bridge/scripts/safety.py --snapshot 调教前
    python E:/sv-bridge/scripts/safety.py --list
    python E:/sv-bridge/scripts/safety.py --restore c001
    python E:/sv-bridge/scripts/safety.py --stop          # 让 agent 停下
    python E:/sv-bridge/scripts/safety.py --resume
    python E:/sv-bridge/scripts/safety.py --sweep         # 清崩溃残留
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import session as S                  # noqa: E402
from svagent.agent import safety as SF            # noqa: E402
from svagent.agent import safewrite as SW         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", action="store_true",
                    help="把六个源文件的当前内容记成基线")
    ap.add_argument("--snapshot", nargs="?", const="", metavar="标签",
                    help="拍一个全套快照")
    ap.add_argument("--list", action="store_true", help="列出所有快照")
    ap.add_argument("--restore", metavar="CID", help="回滚到某个快照")
    ap.add_argument("--stop", action="store_true", help="请求停止")
    ap.add_argument("--resume", action="store_true", help="取消停止")
    ap.add_argument("--sweep", action="store_true", help="清掉崩溃残留")
    a = ap.parse_args()

    sess = S.Session()
    proj = sess.proj
    proj.agent_dir.mkdir(parents=True, exist_ok=True)

    if a.sweep:
        gone = SW.sweep_tmps(SF.watched_dirs(proj))
        print(f"清掉 {len(gone)} 个残留" if gone else "没有残留可清")

    if a.adopt:
        ext, snap, n = SF.adopt(proj)
        if ext:
            print(f"⚠ 有 {len(ext)} 个文件被外部修改，现在起**以你的版本为准**：")
            for p in ext:
                print(f"    {p}")
            print(f"  你这个版本已存进快照 {snap.cid} —— 采纳之后我就可以"
                  f"覆盖它了，被覆盖了跑 --restore {snap.cid} 找回来。")
        print(f"已把 {n} 个文件的当前内容记成基线。")
        print("  注意：这是「以现在为准」，不是「证明这些内容是我写的」——")
        print("  取基线之前的手改无法追溯。")

    if a.snapshot is not None:
        m = SF.store_of(proj).snapshot(proj.sources, label=a.snapshot)
        print(f"快照　{m.describe()}")

    if a.list:
        cps = SF.store_of(proj).list()
        print(f"{len(cps)} 个快照：" if cps else "还没有快照。")
        for m in cps:
            print("  " + m.describe())

    if a.restore:
        snap, touched = SF.rollback(proj, a.restore)
        print(f"回滚前先存了当前状态 → {snap.cid}"
              f"（后悔了跑 --restore {snap.cid}）")
        print(f"回滚到 {a.restore}，写回 {len(touched)} 个文件："
              if touched else f"回滚到 {a.restore}：内容本来就一致，没动任何文件。")
        for p in touched:
            print(f"  {p}")

    if a.stop:
        proj.stop_file.write_text("", encoding="utf-8")
        print(f"已请求停止　{proj.stop_file}")
        print("  agent 会在**下一个动作开始之前**退出，不会掐断正在写的文件。")
    if a.resume:
        proj.stop_file.unlink(missing_ok=True)
        print("已取消停止。")

    st = sess.safety()
    print(f"\n{proj.slug}｜{proj.title}　安全状态")
    print(st.report())
    return 0 if st.worst != "off" else 2


if __name__ == "__main__":
    raise SystemExit(main())
