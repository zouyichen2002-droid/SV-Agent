# -*- coding: utf-8 -*-
"""逆向学习 01《傍晚》第 2 步：把 04-17 终稿的主唱（和「和声1」）吸到真网格上 —— 创作时要用格线。

创作者 09-29：「不用非得吸到格线上（翻唱出成品时），但是还需要把这个作品进行逆向学习，所以也得有一版吸到格线上的，
因为创作的时候要用到格线」。PRD §6.5：《傍晚》逆向学习用 04-17 的最终版 —— 所以吸的是**终稿**的音；
AI 扒的（r05）只当第二个裁判，**不进学习库**（学习库不收生成结果和探针产物）。

规则（每一条都留痕，拿不准的列出来给创作者看）：
1. 网格：grid_check 实测的（131.9775 BPM、「1」在 0.1039 s）；只吸到 2:24（实测速度对的那一段），尾声没有网格 → 原样、标出来
2. 整体偏早偏晚先扣掉（十六分上的圈上平均），再吸到最近的十六分线
3. 离两条线差不多远（离最近那条超过 0.35 格）= 拿不准：看 AI 扒的同一个音（起音差 ≤ 60 ms），两个起音取平均；
   平均完能明确落到一条线的就用它（标「靠 AI 起音定的」），还不行的照最近那条、标「拿不准」
4. 不自己判三连音：一律按十六分吸；一拍里 ≥2 个音、按三连音放误差小一半以上的，标「可能是三连音」
5. 结尾：和下一个音的空隙不到半格 → 连着唱（结尾 = 下一个音的起点）；否则吸到最近的线；至少一格、不和下一个音重叠
6. 吸完和前一个音撞到同一格 → 往后挪一格、标「挤」
音高、歌词、音的个数一个不改。

输出：
- 学习库 `E:/sv-agent-data/learn/01-傍晚/melody_grid.json`：每个音在第几小节、第几拍、第几个十六分、几个十六分长，挪了多少毫秒，标记
- 学习库 `E:/sv-agent-data/learn/01-傍晚/傍晚_04-17终稿_吸格线.svp`：吸过的 vocal1、和声1（调教没带：音挪了调教会错位）+
  原样的两条（静音，对照用）+ 伴奏 + Suno 人声（静音，对照用）；导出设置指到探针目录（渲染出来的音频不进学习库）

    python quantize_melody.py
"""
from __future__ import annotations

import copy
import json
import math
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
import retime_svp as RT                                         # noqa: E402

FINAL = pathlib.Path("F:/我的云端硬盘/临时文件3/SV2/傍晚(星尘).svp")              # 04-17 终稿，只读
AI = pathlib.Path("E:/sv-agent-data/probes/m1-01-voice-to-midi/rounds/r05/傍晚_扒谱_r05.svp")   # 只当裁判
VOCAL_STEM = GC.STEMS / "01_人声.wav"
LEARN = pathlib.Path("E:/sv-agent-data/learn/01-傍晚")
TRACKS = ("vocal1", "和声1")
Q = BG.Q
AMB = 0.35             # 离最近那条线超过 0.35 格（十六分）= 拿不准
REF_WIN = 0.060        # AI 的同一个音：起音差 ≤ 60 ms


