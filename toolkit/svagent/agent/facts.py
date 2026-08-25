# -*- coding: utf-8 -*-
"""建造顺序第 4 项：**环境事实归集**。

## 问题不是「没写下来」，是「写在了 agent 读不到的地方」

这些硬约束现在散在十几个 docstring 里。人读得到，agent 读不到 ——
**agent 读不到就等于没有**。它会重新踩一遍：又去推荐创作者没有的插件、
又把和声写进同一条轨、又用 `hash()` 当种子。

## 但更麻烦的是：事实会烂掉，而且烂得很安静

写这个模块的当天就抓到一条：我一直记着「mido 的中文轨名会崩」，
实际测下来**构造时不崩，保存时才崩**（`UnicodeEncodeError: 'latin-1'`）。
差别很要紧 —— 按错的版本去防，会防在错的地方。

所以这一层的核心不是「把事实抄下来」，而是：

> **能自动复验的事实，就必须自动复验。**

每条事实要么带一个 `check()`，要么老实标成「只有出处，不能复验」。
一份没人复查的约束清单，和只报 0 的检查是同一类东西。

## 每条事实必须记出处

`learned` 字段不许为空。这个项目的事实全是踩出来的 ——
没有出处的断言无法被重新验证，也无法判断它什么时候会失效。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[3]

FAST, SLOW, NETWORK, MANUAL = "fast", "slow", "network", "manual"


@dataclass
class Fact:
    id: str
    domain: str
    claim: str                       # 一句话断言
    matters: str                     # 不知道会怎样
    learned: str                     # **出处，不许空**
    check: Callable[[], tuple[bool, str]] | None = None
    cost: str = MANUAL               # fast / slow / network / manual

    @property
    def verifiable(self) -> bool:
        return self.check is not None


@dataclass
class Result:
    fact: Fact
    ok: bool | None                  # None = 没复验（不可复验或被跳过）
    detail: str = ""

    @property
    def color(self) -> str:
        return "on" if self.ok else ("off" if self.ok is False else "unknown")


# =========================================================================
# 复验函数。**每个都要真的去测，不许读一个常量回来自我确认。**
# =========================================================================

def _v_svp_version() -> tuple[bool, str]:
    p = ROOT / "songs" / "_template" / "empty_v196.svp"
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    need = {"library", "tracks", "time", "uuid"}
    ok = d.get("version") == 196 and need <= set(d)
    return ok, f"version={d.get('version')}　顶层键齐全={need <= set(d)}"


def _v_database_two_places() -> tuple[bool, str]:
    from .. import project as PJ
    d = json.loads(PJ.current().svp.read_text(encoding="utf-8-sig"))
    bad, n_vocal = [], 0
    for t in d.get("tracks", []):
        main = t.get("mainRef") or {}
        if main.get("isInstrumental"):
            continue
        if not (t.get("groups") or []):
            continue          # 还没放音符的空轨，这条断言不适用于它
        n_vocal += 1
        a = (main.get("database") or {}).get("name") or ""
        gs = [(g.get("database") or {}).get("name") or ""
              for g in (t.get("groups") or [])]
        if not a or not all(gs) or not gs:
            bad.append(t.get("name"))
    if not n_vocal:
        # **不适用 ≠ 通过，也 ≠ 失败。** 新歌还没有人声轨时，
        # 这条断言无从复验 —— 三色纪律，不许拿一个状态冒充另一个。
        return None, "当前项目还没有人声轨，这条无从复验"
    return not bad, ("人声轨两处都设了声库" if not bad
                     else f"这些轨缺声库：{bad}")


def _v_mido_latin1() -> tuple[bool, str]:
    """断言是「保存中文轨名会抛 UnicodeEncodeError」。**复验它真的会抛。**"""
    import mido
    mf = mido.MidiFile()
    tr = mido.MidiTrack()
    mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="主旋律"))
    with tempfile.TemporaryDirectory() as d:
        try:
            mf.save(str(Path(d) / "t.mid"))
        except UnicodeEncodeError as e:
            return True, f"保存时抛 {type(e).__name__}（构造时不抛）"
        return False, "居然存进去了 —— mido 换行为了，MIDI_NAME 映射可以去掉"


def _v_hash_salted() -> tuple[bool, str]:
    outs = {subprocess.run([sys.executable, "-c", "print(hash('副歌'))"],
                           capture_output=True, text=True).stdout.strip()
            for _ in range(3)}
    return len(outs) > 1, f"三个进程得到 {len(outs)} 个不同的值"


def _v_midi_tempo_integer() -> tuple[bool, str]:
    out = []
    for bpm in (66, 76):
        us = int(round(60_000_000 / bpm))
        out.append(f"{bpm}→{60_000_000 / us:.6f}")
    inexact = any(abs(60_000_000 / int(round(60_000_000 / b)) - b) > 1e-9
                  for b in (66, 76))
    return inexact, "　".join(out)


def _v_mtime_resolution() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.txt"
        same = 0
        for i in range(100):
            f.write_text("a" * i)
            a = f.stat().st_mtime_ns
            f.write_text("b" * i)
            same += (a == f.stat().st_mtime_ns)
    return same > 0, f"连续两次写 mtime 相同 {same}/100 次"


def _v_mistral_rate() -> tuple[bool, str]:
    """要发一次真请求。**默认不跑** —— 每分钟只有 4 次配额，别让体检吃掉。"""
    import urllib.request
    key = ""
    try:
        for ln in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if ln.startswith("MISTRAL_API_KEY="):
                key = ln.split("=", 1)[1].strip()
    except OSError:
        pass
    if not key:
        return False, "读不到 MISTRAL_API_KEY（.env 缺失？）"
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/models",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        n = r.headers.get("x-ratelimit-limit-req-minute")
    return n is not None, f"服务端报的上限 = {n} 次/分钟"


def _v_alignment_bias() -> tuple[bool, str]:
    """起音检测器的系统性偏置。跑一次正弦自校准，看它落在已知量级里。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import numpy as np
    import step5_assemble as S5
    from verify_alignment import best_lag, onset_envelope
    from .. import project as PJ
    proj = PJ.current()
    _lead, _notes, _k, parts = S5.parts_of_project(proj.bpm)
    cal = S5.sine_render(parts, proj.bpm, proj.n_bars)
    meas, spf = onset_envelope(cal.astype(np.float32), S5.SR)
    exp = S5.expected_env(parts, len(meas), spf, proj.bpm)
    bias, cor = best_lag(exp, meas, spf)
    return 5.0 <= bias <= 20.0, f"实测偏置 {bias:+.1f} ms（相关峰 {cor:.3f}）"


