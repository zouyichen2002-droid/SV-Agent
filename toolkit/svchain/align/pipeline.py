"""按配置装配各阶段的状态。

**存在的理由是防一类具体的 bug**：eval 脚本和可听对照脚本各自拼装了一遍阶段 2，
其中一个漏传了 `max_shift_s`，于是同一份素材算出两个不同的速率（0.340 vs 0.360）
和两个不同的全局偏移（+0.070 vs +0.020），两边都不报错。

凡是「多个入口需要同一个中间状态」的地方，都从这里取，不要在调用侧重新拼。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import evidence, lyrics
from ..audio import cached_track, load_mono
from ..config import Config, Song
from ..evidence import EvidenceMap
from ..lyrics import LyricLine
from ..pitch import (CrepeEstimator, PraatEstimator, RmvpeEstimator,
                     PitchTrack, n_frames_for)
from .activity import ActivityMask, from_stems
from .line_offset import LineOffset, estimate_offsets, estimate_rate


@dataclass
class Stage1:
    tracks: list[PitchTrack]      # 已按配置门控
    evidence: EvidenceMap
    n_frames: int
    duration_s: float
    vocals16: np.ndarray
    no_vocals16: np.ndarray


@dataclass
class Stage2:
    activity: ActivityMask
    lines: list[LyricLine]
    offsets: list[LineOffset]
    rate_s_per_char: float
    global_delta_s: float

    @property
    def main_offsets(self) -> list[LineOffset]:
        return [o for o in self.offsets if not o.line.is_harmony]


def stage1(cfg: Config, song: Song, force: bool = False) -> Stage1:
    P = cfg.pitch
    v = load_mono(song.vocals, P.sr)
    nv = load_mono(song.no_vocals, P.sr)
    n = min(v.size, nv.size)
    nf = n_frames_for(n, P.sr, P.hop_s)
    tracks = []
    for e in (CrepeEstimator(model="full"), PraatEstimator(),
              RmvpeEstimator(cfg.model("rmvpe"))):
        tr, _ = cached_track(cfg.cache_dir, Path(song.vocals), e, P.sr, P.hop_s,
                            nf, P.fmin_hz, P.fmax_hz, force=force)
        tracks.append(tr.gated(P.conf_gate))
    em = evidence.build(tracks, P.agree_cents, min_agree=P.min_agree,
                        required=P.required)
    return Stage1(tracks, em, nf, n / P.sr, v, nv)


def stage2(cfg: Config, song: Song, s1: Stage1 | None = None) -> Stage2:
    P, A = cfg.pitch, cfg.align
    if s1 is None:
        v = load_mono(song.vocals, P.sr)
        nv = load_mono(song.no_vocals, P.sr)
        nf = n_frames_for(min(v.size, nv.size), P.sr, P.hop_s)
    else:
        v, nv, nf = s1.vocals16, s1.no_vocals16, s1.n_frames
    act = from_stems(v, nv, P.hop_len, P.hop_s, nf,
                     rms_db_min=A.act_rms_db_min, ratio_db_min=A.act_ratio_db_min,
                     close_s=A.act_close_s, open_s=A.act_open_s)
    lines = lyrics.parse(song.lyrics, song.lyrics_skip_before_s)
    rate, _ = estimate_rate(lines, act, max_shift_s=A.max_shift_s,
                            margin_s=A.margin_s)
    offs, rate, gd = estimate_offsets(
        lines, act, rate=rate, max_shift_s=A.max_shift_s, margin_s=A.margin_s,
        prior_w=A.prior_w, decisive_plateau_s=A.decisive_plateau_s)
    return Stage2(act, lines, offs, rate, gd)
