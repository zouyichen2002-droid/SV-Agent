# -*- coding: utf-8 -*-
"""M2-01 探针：本地大模型能不能用（PRD v2.7：本地为主，遇到问题再切 Mistral）。

创作者 09-29：「既然这是个人创作助手，我想把 LLM 也换成本地模型（尽量最新、最强），在遇到问题的时候再切换成 Mistral」；
选了 Qwen3.8-27B（unsloth 的 UD-IQ4_XS GGUF，14.3 GB，Apache-2.0）+ llama.cpp b11259 的 Vulkan 版。

只测以后真要用的事 —— 不让它凭一句话写旋律（R03：旋律必须外部学习）：
1. 放不放得下：显卡 12 GB，几层上显卡、几层留在 CPU；载入要多久
2. 快不快：读提示和出字的速度（token/秒）
3. 格式合不合：要它把 PRD 里 C01–C07 那张表转成 JSON，程序逐项核对（重试也算进去）
4. 中文好不好：一道歌词问题，答案原样给创作者看（不写进任何记忆）

    python probe_local.py [--ctx 8192] [--port 8081] [--server <llama-server.exe>] [--device Vulkan0|CUDA0] [--tag _cuda]
服务由脚本自己起、测完自己关，不留后台进程。结果写在仓库外 E:/sv-agent-data/probes/m2-01-local-llm/
（result<tag>.json、server<tag>.log；09-29 先测了 Vulkan 版，创作者说「可以换 CUDA 版试试」→ 同一套题再测一遍）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
SERVER = pathlib.Path("E:/sv-agent-data/tools/llama.cpp-b11259/llama-server.exe")
MODEL = pathlib.Path("E:/sv-agent-data/models/llm/Qwen3.8-27B-UD-IQ4_XS.gguf")
PRD = pathlib.Path(__file__).resolve().parents[2] / "PRD.md"
OUT = pathlib.Path("E:/sv-agent-data/probes/m2-01-local-llm")


def post(port: int, body: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", method="POST",
                                 data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def wait_ready(port: int, proc: subprocess.Popen, limit: float = 900) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limit:
        if proc.poll() is not None:
            raise RuntimeError(f"服务退出了（返回码 {proc.returncode}），看日志")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                if r.status == 200 and json.load(r).get("status") == "ok":
                    return time.perf_counter() - t0
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    raise TimeoutError("服务没在限定时间里就绪")


def speed(resp: dict) -> dict:
    t = resp.get("timings") or {}
    return {"读提示_token": t.get("prompt_n"), "读提示_每秒": round(t.get("prompt_per_second") or 0, 1),
            "出字_token": t.get("predicted_n"), "出字_每秒": round(t.get("predicted_per_second") or 0, 1)}


def prd_table() -> tuple[str, list[tuple[str, str]]]:
    """PRD §7.0 C01–C07 那张表：原文 + 标准答案（编号, 需求名）。"""
    lines = [l for l in PRD.read_text(encoding="utf-8").splitlines() if re.match(r"^\| \*\*C0[1-7]\*\* \|", l)]
    truth = [(re.search(r"C0[1-7]", l).group(0), l.split("|")[2].strip()) for l in lines]
    return "\n".join(lines), truth


def json_test(port: int, no_think: dict) -> dict:
    table, truth = prd_table()
    ask = ("把下面这张 Markdown 表转成 JSON，只输出 JSON，格式："
           '{"items": [{"id": "C01", "name": "需求名（原样照抄）", "points": "验收要点（可以缩短）"}]}\n\n' + table)
    tries = []
    for attempt in range(3):
        r = post(port, {"messages": [{"role": "user", "content": ask}], "max_tokens": 1500, "temperature": 0.2,
                        "response_format": {"type": "json_object"}, **no_think})
        text = r["choices"][0]["message"]["content"]
        try:
            items = json.loads(text)["items"]
            got = [(it["id"], it["name"].strip()) for it in items]
            ok = got == truth
            tries.append({"attempt": attempt + 1, "parsed": True, "exact": ok, **speed(r)})
            if ok:
                break
            tries[-1]["diff"] = [f"{a} ≠ {b}" for a, b in zip(got, truth) if a != b][:5] + ([f"条数 {len(got)} ≠ 7"] if len(got) != 7 else [])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            tries.append({"attempt": attempt + 1, "parsed": False, "error": str(e)[:120], **speed(r)})
    return {"标准答案": truth, "尝试": tries, "一次就对": bool(tries and tries[0].get("exact")),
            "最终对": any(t.get("exact") for t in tries)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--server", default=str(SERVER))
    ap.add_argument("--device", default="Vulkan0")
    ap.add_argument("--tag", default="")
    ap.add_argument("--kv8", action="store_true", help="KV 缓存压成 8 位（-ctk q8_0 -ctv q8_0），腾显存给模型")
    ap.add_argument("--skip-think", action="store_true", help="跳过开思考那项（最费时间）")
    ap.add_argument("--mtp", action="store_true", help="用模型自带的 MTP 草稿层做推测解码（--spec-type draft-mtp）")
    a = ap.parse_args()
    server = pathlib.Path(a.server)
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / f"server{a.tag}.log"
    cmd = [str(server), "-m", str(MODEL), "--host", "127.0.0.1", "--port", str(a.port), "-c", str(a.ctx),
           "--device", a.device, "--fit", "on", "--reasoning-format", "deepseek", "-np", "1"]
    if a.kv8:
        cmd += ["-ctk", "q8_0", "-ctv", "q8_0"]
    if a.mtp:
        cmd += ["--spec-type", "draft-mtp"]
    res: dict = {"model": MODEL.name, "server": server.parent.name, "device": a.device, "cmd": cmd}
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(server.parent))
        try:
            res["载入_秒"] = round(wait_ready(a.port, proc), 1)
            print(f"载入：{res['载入_秒']} 秒")
            logtext = log_path.read_text(encoding="utf-8", errors="replace")
            res["显卡层数"] = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", logtext)[-1:] or "日志里没找到"
            print("显卡层数（上显卡 / 总层数）：", res["显卡层数"])
            no_think = {"chat_template_kwargs": {"enable_thinking": False}}

            q = "什么是「倒字」？举两个流行歌里容易倒字的例子，并说怎么改。150 字以内。"
            r = post(a.port, {"messages": [{"role": "user", "content": q}], "max_tokens": 600, "temperature": 0.7, **no_think})
            res["中文问答"] = {"问": q, "答": r["choices"][0]["message"]["content"], **speed(r)}
            print(f"\n中文问答（关思考）：{speed(r)}\n{res['中文问答']['答']}\n")

            if not a.skip_think:
                r = post(a.port, {"messages": [{"role": "user", "content": q}], "max_tokens": 3000, "temperature": 0.7})
                m = r["choices"][0]["message"]
                res["中文问答_开思考"] = {"思考字数": len(m.get("reasoning_content") or ""), "答": m.get("content"), **speed(r)}
                print(f"中文问答（开思考）：{speed(r)} · 思考了 {res['中文问答_开思考']['思考字数']} 个字")

            res["JSON"] = json_test(a.port, no_think)
            print(f"\nJSON：一次就对 {res['JSON']['一次就对']} · 最终对 {res['JSON']['最终对']} · 尝试 {res['JSON']['尝试']}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
            res["服务已关"] = proc.poll() is not None
    (OUT / f"result{a.tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n服务已关：{res['服务已关']} · 结果：{OUT / f'result{a.tag}.json'} · 日志：{log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
