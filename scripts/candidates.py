# -*- coding: utf-8 -*-
"""发散 → 过筛 → **挑差异最大的 N 个** → 摆给创作者剪枝。

## 相对上一版改了什么，以及为什么

上一版的做法是：每个歌词方向生成 16 个旋律变体，按代价取**最优的那一个**。
结果创作者的反馈是**「旋律和上一首非常像」**、
**「一次提供多一点方案，而且每个方案之间的差异必须比较大」**。

诊断：**这是选择策略的错，不是生成器的错。**
「取代价最低的那个」等于每次都选最安全、最靠近默认值的那个 ——
16 个变体里的多样性被选择环节全部丢掉了。

改法三处：

1. **池子放大**：4 个歌词方向 × N 份补全规格 × M 个种子
2. **选择改成 max-min 多样性**（最远点采样），不再取单一最优
3. **打出两两差异矩阵**，「差异大」这句话可核对，不是声称

## 池子的多样性来自哪里

规格补全（`spec.expand_many`）会主动避开已生成规格的调、节奏细胞、动机，
所以池子在**参数层**就是散开的，不是靠随机种子碰。

用法:
    python scripts/candidates.py                    # 6 个方案
    python scripts/candidates.py --pick 8 --specs 6 --seeds 3
    python scripts/candidates.py --no-audio         # 只看规格与矩阵，不渲染
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "songs" / "yequ"))
sys.stdout.reconfigure(encoding="utf-8")

import lyrics as L
from svagent.compose.checks import CheckCfg, note_name, run_all
from svagent.compose.melodize import melodize_spec
from svagent.compose.repair import Ctx, cost, repair
from svagent.compose.spec import expand_many, motif_name
from svagent.compose.uniqueness import (Fingerprint, distance, pairwise_table,
                                        select_diverse)

OUT = ROOT / "out" / "listen_yequ"


class Cand:
    """一个候选：歌词方向 + 规格 + 生成结果。"""

    def __init__(self, key, spec, seed, notes, phrases, text, sections, cfg):
        self.key, self.spec, self.seed = key, spec, seed
        self.notes, self.phrases, self.text = notes, phrases, text
        self.SECTIONS = sections
        self.BPM = spec.bpm
        self.N_BARS = len(notes) and max(
            int(n.onset_beats + n.duration_beats) // 4 + 1 for n in notes)
        self.KEY_ROOT, self.KEY_QUALITY = spec.key_root, spec.mode
        self.BARS_PER_LINE = spec.bars_per_line
        # 律动：伴奏生成器靠这四个属性区分每首歌的 groove
        self.PAD_STYLE = spec.pad_style
        self.ARP_FIGURE = spec.arp_figure
        self.BASS_GROOVE = spec.bass_groove
        self.DRUM_PICK = spec.drum_pick
        self.ctx = Ctx(text=text, key_root=spec.key_root, quality=spec.mode,
                       phrases=phrases, cfg=cfg)
        self.findings = self.ctx.check(notes)
        self.cost = cost(self.findings)
        self.fp = Fingerprint.of(self.label, notes, phrases)

    @property
    def label(self):
        return f"{self.key}{self.spec.seed}-{self.seed}"

    def build(self):
        return self.notes, self.phrases, self.text

    def try_repair(self):
        res = repair(self.notes, self.ctx)
        if len(res.final) < len(self.findings):
            self.notes = res.notes
            self.findings, self.cost = res.final, cost(res.final)
            self.fp = Fingerprint.of(self.label, self.notes, self.phrases)
        return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", type=int, default=6, help="最终给几个方案")
    ap.add_argument("--specs", type=int, default=6, help="补全几份规格")
    ap.add_argument("--seeds", type=int, default=3, help="每份规格几个种子")
    ap.add_argument("--only", default=None, help="限定歌词方向，如 A,C")
    ap.add_argument("--no-audio", action="store_true")
    # 试听垫 ≠ 成品伴奏。默认用中性参考垫，让差异全部归给旋律
    ap.add_argument("--backing", default="ref",
                    choices=("ref", "drums", "none", "full"),
                    help="ref=底鼓+贝斯长音（推荐）drums=只有鼓 "
                         "none=清唱 full=成品伴奏")
    a = ap.parse_args()

    # 规格里的律动名必须真的存在于伴奏生成器的表里。
    # 这两处是分开维护的，写错名字会到渲染时才崩 —— 提前校验。
    import make_accompaniment as MA
    from svagent.compose import spec as SP
    for pool, table, what in ((SP.PAD_POOL, MA.PAD_STYLES, "垫"),
                              (SP.ARP_POOL, MA.ARP_FIGURES, "琶音"),
                              (SP.BASS_POOL, MA.BASS_GROOVES, "贝斯")):
        miss = [n for n in pool if n not in table]
        assert not miss, f"{what}律动名不存在于 make_accompaniment: {miss}"
    for lvl, opts in SP.DRUM_POOL.items():
        miss = [n for n in opts if n not in MA.DRUM_STYLES]
        assert not miss, f"鼓型不存在: {miss}"

    cfg = CheckCfg()
    keys = ([k.strip() for k in a.only.split(",")] if a.only
            else list(L.CANDIDATES))
    specs = expand_many(L.CANDIDATES and "夜曲", a.specs)

    print(f"《夜曲》池子 = {len(keys)} 个歌词方向 × {a.specs} 份规格 "
          f"× {a.seeds} 个种子 = {len(keys)*a.specs*a.seeds} 个候选")
    print(f"从中挑 {a.pick} 个**互相差异最大**的\n")

    print("补全出来的规格：")
    for i, s in enumerate(specs):
        print(f"  规格{i} {s.bpm:.0f}BPM {s.key_name} "
              f"细胞 {'/'.join(s.rhythm_cells)} 动机 {motif_name(s.motif)}")
        print(f"          律动 垫={s.pad_style} 琶音={s.arp_figure} "
              f"贝斯={s.bass_groove} 鼓={s.drum_pick['full']}")
    print()

    pool = []
    for key in keys:
        for sp in specs:
            for sd in range(a.seeds):
                n, ph, tx, secs = melodize_spec(L.CANDIDATES[key], sp, cfg,
                                                seed=sp.seed * 100 + sd)
                pool.append(Cand(key, sp, sd, n, ph, tx, secs, cfg))

    clean = [c for c in pool if not c.findings]
    print(f"生成 {len(pool)} 个候选，其中 {len(clean)} 个一次就 0 finding "
          f"（{100*len(clean)/len(pool):.0f}%）")
    # 有 finding 的过一遍修复循环，救回来的也进池子
    saved = 0
    for c in pool:
        if c.findings:
            c.try_repair()
            saved += not c.findings
    usable = [c for c in pool if not c.findings]
    print(f"修复循环救回 {saved} 个 → 可用 {len(usable)} 个\n")
    if not usable:
        print("✗ 没有可用候选")
        return 1

    picked = select_diverse(usable, a.pick,
                           cost_of=lambda c: c.cost, fp_of=lambda c: c.fp)

    print("=" * 74)
    print(f"挑出的 {len(picked)} 个方案")
    print("=" * 74)
    for c in picked:
        ps = [n.midi for n in c.notes]
        name = L.CANDIDATES[c.key][0]
        print(f"\n[{c.label}] 词「{name}」　{c.spec.bpm:.0f}BPM "
              f"{c.spec.key_name}")
        print(f"    细胞 {'/'.join(c.spec.rhythm_cells)}　"
              f"动机 {motif_name(c.spec.motif)}")
        print(f"    律动 垫={c.spec.pad_style} 琶音={c.spec.arp_figure} "
              f"贝斯={c.spec.bass_groove} 鼓={c.spec.drum_pick['full']}")
        print(f"    {len(c.notes)} 音符　音域 {note_name(min(ps))}–"
              f"{note_name(max(ps))}　findings {len(c.findings)}")

    print("\n" + "=" * 74)
    print("两两差异度（0=一样，1=毫不相干）—— 「差异大」这句话请自己核对：")
    print(pairwise_table(picked, label_of=lambda c: c.label,
                         fp_of=lambda c: c.fp))
    ds = [distance(x.fp, y.fp) for i, x in enumerate(picked)
          for y in picked[i + 1:]]
    if ds:
        print(f"\n  最小 {min(ds):.3f}　中位 {sorted(ds)[len(ds)//2]:.3f}"
              f"　最大 {max(ds):.3f}")
        print("  **最小值才是判据** —— 它保证任意两个方案之间都拉开了。")

    if not a.no_audio:
        from make_accompaniment import (_write_wav, reference_backing,
                                        render_preview)
        print(f"\n渲染（试听垫 = {a.backing}）：")
        for c in picked:
            parts = reference_backing(c, a.backing)
            mel = [(n.onset_beats, n.duration_beats, n.midi) for n in c.notes]
            acc, m = render_preview(parts, mel, c.BPM, c.N_BARS)
            # 参考垫压低、旋律抬高 —— 这次要听的是旋律
            _write_wav(OUT / f"夜曲_{c.label}_{L.CANDIDATES[c.key][0]}.wav",
                       acc * 0.7 + m * 1.15)
        print("\n完整路径：")
        for c in picked:
            print(f"  {OUT / ('夜曲_%s_%s.wav' % (c.label, L.CANDIDATES[c.key][0]))}")

    print("\n听完告诉我留哪个、砍哪些。原因说不清也没关系。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
