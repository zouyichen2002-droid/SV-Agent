# -*- coding: utf-8 -*-
"""生成仪表盘 HTML。**薄入口** —— 逻辑全在 `svagent.dashboard` 里。

这个文件只做三件事：解析参数、调库、打印路径。将来的 CLI（建造顺序第 9 项）
也是同样的薄度。任何一行业务逻辑出现在这里都是错的。

用法:
    SVAGENT_SONG=xiaofeng python E:/sv-bridge/scripts/dashboard.py
    SVAGENT_SONG=xiaofeng python E:/sv-bridge/scripts/dashboard.py --open
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import dashboard as D


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    ap.add_argument("--refresh", type=int, default=5, help="自动刷新秒数")
    ap.add_argument("--watch", action="store_true",
                    help="盯住源文件，一变就重新生成。**这是常驻进程**，"
                         "别从聊天里的运行按钮启动，那里没法 Ctrl-C")
    ap.add_argument("--minutes", type=float, default=20.0,
                    help="监视多久后自动收工（默认 20 分钟）")
    a = ap.parse_args()

    p = D.write(refresh_s=a.refresh, live=a.watch)
    print(f"仪表盘　{p}　{p.stat().st_size} B")
    if a.open:
        import os
        os.startfile(str(p))          # noqa: S606  Windows only
        print("已在浏览器打开。")
    elif not a.watch:
        print("加 --open 直接打开，或者自己双击这个文件。")

    if a.watch:
        try:
            D.watch(refresh_s=a.refresh, minutes=a.minutes)
        except KeyboardInterrupt:
            print()
            print("停止监视。页面变回静态快照 —— 下次打开记得重新生成。")
            D.write(refresh_s=a.refresh, live=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
