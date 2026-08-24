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
from .agent import state as ST

# 还没建造的面板：名字 · 属于第几项 · 一句话说明。**只列，不画。**
PENDING_PANELS = [
    ("安全", 1, "原子写 · 哈希校验 · 可中断 · 超时 · 幂等，各一个灯"),
    ("会话树", 3, "分支 · HEAD · 每个节点的裁决与度量"),
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


def render(st: ST.ProjectState, *, refresh_s: int = 5) -> str:
    """把一次观察渲染成完整 HTML。**这里只排版，不算任何东西。**"""
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
        f'生成于 {now}<br>',
        '<label class="auto"><input type="checkbox" id="auto"> '
        f'每 {refresh_s} 秒自动刷新</label>',
        '</div></div>',
        f'<div class="bar">{"".join(segs)}</div>',
        f'<h2>状态　{st.n_done}/{len(st.steps)} 步　·　{headline}</h2>',
    ]
    for s in st.steps:
        body.append(_step_card(s, is_next=bool(nx and s.n == nx.n)))

    body += [
        '<div class="pending">',
        '<div class="row" style="color:var(--fg2)">还没建造的面板'
        '（只列名字，不画假界面）</div>',
        pend,
        '</div>',
        '<div class="foot">',
        f'数据来自 <span class="mono">svagent.agent.state.inspect()</span>，'
        f'渲染器 <span class="mono">svagent/dashboard.py</span>。<br>',
        '本页<b>只渲染，不计算</b> —— 所有数字都是库算好的，'
        '所以它不可能和真实状态对不上。<br>',
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
          refresh_s: int = 5) -> Path:
    """观察一次并写出 HTML。→ 写到的路径。"""
    st = st or ST.inspect()
    path = path or (PJ.SONGS / st.proj.slug / "dashboard.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(st, refresh_s=refresh_s), encoding="utf-8")
    return path
