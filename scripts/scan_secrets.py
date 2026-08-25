# -*- coding: utf-8 -*-
"""提交前的凭据扫描。**这是防线，不是提醒。**

## 为什么要有它

创作者 2026-08-25：这份 Mistral key **是和几个人共用的，不能轮换**。
所以泄露的代价不是「我换一个」，是「几个人一起受影响」——
而这个仓库是公开的。

原来的做法是**我每次提交前手工跑一遍 grep**。那靠的是我记得，
而这一轮里我已经失手过一次：`test_llm.py` 里的「同格式假 key」
直接抄了真 key，是提交前那次手工体检拦下来的。**下次可能就没拦住。**

所以改成 git 钩子：机制不会忘。

## 扫描器自己不许存明文 key

否则这个文件本身就会被自己扫出来，而且它是要进仓库的。
所以存的是 **SHA-256**，比对时对候选串取哈希 —— 扫描器泄不出任何东西。

## 只扫暂存区

工作区里有 `.env`（已被 gitignore），扫它只会制造噪声。
真正要拦的是**即将进入 git 的内容**。
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys

# 已知凭据的 SHA-256。**不存明文** —— 见模块说明。
# 加新的：python scripts/scan_secrets.py --hash "<凭据>"
KNOWN_HASHES = {
    "f8b904657a66f13da91b5f6f4596b3244702fccb5d7c025121f1856cc11e5096":
        "Mistral API key（与他人共用，不可轮换）",
}

# 通用形态。**宁可多报** —— 假阳性只花你三秒，漏报是公开的凭据。
PATTERNS = [
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[=:]\s*"
                r"['\"]?([A-Za-z0-9_\-]{20,})"), "疑似凭据赋值"),
    (re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-]{20,})"), "Authorization 头里的明文"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"), "OpenAI 风格的 key"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,})\b"), "GitHub token"),
]

# 允许出现的占位符。**必须完全匹配**，不做模糊。
ALLOW = {"", "***", "your_key_here", "xxx", "changeme",
         "FAKEKEY000000000000000000000000"}


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def staged_diff() -> str:
    r = subprocess.run(["git", "diff", "--cached", "--unified=0"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.stdout or ""


def mask(line: str, secret: str) -> str:
    """把命中的那一段打掉再显示。

    **第一版把 key 原样打到终端上了。** 一个保护凭据的工具反手把凭据
    打出来 —— 而终端会进滚动缓冲、进截图、进这次对话。
    实测发现的，就在装钩子的当天。
    """
    keep = 3 if len(secret) > 8 else 0
    masked = secret[:keep] + "*" * (len(secret) - keep)
    out = line.replace(secret, masked)
    return (out[:76] + "…") if len(out) > 76 else out


def scan(text: str) -> list[tuple[str, str]]:
    """→ [(命中了什么, **打过码的**出处)]。空列表 = 干净。"""
    hits: list[tuple[str, str]] = []
    lines = [l for l in text.splitlines() if l.startswith("+")]

    # 1) 已知凭据：**逐个候选串取哈希比对**
    for ln in lines:
        for tok in re.findall(r"[A-Za-z0-9_\-]{20,}", ln):
            what = KNOWN_HASHES.get(sha(tok))
            if what:
                hits.append((f"**已知凭据**：{what}", mask(ln, tok)))

    # 2) 通用形态
    for ln in lines:
        for pat, what in PATTERNS:
            m = pat.search(ln)
            if not m:
                continue
            val = m.group(m.lastindex or 1)
            if val in ALLOW or set(val) <= {"x", "X", "0", "*"}:
                continue
            hits.append((what, mask(ln, val)))
    return hits


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 2 and sys.argv[1] == "--hash":
        print(sha(sys.argv[2]))
        return 0

    hits = scan(staged_diff())
    if not hits:
        return 0

    print("=" * 66)
    print("✗ 提交被拦住：暂存区里有疑似凭据")
    print("=" * 66)
    seen = set()
    for what, where in hits:
        if (what, where) in seen:
            continue
        seen.add((what, where))
        print(f"  {what}")
        print(f"    {where}")
    print()
    print("  这个仓库是公开的，而 Mistral 那份 key 与他人共用、**不能轮换** ——")
    print("  泄露的代价不是「换一个」，是几个人一起受影响。")
    print()
    print("  确认是假值就加进 scan_secrets.py 的 ALLOW；")
    print("  真要跳过：git commit --no-verify（**想清楚再用**）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
