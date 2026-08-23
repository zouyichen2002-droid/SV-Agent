# -*- coding: utf-8 -*-
"""测量人声 stem 里的复音程度：多少比例的帧同时有 2 个以上声部，音程关系是什么。

## 为什么必须先测这个

项目目标改为「一条多声部人声轨 → 1 条主旋律 + N 条和声轨」之后，
之前所有基于「每帧只有一个音高」的结论都要重新审。特别是：

- 交接文件与本项目此前用 **LRC 括号行**估的和声占比（29.7%，92.85–151.88s）
  是**文本推断**，不是声学测量。歌词里不标括号的地方也可能有和声。
- ADR-0004 把 crepe/rmvpe 的八度分歧（5.8%）当误差压掉了。若那些帧确实是
  两个声部，压掉的就是信号。

## 方法：两条独立证据

**证据 A · RMVPE 显著图的多峰结构。**
RMVPE 输出 360 维音高显著图（20 音分/bin，已按 ADR-0003 标定）。
监峰法：找所有超过绝对阈与相对阈的局部极大，峰间至少隔开 `min_sep_bins`。

**这条证据的已知弱点必须写清**：RMVPE 是在**单声部**歌声上训的，
它的次峰可能是泛音残留而不是第二个声部。**八度（+1200 音分）与纯五度
（+702 音分）恰好也是谐波关系**（2 倍频、3 倍频/2），单看不能区分
"第二个声部" 和 "第一个声部的泛音"。
所以要看音程分布：**三度、六度、七度不是简单谐波关系**，
它们的出现是真复音的强证据。

**证据 B · 谐波求和显著度（自实现，与神经网络完全独立）。**
对每个候选基频，把它的前 N 个谐波位置的谱幅加起来。
真实的第二个声部会在自己的基频上形成独立的谐波堆；
第一个声部的泛音不会（它的能量已经被算进第一个声部的和里）。
再对候选做「次谐波抑制」：若候选 f 的能量能被 f/2 或 f/3 的谐波堆解释，扣掉。

用法: python eval/polyphony.py [song_id] [--no-save]
"""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import config, lyrics
from svagent.align import from_stems
from svagent.audio import load_mono
from svagent.pitch import n_frames_for
from svagent.pitch.dsp import mel_filterbank, stft_mag
from svagent.pitch.rmvpe_est import (CENTS_BASE, CENTS_PER_BIN, CENTS_REF_HZ,
                                     RmvpeEstimator)

# 音程名，用于判读次峰是不是「谐波关系」
INTERVALS = [
    (0, "同音"), (1, "小二"), (2, "大二"), (3, "小三"), (4, "大三"),
    (5, "纯四"), (6, "增四"), (7, "纯五"), (8, "小六"), (9, "大六"),
    (10, "小七"), (11, "大七"), (12, "八度"),
]
# 与基频成简单谐波关系的音程（单看显著图无法与泛音区分）
HARMONIC_AMBIGUOUS = {0, 7, 12, 19, 24, 28}


def bins_to_cents(b):
    return CENTS_PER_BIN * np.asarray(b, float) + CENTS_BASE


def cents_to_hz(c):
    return CENTS_REF_HZ * 2 ** (np.asarray(c, float) / 1200.0)


def find_peaks(sal: np.ndarray, abs_thr: float, rel_thr: float,
               min_sep_bins: int, max_peaks: int = 4):
    """逐帧监峰。返回 (峰 bin 的整数索引列表, 峰值列表)，按峰值降序。"""
    n_f, n_b = sal.shape
    out_idx = np.full((n_f, max_peaks), -1, dtype=np.int16)
    out_val = np.zeros((n_f, max_peaks), dtype=np.float32)
    left = sal[:, :-2]
    mid = sal[:, 1:-1]
    right = sal[:, 2:]
    is_pk = (mid >= left) & (mid > right) & (mid >= abs_thr)
    for i in range(n_f):
        cand = np.flatnonzero(is_pk[i]) + 1
        if cand.size == 0:
            continue
        v = sal[i, cand]
        thr = max(abs_thr, rel_thr * float(v.max()))
        keep = v >= thr
        cand, v = cand[keep], v[keep]
        if cand.size == 0:
            continue
        order = np.argsort(v)[::-1]
        picked: list[int] = []
        for k in order:
            b = int(cand[k])
            if all(abs(b - p) >= min_sep_bins for p in picked):
                picked.append(b)
            if len(picked) == max_peaks:
                break
        for j, b in enumerate(picked):
            out_idx[i, j] = b
            out_val[i, j] = sal[i, b]
    return out_idx, out_val