# =========================================================================
# 事实本体
# =========================================================================

FACTS: list[Fact] = [
    Fact("F01", "文件格式",
         "`.svp` 是纯 JSON，创作者本机版本 196；音符在 `library[i].notes`，"
         "轨通过 `groups[j].groupID → library[i].uuid` 引用",
         "不知道就只能靠 SynthV GUI 手工装配，直写 `.svp` 那一整条路都没了",
         "从创作者本机导出的空工程反推（ADR-0009）。此前按别人的 187 版猜，"
         "缺了 6 个字段",
         _v_svp_version, FAST),

    Fact("F02", "SynthV",
         "声库必须在**两处**设置：`tracks[i].mainRef.database` 与 "
         "`tracks[i].groups[j].database`",
         "只设一处，SynthV 界面显示「未设置默认歌声」，唱不出来",
         "实测踩过。只设了 mainRef，创作者打开发现没声音",
         _v_database_two_places, FAST),

    Fact("F03", "SynthV",
         "**不支持同一条轨里音符重叠**，所以和声与合唱必须分轨",
         "重叠的音符会被吞掉或产生怪声。曾经一次生成出 57 处重叠",
         "实测。根因是句长参数与曲式分配的小节数不一致",
         None, MANUAL),

    Fact("F04", "FL Studio",
         "FL 的脚本 API **不能加载插件**，所以「导入 MIDI」和「给轨挂音源」"
         "永远是手动的",
         "任何指望自动配器的设计都会卡死在这里（ADR-0011 因此把 FL 桥移出主链路）",
         "`fl_plugin_list` 工具自己的说明原文：\"We cannot load NEW plugins "
         "(FL API limit)\"",
         None, MANUAL),

    Fact("F05", "FL Studio",
         "创作者的 FL 是 **Producer 版**：可用 FLEX、General MIDI Library、FPC；"
         "**没有** Morphine / Sakura / Harmor / Ogun（那些是 All Plugins Edition）",
         "推荐他没有的音源，他只能打开一个试用弹窗",
         "我读了 FL 的插件**数据库**目录（58 个生成器）就当成他拥有，推荐错了一轮。"
         "他的版本号当时就在 FL 桥心跳里，我没把两件事连起来",
         None, MANUAL),

    Fact("F06", "平台",
         "Windows 的文件 mtime 分辨率约 15 ms，**连续两次写有很高概率时间戳相同**",
         "只看 mtime 的变更检测会漏掉「同字节长度的改动」，表现是界面显示旧数据且不报错",
         "第 1 项写监视器时实测：100 次里 59 次碰撞",
         _v_mtime_resolution, FAST),

    Fact("F07", "平台",
         "Python 的 `hash()` **每个进程加盐**，同样的字符串跨进程得到不同的值",
         "拿它当随机种子会让「同种子同输出」失效 —— 同一个主题两次跑出不同的调",
         "实测踩过：C 小调变成 G 小调。改用 `zlib.crc32` 修复",
         _v_hash_salted, FAST),

    Fact("F08", "MIDI",
         "`mido` 保存中文轨名会抛 `UnicodeEncodeError`（latin-1）——"
         "**构造 `MetaMessage` 时不抛，`save()` 才抛**",
         "防在构造那一步是防错了地方。项目用 `make_accompaniment.MIDI_NAME` "
         "把中文轨名映射成 ASCII",
         "实测。写这份清单时才发现我原来记的「构造时就崩」是错的",
         _v_mido_latin1, FAST),

    Fact("F09", "MIDI",
         "MIDI 的 tempo 存的是**整数微秒/四分音符**，所以多数 BPM 无法精确表示",
         "「读回来的 BPM 必须等于写进去的」这条判据必然失败。要改判累积漂移",
         "实测：76 BPM 存不下，判据改成累积漂移后是 0.061 ms",
         _v_midi_tempo_integer, FAST),

    Fact("F10", "对齐",
         "谱通量起音检测有 **+10~15 ms 的系统性偏置**（窗跨 23 ms + 音源自身 attack），"
         "必须用同一套事件的正弦渲染做自校准",
         "不校准就会让创作者去修一个**我的测量误差**。而且正负号我曾经推反过",
         "正负对照实验测出来的。符号是靠负对照定的，不是靠推理",
         _v_alignment_bias, SLOW),

    Fact("F11", "模型",
         "Mistral 免费档 **每分钟只有 4 次请求**（token 却有 25 万/分钟）",
         "「token 便宜就多跑几次」不成立。正确形态是次数少、每次塞满 —— "
         "平均每次可带 62,500 tokens",
         "实测：6 路并发立刻 2 个 429；稀疏探测确认是固定 60 秒窗口，"
         "remaining 走 3→2→1→0→3",
         _v_mistral_rate, NETWORK),

    Fact("F12", "作曲",
         "和弦进行必须**从歌词文件读**，不能从旋律反推",
         "三度关系的和弦共享两个音，反推准确率只有 35% —— 会把整首歌的和声搞错",
         "实测统计出来的",
         None, MANUAL),

    Fact("F13", "项目约定",
         "《潮声回响》的**轨 1 和轨 4 不能当参考**",
         "创作者手工编辑并删过音符，拿它们当范例会学到错的东西",
         "创作者明确交代",
         None, MANUAL),

    Fact("F14", "项目约定",
         "默认歌长 **2.5–5 分钟**；48 小节 @66 BPM = 2:54 是下限",
         "更短的产物不构成一首歌，创作者不会接受",
         "`specs/workflow.md` 里创作者定的",
         None, MANUAL),

    Fact("F15", "平台",
         "**不许用 `KMP_DUPLICATE_LIB_OK=TRUE`**",
         "官方提示原文说它可能导致崩溃或**静默产生错误结果** —— "
         "这个项目最怕的就是后者",
         "创作者明确要求",
         None, MANUAL),
]

