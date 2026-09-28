# -*- coding: utf-8 -*-
"""最小生成探针：一句话 → Mistral Medium 3.5 写 16 小节旋律和声 → 钢琴试听 + .svp。

要回答的两件事（docs/m2/00-gen-probe.md）：
1. Medium 3.5 写的旋律，你愿不愿意继续做？（只有你的耳朵能判，PRD §8.2）
2. 「约束词」有没有用？（你 09-05 定的方向：约束词 + 预设）

做法：2 个意图 × 2 版（只给意图 / 意图 + 约束词）= 4 段。同一意图的两版随机标成 A、B，
**盲听**：试听单 listen.md 里看不出哪版加了约束词，揭晓在 reveal.md。

- 预算闸（PRD §17.2）：整次 ≤ 30 万 token 且 ≤ 15 分钟；开跑前按「提示 + 输出上限」预留，不够就不跑
- 没过硬检查的候选，带着错误清单让模型改一次（有上限，不无限重试 —— PRD §9）
- key 只从仓库根目录的 .env 读，不打印、不写文件

    cd /e/sv-bridge/spikes/m2-00-gen-probe && python probe.py
    python probe.py --fill run_20260928_123037     # 只补生成那次运行里没过硬检查的段
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import os
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request

import check
import music

sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
ENV = HERE.parents[1] / ".env"
MODEL = "mistral-medium-2604"            # 钉死日期版本：-latest 这类别名会漂移（V1 清单 ★2）
MAX_TOKENS = 8000                        # 每次调用的输出上限。09-28 第一次真跑：实际 1.3k–2.9k，没有推理输出
FRESH_TRIES = 2                          # 每段最多从头生成 2 次，每次最多改 1 次 → 一段最多 4 次调用
TASK_TOKEN_CAP = 300_000                 # PRD §17.2：每个任务 ≤ 30 万 token
TASK_SECONDS_CAP = 15 * 60               # 且 ≤ 15 分钟
PRICE_IN, PRICE_OUT = 1.5, 7.5           # 美元 / 百万 token，Mistral 官方价格页 2026-09-27
USD_CNY = 7.2

INTENTS = [
    ("1", "写一段末班地铁上的独白，副歌克制一点"),        # PRD §4.1 的例子
    ("2", "夏天傍晚骑车去海边，轻快，带点小得意"),        # 和 1 反差大的一个
]
CONSTRAINT_WORDS = [                    # 和 check.CONSTRAINTS 一一对应
    "节奏要有变化：至少用到 4 种不同的时值",
    "至少两处切分，或者「三三二」（一小节里落点在 0、1.5、3 拍）",
    "每句结尾留气口：至少半拍的休止",
    "相邻两小节的节奏型不要完全一样",
    "主歌稀、副歌密：副歌每小节的音平均比主歌多",
    "副歌的最高音比主歌的最高音高",
]

SYSTEM = """你是一位华语流行歌曲作曲人，给虚拟歌手（Synthesizer V，女声）写一段 16 小节的歌曲片段：第 1–8 小节是主歌，第 9–16 小节是副歌。

只输出一个 JSON 对象，不要任何解释，不要代码块标记。格式如下（示例只写了 2 个小节，你要写满 16 个）：
{"title": "片段名", "key": "C", "mode": "major", "bpm": 90,
 "lyrics": ["今天的风很温柔"],
 "bars": [
  {"bar": 1, "chords": ["C"], "melody": [[0, 1, 64, "今"], [1, 1, 65, "天"], [2, 1.5, 67, "的"], [3.5, 0.5, 69, "风"]]},
  {"bar": 2, "chords": ["F", "G"], "melody": [[0, 2, 67, "很"], [2, 1, 65, "温"], [3, 1, 64, "柔"]]}
 ],
 "idea": "一两句话：你怎么体现这个意图"}

