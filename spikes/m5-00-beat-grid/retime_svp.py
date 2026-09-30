# -*- coding: utf-8 -*-
"""C02：把一个 SynthV 工程换成实测的真拍子 —— 每个音、每个调教点、音频的**实际时间一个都不动**，只换速度表和拍号。

创作者 09-29 定：4/4、一拍按 132 那一档、速度用实测的 131.98；Suno 显示的 131 只是参考值（「不是生成时候就有的参数；
即使生成时定了参数，SUNO 也不一定严格按参数走，会出现漂移」）；尾声先让它自由。

- 速度表：第 1 小节稍慢一点，把歌第一个「1」之前的空白吃掉；从第 2 小节起一律实测速度 → 第 2 小节起每条小节线都压在歌的「1」上，
  小节号和歌本身一致。**音频不挪**：本机 38 个工程里没有一个挪过伴奏轨，不知道 SynthV 怎么对待音频偏移，不赌
- 换算：所有 blick 位置先按旧速度表换成秒，再按新速度表换回 blick —— 音符起止、引用的偏移和起止范围、参数曲线的点、
  音高控制点（点，和曲线里相对于起点的点）
- 同一个音符库组被引用不止一次时，速度表一变就不能共用 —— 碰到就不写
- 新文件；输入只读；已有就不写；导出设置改到新目录
- 自检（全从写出来的文件读回来）：
  1. 每条轨每个音的起止（±1 ms）、音高、歌词和输入一样；每个音高控制点、曲线里每个点、参数曲线每个点的时间（±1 ms）和值一样；音频位置不变
  2. 从第 2 小节起，工程的每一拍和实测拍点差 ≤ 1 ms
  3. 第二个裁判：把键盘分轨按**工程自己的**网格（从写出来的速度表算）折一次（grid_check 的量法），实测速度对的那一段都要锁住
  先拿造的小工程跑一遍，每项都注入已知的错，必须测得出；不过就不跑

    python retime_svp.py <输入.svp> <输出.svp> [--rename 旧轨名=新轨名 ...]
"""
from __future__ import annotations

import collections
import copy
import json
import pathlib
import sys
import uuid

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
import beat_grid as BG                                          # noqa: E402
import compare_notes as C                                       # noqa: E402
import grid_check as GC                                         # noqa: E402

Q = BG.Q
BEATS = 4                                                       # 4/4（创作者 09-29 定）
TOL = 0.001                                                     # 实际时间差 ≤ 1 ms 才算没动


def new_time(bpm: float, one: float) -> tuple[dict, float]:
    """第 1 小节从 0 到歌的一个「1」（离开头至少 3/4 小节，第 1 小节的速度才不离谱）；之后恒定 bpm。→ (time, 第 2 小节的秒数)"""
    bar = BEATS * 60 / bpm
    first = one
    while first < 0.75 * bar:
        first += bar
    if abs(first - bar) < 1e-9:
        tempo = [{"position": 0, "bpm": bpm}]
    else:
        tempo = [{"position": 0, "bpm": BEATS * 60 / first}, {"position": BEATS * Q, "bpm": bpm}]
    return {"meter": [{"index": 0, "numerator": BEATS, "denominator": 4}], "tempo": tempo}, first


def seconds_to_blick(t: float, tempo: list[dict]) -> float:
    marks = sorted(tempo, key=lambda m: m["position"])
    s = 0.0
    for i, m in enumerate(marks):
        if i + 1 < len(marks):
            seg = (marks[i + 1]["position"] - m["position"]) / Q * 60 / m["bpm"]
            if t < s + seg:
                return m["position"] + (t - s) * m["bpm"] / 60 * Q
            s += seg
    m = marks[-1]
    return m["position"] + (t - s) * m["bpm"] / 60 * Q


