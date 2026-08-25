# -*- coding: utf-8 -*-
"""建造顺序第 9 项：库边界的验收测试。

## 验收标准的原话

    同一操作经库调用与经 CLI 调用结果相同

所以每个观察都比两次：一次 `Session.to_json(...)`，一次
`sv.py <cmd> --json` 的 stdout。**比的必须是同一个字典**，
不是「看起来差不多」—— 后者正是这一层要防的漂移。

## 为什么这一层值得单独测

在它之前，六个入口各自 `sys.path.insert` + 直接 import 那七八个模块。
每加一个前端就要把拼装重来一遍，而重来一遍就是「两个实现」的温床 ——
这个项目已经栽过五次（`audio.py` 的 STFT、`state` 的重叠、
对齐计算、乐句构造、动作名模糊匹配）。

第 10 项的 Mistral 循环就是下一个前端。它必须只能通过 `Session` 说话。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import session as S                # noqa: E402
from svagent.agent import diagnose as DG        # noqa: E402

WHATS = ("state", "safety", "metrics", "facts", "tree", "actions", "checks")


def _cli(*args, song: str = "xiaofeng"):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", SVAGENT_SONG=song)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sv.py"),
                        "--song", song, *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=str(ROOT), timeout=900)
    assert r.returncode == 0, f"{args} 退出码 {r.returncode}\n{r.stdout[-800:]}"
    return r.stdout


# =========================================================================
# 一、验收判据：库 == CLI
# =========================================================================

@pytest.mark.parametrize("what", WHATS)
def test_同一操作库与CLI结果相同(what):
    """**验收标准点名的那一条。** 逐字段比字典，不是比人读的文本。"""
    lib = S.Session("xiaofeng").to_json(what)
    cli = json.loads(_cli(what, "--json"))
    assert cli == lib, f"{what}：CLI 与库对不上"


def test_每个观察都能序列化():
    """不能序列化就没法比 —— 而没法比的等价性等于没有等价性。"""
    s = S.Session("xiaofeng")
    for what in WHATS:
        json.dumps(s.to_json(what), ensure_ascii=False, default=str)


def test_不认识的观察要报出可用清单():
    with pytest.raises(ValueError) as e:
        S.Session("xiaofeng").to_json("随便什么")
    for w in WHATS:
        assert w in str(e.value)


# =========================================================================
# 二、Session 不缓存
# =========================================================================

def test_Session不缓存观察结果(tmp_path, monkeypatch):
    """会缓存的 Session 就是又一个会漂移的真相源。"""
    s = S.Session("xiaofeng")
    a = s.to_json("state")
    b = s.to_json("state")
    assert a == b                       # 文件没变，两次一样
    # 换掉文件时间之外的东西不好造，所以直接验它每次真的去读：
    calls = []
    real = S.ST.inspect
    monkeypatch.setattr(S.ST, "inspect", lambda p: (calls.append(1), real(p))[1])
    s.state()
    s.state()
    assert len(calls) == 2, "第二次没有重新观察 —— 说明缓存了"


# =========================================================================
# 三、前端只准通过 Session 说话
# =========================================================================

def test_库暴露了下一个前端要的全部东西():
    """第 10 项的 Mistral 循环需要这些。少一样它就会自己拼一份。"""
    s = S.Session("xiaofeng")
    for name in ("state", "safety", "metrics", "facts", "checks",
                 "tree", "actions", "tools_for_model", "act",
                 "diagnose", "plan", "trial", "commit", "checkout",
                 "verdict", "dashboard", "to_json"):
        assert hasattr(s, name), f"Session 少了 {name}"


def test_给模型的tools来自库而不是前端拼():
    """两个前端各拼一份 schema，迟早出现「CLI 能调、模型调不通」。"""
    from svagent.agent import tools as TL
    tools = S.Session("xiaofeng").tools_for_model()
    assert tools and all(t["type"] == "function" for t in tools)
    names = {t["function"]["name"] for t in tools}
    assert "gen_melody" in names
    # 不写死具体名字 —— 第 10 项把 gen_lyrics 从「待接模型」转成可用之后，
    # 写死名字的断言就过期了。断言**规则**：没接上的一个都不许导出。
    for a in TL.ACTIONS:
        assert (a.name in names) == (a.status != TL.NEEDS_MODEL), a.name


def test_诊断的序列化也在库里():
    """`sv.py why --json` 与将来的模型前端要看到同一份结构。"""
    s = S.Session("xiaofeng")
    d = s.diagnose("总觉得哪儿不对")
    j = S.diagnosis_json(d)
    assert set(j) == {"complaint", "intent", "ask", "confidence",
                      "hypotheses"}
    assert json.dumps(j, ensure_ascii=False)


def test_诊断经CLI与经库结果相同():
    lib = S.diagnosis_json(S.Session("xiaofeng").diagnose("副歌不够爆"))
    cli = json.loads(_cli("why", "副歌不够爆", "--json"))
    for k in ("complaint", "intent", "ask", "confidence", "hypotheses"):
        assert cli[k] == lib[k], k


# =========================================================================
# 四、CLI 保持薄
# =========================================================================

def test_CLI里不许有业务逻辑():
    """判据是可数的：`sv.py` 里不该出现算数、循环里的条件判断这类东西。

    用一个粗但有效的代理指标 —— **它不许 import 除 Session 之外的
    任何 agent 计算模块来做计算**。真要新数字，去库里加。
    """
    src = (ROOT / "scripts" / "sv.py").read_text(encoding="utf-8")
    for banned in ("def compute", "def calc", "statistics", "numpy",
                   "json.loads(proj", "read_text(encoding=\"utf-8-sig\")"):
        assert banned not in src, f"sv.py 里出现了 {banned}"
    assert "from svagent import session as S" in src


def test_未知子命令要退出而不是崩():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sv.py"),
                        "没有这个命令"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env,
                       cwd=str(ROOT), timeout=120)
    assert r.returncode != 0
    assert "invalid choice" in (r.stdout + r.stderr).lower()
