"""跨估计器音高证据层。

核心规则（本项目的方法论地基，见 HANDOFF §5.4）：
**建音符用的估计器不能同时当裁判。** 所以这里不产出「某个估计器的 f0」，
而产出「哪些帧有多个独立估计器互相确认的音高」以及「哪些帧没有」。
没有证据的帧进缺口清单，不猜。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pitch.base import PitchTrack


def cents_diff(a: PitchTrack, b: PitchTrack) -> np.ndarray:
    """逐帧音分差，任一无声则 NaN。"""
    ca, cb = a.cents, b.cents
    d = ca - cb
    d[~(np.isfinite(ca) & np.isfinite(cb))] = np.nan
    return d


@dataclass
class PairStats:
    a: str
    b: str
    n_frames: int
    voiced_a: int
    voiced_b: int
    both_voiced: int
    agree: int              # |Δ| ≤ tol
    octave: int             # |Δ| 落在 ±1200 的 tol 邻域
    other: int
    median_abs_cents: float
    p90_abs_cents: float

    @property
    def agree_rate(self) -> float:
        return self.agree / self.both_voiced if self.both_voiced else float("nan")

    @property
    def octave_rate(self) -> float:
        return self.octave / self.both_voiced if self.both_voiced else float("nan")

    @property
    def voiced_jaccard(self) -> float:
        u = self.voiced_a + self.voiced_b - self.both_voiced
        return self.both_voiced / u if u else float("nan")


def compare(a: PitchTrack, b: PitchTrack, tol_cents: float = 50.0) -> PairStats:
    d = cents_diff(a, b)
    both = np.isfinite(d)
    ad = np.abs(d[both])
    oct_hit = np.abs(ad - 1200.0) <= tol_cents
    agree = ad <= tol_cents
    return PairStats(
        a=a.name, b=b.name, n_frames=a.f0_hz.size,
        voiced_a=int(a.voiced.sum()), voiced_b=int(b.voiced.sum()),
        both_voiced=int(both.sum()), agree=int(agree.sum()), octave=int(oct_hit.sum()),
        other=int((~agree & ~oct_hit).sum()),
        median_abs_cents=float(np.median(ad)) if ad.size else float("nan"),
        p90_abs_cents=float(np.percentile(ad, 90)) if ad.size else float("nan"),
    )


@dataclass
class EvidenceMap:
    """逐帧的音高证据。

    `f0_hz`：只在有证据的帧上有值（取互相确认的估计器的中位），其余 NaM。
    `n_agree`：该帧有多少个估计器落在共识簇里。
    """
    hop_s: float
    f0_hz: np.ndarray
    n_agree: np.ndarray
    spread_cents: np.ndarray
    sources: list[str] = field(default_factory=list)
    tol_cents: float = 50.0

    @property
    def has_evidence(self) -> np.ndarray:
        return np.isfinite(self.f0_hz)

    def coverage(self) -> float:
        return float(self.has_evidence.mean())

    def gaps(self, min_len_s: float = 0.20) -> list[tuple[float, float]]:
        """连续无证据区间，长度 ≥ min_len_s。"""
        ok = self.has_evidence
        out: list[tuple[float, float]] = []
        i = 0
        n = ok.size
        while i < n:
            if ok[i]:
                i += 1
                continue
            j = i
            while j < n and not ok[j]:
                j += 1
            if (j - i) * self.hop_s >= min_len_s:
                out.append((i * self.hop_s, j * self.hop_s))
            i = j
        return out


def build(tracks: list[PitchTrack], tol_cents: float = 50.0,
          min_agree: int = 2, veto_octave_contest: bool = False,
          octave_tol_cents: float = 150.0) -> EvidenceMap:
    """在每一帧上找最大共识簇。

    做法：把该帧所有有声估计器的 cents 排序，找一个宽度 ≤ 2*tol 的最大窗口。
    簇内 ≥ min_agree 个才算有证据，取簇内中位作为该帧音高。

    这样八度错会被自动排除：跟错八度的那个估计器落在簇外，不参与取中位，
    也不会把中位拖到两者之间那个物理上不存在的值。

    `veto_octave_contest=True` 时再加一条：**若簇外还有估计器给出的值恰好差
    约一个八度，本帧判为"有争议"，不算证据。**

    为什么需要这条：min_agree=2 的漏洞是两个估计器一起犯同一个八度错。
    《潮声回响》上实测，praat-ac 在 crepe∩rmvpe 一致的帧里有 64.0% 恰好低一个八度；
    而"只有 crepe+praat 确认"的帧里，rmvpe 有值时 79% 与之相差整一个八度。
    那批就是假确认。宁可算作缺口交给耳朵，也不要写一个自信的错音高。
    """
    n = tracks[0].f0_hz.size
    for t in tracks:
        if t.f0_hz.size != n:
            raise ValueError(f"轨迹长度不一致: {t.name} {t.f0_hz.size} vs {n}")
    C = np.vstack([t.cents for t in tracks])            # (E, N)
    F = np.vstack([t.f0_hz for t in tracks])
    f0 = np.full(n, np.nan)
    n_ag = np.zeros(n, dtype=np.int16)
    spread = np.full(n, np.nan)
    width = 2.0 * tol_cents

    for i in range(n):
        col = C[:, i]
        ok = np.isfinite(col)
        if ok.sum() < min_agree:
            continue
        vals = np.sort(col[ok])
        best_lo = best_hi = -1
        best_k = 0
        for lo in range(vals.size):
            hi = np.searchsorted(vals, vals[lo] + width, side="right") - 1
            if hi - lo + 1 > best_k:
                best_k, best_lo, best_hi = hi - lo + 1, lo, hi
        if best_k < min_agree:
            continue
        cluster = vals[best_lo:best_hi + 1]
        centre = float(np.median(cluster))
        sel = ok & (np.abs(col - centre) <= tol_cents)
        if sel.sum() < min_agree:
            continue
        if veto_octave_contest:
            out = ok & ~sel
            if out.any():
                d = np.abs(col[out] - centre)
                if np.any(np.abs(d - 1200.0) <= octave_tol_cents):
                    continue      # 有八度争议，判为缺口
        f0[i] = float(np.median(F[sel, i]))
        n_ag[i] = int(sel.sum())
        spread[i] = float(cluster.max() - cluster.min())

    return EvidenceMap(tracks[0].hop_s, f0, n_ag, spread,
                       [t.name for t in tracks], tol_cents)