def retime(d_in: dict, time_out: dict) -> dict:
    d = copy.deepcopy(d_in)
    t_in, t_out = d_in["time"]["tempo"], time_out["tempo"]

    def conv(b: float) -> float:
        return seconds_to_blick(BG.blick_to_seconds(b, t_in), t_out)

    used = collections.Counter(r["groupID"] for t in d["tracks"] for r in t.get("groups", []))
    shared = [g for g, n in used.items() if n > 1]
    if shared:
        raise SystemExit(f"有 {len(shared)} 个音符库组被引用不止一次，换了速度表就不能共用 —— 不写")
    lib = {g["uuid"]: g for g in d["library"]}
    for tr in d["tracks"]:
        for g, ref in [(tr["mainGroup"], tr["mainRef"])] + [(lib[r["groupID"]], r) for r in tr.get("groups", [])]:
            off_in = ref.get("blickOffset", 0)
            off_out = round(conv(off_in))

            def here(local: float) -> int:
                return round(conv(off_in + local)) - off_out

            for n in g.get("notes", []):
                a, b = here(n["onset"]), here(n["onset"] + n["duration"])
                n["onset"], n["duration"] = a, max(1, b - a)
            for p in g.get("parameters", {}).values():
                if isinstance(p, dict) and p.get("points"):
                    p["points"] = [here(x) if i % 2 == 0 else x for i, x in enumerate(p["points"])]
            for pc in g.get("pitchControls", []):
                pos_in = pc["pos"]
                pc["pos"] = here(pos_in)
                if pc.get("points"):
                    pc["points"] = [here(pos_in + x) - pc["pos"] if i % 2 == 0 else x for i, x in enumerate(pc["points"])]
            ref["blickOffset"] = off_out
            for key in ("blickAbsoluteBegin", "blickAbsoluteEnd"):
                if ref.get(key) is not None and ref[key] >= 0:
                    ref[key] = round(conv(ref[key]))
    d["time"] = {**d["time"], **time_out}
    return d


def timeline(d: dict) -> dict:
    """{组 uuid: {"pc": [(秒, 音高, [(秒, 值)…])], "param": {名: [(秒, 值)…]}}} + {"audio": {轨名: 秒}}：写的东西的实际时间。"""
    lib = {g["uuid"]: g for g in d.get("library", [])}
    tempo = d["time"]["tempo"]
    out, audio = {}, {}
    for tr in d["tracks"]:
        if tr["mainRef"].get("audio"):
            audio[tr.get("name")] = BG.blick_to_seconds(tr["mainRef"].get("blickOffset", 0), tempo)
        for g, ref in [(tr["mainGroup"], tr["mainRef"])] + [(lib[r["groupID"]], r) for r in tr.get("groups", [])]:
            off = ref.get("blickOffset", 0)
            sec = lambda b: BG.blick_to_seconds(off + b, tempo)                # noqa: E731
            pcs = []
            for pc in g.get("pitchControls", []):
                pts = pc.get("points") or []
                pcs.append((sec(pc["pos"]), pc.get("pitch"),
                            [(sec(pc["pos"] + pts[i]), pts[i + 1]) for i in range(0, len(pts), 2)]))
            params = {k: [(sec(p["points"][i]), p["points"][i + 1]) for i in range(0, len(p["points"]), 2)]
                      for k, p in g.get("parameters", {}).items() if isinstance(p, dict) and p.get("points")}
            out[g["uuid"]] = {"pc": pcs, "param": params}
    return {"groups": out, "audio": audio}


def check(d_in: dict, d_out: dict, renames: dict[str, str], first: float, bpm: float, n_beats: int) -> list[str]:
    fails = []
    a, b = C.tracks(d_in), C.tracks(d_out)
    for name, src in a.items():
        got = b.get(renames.get(name, name), [])
        if len(got) != len(src):
            fails.append(f"「{name}」音数 {len(got)} ≠ 输入 {len(src)}")
            continue
        bad = [k for k, (x, y) in enumerate(zip(src, got))
               if abs(x[0] - y[0]) > TOL or abs((x[0] + x[1]) - (y[0] + y[1])) > TOL or x[2] != y[2] or x[3] != y[3]]
        if bad:
            k = bad[0]
            fails.append(f"「{name}」{len(bad)} 个音动了，第 {k + 1} 个：输入 {src[k][:2]} → 写出 {got[k][:2]}")
    ta, tb = timeline(d_in), timeline(d_out)
    for gid, x in ta["groups"].items():
        y = tb["groups"].get(gid)
        if y is None or len(x["pc"]) != len(y["pc"]):
            fails.append(f"组 {gid[:8]} 的音高控制点数目变了")
            continue
        for (t1, p1, in1), (t2, p2, in2) in zip(x["pc"], y["pc"]):
            if abs(t1 - t2) > TOL or p1 != p2 or len(in1) != len(in2) or \
                    any(abs(u1 - u2) > TOL or v1 != v2 for (u1, v1), (u2, v2) in zip(in1, in2)):
                fails.append(f"组 {gid[:8]} 有音高控制点动了（{t1:.3f}s → {t2:.3f}s）")
                break
        for k, pts in x["param"].items():
            q = y["param"].get(k, [])
            if len(q) != len(pts) or any(abs(u1 - u2) > TOL or v1 != v2 for (u1, v1), (u2, v2) in zip(pts, q)):
                fails.append(f"组 {gid[:8]} 的参数 {k} 动了")
    for name, s in ta["audio"].items():
        if abs(tb["audio"].get(renames.get(name, name), -1) - s) > TOL:
            fails.append(f"音频「{name}」的位置动了")
    T = 60 / bpm
    tempo = d_out["time"]["tempo"]
    worst = max(abs(BG.blick_to_seconds(n * Q, tempo) - (first + (n - BEATS) * T)) for n in range(BEATS, n_beats))
    if worst > TOL:
        fails.append(f"第 2 小节起工程的拍和实测拍点最多差 {worst * 1000:.2f} ms")
    if d_out["time"]["meter"] != [{"index": 0, "numerator": BEATS, "denominator": 4}]:
        fails.append(f"拍号不是 {BEATS}/4：{d_out['time']['meter']}")
    return fails


