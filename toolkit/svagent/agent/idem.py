# -*- coding: utf-8 -*-
"""建造顺序第 2 项：**幂等性**的度量工具。

## 幂等要测什么

    同一个动作连跑两次，产物的**语义**必须相同。

不是字节相同 —— `.svp` 每次写出都会重新生成一批 uuid（`svp_build._fresh()`
的设计），所以逐字节比对永远不等，比了等于没比。

## 所以要先归一化

归一化 = 把「同一件作品的两种等价写法」映射到同一个东西：

    uuid / groupID     丢掉，但**保留引用结构**（轨 → 它实际用的音符）
    音符               按 onset 排序后逐字段取值
    调教参数           按位置排序的 (位置, 值) 列表
    mixer / fxParams   原样保留
    音频轨的 filename  取文件名，不取绝对路径

丢 uuid 的时候必须先把引用解开，否则「轨 A 用了哪组音符」这个信息会一起丢掉 ——
那样两个完全不同的工程会归一化成同一个结果，测试就变成永远通过的空壳。

## 为什么这一项排在第 2

因为它是**第一个会自动告诉我「你弄坏了什么」的东西**。在它之前，
每一次改动的正确性都靠人跑一遍看输出，而这个项目里
「跑通了但结果是错的」出现过至少四次。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

QUARTER_BLICKS = 705600000

# 音符里真正决定「这是什么音」的字段。其余（uuid、显示相关）一律不看。
NOTE_KEYS = ("onset", "duration", "pitch", "lyrics", "phonemes")


def _points(d: dict) -> list:
    """参数曲线 → 排序后的 (位置, 值) 对。**平铺的列表要先两两配对。**"""
    pts = d.get("points") or []
    pairs = [(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
    return sorted(pairs)


def _params(g: dict) -> dict:
    out = {}
    for bag in ("parameters", "vocalModes"):
        for name, v in (g.get(bag) or {}).items():
            if not isinstance(v, dict):
                continue
            pts = _points(v)
            if pts:
                out[f"{bag}.{name}"] = {"mode": v.get("mode"), "points": pts}
    return out


def normalize_svp(path: Path) -> dict:
    """`.svp` → 只含语义的字典。uuid 已解引用后丢弃。"""
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    lib = {g.get("uuid"): g for g in (d.get("library") or [])}

    tracks = []
    for t in (d.get("tracks") or []):
        main = t.get("mainRef") or {}
        audio = main.get("audio") or {}
        notes, params = [], {}
        for ref in (t.get("groups") or []):
            g = lib.get(ref.get("groupID")) or {}
            for n in (g.get("notes") or []):
                notes.append({k: n.get(k) for k in NOTE_KEYS})
            params.update(_params(g))
            # 内联组（音符直接挂在 ref 上而不是 library 里）也要收
            for n in ((ref.get("notes")) or []):
                notes.append({k: n.get(k) for k in NOTE_KEYS})
        tracks.append({
            "name": t.get("name"),
            "instrumental": bool(main.get("isInstrumental")),
            "database": (main.get("database") or {}).get("name"),
            "audio": Path(audio["filename"]).name if audio.get("filename")
                     else None,
            "notes": sorted(notes, key=lambda n: (n["onset"], n["pitch"])),
            "params": params,
            "mixer": t.get("mixer"),
        })
    return {"tempo": d.get("time", {}).get("tempo"),
            "tracks": sorted(tracks, key=lambda t: t["name"] or "")}


def normalize_mid(path: Path) -> dict:
    """`.mid` → 每条轨的事件序列。绝对时刻，不看 delta 的分布方式。"""
    import mido
    mf = mido.MidiFile(str(path))
    tracks = []
    for tr in mf.tracks:
        t, evs, name = 0, [], ""
        for msg in tr:
            t += msg.time
            if msg.type == "track_name":
                name = msg.name
            elif msg.type in ("note_on", "note_off"):
                evs.append((t, msg.type, msg.note, msg.velocity, msg.channel))
            elif msg.type == "set_tempo":
                evs.append((t, "tempo", msg.tempo, 0, 0))
        tracks.append({"name": name, "events": sorted(evs)})
    return {"ticks_per_beat": mf.ticks_per_beat,
            "tracks": sorted(tracks, key=lambda x: x["name"])}


def normalize(path: Path):
    """按后缀分派。不认识的类型退回内容哈希。"""
    path = Path(path)
    if not path.exists():
        return None
    if path.suffix.lower() == ".svp":
        return normalize_svp(path)
    if path.suffix.lower() in (".mid", ".midi"):
        return normalize_mid(path)
    return hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()


def semantic_digest(path: Path) -> str | None:
    """归一化之后的稳定哈希。两次运行相等 = 语义相同。"""
    n = normalize(path)
    if n is None:
        return None
    blob = json.dumps(n, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.blake2b(blob.encode(), digest_size=16).hexdigest()


def content_stats(path: Path) -> dict:
    """产物里有多少**实质内容**。用来防止幂等测试空洞地通过。

    两次都产出空文件，比较起来也是「相等」—— 一个只会比较空产物的测试，
    和只报 0 的检查是同一类东西（`specs/testing-and-acceptance.md` §2）。
    所以每个动作都要声明「我至少该产出什么」，并断言它大于零。
    """
    path = Path(path)
    if not path.exists():
        return {}
    if path.suffix.lower() == ".svp":
        n = normalize_svp(path)
        return {
            "notes": sum(len(t["notes"]) for t in n["tracks"]),
            "tuning_points": sum(len(v["points"]) for t in n["tracks"]
                                 for v in t["params"].values()),
            "audio_tracks": sum(1 for t in n["tracks"] if t["audio"]),
            "fx_tracks": sum(
                1 for t in n["tracks"]
                if any(((t["mixer"] or {}).get("fxParams") or {})
                       .get(k, {}).get("enabled")
                       for k in ("postRoomEq", "compressor", "reverb"))),
        }
    if path.suffix.lower() in (".mid", ".midi"):
        n = normalize_mid(path)
        return {"midi_events": sum(len(t["events"]) for t in n["tracks"]),
                "midi_tracks": len(n["tracks"])}
    return {"bytes": path.stat().st_size}


# 幂等测试的结果落在这里，仪表盘的动作表读它。
# **不是真相来源** —— 它记的是「上次测的时候是什么结果」，所以必须带时间戳，
# 让过期的结论一眼能看出来是过期的。
REPORT_PATH = Path(__file__).resolve().parents[3] / ".agent" / "idempotence.json"


def load_report(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or REPORT_PATH).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_result(script: str, desc: str, ok: bool, stats: dict,
                detail: str = "", path: Path | None = None) -> None:
    import time
    p = Path(path or REPORT_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = load_report(p)
    d[script] = {"desc": desc, "ok": ok, "ts": time.time(),
                 "stats": stats, "detail": detail}
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def code_mtime() -> float:
    """步骤脚本与库的最新改动时间。"""
    root = Path(__file__).resolve().parents[3]
    best = 0.0
    for pat in ("scripts/*.py", "toolkit/svagent/**/*.py"):
        for f in root.glob(pat):
            best = max(best, f.stat().st_mtime)
    return best


def report_is_stale(report: dict | None = None) -> bool | None:
    """报告是不是在代码改动**之前**测出来的。→ None 表示还没测过。

    这条比表上那些 ✓ 本身更重要。一张「上次测是全绿」的表，
    在代码改过之后仍然显示全绿，就是又一个安静地说假话的显示层 ——
    而这正是仪表盘存在的理由。
    """
    report = load_report() if report is None else report
    if not report:
        return None
    return min(v["ts"] for v in report.values()) < code_mtime()


def diff_svp(a: Path, b: Path) -> list[str]:
    """两个工程语义上差在哪。**失败时要说清楚差在哪，不能只说不等。**"""
    na, nb = normalize_svp(a), normalize_svp(b)
    out: list[str] = []
    if na["tempo"] != nb["tempo"]:
        out.append(f"tempo {na['tempo']} → {nb['tempo']}")
    ta = {t["name"]: t for t in na["tracks"]}
    tb = {t["name"]: t for t in nb["tracks"]}
    for name in sorted(set(ta) | set(tb)):
        x, y = ta.get(name), tb.get(name)
        if x is None or y is None:
            out.append(f"轨「{name}」{'新增' if x is None else '消失'}")
            continue
        if len(x["notes"]) != len(y["notes"]):
            out.append(f"轨「{name}」音符 {len(x['notes'])} → {len(y['notes'])}")
        elif x["notes"] != y["notes"]:
            n_diff = sum(1 for p, q in zip(x["notes"], y["notes"]) if p != q)
            out.append(f"轨「{name}」{n_diff} 个音符内容不同")
        for k in sorted(set(x["params"]) | set(y["params"])):
            pa = x["params"].get(k, {}).get("points", [])
            pb = y["params"].get(k, {}).get("points", [])
            if len(pa) != len(pb):
                out.append(f"轨「{name}」{k} 点数 {len(pa)} → {len(pb)}")
            elif pa != pb:
                out.append(f"轨「{name}」{k} 点数相同但值变了")
        if x["mixer"] != y["mixer"]:
            out.append(f"轨「{name}」mixer 不同")
        if x["audio"] != y["audio"]:
            out.append(f"轨「{name}」音频 {x['audio']} → {y['audio']}")
    return out
