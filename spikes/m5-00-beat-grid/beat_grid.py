# -*- coding: utf-8 -*-
"""逆向学习的第一步：找准一首歌的**真实拍子**。拍子不准，学出来的节奏型全是错的。

三个互相独立的裁判：
1. **SynthV 自己的节拍分析** —— 存在 .svp 伴奏轨的 `audio` 里（bpm、alternativeBPMs、beatLocations）
2. **librosa** 对同一段伴奏重新做节拍跟踪
3. **人声音符的起点** —— 换到候选速度下，有多少落在网格上；同时报**随机撒点的偶然水平**
   （网格越细，±容差盖住的时间越多，随机也能「对齐」一大半 —— 不和偶然比，对齐率没有意义）

三个对上才算定。66 和 132 这种差一倍的歧义，数据分不出来 —— 交给创作者凭感觉定。

- 只读输入（云端同步目录一个字节都不写）；结果写到**仓库外**：E:/sv-agent-data/learn/<编号-曲名>/
- 先跑自检：已知速度的合成数据必须测对、随机数据不许「对齐」，不过就不跑

    python beat_grid.py "F:/我的云端硬盘/临时文件3/SV2/傍晚(星尘).svp" 01-傍晚
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
Q = 705_600_000                          # blick / 四分音符
OUT_ROOT = pathlib.Path("E:/sv-agent-data/learn")
TOL = 0.025                              # 起音离网格 ±25 ms 以内算对齐


def load_svp(p: pathlib.Path) -> dict:
    return json.loads(p.read_bytes().rstrip(b"\x00").decode("utf-8"))


def blick_to_seconds(b: float, tempo: list[dict]) -> float:
    """分段积分：速度标记 [{position, bpm}] 之间按各自的速度换算。"""
    marks = sorted(tempo, key=lambda x: x["position"])
    s, prev_pos, prev_bpm = 0.0, 0, marks[0]["bpm"]
    for m in marks[1:]:
        if m["position"] >= b:
            break
        s += (m["position"] - prev_pos) / Q * 60 / prev_bpm
        prev_pos, prev_bpm = m["position"], m["bpm"]
    return s + (b - prev_pos) / Q * 60 / prev_bpm


def voiced_notes(d: dict, track_name: str | None = None) -> list[tuple[float, float, int]]:
    """全部音符组（主组 + 音符库组，位置 = 本地起点 + 引用偏移，M0-04 的教训）→ [(起点秒, 时值秒, 音高)]。"""
    lib = {g["uuid"]: g for g in d.get("library", [])}
    out = []
    for tr in d["tracks"]:
        if tr["mainRef"].get("isInstrumental") or (track_name and tr.get("name") != track_name):
            continue
        for g, ref in [(tr["mainGroup"], tr["mainRef"])] + [(lib.get(r.get("groupID")), r) for r in tr.get("groups", [])]:
            if not g:
                continue
            off = ref.get("blickOffset", 0)
            for n in g.get("notes", []):
                a = blick_to_seconds(n["onset"] + off, d["time"]["tempo"])
                b = blick_to_seconds(n["onset"] + off + n["duration"], d["time"]["tempo"])
                out.append((a, b - a, n["pitch"] + ref.get("pitchOffset", 0)))
    return sorted(out)


def synthv_oracle(d: dict) -> dict:
    tr = next(t for t in d["tracks"] if t["mainRef"].get("isInstrumental") and t["mainRef"].get("audio"))
    audio = tr["mainRef"]["audio"]
    offset = blick_to_seconds(tr["mainRef"].get("blickOffset", 0), d["time"]["tempo"])
    return {"file": audio.get("filename"), "offset_s": offset, "bpm": audio.get("bpm"),
            "alternatives": audio.get("alternativeBPMs") or [],
            "beats": [b + offset for b in (audio.get("beatLocations") or [])]}


def librosa_oracle(path: str) -> dict:
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return {"bpm": float(np.atleast_1d(tempo)[0]), "beats": [float(b) for b in beats],
            "seconds": len(y) / sr}


def grid_fit(onsets: np.ndarray, bpm: float, sub: int) -> dict:
    """在 bpm 的 1/sub 拍网格上找最好的相位 → 对齐率，和随机撒点的偶然水平。"""
    d = 60.0 / bpm / sub
    ang = 2 * math.pi * np.mod(onsets, d) / d
    phase = (math.atan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * math.pi)) / (2 * math.pi) * d
    r = np.mod(onsets - phase, d)
    r = np.minimum(r, d - r)
    return {"bpm": round(bpm, 3), "sub": sub, "aligned": float(np.mean(r <= TOL)),
            "chance": min(1.0, 2 * TOL / d), "median_off_ms": float(np.median(r) * 1000), "phase_s": float(phase)}


def local_fit(onsets: np.ndarray, beats: list[float], sub: int) -> dict:
    """不假设全曲一个速度：每个起音只和它前后两个拍点比，看落在 1/sub 拍的哪儿 —— 速度在飘也量得准。"""
    b = np.array(beats)
    inside = onsets[(onsets >= b[0]) & (onsets < b[-1])]
    i = np.searchsorted(b, inside, side="right") - 1
    span = b[i + 1] - b[i]
    pos = (inside - b[i]) / span * sub
    off = np.abs(pos - np.round(pos)) / sub * span
    return {"aligned": float(np.mean(off <= TOL)), "chance": float(np.mean(np.minimum(1.0, 2 * TOL / (span / sub)))),
            "median_off_ms": float(np.median(off) * 1000), "n": int(len(inside))}


def drift(beats: list[float]) -> dict:
    ibi = np.diff(np.array(beats))
    bpm = 60 / ibi
    return {"median_bpm": float(np.median(bpm)), "p10_bpm": float(np.percentile(bpm, 10)),
            "p90_bpm": float(np.percentile(bpm, 90))}


def match_octave(a: list[float], b: list[float]) -> tuple[list[float], list[float], str]:
    """把两串拍点调到同一个速度档（插中点 ×2 或隔一取一 ÷2），好比较它们是不是落在同一处。"""
    ia, ib = np.median(np.diff(a)), np.median(np.diff(b))
    note = "同一档"
    for _ in range(3):
        if ia / ib > 1.6:
            a = sorted(a + [(a[i] + a[i + 1]) / 2 for i in range(len(a) - 1)])
            ia, note = ia / 2, "SynthV 的拍点插了中点（×2）"
        elif ib / ia > 1.6:
            b = sorted(b + [(b[i] + b[i + 1]) / 2 for i in range(len(b) - 1)])
            ib, note = ib / 2, "librosa 的拍点插了中点（×2）"
    return a, b, note


def beat_agreement(a: list[float], b: list[float]) -> dict:
    a2, b2, note = match_octave(list(a), list(b))
    arr = np.array(a2)
    offs = [float(np.min(np.abs(arr - t))) for t in b2 if arr[0] <= t <= arr[-1]]
    period = float(np.median(np.diff(a2)))
    return {"octave": note, "period_s": period, "median_off_ms": float(np.median(offs) * 1000),
            "within_50ms": float(np.mean(np.array(offs) <= 0.05))}


# ---------------------------------------------------------------- 自检

def selftest() -> list[str]:
    fails = []
    rng = np.random.default_rng(7)
    true_bpm = 132.0
    d16 = 60 / true_bpm / 4
    grid_onsets = np.sort(rng.choice(np.arange(0, 600), 200, replace=False) * d16 + 3.21 + rng.normal(0, 0.008, 200))
    hit = grid_fit(grid_onsets, true_bpm, 4)
    if hit["aligned"] < 0.9:
        fails.append(f"已知 132 BPM 的合成起音只对齐了 {hit['aligned']:.0%}")
    wrong = grid_fit(grid_onsets, 120.0, 4)
    if wrong["aligned"] > wrong["chance"] + 0.15:
        fails.append(f"用错的速度 120 却对齐了 {wrong['aligned']:.0%}（偶然 {wrong['chance']:.0%}）")
    rand = grid_fit(np.sort(rng.uniform(0, 150, 200)), true_bpm, 4)
    if rand["aligned"] > rand["chance"] + 0.15:
        fails.append(f"随机起音对齐了 {rand['aligned']:.0%}（偶然 {rand['chance']:.0%}）—— 量法会骗人")
    try:
        import librosa
        sr = 22050
        y = np.zeros(sr * 30, np.float32)
        for t in np.arange(0.5, 29.5, 60 / true_bpm):
            i = int(t * sr)
            y[i:i + 400] += np.hanning(800)[400:] * np.sin(2 * np.pi * 1000 * np.arange(400) / sr)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr, units="time")
        t0 = float(np.atleast_1d(tempo)[0])
        if not any(abs(t0 - k * true_bpm) / (k * true_bpm) < 0.03 for k in (0.5, 1, 2)):
            fails.append(f"librosa 把 132 BPM 的点击声测成 {t0:.1f}")
    except Exception as e:                  # noqa: BLE001
        fails.append(f"librosa 自检跑不起来：{e}")
    return fails


def main(svp_path: str, name: str) -> int:
    fails = selftest()
    print("自检：", "通过（已知速度测得对、错的速度和随机数据不会「对齐」、librosa 测得出点击声）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1

    src = pathlib.Path(svp_path)
    d = load_svp(src)
    sv = synthv_oracle(d)
    audio = pathlib.Path(sv["file"])
    if not audio.exists():
        print(f"伴奏文件不在了：{audio}")
        return 1
    lb = librosa_oracle(str(audio))
    lead = next(t.get("name") for t in d["tracks"] if not t["mainRef"].get("isInstrumental"))
    notes = voiced_notes(d, lead)
    onsets = np.array([a for a, _, _ in notes])

    cands = [("工程网格", d["time"]["tempo"][0]["bpm"]), ("SynthV", sv["bpm"])]
    cands += [(f"SynthV 备选", x) for x in sv["alternatives"] if abs(x - sv["bpm"]) > 0.5]
    cands += [("librosa", lb["bpm"])]
    fits = []
    for src_name, bpm in cands:
        for sub in (2, 4):
            f = grid_fit(onsets, bpm, sub)
            f["source"] = src_name
            fits.append(f)
    agree = beat_agreement(sv["beats"], lb["beats"]) if sv["beats"] and lb["beats"] else None
    sv132, lb132, _ = match_octave(list(sv["beats"]), list(lb["beats"]))      # 调到同一档（≈132 那一族）再比
    locals_ = {"SynthV 拍点": {s: local_fit(onsets, sv132, s) for s in (2, 4)},
               "librosa 拍点": {s: local_fit(onsets, lb132, s) for s in (2, 4)}}
    drifts = {"SynthV 拍点": drift(sv132), "librosa 拍点": drift(lb132)}

    out = OUT_ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    result = {"svp": str(src), "audio": str(audio), "lead_track": lead, "n_notes": len(notes),
              "synthv": {k: v for k, v in sv.items() if k != "beats"} | {"n_beats": len(sv["beats"])},
              "librosa": {"bpm": lb["bpm"], "n_beats": len(lb["beats"]), "seconds": lb["seconds"]},
              "beat_agreement": agree, "grid_fits": fits, "tolerance_ms": TOL * 1000,
              "local_fits": locals_, "drift": drifts,
              "synthv_beats": sv["beats"], "librosa_beats": lb["beats"],
              "lead_onsets_s": [float(x) for x in onsets]}
    (out / "beat_grid.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n工程：{src.name} · 主唱轨「{lead}」{len(notes)} 个音 · 伴奏 {audio.name}（{lb['seconds']:.1f} 秒）")
    print(f"裁判 1 · SynthV：{sv['bpm']:.2f} BPM，备选 {[round(x, 2) for x in sv['alternatives']]}，{len(sv['beats'])} 个拍点")
    print(f"裁判 2 · librosa：{lb['bpm']:.2f} BPM，{len(lb['beats'])} 个拍点")
    if agree:
        print(f"  两串拍点比对（{agree['octave']}）：拍距 {agree['period_s'] * 1000:.0f} ms，"
              f"中位偏差 {agree['median_off_ms']:.0f} ms，50 ms 以内的 {agree['within_50ms']:.0%}")
    print(f"裁判 3 · 人声起点（±{TOL * 1000:.0f} ms 算对齐）：")
    for f in fits:
        grid = "八分" if f["sub"] == 2 else "十六分"
        print(f"  {f['source']:<10} {f['bpm']:>7.2f} BPM 的{grid}网格：对齐 {f['aligned']:.0%} · 偶然 {f['chance']:.0%} · "
              f"中位偏差 {f['median_off_ms']:.0f} ms")
    print("裁判 3 · 人声起点，按各自的拍点序列局部量（调到同一档，不假设全曲一个速度）：")
    for who, fs in locals_.items():
        dr = drifts[who]
        print(f"  {who}：拍距折合 {dr['median_bpm']:.1f} BPM（10%–90% 在 {dr['p10_bpm']:.1f}–{dr['p90_bpm']:.1f}）")
        for s, f in fs.items():
            grid = "八分" if s == 2 else "十六分"
            print(f"      {grid}网格：对齐 {f['aligned']:.0%} · 偶然 {f['chance']:.0%} · 中位偏差 {f['median_off_ms']:.0f} ms（{f['n']} 个起音）")
    print(f"\n结果：{out / 'beat_grid.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
