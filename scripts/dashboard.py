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
    a = ap.parse_args()

    p = D.write(refresh_s=a.refresh)
    print(f"仪表盘　{p}　{p.stat().st_size} B")
    if a.open:
        import os
        os.startfile(str(p))          # noqa: S606  Windows only
        print("已在浏览器打开。")
    else:
        print("加 --open 直接打开，或者自己双击这个文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
