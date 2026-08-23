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

from svagent import config, evidence, notes as N
from svagent.align import from_stems
from svagent.audio import cached_track, load_mono
from svagent.bridge import Bridge, BridgeError, decode_notes
from svagent.pitch import CrepeEstimator, RmvpeEstimator, n_frames_for

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


def mix_support_mask(cfg, mixed: np.ndarray, f0_hz: np.ndarray,
                     tol_bins: int = 3, abs_thr: float = 0.06):
    """逐帧判断：这个 f0 在**原始混合信号**的 RMVPE 显著图上有没有局部峰支持。

    这是 ADR-0005 的回代检验，裁判是混合信号本身，不依赖任何分离器的判决。
    《潮声回响》实测：主唱 stem 支持率 91.4%，**和声 stem 只有 51.7%** ——
    约一半的和声音高在原始信号里根本没有对应峰，是分离器造出来的。
    """
    from svagent.pitch.base import hz_to_cents
    from svagent.pitch.rmvpe_est import CENTS_BASE, CENTS_PER_BIN

    est = RmvpeEstimator(cfg.model("rmvpe"))
    est._load()
    sal = est._salience(est._mel(mixed, cfg.pitch.sr))
    c = hz_to_cents(f0_hz)
    ok = np.isfinite(c)
    b = np.round(np.where(ok, (c - CENTS_BASE) / CENTS_PER_BIN, 0.0)).astype(int)
    n = min(sal.shape[0], f0_hz.size)
    out = np.zeros(f0_hz.size, dtype=bool)
    for i in range(n):
        if not ok[i]:
            continue
        lo = max(0, b[i] - tol_bins)
        hi = min(sal.shape[1], b[i] + tol_bins + 1)
        if hi <= lo:
            continue
        w = sal[i, lo:hi]
        if w.max() < abs_thr:
            continue
        j = lo + int(np.argmax(w))
        l = sal[i, j - 1] if j > 0 else 0.0
        r = sal[i, j + 1] if j + 1 < sal.shape[1] else 0.0
        if sal[i, j] >= l and sal[i, j] >= r:
            out[i] = True
    return out


def filter_by_activity(ns: list, act_mask: np.ndarray, hop_s: float,
                       min_frac: float = 0.2):
    """只保留与**人声活动**有交集的音符。

    为什么回代检验不够（实测教训）：回代检验问的是「这个音高在混合信号里有没有峰」，
    器乐渗漏在混合 vocals stem 里是**真实存在的能量**，所以它照样通过。
    karaoke 模型会把输入里的器乐渗漏路由到 "instrumental"（和声）输出，
    于是和声轨在 3.22s / 4.11s / 7.00s 这些**已测定无人声**的位置长出音符。

    人声活动掩码用的是 vocals stem 绝对电平 + vocals/no_vocals 能量比，
    与回代检验是不同信息源，两条一起才能同时排除「不存在的音高」和「不是人声的音高」。

    阈值取 0.2 而不是 0.5：活动掩码在乐句边缘偏保守，要求过半会砍掉真音符
    （实测主旋律有 16% 的音符在掩码之外，但其中 0 个落在无人声段 —— 那些是边缘效应）。
    """
    keep, drop = [], []
    for nt in ns:
        i0 = int(round(nt.onset_s / hop_s))
        i1 = min(int(round((nt.onset_s + nt.duration_s) / hop_s)), act_mask.size)
        seg = act_mask[i0:i1]
        frac = float(seg.mean()) if seg.size else 0.0
        (keep if frac >= min_frac else drop).append(nt)
    return keep, drop


