"""直接生成 SynthV 工程文件（`.svp`）。见 [ADR-0009](../../specs/adr/0009-write-svp-directly.md)。

## 为什么直写文件

`.svp` 是纯 JSON。直写它一次性消除 SynthV 侧全部 4 项手动：
新建工程、指派声库、加音频轨、保存 —— 因为写文件本身就是新建 + 保存，
而声库和音频轨都是文件里的字段。

成品从「一个需要六步手工装配的 DAW 状态」变成「一个双击就能听的文件」。

## Schema（2026-08-23 从 14 个真实 .svp 逐字段取证，version 187）

    顶层        {version, time, library, tracks, renderConfig}
    time        {meter:[{index,numerator,denominator}],
                 tempo:[{position,bpm}], startTimeSeconds}
    library[i]  {uuid, name, notes[], parameters{9 条}, pitchControls[], vocalModes{}}
    tracks[i]   {name, dispColor, dispOrder, groups[], mainGroup,
                 mainRef, mixer, renderEnabled}

**音符在 `library[i].notes`，不在 track 上。** track 通过
`groups[j].groupID → library[i].uuid` 引用它。这与桥的语义一致
（桥的 contextId 也是组作用域的，不是顶层）。

**声库在组引用上**：`tracks[i].groups[j].database.name`，实测值
`"MEDIUM5·Stardust"` = 星尘。不是在 `mainRef.database` 上（那里是空串）。

**音频轨** = `mainRef.isInstrumental=true` + `mainRef.audio`，且 `groups` 为空。
`beatLocations` **单位是秒**，间距 60/bpm。

## 边界

直写解决**装配**，不解决**编辑**。调教（转音、参数曲线）、读取 SynthV 实际
状态、回读校验，仍然只能走桥（`bridge.py`）。
"""
from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

QUARTER_BLICKS = 705600000

# 星尘。取自真实工程，逐字段照抄 —— 不猜。
VOICE_STARDUST = {
    "name": "MEDIUM5·Stardust",
    "language": "mandarin",
    "phoneset": "xsampa",
    "languageOverride": "",
    "phonesetOverride": "",
    "backendType": "SVR3",
    "version": "110",
}

# 每个音符和每个组引用都带一份 takes。照抄真实工程的默认值。
_TAKES = {"activeTakeId": 0,
          "takes": [{"id": 0, "seedDuration": 0, "seedPitch": 0,
                     "seedTimbre": 0, "liked": False}]}

_PARAM_NAMES = ("pitchDelta", "vibratoEnv", "loudness", "tension",
                "breathiness", "voicing", "gender", "toneShift",
                "mouthOpening")

# 轨道颜色。ARGB 十六进制字符串，取自真实工程。
COLOR_VOCAL = "ff7db235"
COLOR_AUDIO = "ff4794cb"


def _empty_params() -> dict:
    return {n: {"mode": "cubic", "points": []} for n in _PARAM_NAMES}


def _new_group(name: str, notes: list[dict]) -> dict:
    return {"name": name, "uuid": str(_uuid.uuid4()),
            "parameters": _empty_params(), "vocalModes": {},
            "pitchControls": [], "notes": notes}


def _group_ref(group_id: str, *, database: dict | None = None,
               blick_offset: int = 0, instrumental: bool = False) -> dict:
    """组引用。声库挂在这一层 —— 不是 mainRef.database。"""
    return {
        "groupID": group_id,
        "blickAbsoluteBegin": 0,
        "blickAbsoluteEnd": -1,
        "blickOffset": blick_offset,
        "pitchOffset": 0,
        "mute": False,
        "isInstrumental": instrumental,
        "database": dict(database or VOICE_STARDUST),
        "dictionary": "",
        "voice": {"vocalModeInherited": True, "vocalModePreset": "",
                  "vocalModeParams": {}},
        "voicePresetName": "",
        "takes": json.loads(json.dumps(_TAKES)),
    }


def note(onset_beats: float, duration_beats: float, midi: int,
         lyric: str) -> dict:
    """一个演唱音符。blicks = 拍 × 705600000。"""
    on = int(round(onset_beats * QUARTER_BLICKS))
    off = int(round((onset_beats + duration_beats) * QUARTER_BLICKS))
    return {
        "musicalType": "singing",
        "onset": on,
        "duration": max(1, off - on),
        "lyrics": lyric,
        "phonemes": "",
        "accent": "",
        "pitch": int(midi),
        "detune": 0,
        "attributes": {"evenSyllableDuration": True, "muted": False},
        "takes": json.loads(json.dumps(_TAKES)),
    }


