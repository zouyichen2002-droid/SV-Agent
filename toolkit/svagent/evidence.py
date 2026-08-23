"""跨估计器音高证据层。

核心规则（本项目的方法论地基，见 HANDOFF §5.4）：
**建音符用的估计器不能同时当裁判。** 所以这里不产出「某个估计器的 f0」，
而产出「哪些帧有多个独立估计器互相确认的音高」以及「哪些帧没有」。
没有证据的帧进缺口清单，不猜。
"""
from __future__ import annotations

from collections.abc import Sequence
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

    `f0_hz`：只在有证据的帧上有值（取互相确认的估计器的中位），其余 NaN。
    `n_agree`：该帧有多少个估计器落在共识簇里。
    `by`：(n_frames, n_estimators) 的布尔表，记**是谁确认的**。
        保留来源而不是只保留一个布尔"有/无证据"，是因为阶段 4 建音符时
        不同来源的可信度不同（例如 praat-ac 在本素材上系统性低一个八度），
        下游要能按来源再筛一次，而不是回来重跑。
    """
    hop_s: float
    f0_hz: np.ndarray
    n_agree: np.ndarray
    spread_cents: np.ndarray
    sources: list[str] = field(default_factory=list)
    tol_cents: float = 50.0
    by: np.ndarray | None = None

    def confirmed_by(self, *names: str) -> np.ndarray:
        """这些估计器**全部**参与确认的帧。"""
        if self.by is None:
            raise ValueError("这张证据图没有记录来源")
        m = self.has_evidence.copy()
        for nm in names:
            if nm not in self.sources:
                raise ValueError(f"来源里没有 {nm!r}，有的是 {self.sources}")
            m &= self.by[:, self.sources.index(nm)]
        return m

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
          octave_tol_cents: float = 150.0,
          required: Sequence[str] | None = None) -> EvidenceMap:
    """在每一帧上找最大共识簇。

    做法：把该帧所有有声估计器的 cents 排序，找一个宽度 ≤ 2*tol 的最大窗口。
    簇内 ≥ min_agree 个才算有证据，取簇内中位作为该帧音高。

    这样八度错会被自动排除：跟错八度的那个估计器落在簇外，不参与取中位，
    也不会把中位拖到两者之间那个物理上不存在的值。

    `required` 里的估计器**必须**在共识簇内，否则本帧不算证据。
    《潮声回响》上的实测结论是 `required=["rmvpe"]`（ADR-0004）：
    风险精确集中在「只有 crepe+praat 联署」那 4.8% 的帧 —— 该批里 rmvpe 有值时
    79% 与之相差整一个八度。要求 rmvpe 参与，等于精准剔掉这一批，
    同时保留 praat 有用的部分（praat+rmvpe 一致的 4.2%）。

    `veto_octave_contest=True` 时再加一条：**若簇外还有估计器给出的值恰好差
    约一个八度，本帧判为"有争议"，不算证据。**
    实测这条是钝刀（覆盖 69.8%→53.1%，最差行掉到 6.9%）：praat-ac 在 crepe∩rmvpe
    一致的帧里有 64.0% 恰好低一个八度，所以它在大量否决本来正确的帧。
    留着这个开关是为了记录这条路走不通，默认关闭。
    """
    n = tracks[0].f0_hz.size
    names = [t.name for t in tracks]
    for t in tracks:
        if t.f0_hz.size != n:
            raise ValueError(f"轨迹长度不一致: {t.name} {t.f0_hz.size} vs {n}")
    req_idx: list[int] = []
    for nm in (required or ()):
        if nm not in names:
            raise ValueError(f"required 里的 {nm!r} 不在估计器列表 {names} 中")
        req_idx.append(names.index(nm))
    C = np.vstack([t.cents for t in tracks])            # (E, N)
    F = np.vstack([t.f0_hz for t in tracks])
    f0 = np.full(n, np.nan)
    n_ag = np.zeros(n, dtype=np.int16)
    spread = np.full(n, np.nan)
    by = np.zeros((n, len(tracks)), dtype=bool)
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
        if req_idx and not all(sel[k] for k in req_idx):
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
        by[i] = sel

    return EvidenceMap(tracks[0].hop_s, f0, n_ag, spread, names, tol_cents, by)
