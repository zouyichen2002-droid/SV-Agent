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
from svagent.compose.melodize import melodize_spec, phrases_of
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


def using(proj):
    """临时把模块级全局切到某首歌。用 `with`。

    ## 为什么需要它

    这个模块在 **import 时**绑定 `P = PJ.current()`，而 import 只发生一次。
    作为子进程跑时没问题（每次都是新进程，`SVAGENT_SONG` 说了算），
    但**被 in-process import 之后**（写后钩子、`verify_alignment` 动作
    都这么用），globals 就固定在了第一次 import 时的那首歌上。

    第二首歌一出现，`align_report` 就会去读第一首歌的 wav —— 而且
    不报错，只是数字算错。这个洞只有多首歌并存时才会露头。
    """
    import contextlib

    @contextlib.contextmanager
    def _cm():
        global P, LYRICS, PROJECT, BACKUP_DIR, FORM, N_BARS, SONG_BPM
        old = (P, LYRICS, PROJECT, BACKUP_DIR, FORM, N_BARS, SONG_BPM)
        P, LYRICS, PROJECT = proj, proj.lyrics, proj.svp
        BACKUP_DIR, FORM = proj.backup_dir, proj.form
        N_BARS, SONG_BPM = proj.n_bars, proj.bpm
        try:
            yield proj
        finally:
            (P, LYRICS, PROJECT, BACKUP_DIR, FORM,
             N_BARS, SONG_BPM) = old
    return _cm()


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

    return lead_name, notes, sections_from(notes, ver, form)


def sections_from(notes, ver, form):
    """（音符表, 歌词版本, 曲式）→ melodize 那种 SECTIONS 形状。

    **抽出来是因为局部重生成（`--sections`）也要用它**：拼接之后音符变了，
    段落结构得按新音符重建。原来内联在 `read_lead` 里，
    拼接那条路就得再写一遍 —— 又一次「两个实现」。
    """
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
                        f"音符只有 {len(notes)} 个，"
                        f"歌词需要 {ver.n_chars} 个 —— 两者不同源")
                n = notes[idx]
                syls.append((ch, n.midi, n.duration_beats))
                idx += 1
            sec_lines.append((text, syls, chord))
        sections.append((sec_name, bar_of.get(sec_name, 0), sec_lines))
    if idx != len(notes):
        print(f"  ⚠ 音符 {len(notes)} 个，歌词只用掉 {idx} 个")
    return sections


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


