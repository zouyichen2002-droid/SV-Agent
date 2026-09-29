# -*- coding: utf-8 -*-
"""r02（和声 · C04）：Suno 上下两个八度一起唱的地方，把另一个八度也扒出来，放成单独一条「叠唱」轨。

创作者 09-29：「好，做r02（和声）」。M1-02 第一步查清：《傍晚》的「和声」是八度叠唱，Suno 在两处上下两个八度一起唱；
GAME 只能挑一个八度。r02 = r01 的主唱原样保留 + 一条「叠唱（另一个八度）」—— 谁当主唱、谁当和声由创作者定。

**怎么判（09-29 第二版）**：用 basic-pitch（能同时扒出好几个音的模型）在人声分轨上的**原样输出**：
GAME 的音 p 那段时间里，basic-pitch 同时还报了 p±12、覆盖这个音一半以上、而且不太弱（强弱比 ≥ 0.4）→ 两个八度一起唱。
实测（记在 README）：已知叠唱的 19 个音里 13 个报了另一个八度、强弱比中位 1.03；远离那几段、只有一个声部的 88 个音里 **0 个**。
**方向**：报了上面（p+12）就放上面 —— 只有一个声部的地方它在上面一个都没误报；
报了下面（p−12）要**另有两个条件**才放下面：频谱旁证也说下面确实有声音（读数比整首中位高 12 dB 以上），
而且不低于这首歌音域下限再往下 2 个半音 —— 09-29 第二版没加这两条，41 个叠唱音里 25 个放到了下面，
有的比整首最低音还低一大截（如 1:56.95「zhang」该放 A4，放成了 A2），这一版没交，挪进「r02_弃用_方向放错」留底。
第一版用频谱读数（上面有没有八度：偶数倍比奇数倍高多少）、分界线用整首歌自己算 —— 线被算得太高，已知的一个没抓到、
方向还放反了，没交；频谱读数留着当旁证（下面有没有八度 octave_double.py 那个）。
判成两个八度的音要**连着至少 3 个**（中间单个空缺补上），零星的去掉：叠唱是整句的制作手法。

basic-pitch 的原样输出要先在 pi-audio 环境里存下来（README 里有命令），这里只读那个 JSON。

自检（不过就不写）：判「同时有另一个八度」的逻辑对造好的例子给出预期结果（覆盖够 / 不够、太弱、方向）；
「连着 3 个」的过滤对已知例子给出预期结果；合成一个 / 两个声部，频谱旁证分得开。
打分：叠唱轨对终稿「和声1」；两条轨合起来对终稿「主唱 + 和声1」合起来（起音和音高一起配对）；
终稿没做叠唱的地方多报了几个（逐个列出，让创作者听）。

    python make_r02.py
输入只读；工程写在 E:/sv-agent-data/probes/m1-01-voice-to-midi/rounds/r02/，结果 E:/sv-agent-data/probes/m1-02-harmony/r02.json。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
import compare_notes as C  # noqa: E402
import make_round_svp as R  # noqa: E402
import octave_double as O  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
R01 = "E:/sv-agent-data/probes/m1-01-voice-to-midi/m1-01_v2m_asr.mid"
FINAL = "F:/我的云端硬盘/临时文件3/SV2/傍晚(星尘).svp"
OUT = O.OUT
BP_RAW = OUT / "basic_pitch_raw_newstem.json"     # pi-audio 环境里 extract_notes(人声分轨) 的原样输出
MIN_COVER, MIN_RATIO = 0.5, 0.4                   # 另一个八度要覆盖这个音一半以上；强弱比 ≥ 0.4
DOWN_MARGIN_DB, RANGE_SLACK = 12.0, 2             # 往下放：频谱读数 > 整首中位 + 12 dB；且 ≥ 音域下限 − 2 个半音
MIN_RUN, MAX_GAP = 3, 1.5


def spectrum(y: np.ndarray, sr: int, s: float, d: float):
    a, b = int((s + 0.2 * d) * sr), int((s + 0.8 * d) * sr)
    seg = y[a:b]
    if len(seg) < int(0.08 * sr):
        return None
    n = 1 << int(np.ceil(np.log2(len(seg) * 4)))
    return np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n)), np.fft.rfftfreq(n, 1 / sr)


def upper_index(y: np.ndarray, sr: int, s: float, d: float, f: float) -> float | None:
    """上面有没有一个八度：偶数倍（2f、4f、6f）比奇数倍（f、3f、5f）高多少 dB。"""
    r = spectrum(y, sr, s, d)
    if r is None:
        return None
    sp, fr = r
    ev = sum(O.peak(sp, fr, k * f) for k in (2, 4, 6))
    od = sum(O.peak(sp, fr, k * f) for k in (1, 3, 5))
    return 20 * np.log10((ev + 1e-9) / (od + 1e-9))


def octave_candidates(bp: list[dict], s: float, d: float, cents: float) -> tuple[bool, bool]:
    """GAME 的这个音那段时间里，basic-pitch 有没有同时报 p+12 / p−12（覆盖够、不太弱）→ (上面有, 下面有)。"""
    p, e = int(round(cents / 100)), s + d

    def best(q: int):
        hit = [n for n in bp if n["pitch"] == q and min(e, n["end"]) - max(s, n["start"]) >= MIN_COVER * d]
        return max(hit, key=lambda n: n["velocity"], default=None)
    same, up, dn = best(p), best(p + 12), best(p - 12)
    ref = same["velocity"] if same else max((x["velocity"] for x in (up, dn) if x), default=1)
    ok = lambda x: bool(x) and x["velocity"] / ref >= MIN_RATIO
    return ok(up), ok(dn)


def decide(up: bool, dn: bool, lower_db: float | None, thr_db: float, p: int, range_min: int) -> int:
    """方向：下面有要另有频谱旁证、且不低于音域 → -1200；上面有 → +1200；都不是 → 0。"""
    if dn and lower_db is not None and lower_db > thr_db and p - 12 >= range_min:
        return -1200
    return 1200 if up else 0


def runs_filter(notes: list, flags: list[bool]) -> list[bool]:
    """连着至少 MIN_RUN 个才算；同一句里（相邻间隔 ≤ MAX_GAP 秒）夹在两个标记中间的单个空缺补上。"""
    f = list(flags)
    for i in range(1, len(f) - 1):
        if not f[i] and f[i - 1] and f[i + 1] and notes[i + 1][0] - notes[i - 1][0] <= 2 * MAX_GAP:
            f[i] = True
    out, i = [False] * len(f), 0
    while i < len(f):
        if not f[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(f) and f[j + 1] and notes[j + 1][0] - (notes[j][0] + notes[j][1]) <= MAX_GAP:
            j += 1
        if j - i + 1 >= MIN_RUN:
            for k in range(i, j + 1):
                out[k] = True
        i = j + 1
    return out


def selftest() -> list[str]:
    fails, sr, rng = [], 48000, np.random.default_rng(11)
    lo_single, lo_double, up_single, up_double = [], [], [], []
    for _ in range(20):
        f = float(rng.uniform(180, 500))
        noise = 0.01 * rng.standard_normal(int(0.6 * sr))
        low, high = O.tone(f, 0.6, sr), O.tone(2 * f, 0.6, sr)
        up_single.append(upper_index(low + noise, sr, 0, 0.6, f))                 # GAME 挑低八度、上面没有
        up_double.append(upper_index(low + 0.8 * high + noise, sr, 0, 0.6, f))    # GAME 挑低八度、上面有
        lo_single.append(O.lower_octave_index(high + noise, sr, 0, 0.6, 2 * f))  # GAME 挑高八度、下面没有
        lo_double.append(O.lower_octave_index(high + 0.8 * low + noise, sr, 0, 0.6, 2 * f))
    if not max(up_single) < min(up_double):
        fails.append(f"「上面有没有八度」分不开：一个声部最高 {max(up_single):.1f}，两个声部最低 {min(up_double):.1f}")
    if not max(lo_single) < min(lo_double):
        fails.append(f"「下面有没有八度」分不开：一个声部最高 {max(lo_single):.1f}，两个声部最低 {min(lo_double):.1f}")
    note = (10.0, 0.4, 6000.0, "")                      # 一个 C4，10.0–10.4 秒
    base = {"pitch": 60, "start": 10.0, "end": 10.4, "velocity": 0.8}
    cases = [([base, {"pitch": 72, "start": 10.05, "end": 10.35, "velocity": 0.7}], (True, False), "上面有、覆盖够、够响"),
             ([base, {"pitch": 48, "start": 9.9, "end": 10.5, "velocity": 0.9}], (False, True), "下面有"),
             ([base, {"pitch": 72, "start": 10.3, "end": 10.5, "velocity": 0.8}], (False, False), "上面有但只覆盖 1/4"),
             ([base, {"pitch": 72, "start": 10.0, "end": 10.4, "velocity": 0.2}], (False, False), "上面有但太弱（强弱比 0.25）"),
             ([base, {"pitch": 67, "start": 10.0, "end": 10.4, "velocity": 0.8}], (False, False), "同时有的是五度，不是八度")]
    for bp, want, label in cases:
        got = octave_candidates(bp, *note[:3])
        if got != want:
            fails.append(f"判另一个八度不对（{label}）：得 {got}，应 {want}")
    dcases = [((True, False, -40.0), 1200, "只有上面"), ((False, True, -10.0), -1200, "下面有、频谱也说有、在音域里"),
              ((False, True, -40.0), 0, "下面有但频谱说没有"), ((True, True, -40.0), 1200, "上下都报、频谱说下面没有 → 放上面"),
              ((False, True, -10.0), 0, "下面有、频谱也说有，但低于音域")]
    for k, ((u, dd, db), want, label) in enumerate(dcases):
        p = 50 if k == 4 else 64                          # E4：p−12 = 52 ≥ 音域下限 50；最后一例 p−12 = 38 < 50
        if decide(u, dd, db, -24.0, p, 50) != want:
            fails.append(f"定方向不对（{label}）：得 {decide(u, dd, db, -24.0, p, 50)}，应 {want}")
    ns = [(i * 0.5, 0.4, 6000.0, "") for i in range(14)]
    flags = [False, True, False, False, True, True, False, True, True, True, False, False, True, False]
    # 第 1、12 个零星的去掉（前后都隔着两个空）；第 6 个夹在两个标记中间的单个空缺补上 → 4–9 连成一段
    want = [False, False, False, False, True, True, True, True, True, True, False, False, False, False]
    if runs_filter(ns, flags) != want:
        fails.append(f"连着 3 个的过滤不对：{runs_filter(ns, flags)}")
    return fails


def pair_count(ref: list, est: list, offset: float) -> int:
    """起音 ≤ 50 ms 且音高 ≤ 50 音分一起配对（一对一、按起音差从小到大）—— 两条轨合起来比的时候用。"""
    cand = sorted((abs(r[0] - (e[0] + offset)), i, j) for i, r in enumerate(ref) for j, e in enumerate(est)
                  if abs(r[0] - (e[0] + offset)) <= C.ONSET_TOL and abs(r[2] - e[2]) <= C.PITCH_TOL)
    ur, ue, n = set(), set(), 0
    for _, i, j in cand:
        if i not in ur and j not in ue:
            ur.add(i)
            ue.add(j)
            n += 1
    return n


def f1(hits: int, nr: int, ne: int) -> float:
    return round(2 * hits / (nr + ne), 3) if nr + ne else 0.0


def main() -> int:
    fails = selftest()
    print("自检：", "通过（判另一个八度的 5 个例子都对；连着 3 个的过滤对；合成的一个 / 两个声部频谱旁证分得开）"
          if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    y, sr = sf.read(R.VOCAL_STEM, dtype="float32")
    y = y.mean(axis=1) if y.ndim > 1 else y
    r01 = sorted(list(C.midi_tracks(R01).values())[0])
    bp = json.loads(BP_RAW.read_text(encoding="utf-8"))
    lower_db = [O.lower_octave_index(y, sr, s, d, O.hz(c)) for s, d, c, _ in r01]
    thr_db = float(np.median([v for v in lower_db if v is not None])) + DOWN_MARGIN_DB
    range_min = min(int(round(c / 100)) for _, _, c, _ in r01) - RANGE_SLACK
    cands = [octave_candidates(bp, s, d, c) for s, d, c, _ in r01]
    direction = [decide(u, dn, lower_db[k], thr_db, int(round(r01[k][2] / 100)), range_min) for k, (u, dn) in enumerate(cands)]
    raw = [x != 0 for x in direction]
    flags = runs_filter(r01, raw)
    for k in range(len(r01)):                            # 补上的空缺：方向跟着前一个；放下面会低于音域就放上面
        if flags[k] and direction[k] == 0:
            direction[k] = next((direction[j] for j in range(k - 1, -1, -1) if direction[j]), 1200)
            if direction[k] < 0 and int(round(r01[k][2] / 100)) - 12 < range_min:
                direction[k] = 1200
    double = [(s, d, c + direction[k], ly) for k, (s, d, c, ly) in enumerate(r01) if flags[k]]
    print(f"往下放的门槛：频谱读数 > {thr_db:.1f} dB，且不低于 MIDI {range_min}")
    print(f"单个音同时有另一个八度的 {sum(raw)} 个 → 连着 ≥ {MIN_RUN} 个的留 {len(double)} 个")

    fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"
    names = "C C# D D# E F F# G G# A A# B".split()
    nm = lambda c: f"{names[int(round(c / 100)) % 12]}{int(round(c / 100)) // 12 - 1}"
    tr = C.tracks(C.load_svp(FINAL))
    lead, harm = tr["vocal1"], tr["和声1"]
    known = lambda s: 85.5 <= s <= 92.5 or 115.5 <= s <= 135.0     # 终稿里做了八度处理的两段（只用来打分和分类）
    o = C.offset_between(lead, r01)
    res = {"判法": f"basic-pitch 同时报 p±12、覆盖 ≥ {MIN_COVER}、强弱比 ≥ {MIN_RATIO}；连着 ≥ {MIN_RUN} 个；"
                   f"往下放另要频谱读数 > {thr_db:.1f} dB 且 ≥ MIDI {range_min}",
           "单个音同时有另一个八度": int(sum(raw)), "叠唱音数": len(double),
           "叠唱方向": {"放高八度": sum(1 for k in range(len(r01)) if flags[k] and direction[k] > 0),
                    "放低八度": sum(1 for k in range(len(r01)) if flags[k] and direction[k] < 0)}}
    h = pair_count(harm, double, o)
    res["叠唱轨对和声1"] = {"对上": h, "和声1": len(harm), "叠唱": len(double), "F1": f1(h, len(harm), len(double))}
    both_ref = sorted(lead + harm)
    u1, u2 = pair_count(both_ref, r01, o), pair_count(both_ref, sorted(r01 + double), o)
    res["两条轨合起来对终稿主唱加和声1"] = {
        "r01（只有主唱）": {"对上": u1, "F1": f1(u1, len(both_ref), len(r01))},
        "r02（主唱 + 叠唱）": {"对上": u2, "F1": f1(u2, len(both_ref), len(r01) + len(double))}}
    extra = [n for n in double if not known(n[0])]
    res["终稿没做八度处理的地方多报的"] = [f"{fmt(s)} {nm(c)}「{ly}」" for s, d, c, ly in extra]
    res["叠唱逐个"] = [f"{fmt(s)} {nm(c)}「{ly}」" for s, d, c, ly in double]
    for k, v in res.items():
        print(f"  {k}：{v}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "r02.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    spec = [("扒谱 r02 主唱", r01), ("扒谱 r02 叠唱（另一个八度）", double)]
    bad = []
    for with_final in (False, True):
        _, fl = R.write_round(spec, "r02", with_final)
        bad += fl
    print(f"\n结果：{OUT / 'r02.json'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
