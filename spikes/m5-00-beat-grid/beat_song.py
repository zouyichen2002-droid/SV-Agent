# -*- coding: utf-8 -*-
"""C02 给别的歌找真拍子：grid_check（《傍晚》）的做法推广到没有 Suno 那种一条条分轨的歌。

- 裁判：伴奏整条 + librosa HPSS 从伴奏里拆出来的「打击部分」「和声部分」（和声部分再低通当贝斯）+ 人声的起音（最松，但来源独立）；
  量法全用 grid_check 的：起音强度按十六分折、和错的速度比、每 15 秒一段看锁没锁住、偏差前后在不在线内
- 候选：SynthV 自己的节拍分析（它存的是一张均匀网格：一个速度 + 第一拍）+ 配置里给的别的候选；
  另外在候选附近按整首的折叠长度细扫一遍速度和相位 —— 不偏向任何一个候选
- 小节线、灰的小节、尾声变速、节拍器试听：和 grid_check 一样
- 输入只读；结果写在 <out>/：grid.json（retime_svp、snap_round 读它）+ 节拍器试听
- 先跑 grid_check 的自检（每项注入已知的错），不过就不跑

    python beat_song.py <歌的配置.json>
配置：{"name", "svp": SynthV 分析过伴奏的工程（只读）, "accomp": 伴奏, "vocal": 人声, "out": 输出目录,
       "candidates": [{"from": "说明", "bpm": 数, "first_beat_s": 数}]}
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
import grid_check as GC                                         # noqa: E402

SR = 44100


def load(path: str) -> np.ndarray:
    y, sr = sf.read(path, dtype="float32")
    y = y.mean(axis=1) if y.ndim == 2 else y
    return y if sr == SR else signal.resample_poly(y, SR, sr).astype(np.float32)


def fine_scan(curves: dict, lo: float, hi: float, bpm0: float, span: float = 0.6, step: float = 0.002) -> tuple[float, float, float]:
    """在 bpm0 ±span 里扫速度：[lo, hi) 这一段几条裁判合起来（每条一样重）按十六分折的长度最大的那个 → (速度, 第一拍相位 秒, 长度)。"""
    best = (bpm0, 0.0, -1.0)
    for b in np.arange(bpm0 - span, bpm0 + span + 1e-9, step):
        r, ph = GC.combo_fold(curves, lo, hi, float(b), 0.0)
        if r > best[2]:
            best = (float(b), ph / 1000.0, r)
    b, ph, r = best
    return b, ph % (60 / b / 4), r


def refine_start(curves: dict, bpm: float, t0: float, s_from: float, s_to: float, ref_ms: float) -> tuple[float, list[dict]]:
    """和 grid_check.refine_end 对称：从「速度对的那段」开头往后 30 秒起、8 秒窗每次往前挪 2 秒；
    最前面一个还锁得住、偏差离中位不超过线的窗，它的开头就是开头。"""
    d = 60 / bpm / 4 * 1000
    start, log = None, []
    x = min(s_from + 2 * GC.WIN, s_to - 8.0)
    while x >= 0:
        r, ph = GC.combo_fold(curves, x, x + 8.0, bpm, t0)
        null = np.array([GC.combo_fold(curves, x, x + 8.0, b, t0)[0] for b in GC.null_for(bpm)])
        z = float((r - null.mean()) / (null.std() + 1e-12))
        dev = (ph - ref_ms + d / 2) % d - d / 2
        ok = z >= GC.Z_LOCK and abs(dev) <= GC.LIMIT * 1000
        log.append({"from_s": float(x), "z": round(z, 1), "dev_ms": round(float(dev), 1), "ok": bool(ok)})
        if ok:
            start = float(x)
        elif start is not None:
            break
        x -= 2.0
    return (start if start is not None else s_from), log


def main(cfg_path: str) -> int:
    fails = GC.selftest()
    print("自检（grid_check 的）：", "通过" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    cfg = json.loads(pathlib.Path(cfg_path).read_text(encoding="utf-8"))
    out = pathlib.Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)

    d = BG.load_svp(pathlib.Path(cfg["svp"]))
    acc_name = pathlib.Path(cfg["accomp"]).name
    tr = next(t for t in d["tracks"] if t["mainRef"].get("audio") and pathlib.Path(t["mainRef"]["audio"]["filename"]).name == acc_name)
    a = tr["mainRef"]["audio"]
    b = np.array(a["beatLocations"])
    k = np.round((b - b[0]) / np.median(np.diff(b)))
    fit = np.polyfit(k, b, 1)
    uniform_ms = float(np.abs(b - np.polyval(fit, k)).max() * 1000)
    cands = [{"from": "SynthV 的节拍分析", "bpm": 60 / fit[0], "first_beat_s": float(fit[1])}] + cfg.get("candidates", [])
    print(f"SynthV：{a['bpm']:.4f} BPM，备选 {[round(x, 3) for x in a.get('alternativeBPMs') or []]}；{len(b)} 个拍点是均匀网格"
          f"（离直线最多 {uniform_ms:.3f} ms）")

    acc = load(cfg["accomp"])
    voc = load(cfg["vocal"])
    dur = len(acc) / SR
    harm, perc = librosa.effects.hpss(acc)
    sos = signal.butter(4, 250, "lowpass", fs=SR, output="sos")
    bass = signal.sosfiltfilt(sos, harm).astype(np.float32)
    curves = {"伴奏整条": GC.strength(acc, SR), "打击部分": GC.strength(perc, SR), "和声部分": GC.strength(harm, SR),
              "人声": GC.strength(voc, SR)}

    print("\n候选（每 15 秒一段，锁住的写偏差 ms，没锁住写 ·）：")
    scored = []
    for c in cands:
        bpm, t0 = c["bpm"], c["first_beat_s"]
        tabs = {n: GC.lock_table(*cv, bpm, t0, dur) for n, cv in curves.items()}
        span = GC.locked_span({n: v for n, v in tabs.items() if n != "人声"}, bpm)
        c.update(tabs=tabs, span=span)
        scored.append(c)
        print(f"  {c['from']}：{bpm:.4f} BPM、第一拍 {t0:.4f} s → 速度对的一段 {span['from_s']}–{span['to_s']} s（{span['segments']} 段）")
        print("       " + " ".join(f"{r['from_s']:>5.0f}" for r in tabs["伴奏整条"]))
        for n, rows in tabs.items():
            print(f"    {n:<5} " + " ".join(f"{r['phase_ms']:+5.0f}" if r["locked"] else "    ·" for r in rows))

    base = max(scored, key=lambda c: (c["span"]["segments"], -abs(c["bpm"] - scored[0]["bpm"])))
    judges = {n: curves[n] for n in ("打击部分", "和声部分", "伴奏整条")}
    lo, hi = base["span"]["from_s"] or 0.0, base["span"]["to_s"] or dur
    fb, fph, fr = fine_scan(judges, lo, hi, base["bpm"])
    d16 = 60 / fb / 4
    t0 = fph
    ref0 = base["first_beat_s"] % (60 / fb)                         # 相位对到候选那一拍（拍点等价类里最近的）
    t0 = t0 + round((ref0 - t0) / d16) * d16
    fine_tabs = {n: GC.lock_table(*cv, fb, t0, dur) for n, cv in curves.items()}
    fine_span = GC.locked_span({n: v for n, v in fine_tabs.items() if n != "人声"}, fb)
    print(f"\n不看候选、在 {base['bpm']:.3f} ±0.6 细扫（{lo:.0f}–{hi:.0f} s 这一段，打击 + 和声 + 整条）：{fb:.3f} BPM，相位 {t0:.4f} s "
          f"→ 速度对的一段 {fine_span['from_s']}–{fine_span['to_s']} s（{fine_span['segments']} 段）")
    for n, rows in fine_tabs.items():
        print(f"    {n:<5} " + " ".join(f"{r['phase_ms']:+5.0f}" if r["locked"] else "    ·" for r in rows))

    fine = {"from": "细扫", "bpm": fb, "first_beat_s": t0, "tabs": fine_tabs, "span": fine_span}
    best_cand = max(scored, key=lambda c: c["span"]["segments"])
    # 细扫的锁住段不比最好的候选短，就用细扫（相位是按数据对正的）；否则用那个候选
    pick = fine if fine_span["segments"] >= best_cand["span"]["segments"] else best_cand
    bpm, t0, tabs, span = pick["bpm"], pick["first_beat_s"], pick["tabs"], pick["span"]
    T = 60 / bpm
    phases = {n: (round(float(np.median([r["phase_ms"] for r in rows if r["locked"]])), 1)
                  if any(r["locked"] for r in rows) else None) for n, rows in tabs.items()}
    ref = float(np.median([v for n, v in phases.items() if v is not None and n != "人声"]))
    s_from, s_to = span["from_s"], min(span["to_s"], dur)
    s_to, fine_end = GC.refine_end(judges, bpm, t0, s_from, s_to, ref)
    s_to = min(s_to, dur)
    s_from, fine_start = refine_start(judges, bpm, t0, s_from, s_to, ref)
    print(f"\n用「{pick['from']}」：{bpm:.4f} BPM、第一拍 {t0:.4f} s；速度对的一段 {s_from:.0f}–{s_to:.0f} s"
          f"（{int(s_from // 60)}:{s_from % 60:04.1f}–{int(s_to // 60)}:{s_to % 60:04.1f}）；各裁判偏差中位 {phases}")
    print("  细看开头（8 秒窗，往前扫）：" + " ".join(f"{r['from_s']:.0f}s{'✓' if r['ok'] else '✗'}(z{r['z']:.0f},{r['dev_ms']:+.0f})"
                                              for r in fine_start))
    print("  细看结尾（8 秒窗）：" + " ".join(f"{r['from_s']:.0f}s{'✓' if r['ok'] else '✗'}(z{r['z']:.0f},{r['dev_ms']:+.0f})"
                                         for r in fine_end))
    lo_b, hi_b = bpm * 0.75, bpm * 1.25                            # 扫速度的范围跟着这首歌的速度
    intro = [(x, GC.local_tempo(judges, x, x + 8.0, lo_b, hi_b)) for x in np.arange(0.0, s_from - 7.9, 4.0)]
    inside = [(x, GC.local_tempo(judges, x, x + 8.0, lo_b, hi_b)) for x in np.arange(s_from, s_from + 24.1, 8.0)]
    after = [(x, GC.local_tempo(judges, x, x + 8.0, lo_b, hi_b)) for x in np.arange(s_to, dur - 7.9, 4.0)]
    print(f"  每 8 秒窗自己最合的速度（{lo_b:.0f}–{hi_b:.0f} 里扫）：开头之前 " + (" ".join(f"{x:.0f}s:{v:.1f}" for x, v in intro) or "（没有）")
          + " ｜ 速度对的那段开头 " + " ".join(f"{x:.0f}s:{v:.1f}" for x, v in inside)
          + " ｜ 结尾之后 " + (" ".join(f"{x:.0f}s:{v:.1f}" for x, v in after) or "（没有）"))
    before = inside

    beats = t0 + T * np.arange(int((dur - t0) / T) + 1)
    feat = GC.beat_features({"鼓": perc, "键盘": harm, "贝斯": bass}, SR, beats)
    in_span = (beats[:-1] >= s_from) & (beats[:-1] < s_to)
    db = GC.downbeat(feat, np.ones(len(beats) - 1, bool), in_span)
    print("小节线（8 拍里每一位的平均，0 = 第一拍）：")
    for kname, row in db["table"].items():
        print(f"  {kname:<5} " + " ".join(f"{v:6.3f}" for v in row))
    one = t0 + db["one_132"] * T
    runs = GC.odd_bars(feat["换和弦"], db["one_132"])
    for r in runs:
        x, z = one + r["from_bar"] * 4 * T, one + (r["to_bar"] + 1) * 4 * T
        r.update(from_s=round(x, 1), to_s=round(z, 1), in_span=bool(z <= s_to + T))
        print(f"  灰：{x:.1f}–{z:.1f} s 连着 {r['n_bars']} 个小节换和弦都挪到第 {r['beat']} 拍"
              f"{'' if r['in_span'] else '（在速度对的那一段之后）'}")
    print(f"  → 「1」在拍位 {db['one_132']}（4/4，每 4 拍一小节），第一个「1」在 {one:.4f} s；底鼓同意 {db['kick_agrees']}")

    mix = np.stack([acc + voc, acc + voc], axis=1) * 0.7
    last = int(np.searchsorted(beats, s_to))
    idx = np.arange(db["one_132"] % 1, last)
    acc_mark = ((idx - db["one_132"]) % 4) == 0
    c = GC.clicks(beats[idx], acc_mark, SR, len(mix))
    m = mix + c[:, None]
    peak = float(np.abs(m).max())
    m = m * (0.98 / peak) if peak > 0.98 else m
    wav = out / f"{cfg['name']}_节拍器.wav"
    if not wav.exists():
        sf.write(str(wav), m, SR, subtype="PCM_16")
    got = GC.attacks(c, SR)
    err = float(np.max(np.abs(got - beats[idx][:len(got)]))) * 1000 if len(got) == len(idx) else float("nan")
    print(f"试听 {wav}：{len(idx)} 下节拍、「1」{int(acc_mark.sum())} 下，响到 {s_to:.0f} s；反测拍点最多差 {err:.2f} ms")

    res = {"name": cfg["name"], "config": cfg,
           "synthv": {"bpm": a["bpm"], "alternatives": a.get("alternativeBPMs"), "n_beats": len(b), "uniform_grid_max_ms": uniform_ms},
           "candidates": [{k2: v for k2, v in c2.items() if k2 != "tabs"} for c2 in scored],
           "fine_scan": {"bpm": fb, "first_beat_s": t0, "R": fr, "span": fine_span},
           "picked": pick["from"],
           "grid": {"bpm": bpm, "first_beat_s": t0, "beat_s": T, "first_one_s": one,
                    "bpm_132": bpm, "first_one_s_132": one},              # 后两个名字是给 retime_svp / snap_round 的（《傍晚》时起的名）
           "tempo_span": {"from_s": s_from, "to_s": s_to, "fine": fine_end},
           "phase_ms": phases, "local_tempo": {"before_end": before, "outro": after},
           "downbeat": db, "gray_runs": runs, "listen": str(wav), "lock_tables": tabs}
    (out / "grid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: o.item()), encoding="utf-8")
    print(f"结果：{out / 'grid.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
