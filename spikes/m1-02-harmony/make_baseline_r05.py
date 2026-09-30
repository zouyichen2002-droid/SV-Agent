# -*- coding: utf-8 -*-
"""把《傍晚》人声扒谱 r05 存成只读的基线（创作者 09-29：「这版最好保护一下」）。

- 复制：r05 的两个工程（原来的留给创作者手改）、r05 / r04 的音、r01 的 MIDI、basic-pitch 的原样输出
- 清单 manifest.json：输入（路径、校验码）、工具版本、参数、分数、基线里每个文件的校验码、生成它的仓库提交
- 基线里的文件全部设成只读；已经有基线就拒绝（不覆盖）

    python make_baseline_r05.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
sys.path.insert(0, str(HERE.parent / "m1-03-lyrics"))
import compare_notes as C  # noqa: E402
import lyric_align as LA  # noqa: E402
import make_r02 as M  # noqa: E402
import make_round_svp as R  # noqa: E402
import pick_octave as P  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROUND = R.ROUNDS / "r05"
BASE = ROUND / "基线_只读"
R01_MID = pathlib.Path("E:/sv-agent-data/probes/m1-01-voice-to-midi/m1-01_v2m_asr.mid")
LYRICS = pathlib.Path("E:/sv-agent-data/learn/01-傍晚/lyrics_原文.txt")
V2M = pathlib.Path("E:/sv-agent-data/tools/Vocal2Midi")
TOOLS = pathlib.Path("E:/sv-agent-data/tools")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*args: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8").stdout.strip()


def main() -> int:
    if BASE.exists():
        raise SystemExit(f"{BASE} 已经有了 —— 基线不覆盖")
    BASE.mkdir(parents=True)
    copies = {
        "傍晚_扒谱_r05.svp": ROUND / "傍晚_扒谱_r05.svp",
        "傍晚_扒谱_r05_对比终稿.svp": ROUND / "傍晚_扒谱_r05_对比终稿.svp",
        "r05_notes.json": M.OUT / "r05_notes.json",
        "r04_notes.json": pathlib.Path("E:/sv-agent-data/probes/m1-03-lyrics/r04_notes.json"),
        "r01_只听写.mid": R01_MID,
        "basic_pitch_raw_newstem.json": M.BP_RAW,
    }
    for name, src in copies.items():
        shutil.copy2(src, BASE / name)
    r05 = [tuple(x) for x in json.loads((BASE / "r05_notes.json").read_text(encoding="utf-8"))]
    tr = C.tracks(C.load_svp(M.FINAL))
    lead, harm = tr["vocal1"], tr["和声1"]
    a, b = harm[0][0] - 0.5, harm[-1][0] + harm[-1][1] + 0.5
    upper = sorted([n for n in lead if not (a <= n[0] <= b)] + harm)
    m1, m2 = C.compare(lead, r05), C.compare(upper, r05)
    stem = pathlib.Path(R.VOCAL_STEM)
    man = {
        "说明": "《傍晚》人声扒谱 r05 —— 创作者 09-29：「太棒了，这版基本没问题了！剩下有限个可以创作者手改！这版最好保护一下」",
        "创作者手改用": str(ROUND / "傍晚_扒谱_r05_对比终稿.svp"),
        "代码": {"仓库提交": git("rev-parse", "HEAD", cwd=HERE), "标签": "m1-melody-r05-baseline",
               "回归检查": "spikes/m1-02-harmony/regress_r05.py（vocal2midi 环境）"},
        "输入": {
            "人声分轨": {"路径": str(stem), "字节": stem.stat().st_size, "sha256": sha(stem)},
            "歌词": {"路径": str(LYRICS), "sha256": sha(LYRICS)},
            "终稿（只用来打分）": {"路径": M.FINAL, "sha256": sha(pathlib.Path(M.FINAL))},
        },
        "工具": {
            "Vocal2Midi": {"提交": git("rev-parse", "--short", "HEAD", cwd=V2M), "模式": "只听写（--asr），D3PM 8 步，不量化，歌词拼音"},
            "GAME 模型": {"文件": "GAME-1.0.3-medium-onnx.zip", "sha256": sha(V2M / "models" / "GAME-1.0.3-medium-onnx.zip")},
            "HubertFA 模型": {"文件": "1218_hfa_model_new_dict.zip", "sha256": sha(V2M / "models" / "1218_hfa_model_new_dict.zip")},
            "Qwen3-ASR": {f.name: f.stat().st_size for f in (V2M / "models" / "Qwen3-ASR-1.7B-dml").glob("*.gguf")},
            "llama.cpp（给 Qwen3-ASR 解码）": {"文件": "llama-b9174-bin-win-vulkan-x64.zip",
                                           "sha256": sha(TOOLS / "llama-b9174-bin-win-vulkan-x64.zip")},
            "basic-pitch": "pi-audio 环境（E:/sv-agent-data/envs/pi-audio）里 pi_audio.extract_notes",
        },
        "参数": {
            "修歌词": {"空位最短秒": LA.SLOT_MIN_SEC, "拆音最短秒": 0.3, "打分": [LA.MATCH, LA.NEAR, LA.DIFF, LA.GAP]},
            "叠唱检测": {"覆盖": M.MIN_COVER, "强弱比": M.MIN_RATIO, "往下放频谱门槛_dB": M.DOWN_MARGIN_DB,
                     "音域余量": M.RANGE_SLACK, "连着至少": M.MIN_RUN, "句内间隔秒": M.MAX_GAP},
            "挑八度": {"规则": "叠唱句整句取上 + 单独掉下去的 1–3 个拉回来", "掉下去至少半音": P.DIP_MIN,
                    "拉回来后差不超过": P.DIP_FIT, "最多连着": P.DIP_MAXLEN, "句内间隔秒": P.DIP_GAP},
        },
        "分数": {"对终稿主唱": {"F1": m1["F1"], "八度错误": m1["八度错误"]},
               "对主唱_1:56-2:14用和声1": {"F1": m2["F1"], "八度错误": m2["八度错误"]}},
    }
    man["基线文件的校验码"] = {n: sha(BASE / n) for n in copies}
    (BASE / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in BASE.iterdir():
        os.chmod(p, stat.S_IREAD)
    print(f"基线：{BASE}（{len(copies)} 个文件 + manifest.json，全部只读）")
    print(f"分数：对终稿主唱 F1 {m1['F1']}；对「主唱，1:56–2:14 用和声1」F1 {m2['F1']}、八度错 {m2['八度错误']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