def harmonic_salience(y: np.ndarray, sr: int, hop: int, n_frames: int,
                      f_lo: float = 80.0, f_hi: float = 1000.0,
                      bins_per_semitone: int = 3, n_harm: int = 8):
    """谐波求和显著度，外加次谐波抑制。与神经网络完全独立。"""
    mag = stft_mag(y, n_fft=2048, hop=hop, win_length=2048)      # (F, T)
    freqs = np.linspace(0.0, sr / 2, mag.shape[0])
    n_c = int(round(12 * bins_per_semitone * np.log2(f_hi / f_lo))) + 1
    cand = f_lo * 2 ** (np.arange(n_c) / (12 * bins_per_semitone))
    # 谐波位置 → 频率 bin 索引
    idx = np.clip(np.round(np.outer(cand, np.arange(1, n_harm + 1))
                           / (freqs[1] - freqs[0])).astype(np.int64),
                  0, mag.shape[0] - 1)
    w = 1.0 / np.sqrt(np.arange(1, n_harm + 1))[None, :]          # 高次谐波降权
    T = min(mag.shape[1], n_frames)
    sal = np.zeros((T, n_c), dtype=np.float32)
    for t in range(T):
        col = mag[:, t]
        sal[t] = (col[idx] * w).sum(axis=1)
    # 次谐波抑制：候选 c 若能被 c/2、c/3 解释，扣掉那部分
    per_oct = 12 * bins_per_semitone
    sup = sal.copy()
    for div, sh in ((2, per_oct), (3, int(round(per_oct * np.log2(3))))):
        shifted = np.zeros_like(sal)
        if sh < n_c:
            shifted[:, sh:] = sal[:, :n_c - sh]
        sup -= 0.5 * shifted
    return np.maximum(sup, 0.0), cand


