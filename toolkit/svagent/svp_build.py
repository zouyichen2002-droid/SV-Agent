"""以创作者的空工程为**模板**装配 `.svp`，不再按反推的 schema 构造。

## 为什么改成模板驱动

`svp.py` 的 schema 是从 14 个别人的 `.svp`（`version 187`）反推的。
2026-08-23 读创作者自己新建的空工程，发现它是 **`version 196`**，
并且有六处我完全没有的字段：

    顶层            projectMixer · uuid
    mainGroup       musicalScale {type, root}
    mainRef         timestampLMR · timestampLRSR · uuid
    mainRef.voice   choirSeatingSeparation
    mixer           fxPresetName · fxParams（room / postRoomEq / compressor / reverb）

上一首歌写的 187 文件能打开，**那是运气，不是正确**。

工作流步骤 1 要求创作者「新建一个空 SV 工程并保存」，
这个文件的价值就在这里：它来自**他自己的 SynthV 版本**，
拿它当模板，未来任何版本升级加的字段都自动带上，不必再反推一次。

**原则：只注入我确实需要改的字段，其余一律深拷贝模板。**

## uuid 必须重新生成

模板里的 uuid 是那一个空轨的。复制出多条轨时若不换 uuid，
组引用会全部指向同一个组 —— 12 条轨会显示成同一段音符。
所以 `_fresh()` 递归替换所有 uuid 型字段。
"""
from __future__ import annotations

import copy
import json
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path

QUARTER_BLICKS = 705600000

# 星尘。取自真实工程，逐字段照抄 —— 不猜。
VOICE_STARDUST = {
    "name": "MEDIUM5·Stardust", "language": "mandarin", "phoneset": "xsampa",
    "languageOverride": "", "phonesetOverride": "", "backendType": "SVR3",
    "version": "110",
}
EMPTY_DB = {"name": "", "language": "", "phoneset": "", "languageOverride": "",
            "phonesetOverride": "", "backendType": "", "version": "-2"}

# 轨道颜色，够 12 条轨各不相同
COLORS = ("ff7db235", "ff4794cb", "ffcb5647", "ffb0a04b", "ff8a6fbf",
          "ff4aa88a", "ffc27ba0", "ff6f8fbf", "ffbf8f6f", "ff8fbf6f",
          "ffbf6f8f", "ff6fbfbf")

_UUID_KEYS = ("uuid", "groupID")


def new_uuid() -> str:
    return str(_uuid.uuid4())


def _fresh(obj, remap: dict[str, str] | None = None):
    """深拷贝并给所有 uuid 型字段换新值。同一个旧 uuid 映射到同一个新 uuid，
    这样 mainRef.groupID → mainGroup.uuid 的对应关系不会断。"""
    remap = {} if remap is None else remap
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _UUID_KEYS and isinstance(v, str) and v:
                out[k] = remap.setdefault(v, new_uuid())
            else:
                out[k] = _fresh(v, remap)
        return out
    if isinstance(obj, list):
        return [_fresh(x, remap) for x in obj]
    return obj


def load_template(path: Path | str) -> dict:
    """读创作者的空工程。必须只有一条空轨 —— 有音符就说明拿错了文件。"""
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    n_notes = sum(len(g.get("notes") or []) for g in (d.get("library") or []))
    n_notes += sum(len((t.get("mainGroup") or {}).get("notes") or [])
                   for t in d.get("tracks", []))
    if n_notes:
        raise ValueError(f"{path} 里已经有 {n_notes} 个音符，不是空工程模板")
    if not d.get("tracks"):
        raise ValueError(f"{path} 一条轨都没有，无法当模板")
    return d


def note(onset_beats: float, duration_beats: float, midi: int,
         lyric: str) -> dict:
    on = int(round(onset_beats * QUARTER_BLICKS))
    off = int(round((onset_beats + duration_beats) * QUARTER_BLICKS))
    return {
        "musicalType": "singing", "onset": on, "duration": max(1, off - on),
        "lyrics": lyric, "phonemes": "", "accent": "", "pitch": int(midi),
        "detune": 0,
        "attributes": {"evenSyllableDuration": True, "muted": False},
        "takes": {"activeTakeId": 0,
                  "takes": [{"id": 0, "seedDuration": 0, "seedPitch": 0,
                             "seedTimbre": 0, "liked": False}]},
    }


@dataclass
class AudioTrack:
    filename: str
    duration_s: float
    bpm: float