def carry_over(b, old_path: Path) -> list[str]:
    """把上游步骤的成果搬进新工程：**音频轨 · 混音 · 没变的轨的调教**。

    ## 为什么必须有

    这个函数从**空模板**重建工程。没有搬运的话，一次「只重生成副歌」
    会把第 4/5/6 步的全部成果冲掉：伴奏音频轨消失、调教归零、混音回默认。
    而工程照样能打开、照样能唱 —— 又一个安静的破坏。
    实测就是这么被第 6 项的测试抓到的。

    ## 调教按音符走

    **只有音符逐字段没变的轨才保留调教。** 曲线是按时间锚定的，
    音符换了还留着，等于把颤音挂在错的字上 —— 比丢了更难发现。
    """
    import json
    try:
        old = json.loads(Path(old_path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []

    def notes_of(proj, track):
        lib = {g.get("uuid"): g for g in (proj.get("library") or [])}
        out = []
        for ref in (track.get("groups") or []):
            out += (lib.get(ref.get("groupID")) or {}).get("notes") or []
        return sorted(out, key=lambda n: n["onset"])

    def params_of(proj, track):
        lib = {g.get("uuid"): g for g in (proj.get("library") or [])}
        for ref in (track.get("groups") or []):
            g = lib.get(ref.get("groupID")) or {}
            if g.get("parameters") or g.get("vocalModes"):
                return g.get("parameters"), g.get("vocalModes")
        return None, None

    old_by_name = {t.get("name"): t for t in (old.get("tracks") or [])}
    new_lib = {g.get("uuid"): g for g in (b.proj.get("library") or [])}
    log = []

    for t in b.proj.get("tracks") or []:
        o = old_by_name.get(t.get("name"))
        if o is None:
            continue
        if o.get("mixer"):
            t["mixer"] = o["mixer"]
            log.append(f"搬回混音　{t['name']}")
        pa, vm = params_of(old, o)
        if not (pa or vm):
            continue
        if notes_of(old, o) == notes_of(b.proj, t):
            for ref in (t.get("groups") or []):
                g = new_lib.get(ref.get("groupID"))
                if g is None:
                    continue
                if pa:
                    g["parameters"] = pa
                if vm:
                    g["vocalModes"] = vm
            n = sum(len(v.get("points") or []) // 2
                    for v in (pa or {}).values())
            log.append(f"搬回调教　{t['name']}　{n} 点（音符没变）")
        else:
            log.append(f"丢弃调教　{t['name']}　音符变了，曲线会挂在错的字上")

    new_names = {t.get("name") for t in (b.proj.get("tracks") or [])}
    for o in (old.get("tracks") or []):
        if ((o.get("mainRef") or {}).get("isInstrumental")
                and o.get("name") not in new_names):
            b.proj["tracks"].append(o)
            log.append(f"搬回音频轨　{o.get('name')}")
    return log


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
    for line in carry_over(b, PROJECT):
        print("  " + line)
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
    ap.add_argument("--sections", default="",
                    help="**只重生成这些段落**，其余逐字段不变（按段名前缀匹配）。"
                         "局部修改是归因的前提 —— 整首重生成之后无法判断"
                         "改善来自哪一处")
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

    # 局部重生成必须**锁在现有旋律的调上**。候选是按自己的调生成的，
    # 把 G 小调的副歌拼进 D 小调的歌，结果是满屏 scale finding ——
    # 实测第一版就是这样，13 个调外音，写后钩子当场抓到。
    lock_key = None
    if a.sections:
        _ln, _lnotes, _ls = read_lead(PROJECT, ver, FORM)
        kr0, kq0, kn0 = infer_key([n.midi for n in _lnotes])
        lock_key = (kr0, kq0, kn0)
        print(f"局部重生成　锁定现有调性 {kn0}")

    pool = []
    for si, sp in enumerate(expand_many("晓风残月", a.specs)):
        sp.bpm = a.bpm
        apply_register_shift(sp, shift)
        if lock_key:
            sp.key_root, sp.mode, sp.key_name = lock_key
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

    lead_notes, lead_sections = best.notes, best.SECTIONS
    lead_name = f"主旋律_{best.spec.key_name}"
    key_root, quality = best.spec.key_root, best.spec.mode

    if a.sections:
        # 局部重生成：整首生成一版，然后**只把点名的段落拼进现有旋律**。
        # 这样不必改 melodize，而「没点名的段落逐字段不变」是可断言的。
        from svagent.agent import segments as SG
        old_name, old_notes, _old_secs = read_lead(PROJECT, ver, FORM)
        scope = [x.strip() for x in a.sections.split(",") if x.strip()]
        lead_notes, srep = SG.splice(old_notes, best.notes, scope, ver, FORM)

        # 拼接会在段落交界处留下问题（实测：句末落音）。跑一次自修复，
        # **然后再拼一次** —— 修复可能动到范围外的音符，
        # 而「没点名的段落逐字段不变」是这一项的验收判据，不能为修复让路。
        merged_secs = sections_from(lead_notes, ver, FORM)
        ph2 = phrases_of(merged_secs, infer_key([n.midi for n in lead_notes])[0])
        ctx2 = Ctx(text="".join(t for _s, _b, ls in merged_secs
                                for t, _y, _c in ls),
                   key_root=infer_key([n.midi for n in lead_notes])[0],
                   quality=infer_key([n.midi for n in lead_notes])[1],
                   phrases=ph2, cfg=cfg)
        before_fix = len(ctx2.check(lead_notes))
        if before_fix:
            r = repair(lead_notes, ctx2)
            if len(r.final) < before_fix:
                lead_notes, _ = SG.splice(old_notes, r.notes, scope, ver, FORM)
                print(f"  拼接后自修复　{before_fix} → {len(r.final)} finding")

        lead_sections = sections_from(lead_notes, ver, FORM)
        lead_name = old_name          # 大部分还是原来那条旋律，名字不改
        kr2, kq2, _kn = infer_key([n.midi for n in lead_notes])
        key_root, quality = kr2, kq2
        print()
        print("=" * 72)
        print("局部重生成")
        print("=" * 72)
        for line in srep.describe().splitlines():
            print("  " + line)
        if not SG.unchanged_outside(old_notes, lead_notes, scope, ver):
            print("  ✗ 点名之外的段落被改动了 —— 这是 bug，不要写盘")
            return 5

    ps = [n.midi for n in lead_notes]
    mx = max(n.duration_beats for n in lead_notes)
    print()
    print("=" * 72)
    print("主旋律")
    print("=" * 72)
    print(f"  {a.bpm:.0f}BPM {best.spec.key_name}　{len(lead_notes)} 音符"
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

    return write_project(a, lead_name, lead_notes,
                         lead_sections, key_root, quality,
                         cfg, phrases=best.phrases)


if __name__ == "__main__":
    raise SystemExit(main())
