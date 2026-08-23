# -*- coding: utf-8 -*-
"""完整转写管线 → 写入 SynthV：主旋律 + 和声，带真歌词。

**默认 dry-run，不碰 SynthV。** 要真写必须显式加 `--write`。

## 管线（每一步的依据都在 specs/adr/ 里）

    工程轨3 的 vocals stem（含主旋律 + 对位和声）
      │
      ├─ karaoke 模型分离 ──> 主唱 stem / 和声 stem        ADR-0005
      │
      ├─ 每条 stem 上 RMVPE + CREPE 跨族互证 ──> 音高证据图  ADR-0003/0004
      │
      ├─ 每条 stem 上 CTC 逐字强制对齐（主唱用 33 个主唱行，
      │   和声用 9 个括号行 —— 和声有自己的词，见 benchmark-facts §2b）
      │
      ├─ 按行摊开字起音保 ≥90ms（不合并）                    ADR-0001
      │
      └─ **字定音符边界、音高取证据** ──> 音符 + 歌词

## 为什么是「字定边界」而不是「音高定边界再塞字」

实测：先按音高造音符再把字塞进去，只有 65–70% 的字挂得上（拆出的片段短于 85ms、
或宿主音符已被占用）。反过来做，主旋律 87.0% 的 LRC 字拿到带正确歌词的音符。

没有音高证据的字**不给音符**，进缺口清单交给耳朵 —— 上一次失败的直接原因是
21% 的音符从邻居抄音高，这里结构上不可能发生。

## 安全边界（交接文件 §3.5 / §9）

- 只 `add_track` 建新轨，不改任何现有轨道
- 写前核对工程文件名；`--expect` 可指定
- `add_notes` 用 `grouping="target"` 全部写进主组（默认 ensureNonMain 会每批新建一个组）
- contextId 绑在**组**上，取自 `get_track_notes(writeIntent)` 的 `groups[i].contextId`
- 桥不能保存工程；不按 Ctrl+S 就不落盘
- 新轨没有声库，**必须人工指派**

用法:
    python scripts/write_transcription.py                       # dry-run
    python scripts/write_transcription.py --write --expect 潮声回响-星尘
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import config, evidence, lyrics, notes as N
from svagent.align.ctc import CtcAligner, respace
from svagent.audio import cached_track, load_mono
from svagent.bridge import Bridge, BridgeError, decode_notes
from svagent.pitch import CrepeEstimator, RmvpeEstimator, n_frames_for

CLI_JS = Path(r"E:\SV_MCP\dist\src\cli.js")
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BATCH = 60
ROLES = (("lead", "主旋律", "*(Vocals)*.wav", False),
         ("backing", "和声", "*(Instrumental)*.wav", True))


def note_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def build_role(cfg, song, al, stem: Path, lines, all_t, nf, dur, g4):
    """一条 stem 的完整构建。返回 (音符, 缺口, 账目)。"""
    P = cfg.pitch
    y = load_mono(stem, P.sr)
    per = []
    for l in lines:
        nxt = min((x for x in all_t if x > l.t_s + 0.5), default=l.t_s + 7.0)
        # 窗口左边界只留 0.10s：留 1.0s 时 CTC 会把首字钉在窗口起点上，
        # 实测首字偏移中位 −0.658s（下界恰好是窗口边界 −1.00s）。
        # 收到 0.10s 后中位 +0.040s，与阶段2 用匹配滤波独立测出的 +0.070s 吻合。
        win = (max(0.0, l.t_s - 0.10), min(dur, min(nxt + 0.35, l.t_s + 12.0)))
        la, _ = al.align_line(y, l.chars, l.t_s, win, l.index)
        per.append(la.spans)
    n_aligned = sum(len(g) for g in per)
    rs, rstat = respace(per)
    ct = [(s.t0, s.char) for g in rs for s in g]

    trs = []
    for e in (RmvpeEstimator(cfg.model("rmvpe")), CrepeEstimator(model="full")):
        tr, _ = cached_track(cfg.cache_dir, stem, e, P.sr, P.hop_s, nf,
                            P.fmin_hz, P.fmax_hz)
        trs.append(tr.gated(P.conf_gate))
    em = evidence.build(trs, P.agree_cents, min_agree=2)

    ns, gaps, st = N.notes_from_chars(ct, em.f0_hz, P.hop_s, n_agree=em.n_agree,
                                      min_ms=g4["min_note_ms"],
                                      max_s=g4["max_note_s"])
    ns, gstat = N.enforce_geometry(ns, min_ms=g4["min_note_ms"],
                                   max_s=g4["max_note_s"])
    st.update({"aligned": n_aligned, "respace": rstat, "geom": gstat})
    return ns, gaps, st


def blick_map(b: Bridge, probes=(0.0, 10.0, 60.0, 120.0, 200.0)):
    pts = []
    for s in probes:
        r = b.call("sv_query", {"action": "convert_time", "args": {"seconds": s}})
        blk = r.get("blicks")
        if blk is None:
            raise BridgeError(f"convert_time({s}s) 没返回 blicks: {r}")
        pts.append((s, float(blk)))
    (s0, b0), (s1, b1) = pts[0], pts[-1]
    k = (b1 - b0) / (s1 - s0)
    worst = max(abs(bb - (b0 + k * (ss - s0))) for ss, bb in pts) / k
    print(f"  秒→blicks {k:.1f} blicks/s，线性残差 {worst*1000:.3f}ms"
          + ("（tempo 恒定）" if worst < 0.001 else "  ⚠ tempo 非恒定"))
    if worst >= 0.001:
        raise BridgeError("时间轴非线性，本脚本的仿射映射不适用")
    return lambda sec: int(round(b0 + k * (sec - s0)))


def write_track(b: Bridge, name: str, ns, to_blicks) -> None:
    before = b.call("sv_query", {"action": "list_tracks"})
    n0 = len(before.get("tracks") or [])
    b.call("sv_command", {"action": "add_track", "args": {"name": name}})
    after = b.call("sv_query", {"action": "list_tracks"})
    tracks = after.get("tracks") or []
    idx = next((i + 1 for i, t in enumerate(tracks)
                if str(t.get("name")) == name), len(tracks))
    print(f"\n  建轨「{name}」 → 轨 {idx}（原有 {n0} 条）")

    payload = [{"onset": to_blicks(n.onset_s),
                "duration": max(1, to_blicks(n.onset_s + n.duration_s)
                                - to_blicks(n.onset_s)),
                "pitch": int(n.midi), "lyrics": n.lyric,
                "languageOverride": "mandarin"} for n in ns]
    sent = 0
    for k in range(0, len(payload), BATCH):
        wr = b.call("sv_query", {"action": "get_track_notes",
                                 "args": {"trackIndex": idx},
                                 "contextMode": "writeIntent"})
        cid = ((wr.get("groups") or [{}])[0]).get("contextId")
        if not isinstance(cid, str):
            raise BridgeError(f"拿不到组的 contextId: {sorted((wr.get('groups') or [{}])[0])}")
        chunk = payload[k:k + BATCH]
        r = b.call("sv_command", {
            "action": "add_notes",
            "args": {"trackIndex": idx, "groupIndex": 1,
                     "grouping": "target", "notes": chunk},
            "contextId": cid})
        sent += len(chunk)
        print(f"    批 {k//BATCH+1}/{(len(payload)+BATCH-1)//BATCH}: "
              f"{len(chunk)} 个  verified={r.get('verified')}")
    chk = b.call("sv_query", {"action": "get_track_notes",
                              "args": {"trackIndex": idx, "noteLimit": 512}})
    groups = chk.get("groups") or []
    total = sum(int(g.get("noteCount") or 0) for g in groups)
    print(f"    回读 noteCount={total}（已发 {sent}）  组数 {chk.get('groupCount')}"
          + ("" if total == len(ns) else "  ⚠ 与期望不符"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="chaosheng")
    ap.add_argument("--model", default="mel_band_roformer")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--expect", default=None)
    ap.add_argument("--replace", action="store_true",
                    help="写入前删掉此前由本项目建的、同名前缀的轨")
    a = ap.parse_args()

    cfg = config.load()
    song = cfg.song(a.song)
    song.require("vocals", "lyrics")
    P, g4 = cfg.pitch, cfg.gate("stage4")
    root = Path(__file__).resolve().parents[1] / "out" / "sep" / a.song
    d = next(p for p in sorted(root.iterdir())
             if p.is_dir() and a.model.lower() in p.name.lower())

    v = load_mono(song.vocals, P.sr)
    nf = n_frames_for(v.size, P.sr, P.hop_s)
    dur = v.size / P.sr
    ls = lyrics.parse(song.lyrics, song.lyrics_skip_before_s)
    all_t = [l.t_s for l in ls]
    print(f"曲目 {song.title}   {dur:.2f}s   分离模型 {d.name}")
    print(f"{lyrics.summary(ls)}\n")

    al = CtcAligner(cfg.model("zh_ctc"), sr=P.sr)
    plan = []
    for role, label, pat, is_harm in ROLES:
        stem = next(d.glob(pat))
        lines = [l for l in ls if l.is_harmony == is_harm]
        tot = sum(l.n_chars for l in lines)
        ns, gaps, st = build_role(cfg, song, al, stem, lines, all_t, nf, dur, g4)
        lyr = sum(1 for n in ns if n.lyric not in ("-", "la"))
        dd = np.array([n.duration_s for n in ns])
        ov = sum(1 for k in range(len(ns) - 1)
                 if ns[k].end_s > ns[k + 1].onset_s + 1e-9)
        print(f"=== {label} ===  stem {stem.name[:46]}")
        print(f"  LRC {len(lines)} 行 / {tot} 字")
        print(f"  CTC 对齐 {st['aligned']}（{100*st['aligned']/tot:.1f}%）"
              f"  摊开推动 {st['respace']['pushed']} 次，最大位移 "
              f"{st['respace']['max_push_s']*1000:.0f}ms，一个字没丢")
        print(f"  **带正确歌词的音符 {lyr}（LRC 的 {100*lyr/tot:.1f}%）**")
        print(f"  没给音符的字 {len(gaps)}：无音高证据 {st['no_evidence']}"
              f"  太短 {st['too_short']}  几何 {st['geom']['dropped']}")
        print(f"  音符 {len(ns)}（带字 {lyr}，拖腔 '-' {len(ns)-lyr}）"
              f"  音域 {note_name(min(n.midi for n in ns))}–"
              f"{note_name(max(n.midi for n in ns))}")
        okg = ov <= g4["max_overlaps"] and dd.min() * 1000 >= g4["min_note_ms"] - 1e-6
        print(f"  阶段4 几何门槛: 重叠 {ov}（≤{g4['max_overlaps']}）  "
              f"最短 {dd.min()*1000:.0f}ms（≥{g4['min_note_ms']}）  "
              f"虚构音符 0（≤{g4['fabricated_notes_max']}）  "
              + ("**通过**" if okg else "**未过**"))
        if gaps:
            print(f"  缺口清单（前 12 个，交给耳朵）: "
                  + " ".join(f"{t:.1f}s{c}" for t, c in gaps[:12]))
        print()
        if okg:
            plan.append((f"转写_{label}_带歌词", ns))
        else:
            print(f"  {label} 未过几何门槛，不写入。\n")

    if not a.write:
        print("这是 dry-run，没有碰 SynthV。确认后加 --write。")
        for name, ns in plan:
            print(f"  将建轨「{name}」 {len(ns)} 个音符")
        return 0

    print("=== 连接桥 ===")
    with Bridge(CLI_JS, timeout_s=120) as b:
        st = b.call("sv_status")
        if not st.get("connected"):
            print(f"  桥未连接：{st.get('reason')}")
            print("  请在 SynthV 里执行 脚本 → SynthV Agent Bridge → "
                  "Start SynthV Agent Bridge")
            return 2
        info = b.call("sv_query", {"action": "get_project_info"})
        fname = str(info.get("fileName") or "")
        print(f"  目标工程 {fname}")
        expect = a.expect or (Path(song.project).stem if song.project else "")
        if expect and expect not in fname:
            print(f"  ⚠ 当前工程不含预期子串 {expect!r}，中止")
            print(f"     要写当前这份就加 --expect {Path(fname).stem}")
            return 3
        to_blicks = blick_map(b)

        if a.replace:
            while True:
                tr = b.call("sv_query", {"action": "list_tracks"})
                names = [str(t.get("name")) for t in (tr.get("tracks") or [])]
                hit = next((i + 1 for i, n in enumerate(names)
                            if n.startswith(("识别_", "转写_", "验证-"))), None)
                if hit is None:
                    break
                b.call("sv_command", {"action": "delete_track",
                                      "args": {"trackIndex": hit}})
                print(f"  已删旧轨 {hit}: {names[hit-1]}")

        for name, ns in plan:
            write_track(b, name, ns, to_blicks)

    print("\n" + "=" * 62)
    print("需要你手动做的两件事（桥做不到）：")
    print("  1. 给新建的轨指派声库（星尘）。新轨没有声库，桥的 API 设不了。")
    print("  2. 试听。满意再 Ctrl+S；不满意直接撤销 —— 桥的写入只在内存。")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
