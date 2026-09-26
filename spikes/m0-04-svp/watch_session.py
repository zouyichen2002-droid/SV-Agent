# -*- coding: utf-8 -*-
"""M0-04 实测的监视程序：你在 SynthV 里操作，它在后台等结果、自动核对。

等两样东西出现：
  1. out/m0_04.svp.dump.json   你运行「SV-Agent 导出现状」之后出现 → 跑 compare.py 的比对
  2. out/render/ 里的 WAV       你点「导出为文件」之后出现 → 等它写完（大小 3 秒不变），再检查

WAV 检查三件事：
  · 在不在预设的位置、叫不叫预设的名字 —— 这证明 SynthV 认了工程里预填的 renderConfig
  · 是不是有声音（峰值高于 -40 dBFS）
  · 有声音的那一段有多长 —— 应该接近 12 拍 @ 97.5 BPM = 7.385 秒

另外记下测试工程在实测前后的哈希：变了，说明你在 SynthV 里保存过它。
结果写到 out/session_result.json。最多等 30 分钟。

用法：python watch_session.py
"""
from __future__ import annotations

import array
import glob
import hashlib
import json
import os
import sys
import time
import wave

import compare

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SVP = os.path.join(OUT, "m0_04.svp")
DUMP = SVP + ".dump.json"
RENDER = os.path.join(OUT, "render")
TIMEOUT_S = 30 * 60


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def wav_report(path, expected_s):
    with wave.open(path, "rb") as w:
        ch, bits, sr, n = w.getnchannels(), w.getsampwidth() * 8, w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if bits != 16:
        return {"path": path, "channels": ch, "bits": bits, "sample_rate": sr, "seconds": n / sr,
                "note": "不是 16-bit，没做响度分析"}
    x = array.array("h", raw)
    thr = int(32768 * 0.01)   # -40 dBFS
    loud = [i for i in range(0, len(x), ch) if max(abs(x[i + c]) for c in range(ch)) > thr]
    peak = max((abs(v) for v in x), default=0) / 32768
    active = (loud[-1] - loud[0]) / ch / sr if loud else 0.0
    return {"path": path, "name": os.path.basename(path), "channels": ch, "bits": bits,
            "sample_rate": sr, "seconds": round(n / sr, 3), "peak": round(peak, 4),
            "silent": not loud, "active_start_s": round(loud[0] / ch / sr, 3) if loud else None,
            "active_seconds": round(active, 3), "expected_music_seconds": round(expected_s, 3)}


def main():
    spec = json.load(open(compare.SPEC, encoding="utf-8"))
    before = sha(SVP)
    wavs_before = set(glob.glob(os.path.join(RENDER, "*.wav")))
    result = {"svp_sha_before": before, "started": time.strftime("%H:%M:%S")}
    print(f"开始监视 {time.strftime('%H:%M:%S')}：等 {os.path.basename(DUMP)} 和 render/ 里的新 WAV")
    t0, sizes = time.time(), {}
    while time.time() - t0 < TIMEOUT_S:
        if "dump" not in result and os.path.exists(DUMP):
            time.sleep(1)
            dump = json.loads(open(DUMP, "rb").read().decode("utf-8"))
            bad = compare.diff(spec, dump)
            result["dump"] = {"at": time.strftime("%H:%M:%S"), "mismatches": bad,
                              "tracks": len(dump.get("tracks", [])),
                              "notes": [len(t["notes"]) for t in dump.get("tracks", [])],
                              "tempo": dump.get("tempo"), "meter": dump.get("meter")}
            print(f"  {result['dump']['at']} 收到导出现状：{'完全一致' if not bad else f'{len(bad)} 处不一致'}")
        if "wav" not in result:
            for p in set(glob.glob(os.path.join(RENDER, "*.wav"))) - wavs_before:
                s = os.path.getsize(p)
                prev = sizes.get(p)
                sizes[p] = (s, prev[1] if prev and prev[0] == s else time.time())
                if s > 44 and time.time() - sizes[p][1] >= 3:
                    result["wav"] = wav_report(p, spec["expected_seconds"])
                    result["wav"]["at"] = time.strftime("%H:%M:%S")
                    print(f"  {result['wav']['at']} 收到 WAV：{result['wav']['name']}")
                    break
        if "dump" in result and "wav" in result:
            break
        time.sleep(2)
    result["timed_out"] = not ("dump" in result and "wav" in result)
    result["svp_saved_by_synthv"] = sha(SVP) != before
    with open(os.path.join(OUT, "session_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0)


if __name__ == "__main__":
    main()
