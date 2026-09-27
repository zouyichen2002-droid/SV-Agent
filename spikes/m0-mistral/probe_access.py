# -*- coding: utf-8 -*-
"""Mistral 的 key 能不能用、能用哪些模型、限额是多少（2026-09-27，V1 清单 ★2 的证据）。

    cd /e/sv-bridge/spikes/m0-mistral && python probe_access.py

- key 从仓库根目录的 `.env` 读（被 git 忽略）。**不打印、不写文件**，
  只打印它的 SHA-256 前 12 位，和凭据扫描器登记的哈希对一下。
- 第一个请求是列模型（不收费）；第二个用最便宜的模型、max_tokens=1，
  只为看限额相关的响应头。09-27 那次一共花了 5 个 token。
- 第三、四个是**选定的生成模型** Medium 3.5（`mistral-medium-2604`）：
  模型详情（不收费，看别名、上下文、能力）+ 一次 max_tokens=1 的真调用（09-27 花了 17 个 token）。
  别名那一行是「为什么钉死日期版本、不用 -latest」的证据。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

ENV = pathlib.Path(__file__).resolve().parents[2] / ".env"
# 凭据扫描器登记的那把 key 的 SHA-256（哈希不泄露 key 本身）
KNOWN = "f8b904657a66f13da91b5f6f4596b3244702fccb5d7c025121f1856cc11e5096"
# 选定的生成模型（创作者 09-27 定）。钉死日期版本：-latest 这类别名会漂移
GEN_MODEL = "mistral-medium-2604"


def read_env_key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("MISTRAL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{ENV} 里没有 MISTRAL_API_KEY")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def call(method: str, url: str, key: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), json.load(r), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        return e.code, dict(e.headers), {"error_body": body}, time.perf_counter() - t0


def limit_headers(h: dict) -> dict:
    return {k: v for k, v in h.items() if "limit" in k.lower()}


def main() -> None:
    key = read_env_key()
    env_var = os.environ.get("MISTRAL_API_KEY", "")
    print("key 哈希前 12 位:", sha(key)[:12], "| 是扫描器登记的那把:", sha(key) == KNOWN)
    print("环境变量里的和 .env 里的是同一把:", bool(env_var) and sha(env_var) == sha(key))

    status, headers, body, dt = call("GET", "https://api.mistral.ai/v1/models", key)
    print(f"\n[列模型] HTTP {status} · {dt:.2f} 秒")
    if status == 200:
        ids = sorted({m.get("id", "") for m in body.get("data", [])})
        print("模型数:", len(ids))
        for i in ids:
            if any(w in i for w in ("large", "medium", "small", "ministral", "magistral")):
                print("  ", i)
    else:
        print(body)

    status, headers, body, dt = call("POST", "https://api.mistral.ai/v1/chat/completions", key, {
        "model": "ministral-3b-latest",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    })
    print(f"\n[1 token 请求 · ministral-3b-latest] HTTP {status} · {dt:.2f} 秒")
    print("用量:", body.get("usage") if status == 200 else body)
    print("限额相关的响应头:")
    for k, v in sorted(limit_headers(headers).items()):
        print("  ", k, "=", v)

    status, _headers, body, dt = call("GET", f"https://api.mistral.ai/v1/models/{GEN_MODEL}", key)
    print(f"\n[详情 · {GEN_MODEL}] HTTP {status} · {dt:.2f} 秒")
    if status == 200:
        print("   别名:", body.get("aliases"))
        print("   上下文:", body.get("max_context_length"), "· 退役:", body.get("deprecation"))
        caps = body.get("capabilities") or {}
        print("   能力:", {k: v for k, v in caps.items() if v})
    else:
        print(body)

    status, _headers, body, dt = call("POST", "https://api.mistral.ai/v1/chat/completions", key, {
        "model": GEN_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    })
    print(f"\n[1 token 请求 · {GEN_MODEL}] HTTP {status} · {dt:.2f} 秒")
    print("   返回的型号:", body.get("model") if status == 200 else "——",
          "| 用量:", body.get("usage") if status == 200 else body)


if __name__ == "__main__":
    main()
