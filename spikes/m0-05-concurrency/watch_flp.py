# -*- coding: utf-8 -*-
"""M0-05 · FL 这一轮的监视程序：你在 FL 里操作，我这边的动作全自动。

两个问题：
  A. FL 开着 flp_open.flp 时，我在磁盘上改它的速度，FL 会不会发现？你一保存，我的改动还在不在？
  B. FL 开着的时候，我用命令行导出**另一个**工程（flp_render.flp），会不会打扰你正在用的 FL？

时间线：
  1. 等 flp_open.flp 第一次被保存 —— 这是你给我的信号：「FL 已经把它打开了」
  2. 过 1 秒，在磁盘上把速度 140 改成 96（事件 156，值 = BPM × 1000，M0-03 验证过；原子写）
  3. 等你改点别的（比如加一个音符）再保存 → 读文件里的速度：
        140 → FL 用内存里的版本整个覆盖了，我的改动没了
        96  → FL 重新读过盘，我的改动在
  4. 你保存后 3 秒，用命令行导出 flp_render.flp，同时记下 FL 进程在导出前后的变化，
     以及 WAV 出不出得来 —— 如果 FL 是单实例的，命令可能被转交给你开着的那个 FL

结果写到 out/flp_result.json。参数：最多等几分钟（默认 60）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(HERE, "..", "m0-03-flp"))
import flp  # noqa: E402

FL = r"G:\FL Studio\FL64.exe"
OPEN = os.path.join(OUT, "flp_open.flp")
RENDER_SRC = os.path.join(OUT, "flp_render.flp")
RENDER_DIR = os.path.join(OUT, "render")
TEMPO_ID = 156
TIMEOUT_S = 60 * float(sys.argv[1]) if len(sys.argv) > 1 else 60 * 60


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def tempo(path):
    f = flp.read(path)
    vals = [e.value for e in f.events if e.id == TEMPO_ID]
    return (vals[0] / 1000 if len(vals) == 1 else None), f.structure_ok


def fl_pids():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-Process -Name FL64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }"],
                       capture_output=True, text=True)
    return sorted(int(x) for x in r.stdout.split())


def wait_saved(since_t, not_hash, deadline):
    """等文件在 since_t 之后被改写（not_hash 不为空时还要求内容变了）、并且大小稳定 2 秒。

    信号那一步 not_hash 传 None：FL 保存一个没改过的工程，内容可能一个字节都不变，只看修改时间。
    """
    stable = None
    while time.time() < deadline:
        if os.path.getmtime(OPEN) > since_t and (not_hash is None or sha(OPEN) != not_hash):
            size = os.path.getsize(OPEN)
            if stable and stable[0] == size and time.time() - stable[1] >= 2:
                return True
            stable = stable if stable and stable[0] == size else (size, time.time())
        time.sleep(1)
    return False


def main():
    t0 = time.time()
    deadline = t0 + TIMEOUT_S
    result = {"started": time.strftime("%H:%M:%S")}
    h0 = sha(OPEN)
    print(f"开始监视 {result['started']}：等你在 FL 里第一次保存 flp_open.flp（信号）", flush=True)

    if not wait_saved(t0, None, deadline):
        result["timed_out"] = "等第一次保存（信号）"
    else:
        result["signal_at"] = time.strftime("%H:%M:%S")
        result["tempo_at_signal"] = tempo(OPEN)[0]
        time.sleep(1)
        f = flp.read(OPEN)
        ev = [e for e in f.events if e.id == TEMPO_ID]
        if not f.structure_ok or len(ev) != 1:
            # 第一次跑就死在这里：读取器读不对 FL 2025 存的文件（172 号事件）。读不懂就明说，不去改它
            result["error"] = (f"读不懂 FL 刚存的文件：结构 {'对' if f.structure_ok else '错'}"
                               f"（假事件串 {f.fake_run}）· 速度事件 {len(ev)} 个 · FL 构建 {f.build}")
            print(f"  ✗ {result['error']}，不改它，停。", flush=True)
            with open(os.path.join(OUT, "flp_result.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=1)
            return
        tmp = OPEN + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(flp.with_value(f, ev[0], 96000))
        os.replace(tmp, OPEN)
        h_ext, t_ext = sha(OPEN), time.time()
        result["external_edit_at"] = time.strftime("%H:%M:%S")
        print(f"  {result['signal_at']} 收到信号（当时速度 {result['tempo_at_signal']}）；"
              f"{result['external_edit_at']} 已在磁盘上把速度改成 96。等你改点别的再保存……", flush=True)

        if not wait_saved(t_ext, h_ext, deadline):
            result["timed_out"] = "等你第二次保存"
        else:
            bpm, ok = tempo(OPEN)
            result["saved"] = {"at": time.strftime("%H:%M:%S"), "bpm": bpm, "structure_ok": ok,
                               "size": os.path.getsize(OPEN),
                               "verdict": ("我的外部改动被静悄悄盖掉了（FL 用内存版本覆盖）" if bpm == 140 else
                                           "我的外部改动还在（FL 重新读过盘）" if bpm == 96 else "其他情况，看原始数据")}
            print(f"  {result['saved']['at']} 你保存了：速度 {bpm} → {result['saved']['verdict']}", flush=True)

            time.sleep(3)
            wav = os.path.join(RENDER_DIR, "flp_render.wav")
            if os.path.exists(wav):
                os.remove(wav)
            before = fl_pids()
            ts = time.time()
            result["cli_render"] = {"at": time.strftime("%H:%M:%S"), "fl_pids_before": before}
            print(f"  {result['cli_render']['at']} FL 开着，开始用命令行导出 flp_render.flp（FL 进程 {before}）", flush=True)
            try:
                p = subprocess.Popen([FL, "/R", "/Ewav", "/O" + RENDER_DIR, RENDER_SRC])
                code = p.wait(timeout=120)
            except subprocess.TimeoutExpired:
                p.kill()
                code = "超时 120 秒，已结束这个命令行进程"
            result["cli_render"]["exit"] = code
            result["cli_render"]["process_seconds"] = round(time.time() - ts, 1)
            got = None
            while time.time() - ts < 180 and not got:   # 命令可能被转交给开着的 FL，异步写出
                if os.path.exists(wav) and os.path.getsize(wav) > 44:
                    got = round(time.time() - ts, 1)
                time.sleep(1)
            result["cli_render"]["wav_after_seconds"] = got
            result["cli_render"]["fl_pids_after"] = fl_pids()
            print(f"  命令行进程 {result['cli_render']['process_seconds']} 秒后结束（{code}）；"
                  f"WAV {'在 ' + str(got) + ' 秒时出现' if got else '180 秒内没出现'}；"
                  f"FL 进程 之前 {before} → 之后 {result['cli_render']['fl_pids_after']}", flush=True)

    with open(os.path.join(OUT, "flp_result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
