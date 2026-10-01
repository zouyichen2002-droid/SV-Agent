# -*- coding: utf-8 -*-
"""翻唱一首新歌的第一版：扒出的音 → 按歌词修字 → 挑八度 → 写到这首歌的速度表上（可以分段变速）→ 有速度的段里吸格线。

《傍晚》一步一步试出来的做法，串成一条（每一步用的都是那时的函数，只换这首歌的输入）：
1. Vocal2Midi（GAME 切音 + 听写）的 .mid                                     —— run_vocal2midi.py 先跑
2. 按歌词修字：拼音全局对齐，只改字、不动音（m1-03 repair_lyrics.repair）
3. 挑八度：录音里确认两个八度一起唱的句子整句取上（m1-02 pick_octave.pick，给这首的人声分轨和 basic-pitch 原样输出）
4. 速度表：m5-00 tempo_map.py 的结果（分段、在小节线上换速度；前奏、尾声自由）
5. 第一版吸格线（创作者 09-29：「只有第一版是要吸格线的」）：有速度的段里按拍数吸十六分（quantize_melody.quantize），自由段原样
工程：模板（只读）整个换到速度表上（retime：每条轨实际时间不动）；模板里原来的扒谱轨改名「对照」、静音；原唱人声静音；加上我们这条

    python song_round.py <这首歌的配置.json>
配置：name、template（模板工程，只读）、vocal_template_track（拿它的声库和唱法设置）、vocal_stem、lyrics、v2m_mid、bp_raw、
      tempo_map、rounds（轮次目录）、round（版名）
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import uuid

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
for sub in ("m1-02-harmony", "m1-03-lyrics", "m5-00-beat-grid"):
    sys.path.insert(0, str(HERE.parent / sub))
sys.path.insert(0, str(HERE))
import beat_grid as BG                                          # noqa: E402
import clean_lyrics as LC                                       # noqa: E402
import compare_notes as C                                       # noqa: E402
import cover_rules as CR                                        # noqa: E402
import eval_lyrics as E                                         # noqa: E402
import grid_check as GC                                         # noqa: E402
import pick_octave as P                                         # noqa: E402
import quantize_melody as QM                                    # noqa: E402
import repair_lyrics as RL                                      # noqa: E402
import retime_svp as RT                                         # noqa: E402

Q = BG.Q
TOL = 0.001


FRAG = 0.040            # 短于 40 ms 的算碎片


def merge_fragments(notes: list[tuple]) -> tuple[list[tuple], int]:
    """GAME 切音的毛刺：短于 40 ms、和紧挨着的音同音高、中间空隙 ≤ 10 ms → 并进那个音（先看后一个，再看前一个）。
    《潮声回响》新分离的人声扒出 16 个（如 109.694 s 10 ms + 109.704 s 7 ms，后面紧跟同音高 361 ms 的）；《傍晚》r01 一个都没有。
    字：碎片上有字、那个音是拖音（-）或没字 → 字带过去。"""
    out = [list(n) for n in sorted(notes)]
    merged, i = 0, 0
    same = lambda a, b: int(round(a[2] / 100)) == int(round(b[2] / 100))                   # noqa: E731
    while i < len(out):
        s, d, c, ly = out[i]
        if d < FRAG:
            nxt = out[i + 1] if i + 1 < len(out) else None
            prv = out[i - 1] if i > 0 else None
            if nxt and same(out[i], nxt) and nxt[0] - (s + d) <= 0.010:
                nly = ly if nxt[3] in ("", "-") and ly not in ("", "-") else nxt[3]
                out[i + 1] = [s, nxt[0] + nxt[1] - s, nxt[2], nly]
                del out[i]
                merged += 1
                continue
            if prv and same(out[i], prv) and s - (prv[0] + prv[1]) <= 0.010:
                pl = ly if prv[3] in ("", "-") and ly not in ("", "-") else prv[3]
                out[i - 1] = [prv[0], s + d - prv[0], prv[2], pl]
                del out[i]
                merged += 1
                continue
        i += 1
    return [tuple(n) for n in out], merged


def _fragment_selftest() -> list[str]:
    fails = []
    notes = [(1.000, 0.010, 7800.0, "a"), (1.010, 0.008, 7800.0, "-"), (1.018, 0.361, 7800.0, "-"),   # 碎片 ×2 + 真音
             (2.000, 0.030, 6000.0, "b"), (2.030, 0.300, 6200.0, "c"),                                   # 短但音高不同：不动
             (3.000, 0.030, 6000.0, "d"), (3.100, 0.300, 6000.0, "e")]                                   # 短但中间空 70 ms：不动
    got, n = merge_fragments(notes)
    if n != 2 or len(got) != 5 or got[0][0] != 1.000 or abs(got[0][1] - 0.379) > 1e-9 or got[0][3] != "a":
        fails.append(f"碎片合并：{n} 次，结果 {got[:2]}")
    return fails


def quantize_on_map(notes: list[tuple], tempo: list[dict], metered: list[tuple[float, float]]) -> tuple[list[dict], float]:
    """有速度的段里：时间先按速度表换成「第几拍」，在拍上吸十六分（quantize_melody.quantize，一拍 = 1），再换回秒；自由段原样。"""
    beat = lambda t: RT.seconds_to_blick(t, tempo) / Q                               # noqa: E731
    inside = [any(a - 1e-6 <= n[0] < b - 1e-6 for a, b in metered) for n in notes]
    nb = [(beat(n[0]), beat(n[0] + n[1]) - beat(n[0]), n[2], n[3]) for n, ok in zip(notes, inside) if ok]
    res_in, bias = QM.quantize(nb, 0.0, 1.0, float("inf")) if nb else ([], 0.0)
    out, it = [], iter(res_in)
    for i, (n, ok) in enumerate(zip(notes, inside)):
        if ok:
            r = next(it)
            k, kd = r["k16"], r["dur16"]
            q_on, q_off = BG.blick_to_seconds(k * Q // 4, tempo), BG.blick_to_seconds((k + kd) * Q // 4, tempo)
            r.update(i=i, on_s=round(n[0], 4), off_s=round(n[0] + n[1], 4), q_on_s=q_on, q_off_s=q_off,
                     shift_ms=round((q_on - n[0]) * 1000, 1))
        else:
            r = {"i": i, "lyric": n[3], "pitch": int(round(n[2] / 100)), "cents": float(n[2]), "on_s": n[0], "off_s": n[0] + n[1],
                 "q_on_s": n[0], "q_off_s": n[0] + n[1], "k16": None, "dur16": None, "bar": None, "beat": None, "pos16": None,
                 "shift_ms": 0.0, "flags": ["自由段，没有网格（原样）"]}
        out.append(r)
    for a, b in zip(out[:-1], out[1:]):                           # 有速度的段和自由段交界处：不许重叠
        if a["q_off_s"] > b["q_on_s"] + 1e-9:
            a["q_off_s"] = b["q_on_s"]
            a["flags"].append("结尾截到下一个音")
    return out, bias


def bpm_at(tempo: list[dict], s: float) -> float:
    """速度表在第 s 秒用的是哪个速度。"""
    cur = tempo[0]["bpm"]
    for m in sorted(tempo, key=lambda x: x["position"]):
        if BG.blick_to_seconds(m["position"], tempo) <= s + 1e-6:
            cur = m["bpm"]
    return float(cur)


def blicks_of(r: dict, tempo: list[dict]) -> tuple[int, int]:
    if r["k16"] is not None and "结尾截到下一个音" not in r["flags"]:
        return round(r["k16"] * Q / 4), round(r["dur16"] * Q / 4)
    a = round(RT.seconds_to_blick(r["q_on_s"], tempo))
    return a, max(1, round(RT.seconds_to_blick(r["q_off_s"], tempo)) - a)


def build(cfg: dict, tempo: list[dict], rows: list[dict], track_name: str, out_svp: pathlib.Path) -> dict:
    d0 = C.load_svp(cfg["template"])
    d = RT.retime(d0, {"meter": [{"index": 0, "numerator": 4, "denominator": 4}], "tempo": tempo})
    tmpl = next(t for t in d["tracks"] if t.get("name") == cfg["vocal_template_track"])
    acc_in_tmpl = pathlib.Path(cfg.get("template_accomp") or cfg["accomp"]).name   # 模板里原来那条伴奏的文件名
    for t in d["tracks"]:
        if t["mainRef"].get("audio"):
            if pathlib.Path(t["mainRef"]["audio"]["filename"]).name == acc_in_tmpl:
                # 伴奏：配置里的伴奏换进去（换了分离模型时和模板里的不是同一个文件；位置不动）
                t["mainRef"]["audio"]["filename"] = str(cfg["accomp"]).replace("\\", "/")
                if cfg.get("accomp_name"):
                    t["name"] = cfg["accomp_name"]
                t["mainRef"]["mute"] = t.setdefault("mixer", {})["mute"] = False
            else:
                # 伴奏以外的音频轨都当参考人声：改名、静音；配置里给了 ref_vocal_audio（比如新分出来的主唱）就换成它
                if cfg.get("ref_vocal_audio"):
                    t["mainRef"]["audio"]["filename"] = str(cfg["ref_vocal_audio"]).replace("\\", "/")
                t["name"] = cfg.get("ref_vocal_name", "原唱人声（参考，静音）")
                t["mainRef"]["mute"] = t.setdefault("mixer", {})["mute"] = True
        else:
            t["name"] = f"对照：{t.get('name')}（模板里原来的，静音）"
            t["mainRef"]["mute"] = t.setdefault("mixer", {})["mute"] = True
    # 静音有两处：mainRef.mute 和混音台的 mixer.mute（SynthV 轨头上那个 M）。两处都设 ——
    # 《潮声回响》r01–r05 只设了前一处，扒谱那条从模板人声轨继承了混音台静音，打开时听不到
    for t in d["tracks"]:
        t["mixer"]["solo"] = False
    ours = copy.deepcopy(tmpl)
    ours["name"] = track_name
    ours["mainRef"]["mute"] = ours["mixer"]["mute"] = False
    ours["mainRef"]["uuid"] = str(uuid.uuid4())
    ours["mainGroup"] = {**copy.deepcopy(tmpl["mainGroup"]), "uuid": str(uuid.uuid4()), "notes": [], "pitchControls": []}
    ours["mainRef"]["groupID"] = ours["mainGroup"]["uuid"]
    ours["mainRef"]["blickOffset"] = 0
    ours["groups"] = []
    for p in ours["mainGroup"]["parameters"].values():
        if isinstance(p, dict) and "points" in p:
            p["points"] = []
    notes = []
    for r in rows:
        a, du = blicks_of(r, tempo)
        pitch = r["pitch"]
        notes.append({"uuid": uuid.uuid4().hex[:16], "musicalType": "singing", "onset": int(a), "duration": int(du),
                      "lyrics": r["lyric"] or "la", "phonemes": "", "accent": "", "pitch": pitch,
                      "detune": int(round(r["cents"] - pitch * 100)),
                      "attributes": {"evenSyllableDuration": True, "muted": False},
                      "takes": {"activeTakeId": 0, "takes": [{"id": 0, "seedDuration": 0, "seedPitch": 0, "seedTimbre": 0,
                                                              "liked": False}]}})
    ours["mainGroup"]["notes"] = notes
    # 模板里一个音都没有的音符轨（make_template.py 做的模板：那条人声轨只用来带声库设置）不留，免得多一条空的「对照」
    lib = {g["uuid"]: g for g in d.get("library", [])}
    d["tracks"] = [t for t in d["tracks"] if t["mainRef"].get("audio") or t["mainGroup"].get("notes")
                   or any((lib.get(r.get("groupID")) or {}).get("notes") for r in t.get("groups", []))]
    d["tracks"].append(ours)
    for i, t in enumerate(d["tracks"]):
        t["dispOrder"] = i
    d["uuid"] = str(uuid.uuid4())
    d["renderConfig"].update(destination=str(out_svp.parent / "render").replace("\\", "/"), filename=out_svp.stem)
    return d


def check(path: pathlib.Path, cfg: dict, tempo: list[dict], rows: list[dict], track_name: str) -> list[str]:
    """从写出来的文件读回来：我们这条 —— 音数、音高、歌词；吸过的压在十六分线上、自由段原样；不重叠。
    模板里原来的轨实际时间不动；音频位置不动；速度表是给的那张。"""
    d = C.load_svp(path)
    fails = []
    got = C.tracks(d).get(track_name, [])
    if len(got) != len(rows):
        return [f"「{track_name}」音数 {len(got)} ≠ {len(rows)}"]
    for (x, dx, cx, lx), r in zip(got, rows):
        if int(round(cx / 100)) != r["pitch"] or lx != (r["lyric"] or "la"):
            fails.append(f"音高或歌词不对：{lx} {cx} vs {r['lyric']} {r['pitch']}")
            break
        if abs(x - r["q_on_s"]) > TOL or abs((x + dx) - r["q_off_s"]) > TOL:
            fails.append(f"「{lx}」的位置 {x:.3f}–{x + dx:.3f} 不是算好的 {r['q_on_s']:.3f}–{r['q_off_s']:.3f}")
            break
        if r["k16"] is not None:
            k = RT.seconds_to_blick(x, d["time"]["tempo"]) / (Q / 4)
            if abs(k - r["k16"]) * (Q / 4) > 1000:
                fails.append(f"「{lx}」{x:.3f}s 没压在十六分线上")
                break
    if any(got[i][0] + got[i][1] > got[i + 1][0] + TOL for i in range(len(got) - 1)):
        fails.append("有音重叠")
    t0, t1 = C.tracks(C.load_svp(cfg["template"])), C.tracks(d)
    for name, v in t0.items():
        w = t1.get(f"对照：{name}（模板里原来的，静音）", [])
        if len(w) != len(v) or any(abs(p[0] - q[0]) > TOL or abs(p[1] - q[1]) > TOL or p[2:] != q[2:] for p, q in zip(v, w)):
            fails.append(f"模板里的「{name}」实际时间变了")
    a0 = RT.timeline(C.load_svp(cfg["template"]))["audio"]
    a1 = RT.timeline(d)["audio"]
    if sorted(round(v, 6) for v in a0.values()) != sorted(round(v, 6) for v in a1.values()):
        fails.append("音频位置变了")
    plays = lambda t: not t["mainRef"].get("mute") and not t.get("mixer", {}).get("mute")     # noqa: E731  两处静音都没开才算在放
    audio = [t for t in d["tracks"] if t["mainRef"].get("audio")]
    playing = [t["mainRef"]["audio"]["filename"] for t in audio if plays(t)]
    if playing != [str(cfg["accomp"]).replace("\\", "/")]:
        fails.append(f"在放的音频轨应该只有给的伴奏，实际是 {playing}")
    singing = [t.get("name") for t in d["tracks"] if not t["mainRef"].get("audio") and plays(t)]
    if singing != [track_name]:
        fails.append(f"在放的音符轨应该只有「{track_name}」，实际是 {singing}")
    if any(t.get("mixer", {}).get("solo") for t in d["tracks"]):
        fails.append("有轨开着独奏")
    for t in audio:
        if not pathlib.Path(t["mainRef"]["audio"]["filename"]).exists():
            fails.append(f"音频文件不存在：{t['mainRef']['audio']['filename']}")
    if d["time"]["tempo"] != tempo:
        fails.append("速度表不是给的那张")
    return fails


def main(cfg_path: str) -> int:
    cfg = json.loads(pathlib.Path(cfg_path).read_text(encoding="utf-8"))
    rnd_dir = pathlib.Path(cfg["rounds"]) / cfg["round"]
    out_svp = rnd_dir / f"{cfg['name']}_扒谱_{cfg['round']}.svp"
    before_svp = rnd_dir / f"{cfg['name']}_扒谱_{cfg['round']}_吸格线前.svp"
    for p in (out_svp, before_svp):
        if p.exists():
            raise SystemExit(f"{p} 已经有了 —— 每一版都写新文件")
    tm = json.loads(pathlib.Path(cfg["tempo_map"]).read_text(encoding="utf-8"))["map"]
    tempo, metered = tm["tempo"], [tuple(x) for x in tm["metered"]]

    fails = _fragment_selftest()
    if fails:
        print("碎片合并的自检不过：", fails)
        return 1
    notes0, n_frag = merge_fragments(sorted(E.load(cfg["v2m_mid"])))
    print(f"GAME 的碎片（短于 {FRAG * 1000:.0f} ms、紧贴同音高）并掉 {n_frag} 个")
    rule_log: dict[str, list] = {}
    kept_lens: list[int] | None = None                           # 放进主唱的每行字数（新规矩 4 用）
    if cfg.get("lyrics"):
        chars, pys = E.text_pinyin(cfg["lyrics"])
        fails = RL.selftest(chars, pys)
        if fails:
            print("修歌词的自检不过：", fails)
            return 1
        lyr_used = cfg["lyrics"]
        if cfg.get("rules_0930"):                                # 09-30 新规矩 1：和听写几乎对不上的行整行不放
            fails = CR.selftest()
            if fails:
                print("新规矩的自检不过：", fails)
                return 1
            lines = LC.clean_lines(open(cfg["lyrics"], encoding="utf-8").read())
            rates = CR.line_match(lines, RL.A.align(pys, [n[3] for n in notes0], [n[1] for n in notes0]))
            keep, drop = CR.drop_unsung(lines, rates)
            starts = np.cumsum([0] + [len(ln) for ln in lines])
            chars = [ch for li in keep for ch in chars[starts[li]:starts[li + 1]]]
            pys = [p for li in keep for p in pys[starts[li]:starts[li + 1]]]
            rule_log["拿掉的行"] = [{"行": li + 1, "字数": len(lines[li]), "对上": round(rates[li], 2)} for li in drop]
            kept_lens = [len(lines[li]) for li in keep]
            rnd_dir.mkdir(parents=True, exist_ok=True)
            lyr_used = rnd_dir / "歌词_放进主唱的行.txt"
            lyr_used.write_text("\n".join(lines[li] for li in keep) + "\n", encoding="utf-8")
            print(f"和听写对不上（对上的字不到 {CR.LINE_MIN_MATCH:.0%}）、整行不放的：{len(drop)} 行 —— "
                  + "；".join(f"第 {d['行']} 行（{d['字数']} 字）" for d in rule_log["拿掉的行"]))
        fixed, log = RL.repair(notes0, chars, pys)
        acts = {}
        for x in log:
            acts[x["动作"]] = acts.get(x["动作"], 0) + 1
        before_lyr, after_lyr = E.evaluate(notes0, cfg["lyrics"]), E.evaluate(fixed, str(lyr_used))
        for dct in (before_lyr, after_lyr):                      # evaluate 顺手拿《傍晚》的终稿比 —— 对别的歌没意义
            dct.pop("对终稿", None)
        diff = RL.sung_differently(notes0, chars, pys, log)
        print(f"扒出 {len(notes0)} 个音；歌词 {len(chars)} 个字。修歌词：{acts}")
        print(f"  歌词对得上的：听写 {before_lyr} → 修完 {after_lyr}")
        print(f"  听写和歌词明显不一样的 {len(diff)} 处（照歌词放了）")
    else:                                                        # 没给歌词：字就用听写出来的（拼音），不修
        chars, fixed, log, acts, diff = [], list(notes0), [], {}, []
        before_lyr = after_lyr = {"说明": "没给歌词：只用听写出来的字（拼音），不修"}
        print(f"扒出 {len(notes0)} 个音；没给歌词 —— 字用听写出来的，不修")

    picked, new, why, other = P.pick(fixed, cfg["vocal_stem"], cfg["bp_raw"])
    ps = [int(round(c / 100)) for _, _, c, _ in fixed]
    changed = [k for k in range(len(fixed)) if new[k] != ps[k]]
    doubled = sum(1 for o in other if o)
    print(f"挑八度：录音里两个八度一起唱的音 {doubled} 个，改了八度的 {len(changed)} 个")
    if cfg.get("rules_0930"):                                    # 09-30 新规矩 2、3：同音高的接续（长音截两段写韵母）、念唱拉平
        if int(cfg["rules_0930"]) >= 2 and kept_lens:            # 新规矩 4（09-30 晚）：下一句的第一个字跑到上一句末尾
            picked, rule_log["下一句的第一个字跑到上一句末尾"], rule_log["要你手放的字"] = CR.fix_line_starts(
                picked, kept_lens, pys, lambda s: 60.0 / bpm_at(tempo, s))
            key = "下一句的第一个字跑到上一句末尾"
            print(f"{key}：{len(rule_log[key])} 处" + "".join(f"\n    {x}" for x in rule_log[key]))
        picked, rule_log["同音高的接续"] = CR.same_pitch(picked)
        picked, rule_log["念唱"] = CR.chant(picked, lambda s: 60.0 / bpm_at(tempo, s))
        for k in ("同音高的接续", "念唱"):
            print(f"{k}：{len(rule_log[k])} 处" + "".join(f"\n    {x}" for x in rule_log[k]))

    raw_rows = [{"i": i, "lyric": n[3], "pitch": int(round(n[2] / 100)), "cents": float(n[2]), "on_s": n[0], "off_s": n[0] + n[1],
                 "q_on_s": n[0], "q_off_s": n[0] + n[1], "k16": None, "dur16": None, "flags": []}
                for i, n in enumerate(picked)]
    rows, bias = quantize_on_map(picked, tempo, metered)
    g = [r for r in rows if r["k16"] is not None]
    shifts = np.abs([r["shift_ms"] for r in g]) if g else np.array([0.0])
    flags = {}
    for r in rows:
        for f in r["flags"]:
            flags[f] = flags.get(f, 0) + 1
    print(f"吸格线：{len(g)} / {len(rows)} 个音在有速度的段里吸了；整体偏移 {bias * 1000:+.1f}（千分之一拍，先扣掉）；"
          f"起音挪了中位 {np.median(shifts):.1f} ms、最多 {shifts.max():.1f} ms；标记 {flags}")

    rnd_dir.mkdir(parents=True, exist_ok=True)
    name_q, name_raw = f"扒谱 {cfg['round']}（第一版 · 吸格线）", f"扒谱 {cfg['round']}（吸格线前）"
    for path, rr, nm in ((out_svp, rows, name_q), (before_svp, raw_rows, name_raw)):
        path.write_text(json.dumps(build(cfg, tempo, rr, nm, path), ensure_ascii=False), encoding="utf-8")
        f = check(path, cfg, tempo, rr, nm)
        print(f"写出 {path}\n  自检（读回来）：", "通过" if not f else "不通过")
        for x in f:
            print("    ✗", x)
        fails += f
    d_out = C.load_svp(out_svp)
    tabs = {}
    acc, sr_acc = GC.mono(cfg["accomp"])
    t, w = GC.strength(acc, sr_acc)
    dur = len(acc) / sr_acc
    beats = []
    while not beats or beats[-1] < dur:                           # 从写出来的速度表算工程的每一拍
        beats.append(BG.blick_to_seconds(len(beats) * Q, d_out["time"]["tempo"]))
    for a, b in metered:                                          # 第二个裁判：伴奏按工程自己的网格（每段各自的拍）折一次
        inside = [x for x in beats if a <= x < b]
        if len(inside) < 8:
            continue
        rows_l = GC.lock_table(t, w, 60 / float(np.median(np.diff(inside))), inside[0], dur)
        seg = [r for r in rows_l if a - 15 < r["from_s"] < b]
        tabs[f"{a:.0f}–{b:.0f}"] = seg
        print(f"  第二个裁判（伴奏按工程网格，{a:.0f}–{b:.0f} s）：" + " ".join(
            f"{r['from_s']:.0f}:{r['phase_ms']:+.0f}" if r["locked"] else f"{r['from_s']:.0f}:·" for r in seg))
    res = {"config": cfg, "notes_v2m": len(notes0), "lyrics_chars": len(chars), "repair_actions": acts, "repair_log": log,
           "lyrics_before": before_lyr, "lyrics_after": after_lyr, "sung_differently": diff,
           "octave": {"doubled_notes": doubled, "changed": len(changed), "why": why}, "rules_0930": rule_log,
           "snap": {"bias_beats_x1000": round(bias * 1000, 1), "flags": flags, "shift_ms_median": float(np.median(shifts)),
                    "shift_ms_max": float(shifts.max())}, "rows": rows, "grid_check": tabs}
    (rnd_dir / f"{cfg['name']}_扒谱_{cfg['round']}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
