# -*- coding: utf-8 -*-
"""提交前凭据扫描的测试。

## 这份测试有个特殊约束：它自己不能含真实形态的密钥

否则扫描器会把**它自己**拦住 —— 一提交测试文件就被自己的钩子挡下来。
所以所有测试输入都在**运行时拼出来**（`"api_key=" + "A" * 24`），
源码里不出现任何完整的密钥形态。

这不是绕过检查，是把「检查器与被检查内容」分开：
扫描器读的是 **diff 文本**，而 diff 里只会出现这些拼接表达式。

## 为什么要有这份测试

创作者 2026-08-25：这份 Mistral key **与他人共用、不能轮换**。
所以泄露的代价不是「换一个」，是几个人一起受影响。
而这一轮我已经失手过一次（`test_llm.py` 里的「假 key」抄了真 key），
靠的是提交前手工 grep 拦下的 —— **下次可能就没拦住**。

一个不会响的防线比没有防线更坏，所以每条规则都配反向测试。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scan_secrets as SS  # noqa: E402

A24 = "A" * 24                      # 运行时拼，源码里不成形态
PLUS = "+"


def d(*lines: str) -> str:
    """伪造一段 `git diff --cached` 的新增行。"""
    return "\n".join(PLUS + l for l in lines)


# =========================================================================
# 一、已知凭据（按哈希，不按明文）
# =========================================================================

def test_已知凭据按哈希命中(monkeypatch):
    """**扫描器里不存明文** —— 存哈希，比对时对候选串取哈希。"""
    secret = "Z9" + "k" * 30
    monkeypatch.setattr(SS, "KNOWN_HASHES", {SS.sha(secret): "测试凭据"})
    hits = SS.scan(d(f"KEY={secret}"))
    assert hits and "测试凭据" in hits[0][0]


def test_扫描器源码里没有明文凭据():
    """它自己要进仓库。存明文就等于把凭据发出去。"""
    src = (ROOT / "scripts" / "scan_secrets.py").read_text(encoding="utf-8")
    for h in SS.KNOWN_HASHES:
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert "KNOWN_HASHES" in src


# =========================================================================
# 二、打码：保护凭据的工具不许把凭据打出来
# =========================================================================

def test_命中的值必须被打码():
    """2026-08-25 实测：第一版把 key 原样打到终端上了。
    终端会进滚动缓冲、进截图、进对话记录。"""
    secret = "Q7" + "w" * 30
    out = SS.mask(f"+KEY={secret}", secret)
    assert secret not in out
    assert out.count("*") >= 20
    assert secret[:3] in out, "留前三位是为了让人认得出是哪一个"


def test_扫描结果里不许出现完整凭据(monkeypatch):
    secret = "Q7" + "w" * 30
    monkeypatch.setattr(SS, "KNOWN_HASHES", {SS.sha(secret): "测试凭据"})
    for _what, where in SS.scan(d(f"KEY={secret}")):
        assert secret not in where


def test_短值也打码不越界():
    assert SS.mask("+k=abc", "abc") == "+k=***"


# =========================================================================
# 三、通用形态会响
# =========================================================================

@pytest.mark.parametrize("line", [
    "api_key=" + A24,
    "API_KEY: " + A24,
    "secret = '" + A24 + "'",
    "token=" + A24,
    "password=" + A24,
    "Authorization: Bearer " + A24,
    "sk-" + "b" * 24,
    "ghp_" + "c" * 36,
])
def test_常见形态都要报(line):
    """**宁可多报** —— 假阳性花三秒，漏报是公开的凭据。"""
    assert SS.scan(d(line)), line


# =========================================================================
# 四、不许误报（否则钩子会被关掉，那才是真的没防线）
# =========================================================================

@pytest.mark.parametrize("line", [
    "MISTRAL_API_KEY=",
    "api_key=***",
    "api_key=your_key_here",
    "api_key=" + "x" * 30,
    "# 说明：key 只从环境变量读",
    "print('token 已过期')",
    "MISTRAL_API_KEY=FAKEKEY" + "0" * 25,
])
def test_占位符与说明文字不许报(line):
    """会天天误报的钩子，最后一定会被 --no-verify 绕过去。"""
    assert not SS.scan(d(line)), line


def test_只看新增行():
    """删掉一行含凭据的代码不该被拦 —— 那正是我们想要的方向。"""
    assert not SS.scan("-api_key=" + A24)


def test_干净的diff返回空():
    assert SS.scan(d("def foo():", "    return 42")) == []


# =========================================================================
# 五、钩子确实装上了
# =========================================================================

def test_钩子文件存在且指向扫描器():
    h = ROOT / ".githooks" / "pre-commit"
    assert h.exists(), "钩子没装。跑 git config core.hooksPath .githooks"
    assert "scan_secrets.py" in h.read_text(encoding="utf-8")
