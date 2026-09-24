# -*- coding: utf-8 -*-
"""用 FL Studio 的命令行当「裁判」。

官方手册「Command line export options」一节：
    /R[文件名]   导出音频      /E<格式>   导出格式，如 /Ewav
    /O<文件夹>   输出文件夹    /M<文件夹或文件名>   导出 MIDI

实测（2026-09-24，FL Studio 25.2.5.5319）：
    /R /Ewav /O<文件夹> <工程>    能用
    /M<单个工程>                  能用，MIDI 写在工程旁边、同名
    /M<文件夹>                    **不能用**：退出码 0，一个文件都不产出 —— 和手册说的不一样

**只看退出码会被骗**：/M<文件夹> 退出码也是 0。所以这里一律检查产物在不在。
"""
from __future__ import annotations

import os
import subprocess
import time

FL = r"G:\FL Studio\FL64.exe"


def export_midi(flp_path, timeout=240):
    """让 FL 把一个工程导出成 MIDI → (MIDI 路径, 耗时秒)。没产出就抛错，不看退出码。"""
    mid = os.path.splitext(flp_path)[0] + ".mid"
    if os.path.exists(mid):
        os.remove(mid)
    t0 = time.perf_counter()
    subprocess.run([FL, "/M" + flp_path], timeout=timeout)
    dt = time.perf_counter() - t0
    if not os.path.exists(mid):
        raise RuntimeError(f"FL 没有产出 MIDI：{mid}（{dt:.1f} 秒）")
    return mid, dt


def export_wav(flp_path, out_dir, timeout=600):
    """让 FL 把一个工程导出成 WAV → (WAV 路径, 耗时秒)。没产出就抛错。"""
    wav = os.path.join(out_dir, os.path.splitext(os.path.basename(flp_path))[0] + ".wav")
    if os.path.exists(wav):
        os.remove(wav)
    t0 = time.perf_counter()
    subprocess.run([FL, "/R", "/Ewav", "/O" + out_dir, flp_path], timeout=timeout)
    dt = time.perf_counter() - t0
    if not os.path.exists(wav):
        raise RuntimeError(f"FL 没有产出 WAV：{wav}（{dt:.1f} 秒）")
    return wav, dt


def midi_tempo(mid_path):
    """FL 导出的 MIDI 里的速度 → (PPQ, 所有 set_tempo 的 BPM 列表)。"""
    import mido

    m = mido.MidiFile(mid_path)
    bpms = [mido.tempo2bpm(msg.tempo) for tr in m.tracks for msg in tr if msg.type == "set_tempo"]
    return m.ticks_per_beat, bpms
