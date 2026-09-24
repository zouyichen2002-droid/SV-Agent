# -*- coding: utf-8 -*-
"""M0-01 测量协议（PRD §8.1）。

冷启动  每次起一个新 Python 进程：解释器启动 + import + 载入音源 + 渲染 + 写盘。各 5 次。
        操作系统的文件缓存是热的 —— 真正的冷启动（刚开机）这里测不到，记录里写明。
热启动  一个常驻进程里先载入一次音源，再连续渲染 20 次，模拟 PRD 里的常驻 worker。
        每次计时 = 渲染 + 写 WAV，即「点击试听」到「文件可播」。
        判据：20 次里至少 19 次 ≤ 30 秒。
失败    任何异常都记为失败并写进报告，不跳过、不重试。
确定性  同一份音符渲染两次，输出必须逐样本相同 —— A/B 比较公平的前提（R05）。

用法：python measure.py
产物：out/sample_additive.wav · out/sample_gmdls.wav · out/sample.mid · out/measurements.json
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import traceback
import wave

import numpy as np

import renderers
import sample

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
COLD_RUNS, HOT_RUNS, TARGET_S = 5, 20, 30.0


def cold(name):
    times, fails = [], []
    path = os.path.join(OUT, f"_cold_{name}.wav")
    for i in range(COLD_RUNS):
        if os.path.exists(path):
            os.remove(path)
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, "renderers.py", name, path],
                           cwd=HERE, capture_output=True, text=True)
        dt = time.perf_counter() - t0
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 44:
            times.append(dt)
        else:
            fails.append({"run": i, "returncode": r.returncode, "stderr": r.stderr[-500:]})
    if os.path.exists(path):
        os.remove(path)
    return times, fails


def hot(name):
    t0 = time.perf_counter()
    rend = renderers.RENDERERS[name]().load()
    load_s = time.perf_counter() - t0
    notes = sample.notes_in_seconds()
    path = os.path.join(OUT, f"sample_{name}.wav")
    times, fails, level = [], [], None
    for i in range(HOT_RUNS):
        try:
            t0 = time.perf_counter()
            audio = rend.render(notes)
            peak, rms, clipped = renderers.write_wav(path, audio)
            times.append(time.perf_counter() - t0)
            level = {"peak_dbfs": round(peak, 2), "rms_dbfs": round(rms, 2), "clipped_samples": clipped}
        except Exception:
            fails.append({"run": i, "error": traceback.format_exc()[-500:]})
    a, b = rend.render(notes), rend.render(notes)
    deterministic = a.shape == b.shape and bool(np.array_equal(a, b))
    return load_s, times, fails, level, deterministic, path


def readback(path):
    """把写出去的 WAV 读回来核对：能打开、格式对、时长对。"""
    with wave.open(path, "rb") as w:
        return {"channels": w.getnchannels(), "sample_rate": w.getframerate(),
                "bits": w.getsampwidth() * 8, "seconds": round(w.getnframes() / w.getframerate(), 3)}


def stats(times):
    if not times:
        return {"n": 0}
    s = sorted(times)
    return {"n": len(s), "min": round(s[0], 4), "median": round(statistics.median(s), 4),
            "max": round(s[-1], 4), "mean": round(statistics.fmean(s), 4)}


def cpu_name():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or platform.processor()
    except Exception:
        return platform.processor()


def main():
    os.makedirs(OUT, exist_ok=True)
    sample.write_mid(os.path.join(OUT, "sample.mid"))
    notes = sample.notes_in_seconds()
    report = {
        "conditions": {
            "cpu": cpu_name(),
            "os": platform.platform(),
            "python": sys.version.split()[0],
            "python_exe": sys.executable,
            "numpy": np.__version__,
            "gm_dls_sha256": hashlib.sha256(open(renderers.GmDlsPiano.PATH, "rb").read()).hexdigest(),
            "sample": {"bars": sample.BARS, "bpm": sample.BPM, "notes": len(notes),
                       "music_seconds": round(sample.duration_seconds(), 3)},
            "output_format": "WAV 44100 Hz / 16-bit / mono",
            "target_seconds": TARGET_S,
        },
        "renderers": {},
    }
    for name in renderers.RENDERERS:
        load_s, hot_times, hot_fails, level, deterministic, path = hot(name)
        cold_times, cold_fails = cold(name)
        rb = readback(path)
        report["renderers"][name] = {
            "load_seconds": round(load_s, 4),
            "hot": stats(hot_times),
            "hot_within_target": f"{sum(t <= TARGET_S for t in hot_times)}/{HOT_RUNS}",
            "hot_realtime_factor": round(statistics.median(hot_times) / rb["seconds"], 5) if hot_times else None,
            "cold": stats(cold_times),
            "failures": {"hot": hot_fails, "cold": cold_fails},
            "level": level,
            "deterministic": deterministic,
            "wav": {"path": path, **rb},
        }

    with open(os.path.join(OUT, "measurements.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    c = report["conditions"]
    print(f"{c['cpu']} | Python {c['python']} | numpy {c['numpy']}")
    print(f"sample: {c['sample']['bars']} bars @ {c['sample']['bpm']} BPM, "
          f"{c['sample']['notes']} notes, {c['sample']['music_seconds']} s")
    print(f"{'renderer':9s} {'load':>7s} {'hot med':>8s} {'hot max':>8s} {'<=30s':>6s} "
          f"{'cold med':>9s} {'cold max':>9s} {'fails':>5s} {'peak':>6s} {'rms':>6s} {'clip':>4s} det")
    for name, r in report["renderers"].items():
        nf = len(r["failures"]["hot"]) + len(r["failures"]["cold"])
        lv = r["level"] or {}
        print(f"{name:9s} {r['load_seconds']:7.3f} {r['hot'].get('median', float('nan')):8.3f} "
              f"{r['hot'].get('max', float('nan')):8.3f} {r['hot_within_target']:>6s} "
              f"{r['cold'].get('median', float('nan')):9.3f} {r['cold'].get('max', float('nan')):9.3f} "
              f"{nf:5d} {lv.get('peak_dbfs', float('nan')):6.1f} {lv.get('rms_dbfs', float('nan')):6.1f} "
              f"{lv.get('clipped_samples', -1):4d} {r['deterministic']}")


if __name__ == "__main__":
    main()
