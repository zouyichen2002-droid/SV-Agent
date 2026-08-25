# -*- coding: utf-8 -*-
"""建造顺序第 10 项之二：**tool-calling 循环** —— 引擎。

## 内循环与 coding agent 的标准循环一字不差（架构 §2.5）

    while True:
        ① 装配上下文    系统提示 + 环境事实 + 六步状态 + 指标 + 上次 tool_result
        ② 模型输出      文本 或 tool_call
        ③ 没有 tool_call → 退出，交回创作者
        ④ 执行工具      Session.act（内含 校验哈希 → 备份 → 原子写 → 记节点）
        ⑤ 写后钩子      Runner 里已经跑了
        ⑥ tool_result 回灌 → 回到 ①

外循环是创作者：听 → 说一句 → 新一轮。

## 唯一的不同在 ⑥：`tool_result` 带可程序化的度量

六个对照项目的 `tool_result` 都只说「执行成功 / 失败」。我们的带 `delta`
与钩子结果，所以**模型不需要判断正确性** —— 它只看数字决定下一步。
这是整个架构的支点：模型负责品味，L1 负责正确。

## 四个退出条件，一个都不能少

    1  模型不再调工具      自然结束
    2  达到 auto_rounds     默认 1 —— 变好只有耳朵能判，多跑一轮是在
                            没有奖励信号的方向上多走一步
    3  超预算              max_total_actions / budget_s
    4  stop 文件出现        创作者叫停

3 和 4 缺失就是「卡死」的直接来源。它们在第 1 项就建好了，这里只是接上。

## 请求次数是硬约束

实测每分钟 4 次（§4.5）。所以循环的每一轮**只发一次请求**，
上下文一次塞满 —— 不做「先问一句再问一句」那种多跳。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .. import llm as LM
from .. import session as SS
from . import budget as BD
from . import facts as FA
from . import metrics as MT
from . import tools as TL

SYSTEM = """你是 SV-Agent：虚拟歌手歌曲创作的执行层。创作者用一句话说需求，你调工具去做。

**你不判断正确性。** 八项检查、指标、写后钩子判。你看 tool_result 里的
数字决定下一步 —— 不要凭感觉说「这样应该更好」。

**一次只改一处。** 改两处就无法归因，创作者说「好听了」时你不知道是哪一处起了作用。

**不确定就停下来问，不要猜。** 说「我不确定」是允许的，而且经常是对的。

每分钟只有 4 次请求，所以：一轮只做一件事，把话说完整，不要来回试探。

