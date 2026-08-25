"""仪表盘：把库里已经算好的东西渲染成一个自包含的 HTML。

## 一条硬规则：**前端只渲染，不计算**

这个模块里不许出现任何业务逻辑。它读 `state.inspect()` 的结果，排版，写文件。
所有数字必须来自 `svagent` 里已有的函数 —— **需要一个新数字，就去库里加，
不在这里算**。`ProjectState.n_done` 就是这么来的：进度条要「六步完成几步」，
于是加到库里，而不是在这里 `sum(...)`。

理由是 `audio.py` 那次的 bug 模式：两个入口各自实现同一段 STFT，
产出 0.340 和 0.360 两个数字，**两边都不报错**。仪表盘要是自己算一遍指标，
它和 `state.inspect()` 迟早对不上 —— 而且没有人会发现，
因为没有人会去比对一个「只是显示」的界面。

同一条规则将来同样约束薄 CLI（建造顺序第 9 项）。
库是唯一的业务逻辑所在地，前端只有两个：一个给眼睛，一个给手。

## 为什么是单个 HTML 文件而不是 Web 应用

见 `specs/testing-and-acceptance.md` 第 6 节。一句话：
**仪表盘是文件的视图，不是另一个真相来源。** 它没有自己的状态，
所以不可能和真实状态漂移；崩了重新生成就行；还能进 checkpoint，
将来可以回看「n06 那个节点当时长什么样」。

## 第一版只读

点节点回滚需要服务器。第一版所有操作仍然在对话里说
（「回到 n06」「这版不行」），仪表盘只负责让创作者**看懂**。

## 还没做的面板只列名字，不画假界面

`PENDING_PANELS` 里的四个面板对应建造顺序里还没做的项。**只列，不画** ——
画一个填着假数据的会话树，比没有会话树更糟。

用法:
    SVAGENT_SONG=xiaofeng python E:/sv-bridge/scripts/dashboard.py --open
"""
from __future__ import annotations

import html
import time
from pathlib import Path

from . import project as PJ
from .agent import facts as FA
from .agent import idem as ID
from .agent import safety as SF
from .agent import safewrite as SW
from .agent import state as ST
from .agent import tools as TL
from .agent import tree as TR

# 还没建造的面板：名字 · 属于第几项 · 一句话说明。**只列，不画。**
PENDING_PANELS = [
    ("本轮", 5, "诊断 → 假设 → 动作 → 度量前后对比"),
    ("指标", 7, "八项检查 + 三个新指标的当前值与阈值"),
]

WHO_CLS = {ST.BY_AGENT: "agent", ST.BY_CREATOR: "creator", ST.BY_BOTH: "both"}
MARK_CLS = {"✓": "done", "…": "wait", "✗": "block"}

