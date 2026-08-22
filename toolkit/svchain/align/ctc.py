"""逐字 CTC 强制对齐（阶段 3）。

移植并整理上一会话已验证的原型（`prototypes/ctc_align.py`：33/33 行、300/315 字、
全曲 11 秒）。相对原型的三处改动：

1. **输入改成分离后的主唱 stem**。原型跑在混合 stem 上，那条信号里同时有主唱和
   对位和声，声学模型要在两条人声里挑一条。分离之后输入干净了。
2. 路径、模型、窗口参数全部走配置，不再硬编码。
3. 自实现的 Viterbi 保留（它在这份素材上被验证过），但增加与
   `torchaudio.functional.forced_align` 的交叉校验 —— 两个独立实现给出同一条路径，
   才排除"我把 DP 写错了"这一类静默错误。

## CTC 的尖峰性质（ADR-0001 已确证，这里不要重犯）

CTC 是尖峰式的：每个字只在一帧爆发。**尖峰给的是起音，不是时长。**
所以这里只输出每个字的帧跨度，时长由下游按"到下一字起音"决定。
两字尖峰相距 <85ms 一定是对齐误差，按行摊开保最小间距，**不要合并**
（原型那次用"合并"丢了 43 个字）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

NEG = -1e30


@dataclass
class CharSpan:
    """一个字的对齐结果。时刻是**绝对秒**。"""
    index: int          # 在该行内的字序号
    char: str = field(repr=False)
    t0: float = 0.0
    t1: float = 0.0
    logprob: float = 0.0   # 该字在其尖峰帧上的对数后验，作为置信度

    @property
    def dur(self) -> float:
        return self.t1 - self.t0


@dataclass
class LineAlign:
    line_index: int
    t_lrc: float
    window: tuple[float, float]
    n_chars: int
    spans: list[CharSpan]
    oov: list[str] = field(default_factory=list)

    @property
    def aligned(self) -> int:
        return len(self.spans)

    @property
    def rate(self) -> float:
        return self.aligned / self.n_chars if self.n_chars else 0.0


class CtcAligner:
    def __init__(self, model_dir: str | Path, sr: int = 16000, threads: int = 16):
        import torch
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC

        self.sr = sr
        d = Path(model_dir)
        torch.set_num_threads(threads)
        self.vocab: dict[str, int] = json.loads(
            (d / "vocab.json").read_text(encoding="utf-8"))
        self.blank = self.vocab["<pad>"]
        self.fe = Wav2Vec2FeatureExtractor.from_pretrained(str(d))
        self.model = Wav2Vec2ForCTC.from_pretrained(str(d))
        self.model.eval()
        self._torch = torch

    @property
    def info(self) -> str:
        return (f"vocab={len(self.vocab)} blank={self.blank} "
                f"do_normalize={self.fe.do_normalize} sr={self.sr}")

    def coverage(self, chars) -> tuple[int, int, list[str]]:
        """词表覆盖率。OOV 字无法对齐，必须显式上报而不是静默跳过。"""
        uniq = sorted(set(chars))
        oov = [c for c in uniq if c not in self.vocab]
        return len(uniq) - len(oov), len(uniq), oov

    # ---------- 声学 ----------
    def logprobs(self, seg: np.ndarray):
        t = self._torch
        iv = self.fe(seg, sampling_rate=self.sr, return_tensors="pt")
        with t.no_grad():
            lg = self.model(iv.input_values).logits[0]
        lp = t.log_softmax(lg, -1)
        frame_dur = (len(seg) / self.sr) / lg.shape[0]
        return lp.numpy(), frame_dur, lp

    # ---------- 对齐 ----------
    def _viterbi(self, lp: np.ndarray, ids: list[int]):
        """自实现的 CTC 强制对齐。返回每个 label 的 (起帧, 止帧)。"""
        T = lp.shape[0]
        S = 2 * len(ids) + 1
        ext = np.full(S, self.blank, int)
        for i, c in enumerate(ids):
            ext[2 * i + 1] = c
        dp = np.full((T, S), NEG)
        bt = np.zeros((T, S), np.int8)
        dp[0, 0] = lp[0, ext[0]]
        if S > 1:
            dp[0, 1] = lp[0, ext[1]]
        # 允许跳过 blank 的位置：非 blank 且与前前一个 label 不同
        okc = np.zeros(S, bool)
        for s in range(2, S):
            okc[s] = ext[s] != self.blank and ext[s] != ext[s - 2]
        for t in range(1, T):
            prev = dp[t - 1]
            a = prev
            b = np.concatenate(([NEG], prev[:-1]))
            c = np.where(okc, np.concatenate(([NEG, NEG], prev[:-2])), NEG)
            stack = np.vstack([a, b, c])
            arg = np.argmax(stack, 0)
            dp[t] = stack[arg, np.arange(S)] + lp[t, ext]
            bt[t] = arg
        s = S - 1 if dp[T - 1, S - 1] >= dp[T - 1, S - 2] else S - 2
        path = np.zeros(T, int)
        for t in range(T - 1, -1, -1):
            path[t] = s
            s -= bt[t, s]
        spans: dict[int, list[int]] = {}
        for t, s in enumerate(path):
            if ext[s] != self.blank:
                i = (s - 1) // 2
                spans.setdefault(i, [t, t])[1] = t
        return [tuple(spans[i]) if i in spans else None for i in range(len(ids))]

    def _torchaudio_align(self, lp_t, ids: list[int]):
        """torchaudio 的实现，只用于交叉校验自实现是否写错。"""
        import torchaudio.functional as F

        t = self._torch
        targets = t.tensor([ids], dtype=t.int32)
        al, _ = F.forced_align(lp_t.unsqueeze(0), targets, blank=self.blank)
        path = al[0].numpy()
        spans: dict[int, list[int]] = {}
        k = -1
        prev = -1
        for fr, tok in enumerate(path):
            if tok == self.blank:
                prev = tok
                continue
            if tok != prev:
                k += 1
            if 0 <= k < len(ids):
                spans.setdefault(k, [fr, fr])[1] = fr
            prev = tok
        return [tuple(spans[i]) if i in spans else None for i in range(len(ids))]

    def align_line(self, y: np.ndarray, chars, t_lrc: float,
                   win: tuple[float, float], line_index: int = 0,
                   cross_check: bool = False) -> tuple[LineAlign, dict | None]:
        lo, hi = win
        seg = y[int(lo * self.sr):int(hi * self.sr)]
        if seg.size < self.sr // 10:
            return LineAlign(line_index, t_lrc, win, len(chars), []), None
        lp, fd, lp_t = self.logprobs(seg)
        inv = [(k, c) for k, c in enumerate(chars) if c in self.vocab]
        oov = [c for c in chars if c not in self.vocab]
        if not inv:
            return LineAlign(line_index, t_lrc, win, len(chars), [], oov), None
        ids = [self.vocab[c] for _, c in inv]
        sp = self._viterbi(lp, ids)

        cc = None
        if cross_check:
            try:
                sp2 = self._torchaudio_align(lp_t, ids)
                d = [abs(a[0] - b[0]) for a, b in zip(sp, sp2)
                     if a is not None and b is not None]
                cc = {"n": len(d),
                      "same_start": int(sum(1 for x in d if x == 0)),
                      "max_frame_diff": int(max(d)) if d else 0,
                      "frame_ms": fd * 1000}
            except Exception as e:            # torchaudio 不可用不该阻塞主流程
                cc = {"error": f"{type(e).__name__}: {e}"[:120]}

        spans = []
        for (k, c), rng in zip(inv, sp):
            if rng is None:
                continue
            spans.append(CharSpan(k, c, lo + rng[0] * fd, lo + (rng[1] + 1) * fd,
                                  float(lp[rng[0], self.vocab[c]])))
        spans.sort(key=lambda s: s.t0)
        return LineAlign(line_index, t_lrc, win, len(chars), spans, oov), cc


def line_windows(times: list[float], all_times: list[float], dur_s: float,
                 pre_s: float = 1.0, post_s: float = 0.35,
                 max_span_s: float = 12.0) -> list[tuple[float, float]]:
    """每行的搜索窗：从本行起始前 pre_s，到**下一个演唱行**起始后 post_s。

    下一行要用「所有演唱行」而不是「同类行」—— 主唱行之后可能紧跟一个和声行，
    窗口开到再下一个主唱行会把和声整段吞进来。
    """
    out = []
    for t in times:
        nxt = min((x for x in all_times if x > t + 0.5), default=t + 7.0)
        lo = max(0.0, t - pre_s)
        hi = min(dur_s, min(nxt + post_s, t + max_span_s))
        out.append((lo, hi))
    return out


def respace(spans_by_line: list[list[CharSpan]], min_gap_s: float = 0.090,
            slack_s: float = 0.35) -> tuple[list[list[CharSpan]], dict]:
    """把挤在一起的字起音按行摊开，保证最小间距。**一个字都不丢。**

    为什么必须做：CTC 是尖峰式的，不确定时会把相邻几个字喷在几帧之内。
    《潮声回响》主唱 stem 实测，相邻字起音间距 <85ms 的占 16.9%，
    最密的地方四个字挤在 160ms 内（23.62 / 23.64 / 23.76 / 23.78s）——
    物理上不可能。不摊开的话这些字在分配到音符时会因"拆出的片段短于 85ms"
    被整批丢掉（实测分配率只有 65.3%）。

    交接文件 §6.1 记的教训：**摊开，不要合并**。上一次用"合并"处理丢了 43 个字。

    做法（沿用已验证的原型 `prototypes/respace.py`）：
      1. 逐行前向推，保证相邻间距 ≥ min_gap_s
      2. 若整行被推得太靠后，整体回移；回移量有界，不让首字比原位置早 slack_s 以上
      3. 跨行再保一次最小间距（行与行的边界也可能挤）

    `min_gap_s` 默认 **0.090 而不是 0.085**：下游按 10ms 帧栅格取整，
    `int(round(t / hop_s))` 会把 85ms 的间距算成 8 帧 = 80ms，
    于是音符在最终几何强制那一步因不足 85ms 被丢掉（实测丢了 21 个**带字**音符）。
    留一格余量（9 帧 = 90ms）让摊开的结果能活过取整。
    """
    out: list[list[CharSpan]] = []
    stat = {"pushed": 0, "max_push_s": 0.0, "shifted_lines": 0, "cross_line": 0}
    for spans in spans_by_line:
        g = sorted(spans, key=lambda s: s.t0)
        if not g:
            out.append([])
            continue
        t = [s.t0 for s in g]
        orig = list(t)
        for i in range(1, len(t)):
            if t[i] - t[i - 1] < min_gap_s:
                t[i] = t[i - 1] + min_gap_s
                stat["pushed"] += 1
        over = t[-1] - (orig[-1] + slack_s)
        if over > 0:
            shift = min(over, t[0] - (orig[0] - slack_s))
            if shift > 0:
                t = [x - shift for x in t]
                stat["shifted_lines"] += 1
        stat["max_push_s"] = max(stat["max_push_s"],
                                 max(abs(a - b) for a, b in zip(t, orig)))
        out.append([CharSpan(s.index, s.char, tt, max(tt + min_gap_s, s.t1),
                             s.logprob) for s, tt in zip(g, t)])

    flat = sorted((s for g in out for s in g), key=lambda s: s.t0)
    for i in range(1, len(flat)):
        if flat[i].t0 - flat[i - 1].t0 < min_gap_s:
            d = flat[i - 1].t0 + min_gap_s - flat[i].t0
            flat[i].t0 += d
            flat[i].t1 += d
            stat["cross_line"] += 1
    return out, stat
