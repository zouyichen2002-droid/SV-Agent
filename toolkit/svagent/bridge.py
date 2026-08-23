"""驱动上游 synthv-agent-bridge 的 MCP 客户端（stdio / JSON-RPC）。

本会话没有把桥注册成 MCP 服务（它的 `.mcp.json` 在《潮声回响》目录下），
所以直接 spawn `node dist/src/cli.js` 手动驱动。上游文档确认这条路可行。

**这个客户端刻意做得薄**：它只负责传输与错误暴露，不封装任何领域语义。
桥的工具面（六个工具 / 17 read + 29 edit + 7 delete + 9 ui + 2 transaction）
是上游的，不在这里重新发明。

## 写入协议（交接文件 §3.5，必须遵守）

- 单写者，冲突返回 `BRIDGE_BUSY`
- 写前先 `sv_query ... contextMode=writeIntent` 取 `contextId`，再传给 `sv_command`
- 一个逻辑命令 = 一条 SynthV 撤销记录；撤销记录只是恢复边界，**不承诺自动回滚**
- `edit_notes` 协议上限 512，但 describe 明确警告每批 ≤60
- 桥**不能保存工程**，写完必须人工 Ctrl+S；反过来说，不保存就不落盘，
  这在验证阶段是安全特性
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any


class BridgeError(RuntimeError):
    def __init__(self, message: str, payload: Any = None):
        super().__init__(message)
        self.payload = payload


@dataclass
class Bridge:
    """一次会话。用 with 语句，退出时确保子进程被收掉。"""

    cli_js: Path | None = None
    node: str = r"C:\Program Files\nodejs\node.exe"
    argv: list[str] | None = None      # 给了就用它，不给则起 node cli_js
    cwd: Path | None = None
    client_name: str = "SV-Agent/svagent"
    timeout_s: float = 60.0
    verbose: bool = False
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _q: Queue = field(default_factory=Queue, repr=False)
    _stderr: list[str] = field(default_factory=list, repr=False)
    _next_id: int = field(default=0, repr=False)
    server_info: dict = field(default_factory=dict, repr=False)

    # ---------- 生命周期 ----------
    def __enter__(self) -> "Bridge":
        if self.argv:
            cmd, cwd = list(self.argv), self.cwd
        elif self.cli_js:
            cmd, cwd = [self.node, str(self.cli_js)], self.cli_js.parents[2]
        else:
            raise BridgeError("要么给 cli_js，要么给 argv")
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            cwd=str(cwd) if cwd else None,
        )
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        init = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": self.client_name, "version": "0.1.0"},
        })
        self.server_info = init.get("serverInfo", {})
        self._notify("notifications/initialized", {})
        return self

    def __exit__(self, *exc) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def _pump_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                if self.verbose:
                    print(f"[桥非 JSON 输出] {line[:200]}", file=sys.stderr)

    def _pump_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr[-20:])

    # ---------- 传输 ----------
    def _send(self, obj: dict) -> None:
        assert self._proc and self._proc.stdin
        if self.verbose:
            print(f"→ {json.dumps(obj, ensure_ascii=False)[:400]}")
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = self.timeout_s
        while True:
            try:
                msg = self._q.get(timeout=deadline)
            except Empty:
                raise BridgeError(
                    f"{method} 超时 {self.timeout_s}s。桥的 stderr:\n{self.stderr_tail}")
            if msg.get("id") != rid:
                continue          # 通知或别的响应，跳过
            if "error" in msg:
                raise BridgeError(f"{method} 返回错误: {msg['error']}", msg["error"])
            if self.verbose:
                print(f"← {json.dumps(msg.get('result'), ensure_ascii=False)[:400]}")
            return msg.get("result", {})

    # ---------- 工具面 ----------
    def list_tools(self) -> list[dict]:
        return self._request("tools/list", {}).get("tools", [])

    def call(self, name: str, args: dict | None = None) -> Any:
        res = self._request("tools/call", {"name": name, "arguments": args or {}})
        if res.get("isError"):
            raise BridgeError(f"{name} isError: {_text(res)}", res)
        return _parse(res)


def _text(res: dict) -> str:
    return "\n".join(c.get("text", "") for c in res.get("content", [])
                     if c.get("type") == "text")


def _parse(res: dict) -> Any:
    """工具返回是 content[] 里的文本，通常是 JSON。能解就解，解不了给原文。"""
    if "structuredContent" in res:
        return res["structuredContent"]
    t = _text(res)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, TypeError):
        return t


def decode_notes(payload: Any) -> list[dict]:
    """`get_track_notes` 音符多时会切成 dense 列式投影。两种格式都要认。

    交接文件 §3.4：`notes` 变成 `{columns:[...], rows:[[...]]}`（`noteFormat: "rows"`），
    不是对象数组。调用方必须能识别两种。
    """
    notes = payload
    if isinstance(payload, dict):
        notes = payload.get("notes", payload)
    if isinstance(notes, dict) and "columns" in notes and "rows" in notes:
        cols = notes["columns"]
        return [dict(zip(cols, row)) for row in notes["rows"]]
    if isinstance(notes, list):
        return notes
    return []
