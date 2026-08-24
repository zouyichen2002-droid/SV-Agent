"""Agent 的「观察」：从文件里读出一首歌走到第几步了。

## 为什么这是搭 agent 的第一件事

现在没有任何东西知道「这首歌走到哪了」—— 是人在对话里记着。
而 orchestrator 的第一个动作必然是**观察**，观察不了就无法决定下一步。

## 判定必须看证据，不看标记

**不能用 `done: true` 这种状态文件。** 理由是它会和实际内容脱节：
创作者随时可能在 SynthV 里手改工程、在记事本里改歌词、
或者回滚到 `_backup/` 里的旧版。标记会说谎，内容不会。

所以每一步的完成判定都是**从文件里现算的**：

    步骤 2  歌词能解析、有版本、字数过关
    步骤 3  工程里有主旋律轨且七项检查通过、同轨重叠为 0
    步骤 4  伴奏 MIDI 存在且与工程里的旋律**同源**（每句末音落在标注和弦上）
    步骤 5  工程里有指向 wav 的音频轨；两条人声轨有调教点
    步骤 6  混音 FX 已启用

代价是每次观察都要读文件、跑检查（几秒）。换来的是**状态永远真实**。

## 阻塞原因要具体

`next_actions()` 不只说「不能做」，要说清缺什么、以及那件事该谁做。
「等创作者在 FL 里导出音频」和「等我生成 MIDI」是完全不同的两种阻塞，
agent 必须能区分 —— 否则它会去等一件本该自己做的事。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import project as PJ
from ..compose.checks import CheckCfg, run_all
from ..compose.lyricfile import lint, parse
from ..compose.melodize import chord_of

# 谁来做这一步
BY_AGENT = "agent"
BY_CREATOR = "创作者"
BY_BOTH = "两者"


@dataclass
class Step:
    n: int
    name: str
    who: str
    done: bool
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    command: str | None = None
    # 在等第几步。**「被上游挡住」和「自己坏了」是两件事** ——
    # 仪表盘建好当天就暴露了这个缺失：主旋律同轨重叠 57 处（真的坏了）
    # 和后面三步「等主旋律」被画成一样的红叉，看上去像三处出问题。
    # 这个区分属于状态模型，所以补在这里，不在渲染层拿字符串猜。
    waits_for: int | None = None

    @property
    def blocked_by_self(self) -> bool:
        """有阻塞，且不只是在等上游。"""
        return bool(self.blockers) and self.waits_for is None

    @property
    def mark(self) -> str:
        if self.done:
            return "✓"
        return "✗" if self.blocked_by_self else "…"


@dataclass
class ProjectState:
    proj: PJ.SongProject
    steps: list[Step]

    @property
    def next_step(self) -> Step | None:
        for s in self.steps:
            if not s.done:
                return s
        return None

    @property
    def n_done(self) -> int:
        """完成了几步。**放在这里而不是让前端自己数** —— 见 dashboard.py 的规则。"""
        return sum(1 for s in self.steps if s.done)

    def report(self) -> str:
        out = [self.proj.describe(), ""]
        for s in self.steps:
            out.append(f"  {s.mark} 步骤{s.n} {s.name}　（{s.who}）")
            for e in s.evidence:
                out.append(f"      {e}")
            for b in s.blockers:
                out.append(f"      ⛔ {b}")
        nx = self.next_step
        out.append("")
        if nx is None:
            out.append("  全部六步完成。")
        else:
            out.append(f"  下一步：步骤{nx.n} {nx.name}（{nx.who}）")
            if nx.command:
                out.append(f"    {nx.command}")
        return "\n".join(out)


def _cmd(script: str, slug: str, tail: str = "") -> str:
    return (f"SVAGENT_SONG={slug} python "
            f"E:{chr(92)}sv-bridge{chr(92)}scripts{chr(92)}{script}"
            + (f" {tail}" if tail else ""))


def _svp_tracks(path: Path):
    """→ (轨列表, {组uuid: 组})。文件不存在或坏了返回空。"""
    if not path.exists():
        return [], {}
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return [], {}
    return d.get("tracks", []), {g["uuid"]: g for g in d.get("library", [])}


def _notes_of(track, lib):
    out = []
    for ref in (track.get("groups") or []):
        out += (lib.get(ref.get("groupID")) or {}).get("notes") or []
    return out


def inspect(proj: PJ.SongProject | None = None) -> ProjectState:
    proj = proj or PJ.current()
    slug = proj.slug
    steps: list[Step] = []
    cfg = CheckCfg()

    # ---- 步骤 1：题目 + 空工程 ----
    s1 = Step(1, "定题目", BY_CREATOR, False)
    if PJ.config_path(slug).exists():
        s1.evidence.append(f"配置 {PJ.config_path(slug).name} 存在")
    if not PJ.TEMPLATE.exists():
        s1.blockers.append(f"缺结构模板 {PJ.TEMPLATE}（新建空工程复制过去）")
    if proj.svp.exists():
        s1.evidence.append(f"工程 {proj.svp.name} 存在")
        s1.done = not s1.blockers
    else:
        s1.blockers.append(f"工程 {proj.svp} 不存在 —— 在 SynthV 里新建并保存")
    steps.append(s1)

    # ---- 步骤 2：歌词 ----
    s2 = Step(2, "定歌词", BY_BOTH, False,
              command=f"编辑 {proj.lyrics}")
    if not proj.lyrics.exists():
        s2.blockers.append(f"歌词文件不存在：{proj.lyrics}")
    else:
        vs, probs = parse(proj.lyrics)
        warn = lint(vs)
        if probs:
            s2.blockers.append(f"歌词解析有 {len(probs)} 处问题（跑 lyricfile.py 看）")
        elif not vs:
            s2.blockers.append("歌词文件里没有任何版本（缺 `## X ｜标题`）")
        else:
            for k, v in vs.items():
                s2.evidence.append(f"{k}｜{v.title}　{v.n_lines} 句 / "
                                   f"{v.n_chars} 字"
                                   + ("　⚠ 字数提醒" if warn else ""))
            s2.done = True
    steps.append(s2)

    # ---- 步骤 3：主旋律 + 和声 ----
    s3 = Step(3, "定主旋律和和声", BY_AGENT, False,
              command=_cmd("step3_melody.py", slug, "--write --closed"))
    tracks, lib = _svp_tracks(proj.svp)
    lead = next((t for t in tracks if t["name"].startswith("主旋律")), None)
    harms = [t for t in tracks if t["name"].startswith("和声")]
    if not s2.done:
        s3.blockers.append("等步骤 2 的歌词")
        s3.waits_for = 2
    elif lead is None:
        s3.blockers.append("工程里没有「主旋律」轨")
    else:
        ln = _notes_of(lead, lib)
        Q = 705600000
        srt = sorted(ln, key=lambda n: n["onset"])
        ov = sum(1 for a, b in zip(srt, srt[1:])
                 if a["onset"] + a["duration"] > b["onset"])
        mx = max((n["duration"] / Q for n in ln), default=0)
        s3.evidence.append(f"{lead['name']}　{len(ln)} 音符"
                           f"　同轨重叠 {ov}　最长音 {mx:.2f} 拍")
        for h in harms:
            s3.evidence.append(f"{h['name']}　{len(_notes_of(h, lib))} 音符")
        if ov:
            s3.blockers.append(f"同轨重叠 {ov} 处 —— SynthV 不允许，必须重生成")
        else:
            s3.done = True
    steps.append(s3)

    # ---- 步骤 4：伴奏 ----
    s4 = Step(4, "定伴奏", BY_BOTH, False,
              command=_cmd("step4_accompaniment.py", slug, "--write"))
    if not s3.done:
        s4.blockers.append("等步骤 3 的主旋律")
        s4.waits_for = 3
    else:
        if proj.mid.exists():
            s4.evidence.append(f"伴奏 MIDI {proj.mid.name} "
                               f"{proj.mid.stat().st_size} B")
        else:
            s4.blockers.append(f"伴奏 MIDI 未生成：{proj.mid.name}")
        if proj.wav.exists():
            import soundfile as sf
            try:
                info = sf.info(str(proj.wav))
                s4.evidence.append(f"FL 渲染 {proj.wav.name} "
                                   f"{info.duration:.1f}s"
                                   f"（期望 {proj.duration_s:.1f}s + 尾巴）")
                if info.duration < proj.duration_s * 0.9:
                    s4.blockers.append("渲染时长明显偏短 —— "
                                       "FL 可能导出的是单个 pattern")
                else:
                    s4.done = not s4.blockers
            except Exception as e:
                s4.blockers.append(f"读不了 {proj.wav.name}：{e}")
        else:
            s4.blockers.append(f"等你在 FL 里配器并导出到 {proj.wav}")
            s4.who = BY_CREATOR
    steps.append(s4)

    # ---- 步骤 5：伴奏进 SV + 调教 ----
    s5 = Step(5, "伴奏进 SV + 调教", BY_AGENT, False,
              command=_cmd("step5_assemble.py", slug, "--write --closed")
              + "\n    然后 " + _cmd("step5_tune.py", slug, "--write --closed"))
    audio = [t for t in tracks
             if (t.get("mainRef") or {}).get("isInstrumental")]
    tuned = []
    for t in tracks:
        pts = 0
        for ref in (t.get("groups") or []):
            g = lib.get(ref.get("groupID")) or {}
            pts += sum(len(v.get("points") or []) // 2
                       for v in (g.get("parameters") or {}).values())
            pts += sum(len(v.get("points") or []) // 2
                       for v in (g.get("vocalModes") or {}).values())
        if pts:
            tuned.append((t["name"], pts))
    if not s4.done:
        s5.blockers.append("等步骤 4 的伴奏音频")
        s5.waits_for = 4
    else:
        if audio:
            for t in audio:
                fn = ((t.get("mainRef") or {}).get("audio") or {}).get("filename")
                s5.evidence.append(f"音频轨「{t['name']}」→ {Path(fn).name if fn else '?'}")
        else:
            s5.blockers.append("工程里还没有伴奏音频轨")
        if tuned:
            for nm, pts in tuned:
                s5.evidence.append(f"{nm}　调教 {pts} 点")
        else:
            s5.blockers.append("两条人声轨都没有调教点")
        s5.done = not s5.blockers
    steps.append(s5)

    # ---- 步骤 6：混音 ----
    s6 = Step(6, "混音", BY_AGENT, False,
              command=_cmd("step6_mix.py", slug, "--write --closed"))
    on = []
    for t in tracks:
        fx = (t.get("mixer") or {}).get("fxParams") or {}
        enabled = [k for k in ("postRoomEq", "compressor", "reverb")
                   if (fx.get(k) or {}).get("enabled")]
        if enabled:
            on.append((t["name"], enabled))
    if not s5.done:
        s6.blockers.append("等步骤 5")
        s6.waits_for = 5
    elif not on:
        s6.blockers.append("还没有任何轨启用 FX")
    else:
        for nm, en in on:
            s6.evidence.append(f"{nm}　FX {'/'.join(en)}")
        s6.done = True
    steps.append(s6)

    return ProjectState(proj=proj, steps=steps)


def check_melody(proj: PJ.SongProject | None = None) -> list:
    """对工程里的主旋律跑七项检查。比 inspect 慢，所以单独一个函数。"""
    proj = proj or PJ.current()
    import sys
    sys.path.insert(0, str(PJ.ROOT / "scripts"))
    import step3_melody as S3
    vs, _ = parse(proj.lyrics)
    ver = vs[next(iter(vs))]
    _name, notes, sections = S3.read_lead(proj.svp, ver, proj.form)
    kr, kq, _kn = S3.infer_key([n.midi for n in notes])
    from ..compose.checks import Phrase
    phrases, idx, pi = [], 0, 0
    for _sn, _b, lines in sections:
        for _t, syls, chord in lines:
            _pcs, root, q = chord_of(chord, kr)
            phrases.append(Phrase(pi, idx, idx + len(syls),
                                  chord_root=root, chord_quality=q))
            idx += len(syls)
            pi += 1
    text = "".join(t for _sn, _b, lines in sections for t, _s, _c in lines)
    return run_all(notes, text, kr, kq, phrases, CheckCfg())


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    st = inspect()
    print(st.report())
    if st.steps[2].done:
        fs = check_melody(st.proj)
        print(f"\n  七项检查：{len(fs)} findings")
        for f in fs[:6]:
            print(f"    {f}")
