# -*- coding: utf-8 -*-
"""工作流步骤 4：从已验收的 SynthV 工程生成伴奏 MIDI，供导入 FL Studio。

## 数据从哪来

    旋律   ← 读 SynthV 工程（已验收的那条主旋律轨）
    进行   ← 读歌词文件的和弦列
    调     ← 从旋律音高推定
    曲式   ← step3_melody.FORM（两边共用一个常量）

**进行必须从歌词文件读，不能从旋律反推。** 实测反推准确率只有 35% ——
同调的三度关系和弦共享两个音（i=ACE 与 VI=FAC 共享 A、C），
从旋律里区分不开。所以歌词文件的和弦列是唯一真相来源。

写入前会校验：**每句末音必须落在歌词标注的和弦上**。生成器强制了这一点，
所以这个校验能直接判断「歌词里的进行是否与工程里的旋律同源」。
不同源就拒绝，而不是出一份和旋律打架的伴奏。

## 一个项目一份伴奏 MIDI

固定文件名，覆盖前备份 —— 与 `.svp` 同一套规则。

用法:
    python scripts/step4_accompaniment.py                 # 只看报告
    python scripts/step4_accompaniment.py --write
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import step3_melody as S3
from make_accompaniment import (MIDI_NAME, TPB, build_parts, chord_label,
                                density_of, write_midi)
from svagent.compose.checks import note_name
from svagent.compose.lyricfile import parse
from svagent.compose.melodize import chord_of

# 一个项目一份伴奏 MIDI，固定名字
MIDI_OUT = S3.PROJECT.with_name(S3.PROJECT.stem + "_伴奏.mid")
BACKUP_DIR = S3.BACKUP_DIR


class Song:
    """把「工程里的旋律 + 歌词里的进行」包成伴奏生成器认得的形状。"""

    def __init__(self, sections, key_root, quality, bpm, n_bars, bpl=2):
        self.SECTIONS = sections
        self.KEY_ROOT, self.KEY_QUALITY = key_root, quality
        self.BPM, self.N_BARS, self.BARS_PER_LINE = bpm, n_bars, bpl
        # 律动。先用一套克制的组合：夜曲/离别题材不需要满编鼓
        self.PAD_STYLE = "sustain"
        self.ARP_FIGURE = "sparse"
        self.BASS_GROOVE = "1-3"
        self.DRUM_PICK = {"hat": "hat-4", "build": "kick-2",
                          "full": "ballad", "none": "none"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bpm", type=float, default=S3.SONG_BPM)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    vs, probs = parse(S3.LYRICS)
    if probs:
        print("✗ 歌词解析有问题：")
        for x in probs:
            print("  ", x)
        return 1
    ver = vs[next(iter(vs))]
    lead_name, notes, sections = S3.read_lead(S3.PROJECT, ver, S3.FORM)
    kr, kq, kname = S3.infer_key([n.midi for n in notes])
    ps = [n.midi for n in notes]
    print(f"工程　{S3.PROJECT}")
    print(f"旋律　{lead_name}　{len(notes)} 音符"
          f"　{note_name(min(ps))}-{note_name(max(ps))}　推定 {kname}")
    print(f"曲式　{S3.N_BARS} 小节 @{a.bpm:.0f}BPM")

    # 校验：歌词里的进行与工程里的旋律必须同源
    print()
    print("=== 进行同源校验（每句末音必须落在标注的和弦上）===")
    bad = []
    conv = []
    for sec_name, bar0, lines in sections:
        row = []
        out_lines = []
        for text, syls, chord in lines:
            pcs, root, q = chord_of(chord, kr)
            tail = syls[-1][1]
            hit = tail % 12 in pcs
            frac = sum(1 for _c, m, _d in syls if m % 12 in pcs) / len(syls)
            row.append(f"{chord_label(root, q)}{'✓' if hit else '✗'}"
                       f"{frac*100:.0f}%")
            if not hit:
                bad.append((sec_name, text, chord, note_name(tail)))
            out_lines.append((text, syls, (root, q)))
        conv.append((sec_name, bar0, out_lines))
        print(f"  {sec_name:6} " + "  ".join(row))
    if bad:
        print()
        print(f"✗ {len(bad)} 句的末音不在歌词标注的和弦上 —— "
              "歌词里的进行与工程里的旋律不同源，拒绝生成伴奏：")
        for s, t, c, n in bad:
            print(f"    {s}「{t}」标 {c}，末音 {n}")
        return 2
    print("  ✓ 全部同源")

    # 整句贴合度：这是七项检查目前**没有**的一项，只报告不拦
    weak = []
    for sec_name, _b, lines in conv:
        for text, syls, (root, q) in lines:
            pcs = {(root + t) % 12 for t in
                   ((0, 4, 7) if q == "major" else (0, 3, 7))}
            frac = sum(1 for _c, m, _d in syls if m % 12 in pcs) / len(syls)
            if frac < 0.30:
                weak.append((sec_name, text, chord_label(root, q), frac))
    if weak:
        print()
        print(f"⚠ {len(weak)} 句的和弦音占比低于 30% —— 加了伴奏之后"
              "这几句的和声感会偏模糊。**七项检查目前没有这一项**：")
        for s, t, c, f in weak:
            print(f"    {s}「{t}」配 {c}，只有 {f*100:.0f}% 是和弦音")

    song = Song(conv, kr, kq, a.bpm, S3.N_BARS)
    parts, ch, sec = build_parts(song)

    print()
    print("=== 伴奏 ===")
    print(f"  律动 垫={song.PAD_STYLE} 琶音={song.ARP_FIGURE} "
          f"贝斯={song.BASS_GROOVE} 鼓={song.DRUM_PICK['full']}")
    seen = []
    for b in range(song.N_BARS):
        lab = chord_label(*ch[b])
        if not seen or seen[-1][0] != sec[b]:
            seen.append([sec[b], b, b, [lab]])
        else:
            seen[-1][2] = b
            if seen[-1][3][-1] != lab:
                seen[-1][3].append(lab)
    for name, b0, b1, prog in seen:
        pad, bass, arp, drum, cnt = density_of(name)
        on = [n for n, f in (("垫", pad), ("贝斯", bass), ("琶音", arp),
                             ("副线", cnt)) if f]
        print(f"  {name:6} 第{b0+1:2d}-{b1+1:2d}小节  {'-'.join(prog):14}"
              f" 鼓={drum:5} {' '.join(on)}")
    print()
    total = 0
    for pname, evs in parts.items():
        if not evs:
            continue
        ms = [m for _o, _d, m, _v in evs]
        total += len(evs)
        rng = "GM 打击" if pname == "鼓" else f"MIDI {min(ms)}-{max(ms)}"
        print(f"  {pname:5} {len(evs):4d} 个　{rng}")
    print(f"  合计 {total} 个事件　旋律在 MIDI {min(ps)}-{max(ps)}")

    if not a.write:
        print()
        print("没有 --write，不写 MIDI。")
        return 0

    if MIDI_OUT.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = BACKUP_DIR / (MIDI_OUT.stem + "_"
                            + time.strftime("%Y%m%d_%H%M%S") + ".mid")
        shutil.copy2(MIDI_OUT, dst)
        print()
        print(f"已备份原 MIDI → {dst}")
    write_midi(parts, a.bpm, MIDI_OUT)
    print(f"MIDI 写出　{MIDI_OUT}　{MIDI_OUT.stat().st_size} B")

    # 回读逐事件比对
    import mido
    mid = mido.MidiFile(str(MIDI_OUT))
    got = {}
    for tr in mid.tracks:
        name, t, open_, ns = None, 0, {}, []
        for msg in tr:
            t += msg.time
            if msg.type == "track_name":
                name = msg.name
            elif msg.type == "note_on" and msg.velocity > 0:
                open_.setdefault(msg.note, []).append((t, msg.velocity))
            elif msg.type == "note_off" or (msg.type == "note_on"
                                            and msg.velocity == 0):
                q = open_.get(msg.note)
                if q:
                    on, vel = q.pop(0)
                    ns.append((on, t, msg.note, vel))
        if ns:
            got[name] = sorted(ns)
    allok = True
    for zh, en in MIDI_NAME.items():
        want = sorted((int(round(o * TPB)),
                       max(int(round(o * TPB)) + 1,
                           int(round((o + d) * TPB))), m, v)
                      for o, d, m, v in parts[zh])
        have = got.get(en, [])
        same = want == have
        allok &= same
        print(f"  {'✓' if same else '✗'} {en:8}{len(have):4d} 个"
              + ("　逐事件一致" if same else "　不一致"))
    print()
    print(f"导入 FL：文件 → 导入 → MIDI 文件 → {MIDI_OUT}")
    print(f"tempo 必须是 {a.bpm:.0f}，否则和 SynthV 里的人声对不上。")
    return 0 if allok else 3


if __name__ == "__main__":
    raise SystemExit(main())
