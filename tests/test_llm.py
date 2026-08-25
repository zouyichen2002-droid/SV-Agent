# -*- coding: utf-8 -*-
"""建造顺序第 10 项：Mistral 客户端与 tool-calling 循环的验收测试。

## 这份测试不打真接口

**每分钟只有 4 次配额。** 让测试去烧它，既慢又会让创作者手上正在跑的
调用一起失败。所以全部用注入的假传输，只有一条 `--live` 冒烟测试
默认跳过。

这不是偷懒 —— 要测的东西（退避时机、限流值从头读、脱敏、循环的四个
退出条件）没有一条需要真网络。真网络只能验「接口还在」，
而那一条已经由 `facts.py` 的 F11 复验守着。

## 最要紧的一条：脱敏

仓库是公开的。报错信息最容易顺手打进日志，所以 `redact()` 有反向测试 ——
拿真格式的 key 试一遍，断言它出不来。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

from svagent import llm as LM                   # noqa: E402
from svagent.agent import loop as LP            # noqa: E402

# 32 字符，与真 key 同格式，**纯虚构**。
# 第一版这里直接抄了真 key —— 想着「要同格式才测得准」，结果就是把凭据
# 写进了一个要进 git 的文件。提交前的密钥体检抓到了。
# **测试文件也是要进 git 的文件。**
FAKE_KEY = "FAKEKEY000000000000000000000000"


def _ok(content="好了", tool_calls=None, usage=None):
    msg = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return (200, {"x-ratelimit-limit-req-minute": "4",
                  "x-ratelimit-remaining-req-minute": "3"},
            {"choices": [{"message": msg,
                          "finish_reason": "tool_calls" if tool_calls
                          else "stop"}],
             "usage": usage or {"prompt_tokens": 100,
                                "completion_tokens": 20}})


def _429():
    return (429, {"x-ratelimit-limit-req-minute": "4",
                  "x-ratelimit-remaining-req-minute": "0"},
            {"message": "Rate limit exceeded"})


class Fake:
    """假传输。**记下每次请求，好断言上下文塞了什么。**"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def __call__(self, body):
        self.seen.append(body)
        return self.responses.pop(0) if self.responses else _ok()


def _client(*responses, **kw):
    slept = []
    c = LM.Mistral(key=FAKE_KEY, transport=Fake(*responses), **kw)
    c.sleep = slept.append
    c.slept = slept
    return c


# =========================================================================
# 一、脱敏（仓库是公开的）
# =========================================================================

def test_脱敏会把key擦掉():
    for text in (f"Bearer {FAKE_KEY} 出错了",
                 f"MISTRAL_API_KEY={FAKE_KEY}",
                 f"key 是 {FAKE_KEY}"):
        out = LM.redact(text, FAKE_KEY)
        assert FAKE_KEY not in out, out
        assert "***" in out


def test_不给key也能擦掉Bearer头():
    """有时候拿不到 key 本身，只有一段带 Authorization 的报文。"""
    out = LM.redact("Authorization: Bearer sk-abcdefghijklmnop")
    assert "abcdefghij" not in out and "***" in out


def test_报错信息是脱敏过的():
    c = _client((401, {}, {"message": f"bad key: {FAKE_KEY}"}))
    with pytest.raises(LM.LLMError) as e:
        c.chat([{"role": "user", "content": "hi"}])
    assert FAKE_KEY not in str(e.value)


def test_用量落盘里没有key也没有请求内容(tmp_path):
    c = _client()
    c.chat([{"role": "user", "content": f"密码是 {FAKE_KEY}"}])
    p = LM.save_usage(c.usage, path=tmp_path / "llm.json")
    text = p.read_text(encoding="utf-8")
    assert FAKE_KEY not in text and "密码" not in text
    assert json.loads(text)["calls"] == 1


# =========================================================================
# 二、限流：等到下一个整分钟，且上限从响应头读
# =========================================================================

def test_限流值以响应头为准而不是写死():
    c = _client((200, {"x-ratelimit-limit-req-minute": "60",
                       "x-ratelimit-remaining-req-minute": "59"},
                 {"choices": [{"message": {"content": "x"}}], "usage": {}}))
    c.chat([{"role": "user", "content": "hi"}])
    assert c.usage.rpm_limit == 60, "升到付费档之后应该自己跟上"


def test_撞限流会退避并重试():
    c = _client(_429(), _ok("成功了"))
    out = c.chat([{"role": "user", "content": "hi"}])
    assert out["message"]["content"] == "成功了"
    assert c.usage.backoffs == 1 and len(c.slept) == 1
    assert 0 < c.slept[0] <= 60.0


def test_等的是到下一个整分钟不是指数退避():
    """实测窗口是固定 60 秒边界，指数退避会等过头。"""
    for now, want in ((0.0, 60.0), (30.0, 30.0), (59.5, 0.5)):
        assert abs(LM.seconds_to_next_minute(now) - want) < 0.01


def test_一直限流最终要报出上限而不是无限重试():
    c = _client(_429(), _429(), _429(), _429(), max_retries=2)
    with pytest.raises(LM.LLMError) as e:
        c.chat([{"role": "user", "content": "hi"}])
    assert "4 次/分钟" in str(e.value)


def test_用量统计累加():
    c = _client(_ok(usage={"prompt_tokens": 10, "completion_tokens": 5}),
                _ok(usage={"prompt_tokens": 7, "completion_tokens": 3}))
    c.chat([{"role": "user", "content": "a"}])
    c.chat([{"role": "user", "content": "b"}])
    assert c.usage.calls == 2 and c.usage.total_tokens == 25