字段：
- key：C C# D Eb E F F# G Ab A Bb B 之一；mode：major 或 minor；bpm：50–180 的整数
- bars：恰好 16 个，bar 从 1 到 16
- chords：每小节 1 个或 2 个和弦，2 个时各占半小节。用常见写法：C、Am、F/A、G7、Dm7、Cmaj7、Bb、F#m7b5、Gsus4 等
- melody：每个音 [小节内起拍, 时值, MIDI 音高, 这个音唱的字]
  - 起拍从 0 算，单位是拍（四分音符），是 0.25 的倍数；时值是 0.25 的倍数，最小 0.25
  - 音符不跨小节线：起拍 + 时值 ≤ 4
  - 同一小节里按起拍排序、互不重叠；空出来的地方就是休止
  - 一个字一个音；一个字要拖到下一个音时，下一个音的字写 "-"，而且要紧接着前一个音，中间不能有空隙
  - 主旋律音高在 57–76（A3–E5）之间
- lyrics：中文，按句写。每个不是 "-" 的音唱一个字，按顺序连起来要正好等于 lyrics 连起来（去掉标点）"""


def user_prompt(intent: str, constrained: bool) -> str:
    text = f"意图：{intent}"
    if constrained:
        text += "\n\n约束词（尽量都做到）：\n" + "\n".join("- " + w for w in CONSTRAINT_WORDS)
    return text


def read_key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("MISTRAL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{ENV} 里没有 MISTRAL_API_KEY")


def _post(key: str, payload: dict, timeout: float):
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions", method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def call_mistral(key: str, messages: list[dict]) -> dict:
    """一次生成。最多两次尝试：429/5xx/超时等 5 秒重试；400 就去掉 JSON 模式再试一次。"""
    payload = {"model": MODEL, "messages": messages, "max_tokens": MAX_TOKENS,
               "response_format": {"type": "json_object"}}
    t0 = time.perf_counter()
    last_error = None
    for attempt in range(2):
        try:
            body = _post(key, payload, timeout=480)
            msg = body["choices"][0]
            content = msg["message"].get("content")
            text, thinking = "", 0
            if isinstance(content, list):
                for chunk in content:
                    if chunk.get("type") == "text":
                        text += chunk.get("text", "")
                    elif chunk.get("type") == "thinking":
                        thinking += len(json.dumps(chunk.get("thinking"), ensure_ascii=False))
            else:
                text = content or ""
            return {"ok": True, "text": text, "thinking_chars": thinking, "usage": body.get("usage") or {},
                    "finish": msg.get("finish_reason"), "seconds": time.perf_counter() - t0,
                    "attempts": attempt + 1, "json_mode": "response_format" in payload}
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code == 400 and "response_format" in payload:
                payload.pop("response_format")
                continue
            if e.code == 429 or e.code >= 500:
                time.sleep(5)
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = f"网络：{e}"
            time.sleep(5)
    return {"ok": False, "error": last_error, "usage": {}, "seconds": time.perf_counter() - t0}


def extract_json(text: str):
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("回复里没有 JSON 对象")
    return json.loads(s[a:b + 1])


def generate(key: str, intent: str, constrained: bool) -> dict:
    """生成一段：没过硬检查就带着错误清单让它改一次；还不过，就从头再生成一次（同样最多改一次）。
    → 记录：每一轮的错误和原文都留着（第一轮错在哪，才分得清是模型的错还是检查器太严）。"""
    calls, rounds, cand, errs, raw = [], [], None, ["没有生成"], ""
    for fresh in range(FRESH_TRIES):
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user_prompt(intent, constrained)}]
        for repair in range(2):
            r = call_mistral(key, messages)
            calls.append({k: r.get(k) for k in ("ok", "usage", "seconds", "finish", "attempts",
                                                "json_mode", "thinking_chars", "error")})
            if not r["ok"]:
                errs = [r["error"]]
                rounds.append({"fresh": fresh + 1, "repair": repair, "errors": errs, "raw": ""})
                break
            raw = r["text"]
            try:
                cand = extract_json(raw)
                errs = check.hard_errors(cand)
            except (ValueError, json.JSONDecodeError) as e:
                cand, errs = None, [f"JSON 解析失败：{e}"]
            rounds.append({"fresh": fresh + 1, "repair": repair, "errors": errs, "raw": raw})
            if not errs:
                return {"cand": cand, "errors": [], "raw": raw, "calls": calls, "rounds": rounds}
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": "上面的 JSON 有这些问题，请改好后输出完整的 JSON（还是只输出 JSON）：\n"
                                                     + "\n".join("- " + e for e in errs[:20])}]
    return {"cand": cand, "errors": errs, "raw": raw, "calls": calls, "rounds": rounds}


def tokens_of(calls: list[dict]) -> tuple[int, int]:
    pin = sum((c.get("usage") or {}).get("prompt_tokens", 0) for c in calls)
    pout = sum((c.get("usage") or {}).get("completion_tokens", 0) for c in calls)
    return pin, pout


def selftest_ok() -> bool:
    fails = check.selftest()
    print("检查器自检：", "通过（9 种注入缺陷全部抓到，合法样本不误报）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    return not fails


def budget_ok(n_slots: int) -> bool:
    per_call = max(int(len(SYSTEM + user_prompt(i, c)) * 1.2) for _, i in INTENTS for c in (False, True)) + MAX_TOKENS
    reserve = per_call * FRESH_TRIES * 2 * n_slots     # 每段最多 从头 2 次 × 每次 2 次调用
    print(f"预算闸：最坏情况预留 {reserve:,} token（上限 {TASK_TOKEN_CAP:,}）")
    return reserve <= TASK_TOKEN_CAP


def run_jobs(jobs: list[tuple[str, str, bool]]) -> tuple[dict, float]:
    """jobs = [(标签, 意图, 是否加约束词)] → ({标签: 记录}, 用时秒)。并行，整次最多等 15 分钟。"""
    key = read_key()
    t0 = time.perf_counter()
    records = {}
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = {pool.submit(generate, key, intent, c): label for label, intent, c in jobs}
        done, pending = cf.wait(futs, timeout=TASK_SECONDS_CAP)
        for f in done:
            records[futs[f]] = f.result()
        for f in pending:
            records[futs[f]] = {"cand": None, "errors": ["超过 15 分钟，没等它"], "raw": "", "calls": [], "rounds": []}
    del key
    return records, time.perf_counter() - t0


def finish_row(row: dict, rec: dict, out: pathlib.Path, piano, database, tag: str = "round") -> None:
    """把一次生成的结果并进这一行：留原文、过了就渲染 WAV、写 .svp、量数。之前失败的调用照样记账。"""
    start = len(row.get("rounds", []))
    for i, x in enumerate(rec["rounds"], 1):
        (out / f"{row['label']}.{tag}{start + i}.raw.txt").write_text(x["raw"] or "", encoding="utf-8")
    row["calls"] = row.get("calls", []) + rec["calls"]
    row["rounds"] = row.get("rounds", []) + [{**{k: v for k, v in x.items() if k != "raw"}, "tag": tag} for x in rec["rounds"]]
    row["prompt_tokens"], row["completion_tokens"] = tokens_of(row["calls"])
    row["hard_errors"] = rec["errors"]
    cand = rec["cand"]
    if cand is not None:
        (out / f"{row['label']}.json").write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")
    if cand is not None and not rec["errors"]:
        wav = music.render_wav(cand, str(out / f"{row['label']}.wav"), piano)
        expected = music.music_seconds(cand) + music.renderers.RELEASE_S + 0.05
        wav["duration_ok"] = abs(wav["seconds"] - expected) < 0.02      # 第二个裁判：时长对得上小节数和速度
        svp = music.build_svp(cand, row["label"], str(out / "render"), database)
        (out / f"{row['label']}.svp").write_text(json.dumps(svp, ensure_ascii=False), encoding="utf-8")
        m = check.metrics(cand)
        row.update(title=cand.get("title"), key=cand["key"], mode=cand["mode"], bpm=cand["bpm"],
                   idea=cand.get("idea"), wav=wav, metrics={k: v for k, v in m.items() if not k.startswith("_")},
                   constraints=check.constraint_report(m))


def write_all(out: pathlib.Path, rows: list[dict], totals: dict) -> None:
    totals["prompt_tokens"] = sum(r["prompt_tokens"] for r in rows)
    totals["completion_tokens"] = sum(r["completion_tokens"] for r in rows)
    usd = totals["prompt_tokens"] / 1e6 * PRICE_IN + totals["completion_tokens"] / 1e6 * PRICE_OUT
    totals.update(usd=round(usd, 4), cny=round(usd * USD_CNY, 2))
    (out / "summary.json").write_text(json.dumps({"totals": totals, "rows": rows}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    write_listen(out, rows, totals)
    write_reveal(out, rows, totals)


def print_status(out: pathlib.Path, rows: list[dict], totals: dict) -> None:
    print(f"\n累计：输入 {totals['prompt_tokens']:,} + 输出 {totals['completion_tokens']:,} token · "
          f"约 ${totals['usd']:.3f}（¥{totals['cny']:.2f}）· 生成用时 {totals['wall_seconds']:.1f} 秒")
    for r in rows:
        status = "过" if not r["hard_errors"] else f"没过（{len(r['hard_errors'])} 处）"
        extra = f" · {r['wav']['seconds']:.1f} 秒 · 时长核对 {'对' if r['wav']['duration_ok'] else '不对'}" if "wav" in r else ""
        print(f"  {r['label']}：硬检查{status} · 调用 {len(r['calls'])} 次{extra}")
        for x in r["rounds"]:
            if x["errors"]:
                what = "补生成" if x.get("tag") == "fill" else "生成"
                print(f"      {what}第 {x['fresh']} 次{'（改过）' if x['repair'] else ''}：{len(x['errors'])} 处 —— {x['errors'][:2]}")
    print(f"\n试听单：{out / 'listen.md'}")
    print(f"揭晓（听完再看）：{out / 'reveal.md'}")


def main() -> int:
    if not selftest_ok() or not budget_ok(len(INTENTS) * 2):
        return 1
    piano = music.renderers.GmDlsPiano().load()
    database, _ = music.make_test_svp.voice_database()
    run = dt.datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out = HERE / "out" / run
    (out / "render").mkdir(parents=True)

    seed = int(time.time())
    rng = random.Random(seed)
    rows = []
    for no, intent in INTENTS:
        order = [False, True]
        rng.shuffle(order)
        for letter, constrained in zip("AB", order):
            rows.append({"label": f"{no}{letter}", "intent_no": no, "intent": intent, "constrained": constrained})

    records, wall = run_jobs([(r["label"], r["intent"], r["constrained"]) for r in rows])
    for r in rows:
        finish_row(r, records[r["label"]], out, piano, database)
    totals = {"run": run, "seed": seed, "model": MODEL, "wall_seconds": round(wall, 1), "cap_tokens": TASK_TOKEN_CAP}
    (out / "answer.json").write_text(json.dumps({"seed": seed, "constrained": {r["label"]: r["constrained"] for r in rows}},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    write_all(out, rows, totals)
    print_status(out, rows, totals)
    return 0


def fill(run: str) -> int:
    """补生成：只重做这次运行里没过硬检查的段，盲听编号不变（哪版加了约束词不变）。"""
    out = HERE / "out" / run
    data = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    rows, totals = data["rows"], data["totals"]
    todo = [r for r in rows if r["hard_errors"]]
    if not todo:
        print("这次运行没有要补的段")
        return 0
    if not selftest_ok() or not budget_ok(len(todo)):
        return 1
    piano = music.renderers.GmDlsPiano().load()
    database, _ = music.make_test_svp.voice_database()
    records, wall = run_jobs([(r["label"], r["intent"], r["constrained"]) for r in todo])
    for r in todo:
        finish_row(r, records[r["label"]], out, piano, database, tag="fill")
        r["filled"] = True
    totals["wall_seconds"] = round(totals["wall_seconds"] + wall, 1)
    write_all(out, rows, totals)
    print_status(out, rows, totals)
    return 0


def write_listen(out: pathlib.Path, rows: list[dict], totals: dict) -> None:
    lines = [f"# 生成探针 · 试听单（盲听）", "",
             f"{totals['run']} · {totals['model']}", "",
             "**先别打开 reveal.md。** 同一个意图的 A、B 两版，一版只给了意图，一版还加了约束词 —— 听完、选完再看是哪版。", "",
             "- 先听钢琴版：判断旋律、和声、节奏（PRD §8.1）。伴奏是最朴素的柱式和弦 + 根音，只托住和声，不是编曲",
             "- 想听唱的：用 SynthV 打开同名 `.svp`，直接播放就行；要人声文件再点「导出为文件」（位置已预填）", ""]
    for no, intent in INTENTS:
        lines += [f"## 意图 {no}：{intent}", "", "| 段 | 调 · 速度 | 长度 | 钢琴试听 | SynthV 工程 |", "|---|---|---|---|---|"]
        for r in (x for x in rows if x["intent_no"] == no):
            if "wav" in r:
                lines.append(f"| {r['label']} | {r['key']} {r['mode']} · {r['bpm']} BPM | {r['wav']['seconds']:.0f} 秒 | "
                             f"`{out / (r['label'] + '.wav')}` | `{out / (r['label'] + '.svp')}` |")
            else:
                lines.append(f"| {r['label']} | —— | —— | 没过硬检查，没渲染 | —— |")
        lines.append("")
    lines += ["## 听完填这里（口头告诉 Claude 也行）", "",
              "| 段 | 保留 / 继续改 / 放弃 | 一句原因 |", "|---|---|---|"]
    lines += [f"| {r['label']} | | |" for r in rows]
    lines += ["", "每个意图里，A 和 B 你更喜欢哪个？为什么？", ""]
    (out / "listen.md").write_text("\n".join(lines), encoding="utf-8")


def write_reveal(out: pathlib.Path, rows: list[dict], totals: dict) -> None:
    lines = ["# 生成探针 · 揭晓", "", f"{totals['run']} · {totals['model']} · 随机种子 {totals['seed']}", "",
             "| 段 | 哪一版 | 硬检查 | 约束词做到几条 | 输入 / 输出 token | 用时 |", "|---|---|---|---|---|---|"]
    for r in rows:
        ver = "意图 + 约束词" if r["constrained"] else "只给意图"
        hard = f"过（调用 {len(r['calls'])} 次）" if not r["hard_errors"] else f"没过：{r['hard_errors'][:2]}"
        cons = f"{sum(ok for _, ok in r['constraints'])}/6" if "constraints" in r else "——"
        secs = sum(c.get("seconds") or 0 for c in r["calls"])
        lines.append(f"| {r['label']} | {ver} | {hard} | {cons} | {r['prompt_tokens']:,} / {r['completion_tokens']:,} | {secs:.0f} 秒 |")
    lines += ["", f"合计：输入 {totals['prompt_tokens']:,} + 输出 {totals['completion_tokens']:,} token · "
                  f"约 ${totals['usd']:.3f}（¥{totals['cny']:.2f}）· 整次 {totals['wall_seconds']:.0f} 秒（4 段并行）", ""]
    for r in rows:
        if "metrics" not in r:
            continue
        lines += [f"## {r['label']} ·「{r.get('title')}」", "", f"模型自己的说法：{r.get('idea')}", "",
                  "约束词：" + " · ".join(f"{name}{'✓' if ok else '✗'}" for name, ok in r["constraints"]), "",
                  "| 量了什么 | 数 |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in r["metrics"].items()]
        lines.append("")
    lines += ["这些数只是量出来的，**不判好坏** —— 好不好听只有你的耳朵能判（PRD §2、§8.2）。", ""]
    (out / "reveal.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fill":
        raise SystemExit(fill(sys.argv[2]))
    raise SystemExit(main())
