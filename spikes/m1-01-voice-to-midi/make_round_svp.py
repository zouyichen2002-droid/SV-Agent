# -*- coding: utf-8 -*-
"""把一版扒谱结果写成 SynthV 工程（新文件），给创作者在 SynthV 里试听、挑错。

创作者 09-29：「现在我想尝试一下你识别《傍晚》人声部分的 MIDI，不行再改，再一次一次尝试中进步」。
每一版（r01、r02……）都是新文件，放在 E:/sv-agent-data/probes/m1-01-voice-to-midi/rounds/<版>/：

- 模板：创作者的终稿（只读）—— 拿它的伴奏轨、主唱的声库和唱法设置、混音
- 主唱轨：换成扒出来的音符 + 拼音歌词（参数曲线清空、和声轨不要、音符库组不要）
- 多一条音频轨：Suno 人声分轨，当参考对着听
- 新的工程 uuid；导出设置改到本版的目录和文件名 —— 不会盖掉终稿的导出
- 速度照终稿的 120 BPM（终稿就是 120；音按绝对时间放，和音频对齐）

写完自检：用 compare_notes.tracks() 读回来，音数、每个音的起止（±1 ms）、音高、歌词逐个和源一致；
两条音频的文件都在。不一致就不算写成（退出码 1）。

    python make_round_svp.py <扒谱结果.mid> <版名，如 r01>
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


def build(notes: list, rnd: str, out_dir: pathlib.Path) -> dict:
    d = copy.deepcopy(C.load_svp(TEMPLATE))
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

    for i, t in enumerate((inst, ref_audio, vocal)):
        t["dispOrder"] = i
    d["tracks"] = [inst, ref_audio, vocal]
    d["library"] = []
    d["uuid"] = str(uuid.uuid4())
    d["renderConfig"].update(destination=str(out_dir / "render").replace("\\", "/"), filename=f"傍晚_扒谱_{rnd}")
    return d


def selfcheck(path: pathlib.Path, notes: list, rnd: str) -> list[str]:
    d = C.load_svp(path)
    fails = []
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


def main(src_mid: str, rnd: str) -> int:
    notes = list(C.midi_tracks(src_mid).values())[0]
    out_dir = ROUNDS / rnd
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"傍晚_扒谱_{rnd}.svp"
    if path.exists():
        raise SystemExit(f"{path} 已经有了 —— 每一版都写新文件，换个版名")
    path.write_text(json.dumps(build(notes, rnd, out_dir), ensure_ascii=False), encoding="utf-8")
    fails = selfcheck(path, notes, rnd)
    print(f"写出 {path}（{len(notes)} 个音）")
    print("自检：", "通过（读回来逐个音和源一致，两条音频都在）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
