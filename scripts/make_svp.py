# -*- coding: utf-8 -*-
"""把一首歌打包成一个 `.svp` 文件 —— 人声轨 + 伴奏音频轨，双击即听。

见 [ADR-0009](../specs/adr/0009-write-svp-directly.md)。

## 这一步消除了什么

原来要六步手工：FL 导出 → SynthV 新建工程 → 写入音符（走桥）→ 指派声库
→ 拖音频轨 → 保存。现在一条命令出一个文件。

**SynthV 侧 4 项手动全部消除**（新建 / 指派声库 / 加音频轨 / 保存）。

## 三道校验，写完立刻跑

1. **回读逐字段比对** —— 从写出的文件里读回音符，与源模块的
   onset/duration/pitch/lyrics 逐个比。沿用 `write_song.py` 的做法：
   写完不比对，等于不知道写对没有。
2. **JSON 可解析 + 顶层键齐全** —— 与真实工程的 5 个顶层键对齐。
3. **音频文件真的存在** —— 路径写错 SynthV 会静默不出声，比报错更糟。

用法:
    python scripts/make_svp.py                       # 默认 melody_v2 + 伴奏预览
    python scripts/make_svp.py --audio <别的.wav>
    python scripts/make_svp.py --out <路径.svp> --force
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "out"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import svp
from svagent.compose import note_name, run_all, summarize, CheckCfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-module", default="melody_v2")
    ap.add_argument("--audio", default=None,
                    help="伴奏 wav。默认用 out/listen_yuzhou/伴奏预览_<tag>.wav")
    ap.add_argument("--out", default=None)
    ap.add_argument("--track-name", default="宇宙无边无垠_星尘")
    ap.add_argument("--force", action="store_true", help="允许覆盖已有文件")
    a = ap.parse_args()

    mod = __import__(a.song_module)
    tag = a.song_module.replace("melody_", "")
    notes, phrases, text = mod.build()

    # 写之前先过一遍八项检查。有 block 就不写 —— 和 write_song.py 一致
    fs = run_all(notes, text, mod.KEY_ROOT, mod.KEY_QUALITY, phrases, CheckCfg())
    print("=== 写入前自检 ===")
    print("  " + summarize(fs).replace("\n", "\n  "))
    blocks = [f for f in fs if f.severity == "block"]
    if blocks:
        for f in blocks:
            print("  ", f)
        print("\n  有 block，拒绝写入。")
        return 1

    audio_path = Path(a.audio) if a.audio else (
        ROOT / "out" / "listen_yuzhou" / f"伴奏预览_{tag}.wav")
    audio_path = audio_path.resolve()
    audio = None
    if audio_path.exists():
        info = sf.info(str(audio_path))
        audio = svp.AudioTrack(filename=str(audio_path),
                              duration_s=info.duration, bpm=mod.BPM)
    else:
        print(f"\n  ⚠ 找不到伴奏 {audio_path}，只写人声轨")

    out = Path(a.out) if a.out else (
        ROOT / "out" / "listen_yuzhou" / f"宇宙无边无垠_{tag}.svp")

    proj = svp.build_project(
        bpm=mod.BPM, notes=[svp.note(n.onset_beats, n.duration_beats,
                                     n.midi, n.lyric) for n in notes],
        vocal_track_name=a.track_name,
        voice=svp.VOICE_STARDUST,
        audio=audio)

    pitches = [n.midi for n in notes]
    print(f"\n=== 工程内容 ===")
    print(f"  version {proj['version']}　tempo {mod.BPM:.0f} BPM　"
          f"{proj['time']['meter'][0]['numerator']}/"
          f"{proj['time']['meter'][0]['denominator']}")
    print(f"  人声轨「{a.track_name}」　{len(notes)} 音符　"
          f"{note_name(min(pitches))}–{note_name(max(pitches))}")
    print(f"  声库 {svp.VOICE_STARDUST['name']}"
          f"（{svp.VOICE_STARDUST['language']} / "
          f"{svp.VOICE_STARDUST['phoneset']}）")
    if audio:
        print(f"  伴奏轨　{audio.duration_s:.1f}s　"
              f"{len(proj['tracks'][1]['mainRef']['audio']['beatLocations'])} 个拍点")
        print(f"       {audio.filename}")

    try:
        svp.save(proj, out, force=a.force)
    except FileExistsError as e:
        print(f"\n✗ {e}")
        return 2
    print(f"\n写出　{out}　{out.stat().st_size} B")

    # ---- 三道校验 ----
    print("\n=== 校验 ===")
    ok = True

    d = json.loads(out.read_text(encoding="utf-8"))
    want_keys = {"version", "time", "library", "tracks", "renderConfig"}
    got_keys = set(d)
    same = got_keys == want_keys
    print(f"  {'✓' if same else '✗'} 顶层键与真实工程一致"
          + ("" if same else f"　缺 {want_keys - got_keys}　多 {got_keys - want_keys}"))
    ok &= same

    bad = svp.diff_notes(svp.read_notes(out), notes)
    print(f"  {'✓' if not bad else '✗'} 音符逐字段比对"
          f"（onset/duration/pitch/lyrics）　{len(notes)} 个")
    for b in bad[:5]:
        print("      ", b)
    ok &= not bad

    if audio:
        exists = Path(audio.filename).exists()
        print(f"  {'✓' if exists else '✗'} 伴奏文件存在"
              + ("" if exists else "　—— SynthV 会静默不出声"))
        ok &= exists

    print("\n" + "=" * 62)
    if ok:
        print("✓ 三道校验全过。双击这个文件就能听到人声 + 伴奏。")
        print("  人声要出声还需要 SynthV 渲染一次（第一次打开会自动渲染）。")
    else:
        print("✗ 有校验没过，见上。不要打开这个文件。")
    print("=" * 62)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
