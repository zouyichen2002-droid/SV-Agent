# -*- coding: utf-8 -*-
"""翻唱第一版扒谱吸格线：把一版扒谱工程（已经换成真拍子的）里 AI 扒的那条轨吸到十六分线上，写成新的一版。

创作者 09-29：「我发现吸格线和不吸基本没有区别。为了后续容易判定，干脆翻唱第一次MIDI识别也吸格线吧，
但是创作者修改的时候可以不吸格线，只有第一版是要吸格线的」
- 只吸 AI 扒的那条（第一版）；别的轨（终稿、音频）一个不动。创作者改过的工程**不再吸**
- 吸法和逆向学习第 2 步同一个（quantize_melody.quantize）：先扣整体偏移、吸到最近的十六分；拿不准的照最近那条、标出来；
  三连音不判；实测速度对的那一段之后（尾声）原样。**不拿终稿当裁判** —— 终稿是打分的答案，不能先看答案
- 输入必须已经是真拍子（retime_svp.py 换过的）：第 2 小节起每一拍和实测拍点差 ≤ 1 ms，不然不写
- 新文件；输入只读；已有就不写
- 自检（从写出来的文件读回来）：AI 那条音数、音高、歌词和输入一样；网格那一段每个音压在十六分线上；尾声原样；不重叠；
  别的轨实际时间和输入一样；速度表没变；键盘分轨按工程网格锁住
- 打分：对终稿主唱（吸格线前后都算）；对吸过格线的终稿（逆向学习第 2 步那版），看吸到同一格的有多少

    python snap_round.py <输入.svp> <输出.svp> <AI 轨名> <新轨名>
"""
from __future__ import annotations

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
import quantize_melody as QM                                    # noqa: E402
import retime_svp as RT                                         # noqa: E402

Q = BG.Q
TOL = 0.001


def snap_track(d_in: dict, name: str, new_name: str, one: float, T: float, end: float) -> tuple[dict, list[dict], float]:
    d = copy.deepcopy(d_in)
    tr = next((t for t in d["tracks"] if t.get("name") == name), None)
    if tr is None:
        raise SystemExit(f"没有叫「{name}」的轨")
    if tr.get("groups") or tr["mainRef"].get("blickOffset", 0) != 0:
        raise SystemExit(f"「{name}」引用了音符库组或主组有偏移 —— 这里只处理音都在主组、偏移 0 的扒谱轨")
    notes = C.tracks(d_in)[name]
    res, bias = QM.quantize(notes, one, T, end)                  # 不给裁判：不先看答案
    originals = sorted(tr["mainGroup"]["notes"], key=lambda n: n["onset"])
    assert len(originals) == len(res)
    new = []
    for n0, r in zip(originals, res):
        assert n0.get("lyrics", "") == r["lyric"]
        n = copy.deepcopy(n0)
        if r["k16"] is not None:
            if r["k16"] < 16:
                raise SystemExit("有音在第 1 小节（第 1 小节的速度不是实测速度），这里不处理")
            n["onset"], n["duration"] = round(r["k16"] * Q / 4), round(r["dur16"] * Q / 4)
        new.append(n)
    tr["mainGroup"]["notes"] = new
    tr["name"] = new_name
    return d, res, bias


def check(d_in: dict, d_out: dict, name: str, new_name: str, res: list[dict], one: float, T: float) -> list[str]:
    fails = []
    a, b = C.tracks(d_in), C.tracks(d_out)
    U = T / 4
    got, src = b.get(new_name, []), a[name]
    if len(got) != len(src):
        return [f"「{new_name}」音数 {len(got)} ≠ 输入 {len(src)}"]
    for (x, dx, cx, lx), (y, dy, cy, ly), r in zip(got, src, res):
        if cx != cy or lx != ly:
            fails.append(f"音高或歌词变了：{ly} {cy} → {lx} {cx}")
            break
        if r["k16"] is not None:
            if abs((x - one) / (U / 2) - round((x - one) / (U / 2))) * (U / 2) > TOL or abs(x - r["q_on_s"]) > TOL:
                fails.append(f"「{lx}」{x:.3f}s 没压在十六分线上")
                break
        elif abs(x - y) > TOL or abs((x + dx) - (y + dy)) > TOL:
            fails.append(f"尾声的「{lx}」动了")
            break
    if any(got[i][0] + got[i][1] > got[i + 1][0] + TOL for i in range(len(got) - 1)):
        fails.append("有音重叠")
    for k, v in a.items():
        if k == name:
            continue
        w = b.get(k, [])
        if len(w) != len(v) or any(abs(p[0] - q[0]) > TOL or abs(p[1] - q[1]) > TOL or p[2:] != q[2:] for p, q in zip(v, w)):
            fails.append(f"别的轨「{k}」动了")
    if d_out["time"] != d_in["time"]:
        fails.append("速度表或拍号变了")
    ta, tb = RT.timeline(d_in)["audio"], RT.timeline(d_out)["audio"]
    if ta != tb:
        fails.append("音频位置变了")
    return fails


