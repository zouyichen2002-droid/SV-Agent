# -*- coding: utf-8 -*-
"""跑「他们的翻唱」—— SynthVCopilot pi-agent 的 pi-audio `pair-diff`（Apache-2.0）—— 外加一个对照做法。

创作者 09-28：「他们」= github.com/SynthVCopilot；要看他们的翻唱能不能实现「人声轨 → 主旋律」。

五种做法，各出一份 MIDI：
1. **他们的 pair-diff 默认模式**：有人声版 − 伴奏版（basic-pitch 扒两边、按 (音高, 起点±80ms) 一对一扣掉伴奏、C3–C6、最高音单声部化）
2. **他们的 pair-diff 高级模式**（`--advanced`）：5 个容差择优 + 八度修正 + 合并重复音 + 置信度
3. **对照**：Suno 已经给了干净的人声分轨，直接 basic-pitch 扒它，再套他们**同一套**单声部化和修正函数（导入他们的函数，不重写）
4. **他们工具箱里的新版**（synthv-toolbox 自带的 pi-audio）：不给伴奏，直接扒人声分轨（扒音核心和 1–3 一样，单声部化改了接缝）
5. **同上 + 你给的歌词**（`--lyrics-file`）：歌词按顺序一个字一个音填进去（给了第 4 个参数才跑）。
   `--transcribe`（whisper 自动听歌词）要另外下载模型，没跑

「有人声版」：手上没有 Suno 的整首混音（`Voice1_02.wav` 实测约等于人声分轨，伴奏系数 0），
所以用两条分轨相加当作有人声版。

必须用 pi-audio 的环境跑（Python 3.11 + basic-pitch + TensorFlow）：
    E:/sv-agent-data/envs/pi-audio/Scripts/python.exe run_theirs.py <人声分轨> <伴奏分轨> <输出目录> [<歌词.txt>]
输入只读；产物写在 <输出目录>（仓库外）。pi-agent 版会把 MIDI 写进 ~/.SynthVcopilot/output/，这里再拷一份过来；
工具箱版用它自己的 `--output-external` 直接写进 <输出目录>。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import numpy as np
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
PI_AUDIO = pathlib.Path("E:/逆向学习/synthvcopilot/pi-agent/components/pi-audio")
TOOLBOX_PI_AUDIO = pathlib.Path("E:/逆向学习/synthvcopilot/synthv-toolbox/src/PiDesktop.Tauri/components/pi-audio")
sys.path.insert(0, str(PI_AUDIO))
import pi_audio  # noqa: E402  他们的模块


def make_mix(lead: pathlib.Path, inst: pathlib.Path, out: pathlib.Path) -> dict:
    a, sr = sf.read(str(lead), dtype="float32")
    b, sr2 = sf.read(str(inst), dtype="float32")
    assert sr == sr2, f"采样率不一样：{sr} / {sr2}"
    n = min(len(a), len(b))
    mix = a[:n] + b[:n]
    peak = float(np.max(np.abs(mix)))
    scale = 0.99 / peak if peak > 0.99 else 1.0          # 只整体缩小防削波，不改音符内容
    sf.write(str(out), mix * scale, sr, subtype="PCM_16")
    return {"seconds": n / sr, "sr": sr, "peak_before": round(peak, 3), "scale": round(scale, 3)}


def run_pair_diff(vocal: pathlib.Path, inst: pathlib.Path, name: str, advanced: bool) -> dict:
    cmd = [sys.executable, str(PI_AUDIO / "pi_audio.py"), "pair-diff", str(vocal), str(inst), "--midi", name]
    if advanced:
        cmd.append("--advanced")
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(PI_AUDIO))
    secs = time.perf_counter() - t0
    if r.returncode != 0:
        return {"ok": False, "seconds": secs, "stderr": r.stderr[-800:]}
    out = json.loads(r.stdout[r.stdout.find("{"):])
    out.update(ok=True, seconds=round(secs, 1))
    return out


def run_toolbox(vocal: pathlib.Path, out_mid: pathlib.Path, lyrics: pathlib.Path | None) -> dict:
    """工具箱版 pair-diff，不给伴奏。它用独占方式新建文件（已存在就报错），所以先写临时名再换过去。"""
    tmp = out_mid.with_name(f"{out_mid.stem}.tmp-{os.getpid()}.mid")
    cmd = [sys.executable, str(TOOLBOX_PI_AUDIO / "pi_audio.py"), "pair-diff", str(vocal),
           "--midi", str(tmp), "--output-external"]
    if lyrics:
        cmd += ["--lyrics-file", str(lyrics)]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(TOOLBOX_PI_AUDIO))
    secs = time.perf_counter() - t0
    if r.returncode != 0:
        return {"ok": False, "seconds": round(secs, 1), "stderr": (r.stderr + r.stdout)[-800:]}
    out = json.loads(r.stdout[r.stdout.find("{"):])
    os.replace(tmp, out_mid)
    out.update(ok=True, seconds=round(secs, 1), midi_out=str(out_mid))
    return out


def direct(lead: pathlib.Path, out_mid: pathlib.Path) -> dict:
    import pretty_midi
    t0 = time.perf_counter()
    notes = pi_audio.extract_notes(str(lead))
    in_range = [n for n in notes if 48 <= n["pitch"] <= 84]
    mono = pi_audio.mono_collapse(in_range)
    corrected, corrections = pi_audio.automatic_correct(mono)
    pm = pretty_midi.PrettyMIDI()
    ins = pretty_midi.Instrument(program=54, name="vocal-mono")
    for n in corrected:
        ins.notes.append(pretty_midi.Note(velocity=max(1, min(127, int(n.get("velocity", 90)))),
                                          pitch=n["pitch"], start=n["start"], end=n["end"]))
    pm.instruments.append(ins)
    pm.write(str(out_mid))
    return {"ok": True, "seconds": round(time.perf_counter() - t0, 1), "raw_notes": len(notes),
            "in_C3_C6": len(in_range), "mono": len(mono), "after_corrections": len(corrected),
            "corrections": corrections, "midi_out": str(out_mid)}


def main(lead: str, inst: str, out_dir: str, lyrics: str | None = None) -> int:
    lead_p, inst_p, out = pathlib.Path(lead), pathlib.Path(inst), pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mix = out / "m1-01_mix_lead+inst.wav"
    info = {"mix": make_mix(lead_p, inst_p, mix)}
    print(f"有人声版（两条分轨相加）：{info['mix']['seconds']:.1f} 秒 · 峰值 {info['mix']['peak_before']} · 缩放 {info['mix']['scale']}")

    for name, adv in (("m1-01_theirs_default", False), ("m1-01_theirs_advanced", True)):
        r = run_pair_diff(mix, inst_p, name, adv)
        info[name] = r
        if r["ok"]:
            shutil.copy2(r["midi_out"], out / f"{name}.mid")
            conf = r.get("advanced", {}).get("confidence", {})
            print(f"他们的 pair-diff{'（高级）' if adv else '（默认）'}：{r['seconds']} 秒 · 有人声版 {r['vocal_notes']} 音、"
                  f"伴奏 {r['inst_notes']} 音、扣掉 {r['matched_to_inst']} · 单声部 {r['mono_notes']} 音"
                  + (f" · 置信度 {conf.get('score')}（{conf.get('level')}）" if conf else ""))
        else:
            print(f"他们的 pair-diff{'（高级）' if adv else '（默认）'} 失败：{r['stderr'][-300:]}")

    d = direct(lead_p, out / "m1-01_direct_lead.mid")
    info["m1-01_direct_lead"] = d
    print(f"对照（直接扒人声分轨 + 他们的单声部化和修正）：{d['seconds']} 秒 · 原始 {d['raw_notes']} 音 → 单声部 {d['mono']} → 修正后 {d['after_corrections']}")

    jobs = [("m1-01_toolbox_direct", None)] + ([("m1-01_toolbox_direct_lyrics", pathlib.Path(lyrics))] if lyrics else [])
    for name, ly in jobs:
        r = run_toolbox(lead_p, out / f"{name}.mid", ly)
        info[name] = r
        if r["ok"]:
            print(f"工具箱版（不给伴奏{' · 填歌词' if ly else ''}）：{r['seconds']} 秒 · 原始 {r['vocal_notes']} 音 → 单声部 {r['mono_notes']}"
                  + (f" · 歌词 {r['lyric_tokens']} 个字、补「-」{r['lyric_fill_hyphens']} 个" if ly else ""))
        else:
            print(f"工具箱版失败：{r['stderr'][-300:]}")
    (out / "m1-01_run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n产物：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:5]))
