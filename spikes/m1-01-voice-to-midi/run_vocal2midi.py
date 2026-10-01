# -*- coding: utf-8 -*-
"""跑 Vocal2Midi（github.com/Xiantaidu/Vocal2Midi，Apache-2.0）的流水线，不开它的界面。

创作者 09-29：要找 GitHub 上最新的人声 → MIDI 方法，选了直接测 Vocal2Midi。
它的扒音核心是 openvpi 的 GAME（MIT，SOME 的下一代）；带歌词模式再加听写歌词（Qwen3-ASR）+ 按字强制对齐（HubertFA），
让 GAME 按字切音。

三种模式：
- 不带歌词（默认）：只用 GAME，模型 `models/GAME-1.0.3-medium-onnx`
- 带歌词、只靠听写（`--asr`）：还要 Qwen3-ASR（`models/Qwen3-ASR-1.7B-dml`）、HubertFA（`models/1218_hfa_model_new_dict`）
  和 llama.cpp 的 DLL（`inference/qwen3asr_dml/bin/`，b9174 —— 它的 llama.py 写死了结构体，2026-01-08 到 05-11 之间的 llama.h 才对得上）
- 带歌词、给原歌词（`--lyrics 歌词.txt`）：同上，再拿原歌词去对听写结果

参数照它界面的默认值：D3PM 起点 0、8 步；边界阈值 0.2、半径 0.02；音符阈值 0.2；**不量化**（量化会把音吸到网格上，比对时要原始时间）。

必须用它自己的环境跑：
    E:/sv-agent-data/envs/vocal2midi/Scripts/python.exe run_vocal2midi.py <人声.wav> <输出目录> <输出名> [--asr | --lyrics 歌词.txt] [--device dml|cpu]
输入只读；产物写在 <输出目录>（仓库外）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
V2M = pathlib.Path("E:/sv-agent-data/tools/Vocal2Midi")
sys.path.insert(0, str(V2M))


def _stub_pyopenjtalk(language: str = "zh") -> None:
    """它的歌词模块一加载就 import pyopenjtalk（只有日语用），而 Windows 上没有现成的包。
    日语：换成 fugashi + unidic-lite 做的替身（ja_g2p_fugashi.py，10-01）；别的语言放一个占位 ——
    不改它的代码；万一真走到日语那条路，直接报错，不会悄悄出错。"""
    try:
        import pyopenjtalk  # noqa: F401
    except ImportError:
        if language == "ja":
            import ja_g2p_fugashi
            ja_g2p_fugashi.install()
            return
        import types
        stub = types.ModuleType("pyopenjtalk")

        def _unavailable(*_a, **_k):
            raise RuntimeError("pyopenjtalk 没装（Windows 没有现成的包），只有日语歌词要用它")
        stub.run_frontend = stub.g2p = _unavailable
        sys.modules["pyopenjtalk"] = stub


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out_dir")
    ap.add_argument("name")
    ap.add_argument("--asr", action="store_true", help="带歌词模式，但不给原歌词：全靠它自己听写")
    ap.add_argument("--lyrics", help="原歌词文本（UTF-8）；给了就走带歌词模式，并拿它去对听写结果")
    ap.add_argument("--language", default="zh", choices=["zh", "en", "ja"],
                    help="唱的什么语言（10-01 加 en / ja）：听写、对齐、导出的字都按它")
    ap.add_argument("--lyric-mode", default=None, choices=["pinyin", "hanzi", "word", "kana", "romaji"],
                    help="导出的歌词：中文默认拼音（终稿用的是拼音）、英文整词（后面的音节写 +）、日语默认假名")
    ap.add_argument("--device", default="dml")
    ap.add_argument("--nsteps", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=4,
                    help="GAME 一次算几段（它自己的默认 4）。《潮声回响》4 段一起算显存放不下、换 CPU 吃掉 21 GB 内存 → 用 1")
    ap.add_argument("--asr-batch-size", type=int, default=4, help="听写一次算几段（它自己的默认 4）")
    ap.add_argument("--slicing", default="auto",
                    help="切片的办法（auto = 它的 default）。《潮声回响》和声、混响连成一片，default 切出 69 秒的段、GAME 显存爆掉；"
                         "heuristic 会在最长 10 秒内找最安静的地方强制切")
    ap.add_argument("--low-priority", action="store_true",
                    help="进程优先级调成「低于正常」（它开的子进程跟着低）—— 跑得久也不跟创作者抢机器（09-30 他说「好卡啊」）")
    a = ap.parse_args()
    a.lyric_mode = a.lyric_mode or {"zh": "pinyin", "en": "word", "ja": "kana"}[a.language]
    with_lyrics = bool(a.asr or a.lyrics)
    if a.low_priority and sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p              # 句柄要按指针宽度传；不设的话 64 位上传坏、调用静默失败（09-30 栽过）
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000):   # BELOW_NORMAL_PRIORITY_CLASS
            print("（没调成低优先级）", flush=True)

    _stub_pyopenjtalk(a.language)
    from inference.pipeline.auto_lyric_hybrid import auto_lyric_hybrid_pipeline  # noqa: E402  他们的流水线

    models = V2M / "models"
    lyrics = pathlib.Path(a.lyrics).read_text(encoding="utf-8") if a.lyrics else ""
    ts = [i / a.nsteps for i in range(a.nsteps)]          # 和它界面的 t0_nstep_to_ts(0.0, n) 一样
    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    auto_lyric_hybrid_pipeline(
        audio_path=a.audio, output_filename=a.name, output_dir=out,
        game_model_dir=str(models / "GAME-1.0.3-medium-onnx"),
        hfa_model_dir=str(models / "1218_hfa_model_new_dict"),
        asr_model_path=str(models / "Qwen3-ASR-1.7B-dml"),
        device=a.device, ts=ts, language=a.language,
        lyric_output_mode=a.lyric_mode, original_lyrics=lyrics,
        japanese_asr_engine="qwen",                      # 日语：它默认的罗马音听写模型本机没有 → 直接用 Qwen3-ASR + 日语读音（替身）
        output_formats=["mid", "txt", "csv"],
        slicing_method=a.slicing, tempo=120.0, quantization_step=0, quantization_mode="smart",
        pitch_format="name", round_pitch=True,
        seg_threshold=0.2, seg_radius=0.02, est_threshold=0.2,
        output_lyrics=with_lyrics,
        batch_size=a.batch_size, asr_batch_size=a.asr_batch_size,
    )
    secs = time.perf_counter() - t0
    made = sorted(p.name for p in out.glob(f"{a.name}*"))
    mode = "lyrics+reference" if a.lyrics else ("lyrics-asr-only" if a.asr else "no-lyrics")
    info = {"audio": a.audio, "mode": mode, "language": a.language, "lyric_mode": a.lyric_mode, "device": a.device,
            "batch_size": a.batch_size, "asr_batch_size": a.asr_batch_size, "low_priority": a.low_priority, "slicing": a.slicing,
            "ts": ts, "seconds": round(secs, 1), "outputs": made}
    (out / f"{a.name}_run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Vocal2Midi（{info['mode']}，{a.device}）：{secs:.1f} 秒 · 产物 {made}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
