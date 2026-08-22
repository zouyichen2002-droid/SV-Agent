# -*- coding: utf-8 -*-
"""阶段 3 · 逐字对齐质量，以及「字 → 音符」的匹配性。

## 为什么需要一个非循环的匹配性判据

「CTC 对齐率 300/315」这类数字只说明**声学模型愿意在窗口里放下这些字**，
不说明字放对了位置。上一次失败正是这样：对齐率 95.2%，实听「很多歌词错位」。

这里的判据是：**CTC 给的字起音 vs 音符起音是否重合。**

  - 字起音来自 zh-ctc 声学模型（音素后验）
  - 音符起音来自 RMVPE + CREPE 的音高证据

两者是**完全不同的信息源**，一个看音素、一个看基频。它们独立地把同一段演唱
切成片段；如果切在同样的位置，那这个切分就大概率是真的。这不是循环验证。

用法: python eval/lyric_match.py [song_id] [--no-save] [--limit N]
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

from svchain import config, evidence, lyrics, notes as N
from svchain.align import from_stems
from svchain.align.ctc import CtcAligner, line_windows
from svchain.audio import cached_track, load_mono
from svchain.pitch import CrepeEstimator, RmvpeEstimator, n_frames_for

SEP_ROOT = Path(__file__).resolve().parents[1] / "out" / "sep"


def find_stem(song_id: str, model: str, role: str) -> Path:
    root = SEP_ROOT / song_id
    d = next(p for p in sorted(root.iterdir())
             if p.is_dir() and model.lower() in p.name.lower())
    tag = "(instrumental)" if role == "backing" else "(vocals)"
    return next(f for f in d.glob("*.wav") if tag in f.name.lower())


def report(cfg, song, limit: int) -> None:
    P = cfg.pitch
    v = load_mono(song.vocals, P.sr)
    nv = load_mono(song.no_vocals, P.sr)
    nf = n_frames_for(min(v.size, nv.size), P.sr, P.hop_s)
    dur = v.size / P.sr
    ls = lyrics.parse(song.lyrics, song.lyrics_skip_before_s)
    main = [l for l in ls if not l.is_harmony]
    harm = [l for l in ls if l.is_harmony]
    all_t = [l.t_s for l in ls]
    print(f"曲目 {song.title}   {dur:.2f}s")
    print(f"{lyrics.summary(ls)}")
    print(f"跑于 {datetime.now():%Y-%m-%d %H:%M}\n")

    al = CtcAligner(cfg.model("zh_ctc"), sr=P.sr)
    print(f"CTC 模型 {al.info}")
    for label, lines_ in (("主唱", main), ("和声", harm)):
        chars = [c for l in lines_ for c in l.chars]
        inv, tot, oov = al.coverage(chars)
        print(f"  {label}用字 {len(chars)} 个（去重 {tot}），词表覆盖 {inv}/{tot}"
              f" = {100*inv/max(1,tot):.1f}%"
              + (f"   OOV: {' '.join(oov)}" if oov else ""))
    print()

    act = from_stems(v, nv, P.hop_len, P.hop_s, nf,
                     rms_db_min=cfg.align.act_rms_db_min,
                     ratio_db_min=cfg.align.act_ratio_db_min,
                     close_s=cfg.align.act_close_s, open_s=cfg.align.act_open_s)

    for role, label, lines_ in (("lead", "主唱", main), ("backing", "和声", harm)):
        stem = find_stem(song.id, "mel_band_roformer", role)
        print("=" * 66)
        print(f"=== {label}（{role}）  stem {stem.name[:44]} ===")
        y = load_mono(stem, P.sr)

        # --- 音符：与写入工程时同一条路径 ---
        trs = []
        for e in (RmvpeEstimator(cfg.model("rmvpe")), CrepeEstimator(model="full")):
            tr, _ = cached_track(cfg.cache_dir, stem, e, P.sr, P.hop_s, nf,
                                P.fmin_hz, P.fmax_hz)
            trs.append(tr.gated(P.conf_gate))
        em = evidence.build(trs, P.agree_cents, min_agree=2)
        ns, _, _ = N.build(em.f0_hz, P.hop_s, 0.0, dur, n_agree=em.n_agree)
        note_on = np.array([nt.onset_s for nt in ns])
        print(f"  音符 {len(ns)} 个（未经写入侧的两道过滤，此处只用起音位置）")

        # --- CTC 对齐 ---
        todo = lines_[:limit] if limit else lines_
        wins = line_windows([l.t_s for l in todo], all_t, dur)
        results = []
        cc_all = []
        for k, (l, w) in enumerate(zip(todo, wins)):
            la, cc = al.align_line(y, l.chars, l.t_s, w, l.index,
                                   cross_check=(k < 3))
            results.append(la)
            if cc:
                cc_all.append(cc)
        n_ch = sum(r.n_chars for r in results)
        n_al = sum(r.aligned for r in results)
        print(f"  对齐 {len(results)} 行   字 {n_al}/{n_ch} = "
              f"{100*n_al/max(1,n_ch):.1f}%（直接对齐，无插值）")
        if cc_all:
            good = [c for c in cc_all if "error" not in c]
            if good:
                print(f"  与 torchaudio.forced_align 交叉校验（前 {len(good)} 行）："
                      f"起帧完全相同 {sum(c['same_start'] for c in good)}/"
                      f"{sum(c['n'] for c in good)}，"
                      f"最大差 {max(c['max_frame_diff'] for c in good)} 帧"
                      f"（1 帧 ≈ {good[0]['frame_ms']:.1f}ms）")
            else:
                print(f"  交叉校验不可用: {cc_all[0].get('error')}")

        spans = [s for r in results for s in r.spans]
        if not spans:
            print("  没有对齐结果，跳过匹配性分析\n")
            continue

        # --- 判据 1：字起音 落在人声活动里吗 ---
        idx = np.clip((np.array([s.t0 for s in spans]) / P.hop_s).astype(int),
                      0, act.mask.size - 1)
        print(f"  字起音落在人声活动内: {100*act.mask[idx].mean():.1f}%")

        # --- 判据 2（关键）：字起音 vs 音符起音 ---
        print("  字起音 与 音符起音 的距离（两者信息源完全不同）:")
        if note_on.size:
            d = np.abs(note_on[None, :] - np.array([s.t0 for s in spans])[:, None]).min(axis=1)
            for thr in (0.030, 0.050, 0.085, 0.150, 0.300):
                print(f"    ≤{thr*1000:3.0f}ms  {100*(d<=thr).mean():5.1f}%")
            print(f"    中位 {np.median(d)*1000:.0f}ms   90分位 "
                  f"{np.percentile(d,90)*1000:.0f}ms")

        # --- 判据 3：字间距 ---
        by_line = {}
        for r in results:
            if len(r.spans) >= 2:
                g = np.diff([s.t0 for s in r.spans])
                by_line[r.line_index] = g
        if by_line:
            allg = np.concatenate(list(by_line.values()))
            print(f"  相邻字起音间距: 中位 {np.median(allg)*1000:.0f}ms  "
                  f"<85ms 的 {100*(allg<0.085).mean():.1f}%"
                  f"（<85ms 一定是对齐误差，见 ADR-0001）")

        # --- 判据 3b：塌缩检测 ---
        # CTC 不确定时会把剩余字一次性喷在窗口一端。表现是该行的字全挤在很窄的
        # 跨度里。判据：本行字跨度 / 本行名义时长。名义时长取到下一演唱行。
        print("  塌缩检测（本行字跨度 / 名义行时长）:")
        ratios, collapsed = [], []
        for r in results:
            if len(r.spans) < 3:
                continue
            nxt = min((t for t in all_t if t > r.t_lrc + 0.5), default=r.t_lrc + 7.0)
            nominal = max(0.5, min(nxt - r.t_lrc, 12.0))
            got = r.spans[-1].t0 - r.spans[0].t0
            ratios.append(got / nominal)
            if got / nominal < 0.35:
                collapsed.append((r, got, nominal))
        if ratios:
            rr = np.array(ratios)
            print(f"    中位 {np.median(rr):.2f}   <0.35 的行 {int((rr<0.35).sum())}"
                  f"/{rr.size}   <0.15 的行 {int((rr<0.15).sum())}/{rr.size}")
            print("    （健康的行应该接近 1.0：字铺满整行。远小于 1 = 挤成一堆）")
        for r, got, nom in sorted(collapsed, key=lambda x: x[1] / x[2])[:6]:
            print(f"      L{r.line_index:02d} {r.t_lrc:7.2f}s {r.n_chars:2d}字  "
                  f"字跨度 {got:.2f}s / 名义 {nom:.2f}s = {got/nom:.2f}")

        # --- 判据 3c：行首偏移 ---
        # CTC 给的首字起音 vs LRC 标的行起始。系统性一致 = 对齐大方向对了。
        d0 = np.array([r.spans[0].t0 - r.t_lrc for r in results if r.spans])
        print(f"  首字起音 − LRC 行起始: 中位 {np.median(d0):+.3f}s  "
              f"|残差| 中位 {np.median(np.abs(d0 - np.median(d0))):.3f}s  "
              f"范围 {d0.min():+.2f}…{d0.max():+.2f}s")

        # --- 判据 4：置信度最低的行，交给耳朵抽查 ---
        worst = sorted(results, key=lambda r: (r.rate, np.mean(
            [s.logprob for s in r.spans]) if r.spans else -99))[:6]
        print("  最该人工抽查的 6 行（对齐率低 / 后验低）:")
        for r in worst:
            lpm = np.mean([s.logprob for s in r.spans]) if r.spans else float("nan")
            print(f"    L{r.line_index:02d} {r.t_lrc:7.2f}s  {r.n_chars:2d}字  "
                  f"对齐 {r.aligned:2d}  平均后验 {lpm:6.2f}"
                  + (f"  OOV {''.join(r.oov)}" if r.oov else ""))
        print()


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    cfg = config.load()
    song = cfg.song(args[0] if args else "chaosheng")
    song.require("vocals", "no_vocals", "lyrics")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(cfg, song, limit)
    text = buf.getvalue()
    print(text, end="")
    if "--no-save" not in sys.argv:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / f"lyric_match_{song.id}_{datetime.now():%Y%m%d_%H%M}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"\n报告已存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
