# -*- coding: utf-8 -*-
"""M1-01：人声扒谱准不准 —— 把一份扒出来的 .svp 和标准答案（你改完的终稿）逐音对比。

口径（和常见的扒谱评测一致）：
- **扒对一个音** = 起音相差 ≤ 50 ms，且音高相差 ≤ 50 音分（SynthV 的 pitch + detune）
- 另外单独数：只看起音对不对、音高对的比例、八度错误、时值、歌词
- **整体偏移**：音频在 SynthV 里放的位置差一点，全曲会整体错开 —— 先在 ±2 秒内找让起音匹配最多的偏移，再比

自检：标准答案对它自己必须 100%；整体移八度必须全算八度错；删掉 20% 的音召回必须是 80%；
整体挪 0.3 秒必须被偏移找回来；加 20% 的乱音精确率必须掉下来。不过就不比。

    python compare_notes.py <标准答案.svp> <被比的.svp> [<标准答案里的轨名>]
只读输入；报告写在仓库外 E:/sv-agent-data/learn/01-傍晚/。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
Q = 705_600_000
ONSET_TOL, PITCH_TOL = 0.050, 50.0          # 秒 · 音分
OUT = pathlib.Path("E:/sv-agent-data/learn/01-傍晚")


def load_svp(p) -> dict:
    return json.loads(pathlib.Path(p).read_bytes().rstrip(b"\x00").decode("utf-8"))


def blick_to_seconds(b: float, tempo: list[dict]) -> float:
    marks = sorted(tempo, key=lambda x: x["position"])
    s, prev_pos, prev_bpm = 0.0, 0, marks[0]["bpm"]
    for m in marks[1:]:
        if m["position"] >= b:
            break
        s += (m["position"] - prev_pos) / Q * 60 / prev_bpm
        prev_pos, prev_bpm = m["position"], m["bpm"]
    return s + (b - prev_pos) / Q * 60 / prev_bpm


def tracks(d: dict) -> dict[str, list[tuple[float, float, float, str]]]:
    """→ {轨名: [(起音秒, 时值秒, 音高音分, 歌词)]}，读全部音符组（M0-04 的教训）。"""
    lib = {g["uuid"]: g for g in d.get("library", [])}
    out = {}
    for tr in d["tracks"]:
        if tr["mainRef"].get("isInstrumental"):
            continue
        notes = []
        for g, ref in [(tr["mainGroup"], tr["mainRef"])] + [(lib.get(r.get("groupID")), r) for r in tr.get("groups", [])]:
            if not g:
                continue
            off, poff = ref.get("blickOffset", 0), ref.get("pitchOffset", 0)
            for n in g.get("notes", []):
                a = blick_to_seconds(n["onset"] + off, d["time"]["tempo"])
                b = blick_to_seconds(n["onset"] + off + n["duration"], d["time"]["tempo"])
                cents = (n["pitch"] + poff) * 100 + n.get("detune", 0)
                notes.append((a, b - a, cents, n.get("lyrics", "")))
        if notes:
            out[tr.get("name") or f"轨 {len(out) + 1}"] = sorted(notes)
    return out


def _signed_nearest(ref: np.ndarray, est: np.ndarray, o: float) -> np.ndarray:
    """每个答案起音到最近的被比起音（加偏移后）的有符号距离。"""
    idx = np.searchsorted(est + o, ref)
    lo = est[np.clip(idx - 1, 0, len(est) - 1)] + o
    hi = est[np.clip(idx, 0, len(est) - 1)] + o
    return np.where(np.abs(ref - lo) <= np.abs(ref - hi), ref - lo, ref - hi)


def best_offset(ref: np.ndarray, est: np.ndarray) -> float:
    """在 ±2 秒内找让「起音对得上」最多的整体偏移。

    09-28 自检抓到的：对得上的个数在正确偏移附近 ±容差内是一段平台，第一版取了平台最边上的点（差 49 ms）。
    改成：取最长那段平台的中点，再用配对上的起音的有符号残差中位数细调。"""
    grid = np.arange(-2.0, 2.0001, 0.005)
    counts = np.array([int(np.sum(np.abs(_signed_nearest(ref, est, o)) <= ONSET_TOL)) for o in grid])
    top = counts == counts.max()
    runs, start = [], None
    for k, flag in enumerate(np.append(top, False)):
        if flag and start is None:
            start = k
        elif not flag and start is not None:
            runs.append((k - start, start, k - 1))
            start = None
    _, a, b = max(runs)
    o = float((grid[a] + grid[b]) / 2)
    for _ in range(3):
        s = _signed_nearest(ref, est, o)
        near = np.abs(s) <= ONSET_TOL
        if near.any():
            o += float(np.median(s[near]))
    return o


def match(ref: list, est: list, offset: float) -> dict:
    """贪心一对一匹配：按起音距离从小到大配对，每个音只用一次。"""
    pairs = []
    for i, r in enumerate(ref):
        for j, e in enumerate(est):
            dt = abs(r[0] - (e[0] + offset))
            if dt <= ONSET_TOL:
                pairs.append((dt, i, j))
    pairs.sort()
    used_r, used_e, onset_pairs = set(), set(), []
    for dt, i, j in pairs:
        if i not in used_r and j not in used_e:
            used_r.add(i)
            used_e.add(j)
            onset_pairs.append((i, j, dt))
    full = [(i, j) for i, j, _ in onset_pairs if abs(ref[i][2] - est[j][2]) <= PITCH_TOL]
    octave = [(i, j) for i, j, _ in onset_pairs if abs(abs(ref[i][2] - est[j][2]) - 1200) <= PITCH_TOL]
    lyric_pairs = [(i, j) for i, j, _ in onset_pairs if ref[i][3] and est[j][3]]
    nr, ne = len(ref), len(est)
    p = len(full) / ne if ne else 0.0
    r = len(full) / nr if nr else 0.0
    return {
        "标准答案音数": nr, "被比的音数": ne, "整体偏移_秒": round(offset, 3),
        "扒对（起音+音高）": len(full), "精确率": round(p, 3), "召回率": round(r, 3),
        "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
        "起音对上的": len(onset_pairs), "起音 F1": round(2 * len(onset_pairs) / (nr + ne), 3) if nr + ne else 0.0,
        "起音对上里音高也对的": round(len(full) / len(onset_pairs), 3) if onset_pairs else 0.0,
        "八度错误": len(octave),
        "起音偏差中位_ms": round(float(np.median([dt for *_, dt in onset_pairs])) * 1000, 1) if onset_pairs else None,
        "时值比中位（被比 / 答案）": round(float(np.median([est[j][1] / ref[i][1] for i, j in full if ref[i][1] > 0])), 3) if full else None,
        "歌词都有的配对": len(lyric_pairs),
        "歌词一样的": sum(1 for i, j in lyric_pairs if ref[i][3] == est[j][3]),
    }


def compare(ref: list, est: list) -> dict:
    a = np.array(sorted(x[0] for x in ref))
    b = np.array(sorted(x[0] for x in est))
    return match(ref, est, best_offset(a, b) if len(a) and len(b) else 0.0)


def selftest(ref: list) -> list[str]:
    fails = []
    rng = np.random.default_rng(3)
    m = compare(ref, ref)
    if m["F1"] != 1.0:
        fails.append(f"自己比自己 F1 = {m['F1']}")
    up = [(a, d, c + 1200, ly) for a, d, c, ly in ref]
    m = compare(ref, up)
    if m["扒对（起音+音高）"] != 0 or m["八度错误"] != len(ref):
        fails.append(f"整体高八度：扒对 {m['扒对（起音+音高）']}、八度错误 {m['八度错误']}（应 0 和 {len(ref)}）")
    keep = [x for k, x in enumerate(ref) if k % 5 != 0]
    m = compare(ref, keep)
    if abs(m["召回率"] - len(keep) / len(ref)) > 0.01 or m["精确率"] != 1.0:
        fails.append(f"删掉 20%：召回 {m['召回率']}、精确 {m['精确率']}")
    shifted = [(a + 0.3, d, c, ly) for a, d, c, ly in ref]
    m = compare(ref, shifted)
    if m["F1"] != 1.0 or abs(m["整体偏移_秒"] + 0.3) > 0.002:
        fails.append(f"整体挪 0.3 秒：偏移找成 {m['整体偏移_秒']}、F1 {m['F1']}")
    extra = ref + [(float(rng.uniform(0, ref[-1][0])), 0.2, float(rng.integers(55, 75)) * 100, "") for _ in range(len(ref) // 5)]
    m = compare(ref, sorted(extra))
    if not (0.75 <= m["精确率"] <= 0.9):
        fails.append(f"加 20% 乱音：精确率 {m['精确率']}（应在 0.75–0.9）")
    return fails


def pick(tr: dict, name: str | None) -> tuple[str, list]:
    if name:
        return name, tr[name]
    k = max(tr, key=lambda x: len(tr[x]))
    return k, tr[k]


def main(ref_path: str, est_path: str, ref_track: str | None = None) -> int:
    ref_name, ref = pick(tracks(load_svp(ref_path)), ref_track)
    fails = selftest(ref)
    print("自检：", "通过（自己比自己 100%、八度 / 删音 / 平移 / 乱音都测得出）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    est_tracks = tracks(load_svp(est_path))
    print(f"\n标准答案：{pathlib.Path(ref_path).name} 的「{ref_name}」{len(ref)} 个音")
    results = {}
    for name, est in est_tracks.items():
        m = compare(ref, est)
        results[name] = m
        print(f"\n被比的：{pathlib.Path(est_path).name} 的「{name}」")
        for k, v in m.items():
            print(f"  {k}：{v}")
    OUT.mkdir(parents=True, exist_ok=True)
    tag = pathlib.Path(est_path).stem
    (OUT / f"m1-01_compare_{tag}.json").write_text(
        json.dumps({"reference": ref_path, "reference_track": ref_name, "estimate": est_path,
                    "onset_tol_s": ONSET_TOL, "pitch_tol_cents": PITCH_TOL, "results": results},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果：{OUT / f'm1-01_compare_{tag}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