def test_读不到key要说清楚去哪放(tmp_path, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(LM.LLMError) as e:
        LM.load_key(tmp_path / "没有这个.env")
    assert "环境变量" in str(e.value) and ".gitignore" in str(e.value)


def test_模型钉死日期版():
    """`-latest` 会漂，一漂回归基线就失去意义。"""
    assert LM.DEFAULT_MODEL == "mistral-large-2512"
    assert "latest" not in LM.DEFAULT_MODEL


# =========================================================================
# 三、循环的四个退出条件
# =========================================================================

@pytest.fixture
def sess():
    from svagent import session as S
    return S.Session("xiaofeng")


def _tc(name, params, cid="c1"):
    return [{"id": cid, "type": "function",
             "function": {"name": name,
                          "arguments": json.dumps(params, ensure_ascii=False)}}]


def test_退出条件1_模型不再调工具(sess):
    c = _client(_ok("我看了指标，没什么要改的"))
    r = LP.run(sess, "看看情况", client=c)
    assert "自然结束" in r.exit_reason
    assert r.final_text.startswith("我看了")
    assert r.n_actions == 0


def test_退出条件2_达到auto_rounds(sess):
    c = _client(_ok(tool_calls=_tc("verify_alignment", {})),
                _ok(tool_calls=_tc("verify_alignment", {}, "c2")),
                _ok("够了"))
    r = LP.run(sess, "验一下对齐", client=c, auto_rounds=1)
    assert "auto_rounds" in r.exit_reason


def test_退出条件3_动作数上限(sess):
    c = _client(*[_ok(tool_calls=_tc("verify_alignment", {}, f"c{i}"))
                  for i in range(6)])
    r = LP.run(sess, "反复验", client=c, auto_rounds=99, max_actions=2)
    assert "上限 2" in r.exit_reason and r.n_actions == 2


def test_退出条件4_喊停(sess, tmp_path):
    from svagent.agent import budget as BD
    stop = tmp_path / ".stop"
    stop.write_text("")
    bud = BD.Budget(stop_file=stop)
    c = _client(_ok(tool_calls=_tc("verify_alignment", {})))
    r = LP.run(sess, "干活", client=c, budget=bud)
    assert "到此为止" in r.exit_reason
    assert not c.transport.seen, "喊停之后不该再发请求"


def test_超预算在发请求之前就拦住(sess):
    from svagent.agent import budget as BD
    c = _client(_ok("x"))
    r = LP.run(sess, "干活", client=c,
               budget=BD.Budget(seconds=0.0, stop_file=None))
    assert "墙钟预算" in r.exit_reason
    assert not c.transport.seen, "预算用完了还发请求 = 白烧配额"


# =========================================================================
# 四、上下文与回灌
# =========================================================================

def test_上下文里必须带环境事实(sess):
    """第 4 项的兑现：**agent 读不到就等于没有。**"""
    msgs = LP.context(sess, "副歌不够爆")
    sysmsg = msgs[0]["content"]
    assert "F01" in sysmsg and "F11" in sysmsg
    assert "不判断正确性" in sysmsg


def test_上下文里必须带状态和指标(sess):
    user = LP.context(sess, "副歌不够爆")[1]["content"]
    assert "六步状态" in user and "指标" in user
    assert "副歌不够爆" in user


def test_tool_result回灌的是带数字的那份(sess):
    """架构 §2.5 的支点：模型看数字决定下一步，不是看「执行成功」。"""
    c = _client(_ok(tool_calls=_tc("verify_alignment", {})), _ok("好"))
    LP.run(sess, "验对齐", client=c, auto_rounds=5)
    tool_msgs = [m for b in c.transport.seen for m in b["messages"]
                 if m.get("role") == "tool"]
    assert tool_msgs, "没有回灌"
    payload = json.loads(tool_msgs[-1]["content"])
    assert "delta" in payload and "hooks" in payload
    assert "alignment" in payload and "offset_ms" in payload["alignment"]


def test_工具报错不会让循环崩掉(sess):
    c = _client(_ok(tool_calls=_tc("没有这个动作", {})), _ok("那算了"))
    r = LP.run(sess, "乱调一个", client=c, auto_rounds=5)
    assert r.steps[0].error and "没有叫" in r.steps[0].error
    assert r.final_text == "那算了", "报错之后要能继续"


def test_参数不合法要如实回灌而不是静默改掉(sess):
    c = _client(_ok(tool_calls=_tc("gen_harmony", {"kind": "低八度"})),
                _ok("知道了"))
    r = LP.run(sess, "加和声", client=c, auto_rounds=5)
    assert "应为 array" in r.steps[0].error


def test_模型调用失败要写进退出原因(sess):
    c = _client((500, {}, {"message": "boom"}))
    r = LP.run(sess, "干活", client=c)
    assert "模型调用失败" in r.exit_reason and r.n_actions == 0


# =========================================================================
# 五、真接口冒烟（默认跳过 —— 每分钟只有 4 次配额）
# =========================================================================

@pytest.mark.skipif("--live" not in sys.argv,
                    reason="要打真接口，加 --live 才跑（会吃掉一次配额）")
def test_live_真接口能通():
    c = LM.Mistral()
    out = c.chat([{"role": "user", "content": "只回复两个字：收到"}],
                 max_tokens=20)
    assert out["message"]["content"]
    assert c.usage.rpm_limit is not None