CSS = """
:root {
  --bg: #faf9f7; --card: #ffffff; --line: #e6e2dc; --line2: #d4cec5;
  --fg: #1f1d1b; --fg2: #5c574f; --fg3: #8a837a;
  --done: #2f7d4f; --done-bg: #e8f3ec;
  --wait: #8a837a; --wait-bg: #f1efec;
  --block: #b3341f; --block-bg: #fbeae6;
  --accent: #1f5fa8; --accent-bg: #e8f0fa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #171614; --card: #201f1c; --line: #33312d; --line2: #45423c;
    --fg: #eeece8; --fg2: #a9a49b; --fg3: #7d776e;
    --done: #6cc38d; --done-bg: #1c2f23;
    --wait: #8a837a; --wait-bg: #262421;
    --block: #e8836e; --block-bg: #33201c;
    --accent: #7fb0e8; --accent-bg: #1a2634;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 28px 20px 60px; background: var(--bg); color: var(--fg);
  font: 400 15px/1.65 -apple-system, "Segoe UI", "Microsoft YaHei",
        "PingFang SC", "Hiragino Sans GB", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 880px; margin: 0 auto; }
h1 { margin: 0 0 4px; font-size: 22px; font-weight: 500; letter-spacing: .2px; }
h2 { margin: 0 0 12px; font-size: 15px; font-weight: 500; color: var(--fg2); }
.sub { color: var(--fg2); font-size: 13px; }
.mono { font-family: "Cascadia Mono", Consolas, "SF Mono", monospace; }

.top { display: flex; align-items: flex-start; gap: 16px;
       flex-wrap: wrap; margin-bottom: 20px; }
.top .grow { flex: 1 1 340px; min-width: 0; }
.top .side { text-align: right; font-size: 12px; color: var(--fg3);
             flex: 0 0 auto; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px;
        font-size: 12px; border: 1px solid var(--line2); color: var(--fg2);
        vertical-align: 2px; margin-left: 8px; }

.bar { display: flex; gap: 4px; margin: 14px 0 6px; }
.seg { flex: 1; height: 6px; border-radius: 3px; background: var(--wait-bg);
       border: 1px solid var(--line); }
.seg.done { background: var(--done); border-color: var(--done); }
.seg.next { background: var(--accent); border-color: var(--accent); }

.card { background: var(--card); border: 1px solid var(--line);
        border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; }
.card.next { border-color: var(--accent); background: var(--accent-bg); }

.hd { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.mark { font-size: 15px; width: 18px; display: inline-block; text-align: center; }
.mark.done { color: var(--done); }
.mark.wait { color: var(--wait); }
.mark.block { color: var(--block); }
.nm { font-weight: 500; }
.who { font-size: 12px; padding: 1px 7px; border-radius: 9px;
       border: 1px solid transparent; }
.who.agent   { color: var(--accent); background: var(--accent-bg);
               border-color: var(--accent); }
.who.creator { color: var(--block); background: var(--block-bg);
               border-color: var(--block); }
.who.both    { color: var(--fg2); background: var(--wait-bg);
               border-color: var(--line2); }

ul.ev { margin: 8px 0 0; padding: 0; list-style: none; }
ul.ev li { font-size: 13px; color: var(--fg2); padding: 1px 0 1px 20px;
           position: relative; word-break: break-all; }
ul.ev li::before { content: "·"; position: absolute; left: 8px;
                   color: var(--fg3); }
ul.ev li.blk { color: var(--block); }
ul.ev li.blk::before { content: "⛔"; left: 0; font-size: 11px; }
/* 只是在排队等上游，不是出了问题。用 blocked_by_self 区分（库给的）。 */
ul.ev li.waitblk { color: var(--fg3); }
ul.ev li.waitblk::before { content: "⏳"; left: 0; font-size: 11px; }

.cmd { margin-top: 10px; display: flex; align-items: flex-start; gap: 8px;
       background: var(--bg); border: 1px solid var(--line);
       border-radius: 6px; padding: 8px 10px; }
.cmd code { flex: 1; font-size: 12.5px; white-space: pre-wrap;
            word-break: break-all; color: var(--fg2);
            font-family: "Cascadia Mono", Consolas, "SF Mono", monospace; }
.copy { flex: 0 0 auto; font: inherit; font-size: 12px; cursor: pointer;
        padding: 2px 9px; border-radius: 5px; color: var(--fg2);
        background: var(--card); border: 1px solid var(--line2); }
.copy:hover { color: var(--fg); border-color: var(--fg3); }

.pending { margin-top: 26px; border: 1px dashed var(--line2);
           border-radius: 8px; padding: 12px 16px; }
.pending .row { display: flex; gap: 10px; align-items: baseline;
                font-size: 13px; color: var(--fg3); padding: 2px 0; }
.pending .row b { font-weight: 500; color: var(--fg2); min-width: 58px; }

.foot { margin-top: 24px; font-size: 12px; color: var(--fg3);
        line-height: 1.8; }
label.auto { cursor: pointer; user-select: none; }

.lamp { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
        padding: 6px 0; border-top: 1px solid var(--line); font-size: 13px; }
.lamp:first-of-type { border-top: 0; }
.dot { flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%;
       background: var(--wait); }
.lamp.on  .dot { background: var(--done); }
.lamp.off .dot { background: var(--block); }
.lamp.unknown .dot { background: transparent; border: 1px solid var(--fg3); }
.lnm { font-weight: 500; min-width: 74px; color: var(--fg); }
.ldt code, .lhint code { font-size: 12px; padding: 0 3px;
        border-radius: 3px; background: var(--wait-bg); }
.ldt b, .lhint b { font-weight: 500; color: var(--fg); }
.ldt { color: var(--fg2); }
.lamp.off .ldt { color: var(--block); }
b.here { font-weight: 500; color: var(--accent); margin-left: 10px; }
.lhint { flex: 1 1 100%; padding-left: 93px; color: var(--fg3);
         word-break: break-word;
         font-size: 12.5px; }
.fl { display: flex; gap: 8px; font-size: 12.5px; padding: 2px 0 2px 93px;
      color: var(--fg3); }
.fl b { font-weight: 400; color: var(--fg2); min-width: 150px; }
.fl.ext b, .fl.ext span { color: var(--block); }

.live { display: inline-block; padding: 1px 8px; border-radius: 10px;
        font-size: 12px; border: 1px solid transparent; margin-bottom: 4px; }
.live.on  { color: var(--done);  background: var(--done-bg);
            border-color: var(--done); }
.live.off { color: var(--block); background: var(--block-bg);
            border-color: var(--block); }
"""

