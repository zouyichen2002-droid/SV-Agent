"""基础调教：往 `.svp` 的 `parameters` 与 `vocalModes` 里写自动化点。

## 为什么直接写文件，不走桥

和写音符同一个理由：**文件进、文件出、可校验、可复现**。
桥需要 SynthV 开着、需要 writeIntent 守卫、断了就做不了（实测断过）。
而调教参数在 `.svp` 里就是两个字典，写进去即可。

## 格式（2026-08-23 从创作者自己调过的《世末歌者》实测）

    parameters.<名>  = {"mode": "cosine"|"cubic", "points": [pos, val, pos, val, ...]}
    vocalModes.<名>  = 同上

**points 是扁平列表**，不是 [(pos, val)] 的元组列表。位置单位是 blicks。

实测到的真实用法与值域（星尘，576 音符的一首歌）：

| 参数 | mode | 点数 | 值域 | 单位 |
|---|---|---|---|---|
| `loudness` | cosine | 179 | −1.98 ~ +2.91 | dB |
| `tension` | cubic | 99 | −0.29 ~ +0.34 | 归一化 |
| `toneShift` | cubic | 8 | 0 ~ 182 | 音分 |
| `vocalModes.Power` | cubic | 25 | 0 ~ 141 | 0–100 名义 |
| `vocalModes.Solid/Bright/Emotional/Sweet` | cubic | 6–9 | −40 ~ +89 | 同上 |

值域**不被 0–100 夹住**（实测有 141 和负值），但本模块保守取更小的范围 ——
基础调教的目标是「不机械」，不是「做满」，剩下的留给创作者精调。

## 四件事，按可听度排序

1. **pitchDelta 的滑入与收尾**（转音）—— 最能去掉机械感的一项。
   句首往上滑进（scoop），句末长音微微下沉（fall）。
2. **loudness 的段落起伏 + 句内塑形** —— 主歌收、副歌放；
   句末长音本身要有衰减，否则会像一堵墙。
3. **tension 跟随情绪弧线** —— 与 loudness 同向但幅度更小。
4. **vocalModes 的段落切换** —— Emotional / Power 在副歌抬起来。

**不碰的**：Breathiness、Voicing、音素时长/位置。
那几项一动就容易出怪声，且属于精调而不是基础调教。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .checks import Note

QUARTER_BLICKS = 705600000

# 星尘实际支持的唱法维度（取自创作者《世末歌者》里真实用过的那几个）
VOCAL_MODES = ("Power", "Solid", "Bright", "Emotional", "Sweet")


@dataclass
class TuneCfg:
    """基础调教的强度。**全部偏保守** —— 目标是不机械，不是做满。"""

    # --- pitchDelta（音分）---
    scoop_cents: float = -28.0       # 句首滑入：从低多少开始
    scoop_ms: float = 90.0           # 滑上来用多久
    fall_cents: float = -22.0        # 句末长音收尾下沉
    fall_ms: float = 260.0           # 收尾时长
    long_note_beats: float = 1.2     # 多长算「长音」，够长才做收尾

    # --- loudness（dB）---
    sec_loudness: dict = field(default_factory=lambda: {
        "主歌": -1.4, "预副": 0.0, "副歌": 1.3, "间奏": 0.0,
        "前奏": 0.0, "尾奏": -1.0})
    chorus2_bonus: float = 0.8       # 第二段副歌再抬一点（递进）
    line_swell_db: float = 0.5       # 句内往末字推进
    tail_decay_db: float = -1.1      # 末字长音自身的衰减

    # --- tension（归一化）---
    sec_tension: dict = field(default_factory=lambda: {
        "主歌": -0.16, "预副": 0.02, "副歌": 0.24, "间奏": 0.0,
        "前奏": 0.0, "尾奏": -0.12})
    tail_relax: float = -0.10        # 句末松一点，配合气口

    # --- vocalModes（0–100 名义）---
    modes: dict = field(default_factory=lambda: {
        # 段名 → {维度: 值}
        "主歌": {"Emotional": 6, "Power": 0, "Solid": 22,
                 "Bright": 8, "Sweet": 10},
        "预副": {"Emotional": 24, "Power": 12, "Solid": 24,
                 "Bright": 16, "Sweet": 8},
        "副歌": {"Emotional": 44, "Power": 26, "Solid": 28,
                 "Bright": 28, "Sweet": 6},
    })
    chorus2_mode_bonus: float = 1.28  # 第二段副歌整体乘这个系数


def _b(beats: float) -> int:
    return int(round(beats * QUARTER_BLICKS))


def _sec_stem(name: str) -> str:
    return name.rstrip("0123456789")


def _flat(pairs: list[tuple[int, float]]) -> list:
    """[(pos, val)] → 扁平列表，并按位置排序去重。"""
    out: list = []
    seen = set()
    for pos, val in sorted(pairs):
        if pos in seen:
            continue
        seen.add(pos)
        out.append(int(pos))
        out.append(round(float(val), 6))
    return out


def _lines_of(sections):
    """SECTIONS → [(段名, 是否第二段, [该句的音符下标区间])]，按顺序。"""
    out, idx = [], 0
    for sec_name, _bar0, lines in sections:
        second = sec_name.rstrip("　 ").endswith("2")
        for _text, syls, _chord in lines:
            n = len(syls)
            out.append((sec_name, second, idx, idx + n))
            idx += n
    return out


def build_tuning(notes: list[Note], sections, bpm: float,
                 cfg: TuneCfg | None = None) -> tuple[dict, dict, dict]:
    """→ (parameters 补丁, vocalModes 补丁, 统计)。

    只返回要写的那几个键，其余保持模板里的空值。
    """
    cfg = cfg or TuneCfg()
    spb = 60.0 / bpm
    lines = _lines_of(sections)

    pitch: list[tuple[int, float]] = []
    loud: list[tuple[int, float]] = []
    tens: list[tuple[int, float]] = []
    mode_pts: dict[str, list[tuple[int, float]]] = {m: [] for m in VOCAL_MODES}
    n_scoop = n_fall = 0

    for sec_name, second, i0, i1 in lines:
        stem = _sec_stem(sec_name)
        seg = [n for n in notes[i0:i1]]
        if not seg:
            continue
        base_l = cfg.sec_loudness.get(stem, 0.0)
        base_t = cfg.sec_tension.get(stem, 0.0)
        if second and stem == "副歌":
            base_l += cfg.chorus2_bonus

        # --- pitchDelta：句首滑入 ---
        first = seg[0]
        t0 = first.onset_beats * spb
        dt = cfg.scoop_ms / 1000.0
        pitch.append((_b((t0 - 0.02) / spb), 0.0))
        pitch.append((_b(t0 / spb), cfg.scoop_cents))
        pitch.append((_b((t0 + dt) / spb), 0.0))
        n_scoop += 1

        # --- pitchDelta：句末长音收尾下沉 ---
        last = seg[-1]
        if last.duration_beats >= cfg.long_note_beats:
            te = (last.onset_beats + last.duration_beats) * spb
            df = cfg.fall_ms / 1000.0
            pitch.append((_b((te - df) / spb), 0.0))
            pitch.append((_b(te / spb), cfg.fall_cents))
            pitch.append((_b((te + 0.05) / spb), 0.0))
            n_fall += 1

        # --- loudness / tension：句内塑形 ---
        for k, n in enumerate(seg):
            frac = k / max(1, len(seg) - 1)
            at = _b(n.onset_beats)
            loud.append((at, base_l + cfg.line_swell_db * frac))
            tens.append((at, base_t))
        # 末字长音自身的衰减与放松
        if last.duration_beats >= cfg.long_note_beats:
            end = _b(last.onset_beats + last.duration_beats * 0.92)
            loud.append((end, base_l + cfg.line_swell_db + cfg.tail_decay_db))
            tens.append((end, base_t + cfg.tail_relax))

        # --- vocalModes：每句一个点，段落切换处自然过渡 ---
        mv = cfg.modes.get(stem)
        if mv:
            mul = cfg.chorus2_mode_bonus if (second and stem == "副歌") else 1.0
            at = _b(first.onset_beats)
            for m in VOCAL_MODES:
                mode_pts[m].append((at, round(mv.get(m, 0) * mul, 2)))

    params = {
        "pitchDelta": {"mode": "cubic", "points": _flat(pitch)},
        "loudness": {"mode": "cosine", "points": _flat(loud)},
        "tension": {"mode": "cubic", "points": _flat(tens)},
    }
    vmodes = {m: {"mode": "cubic", "points": _flat(pts)}
              for m, pts in mode_pts.items() if pts}
    stats = {
        "pitchDelta 点": len(pitch), "滑入": n_scoop, "收尾": n_fall,
        "loudness 点": len(loud), "tension 点": len(tens),
        "vocalModes": {m: len(v) for m, v in mode_pts.items() if v},
    }
    return params, vmodes, stats


def describe(params: dict, vmodes: dict) -> str:
    rows = []
    for k, v in params.items():
        pts = v["points"]
        vals = pts[1::2]
        if not vals:
            continue
        unit = {"pitchDelta": "音分", "loudness": "dB"}.get(k, "")
        rows.append(f"  {k:12} {v['mode']:7} {len(vals):4d} 点"
                    f"　{min(vals):+.2f} ~ {max(vals):+.2f} {unit}")
    for k, v in vmodes.items():
        vals = v["points"][1::2]
        if not vals:
            continue
        rows.append(f"  VM.{k:9} {v['mode']:7} {len(vals):4d} 点"
                    f"　{min(vals):+.2f} ~ {max(vals):+.2f}")
    return "\n".join(rows)
