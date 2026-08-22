# -*- coding: utf-8 -*-
"""把分离出的 主旋律 / 和声 各建一条新轨写进本地 SynthV 工程，供人实听。

**默认 dry-run，不碰 SynthV。** 要真写必须显式加 `--write`。

## 这一轮验什么，不验什么

**验的**：分离 + 单声部音高的组合结果。每条轨的音高只来自它自己那条 stem 上
两个跨族估计器（RMVPE + CREPE）互相确认的帧，没有证据的地方留空。
听点是「主旋律像不像主旋律、和声轨里是不是真的和声」。

**不验的**：歌词。两条轨都用中性音节 `la`。
用户已拍板「和声沿用主旋律同位置的字」，但那需要主旋律的**逐字**时刻，
即阶段 3（CTC 逐字对齐）—— 还没做。现在写字就是没有依据地写，
正是上一次失败的那个错（21% 音符从邻居抄歌词）。

好消息是分离之后 CTC 的输入变干净了（主唱 stem 不再混着和声），
阶段 3 的成功率应该比在混合 stem 上更高。

## 安全边界（交接文件 §3.5 / §9）

- 只 `add_track` 建**新轨**（会落在现有 4 条之后，即轨 5、6…），不改任何现有轨道
- 写前 `get_project_info` 核对目标工程文件名，不符就中止
- 写前 `sv_query contextMode=writeIntent` 取 `contextId` 再交给 `sv_command`
- `add_notes` 每批 ≤60
- 桥**不能保存工程**。不按 Ctrl+S 就不落盘 —— 不满意直接撤销
- 新轨没有声库，**必须人工指派**（`clone_track` 系列在 2.2.1 上会崩，上游已禁用）

用法:
    python scripts/write_voice_tracks.py                    # dry-run + 试听
    python scripts/write_voice_tracks.py --write            # 真写入
    python scripts/write_voice_tracks.py --model UVR_MDXNET_KARA_2
    python scripts/write_voice_tracks.py --from 58 --to 76  # 只做一段
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svchain import config, evidence, notes as N
from svchain.audio import cached_track, load_mono
from svchain.bridge import Bridge, BridgeError, decode_notes
from svchain.pitch import CrepeEstimator, RmvpeEstimator, n_frames_for

CLI_JS = Path(r"E:\SV_MCP\dist\src\cli.js")
SR_OUT = 44100
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BATCH = 60
ROLES = (("lead", "主旋律"), ("backing", "和声"))


def note_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def find_stems(song_id: str, model: str | None):
    root = Path(__file__).resolve().parents[1] / "out" / "sep" / song_id
    if not root.is_dir():
        raise SystemExit(f"没有分离结果，先跑 scripts/separate_voices.py（{root}）")
    dirs = [p for p in sorted(root.iterdir()) if p.is_dir()]
    if model:
        dirs = [p for p in dirs if model.lower() in p.name.lower()]
    if not dirs:
        raise SystemExit(f"没匹配到模型 {model!r}，可选 "
                         f"{[p.name for p in sorted(root.iterdir()) if p.is_dir()]}")
    d = dirs[0]
    got: dict[str, Path] = {}
    for f in d.glob("*.wav"):
        n = f.name.lower()
        # 输出名形如 vocals_(Instrumental)_<model>.wav —— 里面也含 "vocals"，
        # 必须按带括号的标记匹配且先判 instrumental
        if "(instrumental)" in n:
            got["backing"] = f
        elif "(vocals)" in n:
            got["lead"] = f
    if len(got) != 2:
        raise SystemExit(f"{d.name} 里缺 stem: 只找到 {sorted(got)}")
    return d.name, got


def evidence_for(cfg, path: Path, nf: int):
    P = cfg.pitch
    trs = []
    for e in (RmvpeEstimator(cfg.model("rmvpe")), CrepeEstimator(model="full")):
        tr, hit = cached_track(cfg.cache_dir, path, e, P.sr, P.hop_s, nf,
                              P.fmin_hz, P.fmax_hz)
        if not hit:
            print(f"      （{tr.name} 重算）")
        trs.append(tr.gated(P.conf_gate))
    return evidence.build(trs, P.agree_cents, min_agree=2)


def audition(built: dict, song, t0: float, t1: float, out: Path) -> None:
    """左=原始混合人声，右=两条轨的音符合成（主旋律与和声用不同音色区分）。"""
    ref, sr = sf.read(str(song.vocals), always_2d=True)
    if sr != SR_OUT:
        raise SystemExit(f"干声 {sr}Hz != {SR_OUT}")
    ref = ref.mean(axis=1)
    i0, i1 = int(t0 * SR_OUT), min(int(t1 * SR_OUT), ref.size)
    left = ref[i0:i1]
    left = left / max(1e-9, np.abs(left).max()) * 0.55
    right = np.zeros_like(left)
    # 主旋律用正弦，和声用带三次谐波的方波感音色，听上去能分开
    for role, _ in ROLES:
        harm = (1.0,) if role == "lead" else (1.0, 0.0, 0.35)
        amp = 0.26 if role == "lead" else 0.20
        for nt in built[role]["notes"]:
            a = int((nt.onset_s - t0) * SR_OUT)
            b = min(a + int(nt.duration_s * SR_OUT), right.size)
            if b <= a or a < 0:
                continue
            f = 440.0 * 2 ** ((nt.midi - 69) / 12)
            t = np.arange(b - a) / SR_OUT
            env = np.clip(np.minimum(t, (b - a) / SR_OUT - t) / 0.012, 0, 1)
            w = sum(g * np.sin(2 * np.pi * f * (k + 1) * t)
                    for k, g in enumerate(harm) if g)
            right[a:b] += w * env * amp
    a = np.stack([left, right], axis=1)
    pk = float(np.abs(a).max())
    if pk > 0.99:
        a *= 0.99 / pk
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), a, SR_OUT, subtype="PCM_16")
    print(f"  试听写出 {out.name}  ({(i1-i0)/SR_OUT:.1f}s)")


def blick_map(b: Bridge, probes=(0.0, 10.0, 60.0, 120.0, 200.0)):
    """秒 → blicks 的仿射映射，并验证线性（tempo 恒定才成立）。"""
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
    worst = max(abs(bb - (b0 + k * (ss - s0))) for ss, bb in pts) / k
    print(f"  秒→blicks {k:.1f} blicks/s，线性残差最大 {worst*1000:.3f}ms"
          + ("（tempo 恒定）" if worst < 0.001 else "  ⚠ tempo 可能有变化"))
    if worst >= 0.001:
        raise BridgeError("时间轴非线性，需逐音符调 convert_time，本脚本未实现")
    return lambda sec: int(round(b0 + k * (sec - s0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="chaosheng")
    ap.add_argument("--model", default="mel_band_roformer")
    ap.add_argument("--from", dest="t0", type=float, default=None)
    ap.add_argument("--to", dest="t1", type=float, default=None)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    cfg = config.load()
    song = cfg.song(a.song)
    song.require("vocals")
    P = cfg.pitch
    tag, stems = find_stems(a.song, a.model)

    v = load_mono(song.vocals, P.sr)
    nf = n_frames_for(v.size, P.sr, P.hop_s)
    t0 = 0.0 if a.t0 is None else a.t0
    t1 = v.size / P.sr if a.t1 is None else a.t1
    print(f"曲目 {song.title}   分离模型 {tag}   区间 {t0:.2f}–{t1:.2f}s\n")

    built: dict[str, dict] = {}
    for role, label in ROLES:
        print(f"=== {label}（{role}）===")
        print(f"  stem {stems[role].name}")
        em = evidence_for(cfg, stems[role], nf)
        ns, gaps, drop = N.build(em.f0_hz, P.hop_s, t0, t1, n_agree=em.n_agree)
        built[role] = {"em": em, "notes": ns, "gaps": gaps}
        print("  " + N.summarize(ns, gaps).replace("\n", "\n  "))
        print("  剔除: " + str({k: q for k, q in drop.items() if q}))
        print()

    if not any(built[r]["notes"] for r, _ in ROLES):
        print("两条都没有可写的音符。")
        return 1

    out = Path(__file__).resolve().parents[1] / "out" / f"listen_{a.song}"
    audition(built, song, t0, t1,
             out / f"07_待写入_{tag}_{t0:.0f}-{t1:.0f}s.wav")

    print("\n=== 计划写入 ===")
    plan = []
    for role, label in ROLES:
        ns = built[role]["notes"]
        if not ns:
            print(f"  {label}: 没有音符，跳过")
            continue
        name = f"识别_{label}_{tag[:18]}_中性音节"
        plan.append((name, ns))
        print(f"  新轨「{name}」  {len(ns)} 个音符  "
              f"{note_name(min(n.midi for n in ns))}–"
              f"{note_name(max(n.midi for n in ns))}  歌词全 'la'")
    if not a.write:
        print("\n  这是 dry-run，没有碰 SynthV。确认后加 --write。")
        return 0

    print("\n=== 连接桥 ===")
    with Bridge(CLI_JS, timeout_s=90) as b:
        st = b.call("sv_status")
        if not st.get("connected"):
            print(f"  桥未连接：{st.get('reason')}")
            print("  请在 SynthV 里执行 脚本 → SynthV Agent Bridge → "
                  "Start SynthV Agent Bridge（菜单里没有就先 脚本 → 重新扫描）")
            return 2
        print(f"  已连接  ageMs {st.get('ageMs')}")
        info = b.call("sv_query", {"action": "get_project_info"})
        fname = str(info.get("fileName") or info.get("projectFile") or "")
        print(f"  目标工程 {fname}")
        if "潮声回响-86BPM" not in fname:
            print("  ⚠ 工程文件名与预期不符，中止")
            return 3
        to_blicks = blick_map(b)

        for name, ns in plan:
            ctx = b.call("sv_query", {"action": "list_tracks",
                                      "contextMode": "writeIntent"})
            cid = ctx.get("contextId")
            n_before = len(ctx.get("tracks") or [])
            b.call("sv_command", {"action": "add_track", "args": {"name": name},
                                 "contextId": cid})
            after = b.call("sv_query", {"action": "list_tracks",
                                        "contextMode": "writeIntent"})
            cid = after.get("contextId", cid)
            tracks = after.get("tracks") or []
            idx = next((i + 1 for i, t in enumerate(tracks)
                        if str(t.get("name")) == name), len(tracks))
            print(f"\n  建轨「{name}」 → 轨 {idx}（原有 {n_before} 条）")
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
                print(f"    批 {k//BATCH+1}/{(len(payload)+BATCH-1)//BATCH}: "
                      f"{len(chunk)} 个  verified={r.get('verified')}")
            chk = b.call("sv_query", {"action": "get_track_notes",
                                      "args": {"trackIndex": idx}})
            print(f"    回读 {len(decode_notes(chk))} 个（期望 {len(ns)}）")

    print("\n" + "=" * 62)
    print("需要你手动做的两件事（桥做不到）：")
    print("  1. 给新建的两条轨指派声库（星尘）。新轨没有声库，桥不能设。")
    print("  2. 试听。**满意再 Ctrl+S；不满意直接撤销或不保存** —— 桥的写入只在内存。")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
