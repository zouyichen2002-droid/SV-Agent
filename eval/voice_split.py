# -*- coding: utf-8 -*-
"""评估「主唱 / 和声」分离的质量，并测出这首歌到底有多少时间真有第二个声部。

## 三条互不依赖的判据

**判据 1 · 两个不同架构的分离器是否一致。**
mel-band RoFormer（Transformer）与 UVR_MDXNET_KARA_2（ONNX 卷积）各自出
主唱/和声 stem，在每条 stem 上跑已标定的 RMVPE + CREPE。
两个分离器给出的主唱 f0 若一致，说明「主唱是哪个声部」这件事不是某个模型的臆造。

**判据 2 · 回代检验（关键）。**
把分离出的和声 f0 拿回**原始混合 stem** 的 RMVPE 显著图上查：
那个音高位置在混合信号里是否真有一个局部峰？

  - 有 → 混合信号里本来就存在这个音高，分离器只是把它拎出来
  - 无 → **这个声部是分离器造出来的**，混合信号里没有

这条的裁判是混合信号本身，**不依赖任何分离器的判决**，
所以它能抓到「分离器幻觉」这类最危险的失败。

**判据 3 · 和声相对主唱的音程分布。**
若集中在三度/六度，是典型的和声写法；若几乎全是八度，
那"和声"可能只是主唱的泛音残留被分到了另一条 stem。

用法: python eval/voice_split.py [song_id] [--no-save]
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

from svchain import config, evidence
from svchain.align import from_stems
from svchain.audio import cached_track, load_mono
from svchain.pitch import CrepeEstimator, RmvpeEstimator, n_frames_for
from svchain.pitch.base import hz_to_cents, hz_to_midi
from svchain.pitch.rmvpe_est import CENTS_BASE, CENTS_PER_BIN

SEP_ROOT = Path(__file__).resolve().parents[1] / "out" / "sep"
INTERVALS = [(0, "同音"), (1, "小二"), (2, "大二"), (3, "小三"), (4, "大三"),
             (5, "纯四"), (6, "增四"), (7, "纯五"), (8, "小六"), (9, "大六"),
             (10, "小七"), (11, "大七"), (12, "八度")]


def find_stems(song_id: str) -> dict[str, dict[str, Path]]:
    """{模型标签: {'lead': path, 'backing': path}}。

    karaoke 模型的 (Vocals) = 主唱，(Instrumental) = 和声/伴唱。
    """
    out: dict[str, dict[str, Path]] = {}
    root = SEP_ROOT / song_id
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        got: dict[str, Path] = {}
        for f in d.glob("*.wav"):
            n = f.name.lower()
            # 输出名形如 vocals_(Instrumental)_<model>.wav —— 里面**也含 "vocals"**。
            # 按带括号的标记匹配，且先判 instrumental，否则两个文件都会命中 lead。
            if "(instrumental)" in n:
                got["backing"] = f
            elif "(vocals)" in n:
                got["lead"] = f
        if len(got) == 2:
            out[d.name] = got
    return out


def track_for(cfg, path: Path, nf: int, force=False):
    """一条 stem 上的 RMVPE + CREPE，按配置门控。"""
    P = cfg.pitch
    trs = []
    for e in (RmvpeEstimator(cfg.model("rmvpe")), CrepeEstimator(model="full")):
        tr, _ = cached_track(cfg.cache_dir, path, e, P.sr, P.hop_s, nf,
                            P.fmin_hz, P.fmax_hz, force=force)
        trs.append(tr.gated(P.conf_gate))
    return trs, evidence.build(trs, P.agree_cents, min_agree=2)


def agree_rate(a: np.ndarray, b: np.ndarray, tol: float) -> tuple[float, int]:
    ca, cb = hz_to_cents(a), hz_to_cents(b)
    both = np.isfinite(ca) & np.isfinite(cb)
    if not both.any():
        return float("nan"), 0
    d = np.abs(ca[both] - cb[both])
    return float((d <= tol).mean()), int(both.sum())


def peak_support(sal: np.ndarray, f0: np.ndarray, tol_bins: int = 3,
                 abs_thr: float = 0.06) -> tuple[float, int]:
    """回代检验：f0 在混合信号显著图上有没有局部峰支持。"""
    c = hz_to_cents(f0)
    ok = np.isfinite(c)
    if not ok.any():
        return float("nan"), 0
    # 先填掉 NaN 再取整：NaN→int 是未定义行为，会得到极大/负的下标。
    # 这些位置后面被 ok 掩码挡掉了，但不能靠"反正用不到"来写。
    b = np.round(np.where(ok, (c - CENTS_BASE) / CENTS_PER_BIN, 0.0)).astype(int)
    n = min(sal.shape[0], f0.size)
    hit = 0
    tot = 0
    for i in range(n):
        if not ok[i]:
            continue
        lo = max(0, b[i] - tol_bins)
        hi = min(sal.shape[1], b[i] + tol_bins + 1)
        if hi <= lo:
            continue
        tot += 1
        w = sal[i, lo:hi]
        if w.size and w.max() >= abs_thr:
            # 还要求它是局部峰，不是某个大峰的裙边
            j = lo + int(np.argmax(w))
            l = sal[i, j - 1] if j > 0 else 0.0
            r = sal[i, j + 1] if j + 1 < sal.shape[1] else 0.0
            if sal[i, j] >= l and sal[i, j] >= r:
                hit += 1
    return (hit / tot if tot else float("nan")), tot


def multipeak_rate(est: RmvpeEstimator, path: Path, sr: int, sung: np.ndarray,
                   abs_thr: float = 0.10, rel_thr: float = 0.25,
                   min_sep_bins: int = 5) -> tuple[float, float]:
    """这条 stem 自己还剩多少复音？返回 (≥2 峰占演唱帧比例, 峰数均值)。

    用途：用户要的是「1 条主旋律 + **多个**和声轨」。karaoke 模型只给
    主唱/和声两条，若和声 stem 自己仍是多声部（三声和声很常见），
    单声部 f0 照样不够，需要再拆或上多音高。

    注意 RMVPE 在单声部上训练，这个比例是**被压低的下界**（见 ADR-0005）。
    它的用法是**比较**：和声 stem 的多峰率若显著高于主唱 stem，就说明还没拆干净。
    """
    y = load_mono(path, sr)
    sal = est._salience(est._mel(y, sr))
    n = min(sal.shape[0], sung.size)
    sal, m = sal[:n], sung[:n]
    idx, _ = find_peaks_simple(sal, abs_thr, rel_thr, min_sep_bins)
    npk = (idx >= 0).sum(axis=1)
    if not m.any():
        return float("nan"), float("nan")
    return float((npk[m] >= 2).mean()), float(npk[m].mean())


def find_peaks_simple(sal: np.ndarray, abs_thr: float, rel_thr: float,
                      min_sep: int, max_peaks: int = 4):
    n_f = sal.shape[0]
    out = np.full((n_f, max_peaks), -1, dtype=np.int16)
    left, mid, right = sal[:, :-2], sal[:, 1:-1], sal[:, 2:]
    is_pk = (mid >= left) & (mid > right) & (mid >= abs_thr)
    for i in range(n_f):
        cand = np.flatnonzero(is_pk[i]) + 1
        if cand.size == 0:
            continue
        v = sal[i, cand]
        keep = v >= max(abs_thr, rel_thr * float(v.max()))
        cand, v = cand[keep], v[keep]
        picked: list[int] = []
        for k in np.argsort(v)[::-1]:
            b = int(cand[k])
            if all(abs(b - p) >= min_sep for p in picked):
                picked.append(b)
            if len(picked) == max_peaks:
                break
        for j, b in enumerate(picked):
            out[i, j] = b
    return out, None


def report(cfg, song) -> None:
    P = cfg.pitch
    stems = find_stems(song.id)
    if not stems:
        print(f"没找到分离结果。先跑 scripts/separate_voices.py")
        print(f"（期望目录 {SEP_ROOT / song.id}/<模型标签>/*.wav）")
        return
    v = load_mono(song.vocals, P.sr)
    nv = load_mono(song.no_vocals, P.sr)
    nf = n_frames_for(min(v.size, nv.size), P.sr, P.hop_s)
    act = from_stems(v, nv, P.hop_len, P.hop_s, nf,
                     rms_db_min=cfg.align.act_rms_db_min,
                     ratio_db_min=cfg.align.act_ratio_db_min,
                     close_s=cfg.align.act_close_s, open_s=cfg.align.act_open_s)
    sung = act.mask[:nf]
    print(f"曲目 {song.title}   {nf} 帧   演唱活动 {100*sung.mean():.1f}%")
    print(f"跑于 {datetime.now():%Y-%m-%d %H:%M}")
    print(f"分离模型 {len(stems)} 个: {list(stems)}\n")

    # 原始混合 stem 的显著图，用作回代检验的裁判
    est = RmvpeEstimator(cfg.model("rmvpe"))
    est._load()
    sal_mix = est._salience(est._mel(v, P.sr))

    res: dict[str, dict] = {}
    for tag, paths in stems.items():
        print(f"=== {tag} ===")
        for role in ("lead", "backing"):
            trs, em = track_for(cfg, paths[role], nf)
            y = load_mono(paths[role], P.sr)
            e_db = 10 * np.log10((y[:min(y.size, nf * P.hop_len)] ** 2).mean() + 1e-12)
            res.setdefault(tag, {})[role] = (trs, em)
            cov_sung = em.has_evidence[:nf][sung].mean() if sung.any() else float("nan")
            print(f"  {role:8s} 整体电平 {e_db:6.1f}dB  "
                  f"两估计器一致覆盖 {100*em.coverage():5.1f}%  "
                  f"演唱帧内 {100*cov_sung:5.1f}%")
        print("  各 stem 自身残余复音（RMVPE 多峰率，是被压低的下界，只作比较用）:")
        base_r, base_n = multipeak_rate(est, Path(song.vocals), P.sr, sung)
        print(f"    {'原始混合':8s} ≥2峰 {100*base_r:5.1f}%   峰数均值 {base_n:.2f}")
        for role in ("lead", "backing"):
            r, nm = multipeak_rate(est, paths[role], P.sr, sung)
            flag = ""
            if r > base_r * 0.8:
                flag = "   ← 与原始混合接近，这条 stem 没怎么拆干净"
            print(f"    {role:8s} ≥2峰 {100*r:5.1f}%   峰数均值 {nm:.2f}{flag}")
        print("    和声 stem 的多峰率若明显高于主唱，说明它自己还是多声部，"
              "要「多个和声轨」还得再拆")

        lead_em = res[tag]["lead"][1]
        back_em = res[tag]["backing"][1]
        both = lead_em.has_evidence[:nf] & back_em.has_evidence[:nf] & sung
        print(f"  两条 stem 同时有音高的演唱帧: {int(both.sum())} = "
              f"{100*both.sum()/max(1,sung.sum()):.1f}% 的演唱帧")
        print("  → 这是「真有第二个声部」的分离器侧估计（还要过回代检验）")

        print("  回代检验（f0 在原始混合信号显著图上是否有局部峰支持）:")
        for role in ("lead", "backing"):
            em = res[tag][role][1]
            f0 = em.f0_hz.copy()
            f0[~sung[:f0.size]] = np.nan
            r, tot = peak_support(sal_mix, f0)
            print(f"    {role:8s} {100*r:5.1f}%  ({tot} 帧参与)"
                  + ("" if r > 0.8 else "   ← 支持率偏低，可能有分离器幻觉"))

        if both.any():
            dl = hz_to_midi(back_em.f0_hz[:nf][both]) - hz_to_midi(lead_em.f0_hz[:nf][both])
            print("  和声相对主唱的音程分布:")
            rows = []
            for semi, nm in INTERVALS:
                for sgn in ((+1,) if semi == 0 else (+1, -1)):
                    k = int((np.abs(dl - sgn * semi) <= 0.5).sum())
                    if k:
                        rows.append((k, f"{'+' if sgn > 0 else '-'}{nm}"))
            for k, nm in sorted(rows, reverse=True)[:8]:
                print(f"    {nm:>6} {k:6d} 帧 {100*k/len(dl):5.1f}%")
            above = float((dl > 0.5).mean())
            print(f"    和声在主唱**上方** {100*above:.1f}%  "
                  f"下方 {100*float((dl < -0.5).mean()):.1f}%  "
                  f"同音 {100*float((np.abs(dl) <= 0.5).mean()):.1f}%")
        print()

    if len(res) >= 2:
        tags = list(res)
        print("=== 判据 1 · 两个分离器是否一致 ===")
        for role in ("lead", "backing"):
            a = res[tags[0]][role][1].f0_hz
            b = res[tags[1]][role][1].f0_hz
            n = min(a.size, b.size, nf)
            m = sung[:n]
            r, tot = agree_rate(np.where(m, a[:n], np.nan),
                                np.where(m, b[:n], np.nan), P.agree_cents)
            print(f"  {role:8s} {tags[0]} vs {tags[1]}: 一致 {100*r:5.1f}%"
                  f"  (共同有值 {tot} 帧)")
        print("  主唱一致率高 = 「主唱是哪个声部」不是某个模型的臆造")
        print("  和声一致率低 = 和声的划分不稳，下游要按最保守的那个来")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    cfg = config.load()
    song = cfg.song(args[0] if args else "chaosheng")
    song.require("vocals", "no_vocals")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(cfg, song)
    text = buf.getvalue()
    print(text, end="")
    if "--no-save" not in sys.argv:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / f"voice_split_{song.id}_{datetime.now():%Y%m%d_%H%M}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"\n报告已存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