BY_ID = {f.id: f for f in FACTS}


# =========================================================================
# 复验与渲染
# =========================================================================

def verify(costs: tuple[str, ...] = (FAST,)) -> list[Result]:
    """跑复验。默认只跑 fast —— slow 要渲染音频，network 要吃掉限流配额。"""
    out = []
    for f in FACTS:
        if f.check is None or f.cost not in costs:
            out.append(Result(f, None,
                              "不可自动复验，靠出处" if f.check is None
                              else f"未跑（{f.cost}）"))
            continue
        try:
            ok, detail = f.check()
        except Exception as e:               # 复验自己炸了也是信息
            ok, detail = False, f"复验出错：{type(e).__name__}: {e}"
        out.append(Result(f, ok, detail))
    return out


def summary(results: list[Result]) -> dict:
    return {
        "total": len(results),
        "verified": sum(1 for r in results if r.ok is True),
        "failed": sum(1 for r in results if r.ok is False),
        "unverifiable": sum(1 for r in results if r.fact.check is None),
        "skipped": sum(1 for r in results
                       if r.ok is None and r.fact.check is not None),
    }


def for_prompt() -> str:
    """给模型看的紧凑版。**这是这一项存在的理由** —— agent 读得到才算数。"""
    lines = ["以下是这个项目的硬约束。违反它们的方案一律不可行。", ""]
    for f in FACTS:
        lines.append(f"[{f.id}｜{f.domain}] {f.claim}")
        lines.append(f"    后果：{f.matters}")
    return "\n".join(lines)


