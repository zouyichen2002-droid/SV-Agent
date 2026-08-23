"""阶段 2 · 逐行独立估 LRC 偏移。

交接文件 §4.1 只做了**全局** offset（估出 ≈0，前四行残差 +0.34/+0.08/−0.28/+0.41s，
平均 239ms）。239ms 对字级对齐太粗：一个字常常只有 250–350ms，
半个字的偏移就足以让 CTC 的搜索窗口错位。所以要逐行。

## 目标函数：带边缘的匹配滤波，不是纯盒重叠

把每行按「字数 × 演唱速率」摊成时间盒，在 ±max_shift 内平移。
打分**不是**盒内活动占比 —— 那个在长活动段里必然是平顶（实测 δ 不确定度
中位就等于整个搜索范围）。改成

    score = 盒内活动占比 − w · (盒前边缘占比 + 盒后边缘占比) / 2

即奖励「盒内满、盒外空」的位置。这样只要该行前后有气口，δ 就有唯一峰。

## 无法确定的行要承认无法确定

紧接前一行、中间没有气口的行，**从活动信号里根本无法定位**，
目标函数在那里是平的。这类行不硬给一个数，退回全局偏移并标记 `decisive=False`，
把不确定度（等价最优解的宽度）显式带下去给阶段 3 加宽窗口。
这是「无证据不猜、显式上报不确定区间」在这一层的落法。

## 单调 DP

校正后的行起点必须保持原有先后且不相互穿越。没有这层，相邻两行会各自被
同一段响亮的活动吸过去，出现"两行叠在一处"。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..lyrics import LyricLine
from .activity import ActivityMask


@dataclass
class LineOffset:
    line: LyricLine
    delta_s: float
    box_len_s: float
    hit: float                 # 盒内活动占比 0..1
    score: float               # 匹配滤波得分
    plateau_s: float           # δ 的不确定度：等价最优解的连续宽度
    decisive: bool             # 活动信号是否足以定住这一行
    onset_residual_s: float    # 校正后行起点 与 最近声学起音 的距离
    onset_found: bool
    gap_before_s: float        # 按 LRC 自身行距算，本行起点前应有多少空白

    @property
    def judgeable(self) -> bool:
        """起音残差这个判据对本行是否有意义。

        **必须同时满足三件事**，缺一不可：

        1. `decisive` —— 活动信号能定住这一行
        2. `gap_before_s >= 0.30` —— 按 LRC 自身行距，本行起点前应该有气口。
           紧接前一行的行**起点处不存在起音**，此时 `nearest_onset` 会去抓
           ±0.5s 内前一段的起音，报出一个虚假的大残差。实测 L13 就是这样
           被误判成 370ms 的（它与前一行的间隔恰好是 0.00s）。
        3. `onset_found` —— 该处确实找到了起音
        """
        return self.decisive and self.onset_found and self.gap_before_s >= 0.30

    @property
    def corrected_t_s(self) -> float:
        return self.line.t_s + self.delta_s

    @property
    def window_s(self) -> tuple[float, float]:
        """给阶段 3 的搜索窗。不确定的行按不确定度左右各放宽。"""
        pad = 0.10 if self.decisive else max(0.25, self.plateau_s / 2)
        return (self.corrected_t_s - pad, self.corrected_t_s + self.box_len_s + pad)


def _box_len(lines: list[LyricLine], k: int, rate: float) -> float:
    L = lines[k].n_chars * rate
    if k + 1 < len(lines):
        L = min(L, max(0.20, lines[k + 1].t_s - lines[k].t_s))
    return L


def estimate_rate(lines: list[LyricLine], act: ActivityMask,
                  lo: float = 0.15, hi: float = 0.55, step: float = 0.01,
                  max_shift_s: float = 1.5, margin_s: float = 0.40,
                  margin_w: float = 1.0) -> tuple[float, float]:
    """全局演唱速率（秒/字）。与逐行偏移联合优化。

    **不能用「盒内活动占比」当目标** —— 盒越短占比越高，那个目标单调偏向最短盒，
    会一路压到扫描下界（实测：换成更稀疏的活动掩码后它从 0.340 掉到 0.290，
    且所有行的盒内命中都变成 1.000，说明盒短到随便放都全中）。

    改用匹配滤波得分：盒太短则边缘也落在活动内、被扣分；盒太长则盒内出现空洞。
    只有盒长≈真实演唱时长时得分最高。对每行取 δ 上的最优再按字数加权求和。
    """
    D = np.arange(-max_shift_s, max_shift_s + 1e-9, act.hop_s)
    best = (lo, -np.inf)
    for r in np.arange(lo, hi + 1e-9, step):
        tot = 0.0
        for k, ln in enumerate(lines):
            sc, _ = _score_row(act, ln.t_s, _box_len(lines, k, float(r)), D,
                               margin_s, margin_w)
            tot += float(sc.max()) * ln.n_chars
        if tot > best[1]:
            best = (float(r), tot)
    return best


def _score_row(act: ActivityMask, t0: float, box: float, D: np.ndarray,
               margin_s: float, margin_w: float) -> tuple[np.ndarray, np.ndarray]:
    """返回 (匹配滤波得分, 盒内占比)。"""
    sc = np.empty(D.size)
    hit = np.empty(D.size)
    for j, d in enumerate(D):
        a = t0 + d
        inside = act.fraction_in(a, a + box)
        left = act.fraction_in(a - margin_s, a)
        right = act.fraction_in(a + box, a + box + margin_s)
        hit[j] = inside
        sc[j] = inside - margin_w * 0.5 * (left + right)
    return sc, hit


def global_offset(lines: list[LyricLine], act: ActivityMask, rate: float,
                  max_shift_s: float = 1.5, margin_s: float = 0.40,
                  margin_w: float = 1.0) -> tuple[float, float]:
    """单一全局偏移基线，用来回答「逐行到底有没有必要」。"""
    D = np.arange(-max_shift_s, max_shift_s + 1e-9, act.hop_s)
    tot = np.zeros(D.size)
    for k, ln in enumerate(lines):
        sc, _ = _score_row(act, ln.t_s, _box_len(lines, k, rate), D,
                           margin_s, margin_w)
        tot += sc * ln.n_chars
    j = int(np.argmax(tot))
    return float(D[j]), float(tot[j])


def estimate_offsets(lines: list[LyricLine], act: ActivityMask, *,
                     rate: float | None = None,
                     max_shift_s: float = 0.60,
                     min_line_gap_s: float = 0.15,
                     margin_s: float = 0.40,
                     margin_w: float = 1.0,
                     smooth_w: float = 0.0,
                     prior_w: float = 0.10,
                     plateau_eps: float = 0.02,
                     decisive_plateau_s: float = 0.30,
                     onset_window_s: float = 0.50,
                     fallback_delta_s: float | None = None
                     ) -> tuple[list[LineOffset], float, float]:
    """返回 (逐行偏移, 采用的速率, 全局偏移基线)。"""
    if not lines:
        return [], 0.0, 0.0
    if rate is None:
        rate, _ = estimate_rate(lines, act)
    gd, _ = global_offset(lines, act, rate, max_shift_s, margin_s, margin_w)
    if fallback_delta_s is None:
        fallback_delta_s = gd

    hop = act.hop_s
    D = np.arange(-max_shift_s, max_shift_s + 1e-9, hop)
    n, n_d = len(lines), D.size
    box = np.array([_box_len(lines, k, rate) for k in range(n)])
    # 按 LRC 自身的行距算：本行名义起点 减 前一行名义盒尾
    gap_before = np.empty(n)
    gap_before[0] = np.inf
    for i in range(1, n):
        gap_before[i] = lines[i].t_s - (lines[i - 1].t_s + box[i - 1])
    score = np.empty((n, n_d))
    hits = np.empty((n, n_d))
    for i, ln in enumerate(lines):
        score[i], hits[i] = _score_row(act, ln.t_s, box[i], D, margin_s, margin_w)
    if prior_w:
        # 向全局偏移拉回。理由见模块 docstring 的「槽位歧义」。
        score = score - prior_w * np.abs(D - gd)[None, :]

    # ---- 单调 DP ----
    f = np.full((n, n_d), -np.inf)
    bp = np.zeros((n, n_d), dtype=np.int32)
    f[0] = score[0]
    for i in range(1, n):
        dt = lines[i].t_s - lines[i - 1].t_s
        # 约束 t_{i-1}+D[d'] <= t_i+D[d] - gap  →  D[d'] <= D[d] + dt - gap
        n_allowed = np.searchsorted(D, D + dt - min_line_gap_s, side="right")
        if smooth_w:
            jump = np.abs(D[:, None] - D[None, :])
            for j in range(n_d):
                k = int(n_allowed[j])
                if k <= 0:
                    continue
                cand = f[i - 1, :k] - smooth_w * jump[j, :k]
                b = int(np.argmax(cand))
                f[i, j] = score[i, j] + cand[b]
                bp[i, j] = b
        else:
            run_max = np.maximum.accumulate(f[i - 1])
            run_arg = np.empty(n_d, dtype=np.int32)
            best, bi = -np.inf, 0
            for j in range(n_d):
                if f[i - 1, j] > best:
                    best, bi = f[i - 1, j], j
                run_arg[j] = bi
            for j in range(n_d):
                k = int(n_allowed[j])
                if k <= 0:
                    continue
                f[i, j] = score[i, j] + run_max[k - 1]
                bp[i, j] = run_arg[k - 1]

    pick = np.zeros(n, dtype=np.int32)
    pick[-1] = int(np.argmax(f[-1]))
    for i in range(n - 1, 0, -1):
        pick[i - 1] = bp[i, pick[i]]

    out: list[LineOffset] = []
    for i, ln in enumerate(lines):
        j = int(pick[i])
        top = score[i].max()
        okv = score[i] >= top - plateau_eps
        lo = hi = j
        while lo > 0 and okv[lo - 1]:
            lo -= 1
        while hi + 1 < n_d and okv[hi + 1]:
            hi += 1
        plateau = float((hi - lo) * hop)
        decisive = plateau <= decisive_plateau_s
        d = float(D[j]) if decisive else float(fallback_delta_s)
        s_corr = ln.t_s + d
        onset, found = act.nearest_onset(s_corr, onset_window_s)
        out.append(LineOffset(ln, d, float(box[i]),
                              float(hits[i, j]), float(score[i, j]),
                              plateau, decisive, abs(onset - s_corr), found,
                              float(gap_before[i])))
    return out, float(rate), float(gd)
