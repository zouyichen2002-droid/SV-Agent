# -*- coding: utf-8 -*-
"""工作流步骤 3：一条主旋律 + 多条和声轨，写进 SynthV 工程。

## 交付形态（创作者 2026-08-23 修正）

**一条主旋律 + 多条和声轨**，之后让 agent 重写或局部修改。

原设计是「一个工程 12 条轨，6 版旋律 + 6 版和声，solo 切换选一版」。
改掉的三个理由，都是实测出来的：

1. **SynthV 不支持同一条轨上音符重叠。** 和声（同一个歌姬唱不同音）与
   合唱（不同歌姬同时唱）必须各占一条轨。这是约束，不是偏好。
2. **六版共用一条时间轴**，因此必须共用同一个 BPM —— 多版的价值本来就打折。
3. **迭代比选择更贴合创作。**「这句改一下」比「六个里挑一个」更接近
   真实的创作动作，而且改动可以累积。

## 一个项目一个文件，改动写回原处

**一个项目就是一个 txt、一个 svp、一个 FL 工程**，修改和重写都写回同一份。

配套三条防护，因为「写回原处」有一个真实风险：
**SynthV 开着该文件时我写盘，它内存里的旧内容可能被创作者保存回去覆盖掉**
（实测差点发生 —— 标题栏带星号，弹窗问「是否放弃未保存的更改」）。

    1. **必须显式确认工程已关闭**（`--closed`）。
       没有这个确认就拒绝写 —— 检测到 SynthV 在跑更是直接拦住。
       这是创作者定的硬规则：**没确认关闭就先提醒，不要改。**
    2. 每次写前自动备份到 `_backup/`，带时间戳
    3. 结构模板另存在仓库（`songs/_template/empty_v196.svp`），
       不拿工作工程兼任模板 —— 那两个身份会冲突

## 局部修改：`--keep-melody`

只想改和声时，从工程里读回主旋律，不重新生成。
段落归属用歌词 + 曲式重算（两者同源），不依赖工程里的元数据。

用法:
    python scripts/step3_melody.py                        # 只看报告
    python scripts/step3_melody.py --write --closed       # 生成新旋律 + 和声
    python scripts/step3_melody.py --keep-melody --harmony 低八度 --write --closed
    python scripts/step3_melody.py --write --closed --harmony-sections 副歌,预副
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "out"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import svp_build as SB
from svagent.compose.checks import (MAJOR, MINOR, NAMES, CheckCfg, Note,
                                    check_range, note_name)
from svagent.compose.harmonize import HarmonyPlan, harmonize
from svagent.compose.lyricfile import parse
from svagent.compose.melodize import melodize_spec
from svagent.compose.repair import Ctx, cost, repair
from svagent.compose.spec import expand_many, motif_name
from svagent.compose.uniqueness import Fingerprint, report

from svagent import project as PJ

# 当前项目由环境变量 SVAGENT_SONG 决定（见 toolkit/svagent/project.py）。
# **每首新歌只改 songs/<slug>/project.json，不改代码。**
P = PJ.current()
LYRICS = P.lyrics
TEMPLATE = PJ.TEMPLATE          # 结构模板：创作者空工程的纯净副本，只读
PROJECT = P.svp                 # 工作工程：始终写这一个，不带序号
BACKUP_DIR = P.backup_dir
FORM = P.form
N_BARS = P.n_bars
SONG_BPM = P.bpm

# 同调替换对。每对共享两个音，换了不破调性
SUBS = {"Am": "C", "C": "Am", "F": "Dm", "Dm": "F", "G": "Em", "Em": "G"}


def vary_progression(sections, rng: random.Random, rate: float):
    """按概率做同调替换。**最后一段的最后一句永不换** —— 必须落主和弦。"""
    out = []
    n_sec = len(sections)
    for si, (name, lines) in enumerate(sections):
        new_lines = []
        for li, (text, chord) in enumerate(lines):
            last = (si == n_sec - 1 and li == len(lines) - 1)
            if not last and rng.random() < rate and chord in SUBS:
                chord = SUBS[chord]
            new_lines.append((text, chord))
        out.append((name, new_lines))
    return out


class Cand:
    def __init__(self, spec, sections, notes, phrases, text, secs, cfg):
        self.spec, self.sections = spec, sections
        self.notes, self.phrases, self.text = notes, phrases, text
        self.SECTIONS = secs
        self.ctx = Ctx(text=text, key_root=spec.key_root, quality=spec.mode,
                       phrases=phrases, cfg=cfg)
        self.findings = self.ctx.check(notes)
        self.cost = cost(self.findings)
        self.fp = Fingerprint.of("候选", notes, phrases)

    @property
    def prog(self):
        return " / ".join("-".join(c for _, c in lines)
                          for _, lines in self.sections)

    def try_repair(self):
        r = repair(self.notes, self.ctx)
        if len(r.final) < len(self.findings):
            self.notes, self.findings = r.notes, r.final
            self.cost = cost(r.final)
            self.fp = Fingerprint.of("候选", self.notes, self.phrases)
        return r


def overlaps(notes) -> int:
    """同轨重叠数。**SynthV 不允许非 0。**"""
    s = sorted(notes, key=lambda n: n.onset_beats)
    return sum(1 for a, b in zip(s, s[1:])
               if a.onset_beats + a.duration_beats > b.onset_beats + 1e-9)


def infer_key(midis: list[int]) -> tuple[int, str, str]:
    """从音高推调。只改和声时不必依赖轨名。小调优先。"""
    best = None
    for quality, degs in (("minor", MINOR), ("major", MAJOR)):
        for root in range(12):
            pcs = {(root + d) % 12 for d in degs}
            hit = sum(1 for m in midis if m % 12 in pcs)
            tonic_w = sum(1 for m in midis if m % 12 == root)
            key = (hit, quality == "minor", tonic_w)
            if best is None or key > best[0]:
                best = (key, root, quality)
    _k, root, quality = best
    name = f"{NAMES[root]} {'小调' if quality == 'minor' else '大调'}"
    return root, quality, name


def read_lead(project: Path, ver, form):
    """从工程里读回主旋律，并重建 melodize 那种 SECTIONS 形状。

    这是「局部修改」的基础：只改和声时不该重新生成旋律。
    段落归属不从工程里读 —— 用歌词 + 曲式重算，两者本来就是同源的。
    """
    back = SB.read_back(project)
    lead_name = next((k for k in back if k.startswith("主旋律")), None)
    if lead_name is None:
        raise SystemExit(f"{project} 里没有「主旋律」轨，无法只改和声")
    raw = sorted(back[lead_name], key=lambda n: n["onset"])
    Q = SB.QUARTER_BLICKS
    notes = [Note(i, n["onset"] / Q, n["duration"] / Q, int(n["pitch"]),
                  str(n["lyrics"])) for i, n in enumerate(raw)]

    bar_of, bar = {}, 0
    for name, nb in form:
        bar_of[name] = bar
        bar += nb
    sections, idx = [], 0
    for sec_name, lines in ver.sections:
        sec_lines = []
        for text, chord in lines:
            syls = []
            for ch in text:
                if idx >= len(notes):
                    raise SystemExit(
                        f"工程里只有 {len(notes)} 个音符，"
                        f"歌词需要 {ver.n_chars} 个 —— 两者不同源")
                n = notes[idx]
                syls.append((ch, n.midi, n.duration_beats))
                idx += 1
            sec_lines.append((text, syls, chord))
        sections.append((sec_name, bar_of.get(sec_name, 0), sec_lines))
    if idx != len(notes):
        print(f"  ⚠ 工程里 {len(notes)} 个音符，歌词只用掉 {idx} 个")
    return lead_name, notes, sections


def synthv_running() -> bool:
    """SynthV 是否在跑。"""
    import subprocess
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True,
                           text=True, errors="replace", timeout=20)
        return "synthesizer v" in r.stdout.lower()
    except Exception:
        return False


def backup(path: Path) -> Path | None:
    """写前备份。**这是「写回原处」唯一的安全网。**

    既防我写坏，也防 SynthV 的旧内存把新内容盖掉 —— 两种都能回滚。
    """
    import shutil
    import time
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / (path.stem + "_" + stamp + path.suffix)
    shutil.copy2(path, dst)
    return dst


def gate_before_write(a) -> str | None:
    """写盘前的闸门。返回拒绝原因，None 表示可以写。

    创作者定的硬规则：**没有确认工程已关闭，就先提醒，不要改。**
    所以默认是拒绝，必须显式给 `--closed`。
    """
    if not a.closed:
        return ("没有确认工程已关闭。请先在 SynthV 里关掉 "
                f"{PROJECT.name}，然后加 --closed 再跑。")
    if synthv_running():
        return ("检测到 SynthV 进程还在运行。即使你确认关了工程，"
                "也请先退出 SynthV —— 它内存里的旧内容有可能被保存回去，"
                "覆盖掉我刚写的。确实要写就加 --force-write。")
    return None


def write_project(a, lead_name, lead_notes, lead_sections,
                  key_root, quality, cfg, phrases=None):
    """生成和声并写工程。两条路径（新旋律 / 只改和声）共用这一段。"""
    kinds = [k.strip() for k in a.harmony.split(",") if k.strip()]
    secs = tuple(x.strip() for x in a.harmony_sections.split(",") if x.strip())
    print()
    print(f"和声轨 {len(kinds)} 条，覆盖 {'/'.join(secs)}")
    harmonies = []
    for kind in kinds:
        hn, warns = harmonize(lead_notes, phrases or [], lead_sections,
                              HarmonyPlan(kind=kind, sections=secs),
                              key_root=key_root, quality=quality, cfg=cfg)
        if not hn:
            print(f"  ✗ {kind}：一个音都没生成")
            continue
        uni = sum(1 for h in hn for m in lead_notes
                  if abs(h.onset_beats - m.onset_beats) < 1e-9
                  and h.midi == m.midi)
        rr = [n.midi for n in hn]
        print(f"  {kind}　{len(hn)} 音符　"
              f"{note_name(min(rr))}-{note_name(max(rr))}"
              f"　range {len(check_range(hn, cfg))}"
              f"　重叠 {overlaps(hn)}　与主旋律同音 {uni}")
        for w in warns[:2]:
            print(f"      {w}")
        harmonies.append((kind, hn))

    if not a.write:
        print()
        print("没有 --write，不碰工程文件。")
        return 0

    reason = gate_before_write(a)
    if reason and not a.force_write:
        print()
        print("✗ 暂不修改工程：" + reason)
        return 4

    bk = backup(PROJECT)
    print()
    print("=== 写工程 ===")
    print(f"模板 {TEMPLATE.name}　→　{PROJECT}")
    if bk:
        print(f"  已备份原文件 → {bk}")
    b = SB.Builder(SB.load_template(TEMPLATE), bpm=a.bpm)
    b.add_vocal(lead_name,
                [SB.note(n.onset_beats, n.duration_beats, n.midi, n.lyric)
                 for n in lead_notes], voice=SB.VOICE_STARDUST)
    for kind, hn in harmonies:
        b.add_vocal(f"和声_{kind}",
                    [SB.note(n.onset_beats, n.duration_beats, n.midi, n.lyric)
                     for n in hn], voice=SB.VOICE_STARDUST, gain_db=-5.0)
    saved = b.save(PROJECT, force=True)
    print(f"工程写出　{saved}　{saved.stat().st_size} B"
          f"　{len(b.proj['tracks'])} 条轨")

    back = SB.read_back(saved)
    allok = True
    checklist = [(lead_name, lead_notes)]
    checklist += [(f"和声_{k}", h) for k, h in harmonies]
    for name, want in checklist:
        got = back.get(name, [])
        same = (len(got) == len(want) and all(
            int(g["pitch"]) == w.midi and str(g["lyrics"]) == w.lyric
            for g, w in zip(got, want)))
        print(f"  {'✓' if same else '✗'} {name}　回读 {len(got)}/{len(want)}"
              + ("　逐字段一致" if same else "　不一致"))
        allok &= same
    print()
    print(f"打开 {saved}")
    print("要改直接说：「重写」「副歌抬高一点」「和声只要下三度」都行 ——")
    print("改动写回这同一个文件，旧版留在 _backup/ 里。")
    return 0 if allok else 3


def parse_register_shift(s: str) -> dict[str, int]:
    """`"+3"` → 全段 +3；`"副歌=+3,主歌=-2"` → 按段。空串 → 不动。

    `""` 是**默认值**，必须解析成「什么都不做」—— 这个开关是给 agent 的
    `adjust_spec` 用的，绝大多数调用不会带它，不许因此改变既有行为。
    """
    s = (s or "").strip()
    if not s:
        return {}
    if "=" not in s:
        return {"*": int(s)}
    out = {}
    for part in s.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = int(v)
    return out


def apply_register_shift(sp, shift: dict[str, int]) -> None:
    """就地改规格的音区。**不许越出声库舒适音域** —— 越界了唱不上去。

    星尘的舒适音域 MIDI 57–78（A3–F#5）。夹取而不是拒绝：
    创作者说「再高一点」时，给他能唱的最高，比报错有用。
    """
    if not shift:
        return
    lo_cap, hi_cap = 57, 78
    for sec, (lo, hi) in list(sp.register.items()):
        d = shift.get(sec, shift.get("*", 0))
        if not d:
            continue
        span = hi - lo
        nlo = max(lo_cap, min(lo + d, hi_cap - span))
        sp.register[sec] = (nlo, nlo + span)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", type=int, default=24,
                    help="候选池大小。只出一条，池子大一点挑得更准")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--bpm", type=float, default=SONG_BPM,
                    help="48 小节：62→3:06　66→2:54　70→2:45")
    ap.add_argument("--harmony", default="低八度",
                    help="和声轨，逗号分隔。可选 低八度/下三度/上三度/下六度")
    ap.add_argument("--harmony-sections", default="副歌",
                    help="和声覆盖哪些段落，逗号分隔（按段名前缀匹配）")
    ap.add_argument("--keep-melody", action="store_true",
                    help="保留工程里现有的主旋律，只重做和声（局部修改）")
    ap.add_argument("--register-shift", default="",
                    help="音区整体或按段偏移半音，如 \"+3\" 或 \"副歌=+3,主歌=-2\"。"
                         "「副歌太平」最直接对应的旋钮（agent 的 adjust_spec 用它）")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--closed", action="store_true",
                    help="确认已在 SynthV 里关闭该工程。**没有它不会写盘**")
    ap.add_argument("--force-write", action="store_true",
                    help="闸门也挡不住时强制写（仍会备份）")
    a = ap.parse_args()

    cfg = CheckCfg()
    vs, probs = parse(LYRICS)
    if probs:
        print("✗ 歌词解析有问题，先修：")
        for x in probs:
            print("  ", x)
        return 1
    ver = vs[next(iter(vs))]
    base = [(name, list(lines)) for name, lines in ver.sections]
    dur = N_BARS * 4 * 60.0 / a.bpm
    print(f"歌词　{ver.key}｜{ver.title}　{ver.n_lines} 句 / {ver.n_chars} 字")
    print(f"曲式　{N_BARS} 小节 @{a.bpm:.0f}BPM = "
          f"{int(dur // 60)}:{int(dur % 60):02d}　"
          + " · ".join(f"{n}{b}" for n, b in FORM))
    print("建议进行　"
          + " / ".join("-".join(c for _, c in ls) for _, ls in base))
    print()

    if a.keep_melody:
        lead_name, lead_notes, lead_sections = read_lead(PROJECT, ver, FORM)
        kr, kq, kname = infer_key([n.midi for n in lead_notes])
        ps = [n.midi for n in lead_notes]
        print(f"保留现有主旋律　{lead_name}　{len(lead_notes)} 音符"
              f"　{note_name(min(ps))}-{note_name(max(ps))}　推定 {kname}")
        return write_project(a, lead_name, lead_notes, lead_sections,
                             kr, kq, cfg)

    shift = parse_register_shift(a.register_shift)
    if shift:
        print(f"音区偏移　{a.register_shift}")

    pool = []
    for si, sp in enumerate(expand_many("晓风残月", a.specs)):
        sp.bpm = a.bpm
        apply_register_shift(sp, shift)
        for sd in range(a.seeds):
            rng = random.Random(si * 1000 + sd)
            rate = 0.0 if sd == 0 else (0.25 if sd == 1 else 0.45)
            secs_in = vary_progression(base, rng, rate)
            n, ph, tx, secs_out = melodize_spec(
                (ver.title, ver.gist, secs_in), sp, cfg,
                seed=si * 100 + sd, form=FORM)
            pool.append(Cand(sp, secs_in, n, ph, tx, secs_out, cfg))

    clean = [c for c in pool if not c.findings]
    print(f"生成 {len(pool)} 个候选，{len(clean)} 个一次就 0 finding "
          f"（{100 * len(clean) / len(pool):.0f}%）")
    for c in pool:
        if c.findings:
            c.try_repair()
    usable = [c for c in pool if not c.findings and overlaps(c.notes) == 0]
    print(f"修复循环 + 零重叠之后可用 {len(usable)} 个")
    if not usable:
        print("✗ 没有可用候选")
        return 2

    refs = []
    try:
        import melody_v2 as prev
        pn, pp, _ = prev.build()
        refs.append(Fingerprint.of("宇宙无边无垠", pn, pp))
    except Exception:
        pass
    best = (max(usable, key=lambda c: min(1.0 - max(c.fp.similarity(r).values())
                                          for r in refs))
            if refs else usable[0])

    ps = [n.midi for n in best.notes]
    mx = max(n.duration_beats for n in best.notes)
    print()
    print("=" * 72)
    print("主旋律")
    print("=" * 72)
    print(f"  {a.bpm:.0f}BPM {best.spec.key_name}　{len(best.notes)} 音符"
          f"　{note_name(min(ps))}-{note_name(max(ps))}")
    print(f"  和声进行 {best.prog}")
    print(f"  节奏细胞 {'/'.join(best.spec.rhythm_cells)}"
          f"　动机 {motif_name(best.spec.motif)}")
    print(f"  音区 主歌{best.spec.register['主歌']}"
          f" 副歌{best.spec.register['副歌']}")
    print(f"  最长音 {mx:.2f} 拍 = {mx * 60 / a.bpm:.2f}s"
          f"　同轨重叠 {overlaps(best.notes)}（SynthV 不允许非 0）")
    if refs:
        print("  与既有作品的相似度：")
        print(report(best.notes, best.phrases, refs))

    return write_project(a, f"主旋律_{best.spec.key_name}", best.notes,
                         best.SECTIONS, best.spec.key_root, best.spec.mode,
                         cfg, phrases=best.phrases)


if __name__ == "__main__":
    raise SystemExit(main())