def quantize(notes: list[tuple], one: float, T: float, end: float, ref_onsets: np.ndarray | None = None) -> tuple[list[dict], float]:
    """notes: [(起音秒, 时值秒, 音分, 歌词)] 按时间排好 → ([每个音的结果], 扣掉的整体偏移秒)。"""
    U = T / 4
    on = np.array([n[0] for n in notes])
    off = on + np.array([n[1] for n in notes])
    grid = on < end
    ang = 2 * math.pi * (((on[grid] - one) / U) % 1)
    bias = math.atan2(np.sin(ang).mean(), np.cos(ang).mean()) / (2 * math.pi) * U if grid.any() else 0.0
    x = (on - one - bias) / U
    k = np.round(x).astype(int)
    amb = grid & (np.abs(x - k) > AMB)
    helped = np.zeros(len(on), bool)
    if ref_onsets is not None and len(ref_onsets):
        for i in np.where(amb)[0]:
            j = int(np.argmin(np.abs(ref_onsets - on[i])))
            if abs(ref_onsets[j] - on[i]) <= REF_WIN:
                x2 = ((on[i] + ref_onsets[j]) / 2 - one - bias) / U
                if abs(x2 - round(x2)) <= AMB:
                    k[i], helped[i], amb[i] = int(round(x2)), True, False
    bumped = np.zeros(len(on), bool)
    idx = np.where(grid)[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if k[b] <= k[a]:
            k[b], bumped[b] = k[a] + 1, True
    trip = np.zeros(len(on), bool)
    beat_of = np.floor((on - one - bias) / T + 1 / 8).astype(int)
    for bt in np.unique(beat_of[grid]):
        m = grid & (beat_of == bt)
        if m.sum() >= 2:
            p = (on[m] - one - bias) / T - bt
            c16 = np.sum((p * 4 - np.round(p * 4)) ** 2 / 16)
            c3 = np.sum((p * 3 - np.round(p * 3)) ** 2 / 9)
            if c3 < 0.5 * c16:
                trip[m] = True
    out = []
    for i, (t0, dur, cents, ly) in enumerate(notes):
        row = {"i": i, "lyric": ly, "pitch": int(round(cents / 100)), "cents": float(cents),
               "on_s": round(float(t0), 4), "off_s": round(float(off[i]), 4), "flags": []}
        if not grid[i]:
            row.update(q_on_s=row["on_s"], q_off_s=row["off_s"], k16=None, bar=None, beat=None, pos16=None, dur16=None,
                       shift_ms=0.0)
            row["flags"].append("尾声，没有网格（原样）")
            out.append(row)
            continue
        q_on = one + k[i] * U
        nxt = i + 1 if i + 1 < len(on) and grid[i + 1] else None
        if nxt is not None and on[nxt] - off[i] < U / 2:
            k_off = int(k[nxt])                                    # 连着唱
        else:
            k_off = int(round((off[i] - one - bias) / U))
        k_off = max(k_off, int(k[i]) + 1)
        if nxt is not None:
            k_off = min(k_off, int(k[nxt]))
        b16 = int(k[i])
        row.update(q_on_s=round(q_on, 4), q_off_s=round(one + k_off * U, 4), k16=b16, bar=b16 // 16 + 1,
                   beat=(b16 % 16) // 4 + 1, pos16=b16 % 16, dur16=k_off - b16, shift_ms=round((q_on - t0) * 1000, 1))
        if amb[i]:
            row["flags"].append("拿不准（离两条线差不多远）")
        if helped[i]:
            row["flags"].append("靠 AI 起音定的")
        if bumped[i]:
            row["flags"].append("挤（和前一个音撞格，往后挪了一格）")
        if trip[i]:
            row["flags"].append("可能是三连音（按十六分吸了）")
        out.append(row)
    return out, bias


# ---------------------------------------------------------------- 自检（造的数据）

def selftest() -> list[str]:
    fails = []
    rng = np.random.default_rng(5)
    T, one, end = 60 / 131.9775, 0.1039, 144.0
    U = T / 4
    ks = np.sort(rng.choice(np.arange(40, 1200), 150, replace=False))
    truth = one + ks * U
    bias = 0.008
    on = truth + bias + rng.normal(0, 0.012, len(ks))
    notes = [(float(a), float(U * 2 * 0.9), 6000.0, "la") for a in on]
    res, b = quantize(notes, one, T, end)
    got = np.array([r["k16"] for r in res])
    ok = float(np.mean(got == ks))
    if ok < 0.97 or abs(b - bias) > 0.003:
        fails.append(f"造的音（抖 12 ms、整体晚 8 ms）只吸对 {ok:.0%}，整体偏移量成 {b * 1000:.1f} ms")
    anchor = [(one + k * U, U / 2, 6000.0, "x") for k in range(600, 1000, 8)]    # 一批压线的音：整体偏移由它们定，不被被测的音带偏

    def run(test: list[tuple], ref: np.ndarray | None = None) -> list[dict]:
        res, _ = quantize(sorted(test + anchor), one, T, end, ref_onsets=ref)
        return res[:len(test)]

    mid = [(one + 100.5 * U, U, 6000.0, "a"), (one + 110 * U, U, 6000.0, "b")]   # 注入：正好在两条线中间
    r = run(mid)
    if not any("拿不准" in f for f in r[0]["flags"]):
        fails.append("正好在两条线中间的音没标拿不准")
    r = run(mid, ref=np.array([one + 101 * U]))                                   # AI 起音在 101 格 → 平均后落 101
    if r[0]["k16"] != 101 or not any("AI" in f for f in r[0]["flags"]):
        fails.append(f"拿不准的音，AI 起音在 101 格，结果 {r[0]['k16']} {r[0]['flags']}")
    r = run([(one + 200 * U, U / 2, 6000.0, "a"), (one + 200 * U + 0.02, U / 2, 6200.0, "b")])   # 注入：两个音挤一格
    if r[1]["k16"] != 201 or not any("挤" in f for f in r[1]["flags"]):
        fails.append(f"两个音挤在一格：{[x['k16'] for x in r]} {r[1]['flags']}")
    r = run([(one + 300 * U, 2 * U - 0.03, 6000.0, "a"), (one + 302 * U, U, 6000.0, "b")])      # 结尾离下一个音 30 ms
    if r[0]["dur16"] != 2:
        fails.append(f"结尾离下一个音 30 ms，时值吸成 {r[0]['dur16']} 格（应连到下一个音 = 2 格）")
    res, _ = quantize(anchor + [(150.0, 0.5, 6000.0, "a")], one, T, end)                     # 尾声：原样
    if res[-1]["q_on_s"] != 150.0 or res[-1]["k16"] is not None:
        fails.append(f"尾声的音被吸了：{res[-1]}")
    r = run([(one + T * 50, T / 3, 6000.0, "a"), (one + T * 50 + T * 2 / 3, T / 3, 6000.0, "b")])   # 一拍里 0 和 2/3
    if not all(any("三连音" in f for f in x["flags"]) for x in r):
        fails.append("0、2/3 拍的两个音没标可能是三连音")
    r = run([(one + T * 60, T / 4, 6000.0, "a"), (one + T * 60 + T * 3 / 4, T / 4, 6000.0, "b")])   # 0 和 3/4（附点）：不许标
    if any(any("三连音" in f for f in x["flags"]) for x in r):
        fails.append("0、3/4 拍（附点）被标成了三连音")
    return fails


# ---------------------------------------------------------------- 写工程

def _track_copy(src: dict, name: str) -> dict:
    """原样的一条轨复制一份（声库、唱法设置照旧），换新 uuid；不再引用音符库组，音符全放主组，调教清空。"""
    t = copy.deepcopy(src)
    t["name"] = name
    t["mainRef"]["uuid"] = str(uuid.uuid4())
    t["mainGroup"]["uuid"] = str(uuid.uuid4())
    t["mainRef"]["groupID"] = t["mainGroup"]["uuid"]
    t["mainRef"]["blickOffset"] = 0
    t["groups"] = []
    for p in t["mainGroup"]["parameters"].values():
        if isinstance(p, dict) and "points" in p:
            p["points"] = []
    t["mainGroup"]["pitchControls"] = []
    return t


def _notes_in_order(track: dict, lib: dict, tempo: list[dict]) -> list[dict]:
    """一条轨全部音符组里的音（主组 + 音符库组），按实际起音排好 —— 和 compare_notes.tracks() 的顺序一样。"""
    rows = []
    for g, ref in [(track["mainGroup"], track["mainRef"])] + [(lib[r["groupID"]], r) for r in track.get("groups", [])]:
        off = ref.get("blickOffset", 0)
        for n in g.get("notes", []):
            rows.append((BG.blick_to_seconds(off + n["onset"], tempo), n))
    return [n for _, n in sorted(rows, key=lambda x: x[0])]


def build(d_final: dict, results: dict[str, list[dict]], one: float, T: float, out_svp: pathlib.Path) -> dict:
    time_out, first = RT.new_time(60 / T, one)
    d = RT.retime(d_final, time_out)                              # 原样的几条（带调教）也换到真拍子上，实际时间不动
    tempo = d["time"]["tempo"]
    lib = {g["uuid"]: g for g in d["library"]}
    inst = next(t for t in d["tracks"] if t["mainRef"].get("isInstrumental"))
    ref_audio = copy.deepcopy(inst)
    ref_audio["name"] = "Suno 人声（参考）"
    ref_audio["mainRef"]["audio"]["filename"] = str(VOCAL_STEM).replace("\\", "/")
    ref_audio["mainRef"]["uuid"] = str(uuid.uuid4())
    ref_audio["mainGroup"]["uuid"] = str(uuid.uuid4())
    ref_audio["mainRef"]["groupID"] = ref_audio["mainGroup"]["uuid"]
    ref_audio["mainRef"]["mute"] = True
    new_tracks = [inst, ref_audio]
    for src_name in TRACKS:
        src = next(t for t in d["tracks"] if t.get("name") == src_name)
        q = _track_copy(src, f"你的终稿 {src_name}（吸格线）")
        originals = _notes_in_order(src, lib, tempo)             # 每个音自己的设置（发音、唱法属性）照搬，只改位置和时长
        assert len(originals) == len(results[src_name]), f"{src_name} 的音数对不上"
        notes = []
        for n0, r in zip(originals, results[src_name]):
            assert n0.get("lyrics", "") == r["lyric"], f"{src_name} 的音顺序对不上：{n0.get('lyrics')} ≠ {r['lyric']}"
            if r["k16"] is not None and r["k16"] >= 16:
                a, b = r["k16"] * Q // 4, (r["k16"] + r["dur16"]) * Q // 4          # 第 2 小节起：十六分 = Q/4，整数
            else:
                a, b = round(RT.seconds_to_blick(r["q_on_s"], tempo)), round(RT.seconds_to_blick(r["q_off_s"], tempo))
            n = copy.deepcopy(n0)
            n.update(uuid=uuid.uuid4().hex[:16], onset=int(a), duration=int(max(1, b - a)),
                     pitch=r["pitch"], detune=int(round(r["cents"] - r["pitch"] * 100)))   # 音高 = 原来的音 + 引用的移调
            notes.append(n)
        q["mainGroup"]["notes"] = notes
        orig = copy.deepcopy(src)
        orig["name"] = f"你的终稿 {src_name}（原样）"
        orig["mainRef"]["mute"] = True
        new_tracks += [q, orig]
    for i, t in enumerate(new_tracks):
        t["dispOrder"] = i
    d["tracks"] = new_tracks
    d["uuid"] = str(uuid.uuid4())
    d["renderConfig"].update(destination=str(GC.OUT / "render").replace("\\", "/"), filename=out_svp.stem)
    return d


def check_svp(path: pathlib.Path, d_final: dict, results: dict[str, list[dict]], one: float, T: float) -> list[str]:
    """从写出来的文件读回来：吸过的两条 —— 音数、音高、歌词和终稿一样；网格那一段每个音都压在十六分线上（±1 ms）；
    尾声原样（±1 ms）；不重叠；原样的两条和终稿实际时间一样（±1 ms）。"""
    d = C.load_svp(path)
    got, fin = C.tracks(d), C.tracks(d_final)
    fails = []
    U = T / 4
    for src in TRACKS:
        q, orig, truth = got.get(f"你的终稿 {src}（吸格线）", []), got.get(f"你的终稿 {src}（原样）", []), fin[src]
        if len(q) != len(truth):
            fails.append(f"{src}（吸格线）音数 {len(q)} ≠ 终稿 {len(truth)}")
            continue
        for (a, da, ca, la), (b, db, cb, lb), r in zip(q, truth, results[src]):
            if ca != cb or la != lb:
                fails.append(f"{src} 有音的音高或歌词变了：{lb} {cb} → {la} {ca}")
                break
            if r["k16"] is not None:
                if abs((a - one) / U - round((a - one) / U)) * U > 0.001 or abs(a - r["q_on_s"]) > 0.001:
                    fails.append(f"{src}「{la}」{a:.3f}s 没压在十六分线上")
                    break
            elif abs(a - b) > 0.001 or abs((a + da) - (b + db)) > 0.001:
                fails.append(f"{src} 尾声的音「{la}」动了")
                break
        if any(q[i][0] + q[i][1] > q[i + 1][0] + 0.001 for i in range(len(q) - 1)):
            fails.append(f"{src}（吸格线）有音重叠")
        if len(orig) != len(truth) or any(abs(x[0] - y[0]) > 0.001 or abs(x[1] - y[1]) > 0.001 for x, y in zip(orig, truth)):
            fails.append(f"{src}（原样）和终稿的实际时间不一样")
    return fails


def main() -> int:
    fails = selftest()
    print("自检：", "通过（造的音吸对 ≥97%、整体偏移量得出；注入正好在中间的、挤一格的、结尾差 30 ms 的、尾声的、"
                  "0 和 2/3 拍的（要标三连音）、0 和 3/4 拍的（不许标），都按规则处理）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    r = json.loads((GC.OUT / "grid_check.json").read_text(encoding="utf-8"))
    bpm, one, end = r["grid"]["bpm_132"], r["grid"]["first_one_s_132"], r["tempo_span"]["to_s"]
    T = 60 / bpm
    d_final = C.load_svp(FINAL)
    fin = C.tracks(d_final)
    ai = list(C.tracks(C.load_svp(AI)).values())[0]
    ai_on = np.array([n[0] for n in ai])
    ai_res, _ = quantize(ai, one, T, end)                          # AI 自己也吸一遍，只拿来比
    ai_k = np.array([x["k16"] if x["k16"] is not None else -1 for x in ai_res])

    results, summary = {}, {}
    for src in TRACKS:
        res, bias = quantize(fin[src], one, T, end, ref_onsets=ai_on)
        results[src] = res
        g = [x for x in res if x["k16"] is not None]
        shifts = np.abs([x["shift_ms"] for x in g])
        flags = {}
        for x in res:
            for f in x["flags"]:
                flags[f] = flags.get(f, 0) + 1
        agree = same = 0
        dis = []
        for x in g:
            j = int(np.argmin(np.abs(ai_on - x["on_s"])))
            if abs(ai_on[j] - x["on_s"]) <= 0.080 and ai_k[j] >= 0:
                agree += 1
                if ai_k[j] == x["k16"]:
                    same += 1
                elif not any("AI" in f for f in x["flags"]):
                    dis.append((x["on_s"], x["lyric"], x["k16"], int(ai_k[j])))
        summary[src] = {"notes": len(res), "on_grid": len(g), "bias_ms": round(bias * 1000, 1),
                        "shift_ms_median": round(float(np.median(shifts)), 1), "shift_ms_max": round(float(shifts.max()), 1),
                        "flags": flags, "ai_matched": agree, "ai_same_cell": same,
                        "ai_disagree": [{"s": round(a, 2), "lyric": b, "ours_k16": c, "ai_k16": e} for a, b, c, e in dis]}
        print(f"\n{src}：{len(res)} 个音，{len(g)} 个在网格那一段（到 {end:.0f} s）· 整体偏移 {bias * 1000:+.1f} ms（先扣掉）· "
              f"起音挪了 中位 {np.median(shifts):.1f} ms、最多 {shifts.max():.1f} ms")
        print("  标记：", flags if flags else "无")
        print(f"  第二个裁判（AI 扒的同一个音，起音差 ≤ 80 ms）：对上 {agree} 个，吸到同一格 {same} 个"
              f"（{same / max(agree, 1):.0%}）；不同格、也没靠 AI 定的 {len(dis)} 个")

    LEARN.mkdir(parents=True, exist_ok=True)
    out_svp = LEARN / "傍晚_04-17终稿_吸格线.svp"
    out_json = LEARN / "melody_grid.json"
    for p in (out_svp, out_json):
        if p.exists():
            raise SystemExit(f"{p} 已经有了 —— 不覆盖；要重做先把旧的挪走")
    d = build(d_final, results, one, T, out_svp)
    out_svp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    fails = check_svp(out_svp, d_final, results, one, T)
    sfails, info = RT.stem_check(C.load_svp(out_svp), end)
    fails += sfails
    doc = {"说明": "《傍晚》04-17 终稿的主唱和和声1，吸到实测真网格上（逆向学习第 2 步）。只学网格那一段；尾声原样、标出来。",
           "来源": str(FINAL), "网格": {"bpm": bpm, "first_one_s": one, "beats_per_bar": 4, "grid_until_s": end,
                                       "sixteenth_s": T / 4, "小节号": "和歌本身一致；第 1 小节从 0.1039 s 起"},
           "规则": {"拿不准": f"离最近的十六分线超过 {AMB} 格", "AI 起音": f"只在拿不准时用，起音差 ≤ {REF_WIN * 1000:.0f} ms，两个取平均",
                    "三连音": "不判，按十六分吸，标出来", "结尾": "空隙不到半格就连着唱"},
           "代码": "E:/sv-bridge/spikes/m5-00-beat-grid/quantize_melody.py", "汇总": summary, "音": results}
    out_json.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写出 {out_svp}\n写出 {out_json}")
    print(f"  第二个裁判：键盘按这个工程的网格锁住 {info['span']['from_s']:.0f}–{info['span']['to_s']:.0f} s，"
          f"偏差中位 {info['median_ms']:+.1f} ms")
    print("  自检（从写出来的文件读回来）：", "通过（音数、音高、歌词和终稿一样；网格那一段每个音压在十六分线上；尾声原样；不重叠；"
          "原样的两条实际时间没动）" if not fails else "不通过")
    for f in fails:
        print("    ✗", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
