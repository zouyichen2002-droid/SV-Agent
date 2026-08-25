# -*- coding: utf-8 -*-
"""把一首原创歌写进当前打开的 SynthV 工程。

**默认 dry-run，不碰 SynthV。** 要真写必须显式加 `--write`。

## 桥做不到、必须人工的三件事

1. **新建工程** —— 64 个动作里没有任何 new/open/save project。人工 `文件 → 新建`。
2. **指派声库** —— `set_group_voice` 只有 loudness/tension/breathiness/gender/toneShift
   五个参数，**没有 database 字段**。新轨没声库就是静音（实测踩过）。
3. **保存** —— 桥写入只在内存。不按 Ctrl+S 就不落盘；这在验证阶段是安全特性。

## 桥能做的，本脚本按顺序做

- `set_time_axis` 设 tempo 与拍号（要 `get_time_axis` 的 expectedFingerprint 做守卫）
- `add_track` 建新轨（不需要 contextId，新建对象没有既存状态要守卫）
- `add_notes` 写音符，**`grouping="target"`** 全部落在主组
  （默认的 ensureNonMain 会让每一批新建一个组，实测 6 批变 7 个组）
  contextId 藏在 `get_track_notes(writeIntent)` 的 `groups[i].contextId`，不在顶层

## 写入前的守卫

- 音符先过[八项检查](../toolkit/svagent/compose/checks.py)，有 block 就拒绝写
- 核对当前工程名，与 `--expect` 不符就中止（防写错工程）
- 秒→blicks 用桥的 `convert_time` 并**验证线性**，不自己按 tempo 算

用法:
    python scripts/write_song.py                      # dry-run
    python scripts/write_song.py --write              # 真写
    python scripts/write_song.py --write --expect 未命名   # 指定工程名子串
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "out"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent.bridge import Bridge, BridgeError, decode_notes
from svagent.compose import CheckCfg, note_name, run_all, summarize

CLI_JS = Path(r"E:\SV_MCP\dist\src\cli.js")
BATCH = 60


def blick_map(b: Bridge, probes=(0.0, 5.0, 15.0, 30.0)):
    """秒 → blicks 的仿射映射，并验证线性（单一 tempo 才成立）。"""
    pts = []
    for s in probes:
        r = b.call("sv_query", {"action": "convert_time", "args": {"seconds": s}})
        blk = r.get("blicks")
        if blk is None:
            raise BridgeError(f"convert_time({s}) 没返回 blicks: {r}")
        pts.append((s, float(blk)))
    (s0, b0), (s1, b1) = pts[0], pts[-1]
    k = (b1 - b0) / (s1 - s0)
    worst = max(abs(bb - (b0 + k * (ss - s0))) for ss, bb in pts) / k
    print(f"  秒→blicks {k:.1f} blicks/s，线性残差 {worst*1000:.4f}ms")
    if worst >= 0.001:
        raise BridgeError("时间轴非线性，本脚本未实现逐音符换算")
    return lambda sec: int(round(b0 + k * (sec - s0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song-module", default="melody_v1",
                    help="out/ 下的旋律模块名")
    ap.add_argument("--track-name", default=None)
    ap.add_argument("--expect", default=None,
                    help="要求当前工程名含此子串；不给则只提示不拦")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    mod = __import__(a.song_module)
    notes, phrases, text = mod.build()
    bpm = mod.BPM
    key_root, key_quality = mod.KEY_ROOT, mod.KEY_QUALITY
    name = a.track_name or "宇宙无边无垠_主旋律_v1"

    cfg = CheckCfg()
    fs = run_all(notes, text, key_root, key_quality, phrases, cfg)
    print(f"=== 写入前自检 ===")
    print("  " + summarize(fs).replace("\n", "\n  "))
    blocks = [f for f in fs if f.severity == "block"]
    if blocks:
        print("\n  有 block，拒绝写入：")
        for f in blocks:
            print("   ", f)
        return 1

    pitches = [n.midi for n in notes]
    dur_beats = max(n.onset_beats + n.duration_beats for n in notes)
    print(f"\n=== 计划写入 ===")
    print(f"  新轨「{name}」")
    print(f"  {len(notes)} 个音符　音域 {note_name(min(pitches))}–{note_name(max(pitches))}"
          f"　跨度 {dur_beats:.0f} 拍 = {dur_beats*60/bpm:.1f} 秒")
    print(f"  tempo {bpm:.0f} BPM · 4/4")
    if not a.write:
        print("\n  dry-run，没有碰 SynthV。确认后加 --write。")
        return 0

    print("\n=== 连接桥 ===")
    with Bridge(CLI_JS, timeout_s=90) as b:
        st = b.call("sv_status")
        if not st.get("connected"):
            print(f"  桥未连接：{st.get('reason')}")
            print("  在 SynthV 里执行 脚本 → SynthV Agent Bridge → "
                  "Start SynthV Agent Bridge")
            return 2
        info = b.call("sv_query", {"action": "get_project_info"})
        fname = str(info.get("fileName") or "")
        tracks_before = int(info.get("trackCount") or 0)
        print(f"  已连接　工程「{fname or '(未命名/未保存)'}」　现有 {tracks_before} 条轨")
        if a.expect and a.expect not in fname:
            print(f"  ⚠ 工程名不含 {a.expect!r}，中止")
            return 3
        cur = (info.get("tempoAtStart") or {}).get("bpm")
        print(f"  当前 tempo {cur}")

        # 1) tempo 与拍号
        if cur is None or abs(float(cur) - bpm) > 1e-6:
            ta = b.call("sv_query", {"action": "get_time_axis",
                                     "contextMode": "writeIntent"})
            fp = ta.get("expectedFingerprint") or ta.get("fingerprint")
            args = {"tempoMarks": [{"position": 0, "bpm": bpm}],
                    "measureMarks": [{"measure": 0, "numerator": 4,
                                      "denominator": 4}]}
            if fp:
                args["expectedFingerprint"] = fp
            r = b.call("sv_command", {"action": "set_time_axis", "args": args})
            print(f"  set_time_axis → {bpm:.0f} BPM 4/4　verified={r.get('verified')}")
        else:
            print(f"  tempo 已是 {bpm:.0f}，跳过")

        to_blicks = blick_map(b)

        # 2) 建轨
        b.call("sv_command", {"action": "add_track", "args": {"name": name}})
        after = b.call("sv_query", {"action": "list_tracks"})
        tl = after.get("tracks") or []
        idx = next((i + 1 for i, t in enumerate(tl)
                    if str(t.get("name")) == name), len(tl))
        print(f"  建轨「{name}」→ 轨 {idx}（原有 {tracks_before} 条）")

        # 3) contextId 在组的作用域上，不在顶层
        wr = b.call("sv_query", {"action": "get_track_notes",
                                 "args": {"trackIndex": idx},
                                 "contextMode": "writeIntent"})
        grp = (wr.get("groups") or [{}])[0]
        cid = grp.get("contextId")
        g_onset = int(grp.get("onset") or 0)
        if not isinstance(cid, str) or not cid:
            print(f"  ✗ 拿不到组的 contextId（groups[0] 键: {sorted(grp)}）")
            return 4
        print(f"  contextId {cid}　组起点 {g_onset} blicks")

        spb = 60.0 / bpm
        payload = []
        for n in notes:
            on = to_blicks(n.onset_beats * spb) - g_onset
            off = to_blicks((n.onset_beats + n.duration_beats) * spb) - g_onset
            payload.append({"onset": on, "duration": max(1, off - on),
                            "pitch": int(n.midi), "lyrics": n.lyric})
        if any(p["onset"] < 0 for p in payload):
            print("  ✗ 有音符的组内起点为负，中止")
            return 5

        for k in range(0, len(payload), BATCH):
            chunk = payload[k:k + BATCH]
            if k:
                wr = b.call("sv_query", {"action": "get_track_notes",
                                         "args": {"trackIndex": idx},
                                         "contextMode": "writeIntent"})
                cid = ((wr.get("groups") or [{}])[0]).get("contextId") or cid
            r = b.call("sv_command", {
                "action": "add_notes",
                "args": {"trackIndex": idx, "groupIndex": 1,
                         "grouping": "target", "notes": chunk},
                "contextId": cid})
            print(f"  add_notes 批 {k//BATCH+1}: {len(chunk)} 个　"
                  f"verified={r.get('verified')}")

        # 4) 回读校验（音符在 groups[].notes 里，noteCount 才是总数）
        chk = b.call("sv_query", {"action": "get_track_notes",
                                  "args": {"trackIndex": idx, "limit": 5000}})
        gs = chk.get("groups") or []
        total = sum(int(g.get("noteCount") or 0) for g in gs)
        got = [n for g in gs for n in decode_notes(g)]
        print(f"\n  回读 noteCount={total}（期望 {len(notes)}）　组数 {chk.get('groupCount')}")
        bad = [(n.get("pitch"), n.get("lyrics")) for n, w in zip(got, notes)
               if int(n.get("pitch", -1)) != w.midi or str(n.get("lyrics")) != w.lyric]
        print(f"  逐字段比对：{len(got)-len(bad)}/{len(got)} 一致"
              + ("" if not bad else f"　✗ 不一致 {bad[:5]}"))

    print("\n" + "=" * 62)
    print("需要你手动做的三件事（桥做不到）：")
    print(f"  1. 给轨 {idx}「{name}」指派声库 星尘 —— 不指派就是静音")
    print("  2. 把 out/listen_yuzhou/参考_click和声.wav 拖进来当音频轨")
    print("  3. 试听。满意再 Ctrl+S；不满意撤销或不保存")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
