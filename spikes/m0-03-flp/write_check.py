# -*- coding: utf-8 -*-
"""往 .flp 里写速度，FL 认不认？—— 两个互相独立的裁判。

  裁判 1  FL 导出的 MIDI 里的速度
  裁判 2  FL 导出的 WAV 有多长。空模板是 1 小节（4 拍），速度一变，长度必须按比例变：
          时长 ≈ 4 × 60 / BPM（再加几毫秒尾巴）。这是 FL 的音频引擎在认，不只是 MIDI 导出器

写入对象是空模板的**拷贝**（find_tempo.py 已经拷好），写出的是**新文件**，原文件不动。
速度事件是 find_tempo.py 找到的 156 号，值 = BPM × 1000。

**先证明检查会响**：注入一个真实会犯的错 —— 忘了乘 1000（想写 66 BPM，实际写进去 66）。
FL 读出来的必须不是 66 BPM，检查必须报红。
"""
from __future__ import annotations

import os
import wave

import flp
import fl_cli

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "out", "samples", "tpl_Empty_Empty.flp")
WORK = os.path.join(HERE, "out", "write")
TEMPO_ID = 156


def wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def write_tempo(base, raw_value, name):
    ev = [e for e in base.events if e.id == TEMPO_ID]
    assert len(ev) == 1, f"事件 {TEMPO_ID} 应恰好 1 个，实际 {len(ev)}"
    path = os.path.join(WORK, name)
    open(path, "wb").write(flp.with_value(base, ev[0], raw_value))
    back = flp.read(path)   # 自己先读回来：结构还对吗？值写进去了吗？
    assert back.structure_ok and [e.value for e in back.events if e.id == TEMPO_ID] == [raw_value]
    return path


def judge(path, want_bpm, with_wav):
    mid, _ = fl_cli.export_midi(path)
    _, bpms = fl_cli.midi_tempo(mid)
    got = bpms[0]
    ok_midi = abs(got - want_bpm) < 0.001
    line = f"MIDI 里 {got:9.4f} BPM（要 {want_bpm:g}）{'✓' if ok_midi else '✗'}"
    ok_wav = True
    if with_wav:
        secs = wav_seconds(fl_cli.export_wav(path, WORK)[0])
        expect = 4 * 60 / want_bpm
        ok_wav = abs(secs - expect) < 0.05
        line += f" · WAV {secs:6.3f} 秒（1 小节应 ≈ {expect:6.3f}）{'✓' if ok_wav else '✗'}"
    return ok_midi and ok_wav, line


def main():
    os.makedirs(WORK, exist_ok=True)
    base = flp.read(BASE)
    orig = [e.value for e in base.events if e.id == TEMPO_ID]
    print(f"底：{os.path.basename(BASE)} · 事件 {TEMPO_ID} = {orig} → {orig[0] / 1000:g} BPM\n")

    print("── 先证明检查会响（注入缺陷：忘了乘 1000）──")
    bad = write_tempo(base, 66, "bug_forgot_x1000.flp")
    ok, line = judge(bad, 66, with_wav=False)
    print(f"  想写 66 BPM，实际写入值 66 → {line}")
    print(f"  → {'检查失灵 ✗（它竟然判对了）' if ok else '检查会响 ✓（判为不对）'}\n")
    if ok:
        raise SystemExit(1)

    print("── 真写入 ──")
    all_ok = True
    for bpm in (66, 97.5):
        path = write_tempo(base, round(bpm * 1000), f"empty_{str(bpm).replace('.', '_')}bpm.flp")
        ok, line = judge(path, bpm, with_wav=True)
        all_ok &= ok
        print(f"  写 {bpm:g} BPM → {line}")
    print(f"\n  写入：{'绿' if all_ok else '红'}")


if __name__ == "__main__":
    main()