回复用中文，简短，直接说结论和数字。"""


@dataclass
class Step:
    """循环里的一步。**每一步都要留痕，包括模型只说了话没调工具。**"""
    n: int
    kind: str                      # "text" | "tool"
    text: str = ""
    action: str = ""
    params: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class LoopResult:
    steps: list[Step] = field(default_factory=list)
    exit_reason: str = ""
    final_text: str = ""
    usage: LM.Usage = field(default_factory=LM.Usage)
    n_actions: int = 0

    def report(self) -> str:
        out = []
        for s in self.steps:
            if s.kind == "text":
                out.append(f"  [{s.n}] 说：{s.text[:200]}")
            else:
                head = f"  [{s.n}] 调 {s.action} " \
                       f"{json.dumps(s.params, ensure_ascii=False)}"
                out.append(head + ("　✗ " + s.error[:120] if s.error else ""))
                d = (s.result or {}).get("delta") or {}
                for k, v in list(d.items())[:6]:
                    out.append(f"        {k}　{v.get('before')} → {v.get('after')}")
                for h in (s.result or {}).get("hooks", []):
                    out.append(f"        {'✓' if h['ok'] else '✗'} 钩子 "
                               f"{h['name']}　{h.get('detail', '')}")
        out.append(f"\n  退出：{self.exit_reason}")
        out.append(LM.Usage.report(self.usage))
        return "\n".join(out)


def context(s: SS.Session, ask: str) -> list[dict]:
    """① 装配上下文。**一次塞满** —— 每分钟只有 4 次请求。

    环境事实进系统提示，这是第 4 项的兑现：
    **agent 读不到就等于没有。**
    """
    st = s.state()
    ms = s.metrics()
    lines = [f"当前项目：{s.proj.title}（{s.proj.slug}）"
             f"　{s.proj.bpm:.0f} BPM · {s.proj.n_bars} 小节",
             f"六步状态：{st.n_done}/6"]
    for x in st.steps:
        lines.append(f"  {x.mark} 步骤{x.n} {x.name}（{x.who}）"
                     + (f"　阻塞：{'；'.join(x.blockers)}" if x.blockers else ""))
    lines.append("\n指标（阈值是按已验收的歌校准的，达标就别乱动）：")
    for m in ms:
        mark = {True: "✓", False: "✗", None: "·"}[m.ok]
        lines.append(f"  {mark} {m.label} {m.show()}　{m.detail}")

    return [
        {"role": "system", "content": SYSTEM + "\n\n" + FA.for_prompt()},
        {"role": "user", "content": "\n".join(lines) + f"\n\n创作者说：{ask}"},
    ]


def run(s: SS.Session, ask: str, *, client: LM.Mistral | None = None,
        auto_rounds: int = 1, max_actions: int = 8,
        budget: BD.Budget | None = None) -> LoopResult:
    """跑一轮。→ `LoopResult`。**不抛异常** —— 退出原因都写在结果里。"""
    client = client or LM.Mistral()
    bud = budget or s.budget
    res = LoopResult(usage=client.usage)
    msgs = context(s, ask)
    tools = s.tools_for_model()
    n = 0

    while True:
        # ---- 退出条件 3 与 4：**在发请求之前就查** -------------------
        try:
            bud.check()
        except BD.BudgetExhausted as e:
            res.exit_reason = str(e)
            break
        if res.n_actions >= max_actions:
            res.exit_reason = f"动作数达到上限 {max_actions}"
            break

        # ---- ② 模型输出 ---------------------------------------------
        n += 1
        try:
            out = client.chat(msgs, tools=tools)
        except LM.LLMError as e:
            res.exit_reason = f"模型调用失败：{e}"
            break
        msg = out["message"]
        calls = msg.get("tool_calls") or []

        # ---- ③ 没有 tool_call → 交回创作者 ---------------------------
        if not calls:
            text = (msg.get("content") or "").strip()
            res.steps.append(Step(n, "text", text=text))
            res.final_text = text
            res.exit_reason = "模型不再调工具（自然结束）"
            break

        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": calls})

        for c in calls:
            fn = c.get("function") or {}
            name = fn.get("name", "")
            try:
                params = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                params = {}
            step = Step(n, "tool", action=name, params=params)

            # ---- ④⑤ 执行 + 钩子（都在 Session.act 里）-----------------
            try:
                r = s.act(name, params)
                step.result = r.to_json()
                step.error = r.error
                res.n_actions += 1
            except TL.ToolError as e:
                step.error = str(e)
                step.result = {"ok": False, "error": str(e)}
            except BD.BudgetExhausted as e:
                step.error = str(e)
                step.result = {"ok": False, "error": str(e)}
                res.steps.append(step)
                res.exit_reason = str(e)
                return _finish(res, client)
            res.steps.append(step)

            # ---- ⑥ tool_result 回灌（**带数字，不只是成功失败**）-------
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""),
                         "name": name,
                         "content": json.dumps(step.result, ensure_ascii=False,
                                               default=str)[:6000]})

        # ---- 退出条件 2 -------------------------------------------
        if n >= auto_rounds + 1:
            res.exit_reason = f"达到 auto_rounds={auto_rounds}，交回创作者"
            break

    return _finish(res, client)


def _finish(res: LoopResult, client: LM.Mistral) -> LoopResult:
    res.usage = client.usage
    try:
        LM.save_usage(client.usage, client.model)
    except Exception:
        pass                       # 落盘失败不该让一整轮白跑
    return res
