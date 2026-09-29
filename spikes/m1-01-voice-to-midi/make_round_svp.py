# -*- coding: utf-8 -*-
"""把一版扒谱结果写成 SynthV 工程（新文件），给创作者在 SynthV 里试听、挑错。

创作者 09-29：「现在我想尝试一下你识别《傍晚》人声部分的 MIDI，不行再改，再一次一次尝试中进步」。
每一版（r01、r02……）都是新文件，放在 E:/sv-agent-data/probes/m1-01-voice-to-midi/rounds/<版>/：

- 模板：创作者的终稿（只读）—— 拿它的伴奏轨、主唱的声库和唱法设置、混音
- 主唱轨：换成扒出来的音符 + 拼音歌词（参数曲线清空、和声轨不要、音符库组不要）
- 多一条音频轨：Suno 人声分轨，当参考对着听
- 新的工程 uuid；导出设置改到本版的目录和文件名 —— 不会盖掉终稿的导出
- 速度照终稿的 120 BPM（终稿就是 120；音按绝对时间放，和音频对齐）

`--with-final`（创作者 09-29：「把我自己创作的那个拿过来放到同一个项目中，我对比」）：
再加一条「你的终稿」—— 终稿的 vocal1 原样搬过来（连同它引用的音符库组、参数、音高线，一个不改），文件名多个「_对比终稿」。

写完自检：用 compare_notes.tracks() 读回来，音数、每个音的起止（±1 ms）、音高、歌词逐个和源一致；
带了终稿的，终稿那条也要逐个音和终稿本身一致；音频文件都在。不一致就不算写成（退出码 1）。

    python make_round_svp.py <扒谱结果.mid> <版名，如 r01> [--with-final]
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import uuid

import compare_notes as C

sys.stdout.reconfigure(encoding="utf-8")
TEMPLATE = "F:/我的云端硬盘/临时文件3/SV2/傍晚(星尘).svp"          # 终稿，只读
VOCAL_STEM = "C:/Users/admin/Documents/Codex/2026-09-28/kan/outputs/傍晚_分轨与MIDI/WAV/01_人声.wav"
ROUNDS = C.OUT / "rounds"


def _new_ids(track: dict) -> dict:
    track["mainRef"]["uuid"] = str(uuid.uuid4())
    track["mainGroup"]["uuid"] = str(uuid.uuid4())
    track["mainRef"]["groupID"] = track["mainGroup"]["uuid"]
    track["groups"] = []
    return track


FINAL_NAME = "你的终稿（04-17 vocal1）"


def build(notes: list, rnd: str, out_dir: pathlib.Path, with_final: bool = False, stem: str = "") -> dict:
    d = copy.deepcopy(C.load_svp(TEMPLATE))
    final_track, final_groups = None, []
    if with_final:                                        # 终稿的 vocal1 原样搬过来：轨道 + 它引用的音符库组
        final_track = copy.deepcopy(next(t for t in d["tracks"] if t.get("name") == "vocal1"))
        final_track["name"] = FINAL_NAME
        wanted = {r["groupID"] for r in final_track.get("groups", [])}
        final_groups = [copy.deepcopy(g) for g in d["library"] if g["uuid"] in wanted]
        assert len(final_groups) == len(wanted), "终稿 vocal1 引用的音符库组没找全"
    tempo = d["time"]["tempo"]
    assert len(tempo) == 1, f"模板有 {len(tempo)} 个速度标记，这里只会换算单一速度"
    bpm = tempo[0]["bpm"]
    to_blick = lambda s: int(round(s * bpm / 60 * C.Q))

    inst = next(t for t in d["tracks"] if t["mainRef"].get("isInstrumental"))
    vocal = next(t for t in d["tracks"] if t.get("name") == "vocal1")
    inst = _new_ids(copy.deepcopy(inst))
    ref_audio = _new_ids(copy.deepcopy(inst))
    ref_audio["name"] = "Suno 人声（参考）"
    ref_audio["mainRef"]["audio"]["filename"] = VOCAL_STEM
    vocal = _new_ids(copy.deepcopy(vocal))
    vocal["name"] = f"扒谱 {rnd}"
    g = vocal["mainGroup"]
    for p in g["parameters"].values():
        if isinstance(p, dict) and "points" in p:
            p["points"] = []
    g["pitchControls"] = []

    out, prev_end = [], None
    for s, dur, cents, ly in sorted(notes):
        on, off = to_blick(s), to_blick(s + dur)
        if prev_end is not None and on < prev_end:        # 单声部：和前一个重叠就把前一个截短
            out[-1]["duration"] = max(1, on - out[-1]["onset"])
        pitch = int(round(cents / 100))
        out.append({"uuid": uuid.uuid4().hex[:16], "musicalType": "singing", "onset": on, "duration": max(1, off - on),
                    "lyrics": ly or "la", "phonemes": "", "accent": "", "pitch": pitch,
                    "detune": int(round(cents - pitch * 100)),
                    "attributes": {"evenSyllableDuration": True, "muted": False},
                    "takes": {"activeTakeId": 0, "takes": [{"id": 0, "seedDuration": 0, "seedPitch": 0,
                                                            "seedTimbre": 0, "liked": False}]}})
        prev_end = off
    g["notes"] = out

    tracks = [inst, ref_audio] + ([final_track] if final_track else []) + [vocal]
    for i, t in enumerate(tracks):
        t["dispOrder"] = i
    d["tracks"] = tracks
    d["library"] = final_groups
    d["uuid"] = str(uuid.uuid4())
    d["renderConfig"].update(destination=str(out_dir / "render").replace("\\", "/"), filename=f"傍晚_扒谱_{rnd}{stem}")
    return d


def selfcheck(path: pathlib.Path, notes: list, rnd: str, with_final: bool = False) -> list[str]:
    d = C.load_svp(path)
    fails = []
    if with_final:
        mine = C.tracks(d).get(FINAL_NAME, [])
        truth = C.tracks(C.load_svp(TEMPLATE))["vocal1"]
        if mine != truth:
            fails.append(f"终稿那条和终稿本身不一致：{len(mine)} 个音 vs {len(truth)} 个")
    got = C.tracks(d).get(f"扒谱 {rnd}", [])
    src = sorted(notes)
    if len(got) != len(src):
        fails.append(f"音数 {len(got)} ≠ 源 {len(src)}")
    for k, ((a, da, ca, la), (b, db, cb, lb)) in enumerate(zip(got, src)):
        if abs(a - b) > 0.001 or (abs(da - db) > 0.001 and k < len(src) - 1 and abs((a + da) - src[k + 1][0]) > 0.001) \
                or abs(ca - round(cb / 100) * 100) > 0.5 or la != (lb or "la"):
            fails.append(f"第 {k + 1} 个音对不上：写入 {a:.3f}/{da:.3f}/{ca}/{la} · 源 {b:.3f}/{db:.3f}/{cb}/{lb}")
            if len(fails) > 5:
                break
    for t in d["tracks"]:
        if t["mainRef"].get("isInstrumental") and not pathlib.Path(t["mainRef"]["audio"]["filename"]).exists():
            fails.append(f"音频不存在：{t['mainRef']['audio']['filename']}")
    return fails


def main(src_mid: str, rnd: str, *flags: str) -> int:
    with_final = "--with-final" in flags
    stem = "_对比终稿" if with_final else ""
    notes = list(C.midi_tracks(src_mid).values())[0]
    out_dir = ROUNDS / rnd
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"傍晚_扒谱_{rnd}{stem}.svp"
    if path.exists():
        raise SystemExit(f"{path} 已经有了 —— 每一版都写新文件，换个版名")
    path.write_text(json.dumps(build(notes, rnd, out_dir, with_final, stem), ensure_ascii=False), encoding="utf-8")
    fails = selfcheck(path, notes, rnd, with_final)
    print(f"写出 {path}（扒谱 {len(notes)} 个音{'，另有你的终稿' if with_final else ''}）")
    print("自检：", ("通过（读回来逐个音和源一致" + ("，终稿那条和终稿本身逐个音一致" if with_final else "") + "，音频都在）")
          if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
