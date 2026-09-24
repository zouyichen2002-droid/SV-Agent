# -*- coding: utf-8 -*-
"""可交互的本地桌面程序 —— 第 5 个前端。

## 为什么不借上游的 Electron 壳

上游 `synthv-toolbox` 的桌面壳带着 Rust C-ABI DLL、插件双层授权、
多宿主兼容。那些解决的是**「分发给第三方」**的问题 ——
本项目是单用户单工作流，引进来就是为架构而架构
（`specs/status-2026-09-16.md` §5.4 的判断，这里沿用）。

代价对比很清楚：借壳要接 Node/Electron 整套构建工具链；
自己写只要标准库 `http.server`，**零新依赖**。

## 它凭什么能这么薄

因为第 9 项库边界（`session.py`）早就为这一刻建好了 ——
原话是「**让换 orchestrator 变成换前端**」。这个文件里
没有一行业务逻辑，全部是 `Session` 方法的转发。

## 硬规则：前端只渲染，不计算

与仪表盘同一条。需要一个新数字就去库里加。
两个入口各算一遍，迟早算出两个不同的值**而且两边都不报错** ——
这个项目为此栽过好几次。

所以：指标读 `Session.metrics()`，状态读 `Session.state()`，
动作表读 `Session.actions()`。**这里一个都不重算**，
唯一的例外是真歌分位 —— 那是对 `out/pop909_survey.json` 的**查表**，
不是计算，而且语料不在就返回 `None`，不编数。

## 三件必须显式呈现的事

1. **`status`** —— 动作池里 `adjust_spec` / `reorchestrate` 是 `partial`，
   `needs_model` 档要 LLM。点下去才发现跑不了，比灰着更糟。
2. **必填参数** —— 14 个动作里 8 个有必填参数，表单按 `schema` 渲染。
   留空的可选参数**不传**，让库里的默认值生效。
3. **`changed_files` 与 `node`** —— 动作跑完要能立刻看见「改了哪些文件、
   退回到哪个节点」。不然「可交互」就成了不可撤销。

## 写动作要显式确认 + 全局串行

动作池里一多半会写盘。网页上误点一下就改了工程，是这个项目最不该出的事。
所以 `writes=True` 必须带 `confirm: true`。

服务器是多线程的（读请求不互相堵），但**所有动作共用一把锁** ——
并发跑两个写动作会把工程写坏，而且多半不报错。

## 只听 127.0.0.1

不是为了防外网，是为了**不把「能改创作者工程」的接口暴露到局域网**。
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import project as PJ
from . import reference as RF
from .session import Session

ROOT = Path(__file__).resolve().parents[2]

_ACT_LOCK = threading.Lock()          # 写动作全局串行


# =========================================================================
# 真歌分位：唯一的「非 Session 数据」，而且只是查表
# =========================================================================

def _real_line_ranges() -> list[float]:
    """593 首真歌的每句极差，排好序。

    **筛选和读取都在 `reference.py`**，这里只是取一次结果。
    第一版这段自己读 json、自己筛，那就是第二个实现 —— 两边算同一件事，
    迟早算出两个不同的数而且两边都不报错。
    """
    return RF.values_of(RF.sane_rows(RF.load_survey()), "contour_line")


_REAL = _real_line_ranges()
REAL_N = len(_REAL)          # 入口脚本要报这个数，所以是公开的


def percentile_of(value: float | None) -> float | None:
    """这个值排在真歌的第几百分位。**没有语料返回 None**，不是 0。"""
    return RF.percentile_in(_REAL, value)


# =========================================================================
# 取数：全部转发给 Session
# =========================================================================

def songs() -> list[dict]:
    out = []
    for d in sorted(PJ.SONGS.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if not (d / "project.json").exists():
            continue
        try:
            p = PJ.load(d.name)
            out.append({"slug": p.slug, "title": p.title, "bpm": p.bpm})
        except Exception as e:
            # 读不了也列出来 —— 静默跳过会让「少了一首」查不出原因
            out.append({"slug": d.name,
                        "title": f"{d.name}（读不了：{type(e).__name__}）",
                        "bpm": None})
    return out


def snapshot(slug: str | None = None) -> dict:
    s = Session(slug) if slug else Session()
    p = s.proj
    ms = s.to_json("metrics")["metrics"]
    for m in ms:                                   # 只附一个查表来的分位
        if m["name"] == "contour_line":
            m["percentile"] = percentile_of(m["value"])

    findings, checks_err = [], ""
    try:
        findings = [{"severity": f.severity, "where": f.where,
                     "detail": f.detail} for f in s.checks()]
    except Exception as e:
        checks_err = f"{type(e).__name__}: {e}"

    acts = [{"name": a.name, "desc": a.desc, "note": a.note,
             "writes": a.writes, "status": a.status,
             "schema": a.schema, "hooks": list(a.hooks)}
            for a in s.actions()]

    return {
        "slug": p.slug, "title": p.title, "bpm": p.bpm,
        "bars": p.n_bars, "duration_s": round(p.duration_s, 1),
        "state": s.to_json("state"), "safety": s.to_json("safety"),
        "metrics": ms, "findings": findings, "checks_error": checks_err,
        "actions": acts, "tree": s.to_json("tree"),
        "real_song_n": len(_REAL),
    }


def run_action(slug: str, name: str, params: dict, confirm: bool) -> dict:
    """跑一个动作。**写动作必须 confirm，且全局串行。**"""
    s = Session(slug)
    act = next((a for a in s.actions() if a.name == name), None)
    if act is None:
        return {"ok": False, "error": f"没有叫 {name!r} 的动作"}
    if act.writes and not confirm:
        return {"ok": False, "need_confirm": True,
                "error": f"「{name}」会写文件，需要确认"}
    if not _ACT_LOCK.acquire(timeout=0.1):
        return {"ok": False,
                "error": "另一个动作正在跑。并发写会把工程写坏，所以这里串行。"}
    try:
        r = s.act(name, params or {})
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    except SystemExit as e:
        # `BaseException`，上面接不住。不归一化的话会打死处理线程。
        return {"ok": False, "error": f"库里退出了：{e}"}
    finally:
        _ACT_LOCK.release()

    return {
        "ok": bool(r.ok),
        "error": r.error or "",
        "elapsed_s": round(r.elapsed_s or 0.0, 2),
        "node": r.node or "",
        "changed_files": [str(x) for x in (r.changed_files or [])],
        "delta": r.delta or {},
        "extra": r.extra or {},
        "hooks": [{"name": h.name, "ok": h.ok, "detail": h.detail,
                   "numbers": h.numbers} for h in (r.hooks or [])],
    }


def new_song(title: str, theme: str, bpm) -> dict:
    """开一首新歌。转发给 `project.new_song` —— 这里不判断什么，只转达。"""
    try:
        p = PJ.new_song(title, theme=theme or "",
                        bpm=float(bpm) if bpm not in (None, "") else None)
    except Exception as e:
        return {"ok": False, "error": f"{e}"}
    bpms = RF.values_of(RF.sane_rows(RF.load_survey()), "bpm")
    return {"ok": True, "slug": p.slug, "title": p.title, "bpm": p.bpm,
            "bpm_percentile": RF.percentile_in(bpms, p.bpm),
            "dir": str(PJ.SONGS / p.slug),
            "lyrics": str((PJ.SONGS / p.slug / "lyrics.txt").resolve())}


def ask(slug: str, text: str, allow_writes: bool, rounds: int) -> dict:
    """说一句话。→ `Session.ask()`，也就是第 10 项那个循环。

    **默认 `allow_writes=False`。** 按钮那条路每次写盘都会弹框确认；
    聊天框没有这一步，随手一句就可能触发写动作。不设闸等于把确认闸绕过去。
    真要让它自己动手，他得在界面上明确勾一下。
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "说点什么"}
    if not _ACT_LOCK.acquire(timeout=0.1):
        return {"ok": False, "error": "另一个动作正在跑，等它完。"}
    try:
        r = Session(slug).ask(text, auto_rounds=max(1, min(rounds, 4)),
                              allow_writes=allow_writes)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    except SystemExit as e:
        # `BaseException`，上面接不住。不归一化的话会打死处理线程。
        return {"ok": False, "error": f"库里退出了：{e}"}
    finally:
        _ACT_LOCK.release()

    return {
        "ok": True,
        "text": r.final_text or "",
        "exit_reason": r.exit_reason,
        "n_actions": r.n_actions,
        # 用量只有计数，**没有 key** —— 这个仓库是公开的
        "usage": {"calls": r.usage.calls,
                  "prompt_tokens": r.usage.prompt_tokens,
                  "completion_tokens": r.usage.completion_tokens},
        "steps": [{"kind": st.kind, "text": st.text, "action": st.action,
                   "params": st.params, "error": st.error,
                   "blocked": bool((st.result or {}).get("blocked")),
                   "ok": (st.result or {}).get("ok")}
                  for st in r.steps],
    }