# 复验结果落在这里，仪表盘读它。**不是真相来源** —— 它记的是
# 「上次复验时是什么结果」，所以必须带时间戳，让过期的结论一眼看出来是过期的。
REPORT_PATH = ROOT / ".agent" / "facts.json"


def save_report(results: list[Result], path: Path | None = None) -> Path:
    """把复验结果落盘。**仪表盘不许自己跑复验** —— 那就是前端在计算了。

    这条是被测试抓出来的：面板一开始每次渲染都现跑一遍，于是
    `test_渲染是纯函数` 挂了 —— mtime 碰撞率每次都不一样。
    而且监视模式下每秒可能重渲一次，那意味着每秒 spawn 三个子进程、
    写 200 次文件。
    """
    from . import safewrite as SW
    p = Path(path or REPORT_PATH)
    SW.write_json(p, {
        "ts": time.time(),
        "results": [{"id": r.fact.id, "ok": r.ok, "detail": r.detail}
                    for r in results],
    })
    return p


def load_report(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or REPORT_PATH).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def results_from_report(path: Path | None = None) -> list[Result]:
    """把落盘的报告还原成 Result。报告里没有的事实标成「没复验过」。"""
    d = load_report(path)
    by_id = {r["id"]: r for r in d.get("results", [])}
    out = []
    for f in FACTS:
        r = by_id.get(f.id)
        if r is None:
            out.append(Result(f, None, "还没复验过"))
        else:
            out.append(Result(f, r["ok"], r["detail"]))
    return out


def render_markdown(results: list[Result] | None = None) -> str:
    results = results or verify()
    s = summary(results)
    when = time.strftime("%Y-%m-%d %H:%M")
    out = [
        "# 环境事实清单",
        "",
        "| | |",
        "|---|---|",
        "| 生成 | **本文件由 `svagent.agent.facts` 生成，不要手改** |",
        f"| 复验于 | {when} |",
        f"| 统计 | 共 {s['total']} 条：{s['verified']} 条刚复验通过 · "
        f"{s['failed']} 条复验失败 · {s['skipped']} 条跳过 · "
        f"{s['unverifiable']} 条不可自动复验 |",
        "",
        "> **能自动复验的事实就必须自动复验。** 一份没人复查的约束清单，",
        "> 和只报 0 的检查是同一类东西。写这份清单的当天就抓到一条记错的"
        "（见 F08）。",
        "",
    ]
    mark = {True: "✅", False: "❌", None: "—"}
    for r in results:
        f = r.fact
        out += [
            f"## {f.id}　{f.claim}",
            "",
            f"- **领域**　{f.domain}",
            f"- **不知道会怎样**　{f.matters}",
            f"- **怎么学到的**　{f.learned}",
            f"- **复验**　{mark[r.ok]} {r.detail}"
            + ("" if f.check is None else f"（{f.cost}）"),
            "",
        ]
    return "\n".join(out)


def write_markdown(path: Path | None = None,
                   results: list[Result] | None = None) -> Path:
    from . import safewrite as SW
    p = Path(path or (ROOT / "specs" / "facts.md"))
    SW.write_text(p, render_markdown(results))
    return p
