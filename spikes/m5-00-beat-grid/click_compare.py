# -*- coding: utf-8 -*-
"""拿别的速度（默认 131 —— Suno Studio 显示的）从同一个「1」起打节拍器，和 grid_check 实测的网格比：到每个时间点差多少；
再做一份试听，让创作者用耳朵比。只读 grid_check.json（实测的网格），不重新量。

    python click_compare.py [BPM]
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import grid_check as GC                                          # noqa: E402


def main(other: float) -> int:
    r = json.loads((GC.OUT / "grid_check.json").read_text(encoding="utf-8"))
    bpm, one, end = r["grid"]["bpm_132"], r["grid"]["first_one_s_132"], r["tempo_span"]["to_s"]
    T, To = 60 / bpm, 60 / other
    print(f"实测：{bpm:.4f} BPM，「1」在 {one:.4f} s，到 {end:.0f} s 为止速度对。对照：{other:g} BPM，从同一个「1」起")
    for t in (15.0, 30.0, 60.0, 90.0, 120.0, end):
        n = round((t - one) / T)
        d = n * (To - T)
        print(f"  {int(t // 60)}:{t % 60:04.1f}（第 {n} 拍）：{other:g} 的节拍器比实测的{'晚' if d > 0 else '早'} {abs(d) * 1000:.0f} ms"
              f" = {abs(d) / T:.2f} 拍")

    lead, sr = sf.read(r["lead"], dtype="float32")
    inst, _ = sf.read(r["instrumental"], dtype="float32")
    music = (lead + inst) * 0.7
    times = one + To * np.arange(int((end - one) / To) + 1)
    acc = np.arange(len(times)) % 4 == 0
    c = GC.clicks(times, acc, sr, len(music))
    got = GC.attacks(c, sr)
    err = float(np.abs(got - times).max()) * 1000 if len(got) == len(times) else float("nan")
    mix = music + c[:, None]
    peak = float(np.abs(mix).max())
    if peak > 0.98:
        mix = mix * (0.98 / peak)
    p = GC.OUT / f"傍晚_节拍器_{other:g}一拍_对照.wav"
    if p.exists():
        print(f"已有 {p.name}，不覆盖")
    else:
        sf.write(str(p), mix, sr, subtype="PCM_16")
    print(f"试听 {p}：{len(times)} 下节拍、「1」{int(acc.sum())} 下，响到 {end:.0f} s；从节拍器轨反测的拍点最多差 {err:.2f} ms")
    return 0 if err == err and err < 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 131.0))