# =========================================================================
# HTTP
# =========================================================================

class _Handler(BaseHTTPRequestHandler):
    server_version = "SVAgent/1.0"

    def log_message(self, *a):                     # 不往 stderr 刷日志
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False,
                                    default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        head, _, qs = self.path.partition("?")
        q = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
        try:
            if head == "/":
                self._send(200, PAGE.encode("utf-8"),
                           "text/html; charset=utf-8")
            elif head == "/api/songs":
                self._json(songs())
            elif head == "/api/snapshot":
                self._json(snapshot(unquote(q.get("slug", "")) or None))
            else:
                self._json({"error": f"没有 {head}"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        except SystemExit as e:
            # **库里会 `raise SystemExit`**（`project.load` 找不到歌、
            # `step3.read_lead` 没有主旋律轨）。它继承 `BaseException`，
            # 上面那句 `except Exception` 接不住 —— 于是处理线程直接死，
            # **连响应都不发**，创作者只看到「✗ Failed to fetch」。
            #
            # 2026-09-18 撞上的：一首刚写完词还没生成旋律的新歌，
            # 整个页面打不开（HTTP 000）。
            #
            # **服务器必须永远回一句话。** 这条不接 `BaseException` ——
            # 那会连 Ctrl-C 一起吞掉。
            self._json({"error": f"库里退出了：{e}"}, 500)

    def do_POST(self):
        head = self.path.partition("?")[0]
        if head not in ("/api/act", "/api/ask", "/api/new"):
            return self._json({"error": "没有这个接口"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            b = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json({"ok": False, "error": f"请求不是 JSON：{e}"}, 400)
        try:
            if head == "/api/act":
                self._json(run_action(b.get("slug", ""), b.get("name", ""),
                                      b.get("params") or {},
                                      bool(b.get("confirm"))))
            elif head == "/api/new":
                self._json(new_song(b.get("title", ""), b.get("theme", ""),
                                    b.get("bpm")))
            else:
                # **默认不给写权限** —— 要它自己动手得显式传 true
                self._json(ask(b.get("slug", ""), b.get("text", ""),
                               bool(b.get("allow_writes")),
                               int(b.get("rounds") or 1)))
        except Exception as e:
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        except SystemExit as e:
            # 同 do_GET：库里的 `raise SystemExit` 会穿过 `except Exception`
            self._json({"ok": False, "error": f"库里退出了：{e}"}, 500)


def serve(port: int = 8765, open_browser: bool = True) -> ThreadingHTTPServer:
    """只听 127.0.0.1 —— 不把「能改工程」的接口暴露到局域网。"""
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    return srv


PAGE = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SV-Agent</title>
<style>
:root{--bg:#13151a;--card:#1b1e25;--line:#2a2f3a;--fg:#e6e8ec;--dim:#868e9e;
      --ok:#4ec9a0;--bad:#e0605e;--warn:#e0b25e;--acc:#6aa3f0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}
header{padding:12px 20px;border-bottom:1px solid var(--line);position:sticky;
       top:0;background:var(--bg);z-index:9;display:flex;align-items:center;
       gap:12px;flex-wrap:wrap}
h1{font-size:15px;font-weight:600;margin:0;letter-spacing:.5px}
select,button,input,textarea{background:var(--card);color:var(--fg);
  border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit}
button{cursor:pointer}
button:hover:not(:disabled){border-color:var(--acc)}
button:disabled{opacity:.4;cursor:not-allowed}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
     gap:12px;padding:14px 20px 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
      padding:13px 15px;min-width:0}
.card h2{font-size:12px;font-weight:600;margin:0 0 9px;color:var(--dim);
         letter-spacing:.8px}
.row{display:flex;justify-content:space-between;gap:10px;padding:2px 0;
     align-items:baseline}
.dim{color:var(--dim)} .ok{color:var(--ok)} .bad{color:var(--bad)}
.warn{color:var(--warn)} .sm{font-size:12px}
.step{padding:4px 0;border-bottom:1px solid var(--line)}
.step:last-child{border:0}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.acts button{font-size:12px;padding:5px 9px}
.ag{display:inline-flex}
.ag button:first-child{border-top-right-radius:0;border-bottom-right-radius:0}
.ag button.g{border-top-left-radius:0;border-bottom-left-radius:0;
  border-left:0;padding:5px 7px;color:var(--dim)}
.w{border-color:#4d3a24}
.p{border-color:#40405a}
pre{background:#0e1015;border:1px solid var(--line);border-radius:8px;
    padding:10px 12px;overflow:auto;max-height:300px;font-size:12px;
    margin:8px 0 0;white-space:pre-wrap;word-break:break-word;
    font-family:Consolas,monospace;line-height:1.55}
.bar{height:5px;background:#232733;border-radius:3px;overflow:hidden;
     margin:2px 0 5px}
.bar>i{display:block;height:100%;background:var(--acc)}
.full{grid-column:1/-1}
.chatbox{display:flex;gap:7px}
.chatbox input{flex:1;min-width:0}
#form{display:none;border:1px solid var(--line);border-radius:8px;
      padding:11px 13px;margin-bottom:8px;background:#161920}
#form .f{display:flex;gap:8px;align-items:center;margin:5px 0}
#form label{width:150px;flex:none;font-size:12px}
#form input[type=text],#form input[type=number],#form textarea{flex:1;min-width:0}
#form textarea{font-family:Consolas,monospace;font-size:12px;min-height:52px}
.req{color:var(--warn)}
.tag{font-size:10px;padding:1px 5px;border-radius:3px;border:1px solid var(--line);
     color:var(--dim);margin-left:5px}
</style></head><body>
<header>
  <h1>SV-Agent</h1>
  <select id="song"></select>
  <button id="refresh">刷新</button>
  <button id="newb" onclick="newSong()">＋ 新歌</button>
  <span id="meta" class="dim sm"></span>
</header>
<main>
  <div class="card"><h2>六步</h2><div id="steps"></div></div>
  <div class="card"><h2>安全五盏灯</h2><div id="safety"></div></div>
  <div class="card"><h2>指标　对照真歌</h2><div id="metrics"></div></div>
  <div class="card"><h2>八项检查</h2><div id="checks"></div></div>
  <div class="card"><h2>会话树　可回退</h2><div id="tree"></div></div>
  <div class="card full"><h2>说一句话</h2>
    <div class="chatbox">
      <input id="say" placeholder="比如：这首歌现在卡在哪？副歌为什么不够爆？下一步该做什么？"
             onkeydown="if(event.key==='Enter')send()">
      <button id="sendb" onclick="send()">发</button>
    </div>
    <label class="sm dim" style="display:block;margin-top:7px">
      <input type="checkbox" id="aw" style="vertical-align:-2px">
      让它自己动手改文件　<span class="warn">不勾的话它只能看和说，要改得你自己点按钮</span>
    </label>
    <pre id="chat">还没说过话。</pre>
  </div>
  <div class="card full"><h2>动作池</h2>
    <div class="sm dim" style="margin-bottom:7px">
      点名字直接跑（可选参数走默认值），点 ⚙ 改参数。<br>
      橙边 = 会写文件（点了要二次确认）　紫边 = 能力只做了一半
      灰 = 要模型跑不了　名字后的橙数字 = 必填参数个数</div>
    <div class="acts" id="acts"></div>
    <div id="form"></div>
    <pre id="out">点一个动作。有必填参数的会先弹表单，会写盘的会先问一遍。</pre>
  </div>
</main>
<script>
const $=s=>document.querySelector(s); let SLUG=null,SNAP=null,PEND=null;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// 指标是浮点，原样打出来是 0.5186363573048267 —— 三位够了，再多是噪音
const fmt=v=>typeof v==='number'?(Number.isInteger(v)?v:+v.toFixed(3)):v;

async function loadSongs(){
  const list=await (await fetch('/api/songs')).json();
  $('#song').innerHTML=list.map(s=>
    `<option value="${esc(s.slug)}">${esc(s.title)}${s.bpm?'　'+s.bpm+' BPM':''}</option>`).join('');
  SLUG=list[0]?list[0].slug:null;
  if(SLUG) load(); else $('#out').textContent='songs/ 下没有工程。';
}
async function load(){
  SLUG=$('#song').value||SLUG;
  const d=await (await fetch('/api/snapshot?slug='+encodeURIComponent(SLUG))).json();
  if(d.error){$('#out').textContent='✗ '+d.error;return;}
  SNAP=d; render();
}
function render(){
  const s=SNAP;
  $('#meta').textContent=`${s.bpm} BPM · ${s.bars} 小节 · ${s.duration_s}s · 第 ${s.state.n_done}/6 步`;

  $('#steps').innerHTML=s.state.steps.map(x=>{
    const m=x.done?'<span class="ok">✓</span>'
      :(x.blockers.length?'<span class="bad">✗</span>':'<span class="dim">·</span>');
    const b=x.blockers.length
      ?`<div class="dim sm" style="padding-left:16px">⛔ ${esc(x.blockers[0])}</div>`:'';
    const w=x.waits_for?`<div class="warn sm" style="padding-left:16px">⏸ 等 ${esc(x.waits_for)}</div>`:'';
    return `<div class="step">${m} ${x.n}. ${esc(x.name)}<span class="tag">${esc(x.who)}</span>${b}${w}</div>`;
  }).join('');

  $('#safety').innerHTML=s.safety.lamps.map(l=>{
    const c=l.ok===true?'ok':(l.ok===false?'bad':'dim');
    const m=l.ok===true?'✓':(l.ok===false?'✗':'·');
    return `<div class="row"><span class="${c}">${m} ${esc(l.name)}</span>`+
           `<span class="dim sm" style="text-align:right">${esc(l.detail)}</span></div>`;
  }).join('');

  $('#metrics').innerHTML=s.metrics.map(m=>{
    if(m.value===null) return `<div class="row"><span class="dim">· ${esc(m.label)}</span>`+
      `<span class="dim sm">还没有依据</span></div>`;
    const c=m.ok?'ok':'bad', mk=m.ok?'✓':'✗';
    let ex='',bar='';
    if(m.percentile!=null){
      const p=m.percentile, cc=p>=30?'ok':(p>=10?'warn':'bad');
      ex=`<div class="${cc} sm" style="text-align:right">真歌第 ${p.toFixed(0)} 百分位</div>`;
      bar=`<div class="bar"><i style="width:${Math.min(100,p)}%"></i></div>`;
    }
    return `<div class="row"><span class="${c}">${mk} ${esc(m.label)}</span>`+
      `<span style="text-align:right">${fmt(m.value)}`+
      `<span class="dim sm"> 门槛 ${fmt(m.threshold)}</span>${ex}</span></div>${bar}`;
  }).join('') + (s.real_song_n
    ? `<div class="dim sm" style="margin-top:7px">分位来自 ${s.real_song_n} 首真歌（POP909）</div>`
    : `<div class="warn sm" style="margin-top:7px">没有真歌语料，分位不可用 —— 不是 0，是没有依据</div>`);

  if(s.checks_error){
    $('#checks').innerHTML=`<div class="bad sm">跑不了：${esc(s.checks_error)}</div>`;
  }else if(!s.findings.length){
    $('#checks').innerHTML='<div class="ok">✓ 0 finding</div>';
  }else{
    $('#checks').innerHTML=s.findings.map(f=>
      `<div class="row"><span class="${f.severity==='error'?'bad':'warn'}">`+
      `${f.severity==='error'?'✗':'!'} ${esc(f.where)}</span></div>`+
      `<div class="dim sm" style="padding-left:16px;margin-bottom:4px">${esc(f.detail)}</div>`).join('');
  }

  const t=s.tree;
  $('#tree').innerHTML=
    `<div class="row"><span class="dim">HEAD</span><span>${esc(t.head||'—')}</span></div>`+
    `<div class="row"><span class="dim">未提交改动</span>`+
    `<span class="${t.dirty?'warn':'dim'}">${t.dirty?'有':'没有'}</span></div>`+
    (t.nodes.length?t.nodes.slice(-7).reverse().map(n=>
      `<div class="row"><button class="sm" style="padding:2px 7px"
        onclick="pre('revert',{node_id:'${esc(n.id)}'})">↩ ${esc(n.id)}</button>`+
      `<span class="dim sm" style="text-align:right">${esc(String(n.label).slice(0,30))}</span></div>`
    ).join(''):'<div class="dim sm">还没有节点。跑一个写动作就会建。</div>');

  $('#acts').innerHTML=s.actions.map(a=>{
    const req=(a.schema.required||[]).length;
    const dis=a.status==='needs_model';
    const cls=dis?'':(a.status==='partial'?'p':(a.writes?'w':''));
    const tip=[a.desc,a.note,a.hooks.length?'钩子：'+a.hooks.join(' '):'']
      .filter(Boolean).join('\n');
    const nopt=Object.keys(a.schema.properties||{}).length;
    // 点名字 = 直接跑（有必填才弹表单）；点齿轮 = 改参数。
    // 主流程六步的参数**全是可选的**，逼它们过一遍表单就把一键变成两步了
    const gear=(!dis&&nopt)?`<button class="${cls} g" ${dis?'disabled':''}
      title="改参数" onclick="pre('${esc(a.name)}')">⚙</button>`:'';
    return `<span class="ag"><button class="${cls}" ${dis?'disabled':''}
      title="${esc(tip)}" onclick="hit('${esc(a.name)}')">${esc(a.name)}`+
      `${req?' <span class="req">·'+req+'</span>':''}</button>${gear}</span>`;
  }).join('');
  $('#form').style.display='none';
}

// 点名字：有必填参数才弹表单，否则直接跑（可选参数走库里的默认值）
function hit(name){
  const a=SNAP.actions.find(x=>x.name===name); if(!a) return;
  if((a.schema.required||[]).length) return pre(name);
  go(name,{},a.writes);
}

// 点齿轮 / 树里的回退：出参数表单
function pre(name,prefill){
  const a=SNAP.actions.find(x=>x.name===name); if(!a) return;
  const props=a.schema.properties||{}, req=a.schema.required||[];
  if(!Object.keys(props).length) return go(name,{},a.writes);
  PEND=name;
  const f=$('#form');
  f.innerHTML=`<div style="margin-bottom:7px"><b>${esc(name)}</b>`+
    `<span class="dim sm">　${esc(a.desc)}</span></div>`+
    Object.entries(props).map(([k,v])=>{
      const r=req.includes(k), t=v.type||'any';
      const val=(prefill&&prefill[k]!=null)?esc(prefill[k]):'';
      let inp;
      if(t==='boolean') inp=`<input type="checkbox" id="p_${k}">`;
      else if(t==='object') inp=`<textarea id="p_${k}" placeholder='JSON，如 {"0": 3}'>${val}</textarea>`;
      else if(t==='integer'||t==='number') inp=`<input type="number" step="any" id="p_${k}" value="${val}">`;
      else if(t==='array') inp=`<input type="text" id="p_${k}" value="${val}" placeholder="逗号分隔">`;
      else inp=`<input type="text" id="p_${k}" value="${val}">`;
      return `<div class="f"><label>${esc(k)}${r?' <span class="req">*</span>':''}`+
        `<span class="dim"> ${t}</span></label>${inp}</div>`+
        (v.description?`<div class="dim sm" style="margin:-3px 0 5px 158px">${esc(v.description)}</div>`:'');
    }).join('')+
    `<div style="margin-top:9px"><button onclick="submit()">跑</button>
     <button onclick="document.getElementById('form').style.display='none'">取消</button>
     <span class="dim sm">　<span class="req">*</span> 必填，其余留空用默认值</span></div>`;
  f.style.display='block'; f.scrollIntoView({block:'nearest'});
}

function submit(){
  const a=SNAP.actions.find(x=>x.name===PEND);
  const props=a.schema.properties||{}, req=a.schema.required||[], p={};
  for(const [k,v] of Object.entries(props)){
    const el=document.getElementById('p_'+k); if(!el) continue;
    const t=v.type||'any';
    if(t==='boolean'){ if(el.checked) p[k]=true; continue; }
    const raw=el.value.trim();
    if(!raw){ if(req.includes(k)){ $('#out').textContent=`✗ ${k} 是必填的`; return; } continue; }
    if(t==='integer') p[k]=parseInt(raw,10);
    else if(t==='number') p[k]=parseFloat(raw);
    else if(t==='array') p[k]=raw.split(',').map(x=>x.trim()).filter(Boolean);
    else if(t==='object'){ try{ p[k]=JSON.parse(raw); }
      catch(e){ $('#out').textContent=`✗ ${k} 不是合法 JSON：${e.message}`; return; } }
    else if(t==='any'){ try{ p[k]=JSON.parse(raw); }catch(e){ p[k]=raw; } }
    else p[k]=raw;
  }
  $('#form').style.display='none';
  go(PEND,p,a.writes);
}

async function go(name,params,writes){
  if(writes && !confirm(
    `「${name}」会写文件，工程会被改动。\n会先建一个可回退的会话树节点。\n\n跑吗？`)) return;
  $('#out').textContent=`跑 ${name} …`;
  document.querySelectorAll('#acts button').forEach(b=>b.disabled=true);
  try{
    const d=await (await fetch('/api/act',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({slug:SLUG,name,params,confirm:!!writes})})).json();
    const L=[(d.ok?'✓ ':'✗ ')+name+(d.elapsed_s?`　${d.elapsed_s}s`:'')];
    if(d.error) L.push('  '+d.error);
    if(d.node) L.push('  会话树节点：'+d.node+'　（要退回就点树里那一行）');
    if(d.hooks&&d.hooks.length){ L.push('  钩子：');
      d.hooks.forEach(h=>L.push(`    ${h.ok===true?'✓':(h.ok===false?'✗':'·')} `+
        `${h.name}　${h.detail}`+
        ((h.numbers&&Object.keys(h.numbers).length)?'　'+JSON.stringify(h.numbers):''))); }
    if(d.changed_files&&d.changed_files.length){ L.push('  改了：');
      d.changed_files.forEach(f=>L.push('    '+f)); }
    if(d.delta&&Object.keys(d.delta).length) L.push('  指标变化：'+JSON.stringify(d.delta,null,1));
    if(d.extra&&Object.keys(d.extra).length) L.push('  产出：'+JSON.stringify(d.extra,null,1));
    $('#out').textContent=L.join('\n');
  }catch(e){ $('#out').textContent='✗ '+e; }
  document.querySelectorAll('#acts button').forEach(b=>b.disabled=false);
  load();
}
async function newSong(){
  const title=prompt('歌名（中文就行）'); if(!title) return;
  const theme=prompt('一句话主题。越具体越好写 ——\n'+
    '「末班地铁上给自己写的信」比「孤独」好写十倍。')||'';
  const bpm=prompt('速度 BPM。\n留空 = 按 593 首真歌的分布取一个'+
    '（四分位距，大概 67–83）')||'';
  $('#chat').textContent='建…';
  const d=await (await fetch('/api/new',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({title,theme,bpm})})).json();
  if(!d.ok){ $('#chat').textContent='✗ '+d.error; return; }
  const p=d.bpm_percentile;
  $('#chat').textContent=
    `✓ 建好了《${d.title}》\n`+
    `  目录名　${d.slug}\n`+
    `  速度　　${d.bpm} BPM`+(p!=null?`（真歌第 ${p.toFixed(0)} 百分位）`:'')+'\n'+
    `  歌词　　${d.lyrics}\n\n`+
    `下一步：把歌词写进上面那个文件，然后回来点 gen_melody。\n`+
    `不想自己写词就在下面说一句，或者点 gen_lyrics。`;
  await loadSongs();
  $('#song').value=d.slug; load();
}

async function send(){
  const el=$('#say'), text=el.value.trim(); if(!text) return;
  const aw=$('#aw').checked;
  if(aw && !confirm('勾了「让它自己动手」，它可以不再问你就改文件。\n\n确定？')){
    $('#aw').checked=false; return;
  }
  el.disabled=true; $('#sendb').disabled=true;
  $('#chat').textContent='你：'+text+'\n\n想…';
  try{
    const d=await (await fetch('/api/ask',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({slug:SLUG,text,allow_writes:aw,rounds:1})})).json();
    const L=['你：'+text,''];
    if(!d.ok){ L.push('✗ '+d.error); }
    else{
      (d.steps||[]).forEach(st=>{
        if(st.kind==='tool'){
          const m=st.blocked?'⛔':(st.ok?'✓':'✗');
          L.push(`  ${m} 它调了 ${st.action}`+
            (st.params&&Object.keys(st.params).length?' '+JSON.stringify(st.params):''));
          if(st.error) L.push('     '+st.error);
        }
      });
      if(d.steps&&d.steps.some(s=>s.kind==='tool')) L.push('');
      L.push(d.text||'（它没说话）');
      L.push('');
      L.push(`— ${d.exit_reason}　动作 ${d.n_actions} 个　`+
             `模型 ${d.usage.calls} 次 / ${d.usage.prompt_tokens+d.usage.completion_tokens} token`);
    }
    $('#chat').textContent=L.join('\n');
  }catch(e){ $('#chat').textContent='✗ '+e; }
  el.disabled=false; $('#sendb').disabled=false; el.value=''; el.focus();
  load();
}
$('#song').onchange=load; $('#refresh').onclick=load; loadSongs();
</script></body></html>
"""