def main(src: str, dst: str, name: str, new_name: str) -> int:
    r = json.loads((GC.OUT / "grid_check.json").read_text(encoding="utf-8"))
    bpm, one, end = r["grid"]["bpm_132"], r["grid"]["first_one_s_132"], r["tempo_span"]["to_s"]
    T = 60 / bpm
    src_p, dst_p = pathlib.Path(src), pathlib.Path(dst)
    if dst_p.exists():
        raise SystemExit(f"{dst_p} 已经有了 —— 写新文件，换个名字")
    d_in = C.load_svp(src_p)
    time_want, first = RT.new_time(bpm, one)
    tempo = d_in["time"]["tempo"]
    dur = max(t["mainRef"]["audio"]["duration"] for t in d_in["tracks"] if t["mainRef"].get("audio"))
    worst = max(abs(BG.blick_to_seconds(n * Q, tempo) - (first + (n - 4) * T)) for n in range(4, int(dur / T)))
    if worst > TOL:
        raise SystemExit(f"输入不是真拍子（第 2 小节起的拍和实测差 {worst * 1000:.1f} ms）—— 先用 retime_svp.py 换")

    d, res, bias = snap_track(d_in, name, new_name, one, T, end)
    d["uuid"] = str(uuid.uuid4())
    d["renderConfig"].update(destination=str(dst_p.parent / "render").replace("\\", "/"), filename=dst_p.stem)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    dst_p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    d_out = C.load_svp(dst_p)
    fails = check(d_in, d_out, name, new_name, res, one, T)
    sfails, info = RT.stem_check(d_out, end)
    fails += sfails

    g = [x for x in res if x["k16"] is not None]
    shifts = np.abs([x["shift_ms"] for x in g])
    flags = {}
    for x in res:
        for f in x["flags"]:
            flags[f] = flags.get(f, 0) + 1
    print(f"写出 {dst_p}")
    print(f"  「{new_name}」：{len(res)} 个音，{len(g)} 个吸到网格（到 {end:.0f} s）· 整体偏移 {bias * 1000:+.1f} ms（先扣掉）· "
          f"起音挪了 中位 {np.median(shifts):.1f} ms、最多 {shifts.max():.1f} ms · 标记 {flags}")

    fin = C.tracks(C.load_svp(QM.FINAL))
    lead, harm = fin["vocal1"], fin["和声1"]
    mixed = sorted([n for n in lead if not (116.0 <= n[0] < 134.0)] + harm)   # 1:56–2:14 用和声1（上面那条）
    before, after = C.tracks(d_in)[name], C.tracks(d_out)[new_name]
    qd = json.loads((QM.LEARN / "melody_grid.json").read_text(encoding="utf-8"))["音"]
    qfin = sorted((x["q_on_s"], x["q_off_s"] - x["q_on_s"], x["cents"], x["lyric"]) for x in qd["vocal1"])
    scores = {}
    for label, ref in (("终稿主唱", lead), ("终稿主唱、1:56–2:14 用和声1", mixed), ("吸过格线的终稿主唱", qfin)):
        s0, s1 = C.compare(ref, before), C.compare(ref, after)
        scores[label] = {"吸格线前": s0["F1"], "吸格线后": s1["F1"]}
        print(f"  打分 · 对{label}：F1 吸格线前 {s0['F1']:.3f} → 后 {s1['F1']:.3f}"
              f"（起音放宽到 100 ms：{s0['起音容差放宽后的 F1']['100 ms']:.3f} → {s1['起音容差放宽后的 F1']['100 ms']:.3f}）")
    print(f"  第二个裁判：键盘按工程网格锁住 {info['span']['from_s']:.0f}–{info['span']['to_s']:.0f} s，偏差中位 {info['median_ms']:+.1f} ms")
    print("  自检（从写出来的文件读回来）：", "通过（音数、音高、歌词不变；网格那一段压线；尾声原样；不重叠；别的轨、速度表、音频没动）"
          if not fails else "不通过")
    for f in fails:
        print("    ✗", f)
    log = dst_p.with_suffix(".json")
    if not log.exists():
        log.write_text(json.dumps({"输入": str(src_p), "轨": new_name, "整体偏移_ms": round(bias * 1000, 1), "标记": flags,
                                   "打分": scores, "音": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:5]))