JS = """
(function () {
  var KEY = 'svagent-dash-autorefresh';
  var box = document.getElementById('auto');
  var on = true;
  try { on = localStorage.getItem(KEY) !== '0'; } catch (e) {}
  box.checked = on;
  var timer = null;
  function arm() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (box.checked) timer = setTimeout(function () { location.reload(); }, MS);
  }
  box.addEventListener('change', function () {
    try { localStorage.setItem(KEY, box.checked ? '1' : '0'); } catch (e) {}
    arm();
  });
  arm();

  document.querySelectorAll('.copy').forEach(function (b) {
    b.addEventListener('click', function () {
      var txt = b.parentNode.querySelector('code').textContent;
      var done = function () {
        b.textContent = '已复制';
        setTimeout(function () { b.textContent = '复制'; }, 1200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(done, fallback);
      } else { fallback(); }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = txt; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch (e) {}
        document.body.removeChild(ta);
      }
    });
  });
})();
"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _md(s) -> str:
    """把 `**粗体**` 和 反引号代码 渲染成 HTML。

    **先转义再替换** —— 顺序反了就等于把库里的文本当 HTML 执行。
    纯排版，不是计算：这里不改变任何值，只决定它长什么样。
    """
    import re
    out = _e(s)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    return re.sub(r"`(.+?)`", r'<code class="mono">\1</code>', out)


def _cmd_block(cmd: str) -> str:
    return (f'<div class="cmd"><code>{_e(cmd)}</code>'
            f'<button class="copy" type="button">复制</button></div>')


def _step_card(s: ST.Step, is_next: bool) -> str:
    out = [f'<div class="card{" next" if is_next else ""}">']
    out.append('<div class="hd">'
               f'<span class="mark {MARK_CLS.get(s.mark, "wait")}">{s.mark}</span>'
               f'<span class="nm">步骤 {s.n}　{_e(s.name)}</span>'
               f'<span class="who {WHO_CLS.get(s.who, "both")}">{_e(s.who)}</span>'
               '</div>')
    if s.evidence or s.blockers:
        out.append('<ul class="ev">')
        for e in s.evidence:
            out.append(f'<li>{_e(e)}</li>')
        bcls = "blk" if s.blocked_by_self else "waitblk"
        for b in s.blockers:
            out.append(f'<li class="{bcls}">{_e(b)}</li>')
        out.append('</ul>')
    if is_next and s.command:
        out.append(_cmd_block(s.command))
    out.append('</div>')
    return "".join(out)


def _safety_panel(sf: SF.SafetyState) -> str:
    """安全面板（第 1 项）。**每盏灯的颜色和文字都是 safety.inspect() 给的。**"""
    rows = []
    for l in sf.lamps:
        rows.append(
            f'<div class="lamp {l.color}"><span class="dot"></span>'
            f'<span class="lnm">{_e(l.name)}</span>'
            f'<span class="ldt">{_md(l.detail)}</span>'
            + (f'<span class="lhint">→ {_md(l.hint)}</span>' if l.hint else "")
            + "</div>")
        # 哈希那一项要逐文件摊开 —— 只说「1 个文件被改了」还得去猜是哪个
        if l.name == "哈希校验":
            for p, v in sf.files:
                cls = "fl ext" if v == SW.EXTERNAL else "fl"
                rows.append(f'<div class="{cls}"><b>{_e(p.name)}</b>'
                            f'<span>{_e(SF.VERDICT_ZH[v])}</span></div>')
    return (f'<h2>安全　第 1 项</h2><div class="card">{"".join(rows)}</div>')


def _highlight(nd, depth: int) -> str:
    """改动高亮（第 6 项）：哪些小节被改了，改了几个音符。

    只有做过局部修改的节点才有这一行 —— 整首重生成没有「哪几小节」可言。
    """
    m = nd.metrics_after or {}
    if not m.get("sections"):
        return ""
    bars = m.get("bars") or {}
    bits = []
    for name in m["sections"]:
        b = bars.get(name)
        bits.append(f"{name} 小节 {b[0]}–{b[1]}" if b else name)
    src = f"取自 {m['from_node']}　" if m.get("from_node") else ""
    return (f'<span class="lhint" style="padding-left:{depth * 22 + 93}px">'
            f'✎ {src}{_e("　".join(bits))}　'
            f'改了 {m.get("n_replaced", "?")} 个音符，'
            f'其余 {m.get("n_kept", "?")} 个逐字段不变</span>')


def _tree_panel(t: TR.Tree) -> str:
    """会话树（第 3 项）—— 架构文档说这是创作者最常看的一屏。

    缩进直接用节点深度，不画连线：HTML 里画树线要么用图片要么用一堆边框，
    而这一屏的价值在于**看懂哪条分支是哪条、现在在哪、哪些被否了**，
    不在于线画得漂不漂亮。
    """
    try:
        nodes = t.nodes()
    except TR.TreeError as e:
        return (f'<h2>会话树　第 3 项</h2><div class="card"><div class="lamp off">'
                f'<span class="dot"></span><span class="ldt">'
                f'日志读不了：{_e(e)}</span></div></div>')
    if not nodes:
        return ('<h2>会话树　第 3 项</h2><div class="card"><div class="lamp '
                'unknown"><span class="dot"></span><span class="ldt">'
                '还没有任何节点　—　跑 tree.py --commit "标签" 存第一个'
                '</span></div></div>')

    head = t.head()
    depth: dict[str, int] = {}
    rows = []

    def walk(nd, d):
        depth[nd.id] = d
        cls = {TR.ACCEPTED: "on", TR.REJECTED: "off"}.get(nd.verdict, "unknown")
        rows.append(
            f'<div class="lamp {cls}" style="padding-left:{d * 22}px">'
            f'<span class="dot"></span>'
            f'<span class="lnm mono">{_e(nd.id)}</span>'
            f'<span class="ldt">{_e(nd.label)}　{_e(nd.when)}'
            + (f'　「{_e(nd.verdict_note)}」' if nd.verdict_note else "")
            + ('<b class="here">← 你在这</b>' if nd.id == head else "")
            + "</span>"
            + _highlight(nd, d)
            + "</div>")
        for k in t.children(nd.id):
            walk(k, d + 1)

    for r in t.roots():
        walk(r, 0)
    dirty = ('<div class="lamp off"><span class="dot"></span>'
             '<span class="lnm">有未提交的改动</span><span class="ldt">'
             '文件与当前节点不一致 —— 切走之前会自动存一个节点</span></div>'
             if t.is_dirty() else "")
    bad = len(t.rejected())
    foot = (f'<div class="fl" style="padding-left:0"><span>{len(nodes)} 个节点'
            f'　{bad} 个被否决（否决记忆的原料）</span></div>')
    return (f'<h2>会话树　第 3 项</h2><div class="card">'
            f'{dirty}{"".join(rows)}{foot}</div>')


def _facts_panel() -> str:
    """约束清单（第 4 项）。**能自动复验的当场复验，不能的老实标出来。**

    **这里不跑复验**，只读 `scripts/facts.py` 落下的报告。

    面板一开始是现跑的，被 `test_渲染是纯函数` 抓了 —— 复验结果本身会变
    （mtime 碰撞率每次不同），渲染就不再是状态的纯函数。而且监视模式下
    每秒重渲一次意味着每秒 spawn 三个子进程。**前端只渲染，不计算。**
    """
    rs = FA.results_from_report()
    s = FA.summary(rs)
    d = FA.load_report()
    when = (time.strftime("%m-%d %H:%M", time.localtime(d["ts"]))
            if d.get("ts") else "从未")
    rows = []
    for r in rs:
        rows.append(
            f'<div class="lamp {r.color}"><span class="dot"></span>'
            f'<span class="lnm mono">{_e(r.fact.id)}</span>'
            f'<span class="ldt">{_md(r.fact.claim)}</span>'
            f'<span class="lhint">{_md(r.fact.matters)}'
            f'　—　{_e(r.detail)}</span></div>')
    head = (f'{s["total"]} 条　复验于 {when}　{s["verified"]} 条通过 · '
            f'{s["failed"]} 条失败 · {s["skipped"]} 条跳过（slow/network）· '
            f'{s["unverifiable"]} 条只有出处')
    return (f'<h2>约束清单　第 4 项</h2><div class="card">'
            f'<div class="fl" style="padding-left:0"><span>{head}</span></div>'
            f'{"".join(rows)}</div>')


def _actions_panel() -> str:
    """动作表（第 2 项）：每个动作一行，标幂等 ✓/✗。

    **表头必须先说这张表是什么时候测的。** 代码改过之后那些 ✓ 就不再算数，
    而一张不肯承认自己过期的表，比没有表更坏 —— 和仪表盘那次是同一条教训。
    """
    rep = ID.load_report()
    if not rep:
        head = ('<div class="lamp unknown"><span class="dot"></span>'
                '<span class="lnm">幂等未测</span><span class="ldt">'
                '跑 pytest tests/test_idempotence.py</span></div>')
    else:
        stale = ID.report_is_stale(rep)
        when = time.strftime("%m-%d %H:%M",
                             time.localtime(max(v["ts"] for v in rep.values())))
        head = (f'<div class="lamp {"off" if stale else "on"}">'
                f'<span class="dot"></span>'
                f'<span class="lnm">幂等测于 {when}</span>'
                f'<span class="ldt">'
                + ("代码在这之后改过 —— 幂等那一列已经不算数，重跑 "
                   "pytest tests/test_idempotence.py" if stale
                   else "幂等这一列是最新代码的结果")
                + "</span></div>")
    # 第 5 项之后这张表以**动作池**为主键，幂等报告只是其中一列。
    # 幂等测的是步骤脚本，动作是它们的封装 —— 一个动作没有对应的幂等记录
    # 不代表它不幂等，所以那一列缺失时标「—」，不标红。
    badge = {TL.READY: ("on", "可用"), TL.PARTIAL: ("unknown", "部分"),
             TL.NEEDS_MODEL: ("unknown", "待接模型")}
    rows = []
    for act in TL.ACTIONS:
        cls, word = badge[act.status]
        idem = rep.get(act.script) if act.script else None
        bits = [word]
        bits.append("只读" if not act.writes else "写")
        bits.append("钩子 " + ("、".join(act.hooks) if act.hooks else "无"))
        if idem is not None:
            bits.append("幂等 " + ("✓" if idem["ok"] else "✗"))
        rows.append(
            f'<div class="lamp {cls}"><span class="dot"></span>'
            f'<span class="lnm mono">{_e(act.name)}</span>'
            f'<span class="ldt">{_md(act.desc)}　·　{_e(" · ".join(bits))}</span>'
            + (f'<span class="lhint">{_md(act.note)}</span>' if act.note else "")
            + "</div>")
    n_ready = sum(1 for a in TL.ACTIONS if a.status == TL.READY)
    lead = (f'<div class="fl" style="padding-left:0"><span>'
            f'{len(TL.ACTIONS)} 个动作　{n_ready} 个完全可用　'
            f'导给模型 {len(TL.to_mistral_tools())} 个</span></div>')
    return (f'<h2>动作表　第 5 项</h2><div class="card">'
            f'{lead}{head}{"".join(rows)}</div>')


def render(st: ST.ProjectState, *, refresh_s: int = 5,
           live: bool = False, sf: SF.SafetyState | None = None) -> str:
    """把一次观察渲染成完整 HTML。**这里只排版，不算任何东西。**

    `live` 决定页面上那枚徽章说什么。**它必须诚实** ——
    静态快照就说自己是静态快照，不许让人以为看的是实时状态。
    """
    p = st.proj
    nx = st.next_step
    d = p.duration_s
    now = time.strftime("%H:%M:%S")

    segs = []
    for s in st.steps:
        cls = "done" if s.done else ("next" if nx and s.n == nx.n else "")
        segs.append(f'<div class="seg {cls}" title="步骤 {s.n} {_e(s.name)}"></div>')

    if nx is None:
        headline = "六步全部完成"
    else:
        headline = f"下一步：步骤 {nx.n}　{_e(nx.name)}　（{_e(nx.who)}）"

    pend = "".join(
        f'<div class="row"><b>第 {n} 项</b>{_e(name)} 面板　—　{_e(desc)}</div>'
        for name, n, desc in PENDING_PANELS)

    body = [
        '<div class="wrap">',
        '<div class="top">',
        '<div class="grow">',
        f'<h1>{_e(p.title)}<span class="pill mono">{_e(p.slug)}</span></h1>',
        f'<div class="sub">{p.bpm:.0f} BPM · {p.n_bars} 小节 · '
        f'{int(d // 60)}:{int(d % 60):02d}</div>',
        '</div>',
        '<div class="side">',
        ('<span class="live on">监视中 · 文件一变就重算</span><br>' if live
         else '<span class="live off">静态快照 · 不会自己更新</span><br>'),
        f'生成于 {now}<br>',
        '<label class="auto"><input type="checkbox" id="auto"> '
        f'每 {refresh_s} 秒自动刷新</label>',
        '</div></div>',
        f'<div class="bar">{"".join(segs)}</div>',
        f'<h2>状态　{st.n_done}/{len(st.steps)} 步　·　{headline}</h2>',
    ]
    for s in st.steps:
        body.append(_step_card(s, is_next=bool(nx and s.n == nx.n)))

    body.append(_tree_panel(TR.Tree(st.proj)))
    if sf is not None:
        body.append(_safety_panel(sf))
    body.append(_actions_panel())
    body.append(_facts_panel())

    body += [
        '<div class="pending">',
        '<div class="row" style="color:var(--fg2)">还没建造的面板'
        '（只列名字，不画假界面）</div>',
        pend,
        '</div>',
        '<div class="foot">',
        f'数据来自 <span class="mono">svagent.agent.state.inspect()</span>，'
        f'渲染器 <span class="mono">svagent/dashboard.py</span>。<br>',
        '本页<b>只渲染，不计算</b> —— 数字都是库算好的，'
        '所以它不会和库算出两个不同的值。<br>'
        '但它是<b>快照</b>：没人重新生成它就会过期 —— '
        '「不会算错」和「不会过期」是两件事，别混。<br>',
        f'工程 <span class="mono">{_e(p.svp)}</span><br>',
        f'歌词 <span class="mono">{_e(p.lyrics)}</span>',
        '</div></div>',
    ]

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_e(p.title)}　SV-Agent 仪表盘</title>'
        f'<style>{CSS}</style></head><body>'
        + "".join(body)
        + f'<script>var MS={int(refresh_s) * 1000};{JS}</script>'
        '</body></html>\n'
    )


def write(st: ST.ProjectState | None = None, *, path: Path | None = None,
          refresh_s: int = 5, live: bool = False) -> Path:
    """观察一次并写出 HTML。→ 写到的路径。"""
    st = st or ST.inspect()
    path = path or (PJ.SONGS / st.proj.slug / "dashboard.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    # 页面自己走原子写。一个渲染到一半的仪表盘正好会在创作者刷新的那一刻
    # 显示半截 HTML —— 这一项防的就是这个。
    SW.write_text(path, render(st, refresh_s=refresh_s, live=live,
                               sf=SF.inspect(st.proj)))
    return path


def sources_stamp(proj: PJ.SongProject) -> dict[str, str | None]:
    """源文件指纹。**来源列表由 `proj.sources` 给，哈希算法由 `safewrite` 给。**

    这个函数自己什么都不算 —— 它只是把两个库函数拼起来。
    两个入口各自实现同一段哈希，迟早算出两个不同的值而且两边都不报错
    （`audio.py` 的 0.340 / 0.360 就是这么来的）。
    """
    return {str(f): SW.fingerprint(f) for f in proj.sources}


def watch(slug: str | None = None, *, path: Path | None = None,
          refresh_s: int = 5, poll_s: float = 1.0, minutes: float = 20.0,
          log=print) -> None:
    """盯住源文件，一变就重新生成。Ctrl-C 退出。

    ## 为什么这个不是锦上添花

    `dashboard.html` 是**快照**，不是视图。创作者手改歌词、或者在 SynthV 里
    动了工程之后，浏览器再怎么刷新，读到的都是同一份旧 HTML ——
    页面会理直气壮地显示一个过期的数字，**而且不报错**。

    这是本项目第三次踩同一类坑：`audio.py` 的 0.340 / 0.360、
    `fl_ping` 的假阴性，都是「显示层安静地说了假话」。前两次的代价是
    我让创作者去修一个不存在的问题。

    所以监视模式是「状态从文件现算」这句话在**界面上**成立的前提。
    没有它，那句话只在生成的那一瞬间为真。

    ## 为什么一定要有 `minutes`

    这是个常驻进程，从聊天里的运行按钮启动就会永远转圈 —— 那里没有 Ctrl-C。
    所以它**必须自己会收工**：默认盯 20 分钟，到点自动退出并把页面标回
    「静态快照」。一个永远不结束、又不肯承认自己已经不再更新的界面，
    比没有界面更坏。
    """
    slug = slug or PJ.current().slug
    deadline = time.monotonic() + minutes * 60.0
    last: dict | None = None
    log(f"监视 {slug} 的 {len(PJ.load(slug).sources)} 个源文件"
        f"　{minutes:.0f} 分钟后自动收工，或 Ctrl-C")
    while time.monotonic() < deadline:
        proj = PJ.load(slug)          # 每轮重读，project.json 改了也跟得上
        cur = sources_stamp(proj)
        if cur != last:
            p = write(ST.inspect(proj), path=path, refresh_s=refresh_s,
                      live=True)
            log(f"{time.strftime('%H:%M:%S')}  重新生成  {p}")
            last = cur
        time.sleep(poll_s)
    # 到点了：页面必须改口说自己是静态的，否则它会顶着绿徽章慢慢过期
    write(ST.inspect(PJ.load(slug)), path=path, refresh_s=refresh_s, live=False)
    log(f"{minutes:.0f} 分钟到，停止监视。页面已标回「静态快照」。")
