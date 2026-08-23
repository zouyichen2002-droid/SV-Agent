# -*- coding: utf-8 -*-
"""阶段 2 门槛测量：逐行 LRC 偏移。

活动掩码只来自两条 stem 的能量（见 align/activity.py），**不看 LRC 时间戳**，
也不看音高估计器 —— 否则拿它去验 LRC 偏移就是循环论证。

报告只输出时间与字数，不输出歌词文本（版权）。

用法: python eval/line_offset.py [song_id] [--no-save]
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
from svagent.align import stage2
from svagent.align.activity import from_stems
from svagent.audio import load_mono
from svagent.pitch import n_frames_for

# 带标签锚点，用于回报检测器在本次运行下的表现（用于挑阈值的那批，见 activity.py）
SING = [(23.54, 28.60), (35.25, 40.30), (58.28, 63.00), (85.61, 88.30),
        (164.81, 169.00), (186.94, 190.00)]
NOSING = [(0.0, 2.30), (14.0, 23.40), (115.0, 124.0), (202.5, 212.0), (220.9, 229.4)]


def report(cfg, song) -> None:
    P = cfg.pitch
    v = load_mono(song.vocals, P.sr)
    nv = load_mono(song.no_vocals, P.sr)
    n = min(v.size, nv.size)
    nf = n_frames_for(n, P.sr, P.hop_s)
    lines = lyrics.parse(song.lyrics, song.lyrics_skip_before_s)
    mains = [l for l in lines if not l.is_harmony]
    print(f"曲目 {song.title}   {n/P.sr:.2f}s   {nf} 帧 @ {P.hop_s*1000:.0f}ms")
    print(f"{lyrics.summary(lines)}")
    print(f"跑于 {datetime.now():%Y-%m-%d %H:%M}\n")

    print("=== 人声活动检测（只用两条 stem 的能量）===")
    for rms_thr, rat_thr in ((-23.0, 2.0), (-25.0, 2.0), (-23.0, 0.0), (-20.0, 2.0)):
        a = from_stems(v, nv, P.hop_len, P.hop_s, nf,
                       rms_db_min=rms_thr, ratio_db_min=rat_thr)
        s = np.array([a.fraction_in(x, y) for x, y in SING])
        ns = np.array([a.fraction_in(x, y) for x, y in NOSING])
        segs = a.segments
        L = np.array([b - x for x, b in segs])
        mark = " ←采用" if (rms_thr, rat_thr) == (-23.0, 2.0) else ""
        print(f"  rms≥{rms_thr:+.0f}dB ratio≥{rat_thr:+.0f}dB → {len(segs):3d}段 "
              f"活动 {L.sum():6.1f}s  段长中位 {np.median(L):4.2f}s  "
              f"在唱锚点 {100*s.mean():5.1f}%  无唱锚点 {100*ns.mean():4.1f}%{mark}")
    A = cfg.align
    # 与 scripts/make_listening_checks.py 走同一条装配，避免两个入口各自拼出
    # 不同的速率与全局偏移（曾经真的发生过：0.340 vs 0.360、+0.070 vs +0.020）
    st2 = stage2(cfg, song)
    act, rate, gd = st2.activity, st2.rate_s_per_char, st2.global_delta_s
    n_char_all = sum(l.n_chars for l in lines)

    print(f"\n=== 演唱速率 ===")
    print(f"  实测 {rate:.3f} s/字 = {1/rate:.2f} 字/秒")
    print(f"  一致性检查：{n_char_all} 字 × {rate:.3f} = "
          f"{n_char_all*rate:.1f}s 名义演唱时长，实测活动 "
          f"{act.mask.sum()*P.hop_s:.1f}s（主唱与和声有时间重叠，实测应偏小）")

    offs = st2.offsets
    m = st2.main_offsets
    dec = np.array([o.decisive for o in m])
    d = np.array([o.delta_s for o in m])
    pl = np.array([o.plateau_s for o in m])
    hit = np.array([o.hit for o in m])
    found = np.array([o.onset_found for o in m])
    res = np.array([o.onset_residual_s for o in m])
    jdg = np.array([o.judgeable for o in m])
    gapb = np.array([min(o.gap_before_s, 9.99) for o in m])

    print(f"\n=== 全局偏移基线 ===")
    print(f"  匹配滤波最优全局偏移 {gd:+.3f}s"
          f"（交接文件 §4.1 用完全不同的方法估的是 ≈0，独立吻合）")
    print(f"  搜索半径 ±{A.max_shift_s:.2f}s，向全局偏移拉回的先验权重 {A.prior_w:.2f}")

    print(f"\n=== 逐行偏移（主唱行 {len(m)} 条）===")
    print(f"  可定住的行（不确定度 ≤{A.decisive_plateau_s*1000:.0f}ms）"
          f"  {int(dec.sum())}/{len(m)}")
    print(f"  定不住的行，退回全局偏移并标记   {int((~dec).sum())}/{len(m)}")
    if dec.any():
        dd = d[dec]
        print(f"  可定住行的 δ：中位 {np.median(dd):+.3f}s  |δ| 中位 "
              f"{np.median(np.abs(dd)):.3f}s  |δ| 90分位 "
              f"{np.percentile(np.abs(dd), 90):.3f}s  范围 {dd.min():+.2f}…{dd.max():+.2f}s")
        print(f"  不确定度：可定住行中位 {np.median(pl[dec])*1000:.0f}ms  "
              f"定不住行中位 {np.median(pl[~dec])*1000:.0f}ms" if (~dec).any()
              else f"  不确定度：中位 {np.median(pl[dec])*1000:.0f}ms")
    print(f"  盒内活动占比 中位 {np.median(hit):.3f}  最差 {hit.min():.3f}")

    print(f"\n=== 逐行明细（主唱行）===")
    print(f"  {'行':>4} {'LRC':>8} {'δ':>7} {'校正后':>8} {'字':>3} {'盒长':>6} "
          f"{'前间隔':>7} {'命中':>6} {'不定':>7} {'定住':>5} {'起音残差':>9} 可判")
    for o in m:
        rs = f"{o.onset_residual_s*1000:6.0f}ms" if o.onset_found else "   无起音"
        flag = ""
        if o.decisive and abs(o.delta_s) > 0.5:
            flag += " 大偏移"
        if o.hit < 0.5:
            flag += " 命中低"
        if o.judgeable and o.onset_residual_s > 0.15:
            flag += " 残差超线"
        gb = "  ∞" if not np.isfinite(o.gap_before_s) else f"{o.gap_before_s:5.2f}"
        print(f"  L{o.line.index:02d} {o.line.t_s:8.2f} {o.delta_s:+7.3f} "
              f"{o.corrected_t_s:8.2f} {o.line.n_chars:3d} {o.box_len_s:6.2f} "
              f"{gb:>7} {o.hit:6.3f} {o.plateau_s*1000:6.0f}ms "
              f"{'是' if o.decisive else '否':>4} {rs}"
              f"  {'是' if o.judgeable else '否'}{flag}")

    # ---- 门槛判定 ----
    g = cfg.gate("stage2")
    need = float(g["line_residual_max_s"])
    jud = jdg
    print(f"\n=== 阶段 2 门槛判定 ===")
    print(f"  门槛：每行残差 < {need*1000:.0f}ms")
    print(f"  可判定的行 {int(jud.sum())}/{len(m)}"
          f"（须同时：活动信号能定住 + LRC 行距表明前面有气口 ≥300ms + 找到起音）")
    print(f"  对照：只要「定住 + 找到起音」是 {int((dec & found).sum())}/{len(m)}，"
          f"其中 {int((dec & found & ~jdg).sum())} 条紧接前一行、起点处本无起音，")
    print(f"        对它们量「到最近起音的距离」是无意义的（L13 就这样被误报成 370ms）")
    print(f"  前间隔 <300ms 的行 {int((gapb < 0.30).sum())}/{len(m)}"
          f" —— 这首歌大段是连唱，没有气口可依")
    if jud.any():
        r = res[jud]
        print(f"  过线 {int((r<=need).sum())}/{int(jud.sum())}"
              f"   残差中位 {np.median(r)*1000:.0f}ms  90分位 "
              f"{np.percentile(r,90)*1000:.0f}ms  最大 {r.max()*1000:.0f}ms")
    cover = jud.sum() / len(m)
    passed = bool(jud.any() and (res[jud] <= need).all() and cover >= 0.5)
    print(f"\n  阶段 2：{'通过' if passed else '未过 —— 停下报告，不进阶段 3'}")
    if not passed:
        bad = [o for o in m if o.judgeable and o.onset_residual_s > need]
        if bad:
            print(f"  超线的行（{len(bad)} 条）：")
            for o in sorted(bad, key=lambda x: -x.onset_residual_s)[:10]:
                print(f"    L{o.line.index:02d} {o.line.t_s:7.2f}s  "
                      f"残差 {o.onset_residual_s*1000:.0f}ms  δ {o.delta_s:+.3f}s")
        if cover < 0.5:
            print(f"  判据覆盖不足：只有 {int(jud.sum())}/{len(m)} 行"
                  f"（{100*cover:.0f}%）可判定，低于 50%。")

    print("\n=== 「残差」这个判据的局限（需要决策）===")
    print("  当前定义：校正后行起点 与 最近声学起音 的距离。")
    print("  三类行判不了：(a) 活动信号定不住的；(b) 紧接前一行、起点处本无起音；")
    print("               (c) 附近没找到起音的。")
    print(f"  本曲实测可判定 {int(jud.sum())}/{len(m)} 行。")
    print("  替代定义（阶段 3 之后才能量）：残差 = |CTC首字时刻 − 校正后行起点|。")
    print("  CTC 用的是声学模型 + 字序列，与本层的 stem 能量是不同信息源，非循环。")
    print("  代价：阶段 2 与阶段 3 的门槛耦合，不能独立判定。")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    song_id = args[0] if args else "chaosheng"
    cfg = config.load()
    song = cfg.song(song_id)
    song.require("vocals", "no_vocals", "lyrics")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(cfg, song)
    text = buf.getvalue()
    print(text, end="")
    if "--no-save" not in sys.argv:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / f"line_offset_{song_id}_{datetime.now():%Y%m%d_%H%M}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"\n报告已存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
