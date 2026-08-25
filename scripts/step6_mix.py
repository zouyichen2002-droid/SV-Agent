# -*- coding: utf-8 -*-
"""工作流步骤 6：混音。往工程每条轨的 `mixer.fxParams` 写 EQ / 压缩 / 混响。

## 术语先说清

V 家流程最后那一步是**混音**，不是 remix。
remix 是把一首歌改编成另一个版本（换风格换速度），那是另一件事。

## 只改 `.svp`，音频文件一个字节不动

创作者 2026-08-23 选定的范围：人声链 + 和声处理。
所有改动都在 `.svp` 的 `mixer` 字段里，所以

    · 伴奏 wav 不动
    · `--clear` 一键撤销
    · 每次写前自动备份

**乐谱驱动的闪避**（按 176 个音符的精确位置压伴奏）和**母带 LUFS 归一**
需要重写音频文件，属于下一档，本脚本不做。

## 原地注入，不重建

和调教一样：读原始 JSON，只改要改的字段，其余一个字节不动。
重建会丢掉音频轨和创作者自己在 SynthV 里做过的改动。

用法:
    python scripts/step6_mix.py                          # 只看方案
    python scripts/step6_mix.py --write --closed
    python scripts/step6_mix.py --write --closed --no-carve   # 不碰伴奏 EQ
    python scripts/step6_mix.py --clear --write --closed      # 一键撤销
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import step3_melody as S3
from svagent.compose.mixing import (accompaniment_carve, describe,
                                    disable_all, harmony_behind, lead_ballad)


def classify(track: dict) -> str:
    if (track.get("mainRef") or {}).get("isInstrumental"):
        return "伴奏"
    if track.get("name", "").startswith("主旋律"):
        return "主旋律"
    if track.get("name", "").startswith("和声"):
        return "和声"
    return "其它人声"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lead-gain", type=float, default=0.0)
    ap.add_argument("--harmony-gain", type=float, default=-6.5)
    # 创作者 2026-08-25 实听《风筝线》后的判断：「歌声对比伴奏有点弱」。
    # 从 −3 降到 −6 dB。**挖槽只解决频段打架，解决不了整体音量关系**，
    # 所以必须动电平，不是再多挖一点。这类判断只有耳朵能下（事实 F17）。
    ap.add_argument("--acc-gain", type=float, default=-6.0,
                    help="伴奏轨增益 dB。默认 −6：人声要压得住伴奏")
    ap.add_argument("--no-carve", action="store_true",
                    help="不给伴奏挖人声让位槽（默认会挖，只改 .svp）")
    ap.add_argument("--clear", action="store_true", help="关掉全部 FX")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--closed", action="store_true")
    a = ap.parse_args()

    raw = json.loads(S3.PROJECT.read_text(encoding="utf-8-sig"))
    print(f"工程　{S3.PROJECT}　{len(raw['tracks'])} 条轨")
    print()

    if a.clear:
        print("撤销混音（关掉全部 FX，gain/pan 归零）：")
        for t in raw["tracks"]:
            t["mixer"] = disable_all(t["mixer"])
            print(f"  {t['name']:<18} 已关闭")
    else:
        print("混音方案：")
        for t in raw["tracks"]:
            kind = classify(t)
            if kind == "主旋律":
                mix = lead_ballad(a.lead_gain)
            elif kind == "和声":
                mix = harmony_behind(a.harmony_gain)
            elif kind == "伴奏":
                if a.no_carve:
                    print(f"  {t['name']:<18} 跳过（--no-carve）")
                    continue
                mix = accompaniment_carve(a.acc_gain)
            else:
                print(f"  {t['name']:<18} 跳过（不认识的轨型）")
                continue
            t["mixer"] = mix.apply(t["mixer"])
            print(describe(t["name"], t["mixer"]))
        print()
        print("  设计意图：")
        print("    主旋律 低切 120Hz 去泥 · 3kHz +2.5dB 吐字 · 9kHz +1.5dB 空气")
        print("    和声   切到 150Hz · **3kHz −2dB 让位** · 更湿坐后面")
        print("    伴奏   3kHz −2.5dB 给人声让出清晰度（只改 .svp，音频不动）")
        print("  伴奏实测高频只占 0.1%，所以人声提亮不会与它抢 —— "
              "这是让人声浮出来最省力的方式，比推音量干净")

    if not a.write:
        print()
        print("没有 --write，不碰工程文件。")
        return 0
    if not a.closed:
        print()
        print(f"✗ 暂不修改工程：没有确认已在 SynthV 里关闭 "
              f"{S3.PROJECT.name}。确认后加 --closed。")
        return 4
    if S3.synthv_running():
        print()
        print("✗ 检测到 SynthV 仍在运行，先退出它。")
        return 4

    bk = S3.backup(S3.PROJECT)
    print()
    print(f"已备份 → {bk}")
    S3.PROJECT.write_text(json.dumps(raw, ensure_ascii=False),
                          encoding="utf-8")
    print(f"工程写出　{S3.PROJECT}　{S3.PROJECT.stat().st_size} B")

    # 回读校验：音符与音频轨必须没动
    chk = json.loads(S3.PROJECT.read_text(encoding="utf-8-sig"))
    lib = {g["uuid"]: g for g in chk.get("library", [])}
    print()
    ok = len(chk["tracks"]) == len(raw["tracks"])
    for t in chk["tracks"]:
        n = 0
        for ref in (t.get("groups") or []):
            n += len((lib.get(ref.get("groupID")) or {}).get("notes") or [])
        has_audio = "audio" in (t.get("mainRef") or {})
        fx = (t.get("mixer") or {}).get("fxParams") or {}
        on = [k for k in ("postRoomEq", "compressor", "reverb")
              if (fx.get(k) or {}).get("enabled")]
        print(f"  ✓ {t['name']:<18} 音符 {n:3d}　"
              f"{'音频轨 ' if has_audio else ''}FX 启用 {on or '无'}")
    print(f"  轨道 {len(chk['tracks'])} 条 —— 原地注入，音频文件未动")
    print()
    print(f"打开 {S3.PROJECT} 听。")
    print("过了就 --no-carve 或调 gain；完全不要就 --clear --write --closed。")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