def report(cfg, song) -> None:
    P = cfg.pitch
    v = load_mono(song.vocals, P.sr)
    nv = load_mono(song.no_vocals, P.sr)
    nf = n_frames_for(min(v.size, nv.size), P.sr, P.hop_s)
    lines = lyrics.parse(song.lyrics, song.lyrics_skip_before_s)
    print(f"曲目 {song.title}   {min(v.size,nv.size)/P.sr:.2f}s   {nf} 帧")
    print(f"{lyrics.summary(lines)}")
    print(f"跑于 {datetime.now():%Y-%m-%d %H:%M}\n")

    act = from_stems(v, nv, P.hop_len, P.hop_s, nf,
                     rms_db_min=cfg.align.act_rms_db_min,
                     ratio_db_min=cfg.align.act_ratio_db_min,
                     close_s=cfg.align.act_close_s, open_s=cfg.align.act_open_s)
    sung = act.mask[:nf]
    print(f"人声活动帧 {int(sung.sum())}/{nf} = {100*sung.mean():.1f}%"
          f"（只在这些帧上统计复音，否则器乐渗漏会污染）\n")

    # ---------- 证据 A ----------
    est = RmvpeEstimator(cfg.model("rmvpe"))
    est._load()
    sal = est._salience(est._mel(v, P.sr))
    T = min(sal.shape[0], nf)
    sal, sung_a = sal[:T], sung[:T]
    print("=== 证据 A · RMVPE 显著图多峰 ===")
    print(f"  显著图 {sal.shape}，绝对阈 0.10，相对阈 0.25×峰值，峰间隔 ≥5 bin(100音分)")
    idx, val = find_peaks(sal, abs_thr=0.10, rel_thr=0.25, min_sep_bins=5)
    npk = (idx >= 0).sum(axis=1)
    for k in range(0, 4):
        m = sung_a & (npk == k)
        print(f"  {k} 个峰: {int(m.sum()):6d} 帧  {100*m.mean()/max(1e-9,sung_a.mean()):5.1f}% 的演唱帧")
    m2 = sung_a & (npk >= 2)
    print(f"  ≥2 个峰: {int(m2.sum()):6d} 帧 = 演唱帧的 "
          f"{100*m2.sum()/max(1,sung_a.sum()):.1f}%")

    print("\n  次峰相对首峰的音程分布（只算 ≥2 峰的演唱帧）：")
    d_cent = np.where(m2, bins_to_cents(idx[:, 1]) - bins_to_cents(idx[:, 0]), np.nan)
    d_semi = d_cent / 100.0
    hist_rows = []
    tot = int(m2.sum())
    for semi, nm in INTERVALS:
        for sgn in ((+1,) if semi == 0 else (+1, -1)):
            k = np.abs(d_semi - sgn * semi) <= 0.5
            c = int(np.nansum(k & m2))
            if c > 0:
                amb = "  ← 与泛音无法区分" if semi in HARMONIC_AMBIGUOUS else ""
                hist_rows.append((c, f"{'+' if sgn>0 else '-'}{nm}", amb))
    for c, nm, amb in sorted(hist_rows, reverse=True)[:14]:
        print(f"    {nm:>6}  {c:6d} 帧  {100*c/max(1,tot):5.1f}%{amb}")
    amb_mask = np.zeros(T, dtype=bool)
    for semi in HARMONIC_AMBIGUOUS:
        amb_mask |= (np.abs(np.abs(d_semi) - semi) <= 0.5)
    clean = m2 & ~amb_mask & np.isfinite(d_semi)
    print(f"  音程**不是**简单谐波关系（三度/四度/六度/七度等）的帧："
          f"{int(clean.sum())} = 演唱帧的 {100*clean.sum()/max(1,sung_a.sum()):.1f}%")
    print("  → 这部分是真复音的强证据；谐波关系的那部分单看显著图判不了")

    # ---------- 证据 B ----------
    print("\n=== 证据 B · 谐波求和显著度（自实现，不用神经网络）===")
    hs, cand = harmonic_salience(v, P.sr, P.hop_len, nf)
    Tb = min(hs.shape[0], T)
    hs, sung_b = hs[:Tb], sung[:Tb]
    mx = hs.max(axis=1, keepdims=True)
    hidx, hval = find_peaks(hs / np.maximum(mx, 1e-9), abs_thr=0.25,
                            rel_thr=0.35, min_sep_bins=6)
    hn = (hidx >= 0).sum(axis=1)
    mb = sung_b & (hn >= 2)
    print(f"  候选栅格 {hs.shape[1]} 个（80–1000Hz，每半音 3 格），8 次谐波，含次谐波抑制")
    print(f"  ≥2 个峰: {int(mb.sum())} 帧 = 演唱帧的 "
          f"{100*mb.sum()/max(1,sung_b.sum()):.1f}%")
    hz1 = np.where(hidx[:, 0] >= 0, cand[np.clip(hidx[:, 0], 0, None)], np.nan)
    hz2 = np.where(hidx[:, 1] >= 0, cand[np.clip(hidx[:, 1], 0, None)], np.nan)
    ds = 12 * np.log2(np.where(mb, hz2 / hz1, np.nan))
    amb_b = np.zeros(Tb, dtype=bool)
    for semi in HARMONIC_AMBIGUOUS:
        amb_b |= (np.abs(np.abs(ds) - semi) <= 0.5)
    cb = mb & ~amb_b & np.isfinite(ds)
    print(f"  非谐波关系音程的帧: {int(cb.sum())} = 演唱帧的 "
          f"{100*cb.sum()/max(1,sung_b.sum()):.1f}%")

    # ---------- 两条证据的一致性 ----------
    n = min(T, Tb)
    a_multi, b_multi = m2[:n], mb[:n]
    both = a_multi & b_multi
    union = a_multi | b_multi
    print("\n=== 两条证据的一致性 ===")
    print(f"  A 判多声部 {int(a_multi.sum())}  B 判多声部 {int(b_multi.sum())}"
          f"  两者都判 {int(both.sum())}"
          f"  Jaccard {both.sum()/max(1,union.sum()):.3f}")

    # ---------- 时间分布 vs LRC 括号行 ----------
    print("\n=== 复音的时间分布 vs LRC 括号行的推断 ===")
    hw = song.harmony_window_s
    tt = np.arange(n) * P.hop_s
    if hw:
        inw = (tt >= hw[0]) & (tt <= hw[1])
        sv = sung[:n]
        for nm, mm in (("A(RMVPE多峰)", a_multi), ("B(谐波求和)", b_multi)):
            i_r = mm[inw & sv].mean() if (inw & sv).any() else float("nan")
            o_r = mm[~inw & sv].mean() if (~inw & sv).any() else float("nan")
            print(f"  {nm:14s} 括号行区间内 {100*i_r:5.1f}%   区间外 {100*o_r:5.1f}%")
        print(f"  （括号行区间 = {hw[0]:.2f}–{hw[1]:.2f}s，占全曲 "
              f"{100*(hw[1]-hw[0])/(n*P.hop_s):.1f}%）")
        print("  若区间外也有可观复音，说明「和声只在括号行」这个文本推断不成立")

    print("\n=== 复音最密集的 12 个 10 秒窗口 ===")
    W = int(10.0 / P.hop_s)
    rows = []
    for s in range(0, n - W, W // 2):
        sv = sung[s:s + W]
        if sv.sum() < W * 0.2:
            continue
        rows.append((float(a_multi[s:s + W][sv].mean()) if sv.any() else 0.0,
                     s * P.hop_s, float(b_multi[s:s + W][sv].mean()) if sv.any() else 0.0))
    for r, t0, rb in sorted(rows, reverse=True)[:12]:
        inw = bool(hw and hw[0] <= t0 <= hw[1])
        print(f"  {t0:7.2f}–{t0+10:7.2f}s  A {100*r:5.1f}%  B {100*rb:5.1f}%"
              f"  {'← 括号行区间内' if inw else ''}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    cfg = config.load()
    song = cfg.song(args[0] if args else "chaosheng")
    song.require("vocals", "no_vocals", "lyrics")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(cfg, song)
    text = buf.getvalue()
    print(text, end="")
    if "--no-save" not in sys.argv:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / f"polyphony_{song.id}_{datetime.now():%Y%m%d_%H%M}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"\n报告已存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
