# -*- coding: utf-8 -*-
"""没有现成 SynthV 工程的歌（比如《刽子手》：B 站下来的整首音频）做一个最小的模板，给 song_round.py 用：
一条人声轨（声库、混音设置从给的工程里抄）+ 伴奏 + 参考人声。

- 速度表就是我们量的（tempo_map.json）—— song_round 再按它重排时什么都不会动
- 音频轨里 SynthV 自己存的分析（bpm、alternativeBPMs、beatLocations）也换成这首的：拍点按速度表算、bpm 取有速度的第一段；
  不留别的歌的值（你存过的工程里这五项都有，照样写全）。duration 读 wav
- 人声轨一个音都没有（只带声库设置），song_round 生成工程时不留它
- 两处静音都设：伴奏放、参考人声静音（见 song_round 里那段说明）
- 只写新文件；写完读回来核对，不过就不算数

    python make_template.py <配置.json>
配置：{"base": 抄设置的工程, "base_voice_track": 人声轨名, "base_accomp_track": 伴奏轨名, "base_ref_track": 参考人声轨名,
       "voice_track_name": 新模板人声轨的名字, "accomp": 伴奏 wav, "ref_vocal": 参考人声 wav, "tempo_map": tempo_map.json, "out": 输出 .svp}
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import uuid

import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m5-00-beat-grid"))
sys.path.insert(0, str(HERE))
import beat_grid as BG                                          # noqa: E402
import compare_notes as C                                       # noqa: E402

Q = BG.Q
TOL = 1e-3


def fresh_group(g: dict) -> dict:
    g = copy.deepcopy(g)
    g["uuid"] = str(uuid.uuid4())
    g["notes"], g["pitchControls"] = [], []
    for p in g.get("parameters", {}).values():
        if isinstance(p, dict) and "points" in p:
            p["points"] = []
    return g


def track_from(base_track: dict, name: str, mute: bool, audio: dict | None = None) -> dict:
    t = copy.deepcopy(base_track)
    t["name"] = name
    t["mainGroup"] = fresh_group(t["mainGroup"])
    t["mainRef"]["uuid"] = str(uuid.uuid4())
    t["mainRef"]["groupID"] = t["mainGroup"]["uuid"]
    t["mainRef"]["blickOffset"] = 0
    t["mainRef"]["mute"] = t["mixer"]["mute"] = mute
    t["mixer"]["solo"] = False
    t["groups"] = []
    if audio is not None:
        t["mainRef"]["audio"] = audio
    return t


def bpm_at(tempo: list[dict], s: float) -> float:
    marks = sorted(tempo, key=lambda x: x["position"])
    cur = marks[0]["bpm"]
    for m in marks:
        if BG.blick_to_seconds(m["position"], tempo) <= s + 1e-6:
            cur = m["bpm"]
    return float(cur)


def audio_entry(wav: str, tempo: list[dict], metered: list) -> dict:
    info = sf.info(wav)
    dur = info.frames / info.samplerate
    beats, k = [], 0
    while (s := BG.blick_to_seconds(k * Q, tempo)) <= dur:
        beats.append(float(s))
        k += 1
    bpm = bpm_at(tempo, metered[0][0]) if metered else float(tempo[0]["bpm"])
    return {"filename": str(wav).replace("\\", "/"), "duration": dur, "bpm": bpm,
            "alternativeBPMs": [bpm, bpm * 2, bpm / 2], "beatLocations": beats}


def check(path: pathlib.Path, cfg: dict, base: dict, tempo: list[dict]) -> list[str]:
    d = C.load_svp(path)
    fails = []
    names = [t["name"] for t in d["tracks"]]
    if names != [cfg["voice_track_name"], "伴奏", cfg.get("ref_name", "原唱人声（参考，静音）")]:
        fails.append(f"轨不对：{names}")
        return fails
    bv = next(t for t in base["tracks"] if t["name"] == cfg["base_voice_track"])
    v, acc, ref = d["tracks"]
    for k in ("database", "dictionary", "voice", "voicePresetName"):
        if v["mainRef"].get(k) != bv["mainRef"].get(k):
            fails.append(f"人声轨的 {k} 和抄的工程不一样")
    if C.tracks(d):
        fails.append("模板里不该有音符")
    plays = lambda t: not t["mainRef"].get("mute") and not t["mixer"].get("mute")        # noqa: E731
    if not plays(acc) or plays(ref) or not plays(v):
        fails.append("静音不对：伴奏、人声轨要放，参考人声要静音")
    for t, wav in ((acc, cfg["accomp"]), (ref, cfg["ref_vocal"])):
        a = t["mainRef"]["audio"]
        info = sf.info(wav)
        if a["filename"] != str(wav).replace("\\", "/") or not pathlib.Path(a["filename"]).exists():
            fails.append(f"音频文件不对：{a['filename']}")
        if abs(a["duration"] - info.frames / info.samplerate) > TOL:
            fails.append(f"{t['name']} 的时长 {a['duration']} 和 wav 不一样")
        b = a["beatLocations"]
        if not b or b[0] < 0 or b[-1] > a["duration"] + TOL or any(y <= x for x, y in zip(b, b[1:])):
            fails.append(f"{t['name']} 的拍点不对")
        if any(abs(BG.blick_to_seconds(k * Q, d["time"]["tempo"]) - s) > TOL for k, s in enumerate(b)):
            fails.append(f"{t['name']} 的拍点和速度表对不上")
    if d["time"]["tempo"] != tempo:
        fails.append("速度表不是给的那张")
    return fails


def main(cfg_path: str) -> int:
    cfg = json.loads(pathlib.Path(cfg_path).read_text(encoding="utf-8"))
    out = pathlib.Path(cfg["out"])
    if out.exists():
        raise SystemExit(f"{out} 已经有了 —— 只写新文件")
    base = C.load_svp(cfg["base"])
    tm = json.loads(pathlib.Path(cfg["tempo_map"]).read_text(encoding="utf-8"))["map"]
    tempo, metered = tm["tempo"], tm["metered"]
    bt = {t["name"]: t for t in base["tracks"]}
    tracks = [track_from(bt[cfg["base_voice_track"]], cfg["voice_track_name"], mute=False),
              track_from(bt[cfg["base_accomp_track"]], "伴奏", mute=False, audio=audio_entry(cfg["accomp"], tempo, metered)),
              track_from(bt[cfg["base_ref_track"]], cfg.get("ref_name", "原唱人声（参考，静音）"), mute=True,
                         audio=audio_entry(cfg["ref_vocal"], tempo, metered))]
    for i, t in enumerate(tracks):
        t["dispOrder"] = i
    d = {"version": base["version"], "uuid": str(uuid.uuid4()),
         "time": {"meter": [{"index": 0, "numerator": 4, "denominator": 4}], "tempo": tempo, "startTimeSeconds": 0.0},
         "library": [], "tracks": tracks,
         "renderConfig": {**copy.deepcopy(base["renderConfig"]), "destination": "", "filename": "未命名"},
         "projectMixer": copy.deepcopy(base.get("projectMixer", {}))}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    fails = check(out, cfg, base, tempo)
    a = tracks[1]["mainRef"]["audio"]
    print(f"写出 {out}：人声轨「{cfg['voice_track_name']}」（{tracks[0]['mainRef']['database'].get('name')}）· 伴奏 · 参考人声；"
          f"速度表 {len(tempo)} 段、拍点 {len(a['beatLocations'])} 个、bpm {a['bpm']:.4f}、时长 {a['duration']:.3f} 秒")
    print("  自检（读回来）：", "通过" if not fails else "不通过")
    for f in fails:
        print("    ✗", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
