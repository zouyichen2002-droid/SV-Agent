# -*- coding: utf-8 -*-
"""C02「拍子必须算对」：拿 Suno 分轨的起音当独立裁判，验 SynthV 给的速度和拍点整首准不准；再找小节线（哪一拍是 1）；
最后做两份带节拍器的试听（132 一拍 / 66 一拍），交给创作者听 —— 耳朵是最后一个裁判。

SynthV 存的 beatLocations 是**一张均匀网格**（一个速度 + 第一拍），不是逐拍测的 —— 它自己不会「飘」，
所以准不准只能拿别的东西量：这里用鼓、贝斯、合成器、键盘、弦乐五条分轨各自的起音强度，按网格的十六分折起来，
和「错的速度」折出来的比（偶然水平）。能锁住的那一段速度才算对；锁不住的一段报灰。

- 输入只读：终稿 .svp（SynthV 对伴奏的节拍分析）、Suno 分轨。先验分轨和 SynthV 分析的伴奏是同一个零点
- 结果写在仓库外：E:/sv-agent-data/probes/m5-00-beat-grid/（探针产物，不进学习库）
- 先跑自检（每一项都注入已知的错，必须测得出），不过就不跑

    python grid_check.py
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

SVP = pathlib.Path("F:/我的云端硬盘/临时文件3/SV2/傍晚(星尘).svp")               # 终稿，只读
STEMS = pathlib.Path("C:/Users/admin/Documents/Codex/2026-09-28/kan/outputs/傍晚_分轨与MIDI/WAV")
INSTR = {"鼓": "02_鼓.wav", "贝斯": "03_贝斯.wav", "合成器": "04_合成器.wav", "键盘": "05_键盘.wav", "弦乐": "06_弦乐.wav"}
OUT = pathlib.Path("E:/sv-agent-data/probes/m5-00-beat-grid")
LIMIT = 0.020          # C02 的线：网格和真实拍点整首偏差不超过 ±20 ms（两下打击声差 20 ms 左右开始听得出不齐）
WIN = 15.0             # 分段量：每段 15 秒
NULL_BPM = np.r_[np.linspace(124.0, 128.0, 12), np.linspace(136.0, 140.0, 12)]   # 偶然水平：差 3–6% 的错速度
Z_LOCK = 4.0           # 比偶然高 4 个标准差才算锁住
FLAG = 0.15            # 一小节里换和弦的强度到这个数，才算「有换」


def mono(path, sr: int | None = None) -> tuple[np.ndarray, int]:
    y, s = sf.read(str(path), dtype="float32")
    y = y.mean(axis=1) if y.ndim == 2 else y
    if sr and sr != s:
        y, s = signal.resample_poly(y, sr, s).astype(np.float32), sr
    return y, s


def lag_ms(x: np.ndarray, y: np.ndarray, sr: int, max_s: float = 0.5) -> tuple[float, float]:
    """y 比 x 晚多少毫秒（互相关峰的位置），和相关系数。"""
    c = signal.correlate(x, y, mode="full", method="fft")
    lags = signal.correlation_lags(len(x), len(y), mode="full")
    m = np.abs(lags) <= max_s * sr
    i = int(np.argmax(c[m]))
    return float(-lags[m][i] / sr * 1000), float(c[m][i] / math.sqrt(np.dot(x, x) * np.dot(y, y)))


def attacks(y: np.ndarray, sr: int) -> np.ndarray:
    """起音时刻：先找起音强度的峰，再往回找「能量升到局部峰值一半」的那一刻（打击声的起头）。"""
    hop = max(sr // 1000, 1)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, n_fft=1024)
    peaks = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop, units="time",
                                       pre_max=30, post_max=30, pre_avg=100, post_avg=100, delta=0.07, wait=60)
    w = max(sr // 1000, 1)
    rms = np.sqrt(np.convolve(y.astype(np.float64) ** 2, np.ones(w) / w, mode="same"))
    out = []
    for t in peaks:
        a, b = max(int((t - 0.04) * sr), 0), int((t + 0.03) * sr)
        seg = rms[a:b]
        if len(seg) < 10:
            out.append(t)
            continue
        m = int(np.argmax(seg))
        i = np.where(seg[:m + 1] < 0.5 * seg[m])[0]
        out.append((a + (i[-1] + 1 if len(i) else 0)) / sr)
    return np.array(out)


def strength(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """起音强度曲线（1 ms 一格），减掉中位数、负的记 0：强的起音分量大，长音和底噪几乎不算。"""
    hop = max(sr // 1000, 1)
    e = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, n_fft=1024)
    return np.arange(len(e)) * hop / sr, np.maximum(e - np.median(e), 0)


def fold(t: np.ndarray, w: np.ndarray, bpm: float, t0: float) -> tuple[float, float]:
    """按 bpm 的十六分把强度曲线折起来：长度 R（越大越集中在网格线上）、平均落在网格线后面多少毫秒。

    - 按十六分折：键盘一串十六分也都压线；按八分折，十六分位置的起音正好在两条线中间，会把压线的抵消掉
    - 不先挑离散的起音：音高分轨（贝斯、键盘、弦乐）起音软，挑出来的一大半是乱的；
      只看落在线附近的、取中位数也会骗人 —— 在对称的窗口里乱撒，中位数本来就在 0 附近（探路时栽过）"""
    d = 60 / bpm / 4
    z = (w * np.exp(2j * np.pi * ((t - t0) % d) / d)).sum() / (w.sum() + 1e-12)
    return float(abs(z)), float(math.atan2(z.imag, z.real) / (2 * math.pi) * d * 1000)


def null_for(bpm: float) -> np.ndarray:
    """偶然水平用的「错的速度」：NULL_BPM 是按 132 定的（差 3–6%）；离 132 远的歌按比例缩放，不然会碰上真速度的简单倍数
    （86 × 3/2 = 129 正好在 124–140 里）。离 132 不到 5 BPM（《傍晚》）就原样用，结果和以前一模一样。"""
    return NULL_BPM if abs(bpm - 132.0) <= 5.0 else NULL_BPM * bpm / 132.0


def lock_table(t: np.ndarray, w: np.ndarray, bpm: float, t0: float, end: float) -> list[dict]:
    """每 15 秒一段：R 比「错的速度」（差 3–6%）折出来的高几个标准差（z ≥ 4 算锁住），锁住的段平均偏差多少。"""
    rows = []
    for lo in np.arange(0, end, WIN):
        m = (t >= lo) & (t < lo + WIN)
        if w[m].sum() <= 0:
            rows.append({"from_s": float(lo), "locked": False, "z": None})
            continue
        r, ph = fold(t[m], w[m], bpm, t0)
        null = np.array([fold(t[m], w[m], b, t0)[0] for b in null_for(bpm)])
        z = float((r - null.mean()) / (null.std() + 1e-12))
        rows.append({"from_s": float(lo), "R": round(r, 3), "z": round(z, 1), "locked": z >= Z_LOCK, "phase_ms": round(ph, 1)})
    return rows


def locked_span(tables: dict[str, list[dict]], bpm: float) -> dict:
    """最长的一段连续时间：每 15 秒至少一条分轨锁住，而且每条分轨锁住的偏差前后相差不超过 2 × 线（整段都在 ±线 以内）
    → 这一段里速度算对。速度差一点点，偏差会一段一段挪出线外，这一段就断开。"""
    d = 60 / bpm / 4 * 1000
    n = max(len(v) for v in tables.values())
    best, i = (0, -1), 0
    while i < n:
        j, ref, lo, hi = i, {}, {}, {}
        while j < n:
            locked = {k: v[j] for k, v in tables.items() if j < len(v) and v[j]["locked"]}
            if not locked:
                break
            ok = True
            for k, row in locked.items():
                ref.setdefault(k, row["phase_ms"])
                dev = (row["phase_ms"] - ref[k] + d / 2) % d - d / 2
                a, b = min(lo.get(k, dev), dev), max(hi.get(k, dev), dev)
                if b - a > 2 * LIMIT * 1000:
                    ok = False
                    break
                lo[k], hi[k] = a, b
            if not ok:
                break
            j += 1
        if j - i > best[1] - best[0] + 1:
            best = (i, j - 1)
        i = max(j, i + 1)
    if best[1] < best[0]:
        return {"from_s": None, "to_s": None, "segments": 0}
    return {"from_s": best[0] * WIN, "to_s": (best[1] + 1) * WIN, "segments": best[1] - best[0] + 1}


def combo_fold(curves: dict[str, tuple[np.ndarray, np.ndarray]], lo: float, hi: float, bpm: float, t0: float,
               sub: int = 4) -> tuple[float, float]:
    """几条分轨在 [lo, hi) 里按 1/sub 拍各折一次、每条一样重地合起来（不让最响的那条说了算）。"""
    d = 60 / bpm / sub
    acc, n = 0j, 0
    for t, w in curves.values():
        m = (t >= lo) & (t < hi)
        s = w[m].sum()
        if s > 0:
            acc += (w[m] * np.exp(2j * np.pi * ((t[m] - t0) % d) / d)).sum() / s
            n += 1
    if not n:
        return 0.0, 0.0
    z = acc / n
    return float(abs(z)), float(math.atan2(z.imag, z.real) / (2 * math.pi) * d * 1000)


def refine_end(curves: dict[str, tuple[np.ndarray, np.ndarray]], bpm: float, t0: float,
               s_from: float, s_to: float, ref_ms: float) -> tuple[float, list[dict]]:
    """「速度对」那一段的结尾从 15 秒一格细到 2 秒一格：8 秒的窗、每次挪 2 秒，从结尾前 30 秒往后扫；
    最后一个还锁得住、偏差离这一段的中位不超过线的窗，它的结尾就是结尾。"""
    d = 60 / bpm / 4 * 1000
    end, log = None, []
    for lo in np.arange(max(s_from, s_to - 2 * WIN), s_to + WIN / 2, 2.0):
        r, ph = combo_fold(curves, lo, lo + 8.0, bpm, t0)
        null = np.array([combo_fold(curves, lo, lo + 8.0, b, t0)[0] for b in null_for(bpm)])
        z = float((r - null.mean()) / (null.std() + 1e-12))
        dev = (ph - ref_ms + d / 2) % d - d / 2
        ok = z >= Z_LOCK and abs(dev) <= LIMIT * 1000
        log.append({"from_s": float(lo), "z": round(z, 1), "dev_ms": round(float(dev), 1), "ok": bool(ok)})
        if ok:
            end = float(lo + 8.0)
        elif end is not None:
            break
    return (end if end is not None else s_to), log


def local_tempo(curves: dict[str, tuple[np.ndarray, np.ndarray]], lo: float, hi: float,
                bpm_lo: float = 96.0, bpm_hi: float = 140.0) -> float:
    """这一窗自己最合的速度：bpm_lo–bpm_hi（默认 96–140，《傍晚》那档）每 0.05 扫一遍，按拍、八分、十六分各折一次加起来取最大。
    只用来描述尾声，不判对错。只按拍和八分折不行：一串十六分正好在拍和八分线之间抵消，速度对反而折不出来（自检里栽过：120 扫成 113.85）。
    扫的范围要跟着这首歌的速度定：别的歌用默认范围会扫出假的数（《潮声回响》86 BPM 被扫成 129 = 86 × 3/2）。"""
    scan = np.arange(bpm_lo, bpm_hi + 0.001, 0.05)
    r = [sum(combo_fold(curves, lo, hi, b, 0.0, s)[0] for s in (1, 2, 4)) for b in scan]
    return float(scan[int(np.argmax(r))])


def beat_features(stems: dict[str, np.ndarray], sr: int, beats: np.ndarray) -> dict[str, np.ndarray]:
    """每一拍：底鼓 / 军鼓高频的力度（鼓分轨分频段），和「这一拍比上一拍换了多少和弦」（键盘 + 贝斯的色度）。"""
    def band(y, lo, hi):
        S = np.abs(librosa.stft(y, n_fft=2048, hop_length=240)) ** 2
        f = librosa.fft_frequencies(sr=sr, n_fft=2048)
        e = S[(f >= lo) & (f < hi)].sum(axis=0)
        e = np.log1p(e / (np.median(e) + 1e-12))
        flux = np.maximum(0, np.diff(e, prepend=e[0]))
        dt = 240 / sr
        return np.array([flux[max(int((b - 0.03) / dt), 0):int((b + 0.03) / dt) + 1].max(initial=0) for b in beats[:-1]])

    def chord_change(y):
        y2 = librosa.resample(y, orig_sr=sr, target_sr=22050)
        C = librosa.feature.chroma_cqt(y=y2, sr=22050, hop_length=256)
        dt = 256 / 22050
        per = np.array([C[:, int(beats[i] / dt):max(int(beats[i + 1] / dt), int(beats[i] / dt) + 1)].mean(axis=1)
                        for i in range(len(beats) - 1)])
        loud = np.array([np.abs(y2[int(beats[i] * 22050):int(beats[i + 1] * 22050)]).mean() for i in range(len(beats) - 1)])
        per = per / (np.linalg.norm(per, axis=1, keepdims=True) + 1e-9)
        nov = np.r_[0, 1 - (per[1:] * per[:-1]).sum(axis=1)]
        nov[loud < 0.05 * loud.max()] = 0                          # 没声音的拍不算
        return nov

    return {"底鼓": band(stems["鼓"], 30, 150), "军鼓高频": band(stems["鼓"], 2000, 8000),
            "换和弦": chord_change(stems["键盘"]) + chord_change(stems["贝斯"])}


def downbeat(feat: dict[str, np.ndarray], active_drums: np.ndarray, in_span: np.ndarray | None = None) -> dict:
    """「1」在 8 拍里的哪一位：换和弦最多的那一位；底鼓最重的那一位要和它一样，不一样就报灰。只数速度对的那一段里的拍。"""
    idx = np.arange(len(feat["换和弦"]))
    span = np.ones(len(idx), bool) if in_span is None else in_span
    table = {}
    for k, v in feat.items():
        m = (active_drums if k != "换和弦" else np.ones(len(v), bool)) & span
        table[k] = [round(float(v[m & (idx % 8 == p)].mean()), 3) for p in range(8)]
    ch, kick = np.array(table["换和弦"]), np.array(table["底鼓"])
    p132 = int(np.argmax(ch[:4] + ch[4:]))                        # 132 那档一小节 4 拍
    p66 = p132 if ch[p132] + kick[p132] >= ch[p132 + 4] + kick[p132 + 4] else p132 + 4   # 66 那档一小节 = 8 拍
    kick_ok = int(np.argmax(kick[:4] + kick[4:])) == p132
    return {"table": table, "one_132": p132, "one_66": p66, "kick_agrees": kick_ok}


def odd_bars(change: np.ndarray, one: int) -> list[dict]:
    """逐小节（132 那档，4 拍）：最强的换和弦不在「1」上 = 怪。**连着两个以上怪小节、都挪到同一拍**（中间只隔着没怎么换和弦的小节）→ 灰。
    真的多了或少了一拍，后面的换和弦会一路挪到同一个新位置；只怪一小节的多半是提前换（抢拍），挪到不同拍的多半是零星的，都不算。"""
    runs, cur = [], []

    def close():
        if len(cur) >= 2:
            runs.append(list(cur))
        cur.clear()

    for bar in range((len(change) - one) // 4):
        seg = change[one + bar * 4: one + bar * 4 + 4]
        if len(seg) < 4 or seg.max() < FLAG:
            continue                                               # 这小节没怎么换和弦：不算对也不算怪，不打断
        j = int(np.argmax(seg)) + 1
        if j == 1 or (cur and cur[-1][1] != j):
            close()
        if j != 1:
            cur.append((bar, j))
    close()
    return [{"from_bar": r[0][0], "to_bar": r[-1][0], "beat": r[0][1], "n_bars": len(r)} for r in runs]


def clicks(times: np.ndarray, accent: np.ndarray, sr: int, n: int) -> np.ndarray:
    """节拍器：每拍一下 1100 Hz；「1」那一下 1760 Hz、更响。声音从拍点那一刻开始。"""
    y = np.zeros(n, np.float32)
    L = int(0.03 * sr)
    tt = np.arange(L) / sr
    env = np.exp(-tt / 0.006)
    for t, a in zip(times, accent):
        f, amp = (1760.0, 0.6) if a else (1100.0, 0.35)
        i = int(round(t * sr))
        if 0 <= i < n - L:
            y[i:i + L] += (amp * env * np.sin(2 * np.pi * f * tt)).astype(np.float32)
    return y


# ---------------------------------------------------------------- 自检

def selftest() -> list[str]:
    fails = []
    rng = np.random.default_rng(11)
    sr = 8000
    x = rng.normal(0, 1, sr * 5).astype(np.float32)
    lag, _ = lag_ms(x, np.r_[np.zeros(40, np.float32), x[:-40]], sr)
    if abs(lag - 5.0) > 0.2:
        fails.append(f"零点检查：晚 5 ms 的信号量成了 {lag:.2f} ms")
    lag0, _ = lag_ms(x, x, sr)
    if abs(lag0) > 0.2:
        fails.append(f"零点检查：同一个信号量出 {lag0:.2f} ms")

    sr = 48000
    true_bpm, t0 = 131.9775, 0.1039
    T = 60 / true_bpm
    tt = np.arange(0, 177.0, 0.001)                                # 强度曲线的时间轴，1 ms 一格

    def pulses(times: np.ndarray, noise: float = 0.02) -> np.ndarray:
        w = rng.random(len(tt)) * noise
        np.add.at(w, np.clip(np.round(np.asarray(times) / 0.001).astype(int), 0, len(tt) - 1), 1.0)
        return w

    g16 = t0 + T / 4 * np.arange(int((177.0 - t0) / (T / 4)))       # 一串十六分（像键盘分解和弦），去掉四成、带 4 ms 抖动
    on = g16[rng.random(len(g16)) < 0.6]
    w_ok = pulses(on + rng.normal(0, 0.004, len(on)))
    span = locked_span({"k": lock_table(tt, w_ok, true_bpm, t0, 177.0)}, true_bpm)
    if span["segments"] < 11:
        fails.append(f"速度对、整首都压着网格，却只锁住 {span}")
    for wrong in (131.9, 131.0):                                   # 注入：速度差 0.08 / 1 BPM，锁住的一段必须短得多
        s = locked_span({"k": lock_table(tt, w_ok, wrong, t0, 177.0)}, wrong)
        if s["segments"] > 6:
            fails.append(f"速度差到 {wrong}，却还锁住 {s}")
    late = lock_table(tt, pulses(on + 0.03), true_bpm, t0, 177.0)   # 注入：整体晚 30 ms，拍点位置必须量得出来
    ph = float(np.median([r["phase_ms"] for r in late if r["locked"]]))
    if abs(ph - 30) > 3:
        fails.append(f"整体晚 30 ms，量成 {ph:.1f} ms")
    cut, T2 = 140.0, 60 / 120.0                                    # 注入：140 秒以后换成 120 BPM（尾声变速），锁住的一段必须停在 140 附近
    tail = cut + T2 / 4 * np.arange(int((177.0 - cut) / (T2 / 4)))
    s = locked_span({"k": lock_table(tt, pulses(np.r_[on[on < cut], tail[rng.random(len(tail)) < 0.6]]), true_bpm, t0, 177.0)},
                    true_bpm)
    if s["to_s"] is None or abs(s["to_s"] - cut) > WIN:
        fails.append(f"140 秒后换速度，锁住的一段报成 {s}")
    else:
        w_cut = pulses(np.r_[on[on < cut], tail[rng.random(len(tail)) < 0.6]])
        end, _ = refine_end({"k": (tt, w_cut)}, true_bpm, t0, s["from_s"], s["to_s"], 0.0)
        if abs(end - cut) > 4.0:
            fails.append(f"140 秒后换速度，细到 2 秒一格的结尾报成 {end:.1f} s")
        got = local_tempo({"k": (tt, w_cut)}, 150.0, 158.0)            # 尾声那 120 BPM（一串十六分）：自己扫出来必须是 120
        if abs(got - 120.0) > 0.3:
            fails.append(f"120 BPM 的一串十六分，自己扫出来 {got:.2f}")
        acc = 150.0 + 0.5 * np.arange(16)                              # 重音在拍上、八分弱一点的 120 BPM：也必须是 120
        w_acc = pulses(np.r_[acc, acc + 0.25])
        np.add.at(w_acc, np.round(acc / 0.001).astype(int), 2.0)
        got = local_tempo({"k": (tt, w_acc)}, 150.0, 158.0)
        if abs(got - 120.0) > 0.3:
            fails.append(f"重音在拍上的 120 BPM，自己扫出来 {got:.2f}")

    y = np.zeros(sr * 4, np.float32)
    known = np.array([0.5, 1.1, 1.9, 2.6, 3.3])
    for t in known:
        i = int(t * sr)
        y[i:i + 2400] += (np.exp(-np.arange(2400) / 300) * rng.normal(0, 0.5, 2400)).astype(np.float32)
    got = attacks(y, sr)
    if len(got) != len(known) or np.abs(got - known).max() > 0.003:
        fails.append(f"起音：已知 {known.tolist()}，测到 {np.round(got, 4).tolist()}")

    beats = t0 + T * np.arange(64)                                 # 小节线：造一段「1」在第 0 拍的鼓和和弦
    t = np.arange(int(beats[-1] * sr) + sr) / sr
    kick = np.zeros_like(t, np.float32)
    snare = np.zeros_like(t, np.float32)
    keys = np.zeros_like(t, np.float32)
    roots = [0, 5, 7, 3]
    for k, b in enumerate(beats[:-1]):
        i = int(b * sr)
        amp = 1.0 if k % 4 == 0 else (0.6 if k % 4 == 2 else 0.0)
        kick[i:i + 4800] += (amp * np.exp(-np.arange(4800) / 900) * np.sin(2 * np.pi * 60 * np.arange(4800) / sr)).astype(np.float32)
        if k % 4 == 2:
            snare[i:i + 3000] += (0.8 * np.exp(-np.arange(3000) / 500) * rng.normal(0, 1, 3000)).astype(np.float32)
        root = roots[(k // 4) % 4]
        seg = np.arange(int(T * sr))
        for semi in (0, 4, 7):
            f = 261.63 * 2 ** ((root + semi) / 12)
            keys[i:i + len(seg)] += (0.1 * np.sin(2 * np.pi * f * seg / sr)).astype(np.float32)
    stems = {"鼓": kick + snare, "键盘": keys, "贝斯": keys * 0.5}
    for shift, want in ((0, 0), (1, 3)):                           # 注入：网格从第 2 拍开始数，「1」必须挪到拍位 3
        f = beat_features(stems, sr, beats[shift:])
        db = downbeat(f, np.ones(len(f["换和弦"]), bool))
        if db["one_132"] != want or not db["kick_agrees"]:
            fails.append(f"小节线：网格挪了 {shift} 拍，「1」应在拍位 {want}，测到 {db['one_132']}，底鼓同意 {db['kick_agrees']}")

    ch = np.where(np.arange(80) % 4 == 0, 0.5, 0.0)
    if odd_bars(ch, 0):
        fails.append(f"逐小节：每小节都在「1」上换，却报了灰 {odd_bars(ch, 0)}")
    ch[24], ch[27] = 0.0, 0.4                                      # 一次抢拍（第 6 小节第 4 拍）：不许报
    ch[28], ch[29] = 0.0, 0.0                                      # 第 7 小节没怎么换
    ch[32], ch[33] = 0.1, 0.3                                      # 第 8 小节零星换在第 2 拍（和第 6 小节不同拍）：也不许报
    ch[40:] = np.where(np.arange(40) % 4 == 1, 0.5, 0.0)           # 注入：第 10 小节起多了一拍，换和弦挪到第 2 拍
    runs = odd_bars(ch, 0)
    if len(runs) != 1 or runs[0]["from_bar"] != 10 or runs[0]["beat"] != 2:
        fails.append(f"逐小节：第 10 小节起挪到第 2 拍，报成 {runs}")

    n = sr * 3
    ct = np.array([0.2, 0.7, 1.3, 2.4])
    y = clicks(ct, np.array([True, False, False, True]), sr, n)
    got = attacks(y, sr)
    if len(got) != len(ct) or np.abs(got - ct).max() > 0.002:
        fails.append(f"节拍器：应在 {ct.tolist()}，测到 {np.round(got, 4).tolist()}")
    if not np.abs(y[int(0.2 * sr):int(0.23 * sr)]).max() > np.abs(y[int(0.7 * sr):int(0.73 * sr)]).max():
        fails.append("节拍器：「1」那一下不比普通拍响")
    return fails


# ---------------------------------------------------------------- 主流程

def main() -> int:
    fails = selftest()
    print("自检：", "通过（零点、速度差一点 / 差很多、整体晚了、中途变速、尾声速度、起音、小节线、逐小节、节拍器，每项都注入了已知的错）"
          if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1

    d = BG.load_svp(SVP)
    sv = BG.synthv_oracle(d)
    b = np.array(sv["beats"])
    k = np.round((b - b[0]) / np.median(np.diff(b)))
    fit = np.polyfit(k, b, 1)
    uniform_ms = float(np.abs(b - np.polyval(fit, k)).max() * 1000)
    bpm66 = 60 / fit[0]
    bpm = bpm66 * 2 if bpm66 < 90 else bpm66                         # 统一在 132 那档量，66 那档是隔一拍取一拍
    T, t0 = 60 / bpm, float(fit[1])
    print(f"SynthV：{sv['bpm']:.5f} BPM，备选 {[round(x, 3) for x in sv['alternatives']]}；{len(b)} 个拍点"
          f"是均匀网格（离直线最多 {uniform_ms:.3f} ms）→ 一个速度 {bpm:.4f}（= {bpm / 2:.5f} × 2）+ 第一拍 {t0:.4f} s")

    inst_path = pathlib.Path(sv["file"])
    lead_path = inst_path.with_name("0 Lead Vocals.wav")
    inst8, _ = mono(inst_path, 8000)
    parts8 = [mono(STEMS / f, 8000)[0] for f in INSTR.values()]
    zlag, zr = lag_ms(inst8, np.sum(parts8, axis=0), 8000)
    print(f"零点：五条乐器分轨之和 比 SynthV 分析的伴奏 晚 {zlag:.3f} ms（相关 {zr:.3f}）")
    if abs(zlag) > 1.0:
        print("  ✗ 分轨和伴奏不是同一个零点，不往下量")
        return 1

    stems, sr = {}, 48000
    for name, f in INSTR.items():
        stems[name], sr = mono(STEMS / f)
    dur = len(stems["鼓"]) / sr
    tabs, curves = {}, {}
    for name, y in stems.items():
        curves[name] = strength(y, sr)
        tabs[name] = lock_table(*curves[name], bpm, t0, dur)
    print(f"\n裁判：五条分轨的起音强度，按 SynthV 网格（{bpm:.4f} BPM）的十六分折起来；每 15 秒一段，"
          f"锁住（比错的速度高 {Z_LOCK:.0f} 个标准差）的写偏差（ms），没锁住的写 ·")
    print("       " + " ".join(f"{r['from_s']:>5.0f}" for r in tabs["键盘"]))
    for name, rows in tabs.items():
        print(f"  {name:<4} " + " ".join(f"{r['phase_ms']:+5.0f}" if r["locked"] else "    ·" for r in rows))
    span = locked_span(tabs, bpm)
    if not span["segments"]:
        print("  ✗ 哪一段都锁不住：SynthV 的速度不对，或者分轨不对")
        return 1
    s_from, coarse_to = span["from_s"], min(span["to_s"], dur)
    phases = {}
    for name, rows in tabs.items():
        ph = [r["phase_ms"] for r in rows if r["locked"] and s_from <= r["from_s"] < coarse_to]
        phases[name] = round(float(np.median(ph)), 1) if ph else None
    phase_ok = all(abs(v) <= LIMIT * 1000 for k, v in phases.items() if v is not None and k in ("鼓", "键盘"))
    judges = {k: curves[k] for k, v in phases.items() if v is not None}          # 锁住过的分轨才当裁判
    ref = float(np.median([v for v in phases.values() if v is not None]))
    s_to, fine = refine_end(judges, bpm, t0, s_from, coarse_to, ref)
    s_to = min(s_to, dur)
    print(f"  → 速度对的一段（每 15 秒至少一条锁住、各自的偏差前后都在 ±{LIMIT * 1000:.0f} ms 以内）：{s_from:.0f}–{coarse_to:.0f} s；"
          f"用 {'、'.join(judges)} 细到 2 秒一格：到 {s_to:.0f} s（{int(s_to // 60)}:{s_to % 60:04.1f}）；这之后锁不住 —— 灰")
    print("    细看结尾（8 秒窗）：" + " ".join(f"{r['from_s']:.0f}s{'✓' if r['ok'] else '✗'}(z{r['z']:.0f},{r['dev_ms']:+.0f})" for r in fine))
    before = [(lo, local_tempo(judges, lo, lo + 8.0)) for lo in np.arange(s_to - 24.0, s_to - 7.9, 4.0)]
    outro = [(lo, local_tempo(judges, lo, lo + 8.0)) for lo in np.arange(s_to, dur - 7.9, 4.0)]
    print("    每 8 秒窗自己最合的速度（只描述）：结尾前 " + " ".join(f"{lo:.0f}s:{b:.1f}" for lo, b in before)
          + " ｜ 结尾后 " + " ".join(f"{lo:.0f}s:{b:.1f}" for lo, b in outro))
    print("  → 拍点位置（这一段里锁住的偏差中位数）：" + "，".join(f"{k} {v:+.1f} ms" for k, v in phases.items() if v is not None)
          + f" —— {'过' if phase_ok else '不过'}")
    tk, wk = strength(stems["键盘"], sr)
    alt = {str(c): locked_span({"键盘": lock_table(tk, wk, c, t0, dur)}, c) for c in (131.0, 132.0, round(bpm, 4))}
    print("  对照（只用键盘，换别的速度折）：" + "；".join(
        f"{k} → {v['from_s']:.0f}–{v['to_s']:.0f} s" if v["segments"] else f"{k} → 一段都锁不住" for k, v in alt.items())
        + "（Suno Studio 显示 131）")

    beats = t0 + T * np.arange(int((dur - t0) / T) + 1)
    feat = beat_features(stems, sr, beats)
    drum_on = np.array([np.abs(stems["鼓"][int(x * sr):int((x + T) * sr)]).mean() for x in beats[:-1]])
    active = drum_on > 0.1 * drum_on.max()
    in_span = (beats[:-1] >= s_from) & (beats[:-1] < s_to)
    db = downbeat(feat, active, in_span)
    print(f"\n小节线：8 拍里每一位的平均（0 = SynthV 第一拍；只数 {s_from:.0f}–{s_to:.0f} s 里的拍，鼓只算有鼓的拍）")
    for kname, row in db["table"].items():
        print(f"  {kname:<5} " + " ".join(f"{v:6.3f}" for v in row))
    print(f"  → 132 一拍：「1」在拍位 {db['one_132']}（每 4 拍一小节）；66 一拍：「1」在拍位 {db['one_66']}（每 8 拍）；"
          f"底鼓同意 {db['kick_agrees']}")
    runs = odd_bars(feat["换和弦"], db["one_132"])
    first_one = t0 + db["one_132"] * T
    for r in runs:
        a, z = first_one + r["from_bar"] * 4 * T, first_one + (r["to_bar"] + 1) * 4 * T
        r["from_s"], r["to_s"], r["in_span"] = round(a, 1), round(z, 1), bool(z <= s_to + T)
        why = "要你听" if r["in_span"] else "在速度对的那一段之后 —— 尾声变速带出来的，不另算"
        print(f"  灰：{a:.1f}–{z:.1f} s（{int(a // 60)}:{a % 60:04.1f}–{int(z // 60)}:{z % 60:04.1f}）连着 {r['n_bars']} 个小节"
              f"换和弦都挪到第 {r['beat']} 拍 —— {why}")

    OUT.mkdir(parents=True, exist_ok=True)
    lead, _ = sf.read(str(lead_path), dtype="float32")
    inst, _ = sf.read(str(inst_path), dtype="float32")
    music = (lead + inst) * 0.7
    files = {}
    last = int(np.searchsorted(beats, s_to))                        # 节拍器只响到速度对的那一段结束，尾声不响
    for label, step, bar in (("132一拍", 1, 4), ("66一拍", 2, 4)):
        idx = np.arange(db["one_132"] % step, last, step)
        one = db["one_132"] if step == 1 else db["one_66"]
        acc = ((idx - one) % (step * bar)) == 0
        c = clicks(beats[idx], acc, sr, len(music))
        mix = music + c[:, None]
        peak = float(np.abs(mix).max())
        if peak > 0.98:
            mix = mix * (0.98 / peak)
        p = OUT / f"傍晚_节拍器_{label}.wav"
        if p.exists():
            print(f"  已有 {p.name}，不覆盖")
        else:
            sf.write(str(p), mix, sr, subtype="PCM_16")
        files[label] = str(p)
        got = attacks(c, sr)
        err = float(np.max(np.abs(got - beats[idx][:len(got)]))) * 1000 if len(got) == len(idx) else float("nan")
        print(f"  试听 {p.name}：{len(idx)} 下节拍，「1」{int(acc.sum())} 下；从节拍器轨反测的拍点和网格最多差 {err:.2f} ms")

    result = {"svp": str(SVP), "stems": str(STEMS), "instrumental": str(inst_path), "lead": str(lead_path),
              "synthv": {"bpm": sv["bpm"], "alternatives": sv["alternatives"], "n_beats": len(b), "uniform_grid_max_ms": uniform_ms},
              "grid": {"bpm_132": bpm, "bpm_66": bpm / 2, "first_beat_s": t0, "beat_s": T,
                       "first_one_s_132": first_one, "first_one_s_66": t0 + db["one_66"] * T},
              "zero_check": {"lag_ms": zlag, "corr": zr}, "limit_ms": LIMIT * 1000,
              "lock_tables": tabs, "tempo_span": {"from_s": s_from, "to_s": s_to, "coarse_to_s": coarse_to, "fine": fine},
              "local_tempo": {"before_end": before, "outro": outro},
              "phase_ms": phases, "phase_ok": phase_ok,
              "alt_keys_span": alt, "downbeat": db, "gray_runs": runs, "listen": files}
    p = OUT / "grid_check.json"
    p.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=lambda o: o.item()), encoding="utf-8")
    print(f"\n结果：{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