def filter_by_support(ns: list, support: np.ndarray, hop_s: float,
                      min_frac: float = 0.6):
    """只保留「跨度内 ≥min_frac 的帧都被原始混合信号支持」的音符。"""
    keep, drop = [], []
    for nt in ns:
        i0 = int(round(nt.onset_s / hop_s))
        i1 = int(round((nt.onset_s + nt.duration_s) / hop_s))
        i1 = min(i1, support.size)
        seg = support[i0:i1]
        frac = float(seg.mean()) if seg.size else 0.0
        (keep if frac >= min_frac else drop).append(nt)
    return keep, drop


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
    ap.add_argument("--expect", default=None,
                    help="要求当前工程文件名含此子串，防写错工程。"
                         "默认取配置里 song.project 的文件名主干")
    ap.add_argument("--no-mix-filter", action="store_true",
                    help="不对和声做回代过滤（会写入分离器幻觉，只用于对照试听）")
    ap.add_argument("--no-activity-filter", action="store_true",
                    help="不做人声活动约束（会写入器乐渗漏，只用于对照）")
    ap.add_argument("--activity-min", type=float, default=0.2,
                    help="音符跨度与人声活动掩码的交集下限")
    ap.add_argument("--support-min", type=float, default=0.6,
                    help="回代过滤阈值：音符跨度内被原始混合信号支持的帧占比下限")
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
        print("  " + N.summarize(ns, gaps).replace("\n", "\n  "))
        print("  剔除: " + str({k: q for k, q in drop.items() if q}))
        unfiltered = list(ns)
        # 两条轨都过人声活动约束：排除「不是人声」的音高（器乐渗漏）
        if not a.no_activity_filter:
            nv = load_mono(song.no_vocals, P.sr)
            act = from_stems(v, nv, P.hop_len, P.hop_s, nf,
                             rms_db_min=cfg.align.act_rms_db_min,
                             ratio_db_min=cfg.align.act_ratio_db_min,
                             close_s=cfg.align.act_close_s,
                             open_s=cfg.align.act_open_s)
            ns, off = filter_by_activity(ns, act.mask, P.hop_s, a.activity_min)
            pre = [x for x in off if x.onset_s < song.lyrics_skip_before_s]
            print(f"  人声活动约束（与活动掩码交集 ≥{100*a.activity_min:.0f}%）:")
            print(f"    保留 {len(ns)} / 剔除 {len(off)}"
                  f"，其中 {len(pre)} 个落在已测定的无人声段（器乐渗漏）")
        if role == "backing" and not a.no_mix_filter:
            # 和声必须过回代检验。实测支持率只有 51.7%，不过滤就是写一半幻觉。
            sup = mix_support_mask(cfg, v, em.f0_hz)
            ns, dropped = filter_by_support(ns, sup, P.hop_s, a.support_min)
            print(f"  回代过滤（要求跨度内 ≥{100*a.support_min:.0f}% 的帧被"
                  f"原始混合信号支持）:")
            print(f"    保留 {len(ns)} / 剔除 {len(dropped)}"
                  f"（{100*len(dropped)/max(1,len(unfiltered)):.0f}% 被判为分离器幻觉）")
            if ns:
                print("    " + N.summarize(ns, gaps).replace("\n", "\n    "))
        built[role] = {"em": em, "notes": ns, "gaps": gaps,
                       "unfiltered": unfiltered}
        print()

    if not any(built[r]["notes"] for r, _ in ROLES):
        print("两条都没有可写的音符。")
        return 1

    out = Path(__file__).resolve().parents[1] / "out" / f"listen_{a.song}"
    audition(built, song, t0, t1,
             out / f"07_待写入_过滤后_{t0:.0f}-{t1:.0f}s.wav")
    # 再出一版和声不过滤的，让耳朵自己判那批被剔掉的到底像不像和声
    raw = {r: {"notes": built[r]["unfiltered"]} for r, _ in ROLES}
    audition(raw, song, t0, t1,
             out / f"07_待写入_和声未过滤_{t0:.0f}-{t1:.0f}s.wav")

    print("\n=== 计划写入 ===")
    plan = []
    for role, label in ROLES:
        ns = built[role]["notes"]
        if not ns:
            print(f"  {label}: 没有音符，跳过")
            continue
        short = "RoFormer" if "roformer" in tag.lower() else "MDX"
        suffix = "" if (role == "lead" or a.no_mix_filter) else "-已过回代检验"
        name = f"识别_{label}{suffix}_{short}_中性音节"
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
        expect = a.expect or (Path(song.project).stem if song.project else "")
        if expect and expect not in fname:
            print(f"  ⚠ 当前工程不含预期子串 {expect!r}，中止（交接文件 §9.6：别写错工程）")
            print(f"     要写当前这份就加 --expect {Path(fname).stem}")
            return 3
        print(f"  工程校验通过（要求含 {expect!r}）")
        to_blicks = blick_map(b)

        for name, ns in plan:
            before = b.call("sv_query", {"action": "list_tracks"})
            n_before = len(before.get("tracks") or [])
            # add_track 不需要 contextId：新建轨道没有既存对象要守卫。
            # 注意不能传 contextId=None —— schema 要 string，传 null 会被校验拒绝。
            b.call("sv_command", {"action": "add_track", "args": {"name": name}})
            after = b.call("sv_query", {"action": "list_tracks"})
            tracks = after.get("tracks") or []
            idx = next((i + 1 for i, t in enumerate(tracks)
                        if str(t.get("name")) == name), len(tracks))
            print(f"\n  建轨「{name}」 → 轨 {idx}（原有 {n_before} 条）")

            # contextId 绑定在**组**的作用域上，藏在 get_track_notes(writeIntent)
            # 的 groups[i] 里，不在顶层。上游 issue-8 文档：没有 contextId 也没有
            # 显式 fingerprint 时，写入会 fail-closed 被拒。
            gi = 1
            wr = b.call("sv_query", {"action": "get_track_notes",
                                     "args": {"trackIndex": idx},
                                     "contextMode": "writeIntent"})
            grp = (wr.get("groups") or [{}])[0]
            cid = grp.get("contextId")
            g_onset = int(grp.get("onset") or 0)
            if not isinstance(cid, str) or not cid:
                print(f"    ✗ 没拿到组的 contextId，跳过（groups[0] 键: "
                      f"{sorted(grp)}）")
                continue
            print(f"    contextId {cid}   组起点 {g_onset} blicks")

            payload = [{"onset": to_blicks(n.onset_s) - g_onset,
                        "duration": max(1, to_blicks(n.onset_s + n.duration_s)
                                        - to_blicks(n.onset_s)),
                        "pitch": int(n.midi), "lyrics": n.lyric} for n in ns]
            bad = [p for p in payload if p["onset"] < 0]
            if bad:
                print(f"    ✗ {len(bad)} 个音符的组内起点为负，跳过本轨")
                continue
            ok = 0
            for k in range(0, len(payload), BATCH):
                chunk = payload[k:k + BATCH]
                # 每批前重取 contextId：上游明确一个 contextId 的复用有边界，
                # 会话或目标变化后失效，旧值不得自动重试。
                if k:
                    wr = b.call("sv_query", {"action": "get_track_notes",
                                             "args": {"trackIndex": idx},
                                             "contextMode": "writeIntent"})
                    cid = ((wr.get("groups") or [{}])[0]).get("contextId") or cid
                r = b.call("sv_command", {
                    "action": "add_notes",
                    # grouping 默认是 ensureNonMain —— 那会让**每一批**都新建一个
                    # 音符组（实测 6 批变成 6 个组，main 组反而是空的）。
                    # 用 target 写进指定组，全部音符落在同一个主组里。
                    "args": {"trackIndex": idx, "groupIndex": gi,
                             "grouping": "target", "notes": chunk},
                    "contextId": cid})
                ok += len(chunk)
                print(f"    批 {k//BATCH+1}/{(len(payload)+BATCH-1)//BATCH}: "
                      f"{len(chunk)} 个  verified={r.get('verified')}")
            # get_track_notes 把音符放在 groups[].notes 里，不在顶层；
            # 且 noteCount 是真实总数，notes 受 noteLimit 分页限制。
            chk = b.call("sv_query", {"action": "get_track_notes",
                                      "args": {"trackIndex": idx,
                                               "noteLimit": 512}})
            groups = chk.get("groups") or []
            total = sum(int(g.get("noteCount") or 0) for g in groups)
            ret = sum(len(decode_notes(g)) for g in groups)
            print(f"    回读 noteCount={total}（已发 {ok}，期望 {len(ns)}）"
                  f"  组数 {chk.get('groupCount')}  本次返回 {ret} 个明细"
                  + ("" if total == len(ns) else "  ⚠ 与期望不符"))

    print("\n" + "=" * 62)
    print("需要你手动做的两件事（桥做不到）：")
    print("  1. 给新建的两条轨指派声库（星尘）。新轨没有声库，桥不能设。")
    print("  2. 试听。**满意再 Ctrl+S；不满意直接撤销或不保存** —— 桥的写入只在内存。")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