def stem_check(d_out: dict, ok_to: float) -> tuple[list[str], dict]:
    """第二个裁判：键盘分轨按工程自己的网格（从写出来的速度表算）折，实测速度对的那一段都要锁住。"""
    tempo = d_out["time"]["tempo"]
    bpm_file = sorted(tempo, key=lambda m: m["position"])[-1]["bpm"]
    t0_file = BG.blick_to_seconds(BEATS * Q, tempo)                  # 工程第 2 小节第 1 拍
    y, sr = GC.mono(GC.STEMS / GC.INSTR["键盘"])
    t, w = GC.strength(y, sr)
    rows = GC.lock_table(t, w, bpm_file, t0_file, len(y) / sr)
    span = GC.locked_span({"键盘": rows}, bpm_file)
    fails = []
    if not span["segments"] or span["from_s"] > 0 or span["to_s"] < ok_to - GC.WIN:
        fails.append(f"键盘按工程自己的网格只锁住 {span}（实测速度对到 {ok_to:.0f} s）")
    ph = [r["phase_ms"] for r in rows if r["locked"]]
    med = float(np.median(ph)) if ph else float("nan")
    if not ph or abs(med) > GC.LIMIT * 1000:
        fails.append(f"键盘按工程自己的网格，偏差中位 {med:.1f} ms，超线")
    return fails, {"span": span, "median_ms": round(med, 1), "bpm": bpm_file, "bar2_s": t0_file}


# ---------------------------------------------------------------- 自检（造的小工程）

