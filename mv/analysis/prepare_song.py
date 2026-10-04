# -*- coding: utf-8 -*-
r"""给代码画的 MV 准备一首歌的数据（SV-Agent 10-03）。写到这首歌项目里的 MV\ 文件夹（仓库外：第三方的歌和歌词不进仓库）：

    audio.wav       成品混音（创作者从 SV 导出的那份，拷一份）
    逐字时间.json    worker/lyric_timing.py 从 SV 工程算的（和歌词视频同一套：工程里每个音的起止 → 歌词每个字）
    lyrics.json     引擎要的格式：lines[{text, start, end, words[{w, start, end}]}]（中文一个字一个单位）
    audio.json      引擎要的格式：duration、bpm、fps(100)、beats、downbeats、sections、features、onsets
    准备.json        用了哪些文件、对齐结果、各项统计（不写歌词原文）

数据从哪来：
    拍子、强拍   项目的 拍子\tempo_map.json（找拍子的结果；每个速度段从第一个「1」起每 60/bpm 秒一拍、4 拍一小节）
    对齐        成品混音和分离出来的伴奏比（worker/audio_offset.py，歌词视频同一个）；可信又差 0.02 秒以上就把歌词时间平移
    各声部响度   rms / low / mid / high 从成品混音算；vocal 从分离出来的主唱算（原唱的，和 SV 唱的同一条旋律、同样的时间）；
                drums / bass / other 从分离出来的伴奏拆打击和和声部分算（翻唱用的就是原曲伴奏）
    鼓点        伴奏的打击部分按频段找起音：kick 40–150 Hz、snare 1–5 kHz、hat 7–11.5 kHz；vocal = 每个字开始唱的时间
    段落        先按歌词分块（两句之间空 2 小节以上就断开），段落边界吸到强拍；正式的段落在定概念那天和创作者一起定

用法（miniconda 的 Python，要 librosa）：
    python prepare_song.py --project <项目文件夹> --svp <和混音对应的那份 .svp> --mix <成品混音.wav>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

import librosa
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
WORKER = HERE.parent.parent / "worker"
sys.path.insert(0, str(WORKER))
import audio_offset as O  # noqa: E402

SR, HOP = 24000, 240          # 100 帧 / 秒
FPS = SR // HOP
SHIFT_MIN = 0.02              # 对齐差这么多以上才平移歌词时间（和歌词视频一样）
GAP_BARS = 2                  # 两句之间空这么多小节以上，算新的一块


def low_priority() -> None:
    """低于正常（在创作者的电脑上跑重活的规矩）；之后起的子进程（vocal2midi、ffmpeg）跟着低。"""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE      # 不设 restype，64 位上伪句柄会被截断、静默失败
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.SetPriorityClass.restype = wintypes.BOOL
    k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS


def norm(x: np.ndarray, q: float = 99.5, gamma: float = 0.6) -> np.ndarray:
    """0..1 的包络：按高分位数归一、截到 1、稍微压一下（听感上小声的地方也看得见）。"""
    p = float(np.percentile(x, q)) or 1.0
    return np.clip(x / p, 0.0, 1.0) ** gamma


def fit(x: np.ndarray, n: int) -> np.ndarray:
    return x[:n] if len(x) >= n else np.pad(x, (0, n - len(x)))


def band(S: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> np.ndarray:
    m = (freqs >= lo) & (freqs < hi)
    return np.sqrt((S[m] ** 2).sum(axis=0))


def onsets(S: np.ndarray, freqs: np.ndarray, lo: float, hi: float, wait_s: float, k: float) -> list[list[float]]:
    """某个频段的起音：对数幅度的正向变化（谱通量）找峰；强度按峰高归一到 0..1。"""
    m = (freqs >= lo) & (freqs < hi)
    L = np.log1p(S[m] * 100.0)
    flux = np.maximum(0.0, np.diff(L, axis=1)).sum(axis=0)
    flux = np.concatenate([[0.0], flux])
    p99 = float(np.percentile(flux, 99)) or 1.0
    peaks = librosa.util.peak_pick(flux, pre_max=3, post_max=3, pre_avg=10, post_avg=10, delta=k * p99, wait=int(wait_s * FPS))
    return [[round(i / FPS, 3), round(min(1.0, float(flux[i]) / p99), 3)] for i in peaks]


def beat_grid(tm: dict, duration: float) -> tuple[float, list[float], list[float]]:
    beats: list[float] = []
    downs: list[float] = []
    bpm = 0.0
    for s in tm["sections"]:
        bpm = float(s["bpm"])
        per = 60.0 / bpm
        t0 = float(s["start_s"])
        lo, hi = float(s["from_s"]), min(float(s["to_s"]), duration)
        k = int(np.ceil((lo - t0) / per - 1e-9))
        while True:
            t = t0 + k * per
            if t >= hi:
                break
            if t >= 0:
                beats.append(round(t, 4))
                if k % 4 == 0:
                    downs.append(round(t, 4))
            k += 1
    return round(bpm, 3), beats, downs


def sections(lines: list[dict], downs: list[float], duration: float, bar_s: float) -> list[dict]:
    """先分个大概，给占位场景换段用（正式段落定概念那天和创作者一起定）。在句首切：
    两句之间空了 ≥ GAP_BARS 小节；重复出现的一组句子（第二次起）的第一句；一块超过 16 小节，就大约每 8 小节在句首再切一刀。
    切点吸到那句第一个字之前最近的强拍。"""
    if not lines or not downs:
        return [{"name": "全曲", "start": 0.0, "end": round(duration, 3)}]
    starts = {0}
    first_seen: dict[str, int] = {}
    for i, l in enumerate(lines):
        if i and l["start"] - lines[i - 1]["end"] >= GAP_BARS * bar_s:
            starts.add(i)
        j = first_seen.get(l["text"])
        prev_repeats = i > 0 and first_seen.get(lines[i - 1]["text"], i - 1) < i - 1
        if j is not None and i - j >= 4 and not prev_repeats:
            starts.add(i)
        first_seen.setdefault(l["text"], i)
    idx = sorted(starts) + [len(lines)]
    cut_lines = []
    for a, b in zip(idx, idx[1:]):
        cut_lines.append(a)
        if lines[b - 1]["end"] - lines[a]["start"] <= 16 * bar_s:
            continue
        target = lines[a]["start"] + 8 * bar_s
        for j in range(a + 1, b):
            if lines[j]["start"] >= target and lines[b - 1]["end"] - lines[j]["start"] >= 4 * bar_s:
                cut_lines.append(j)
                target = lines[j]["start"] + 8 * bar_s
    down_before = lambda t: max([d for d in downs if d <= t + 0.02], default=0.0)
    down_after = lambda t: min([d for d in downs if d >= t - 0.02], default=duration)
    cuts = sorted({round(down_before(lines[i]["start"]), 3) for i in cut_lines})
    out = []
    if cuts[0] > 0.5:
        out.append({"name": "前奏", "start": 0.0, "end": cuts[0]})
    else:
        cuts[0] = 0.0
    tail = round(down_after(lines[-1]["end"]), 3)
    has_tail = duration - tail > bar_s
    for i, c in enumerate(cuts):
        end = cuts[i + 1] if i + 1 < len(cuts) else (tail if has_tail else round(duration, 3))
        out.append({"name": f"段{i + 1}", "start": c, "end": end})
    if has_tail:
        out.append({"name": "尾奏", "start": tail, "end": round(duration, 3)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="这首歌的项目文件夹（E:\\sv-agent-workspace\\<歌名>）")
    ap.add_argument("--svp", required=True, help="和成品混音对应的那份 SV 工程")
    ap.add_argument("--mix", required=True, help="创作者从 SV 导出的成品混音")
    ap.add_argument("--lyrics", help="默认 <项目>\\素材\\歌词_要唱的字.txt")
    ap.add_argument("--tempo-map", help="默认 <项目>\\拍子\\tempo_map.json")
    ap.add_argument("--vocal", help="默认 <项目>\\分离\\主唱_缺的段用整条人声补.wav")
    ap.add_argument("--accomp", help="默认 <项目>\\分离\\原曲整首_(other)_vocals_mel_band_roformer.wav")
    a = ap.parse_args()
    low_priority()

    proj = pathlib.Path(a.project)
    out = proj / "MV"
    out.mkdir(exist_ok=True)
    cfg = json.loads((WORKER / "cover_config.json").read_text(encoding="utf-8"))
    lyrics_txt = pathlib.Path(a.lyrics or proj / "素材" / "歌词_要唱的字.txt")
    tm_path = pathlib.Path(a.tempo_map or proj / "拍子" / "tempo_map.json")
    vocal = pathlib.Path(a.vocal or proj / "分离" / "主唱_缺的段用整条人声补.wav")
    accomp = pathlib.Path(a.accomp or proj / "分离" / "原曲整首_(other)_vocals_mel_band_roformer.wav")
    for p in (pathlib.Path(a.svp), pathlib.Path(a.mix), lyrics_txt, tm_path, vocal, accomp):
        if not p.exists():
            raise SystemExit(f"找不到：{p}")
    report: dict = {"工程": str(a.svp), "成品混音": str(a.mix), "歌词": str(lyrics_txt), "拍子": str(tm_path),
                    "主唱（原唱分离）": str(vocal), "伴奏（原曲分离）": str(accomp)}

    # 1. 成品混音拷一份
    shutil.copy2(a.mix, out / "audio.wav")

    # 2. 逐字时间（vocal2midi 环境里跑，和歌词视频同一个）
    timing = out / "逐字时间.json"
    r = subprocess.run([cfg["vocal2midi_python"], str(WORKER / "lyric_timing.py"), str(a.svp), str(lyrics_txt), str(timing)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    (out / "逐字时间.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"lyric_timing.py 失败，见 {out / '逐字时间.log'}")
    T = json.loads(timing.read_text(encoding="utf-8"))

    # 3. 对齐：成品混音和原曲伴奏比
    res = O.offset(cfg["ffmpeg"], str(a.mix), str(accomp))
    shift = res["晚秒"] if res["可信"] and abs(res["晚秒"]) >= SHIFT_MIN else 0.0
    report["对齐"] = {k: res[k] for k in ("晚秒", "相关", "次峰", "可信") if k in res} | {"平移秒": shift}

    # 4. lyrics.json：缺时间的单位（歌词里有、音上没有）跟下一个有时间的单位一起亮（时长 0）
    lines = []
    for row in T["行"]:
        units = row["单位"]
        nxt = None
        filled = []
        for u in reversed(units):
            s, e = u.get("开始"), u.get("结束")
            if s is None or e is None:
                s = e = nxt if nxt is not None else row["结束"]
            nxt = s
            filled.append({"w": u["文字"], "start": round(s + shift, 3), "end": round(e + shift, 3)})
        filled.reverse()
        lines.append({"text": row["文字"], "start": round(row["开始"] + shift, 3), "end": round(row["结束"] + shift, 3), "words": filled})
    (out / "lyrics.json").write_text(json.dumps({"lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
    report["歌词"] = {"行": len(lines), "单位": sum(len(l["words"]) for l in lines), "统计": T.get("统计")}

    # 5. 音频分析
    y, _ = librosa.load(a.mix, sr=SR, mono=True)
    n_frames = len(y) // HOP + 1
    duration = round(len(y) / SR, 3)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    lag = int(round(shift * SR))  # 分离出来的轨按原曲的时间：混音晚了 shift 秒，就把分离轨往后挪同样多

    def stem(p: pathlib.Path) -> np.ndarray:
        s, _ = librosa.load(str(p), sr=SR, mono=True)
        s = np.concatenate([np.zeros(lag), s]) if lag > 0 else s[-lag:]
        return fit(s, len(y))

    yv, ya = stem(vocal), stem(accomp)
    Sa = np.abs(librosa.stft(ya, n_fft=2048, hop_length=HOP))
    H, P = librosa.decompose.hpss(Sa)
    feats = {
        "rms": norm(librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]),
        "low": norm(band(S, freqs, 30, 200)),
        "mid": norm(band(S, freqs, 200, 2500)),
        "high": norm(band(S, freqs, 2500, 10000)),
        "vocal": norm(librosa.feature.rms(y=yv, frame_length=2048, hop_length=HOP)[0]),
        "drums": norm(band(P, freqs, 30, 11500)),
        "bass": norm(band(H, freqs, 30, 180)),
        "other": norm(band(H, freqs, 180, 8000)),
    }
    feats = {k: [round(float(v), 3) for v in fit(x, n_frames)] for k, x in feats.items()}
    ons = {
        "kick": onsets(P, freqs, 40, 150, 0.09, 0.35),
        "snare": onsets(P, freqs, 1000, 5000, 0.09, 0.35),
        "hat": onsets(P, freqs, 7000, 11500, 0.05, 0.30),
        "vocal": [[w["start"], 1.0] for l in lines for w in l["words"] if w["end"] > w["start"]],
    }
    tm = json.loads(tm_path.read_text(encoding="utf-8"))
    bpm, beats, downs = beat_grid(tm, duration)
    bar_s = 240.0 / bpm if bpm else 2.0
    secs = sections(lines, downs, duration, bar_s)
    audio = {"duration": duration, "bpm": bpm, "fps": FPS, "beats": beats, "downbeats": downs, "sections": secs,
             "features": feats, "onsets": ons}
    (out / "audio.json").write_text(json.dumps(audio, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    report["音频"] = {"时长秒": duration, "bpm": bpm, "拍": len(beats), "强拍": len(downs),
                    "起音": {k: len(v) for k, v in ons.items()},
                    "段落": [f"{s['name']} {s['start']:.2f}–{s['end']:.2f}" for s in secs]}
    (out / "准备.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("对齐", "音频")}, ensure_ascii=False, indent=1))
    print(f"歌词：{report['歌词']['行']} 行、{report['歌词']['单位']} 个字；写到 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
