# -*- coding: utf-8 -*-
"""建造顺序第 10 项之一：**Mistral 客户端**。

## 三条约束都是实测出来的，不是猜的（见架构文档 §4.5）

    每分钟 4 次请求        x-ratelimit-limit-req-minute = 4
    每分钟 25 万 tokens    基本用不完
    tool calling 可用      finish_reason = tool_calls

两个数一除：**平均每次请求可以带 62,500 tokens**。所以这一层的设计取向是
「次数少、每次塞满」，而不是「token 便宜就多跑几次」。

## 退避等到下一个整分钟，不用指数退避

实测窗口是**固定的 60 秒边界**（remaining 走 3→2→1→0→3）。
指数退避会等过头 —— 等 1、2、4、8 秒，而真正该等的是「到下一分钟还剩几秒」。

## 限流值从响应头读，不写死

每个响应都带 `x-ratelimit-limit-req-minute`。创作者哪天升到付费档，
这一层自己就跟上，不用改代码。**写死 4 就等于把一个会变的事实焊进代码。**

## 凭据的三条硬规则（仓库是公开的）

1. key 只从环境变量 / `.env` 读，**绝不写进任何进 git 的文件**
2. **绝不写进 `journal.jsonl`**，绝不渲染进 `dashboard.html`
3. 出错要脱敏 —— `Authorization` 头一律打成 `Bearer ***` 再打印

第 3 条有测试守着：`redact()` 的反向测试会拿真格式的 key 试一遍。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://api.mistral.ai/v1/chat/completions"

# **钉死日期版，不用 `-latest`。** `-latest` 会漂，一漂回归基线就失去意义。
DEFAULT_MODEL = "mistral-large-2512"

# 实测值，仅作**没有响应头时**的初始猜测。有响应头就以响应头为准。
FALLBACK_RPM = 4


class LLMError(Exception):
    """调用失败。**消息一定是脱敏过的。**"""


def load_key(env_path: Path | None = None) -> str:
    """只从环境变量或 `.env` 读。**没有别的来源。**"""
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if key:
        return key
    p = Path(env_path or (ROOT / ".env"))
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.startswith("MISTRAL_API_KEY="):
                return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    raise LLMError(f"读不到 MISTRAL_API_KEY。放进环境变量，或写进 {p}"
                   f"（那个文件已被 .gitignore 忽略）")


def redact(text: str, key: str = "") -> str:
    """脱敏。**任何要被打印、落盘、进日志的字符串都要过它。**

    仓库是公开的，而报错信息最容易顺手打进日志。
    """
    out = str(text)
    if key:
        out = out.replace(key, "***")
    out = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-]{8,}", r"\1***", out)
    out = re.sub(r"(MISTRAL_API_KEY\s*=\s*)\S+", r"\1***", out)
    return out


@dataclass
class Usage:
    """本次会话烧掉了什么。**模型面板读它。**"""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    backoffs: int = 0
    waited_s: float = 0.0
    rpm_limit: int | None = None
    rpm_remaining: int | None = None
    errors: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_json(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "backoffs": self.backoffs, "waited_s": round(self.waited_s, 1),
                "rpm_limit": self.rpm_limit, "rpm_remaining": self.rpm_remaining,
                "errors": self.errors}

    def report(self) -> str:
        return (f"  调用 {self.calls} 次　token {self.total_tokens}"
                f"（入 {self.prompt_tokens} / 出 {self.completion_tokens}）\n"
                f"  限流退避 {self.backoffs} 次，共等 {self.waited_s:.0f}s"
                + (f"　服务端上限 {self.rpm_limit} 次/分钟"
                   if self.rpm_limit else ""))


def seconds_to_next_minute(now: float | None = None) -> float:
    """离下一个整分钟还有几秒。**这就是该等的时长。**"""
    t = time.time() if now is None else now
    return max(0.05, 60.0 - (t % 60.0))


@dataclass
class Mistral:
    """一个极薄的客户端。**不装 SDK** —— 我们需要的只是 POST + 读头 + 处理 429。"""

    key: str = ""
    model: str = DEFAULT_MODEL
    timeout_s: float = 120.0
    max_retries: int = 3
    usage: Usage = field(default_factory=Usage)
    # 注入点：测试用假传输，**不打真接口**（每分钟只有 4 次配额，
    # 让测试去烧它既慢又会让别的调用失败）
    transport: object = None
    sleep = staticmethod(time.sleep)

    def __post_init__(self):
        if not self.key and self.transport is None:
            self.key = load_key()

    # ---- 传输 --------------------------------------------------------
    def _post(self, body: dict) -> tuple[int, dict, dict]:
        if self.transport is not None:
            return self.transport(body)
        req = urllib.request.Request(
            ENDPOINT, data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return r.status, dict(r.headers), json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"message": raw[:300].decode("utf-8", "replace")}
            return e.code, dict(e.headers), payload

    def _note_headers(self, headers: dict) -> None:
        def geti(k):
            v = headers.get(k)
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        lim = geti("x-ratelimit-limit-req-minute")
        if lim is not None:
            self.usage.rpm_limit = lim           # **以响应头为准，不写死**
        self.usage.rpm_remaining = geti("x-ratelimit-remaining-req-minute")

    # ---- 主入口 ------------------------------------------------------
    def chat(self, messages: list[dict], *, tools: list[dict] | None = None,
             temperature: float = 0.3, max_tokens: int = 2000) -> dict:
        """一次对话。撞限流就等到下一个整分钟再试。→ `choices[0].message`。"""
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        for attempt in range(self.max_retries + 1):
            status, headers, payload = self._post(body)
            self._note_headers(headers)

            if status == 200:
                self.usage.calls += 1
                u = payload.get("usage") or {}
                self.usage.prompt_tokens += int(u.get("prompt_tokens") or 0)
                self.usage.completion_tokens += int(
                    u.get("completion_tokens") or 0)
                ch = (payload.get("choices") or [{}])[0]
                return {"message": ch.get("message") or {},
                        "finish_reason": ch.get("finish_reason"),
                        "usage": u}

            if status == 429 and attempt < self.max_retries:
                wait = seconds_to_next_minute()
                self.usage.backoffs += 1
                self.usage.waited_s += wait
                self.sleep(wait)
                continue

            self.usage.errors += 1
            if status == 429:
                # **最常见的失败必须给最有用的消息。** 掉进通用分支只会说
                # 「HTTP 429」，而创作者需要知道的是上限、窗口、以及该怎么办。
                raise LLMError(
                    f"连续 {self.max_retries + 1} 次撞限流仍未通过。"
                    f"服务端上限 {self.usage.rpm_limit or FALLBACK_RPM} 次/分钟"
                    f"（固定 60 秒窗口）。等一分钟再来，"
                    f"或者把这一轮要问的事合成一次问完。")
            msg = redact(payload.get("message") or payload, self.key)
            raise LLMError(f"HTTP {status}：{str(msg)[:300]}")

        self.usage.errors += 1
        raise LLMError(f"连续 {self.max_retries} 次撞限流仍未通过。"
                       f"服务端上限 {self.usage.rpm_limit or FALLBACK_RPM} 次/分钟")


# =========================================================================
# 用量报告：仪表盘的模型面板读它
# =========================================================================

REPORT_PATH = ROOT / ".agent" / "llm.json"


def save_usage(u: Usage, model: str = DEFAULT_MODEL,
               path: Path | None = None) -> Path:
    """落盘。**不含 key，也不含任何请求内容** —— 只有计数。"""
    from .agent import safewrite as SW
    p = Path(path or REPORT_PATH)
    SW.write_json(p, {"ts": time.time(), "model": model, **u.to_json()})
    return p


def load_usage(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or REPORT_PATH).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
