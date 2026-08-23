# -*- coding: utf-8 -*-
"""工作流步骤 5 后半：基础调教。往工程的 parameters / vocalModes 注入自动化点。

## 为什么是原地注入，不是重建工程

调教是对**已有工程的修改**，不是重新装配。重建会丢掉音频轨、混音器设置、
以及创作者自己在 SynthV 里做过的任何改动。所以这里读原始 JSON，
按轨名找到对应的 library 组，只往 `parameters` / `vocalModes` 里写，
其余一个字节不动。

## 只做基础调教

目标是**去掉机械感**，不是做满。四件事，按可听度排序：

1. `pitchDelta` 的句首滑入与句末收尾（转音）—— 最能去机械感
2. `loudness` 的段落起伏 + 句内塑形
3. `tension` 跟随情绪弧线
4. `vocalModes` 的段落切换（Emotional / Power 在副歌抬起来）

**不碰** Breathiness、Voicing、音素时长/位置 —— 那几项一动容易出怪声，
属于精调，留给创作者。

和声轨用更轻的强度（`--harmony-scale`），否则和声会压过主旋律。

用法:
    python scripts/step5_tune.py                       # 只算，不写
    python scripts/step5_tune.py --write --closed
    python scripts/step5_tune.py --write --closed --scale 0.6   # 更保守
    python scripts/step5_tune.py --clear --write --closed       # 清空调教
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import step3_melody as S3
from svagent.compose.checks import Note
from svagent.compose.lyricfile import parse
from svagent.compose.tuning import (QUARTER_BLICKS, VOCAL_MODES, TuneCfg,
                                    build_tuning, describe)

TUNED_KEYS = ("pitchDelta", "loudness", "tension")


def scale_points(d: dict, k: float) -> dict:
    """按比例缩放自动化点的**值**（位置不动）。"""
    out = {}
    for name, cur in d.items():
        pts = list(cur.get("points") or [])
        for i in range(1, len(pts), 2):
            pts[i] = round(pts[i] * k, 6)
        out[name] = {"mode": cur.get("mode", "cubic"), "points": pts}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bpm", type=float, default=S3.SONG_BPM)
    ap.add_argument("--scale", type=float, default=1.0,
                    help="主旋律调教强度倍数。觉得过了就调小")
    ap.add_argument("--harmony-scale", type=float, default=0.55,
                    help="和声轨的强度倍数。和声不该压过主旋律")
    ap.add_argument("--clear", action="store_true", help="清空全部调教")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--closed", action="store_true")
    a = ap.parse_args()

    ver = parse(S3.LYRICS)[0][next(iter(parse(S3.LYRICS)[0]))]
    raw = json.loads(S3.PROJECT.read_text(encoding="utf-8-sig"))
    lib = {g["uuid"]: g for g in raw.get("library", [])}
    print(f"工程　{S3.PROJECT}")
    print(f"　　　{len(raw['tracks'])} 条轨　library {len(lib)} 组\n")

    # 轨名 → 它引用的组
    targets = []
    for t in raw["tracks"]:
        for ref in (t.get("groups") or []):
            g = lib.get(ref.get("groupID"))
            if g and (g.get("notes")):
                targets.append((t["name"], g))
    if not targets:
        print("✗ 工程里没有带音符的人声轨")
        return 1

    if a.clear:
        print("清空调教：")
        for name, g in targets:
            for k in list(g.get("parameters") or {}):
                g["parameters"][k] = {"mode": g["parameters"][k].get(
                    "mode", "cubic"), "points": []}
            g["vocalModes"] = {}
            print(f"  {name}　已清空 parameters 与 vocalModes")
    else:
        # 主旋律的段落结构从歌词 + 曲式重算；和声只覆盖部分段落，
        # 所以它按自己的音符时间去套主旋律算出来的曲线
        lead_name, lead_notes, lead_sections = S3.read_lead(
            S3.PROJECT, ver, S3.FORM)
        params, vmodes, stats = build_tuning(lead_notes, lead_sections,
                                             a.bpm, TuneCfg())
        print("基础调教（主旋律）：")
        print(describe(params, vmodes))
        print()
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print()
        for name, g in targets:
            is_lead = name.startswith("主旋律")
            k = a.scale if is_lead else a.harmony_scale
            g.setdefault("parameters", {}).update(scale_points(params, k))
            g["vocalModes"] = scale_points(vmodes, k)
            n_pts = sum(len(v["points"]) // 2
                        for v in g["parameters"].values() if v.get("points"))
            n_vm = sum(len(v["points"]) // 2 for v in g["vocalModes"].values())
            print(f"  {name:<18} 强度 ×{k:.2f}　"
                  f"parameters {n_pts} 点　vocalModes {n_vm} 点")

    if not a.write:
        print("\n没有 --write，不碰工程文件。")
        return 0
    if not a.closed:
        print(f"\n✗ 暂不修改工程：没有确认已在 SynthV 里关闭 "
              f"{S3.PROJECT.name}。确认后加 --closed。")
        return 4
    if S3.synthv_running():
        print("\n✗ 检测到 SynthV 仍在运行，先退出它。")
        return 4

    bk = S3.backup(S3.PROJECT)
    print(f"\n已备份 → {bk}")
    S3.PROJECT.write_text(json.dumps(raw, ensure_ascii=False),
                          encoding="utf-8")
    print(f"工程写出　{S3.PROJECT}　{S3.PROJECT.stat().st_size} B")

    # 回读校验：音符数不能变，调教点要写进去
    chk = json.loads(S3.PROJECT.read_text(encoding="utf-8-sig"))
    clib = {g["uuid"]: g for g in chk.get("library", [])}
    ok = True
    print()
    for name, g in targets:
        cg = clib.get(g["uuid"])
        if cg is None:
            print(f"  ✗ {name} 组丢失")
            ok = False
            continue
        same_notes = len(cg.get("notes") or []) == len(g.get("notes") or [])
        n_pts = sum(len(v.get("points") or []) // 2
                    for v in (cg.get("parameters") or {}).values())
        n_vm = sum(len(v.get("points") or []) // 2
                   for v in (cg.get("vocalModes") or {}).values())
        print(f"  {'✓' if same_notes else '✗'} {name:<18} "
              f"音符 {len(cg.get('notes') or [])}　"
              f"parameters {n_pts} 点　vocalModes {n_vm} 点")
        ok &= same_notes
    n_tracks = len(chk["tracks"])
    n_audio = sum(1 for t in chk["tracks"]
                  if (t.get("mainRef") or {}).get("isInstrumental"))
    print(f"  轨道 {n_tracks} 条（其中音频轨 {n_audio} 条）—— 原地注入，未重建")
    print(f"\n打开 {S3.PROJECT} 听。")
    print("觉得过了就 --scale 0.6 重跑；完全不要就 --clear。")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
