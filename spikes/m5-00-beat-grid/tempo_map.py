# -*- coding: utf-8 -*-
"""C02 分段速度：一首歌中途换速度时（《潮声回响》82 → 86 → 82），找出每段的速度和小节线、在哪条小节线上换，写成速度表。

编曲软件里速度都是在小节线上换的 —— 所以两段各自按段内的音频拟合、各推到交界处，小节线应该正好重合；
重合了，就在那条小节线上换速度（两段之间整数个小节）。接不上的交界、锁不住的前奏和尾声 = 自由段：不上网格、不吸格线。

1. 全曲 8 秒窗每 2 秒扫一次速度（grid_check.local_tempo，范围跟着歌的速度）；连着 ≥ 4 个窗在 ±0.4 BPM 以内 = 一段稳定速度
2. 每段在段内细扫速度和十六分相位（beat_song.fine_scan）；「1」在一小节 16 个十六分里找 —— 换和弦（和声部分的色度变化）
   和底鼓（打击部分低频）最集中的那一格（按拍折的方向不行：打击乐八分、十六分铺满时方向离哪格都远）
3. 每段往前、往后按小节扩：8 秒窗还锁得住就算这段的
4. 相邻两段：交界附近两串小节线最近的一对差 ≤ 20 ms → 在那儿换速度；否则中间算自由段
5. 速度表：第 1 段之前的自由前奏拉成整数个小节（和《傍晚》第 1 小节同一个办法）；每两个换速度点之间整数个小节，速度按这个算；
   最后一段的速度一直用到结尾（尾声自由，不吸）
6. 节拍器试听只在有速度的段里响
先跑自检（造的数据：自由前奏 + 82 BPM + 在小节线上换成 86；注入：交界差 60 ms 的接不上），不过就不跑

    python tempo_map.py <歌的配置.json>        # 配置和 beat_song.py 一样；输出 <out>/tempo_map.json 和节拍器试听
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import librosa
import numpy as np
import soundfile as sf
from scipy import signal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import beat_grid as BG                                          # noqa: E402
import beat_song as BS                                          # noqa: E402
import grid_check as GC                                         # noqa: E402

Q = BG.Q
SR = BS.SR
JOIN_MS = 20.0          # 两段小节线差 ≤ 20 ms 算接上（和 C02 的线一样）
STABLE = 0.4            # 连着的窗速度在 ±0.4 BPM 以内算稳
MIN_WINDOWS = 4
LAG_TOL = 0.015         # 自检的容差：造的声音过起音强度曲线会晚几毫秒（实测 9 ms）；自检抓的是错一拍、接错这类结构错（≥ 100 ms）


def walk(curves: dict, dur: float, lo_b: float, hi_b: float) -> list[tuple[float, float]]:
    return [(float(x), GC.local_tempo(curves, x, x + 8.0, lo_b, hi_b)) for x in np.arange(0.0, dur - 8.0, 2.0)]


def stable_runs(w: list[tuple[float, float]]) -> list[dict]:
    runs, cur = [], []
    for x, b in w:
        if cur and abs(b - np.median([v for _, v in cur])) <= STABLE:
            cur.append((x, b))
        else:
            if len(cur) >= MIN_WINDOWS:
                runs.append(cur)
            cur = [(x, b)]
    if len(cur) >= MIN_WINDOWS:
        runs.append(cur)
    return [{"from_s": r[0][0], "to_s": r[-1][0] + 8.0, "bpm": float(np.median([v for _, v in r]))} for r in runs]


MERGE_BPM = 0.1


def merge_runs(runs: list[dict]) -> list[dict]:
    """相邻两段速度差不到 0.1 BPM、时间上又重叠 → 并成一段。窗是 8 秒、每 2 秒一个，中间一个窗抖一下就会把一段断成两段，
    断开的两段在时间上是重叠的（《天星问》整首 77.0，被 6 s 处一个 124 和 26–28 s 的 76.5 断成三段，每段各找各的「1」、
    交界接不上，组装出 1212 / -14 BPM）。真换速度的（《潮声回响》82 → 86）差得远、不并。"""
    out: list[dict] = []
    for r in runs:
        if out and abs(r["bpm"] - out[-1]["bpm"]) <= MERGE_BPM and r["from_s"] <= out[-1]["to_s"]:
            a = out[-1]
            la, lr = a["to_s"] - a["from_s"], r["to_s"] - r["from_s"]
            out[-1] = {"from_s": a["from_s"], "to_s": max(a["to_s"], r["to_s"]), "bpm": (a["bpm"] * la + r["bpm"] * lr) / (la + lr)}
        else:
            out.append(dict(r))
    return out


class Features:
    """一小节 16 个十六分里找「1」要用的：和声部分的色度（换和弦）、打击部分的低频起音（底鼓）。"""

    def __init__(self, harm: np.ndarray, perc: np.ndarray, sr: int):
        y22 = librosa.resample(harm, orig_sr=sr, target_sr=22050)
        self.C = librosa.feature.chroma_cqt(y=y22, sr=22050, hop_length=256)
        self.cdt = 256 / 22050
        S = np.abs(librosa.stft(perc, n_fft=2048, hop_length=220)) ** 2
        f = librosa.fft_frequencies(sr=sr, n_fft=2048)
        low = np.log1p(S[(f >= 30) & (f < 150)].sum(axis=0))
        self.low = np.maximum(0, np.diff(low, prepend=low[0]))
        self.ldt = 220 / sr

    def chroma_change(self, t: float, T: float) -> float:
        a, m, b = int((t - T) / self.cdt), int(t / self.cdt), int((t + T) / self.cdt)
        if a < 0 or b > self.C.shape[1] or m <= a or b <= m:
            return 0.0
        x, y = self.C[:, a:m].mean(axis=1), self.C[:, m:b].mean(axis=1)
        x, y = x / (np.linalg.norm(x) + 1e-9), y / (np.linalg.norm(y) + 1e-9)
        return float(1 - x @ y)

    def kick(self, t: float) -> float:
        i = int(t / self.ldt)
        return float(self.low[max(i - 3, 0):i + 4].max()) if 0 <= i < len(self.low) else 0.0


def section_grid(curves: dict, feat: Features, lo: float, hi: float, bpm0: float) -> dict:
    """段内：细扫速度和十六分相位；一小节 16 格里「1」在哪格（换和弦 + 底鼓，各自标准化后相加，最大的那格）。"""
    fb, ph16, r = BS.fine_scan(curves, lo, hi, bpm0, span=1.0, step=0.002)
    U = 60 / fb / 4
    k0 = int(math.ceil((lo - ph16) / U))
    lines = ph16 + U * np.arange(k0, int((hi - ph16) / U))
    ch = np.array([feat.chroma_change(t, 4 * U) for t in lines])
    kk = np.array([feat.kick(t) for t in lines])
    pos = np.arange(k0, k0 + len(lines)) % 16
    chp = np.array([ch[pos == p].mean() if (pos == p).any() else 0.0 for p in range(16)])
    kkp = np.array([kk[pos == p].mean() if (pos == p).any() else 0.0 for p in range(16)])

    def zs(v: np.ndarray) -> np.ndarray:
        """标准化；16 格几乎一样（变化不到平均的 10%）= 这一项没信息，不参与（不然标准化会把噪声放大成和别的项一样重）。"""
        if v.std() < 0.10 * (abs(v.mean()) + 1e-9):
            return np.zeros_like(v)
        return (v - v.mean()) / (v.std() + 1e-9)

    z = zs(chp) + zs(kkp)
    best = int(np.argmax(z))
    bar = 16 * U
    one = (ph16 + best * U) % bar
    return {"bpm": fb, "ph16": ph16, "one_mod_bar": one, "bar_s": bar, "score": float(z[best]),
            "second": float(sorted(z)[-2]), "from_s": lo, "to_s": hi}


def bar_lines(g: dict, lo: float, hi: float) -> np.ndarray:
    k0, k1 = math.ceil((lo - g["one_mod_bar"]) / g["bar_s"]), math.floor((hi - g["one_mod_bar"]) / g["bar_s"])
    return g["one_mod_bar"] + g["bar_s"] * np.arange(k0, k1 + 1)


def locked_window(curves: dict, g: dict, x: float, ref_ms: float) -> bool:
    r, ph = GC.combo_fold(curves, x, x + 8.0, g["bpm"], g["one_mod_bar"])
    null = np.array([GC.combo_fold(curves, x, x + 8.0, b, g["one_mod_bar"])[0] for b in GC.null_for(g["bpm"])])
    z = (r - null.mean()) / (null.std() + 1e-12)
    d = 60 / g["bpm"] / 4 * 1000
    dev = (ph - ref_ms + d / 2) % d - d / 2
    return bool(z >= GC.Z_LOCK and abs(dev) <= GC.LIMIT * 1000)


def extend(curves: dict, g: dict, dur: float) -> dict:
    """按小节往前、往后扩：以小节线开头的 8 秒窗还锁得住，这条小节线就还算这段的。"""
    r, ref = GC.combo_fold(curves, g["from_s"], g["to_s"], g["bpm"], g["one_mod_bar"])
    lines = bar_lines(g, 0.0, dur)
    inside = [b for b in lines if g["from_s"] <= b <= g["to_s"] - 8.0]
    if not inside:
        return dict(g, start_s=g["from_s"], end_s=g["to_s"], ref_ms=ref)
    i0, i1 = list(lines).index(inside[0]), list(lines).index(inside[-1])
    while i0 - 1 >= 0 and locked_window(curves, g, float(lines[i0 - 1]), ref):
        i0 -= 1
    while i1 + 1 < len(lines) and lines[i1 + 1] + 8.0 <= dur and locked_window(curves, g, float(lines[i1 + 1]), ref):
        i1 += 1
    end = float(lines[i1]) + 8.0
    end = float(lines[lines <= end][-1]) if (lines <= end).any() else end        # 到一条小节线为止
    return dict(g, start_s=float(lines[i0]), end_s=end, ref_ms=ref)


def join(a: dict, b: dict) -> dict:
    """a 在前、b 在后：交界附近（a 的结尾 ±3 小节）两串小节线最近的一对。"""
    lo, hi = min(a["end_s"], b["start_s"]) - 3 * a["bar_s"], max(a["end_s"], b["start_s"]) + 3 * b["bar_s"]
    la, lb = bar_lines(a, lo, hi), bar_lines(b, lo, hi)
    d, x, y = min(((abs(x - y), x, y) for x in la for y in lb), key=lambda z: z[0])
    return {"a_s": float(x), "b_s": float(y), "diff_ms": round(d * 1000, 1), "joined": d * 1000 <= JOIN_MS, "at_s": float((x + y) / 2)}


def build_map(grids: list[dict], joins: list[dict], dur: float) -> dict:
    """→ 速度表：anchors = [(小节号, 秒)]（小节号从 0 数，工程第 n+1 小节），每两个 anchor 之间整数个小节；
    metered = 有速度的时间段；free = 自由段。接不上的交界：后一段从它自己的第一条小节线另起（中间自由）。"""
    anchors, metered, free, notes = [(0, 0.0)], [], [], []
    g0 = grids[0]
    start = g0["start_s"]
    if start < 0.5 * g0["bar_s"]:
        # 开头不到半小节（《逃跑的天使》第一个「1」在 0.125 s）：压成一小节，速度就到 1900 多 BPM（SynthV 的速度范围没核实过，
        # 太大怕被截断、整首错位）→ 和下一小节并成第 1 小节（速度慢一点，这一段算自由段、不吸格线；前奏里没有人声）
        notes.append(f"开头只有 {start:.3f} s（不到半小节）：并进下一小节，第 1 小节到 {start + g0['bar_s']:.3f} s")
        start += g0["bar_s"]
    n_intro = max(1, round(start / g0["bar_s"]))
    anchors.append((n_intro, start))
    if start > 0.5 * g0["bar_s"]:
        free.append((0.0, start))
    bar_no, seg_start = n_intro, start
    for i, g in enumerate(grids):
        end = g["end_s"]
        if i + 1 < len(grids):
            j = joins[i]
            end = j["at_s"] if j["joined"] else g["end_s"]
        n = (end - seg_start) / g["bar_s"]
        if abs(n - round(n)) > 0.1:
            notes.append(f"第 {i + 1} 段 {seg_start:.2f}–{end:.2f} s 是 {n:.2f} 个小节，不是整数")
        n = max(1, round(n))
        metered.append((seg_start, end))
        bar_no += n
        anchors.append((bar_no, end))
        if i + 1 < len(grids) and not joins[i]["joined"]:
            nxt = grids[i + 1]["start_s"]
            m = max(1, round((nxt - end) / grids[i + 1]["bar_s"]))
            free.append((end, nxt))
            bar_no += m
            anchors.append((bar_no, nxt))
        seg_start = anchors[-1][1]
    if metered[-1][1] < dur - 0.5 * grids[-1]["bar_s"]:
        free.append((metered[-1][1], dur))
    tempo = []
    for (b0, t0), (b1, t1) in zip(anchors[:-1], anchors[1:]):
        tempo.append({"position": int(b0 * 4 * Q), "bpm": 240.0 * (b1 - b0) / (t1 - t0)})
    tempo.append({"position": int(anchors[-1][0] * 4 * Q), "bpm": grids[-1]["bpm"]})
    merged = [tempo[0]]
    for m in tempo[1:]:                                              # 相邻速度一样就合并
        if abs(m["bpm"] - merged[-1]["bpm"]) > 1e-9:
            merged.append(m)
    return {"anchors": anchors, "tempo": merged, "metered": metered, "free": free, "notes": notes}


def beat_times(tempo: list[dict], dur: float) -> np.ndarray:
    out, n = [], 0
    while True:
        t = BG.blick_to_seconds(n * Q, tempo)
        if t > dur:
            return np.array(out)
        out.append(t)
        n += 1


# ---------------------------------------------------------------- 自检

def selftest() -> list[str]:
    fails = []
    # 相邻、重叠、速度一样的几段并成一段；真换速度的、不重叠的不并
    got = merge_runs([{"from_s": 12, "to_s": 34, "bpm": 76.97}, {"from_s": 30, "to_s": 112, "bpm": 77.0}, {"from_s": 108, "to_s": 224, "bpm": 77.0}])
    if len(got) != 1 or got[0]["from_s"] != 12 or got[0]["to_s"] != 224 or abs(got[0]["bpm"] - 77.0) > 0.01:
        fails.append(f"断成三段的同一个速度没并起来：{got}")
    for runs, why in (([{"from_s": 0, "to_s": 40, "bpm": 82.0}, {"from_s": 38, "to_s": 90, "bpm": 86.0}], "真换速度的"),
                      ([{"from_s": 0, "to_s": 40, "bpm": 120.0}, {"from_s": 44, "to_s": 90, "bpm": 120.05}], "不重叠的")):
        if len(merge_runs(runs)) != 2:
            fails.append(f"{why}被并成了一段")
    rng = np.random.default_rng(21)
    sr = 22050
    dur = 100.0
    y = np.zeros(int(dur * sr), np.float32)
    t = np.arange(len(y)) / sr

    def hit(at: float, amp: float, f0: float) -> None:
        i = int(at * sr)
        n = min(3000, len(y) - i)
        if n > 0:
            y[i:i + n] += (amp * np.exp(-np.arange(n) / 400) * np.sin(2 * np.pi * f0 * np.arange(n) / sr)).astype(np.float32)

    for at in np.sort(rng.uniform(0.5, 12.0, 25)):                  # 自由前奏：乱撒
        hit(at, 0.3, 300.0)
    TA, TB = 60 / 82.0, 60 / 86.0
    oneA = 12.4
    joinT = oneA + 12 * 4 * TA                                       # A 12 小节后，在小节线上换成 86
    beats_true = list(oneA + TA * np.arange(48)) + list(joinT + TB * np.arange(int((dur - 2 - joinT) / TB)))
    for k, bt in enumerate(beats_true):
        hit(bt, 1.0 if k % 4 == 0 else 0.5, 60.0)                  # 拍上：底鼓（「1」更重）
        hit(bt + (TA if bt < joinT else TB) / 2, 0.35, 3000.0)     # 反拍：镲
    ones = beats_true[::4]
    roots = [0, 5, 7, 3]
    for k, (a0, a1) in enumerate(zip(ones[:-1], ones[1:])):       # 和弦：每小节「1」换一次
        i0, i1 = int(a0 * sr), int(a1 * sr)
        tt = np.arange(i1 - i0) / sr
        for semi in (0, 4, 7):
            y[i0:i1] += (0.05 * np.sin(2 * np.pi * 261.63 * 2 ** ((roots[k % 4] + semi) / 12) * tt)).astype(np.float32)
    curves = {"x": GC.strength(y, sr)}
    w = walk(curves, dur, 60.0, 110.0)
    runs = stable_runs(w)
    if len(runs) != 2 or abs(runs[0]["bpm"] - 82) > 0.5 or abs(runs[1]["bpm"] - 86) > 0.5:
        fails.append(f"两段速度（82 → 86）认成 {[(round(r['from_s']), round(r['to_s']), round(r['bpm'], 1)) for r in runs]}")
        return fails
    feat = Features(y, y, sr)                                       # 「1」自己找：造的底鼓在「1」上更重
    ga = section_grid(curves, feat, runs[0]["from_s"], runs[0]["to_s"], runs[0]["bpm"])
    gb = section_grid(curves, feat, runs[1]["from_s"], runs[1]["to_s"], runs[1]["bpm"])
    for g, one_true, T_ in ((ga, oneA, TA), (gb, joinT, TB)):
        d = (g["one_mod_bar"] - one_true % (4 * T_) + 2 * T_) % (4 * T_) - 2 * T_
        if abs(d) > LAG_TOL or abs(g["bpm"] - 60 / T_) > 0.05:
            fails.append(f"段的速度或「1」没找对：{g['bpm']:.3f} BPM、「1」差 {d * 1000:.0f} ms")
            return fails
    ea, eb = extend(curves, ga, dur), extend(curves, gb, dur)
    j = join(ea, eb)
    if not j["joined"] or abs(j["at_s"] - joinT) > LAG_TOL:
        fails.append(f"在小节线上换速度（{joinT:.3f} s），交界认成 {j}")
    m = build_map([ea, eb], [j], dur)
    bt = beat_times(m["tempo"], dur)
    inA = [b for b in beats_true if oneA + 1 <= b < dur - 3]
    err = max(float(np.min(np.abs(bt - b))) for b in inA)
    if err > LAG_TOL:
        fails.append(f"速度表的拍和真拍最多差 {err * 1000:.1f} ms（速度表 {m['tempo']}）")
    if not m["free"] or m["free"][0][0] != 0.0 or abs(m["free"][0][1] - ea["start_s"]) > 1e-6:
        fails.append(f"自由前奏没标出来：{m['free']}")
    bad = dict(eb, one_mod_bar=(eb["one_mod_bar"] + 0.06) % eb["bar_s"])       # 注入：后一段的小节线挪 60 ms
    jb = join(ea, bad)
    if jb["joined"]:
        fails.append(f"小节线差 60 ms 却认成接上了：{jb}")
    return fails


# ---------------------------------------------------------------- 主流程

def main(cfg_path: str, *flags: str) -> int:
    """flags 里有 --reuse 且输出目录已有 tempo_map.json：速度走势、稳定的段、每段的速度 / 小节线、交界直接用上次的（这些最费时，
    整首要二十来分钟），只重新组装速度表、重做按速度表的核对和节拍器试听 —— 改的只是组装速度表的规矩时用。"""
    fails = GC.selftest() + selftest()
    print("自检：", "通过（grid_check 那套 + 造的「自由前奏 + 82 BPM + 在小节线上换 86」认得出、速度表的拍和真拍差 ≤ 15 ms、"
                  "小节线差 60 ms 不许认成接上）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    cfg = json.loads(pathlib.Path(cfg_path).read_text(encoding="utf-8"))
    out = pathlib.Path(cfg["out"])
    acc, voc = BS.load(cfg["accomp"]), BS.load(cfg["vocal"])
    dur = len(acc) / SR
    harm, perc = librosa.effects.hpss(acc)
    curves = {"打击部分": GC.strength(perc, SR), "和声部分": GC.strength(harm, SR), "伴奏整条": GC.strength(acc, SR)}
    prev_path = out / "tempo_map.json"
    if "--reuse" in flags and prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        w, runs, grids, joins = [tuple(x) for x in prev["walk"]], prev["runs"], prev["sections"], prev["joins"]
        print("（--reuse：速度走势、稳定的段、每段的速度和小节线、交界用上次的 tempo_map.json，只重新组装速度表、重做核对和试听）")
    else:
        feat = Features(harm, perc, SR)
        if "--reuse-walk" in flags and prev_path.exists():
            w = [tuple(x) for x in json.loads(prev_path.read_text(encoding="utf-8"))["walk"]]
            print("（--reuse-walk：速度走势用上次的 tempo_map.json；稳定的段、每段的速度和小节线、交界都重算）")
        else:
            center = cfg.get("bpm_center", 86.0)
            w = walk(curves, dur, center * 0.7, center * 1.3)
        runs = merge_runs(stable_runs(w))
        grids = [extend(curves, section_grid(curves, feat, r["from_s"], r["to_s"], r["bpm"]), dur) for r in runs]
        joins = [join(a, b) for a, b in zip(grids[:-1], grids[1:])]
    print("全曲速度走势（8 秒窗、每 2 秒）：" + " ".join(f"{x:.0f}:{b:.1f}" for x, b in w))
    print("稳定的段：" + "；".join(f"{r['from_s']:.0f}–{r['to_s']:.0f} s ≈ {r['bpm']:.2f}" for r in runs))
    for k, g in enumerate(grids, 1):
        print(f"  段 {k}：{g['bpm']:.3f} BPM，「1」模一小节 {g['one_mod_bar']:.4f} s（合分 {g['score']:.2f}，第二名 {g['second']:.2f}），"
              f"按小节扩到 {g['start_s']:.3f}–{g['end_s']:.3f} s")
    for i, j in enumerate(joins):
        print(f"  段 {i + 1} → 段 {i + 2}：最近的一对小节线 {j['a_s']:.3f} / {j['b_s']:.3f} s，差 {j['diff_ms']} ms → "
              f"{'在这条小节线上换速度' if j['joined'] else '接不上，中间算自由段'}")
    m = build_map(grids, joins, dur)
    print("速度表（工程第几小节起 → BPM）：" + "；".join(f"第 {t['position'] // (4 * Q) + 1} 小节 {t['bpm']:.4f}" for t in m["tempo"]))
    print("有速度的段：" + "；".join(f"{a:.2f}–{b:.2f} s" for a, b in m["metered"]) + " ｜ 自由段：" +
          "；".join(f"{a:.2f}–{b:.2f} s" for a, b in m["free"]))
    for n in m["notes"]:
        print("  ⚠", n)
    tabs = {}                                                          # 第二个裁判：按速度表的网格，每段各自的拍折一次
    bt = beat_times(m["tempo"], dur)
    for (a, b), g in zip(m["metered"], grids):
        inside = bt[(bt >= a) & (bt < b)]
        tabs[f"{a:.0f}–{b:.0f}"] = {n: GC.lock_table(*cv, 60 / float(np.median(np.diff(inside))), float(inside[0]), dur)
                                    for n, cv in curves.items()}
    for key, t in tabs.items():
        a, b = (float(x) for x in key.split("–"))
        print(f"  按速度表量 {key} s：" + "；".join(
            f"{n} " + " ".join(f"{r['from_s']:.0f}:{r['phase_ms']:+.0f}" if r["locked"] else f"{r['from_s']:.0f}:·"
                               for r in rows if a - 15 < r["from_s"] < b)
            for n, rows in t.items()))
    mix = np.stack([acc + voc, acc + voc], axis=1) * 0.7
    keep = np.zeros(len(bt), bool)
    for a, b in m["metered"]:
        keep |= (bt >= a - 1e-6) & (bt < b - 1e-6)
    idx = np.where(keep)[0]
    accent = np.array([BG.blick_to_seconds(0, m["tempo"]) is not None and (k % 4 == 0) for k in idx])
    c = GC.clicks(bt[idx], accent, SR, len(mix))
    mm = mix + c[:, None]
    peak = float(np.abs(mm).max())
    mm = mm * (0.98 / peak) if peak > 0.98 else mm
    wav = out / f"{cfg['name']}_节拍器_分段速度.wav"
    if not wav.exists():
        sf.write(str(wav), mm, SR, subtype="PCM_16")
    got = GC.attacks(c, SR)
    err = float(np.max(np.abs(got - bt[idx][:len(got)]))) * 1000 if len(got) == len(idx) else float("nan")
    print(f"试听 {wav}：{len(idx)} 下节拍、「1」{int(accent.sum())} 下（只在有速度的段里响）；反测拍点最多差 {err:.2f} ms")
    res = {"name": cfg["name"], "config": cfg, "walk": w, "runs": runs, "sections": grids, "joins": joins, "map": m,
           "check": {k: {n: [dict(r) for r in rows] for n, rows in t.items()} for k, t in tabs.items()}, "listen": str(wav)}
    (out / "tempo_map.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: o.item()), encoding="utf-8")
    print(f"结果：{out / 'tempo_map.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