@dataclass
class AudioTrack:
    """伴奏音频轨。SynthV 里 isInstrumental=true 的轨。"""
    filename: str          # 写进工程的路径（相对或绝对，SynthV 都认）
    duration_s: float
    bpm: float

    def to_ref(self) -> dict:
        ref = _group_ref(str(_uuid.uuid4()), instrumental=True)
        ref["database"] = {"name": "", "language": "", "phoneset": "",
                           "languageOverride": "", "phonesetOverride": "",
                           "backendType": "", "version": "-2"}
        spb = 60.0 / self.bpm
        n_beats = int(self.duration_s / spb) + 1
        ref["audio"] = {
            "filename": self.filename,
            "duration": self.duration_s,
            "bpm": self.bpm,
            "alternativeBPMs": [self.bpm],
            # 单位是秒，不是 blicks。我们的伴奏从 0 开始且 tempo 恒定，
            # 所以是等间距 —— 不需要像 SynthV 那样去检测。
            "beatLocations": [round(k * spb, 9) for k in range(n_beats)],
        }
        return ref


def build_project(*, bpm: float, notes: Iterable[dict],
                  vocal_track_name: str = "人声",
                  group_name: str = "main",
                  voice: dict | None = None,
                  audio: AudioTrack | None = None,
                  audio_track_name: str = "伴奏",
                  numerator: int = 4, denominator: int = 4) -> dict:
    """组装一个完整工程。"""
    notes = list(notes)
    grp = _new_group(group_name, notes)
    tracks: list[dict] = [{
        "name": vocal_track_name,
        "dispColor": COLOR_VOCAL,
        "dispOrder": 0,
        "groups": [_group_ref(grp["uuid"], database=voice)],
        # mainGroup 留空：音符走 library + groups 引用那条路，
        # 与真实工程一致（实测真实工程的 mainGroup.notes 都是 0）
        "mainGroup": _new_group("main", []),
        "mainRef": _group_ref("", database={
            "name": "", "language": "", "phoneset": "",
            "languageOverride": "", "phonesetOverride": "",
            "backendType": "", "version": "-2"}),
        "mixer": {"gainDecibel": 0.0, "pan": 0.0, "mute": False,
                  "solo": False, "display": True},
        "renderEnabled": True,
    }]
    tracks[0]["mainRef"]["groupID"] = tracks[0]["mainGroup"]["uuid"]

    if audio is not None:
        at = {
            "name": audio_track_name,
            "dispColor": COLOR_AUDIO,
            "dispOrder": 1,
            "groups": [],
            "mainGroup": _new_group("main", []),
            "mainRef": audio.to_ref(),
            "mixer": {"gainDecibel": 0.0, "pan": 0.0, "mute": False,
                      "solo": False, "display": True},
            # 音频轨不需要渲染人声，真实工程里这一项是 false
            "renderEnabled": False,
        }
        at["mainRef"]["groupID"] = at["mainGroup"]["uuid"]
        tracks.append(at)

    return {
        "version": 187,
        "time": {
            "meter": [{"index": 0, "numerator": numerator,
                       "denominator": denominator}],
            "tempo": [{"position": 0, "bpm": float(bpm)}],
            "startTimeSeconds": 0.0,
        },
        "library": [grp],
        "tracks": tracks,
        "renderConfig": {"destination": ".", "filename": "untitled",
                         "numChannels": 1, "aspirationFormat": "noAspiration",
                         "bitDepth": 16, "sampleRate": 44100,
                         "exportMixDown": False, "exportPitch": False},
    }


def save(project: dict, path: Path, *, force: bool = False) -> Path:
    """写文件。**已存在就拒绝** —— 这是用户的工程，不能默认覆盖。"""
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"{path} 已存在。确认要覆盖再加 force=True")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    return path


def read_notes(path: Path) -> list[dict]:
    """回读 library 里的全部音符，用于逐字段比对。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [n for g in d.get("library", []) for n in (g.get("notes") or [])]


def diff_notes(written: list[dict], expected: list[Any]) -> list[str]:
    """写出的音符 vs 源模块的 Note。返回不一致的描述列表。"""
    out: list[str] = []
    if len(written) != len(expected):
        out.append(f"数量 {len(written)} != {len(expected)}")
    for i, (w, e) in enumerate(zip(written, expected)):
        on = int(round(e.onset_beats * QUARTER_BLICKS))
        dur = max(1, int(round((e.onset_beats + e.duration_beats)
                               * QUARTER_BLICKS)) - on)
        if w["onset"] != on:
            out.append(f"[{i}] onset {w['onset']} != {on}")
        if w["duration"] != dur:
            out.append(f"[{i}] duration {w['duration']} != {dur}")
        if int(w["pitch"]) != int(e.midi):
            out.append(f"[{i}] pitch {w['pitch']} != {e.midi}")
        if str(w["lyrics"]) != str(e.lyric):
            out.append(f"[{i}] lyrics {w['lyrics']!r} != {e.lyric!r}")
    return out