class Builder:
    """把轨道注入模板。每次 `add_*` 复制一份模板轨，只改需要改的字段。"""

    def __init__(self, template: dict, *, bpm: float,
                 numerator: int = 4, denominator: int = 4):
        self.proj = _fresh(copy.deepcopy(template))
        self._proto = copy.deepcopy(self.proj["tracks"][0])
        self.proj["tracks"] = []
        self.proj["library"] = []
        self.proj["time"] = {
            "meter": [{"index": 0, "numerator": numerator,
                       "denominator": denominator}],
            "tempo": [{"position": 0, "bpm": float(bpm)}],
            "startTimeSeconds": 0.0,
        }

    def _new_track(self, name: str) -> dict:
        t = _fresh(copy.deepcopy(self._proto))
        t["name"] = name
        t["dispOrder"] = len(self.proj["tracks"])
        t["dispColor"] = COLORS[len(self.proj["tracks"]) % len(COLORS)]
        return t

    def add_vocal(self, name: str, notes: list[dict], *,
                  voice: dict | None = None, mute: bool = False,
                  gain_db: float = 0.0,
                  parameters: dict | None = None,
                  vocal_modes: dict | None = None) -> dict:
        """人声轨：音符进 library 的组，轨上用 groups[] 引用它，声库挂在引用上。"""
        t = self._new_track(name)
        gid = new_uuid()
        # 组的骨架照抄模板的 mainGroup —— parameters / musicalScale 等都带上
        grp = _fresh(copy.deepcopy(self._proto["mainGroup"]))
        grp["uuid"] = gid
        grp["name"] = name
        grp["notes"] = notes
        # 调教：往组的 parameters / vocalModes 里写自动化点。
        # 只覆盖给出的键，其余保持模板里的空值 —— 见 compose/tuning.py
        if parameters:
            grp.setdefault("parameters", {}).update(
                {k: dict(v) for k, v in parameters.items()})
        if vocal_modes:
            grp["vocalModes"] = {k: dict(v) for k, v in vocal_modes.items()}
        self.proj["library"].append(grp)
        # 声库要挂**两处**：
        #   groups[].database  —— 这个组实际用哪个声库
        #   mainRef.database   —— 轨道的「默认歌声」，SynthV 界面显示的就是它
        # 只挂前者时，音符能唱，但界面上写「未设置默认歌声」（实测截图证实）。
        db = dict(voice or VOICE_STARDUST)
        t["mainRef"]["database"] = dict(db)
        # 组引用照抄 mainRef 的形状，改 groupID 与 database
        ref = _fresh(copy.deepcopy(self._proto["mainRef"]))
        ref["groupID"] = gid
        ref["database"] = dict(db)
        ref["isInstrumental"] = False
        t["groups"] = [ref]
        t["renderEnabled"] = True
        t["mixer"] = dict(t["mixer"], mute=bool(mute), gainDecibel=gain_db)
        self.proj["tracks"].append(t)
        return t

    def add_audio(self, name: str, audio: AudioTrack, *,
                  mute: bool = False, gain_db: float = 0.0) -> dict:
        """伴奏/和声垫音频轨：isInstrumental=true + mainRef.audio。"""
        t = self._new_track(name)
        mr = t["mainRef"]
        mr["isInstrumental"] = True
        mr["database"] = dict(EMPTY_DB)
        spb = 60.0 / audio.bpm
        n_beats = int(audio.duration_s / spb) + 1
        mr["audio"] = {
            "filename": audio.filename,
            "duration": audio.duration_s,
            "bpm": audio.bpm,
            "alternativeBPMs": [audio.bpm],
            # 单位是秒。我们的音频从 0 起、tempo 恒定，所以等间距
            "beatLocations": [round(k * spb, 9) for k in range(n_beats)],
        }
        t["groups"] = []
        t["renderEnabled"] = False
        t["mixer"] = dict(t["mixer"], mute=bool(mute), gainDecibel=gain_db)
        self.proj["tracks"].append(t)
        return t

    def save(self, path: Path | str, *, force: bool = False) -> Path:
        """写文件。已存在就拒绝 —— 那是创作者的工程。"""
        path = Path(path)
        if path.exists() and not force:
            raise FileExistsError(f"{path} 已存在。确认要覆盖再加 force=True")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.proj, ensure_ascii=False),
                        encoding="utf-8")
        return path


def read_back(path: Path | str) -> dict:
    """回读：{轨名: 音符列表}，用于逐字段比对。"""
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    lib = {g["uuid"]: g for g in d.get("library", [])}
    out = {}
    for t in d.get("tracks", []):
        ns = []
        for ref in (t.get("groups") or []):
            ns += (lib.get(ref.get("groupID")) or {}).get("notes") or []
        out[t["name"]] = ns
    return out
