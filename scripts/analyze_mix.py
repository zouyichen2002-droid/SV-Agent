# -*- coding: utf-8 -*-
"""分析一条渲染出来的混音，给可执行的混音判断。**不需要 loopMIDI。**

## 为什么有这个

FL 的混音层本来要靠 flstudio-mcp，但那需要 loopMIDI（内核级虚拟 MIDI 驱动）。
不过 MCP 里有两个函数是**纯文件分析、不碰 FL** 的：

    audio_analyze   tempo / key / beats / onsets
    analyze_bands   rms_db / peak_db / 低中高三段能量占比

所以流程可以是：**用户从 FL 导出 wav → 这个脚本分析 → 我给逐条混音指令 →
用户在 FL 里手动执行**。全程不需要驱动。

## 走 flmcp 那个 env，不走主环境

这两个函数依赖 librosa + numba，装在隔离的 Python 3.12 env 里
（主环境是 3.13）。所以用子进程调过去，不在主环境重复装一套。

**不要经 MCP 调**：每个 MCP 子进程都要重新预热 numba，实测 120s 还没跑完；
直连 11s。MCP 那层在这件事上不带来任何价值。

## 这些数字能说明什么、不能说明什么

`bands_pct` 是 <250Hz / 250–4000Hz / >4000Hz 三段的能量占比。
**它只在真实音源渲染出来的音频上有意义。** 正弦预览（`伴奏预览_v2.wav`）
测出来低频占 92%，那是正弦没有泛音的结果，不是编排有问题。

`key` 是估计值，模块自己标注「~60-80% 准确，可能混淆关系大小调」——
拿它做交叉验证可以，当判据不行。

用法:
    python scripts/analyze_mix.py <混音.wav>
    python scripts/analyze_mix.py <混音.wav> --ref <参考曲.wav>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FLMCP_PY = Path(r"G:\miniconda\envs\flmcp\python.exe")
FLMCP_REPO = Path(r"E:\FL_MCP")

_PROBE = r"""
import json, sys
from fl_studio_mcp.tools.audio import audio_analyze, analyze_bands
out = {}
for p in sys.argv[1:]:
    try:
        out[p] = {"bands": analyze_bands(p), "musical": audio_analyze(p)}
    except Exception as e:
        out[p] = {"error": f"{type(e).__name__}: {e}"}
print("@@JSON@@" + json.dumps(out, default=str))
"""


def probe(paths: list[Path]) -> dict:
    """在 flmcp env 里跑分析。慢的是 numba 预热，第二次会快很多。"""
    if not FLMCP_PY.exists():
        raise SystemExit(f"找不到 {FLMCP_PY}")
    r = subprocess.run([str(FLMCP_PY), "-c", _PROBE, *map(str, paths)],
                       cwd=str(FLMCP_REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    for line in r.stdout.splitlines():
        if line.startswith("@@JSON@@"):
            return json.loads(line[len("@@JSON@@"):])
    raise SystemExit(f"分析失败。stderr 尾部:\n{r.stderr[-800:]}")


# 参考区间。来源是这次分析要服务的目标：一首人声在前的慢速流行/氛围曲。
# 这些是**经验区间，不是硬门槛** —— 超出只说明值得看一眼，不等于错。
GUIDE = {
    "peak_db": (-6.0, -0.3, "母带前留 headroom；贴 0 会在后续处理里削顶"),
    "rms_db":  (-20.0, -12.0, "整体电平。太低推不起来，太高没有动态"),
    "low":     (20.0, 45.0, "<250Hz 占比。过高糊，过低单薄"),
    "mid":     (40.0, 70.0, "250–4000Hz 占比。人声就在这一段"),
    "high":    (5.0, 25.0, "> 4000Hz 占比。过低发闷，过高刺"),
}


def verdict(name: str, v: float) -> str:
    lo, hi, why = GUIDE[name]
    if v < lo:
        return f"低于经验区间 {lo}–{hi}　{why}"
    if v > hi:
        return f"高于经验区间 {lo}–{hi}　{why}"
    return f"在经验区间 {lo}–{hi} 内"


def report(path: Path, d: dict) -> None:
    if "error" in d:
        print(f"  ✗ {d['error']}")
        return
    b, m = d["bands"], d["musical"]
    print(f"  时长 {b['duration_sec']:.1f}s　"
          f"tempo {m.get('tempo_bpm')}　"
          f"key {(m.get('key') or {}).get('key')}"
          f"（置信度 {(m.get('key') or {}).get('confidence')}，估计值）")
    print(f"  onsets {m.get('onsets')}　beats {m.get('beats')}")
    print()
    for k, v in (("peak_db", b["peak_db"]), ("rms_db", b["rms_db"])):
        print(f"  {k:8} {v:7.1f} dB　{verdict(k, v)}")
    for k in ("low", "mid", "high"):
        v = b["bands_pct"][k]
        edge = b["band_edges_hz"][k]
        print(f"  {k:8} {v:6.1f}%　({edge} Hz)　{verdict(k, v)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mix", help="从 FL 导出的混音 wav")
    ap.add_argument("--ref", default=None, help="参考曲 wav（可选）")
    a = ap.parse_args()

    mix = Path(a.mix)
    if not mix.exists():
        raise SystemExit(f"找不到 {mix}")
    paths = [mix] + ([Path(a.ref)] if a.ref else [])
    for p in paths:
        if not p.exists():
            raise SystemExit(f"找不到 {p}")
    # 子进程的 cwd 是 FL_MCP，相对路径会解析到那边 —— 必须先转绝对
    paths = [p.resolve() for p in paths]
    mix = paths[0]

    print(f"分析 {len(paths)} 个文件（首次要预热 numba，可能几十秒）...\n")
    res = probe(paths)

    print("=" * 66)
    print(f"混音　{mix}")
    print("=" * 66)
    report(mix, res[str(mix)])

    if a.ref:
        ref = paths[1]          # 同一个 resolve 之后的路径，否则查不到
        print()
        print("=" * 66)
        print(f"参考　{ref}")
        print("=" * 66)
        report(ref, res[str(ref)])
        m, r = res[str(mix)], res[str(ref)]
        if "error" not in m and "error" not in r:
            print("\n差值（混音 − 参考）：")
            print(f"  rms_db  {m['bands']['rms_db'] - r['bands']['rms_db']:+.1f} dB")
            print(f"  peak_db {m['bands']['peak_db'] - r['bands']['peak_db']:+.1f} dB")
            for k in ("low", "mid", "high"):
                d = m["bands"]["bands_pct"][k] - r["bands"]["bands_pct"][k]
                print(f"  {k:6}  {d:+.1f} 个百分点")
            print("\n  差值比绝对值可靠 —— 参考曲替你定义了'这个风格该是什么样'。")

    print("\n" + "=" * 66)
    print("提醒：bands_pct 只在真实音源渲染的音频上有意义。")
    print("正弦预览测出低频 92% 是正弦没泛音，不是编排问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
