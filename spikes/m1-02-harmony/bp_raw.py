# -*- coding: utf-8 -*-
"""basic-pitch 在人声分轨上的原样输出（多声部）—— 挑八度（pick_octave）拿它当第二个裁判：同一时刻听到了哪几个音高。
用他们（SynthVCopilot）pi-audio 里的 extract_notes，和《傍晚》那份（basic_pitch_raw_newstem.json）同一个做法。
低优先级 + 限制 TensorFlow 线程（09-30 创作者说过「好卡啊」）；已有就不写。

    E:/sv-agent-data/envs/pi-audio/Scripts/python.exe bp_raw.py <人声.wav> <输出.json> [线程数，默认 4]
"""
from __future__ import annotations

import ctypes
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main(src: str, dst: str, threads: str = "4") -> int:
    if pathlib.Path(dst).exists():
        raise SystemExit(f"{dst} 已经有了")
    if sys.platform == "win32":
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)   # BELOW_NORMAL_PRIORITY_CLASS
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ["TF_NUM_INTRAOP_THREADS"] = threads
    os.environ["TF_NUM_INTEROP_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = threads
    sys.path.insert(0, "E:/逆向学习/synthvcopilot/pi-agent/components/pi-audio")
    import pi_audio                                               # noqa: E402  他们的模块
    notes = pi_audio.extract_notes(src)
    keep = [{"pitch": int(n["pitch"]), "start": float(n["start"]), "end": float(n["end"]), "velocity": int(n["velocity"])} for n in notes]
    pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(dst).write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    print(f"basic-pitch 原样输出 {len(keep)} 个音 → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
