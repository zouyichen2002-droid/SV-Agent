# -*- coding: utf-8 -*-
"""校验伴奏 MIDI。

**为什么必须校验**：选 MIDI 这条路的唯一理由就是"对齐一个 tick 不丢"。
这个理由如果不验，就只是个说法。

六项检查：

1. **回读一致** —— 从文件解析出的每个 (轨, tick, 音高, 力度) 与生成意图逐一相等。
   这是"tick 不丢"的直接证据，不是推论。
2. **落格** —— 所有起点落在 1/8 拍格子上，无浮点漂移。
3. **总长** —— 不超出 48 小节。
4. **调内** —— 所有音在 A 自然小调的七个音级内。
5. **和弦音** —— 垫/贝斯/琶音的每个音都是当前小节和弦的和弦音。
6. **不与旋律撞** —— 时间上重叠的音符，音高要有间隔；
   副线在旋律频段内，所以要求它与旋律**零时间重叠**。

用法:
    python scripts/verify_accompaniment.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "out"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import mido

from make_accompaniment import (MIDI_NAME, TPB, build_parts, chord_label,
                                chord_map)


def triad_pcs(root_pc: int, quality: str) -> set[int]:
    t = (0, 4, 7) if quality == "major" else (0, 3, 7)
    return {(root_pc + x) % 12 for x in t}


def key_pcs(root_pc: int, quality: str) -> set[int]:
    deg = (0, 2, 4, 5, 7, 9, 11) if quality == "major" else (0, 2, 3, 5, 7, 8, 10)
    return {(root_pc + d) % 12 for d in deg}


def read_notes(path: Path):
    """→ {轨名: [(on_tick, off_tick, 音高, 力度), ...]}，外加 (bpm, 拍号)。"""
    mid = mido.MidiFile(str(path))
    bpm = num = den = None
    out: dict[str, list] = {}
    for tr in mid.tracks:
        name, t, open_, notes = None, 0, {}, []
        for msg in tr:
            t += msg.time
            if msg.type == "track_name":
                name = msg.name
            elif msg.type == "set_tempo":
                bpm = mido.tempo2bpm(msg.tempo)
            elif msg.type == "time_signature":
                num, den = msg.numerator, msg.denominator
            elif msg.type == "note_on" and msg.velocity > 0:
                open_.setdefault(msg.note, []).append((t, msg.velocity))
            elif msg.type == "note_off" or (msg.type == "note_on"
                                            and msg.velocity == 0):
                q = open_.get(msg.note)
                if q:
                    on, vel = q.pop(0)
                    notes.append((on, t, msg.note, vel))
        if notes:
            out[name] = sorted(notes)
        if any(q for q in open_.values()):
            raise AssertionError(f"轨「{name}」有未关闭的 note_on")
    return out, bpm, (num, den)


def main() -> int:
    import melody_v2 as mod
    tag = "v2"
    path = (Path(__file__).resolve().parents[1] / "out" / "listen_yuzhou"
            / f"伴奏_{tag}.mid")
    if not path.exists():
        print(f"找不到 {path}，先跑 scripts/make_accompaniment.py")
        return 1

    parts, ch, sec = build_parts(mod)
    got, bpm, meter = read_notes(path)
    mel = [(n.onset_beats, n.onset_beats + n.duration_beats, n.midi)
           for n in mod.build()[0]]

    fails: list[str] = []
    def chk(ok, label, detail=""):
        print(f"  {'✓' if ok else '✗'} {label}" + (f"　{detail}" if detail else ""))
        if not ok:
            fails.append(label)

    print(f"《宇宙无边无垠》伴奏校验　{path.name}\n")
    print(f"文件头：{bpm:.4f} BPM · {meter[0]}/{meter[1]} · "
          f"{len(got)} 条有音符的轨\n")
    # MIDI 的 tempo 是"每四分音符多少微秒"的整数，76 BPM 表示不出来（789473.68…）。
    # 所以不能判 BPM 相等，要判**全曲累积漂移**。
    upq = round(60e6 / mod.BPM)
    exact = 60e6 / upq
    total_s = mod.N_BARS * 4 * 60.0 / mod.BPM
    drift_ms = abs(exact - mod.BPM) / mod.BPM * total_s * 1000
    chk(abs(bpm - exact) < 1e-9 and drift_ms < 1.0,
        "tempo 量化误差在全曲内可忽略",
        f"{bpm:.6f} BPM（{upq} µs/四分音符）　"
        f"{total_s:.1f}s 累积漂移 {drift_ms:.3f}ms")
    chk(meter == (4, 4), "拍号 4/4")

    # 1) 回读一致 —— tick 级逐事件比对
    print("\n[1] 回读一致（tick 级）")
    for zh, en in MIDI_NAME.items():
        want = sorted((int(round(o * TPB)),
                       max(int(round(o * TPB)) + 1, int(round((o + d) * TPB))),
                       m, v) for o, d, m, v in parts[zh])
        have = got.get(en, [])
        same = want == have
        chk(same, f"{en:8}{len(have):4d} 个音符",
            "逐事件全等" if same else f"意图 {len(want)} 个，差异见下")
        if not same:
            for w, h in zip(want, have):
                if w != h:
                    print(f"      首个差异 意图={w} 实际={h}")
                    break

    # 2) 落格：最细的单位是 1/8 拍（0.4 拍的贝斯推进音也是精确 tick）
    print("\n[2] 落格与总长")
    grid = TPB // 8
    off = [(en, on) for en, ns in got.items() for on, _, _, _ in ns
           if on % grid]
    chk(not off, f"所有起点落在 1/{8} 拍格子上（{grid} tick）",
        "" if not off else f"{len(off)} 个偏格，例 {off[:3]}")
    end = mod.N_BARS * 4 * TPB
    over = [(en, o) for en, ns in got.items() for _, o, _, _ in ns if o > end]
    chk(not over, f"全部在 {mod.N_BARS} 小节内（{end} tick）",
        "" if not over else f"{len(over)} 个越界")

    # 3) 调内 + 4) 和弦音
    print("\n[3] 调内与和弦音")
    kp = key_pcs(mod.KEY_ROOT, mod.KEY_QUALITY)
    bad_key = [(en, m) for en, ns in got.items() if en != "Drums"
               for _, _, m, _ in ns if m % 12 not in kp]
    chk(not bad_key, f"全部在 {chord_label(mod.KEY_ROOT, mod.KEY_QUALITY)} 自然音阶内",
        "" if not bad_key else f"{len(bad_key)} 个越调，例 {bad_key[:3]}")
    bad_ch = []
    for en, ns in got.items():
        if en in ("Drums", "Counter"):
            continue
        for on, _, m, _ in ns:
            bar = on // (4 * TPB)
            if m % 12 not in triad_pcs(*ch[bar]):
                bad_ch.append((en, bar + 1, chord_label(*ch[bar]), m))
    chk(not bad_ch, "垫/贝斯/琶音全是当前和弦的和弦音",
        "" if not bad_ch else f"{len(bad_ch)} 个非和弦音，例 {bad_ch[:3]}")

    # 5) 与旋律的关系
    print("\n[4] 与旋律的关系（旋律 MIDI "
          f"{min(m for _,_,m in mel)}–{max(m for _,_,m in mel)}）")
    mel_t = [(a * TPB, b * TPB) for a, b, _ in mel]

    def overlaps_melody(on, off):
        return any(on < mb and ma < off for ma, mb in mel_t)

    for en in ("Pad", "Bass", "Arp"):
        ns = got.get(en, [])
        clash = [m for on, off, m, _ in ns
                 if overlaps_melody(on, off)
                 and any(abs(m - mm) < 3 and on < mb and ma < off
                         for (ma, mb), (_, _, mm) in zip(mel_t, mel))]
        lo = min(m for _, _, m, _ in ns); hi = max(m for _, _, m, _ in ns)
        chk(not clash, f"{en:5} MIDI {lo}–{hi} 与旋律无 3 半音内的同时发声",
            "" if not clash else f"{len(clash)} 处，例 {clash[:5]}")

    cnt = got.get("Counter", [])
    bleed = [(on, off, m) for on, off, m, _ in cnt if overlaps_melody(on, off)]
    chk(not bleed, f"Counter {len(cnt)} 个音与旋律零时间重叠",
        "" if not bleed else f"{len(bleed)} 处撞上人声：{bleed[:3]}")

    # 段落覆盖：不能有小节是全空的（除了刻意的留白，这里要求垫铺满）
    print("\n[5] 段落覆盖")
    pad_bars = {on // (4 * TPB) for on, _, _, _ in got.get("Pad", [])}
    holes = sorted(set(range(mod.N_BARS)) - pad_bars)
    chk(not holes, f"垫铺满全部 {mod.N_BARS} 小节",
        "" if not holes else f"空缺小节 {[h+1 for h in holes]}")

    print("\n" + "=" * 58)
    if fails:
        print(f"✗ {len(fails)} 项未通过：")
        for f in fails:
            print(f"    {f}")
        return 2
    print("✓ 六项全部通过。MIDI 可以导入 FL Studio。")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
