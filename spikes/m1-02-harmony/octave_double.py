# -*- coding: utf-8 -*-
"""M1-02 探针（和声 · C04）第一步：Suno 的人声分轨里，这一段是不是本来就有上下两个八度一起唱？

背景（09-29）：终稿的「和声1」一共 30 个音，全在 1:56–2:14，每个都正好比主唱高一个八度 —— 八度叠唱。
GAME 在这一段有的音扒在上八度、有的扒在下八度。要分清：分轨里本来就有两个八度（能「识别」），
还是只有一个（另一个是创作者自己编的）。

怎么判（物理，不靠模型）：设上八度音的基频为 f。
- 只有上八度那一个声音：能量在 f、2f、3f……（f 的整数倍）
- 再有一个下八度的声音（基频 f/2）：还会在 **f/2、1.5f、2.5f** 这些「f/2 的奇数倍」上有能量 —— 上八度的声音自己产生不了
→ 看「f/2 的奇数倍」的能量比「f 的整数倍」低多少分贝（下八度指数，越接近 0 越说明有下八度）。

自检（不过就不比）：合成一个声部 → 指数必须很低；两个声部（上下八度）→ 必须明显高；两者要分得开。
对照：同一首歌里**只有主唱一个声部**的段落，把主唱本身当「上面那个声音」，看它**下面**有没有一个八度 → 当「没有下八度」的底。
（09-29 第一版的对照写反了：假设主唱上面还有一个八度 —— 那样「下面」正好是主唱本人，读数当然高，不能当底。已改。）

    python octave_double.py <人声分轨.wav> <终稿.svp>
只读输入；结果写在 E:/sv-agent-data/probes/m1-02-harmony/。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "m1-01-voice-to-midi"))
import compare_notes as C  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = pathlib.Path("E:/sv-agent-data/probes/m1-02-harmony")


def peak(spec: np.ndarray, freqs: np.ndarray, f: float, cents: float = 40) -> float:
    lo, hi = f * 2 ** (-cents / 1200), f * 2 ** (cents / 1200)
    band = spec[(freqs >= lo) & (freqs <= hi)]
    return float(band.max()) if band.size else 0.0


def lower_octave_index(y: np.ndarray, sr: int, start: float, dur: float, f_up: float) -> float | None:
    """上八度基频 f_up 的这个音里，「f/2 的奇数倍」比「f 的整数倍」低多少 dB。"""
    a, b = int((start + 0.2 * dur) * sr), int((start + 0.8 * dur) * sr)
    seg = y[a:b]
    if len(seg) < int(0.08 * sr):
        return None
    n = 1 << int(np.ceil(np.log2(len(seg) * 4)))
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    odd = sum(peak(spec, freqs, k * f_up / 2) for k in (1, 3, 5))       # 只有下八度会有
    even = sum(peak(spec, freqs, k * f_up) for k in (1, 2, 3))          # 上八度（下八度也有）
    return 20 * np.log10((odd + 1e-9) / (even + 1e-9))


def hz(cents: float) -> float:
    return 440.0 * 2 ** ((cents / 100 - 69) / 12)


def tone(f: float, dur: float, sr: int) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return sum(np.sin(2 * np.pi * k * f * t) / k for k in range(1, 8) if k * f < sr / 2)


def selftest(sr: int = 48000) -> tuple[list[str], dict]:
    rng = np.random.default_rng(7)
    one, two = [], []
    for _ in range(20):
        f = float(rng.uniform(200, 600))
        s1 = tone(f, 0.6, sr) + 0.01 * rng.standard_normal(int(0.6 * sr))
        s2 = s1 + 0.7 * tone(f / 2, 0.6, sr)
        one.append(lower_octave_index(s1, sr, 0.0, 0.6, f))
        two.append(lower_octave_index(s2, sr, 0.0, 0.6, f))
    stats = {"一个声部_中位_dB": round(float(np.median(one)), 1), "两个声部_中位_dB": round(float(np.median(two)), 1)}
    fails = []
    if not max(one) < min(two):
        fails.append(f"一个声部和两个声部分不开：一个声部最高 {max(one):.1f} dB，两个声部最低 {min(two):.1f} dB")
    return fails, stats


def main(wav: str, final_svp: str) -> int:
    fails, st = selftest()
    print("自检：", f"通过（合成一个声部中位 {st['一个声部_中位_dB']} dB，两个声部 {st['两个声部_中位_dB']} dB，完全分得开）"
          if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    y, sr = sf.read(wav, dtype="float32")
    y = y.mean(axis=1) if y.ndim > 1 else y
    tr = C.tracks(C.load_svp(final_svp))
    lead, harm = tr["vocal1"], tr["和声1"]
    a, b = harm[0][0] - 0.5, harm[-1][0] + harm[-1][1] + 0.5
    test = [lower_octave_index(y, sr, s, d, hz(c)) for s, d, c, _ in harm]
    ctrl = [lower_octave_index(y, sr, s, d, hz(c)) for s, d, c, _ in lead if not (a - 5 <= s <= b + 5)]
    test = [v for v in test if v is not None]
    ctrl = [v for v in ctrl if v is not None]
    q = lambda v: [round(float(np.percentile(v, p)), 1) for p in (10, 50, 90)]
    thr = float(np.percentile(ctrl, 90))
    above = sum(v > thr for v in test)
    res = {"自检": st, "这一段（和声1 的 30 个音）_10/50/90 分位_dB": q(test),
           "对照（只有主唱的段落，看主唱下面有没有八度）_10/50/90 分位_dB": q(ctrl),
           "这一段高于对照 90 分位的音": f"{above}/{len(test)}", "对照音数": len(ctrl)}
    for k, v in res.items():
        print(f"  {k}：{v}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "octave_double.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果：{OUT / 'octave_double.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
