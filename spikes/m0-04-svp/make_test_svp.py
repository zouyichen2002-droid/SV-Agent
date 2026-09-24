# -*- coding: utf-8 -*-
"""生成 M0-04 / M0-05 的测试工程（.svp）和它的「标准答案」（spec.json）。

结构模板：v1-archive 标签里那个 SynthV 亲手存的零音符工程（version 196，和 2.2.1 一致）。
           它不是代码，是 SynthV 写出来的格式样本。直接从 git 历史里取，不复制进仓库。
声库：    从你最近的 SynthV 恢复文件里拷声库引用（模板没挂声库，导出来会是静音）。
音符字段：照 SynthV 自己存的 366 个音符的默认值填（musicalType / accent / attributes / takes 全一致）。

内容是一份已知的乐谱：97.5 BPM（带小数）· 4/4 · 8 个音 · 中文歌词。
导出设置预先填好（renderConfig）：输出到 out/render，文件名 m0_04。

SynthV 打开它之后，用 SVAgentDump.lua 把 SynthV 眼里的工程写成 JSON，
再用 compare.py 和 spec.json 逐项核对。

用法：python make_test_svp.py
"""
from __future__ import annotations

import copy
import glob
import json
import os
import subprocess
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
RECOVERY = os.path.join(os.environ["APPDATA"], "Dreamtonics", "Synthesizer V Studio 2", "recovery")

QUARTER = 705_600_000   # SynthV 的时间单位 blick：1 个四分音符
BPM = 97.5
NOTES = [  # (起拍, 时值拍, MIDI 音高, 歌词) —— 3 小节
    (0, 1, 60, "今"), (1, 1, 62, "天"), (2, 1.5, 64, "的"), (3.5, 0.5, 65, "风"),
    (4, 2, 67, "很"), (6, 1, 65, "温"), (7, 1, 64, "柔"), (8, 4, 62, "啊"),
]
DEFAULT_TAKES = {"activeTakeId": 0,
                 "takes": [{"id": 0, "liked": False, "seedDuration": 0, "seedPitch": 0, "seedTimbre": 0}]}


def load_svp(raw: bytes):
    return json.loads(raw.rstrip(b"\x00").decode("utf-8"))


def template():
    raw = subprocess.run(["git", "-C", REPO, "show", "v1-archive:songs/_template/empty_v196.svp"],
                         capture_output=True, check=True).stdout
    return load_svp(raw)


def voice_database():
    """最近的恢复文件里，第一条挂了声库、且有音符的人声轨 → (声库引用, 来自哪个文件)。"""
    files = sorted(glob.glob(os.path.join(RECOVERY, "**", "*.svp"), recursive=True),
                   key=os.path.getmtime, reverse=True)
    for p in files:
        d = load_svp(open(p, "rb").read())
        for tr in d["tracks"]:
            ref = tr["mainRef"]
            if ref.get("database", {}).get("name") and not ref["isInstrumental"] and tr["mainGroup"]["notes"]:
                return copy.deepcopy(ref["database"]), p
    raise LookupError("恢复文件里找不到挂了声库的人声轨")


def note(onset, duration, pitch, lyric):
    return {"uuid": str(uuid.uuid4()), "musicalType": "singing", "onset": onset, "duration": duration,
            "lyrics": lyric, "phonemes": "", "accent": "", "pitch": pitch, "detune": 0,
            "attributes": {"evenSyllableDuration": True, "muted": False},
            "takes": copy.deepcopy(DEFAULT_TAKES)}


def build(name, render_dir, database):
    d = template()
    d["uuid"] = str(uuid.uuid4())
    d["time"]["tempo"] = [{"position": 0, "bpm": BPM}]
    d["time"]["meter"] = [{"index": 0, "numerator": 4, "denominator": 4}]
    tr = d["tracks"][0]
    tr["name"] = "M0 测试"
    tr["mainRef"]["database"] = database
    tr["mainGroup"]["notes"] = [note(round(t * QUARTER), round(dur * QUARTER), p, ly) for t, dur, p, ly in NOTES]
    d["renderConfig"].update(destination=render_dir, filename=name)
    return d


def main():
    render_dir = os.path.join(OUT, "render")
    os.makedirs(render_dir, exist_ok=True)
    database, source = voice_database()
    spec = {
        "bpm": BPM, "meter": [4, 4],
        "notes": [{"onset": round(t * QUARTER), "duration": round(d * QUARTER), "pitch": p, "lyrics": ly}
                  for t, d, p, ly in NOTES],
        "render": {"destination": render_dir, "filename": "m0_04"},
        "expected_seconds": 12 * 60 / BPM,   # 3 小节 = 12 拍
        "voice": database.get("name"),
    }
    for name in ("m0_04", "m0_05"):
        path = os.path.join(OUT, f"{name}.svp")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(build(name, render_dir, database), f, ensure_ascii=False)
        print(f"写出 {path}")
    with open(os.path.join(OUT, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    print(f"标准答案 {os.path.join(OUT, 'spec.json')}")
    print(f"声库 {database.get('name')}（取自 {os.path.basename(source)}）")
    print(f"音乐长度 {spec['expected_seconds']:.3f} 秒 = 12 拍 @ {BPM} BPM")


if __name__ == "__main__":
    main()
