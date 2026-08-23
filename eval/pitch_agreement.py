# -*- coding: utf-8 -*-
"""阶段 1 · 跨估计器音高证据层的测量。

产出的**不是**「某个估计器的 f0」，而是「哪些帧有被独立确认的音高、哪些没有」。
门槛数值由人定，本脚本只给分布。

三个估计器刻意跨算法族选取 —— 同族互验会一起犯同一种错：

    torchcrepe   neural          通用音高，训练语料以语音/乐器为主
    praat-ac     autocorr        自相关，与 pyin（差分函数）同源
    rmvpe        neural-singing   歌声专训，前端经实测标定（见 scripts/calibrate_rmvpe.py）

用法:
    python eval/pitch_agreement.py [song_id] [--force] [--no-save]
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import config, evidence
from svagent.audio import cached_track, load_mono
from svagent.pitch import (CrepeEstimator, PraatEstimator, RmvpeEstimator,
                           n_frames_for)

# 交接文件 §5.3 记录的三个 pyin 失效点。新估计器必须在这里被单独检查，
# 「整体准确率」会把这种局部灾难平均掉。
KNOWN_TRAPS = [
    (49.3, 50.5, 67.90, "气声/强混段：pyin vprob 中位 0.01 但确在唱（rms −18.8dB）"),
    (139.9, 140.6, 68.90, "pyin 锁三次次谐波：正确 68.90 半音被报成 50.00"),
    (110.0, 113.0, 77.90, "LRC 无词但有稳定 77.9 半音：和声尾音 or 器乐渗漏"),
]
GATES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


def parse_lrc(path: Path, skip_before: float):
    ts = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
    rows = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        s = raw.strip()
        m = ts.match(s)
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        text = ts.sub("", s).strip()
        han = len(re.findall(r"[一-鿿]", text))
        if han == 0 or re.match(r"^[A-Za-z][A-Za-z ./&]*[:：]", text):
            continue
        if t < skip_before:
            continue
        rows.append((t, han, ("(" in text or "（" in text)))
    rows.sort()
    return rows


def hz_to_midi(f):
    return 69.0 + 12.0 * np.log2(np.asarray(f, float) / 440.0)


def report(cfg, song, force: bool) -> None:
    P = cfg.pitch
    y = load_mono(song.vocals, P.sr)
    n = n_frames_for(y.size, P.sr, P.hop_s)
    dur = y.size / P.sr
    print(f"曲目 {song.title}   {dur:.3f}s   {n} 帧 @ {P.hop_s*1000:.0f}ms")
    print(f"配置 {cfg.source.name}   一致判据 ±{P.agree_cents:.0f} 音分"
          f"（{P.agree_cents/100:.1f} 半音）")
    print(f"跑于 {datetime.now():%Y-%m-%d %H:%M}\n")

    ests = [CrepeEstimator(model="full"), PraatEstimator(),
            RmvpeEstimator(cfg.model("rmvpe"))]
    tracks = []
    print("=== 估计器 ===")
    for e in ests:
        t0 = time.perf_counter()
        tr, hit = cached_track(cfg.cache_dir, Path(song.vocals), e, P.sr, P.hop_s,
                              n, P.fmin_hz, P.fmax_hz, force=force)
        el = time.perf_counter() - t0
        print(f"  {tr.name:12s} {tr.family:14s} 原始有声 {100*tr.voiced.mean():5.1f}%"
              f"   {'缓存' if hit else f'{el:.1f}s'}")
        tracks.append(tr)

    print("\n=== 置信门控扫描 ===")
    print("  CREPE 从不输出「无声」—— 它对任何输入都给一个 f0。不做门控时它的"
          "「有声率」是假的，必须靠周期性门限。Praat/RMVPE 自带无声判决，门控是加严。")
    print(f"\n  {'门限':>6}" + "".join(f"{t.name:>14}" for t in tracks))
    for g in GATES:
        row = f"  {g:>6.1f}"
        for tr in tracks:
            v = (tr.confidence >= g) & tr.voiced
            row += f"{100*v.mean():13.1f}%"
        print(row)

    print(f"\n=== 两两一致性（仅两者都判有声的帧，门限 {P.conf_gate}）===")
    gated = [tr.gated(P.conf_gate) for tr in tracks]
    for i in range(len(gated)):
        for j in range(i + 1, len(gated)):
            s = evidence.compare(gated[i], gated[j], P.agree_cents)
            same = tracks[i].family == tracks[j].family
            print(f"  {s.a} vs {s.b}"
                  f"   [{'同族' if same else '跨族'}]")
            print(f"    共同有声 {s.both_voiced:6d} 帧（有声集合 Jaccard {s.voiced_jaccard:.3f}）")
            print(f"    一致 {100*s.agree_rate:5.1f}%   八度差 {100*s.octave_rate:5.1f}%"
                  f"   其它不一致 {100*s.other/max(1,s.both_voiced):5.1f}%")
            print(f"    |Δ| 中位 {s.median_abs_cents:6.1f} 音分   90分位 "
                  f"{s.p90_abs_cents:7.1f} 音分")

    print("\n=== 音高证据覆盖 ===")
    print(f"  {'门限':>6} {'≥2一致':>9} {'≥3一致':>9} {'簇内散布中位':>13} {'>1s空洞':>9}")
    for g in (0.0, 0.2, 0.3, 0.5):
        gt = [tr.gated(g) for tr in tracks]
        e2 = evidence.build(gt, P.agree_cents, min_agree=2)
        e3 = evidence.build(gt, P.agree_cents, min_agree=3)
        sp = e2.spread_cents[np.isfinite(e2.spread_cents)]
        gaps = e2.gaps(1.0)
        print(f"  {g:>6.1f} {100*e2.coverage():8.1f}% {100*e3.coverage():8.1f}%"
              f" {np.median(sp) if sp.size else float('nan'):12.1f} "
              f"{len(gaps):6d} 处/{sum(b-a for a,b in gaps):.0f}s")

    em = evidence.build(gated, P.agree_cents, min_agree=P.min_agree,
                        required=P.required)
    print(f"\n  采用规则（ADR-0004）：门限 {P.conf_gate} / ≥{P.min_agree} 一致 / "
          f"必须含 {list(P.required) or '无'}   →   覆盖 {100*em.coverage():.1f}%")
    print("  确认来源拆解（占有证据帧）：")
    tot = max(1, int(em.has_evidence.sum()))
    for nm in em.sources:
        k = em.confirmed_by(nm)
        print(f"    {nm:12s} 参与确认 {int(k.sum()):6d} 帧  {100*k.sum()/tot:5.1f}%")
    for k in (2, 3):
        mk = em.has_evidence & (em.n_agree == k)
        print(f"    恰好 {k} 个确认   {int(mk.sum()):6d} 帧  {100*mk.sum()/tot:5.1f}%")
    gaps = em.gaps(1.0)
    print(f"  >1s 无证据空洞 {len(gaps)} 处，合计 "
          f"{sum(b-a for a,b in gaps):.1f}s（占全曲 {100*sum(b-a for a,b in gaps)/dur:.1f}%）")
    for a, b in sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[:8]:
        print(f"    {a:7.2f} – {b:7.2f}s  ({b-a:5.2f}s)")

    print("\n=== 演唱区间内的覆盖（LRC 主唱行）===")
    rows = parse_lrc(Path(song.lyrics), song.lyrics_skip_before_s)
    main_rows = [r for r in rows if not r[2]]
    print(f"  主唱行 {len(main_rows)} 行 / {sum(r[1] for r in main_rows)} 字"
          f"（已跳过 {song.lyrics_skip_before_s:.0f}s 之前，见 "
          f"specs/benchmark-facts-chaosheng.md §2）")
    per_line = []
    for k, (t, han, _) in enumerate(main_rows):
        end = main_rows[k + 1][0] if k + 1 < len(main_rows) else t + han * 0.30
        end = min(end, t + han * 0.45)
        i0, i1 = int(t / P.hop_s), int(end / P.hop_s)
        seg = em.has_evidence[i0:i1]
        if seg.size:
            per_line.append((float(seg.mean()), t, end, han))
    cov = np.array([c for c, *_ in per_line])
    print(f"  逐行覆盖  中位 {100*np.median(cov):.1f}%   最差 {100*cov.min():.1f}%"
          f"   最好 {100*cov.max():.1f}%   <50% 的行 {int((cov<0.5).sum())}/{cov.size}")
    print("  覆盖最差的 8 行：")
    for c, a, b, han in sorted(per_line)[:8]:
        inh = bool(song.harmony_window_s
                   and song.harmony_window_s[0] <= a <= song.harmony_window_s[1])
        print(f"    {a:7.2f}–{b:7.2f}s ({han:2d}字) 覆盖 {100*c:5.1f}%"
              f"  {'← 和声区间内' if inh else ''}")

    print("\n=== 交接文件记录的三个 pyin 失效点 ===")
    for a, b, ref_midi, why in KNOWN_TRAPS:
        i0, i1 = int(a / P.hop_s), int(b / P.hop_s)
        print(f"  {a:6.2f}–{b:6.2f}s  {why}")
        print(f"    参考值 MIDI {ref_midi:.2f}")
        for tr in gated:
            f = tr.f0_hz[i0:i1]
            v = np.isfinite(f)
            md = hz_to_midi(np.median(f[v])) if v.any() else float("nan")
            d = md - ref_midi if np.isfinite(md) else float("nan")
            print(f"      {tr.name:12s} 有声 {100*v.mean():5.1f}%  MIDI {md:6.2f}"
                  f"  偏差 {d:+6.2f} 半音")
        e = em.has_evidence[i0:i1]
        f = em.f0_hz[i0:i1]
        v = np.isfinite(f)
        md = hz_to_midi(np.median(f[v])) if v.any() else float("nan")
        print(f"      → 证据层  有证据 {100*e.mean():5.1f}%  MIDI {md:6.2f}"
              f"  偏差 {md-ref_midi:+6.2f} 半音")

    if song.harmony_window_s:
        h0, h1 = song.harmony_window_s
        tt = np.arange(em.f0_hz.size) * P.hop_s
        ih = (tt >= h0) & (tt <= h1)
        print(f"\n=== 和声区间内外（{h0:.2f}–{h1:.2f}s）===")
        print(f"  区间内 覆盖 {100*em.has_evidence[ih].mean():5.1f}%"
              f"   区间外 覆盖 {100*em.has_evidence[~ih].mean():5.1f}%")
        print("  交接文件称 stem 混了主唱/和声是「总闸门」。若两者接近，"
              "该说法不成立 —— 见 specs/benchmark-facts-chaosheng.md §3.3")

    # ---- 门槛判定 ----
    g = cfg.gate("stage1")
    best_pair = max(
        (evidence.compare(a, b, P.agree_cents)
         for a, b in [(gated[i], gated[j])
                      for i in range(len(gated)) for j in range(i + 1, len(gated))]),
        key=lambda s: s.agree_rate)
    line_med = float(np.median(cov))
    checks = [
        ("最佳一对独立估计器的一致率",
         best_pair.agree_rate, g["pair_agree_min"],
         f"{best_pair.a} vs {best_pair.b}"),
        ("演唱行音高证据覆盖中位", line_med, g["line_coverage_median_min"], ""),
    ]
    print("\n=== 阶段 1 门槛判定（ADR-0004）===")
    ok_all = True
    for label, got, need, note in checks:
        ok = got >= need
        ok_all &= ok
        print(f"  {'通过' if ok else '未过'}  {label:<26} 实测 {100*got:5.1f}%  "
              f"门槛 ≥{100*need:.0f}%  余量 {100*(got-need):+5.1f} 个百分点"
              f"{('   ' + note) if note else ''}")
    print(f"\n  阶段 1：{'通过，可进阶段 2（逐行 LRC 偏移）' if ok_all else '未过，停下报告'}")
    if ok_all:
        print("  提醒：覆盖中位余量只有 "
              f"{100*(line_med-g['line_coverage_median_min']):+.1f} 个百分点，很薄。"
              "换素材后要重跑，不要当作已经稳。")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    song_id = args[0] if args else "chaosheng"
    force = "--force" in sys.argv
    save = "--no-save" not in sys.argv

    cfg = config.load()
    song = cfg.song(song_id)
    song.require("vocals", "lyrics")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(cfg, song, force)
    text = buf.getvalue()
    print(text, end="")

    if save:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / f"pitch_agreement_{song_id}_{datetime.now():%Y%m%d_%H%M}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"\n报告已存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
