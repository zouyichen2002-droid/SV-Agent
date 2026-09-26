# -*- coding: utf-8 -*-
"""FL 开着的时候用命令行导出另一个工程，会不会打扰你正在用的那个 FL？—— 全自动，不用你操作。

上一轮的监视程序记下的「FL 进程列表」在 FL 明明开着的时候也是空的 —— 那个探针本身不可信，
所以这里单独测，而且**先证明探针能看见 FL**，再拿它下结论：

  1. 打开 FL（开着 flp_open.flp），等窗口标题里出现「flp_open」—— 探针看得见，才往下走
  2. 用命令行导出 flp_render.flp；导出全程每 0.3 秒记一次：所有 FL 进程、各自的窗口标题
  3. 判断：
       有没有冒出第二个 FL 进程            → 命令行导出是另起一个 FL，还是转交给开着的那个
       开着的那个窗口，标题里的工程名变没变  → 你正在编辑的工程有没有被悄悄换掉
       WAV 出没出来
  4. 结束后温和地关掉开着的那个 FL（等同点关闭按钮）；关不掉就留给你关

结果写到 out/cli_while_open.json。
"""
from __future__ import annotations

import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
FL = r"G:\FL Studio\FL64.exe"
OPEN = os.path.join(OUT, "flp_open.flp")
RENDER = os.path.join(OUT, "flp_render.flp")
RENDER_DIR = os.path.join(OUT, "render")
WAV = os.path.join(RENDER_DIR, "flp_render.wav")

PS_LIST = ("Get-Process | Where-Object { $_.ProcessName -like 'FL*' } | "
           "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessName, $_.Id, $_.MainWindowTitle }")


def fl_procs():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_LIST], capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        name, pid, title = (line.split("|", 2) + ["", ""])[:3]
        if pid.strip().isdigit():
            out.append({"name": name, "pid": int(pid), "title": title.strip()})
    return out


def main():
    res = {}
    if fl_procs():
        res["error"] = "测试前 FL 已经开着 —— 先关掉再测"
    else:
        gui = subprocess.Popen([FL, OPEN])
        t0 = time.time()
        seen = []
        while time.time() - t0 < 90:
            seen = fl_procs()
            if any("flp_open" in p["title"] for p in seen):
                break
            time.sleep(1)
        res["gui_ready_seconds"] = round(time.time() - t0, 1)
        res["before"] = seen
        if not any("flp_open" in p["title"] for p in seen):
            res["error"] = "90 秒内窗口标题里没出现 flp_open —— 探针看不见 FL，下面的结论不可信"
        else:
            gui_pid = next(p["pid"] for p in seen if "flp_open" in p["title"])
            if os.path.exists(WAV):
                os.remove(WAV)
            timeline = []
            ts = time.time()
            cli = subprocess.Popen([FL, "/R", "/Ewav", "/O" + RENDER_DIR, RENDER])
            while time.time() - ts < 60:
                snap = fl_procs()
                timeline.append({"t": round(time.time() - ts, 1), "procs": snap,
                                 "cli_alive": cli.poll() is None, "wav": os.path.exists(WAV)})
                if cli.poll() is not None and os.path.exists(WAV) and time.time() - ts > 3:
                    break
                time.sleep(0.3)
            time.sleep(2)
            after = fl_procs()
            titles_of_gui = sorted({p["title"] for s in timeline for p in s["procs"] if p["pid"] == gui_pid})
            other_pids = sorted({p["pid"] for s in timeline for p in s["procs"] if p["pid"] != gui_pid})
            res.update({
                "gui_pid": gui_pid, "cli_pid": cli.pid, "cli_exit": cli.poll(),
                "cli_seconds": next((s["t"] for s in timeline if not s["cli_alive"]), None),
                "wav_seconds": next((s["t"] for s in timeline if s["wav"]), None),
                "other_fl_pids_seen": other_pids,
                "gui_titles_seen": titles_of_gui,
                "after": after,
                "samples": len(timeline),
            })
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-Process -Id {gui_pid} -ErrorAction SilentlyContinue).CloseMainWindow() | Out-Null"])
            time.sleep(15)
            res["gui_closed"] = not any(p["pid"] == gui_pid for p in fl_procs())
    with open(os.path.join(OUT, "cli_while_open.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ("before", "after")}, ensure_ascii=False, indent=1))
    print("before:", res.get("before"))
    print("after:", res.get("after"))


if __name__ == "__main__":
    main()
