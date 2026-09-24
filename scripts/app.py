# -*- coding: utf-8 -*-
"""可交互桌面程序的入口。**薄入口** —— 逻辑全在 `svagent.webapp` 里。

与 `dashboard.py` 的分工：

| | 仪表盘 `dashboard.py` | 本程序 `app.py` |
|---|---|---|
| 形态 | 生成一个静态 HTML 文件 | 常驻本地服务 |
| 能不能点 | **只读**（设计如此） | 可以跑动作 |
| 适合 | 贴给别人看、留档 | 边看边改 |

**这是常驻进程**，Ctrl-C 停。

用法:
    python E:/sv-bridge/scripts/app.py
    python E:/sv-bridge/scripts/app.py --port 9000 --no-open
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import webapp as W


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="不自动开浏览器")
    a = ap.parse_args()

    try:
        srv = W.serve(port=a.port, open_browser=not a.no_open)
    except OSError as e:
        print(f"起不来：{e}")
        print(f"多半是 {a.port} 被占了。换一个：--port {a.port + 1}")
        return 1

    print(f"SV-Agent　http://127.0.0.1:{a.port}/")
    print(f"歌：{len(W.songs())} 首　真歌语料：{W.REAL_N} 首"
          if W.REAL_N else
          f"歌：{len(W.songs())} 首　真歌语料：没有（分位那栏会空着）")
    print("只听 127.0.0.1 —— 局域网里别的机器连不上。")
    print("Ctrl-C 停。")
    try:
        import threading
        threading.Event().wait()
    except KeyboardInterrupt:
        print()
        print("停了。")
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
