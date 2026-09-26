# -*- coding: utf-8 -*-
"""M0-05 · SynthV 这一轮的监视程序：你在 SynthV 里操作，我这边的动作全自动。

时间线：
  1. 等你运行「SV-Agent 导出现状」—— 它的输出文件出现，就说明工程在 SynthV 里开着了。
     顺带验证导出脚本第 2 版：必须读出 8 个音、和标准答案一致（M0-04 里第 1 版读成了 0 个）
  2. 过 2 秒，**在磁盘上改这个工程**：速度 97.5 → 120，第一个字「今」→「明」
     （原子写：先写临时文件再替换，SynthV 不会读到半个文件）
  3. 等你在 SynthV 里改最后一个字「啊」→「哦」并保存
  4. 读你保存后的文件，看三样东西：
        速度是 97.5 还是 120      → 我的外部改动在不在
        第一个字是「今」还是「明」 → 同上
        最后一个字是不是「哦」     → 你的改动在不在
     我的改动没了、你的在 → **静悄悄地盖掉了**（最坏也最常见的情况）

结果写到 out/svp_result.json。最多等 30 分钟。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(HERE, "..", "m0-04-svp"))
import compare  # noqa: E402
import verify_recovery  # noqa: E402

SVP = os.path.join(OUT, "m0_05.svp")
DUMP = SVP + ".dump.json"
TIMEOUT_S = 60 * float(sys.argv[1]) if len(sys.argv) > 1 else 30 * 60   # 参数：最多等几分钟


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def load_svp(path):
    return json.loads(open(path, "rb").read().rstrip(b"\x00").decode("utf-8"))


def external_edit():
    """在磁盘上改：速度 → 120，第一个字 → 明。原子写。"""
    d = load_svp(SVP)
    d["time"]["tempo"][0]["bpm"] = 120.0
    notes = d["tracks"][0]["mainGroup"]["notes"]
    notes[0]["lyrics"] = "明"
    tmp = SVP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, SVP)


def main():
    spec = json.load(open(compare.SPEC, encoding="utf-8"))
    result = {"started": time.strftime("%H:%M:%S")}
    t0 = time.time()
    print(f"开始监视 {result['started']}：等 {os.path.basename(DUMP)}", flush=True)

    # 只认监视开始之后才写出来的导出文件 —— 旧文件不算信号
    while not (os.path.exists(DUMP) and os.path.getmtime(DUMP) > t0):
        if time.time() - t0 > TIMEOUT_S:
            result["timed_out"] = "等导出现状"
            break
        time.sleep(1)
    else:
        time.sleep(1)
        dump = json.loads(open(DUMP, "rb").read().decode("utf-8"))
        bad = compare.diff(spec, dump)
        result["dump_v2"] = {"at": time.strftime("%H:%M:%S"), "script": dump.get("script"),
                             "notes": len(dump["tracks"][0]["notes"]) if dump.get("tracks") else 0,
                             "groups": sorted({n.get("group", "?") for t in dump.get("tracks", []) for n in t["notes"]}),
                             "mismatches": bad}
        print(f"  {result['dump_v2']['at']} 导出脚本第 2 版：读出 {result['dump_v2']['notes']} 个音，"
              f"{'和标准答案一致' if not bad else f'{len(bad)} 处不一致'}", flush=True)

        time.sleep(2)
        external_edit()
        h_ext, t_ext = sha(SVP), time.time()
        result["external_edit_at"] = time.strftime("%H:%M:%S")
        print(f"  {result['external_edit_at']} 已在磁盘上改：速度 120、第一个字「明」。等你保存……", flush=True)

        stable = None
        while time.time() - t0 <= TIMEOUT_S:
            if os.path.getmtime(SVP) > t_ext and sha(SVP) != h_ext:
                size = os.path.getsize(SVP)
                if stable and stable[0] == size and time.time() - stable[1] >= 2:
                    break
                stable = stable if stable and stable[0] == size else (size, time.time())
            time.sleep(1)
        else:
            result["timed_out"] = "等你保存"

        if "timed_out" not in result:
            d = load_svp(SVP)
            notes = verify_recovery.as_dump(d)["tracks"][0]["notes"]
            saved = {"at": time.strftime("%H:%M:%S"), "bpm": d["time"]["tempo"][0]["bpm"],
                     "first": notes[0]["lyrics"] if notes else None,
                     "last": notes[-1]["lyrics"] if notes else None, "notes": len(notes),
                     "where": sorted({n["group"] for n in notes})}
            mine_kept = saved["bpm"] == 120.0 and saved["first"] == "明"
            mine_gone = saved["bpm"] == 97.5 and saved["first"] == "今"
            yours_kept = saved["last"] == "哦"
            saved["verdict"] = ("我的外部改动被静悄悄盖掉了，你的改动在" if mine_gone and yours_kept else
                                "两边的改动都在（SynthV 重新读了磁盘上的文件）" if mine_kept and yours_kept else
                                "其他情况，看原始数据")
            result["saved"] = saved
            print(f"  {saved['at']} 你保存了：速度 {saved['bpm']} · 第一个字「{saved['first']}」"
                  f"· 最后一个字「{saved['last']}」→ {saved['verdict']}", flush=True)

    with open(os.path.join(OUT, "svp_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