def _toy(shared: bool = False) -> dict:
    note = lambda on, du, p: {"onset": on, "duration": du, "pitch": p, "detune": 0, "lyrics": "la"}     # noqa: E731
    lib = {"uuid": "g1", "name": "库", "notes": [note(Q * 40, Q, 60), note(Q * 41, Q // 2, 62)],
           "parameters": {"pitchDelta": {"mode": "cubic", "points": [Q * 40, 10.0, Q * 42, -5.0]}},
           "pitchControls": [{"pos": Q * 40, "pitch": 60.0, "id": "0", "type": "point"},
                             {"pos": Q * 41, "pitch": 61.0, "id": "1", "type": "curve", "points": [0, 0.0, Q // 4, 0.5, Q // 2, 0.0]}]}
    ref = {"groupID": "g1", "blickOffset": Q * 8, "blickAbsoluteBegin": Q * 8, "blickAbsoluteEnd": Q * 60, "pitchOffset": 0}
    voc = {"name": "唱", "mainRef": {"groupID": "m1", "blickOffset": 0, "blickAbsoluteBegin": 0, "blickAbsoluteEnd": -1,
                                     "isInstrumental": False},
           "mainGroup": {"uuid": "m1", "name": "main", "notes": [note(Q * 50, Q, 64)], "parameters": {}, "pitchControls": []},
           "groups": [ref] + ([dict(ref, blickOffset=Q * 80)] if shared else [])}
    inst = {"name": "伴奏", "mainRef": {"groupID": "a1", "blickOffset": 0, "isInstrumental": True,
                                        "audio": {"filename": "x.wav", "duration": 60.0}},
            "mainGroup": {"uuid": "a1", "name": "main", "notes": [], "parameters": {}, "pitchControls": []}, "groups": []}
    return {"time": {"meter": [{"index": 0, "numerator": 4, "denominator": 4}], "tempo": [{"position": 0, "bpm": 120.0}]},
            "library": [lib], "tracks": [inst, voc]}


def selftest() -> list[str]:
    fails = []
    bpm, one = 131.9775, 0.1039
    time_out, first = new_time(bpm, one)
    d_in = _toy()
    d = retime(d_in, time_out)
    got = check(d_in, d, {}, first, bpm, 400)
    if got:
        fails.append(f"造的工程换拍子后自检不过：{got}")
    if abs(time_out["tempo"][0]["bpm"] - 240 / (one + 240 / bpm)) > 1e-6 or time_out["tempo"][1]["position"] != 4 * Q:
        fails.append(f"速度表不对：{time_out}")
    bad = copy.deepcopy(d)                                      # 注入：一个音挪 2 ms
    bad["library"][0]["notes"][0]["onset"] += round(0.002 * bpm / 60 * Q)
    if not any("动了" in f for f in check(d_in, bad, {}, first, bpm, 400)):
        fails.append("一个音挪了 2 ms，没查出来")
    bad = copy.deepcopy(d)                                      # 注入：曲线里一个点挪 2 ms
    bad["library"][0]["pitchControls"][1]["points"][2] += round(0.002 * bpm / 60 * Q)
    if not any("音高控制点" in f for f in check(d_in, bad, {}, first, bpm, 400)):
        fails.append("音高曲线里一个点挪了 2 ms，没查出来")
    bad = copy.deepcopy(d)                                      # 注入：速度写成整数 132
    bad["time"]["tempo"][1]["bpm"] = 132.0
    if not any("拍和实测拍点" in f for f in check(d_in, bad, {}, first, bpm, 400)):
        fails.append("速度写成 132 没查出来")
    naive = copy.deepcopy(d_in)                                 # 注入：只换速度表、不换算位置（最容易犯的错）
    naive["time"] = {**naive["time"], **time_out}
    if not any("动了" in f for f in check(d_in, naive, {}, first, bpm, 400)):
        fails.append("只换速度表、不换算位置，没查出来")
    try:
        retime(_toy(shared=True), time_out)
        fails.append("同一个音符库组引用两次，居然写了")
    except SystemExit:
        pass
    return fails


def main(src: str, dst: str, *flags: str) -> int:
    fails = selftest()
    print("自检：", "通过（造的工程：换完实际时间不动；注入挪 2 ms 的音、挪 2 ms 的曲线点、速度写整数、"
                  "只换速度表不换算、音符库组引用两次，都查得出）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1

    renames = dict(f.split("=", 1) for f in flags if "=" in f)
    r = json.loads((GC.OUT / "grid_check.json").read_text(encoding="utf-8"))
    bpm, one, ok_to = r["grid"]["bpm_132"], r["grid"]["first_one_s_132"], r["tempo_span"]["to_s"]
    src_p, dst_p = pathlib.Path(src), pathlib.Path(dst)
    if dst_p.exists():
        raise SystemExit(f"{dst_p} 已经有了 —— 写新文件，换个名字")
    d_in = C.load_svp(src_p)
    time_out, first = new_time(bpm, one)
    d = retime(d_in, time_out)
    for t in d["tracks"]:
        if t.get("name") in renames:
            t["name"] = renames[t["name"]]
    d["uuid"] = str(uuid.uuid4())
    d["renderConfig"].update(destination=str(dst_p.parent / "render").replace("\\", "/"), filename=dst_p.stem)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    dst_p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    d_out = C.load_svp(dst_p)                                   # 从写出来的文件读回来查
    dur = max(t["mainRef"]["audio"]["duration"] for t in d_out["tracks"] if t["mainRef"].get("audio"))
    fails = check(d_in, d_out, renames, first, bpm, int(dur / (60 / bpm)) + 1)
    for t in d_out["tracks"]:
        if t["mainRef"].get("audio") and not pathlib.Path(t["mainRef"]["audio"]["filename"]).exists():
            fails.append(f"音频不存在：{t['mainRef']['audio']['filename']}")
    sf, info = stem_check(d_out, ok_to)
    fails += sf
    tm = d_out["time"]["tempo"]
    n_notes = {k: len(v) for k, v in C.tracks(d_out).items()}
    print(f"写出 {dst_p}")
    print(f"  速度表：第 1 小节 {tm[0]['bpm']:.3f} BPM（0 → {first:.4f} s，吃掉歌开头「1」之前的 {one:.4f} s）；"
          f"第 2 小节起 {tm[-1]['bpm']:.4f} BPM；拍号 {BEATS}/4")
    print(f"  各轨音数：{n_notes}；音频位置不变")
    print(f"  第二个裁判：键盘按工程自己的网格（第 2 小节在 {info['bar2_s']:.4f} s）锁住 "
          f"{info['span']['from_s']:.0f}–{info['span']['to_s']:.0f} s，偏差中位 {info['median_ms']:+.1f} ms")
    print("  自检（从写出来的文件读回来）：", "通过（每个音、每个音高控制点实际时间没动，第 2 小节起每拍和实测差 ≤ 1 ms，键盘锁住）"
          if not fails else "不通过")
    for f in fails:
        print("    ✗", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
