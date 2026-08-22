# -*- coding: utf-8 -*-
"""把一段验证用的音符写进本地 SynthV 工程，供人实听。

**默认 dry-run，不碰 SynthV。** 要真写必须显式加 `--write`。

## 这一段验证的是什么，不验证什么

**验的**：阶段 1 的音高证据层。音高与时长全部来自「两个以上跨族估计器互相确认」
的帧，没有证据的地方直接留空。听点是「旋律对不对」。

**不验的**：歌词位置。歌词一律用中性音节 `la`。阶段 3（CTC 逐字对齐）没过，
按项目原则不能写没有依据的字 —— 上一次的可闻缺陷正是 21% 的音符从邻居抄歌词。

## 安全边界（交接文件 §3.5 / §9）

- 只 `add_track` 建**新轨**，不改任何现有轨道
- 写前 `get_project_info` 核对目标工程文件名
- 写前 `sv_query contextMode=writeIntent` 取 `contextId` 再交给 `sv_command`
- `add_notes` 每批 ≤60
- 桥**不能保存工程**。不按 Ctrl+S 就不落盘 —— 验证阶段这是安全特性，
  不满意直接撤销或不保存即可
- 新轨没有声库，**必须人工指派**（`clone_track` 系列在 2.2.1 上会崩，已禁用）

用法:
    python scripts/write_verify_slice.py                  # dry-run + 生成试听
    python scripts/write_verify_slice.py --write          # 真写入
    python scripts/write_verify_slice.py --from 58.32 --to 75.68
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svchain import config, notes as N
from svchain.align import stage1
from svchain.bridge import Bridge, BridgeError

CLI_JS = Path(r"E:\SV_MCP\dist\src\cli.js")
SR_OUT = 44100
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BATCH = 60


def note_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def audition(ns: list[N.Note], song, t0: float, t1: float, out: Path) -> None:
    """量化后的音符合成正弦 vs 干声。这才是 SynthV 会唱的东西。"""
    ref, sr = sf.read(str(song.vocals), always_2d=True)
    if sr != SR_OUT:
        raise SystemExit(f"干声 {sr}Hz != {SR_OUT}")
    ref = ref.mean(axis=1)
    i0, i1 = int(t0 * SR_OUT), min(int(t1 * SR_OUT), ref.size)
    left = ref[i0:i1]
    left = left / max(1e-9, np.abs(left).max()) * 0.6
    right = np.zeros_like(left)
    for nt in ns:
        a = int((nt.onset_s - t0) * SR_OUT)
        b = min(a + int(nt.duration_s * SR_OUT), right.size)
        if b <= a:
            continue
        f = 440.0 * 2 ** ((nt.midi - 69) / 12)
        t = np.arange(b - a) / SR_OUT
        env = np.minimum(1.0, np.minimum(t, (b - a) / SR_OUT - t) / 0.01)
        right[a:b] += np.sin(2 * np.pi * f * t) * np.clip(env, 0, 1) * 0.22
    a = np.stack([left, right], axis=1)
    pk = float(np.abs(a).max())
    if pk > 0.99:
        a *= 0.99 / pk
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), a, SR_OUT, subtype="PCM_16")
    print(f"  试听写出 {out}  ({(i1-i0)/SR_OUT:.1f}s)")


def blick_map(b: Bridge, probes=(0.0, 10.0, 60.0, 120.0, 200.0)):
    """秒 → blicks 的仿射映射，并**验证线性**（tempo 恒定才成立）。"""
    pts = []
    for s in probes:
        r = b.call("sv_query", {"action": "convert_time", "args": {"seconds": s}})
        blk = r.get("blicks") if isinstance(r, dict) else None
        if blk is None and isinstance(r, dict):
            for k in ("result", "value", "position"):
                if isinstance(r.get(k), dict) and "blicks" in r[k]:
                    blk = r[k]["blicks"]
                    break
        if blk is None:
            raise BridgeError(f"convert_time({s}s) 没返回 blicks: {r}")
        pts.append((s, float(blk)))
    (s0, b0), (s1, b1) = pts[0], pts[-1]
    k = (b1 - b0) / (s1 - s0)
    resid = [abs(bb - (b0 + k * (ss - s0))) for ss, bb in pts]
    worst_s = max(resid) / k
    print(f"  秒→blicks: {k:.1f} blicks/s，截距 {b0:.0f}")
    print(f"  线性性检查：{len(pts)} 个探点最大残差 {max(resid):.0f} blicks "
          f"= {worst_s*1000:.3f}ms" + ("  （tempo 恒定，仿射映射成立）"
                                       if worst_s < 0.001 else
                                       "  ⚠ 残差偏大，tempo 可能有变化，"
                                       "应逐个音符调 convert_time"))
    return (lambda sec: int(round(b0 + k * (sec - s0)))), worst_s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="chaosheng")
    ap.add_argument("--from", dest="t0", type=float, default=58.32)
    ap.add_argument("--to", dest="t1", type=float, default=75.68)
    ap.add_argument("--write", action="store_true", help="真正写入 SynthV")
    ap.add_argument("--track-name", default=None)
    a = ap.parse_args()

    cfg = config.load()
    song = cfg.song(a.song)
    song.require("vocals")
    P = cfg.pitch
    name = a.track_name or f"验证-阶段1音高-{a.t0:.0f}到{a.t1:.0f}s-中性音节"

    print(f"曲目 {song.title}   区间 {a.t0:.2f}–{a.t1:.2f}s")
    em = stage1(cfg, song).evidence
    ns, gaps, drop = N.build(em.f0_hz, P.hop_s, a.t0, a.t1, n_agree=em.n_agree)
    print("\n=== 音符构建 ===")
    print("  " + N.summarize(ns, gaps).replace("\n", "\n  "))
    print("  剔除: " + str({k: v for k, v in drop.items() if v}))
    if not ns:
        print("没有可写的音符。")
        return 1

    print("\n=== 试听（写入前先用耳朵过一遍）===")
    out = Path(__file__).resolve().parents[1] / "out" / f"listen_{a.song}"
    audition(ns, song, a.t0, a.t1, out / f"05_待写入音符_{a.t0:.0f}-{a.t1:.0f}s.wav")

    print("\n=== 计划写入 ===")
    print(f"  新轨名称: {name}")
    print(f"  音符 {len(ns)} 个，歌词全部 'la'（中性，见脚本 docstring）")
    print(f"  音高 {note_name(min(n.midi for n in ns))}–"
          f"{note_name(max(n.midi for n in ns))}")
    if not a.write:
        print("\n  这是 dry-run，没有碰 SynthV。确认后加 --write。")
        return 0

    print("\n=== 连接桥 ===")
    with Bridge(CLI_JS, timeout_s=60) as b:
        st = b.call("sv_status")
        if not st.get("connected"):
            print(f"  桥未连接：{st.get('reason')}")
            print("  请在 SynthV 里执行 脚本 → SynthV Agent Bridge → "
                  "Start SynthV Agent Bridge（菜单里没有就先 脚本 → 重新扫描）")
            return 2
        print(f"  已连接  host {st['status']['host']['hostVersion']}  "
              f"ageMs {st.get('ageMs')}")

        info = b.call("sv_query", {"action": "get_project_info"})
        fname = str(info.get("fileName") or info.get("projectFile") or "")
        print(f"  目标工程 {fname}")
        if "潮声回响-86BPM" not in fname:
            print("  ⚠ 工程文件名与预期不符，中止（交接文件 §9.6：别写错工程）")
            return 3

        to_blicks, _ = blick_map(b)

        ctx = b.call("sv_query", {"action": "list_tracks",
                                  "contextMode": "writeIntent"})
        cid = ctx.get("contextId")
        before = ctx.get("tracks") or []
        print(f"  contextId {cid}   现有轨道 {len(before)} 条")

        print("\n=== 写入 ===")
        b.call("sv_command", {"action": "add_track", "args": {"name": name},
                             "contextId": cid})
        after = b.call("sv_query", {"action": "list_tracks",
                                    "contextMode": "writeIntent"})
        cid = after.get("contextId", cid)
        tracks = after.get("tracks") or []
        idx = next((i + 1 for i, t in enumerate(tracks)
                    if str(t.get("name")) == name), len(tracks))
        print(f"  建轨完成，trackIndex={idx}（共 {len(tracks)} 条）")

        payload = [{"onset": to_blicks(n.onset_s),
                    "duration": max(1, to_blicks(n.onset_s + n.duration_s)
                                    - to_blicks(n.onset_s)),
                    "pitch": int(n.midi), "lyrics": n.lyric} for n in ns]
        for k in range(0, len(payload), BATCH):
            chunk = payload[k:k + BATCH]
            r = b.call("sv_command", {
                "action": "add_notes",
                "args": {"trackIndex": idx, "groupIndex": 1, "notes": chunk},
                "contextId": cid})
            print(f"  add_notes 批 {k//BATCH+1}: {len(chunk)} 个  "
                  f"verified={r.get('verified')}")

        chk = b.call("sv_query", {"action": "get_track_notes",
                                  "args": {"trackIndex": idx}})
        from svchain.bridge import decode_notes
        got = decode_notes(chk)
        print(f"\n  回读 {len(got)} 个音符（期望 {len(ns)}）")

    print("\n" + "=" * 60)
    print("接下来需要你手动做两件事（桥做不到）：")
    print("  1. 给新轨指派声库（星尘）。新建轨道没有声库，桥不能设。")
    print("  2. 试听。**满意再 Ctrl+S，不满意直接撤销或不保存** —— 桥的写入只在内存。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
