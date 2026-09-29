# -*- coding: utf-8 -*-
"""M1-01 第二个裁判：直接问人声分轨「这个音的时间段里，实际唱的是不是这个音高」—— 不靠你的终稿。

为什么要它：终稿是你改过的编曲，你可能故意改了 Suno 唱的音。只拿终稿当答案，
扒谱工具的分数里会混进「你改过的地方」。这个裁判用 librosa 的 pyin 从人声分轨里测音高，各自打分：
- 终稿和音频有多一致 → 终稿能不能当「Suno 实际唱了什么」的答案（也顺带看出你改了多少）
- 每个工具扒出来的音和音频有多一致 → 工具自己的音高准不准，和你改没改无关

口径：每个音取中间 60% 的时间段；pyin 判成有声的帧 ≥ 30% 才算测得出；
这些帧音高的中位数和音符相差 ≤ 50 音分 = 对；差一个八度（±50 音分）= 八度错；其余 = 不对。
整体偏移：±0.5 秒内找「对」最多的偏移（最长平台的中点，和 compare_notes 一样）。

自检（不过就不比）：按终稿前 60 个音合成一条带泛音的假人声 →
终稿对它 ≥ 95% 对、偏移找成 0；20% 的音升半音 → 必须判成不对；10% 的音升八度 → 必须判成八度错；
整体挪 0.25 秒 → 偏移必须找回来。

    python audio_oracle.py <人声分轨.wav> <标准答案.svp> <轨名> [<被比的 .svp::轨名 或 .mid> ...]
只读输入；结果和 pyin 缓存写在 E:/sv-agent-data/probes/m1-01-voice-to-midi/（第二次跑不用重算）。
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

import librosa
import numpy as np
import soundfile as sf

import compare_notes as C

sys.stdout.reconfigure(encoding="utf-8")
SR, HOP, FRAME = 22050, 256, 2048
FMIN, FMAX = float(librosa.note_to_hz("C2")), float(librosa.note_to_hz("C6"))
MID, VOICED_MIN, TOL = 0.6, 0.3, 50.0      # 取中间 60% · 有声帧 ≥ 30% · 50 音分
OUT = C.OUT


def f0_cents(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """→ (帧时间秒, 音高音分 = MIDI × 100；无声 = nan)。"""
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    f0, voiced, _ = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=SR, frame_length=FRAME, hop_length=HOP)
    t = librosa.times_like(f0, sr=SR, hop_length=HOP)
    ok = voiced & np.isfinite(f0)
    return t, np.where(ok, 6900 + 1200 * np.log2(np.where(ok, f0, 440.0) / 440.0), np.nan)


def cached_f0(wav: pathlib.Path) -> tuple[np.ndarray, np.ndarray]:
    st = wav.stat()
    key = f"{wav}|{st.st_size}|{int(st.st_mtime)}|{SR}|{HOP}|{FRAME}|{FMIN:.2f}|{FMAX:.2f}"
    cache = OUT / f"m1-01_f0_{wav.stem}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        if str(z["key"]) == key:
            return z["t"], z["cents"]
    y, sr = sf.read(str(wav), dtype="float32")
    t, cents = f0_cents(y, sr)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez(cache, t=t, cents=cents, key=np.array(key))
    return t, cents


def note_medians(notes: list, t: np.ndarray, cents: np.ndarray, offset: float) -> np.ndarray:
    """每个音中间 60% 里有声帧音高的中位数；测不出 = nan。"""
    out = np.full(len(notes), np.nan)
    for k, (s, d, _, _) in enumerate(notes):
        a = s + offset + d * (1 - MID) / 2
        i0, i1 = np.searchsorted(t, [a, a + d * MID])
        seg = cents[i0:i1]
        v = seg[np.isfinite(seg)]
        if len(seg) and len(v) >= max(1, VOICED_MIN * len(seg)):
            out[k] = np.median(v)
    return out


def classify(notes: list, med: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """→ (音符 − 音频 的音分差, 对, 八度错, 测得出)。"""
    diff = np.array([c for _, _, c, _ in notes]) - med
    return diff, np.abs(diff) <= TOL, np.abs(np.abs(diff) - 1200) <= TOL, np.isfinite(med)


def best_offset(notes: list, t: np.ndarray, cents: np.ndarray, span: float = 0.5, step: float = 0.01) -> float:
    grid = np.arange(-span, span + 1e-9, step)
    counts = np.array([int(classify(notes, note_medians(notes, t, cents, o))[1].sum()) for o in grid])
    top = counts == counts.max()
    runs, start = [], None
    for k, flag in enumerate(np.append(top, False)):
        if flag and start is None:
            start = k
        elif not flag and start is not None:
            runs.append((k - start, start, k - 1))
            start = None
    _, a, b = max(runs)
    return float((grid[a] + grid[b]) / 2)


def score(notes: list, t: np.ndarray, cents: np.ndarray) -> dict:
    o = best_offset(notes, t, cents)
    diff, ok, octv, meas = classify(notes, note_medians(notes, t, cents, o))
    n, m = len(notes), int(meas.sum())
    hist = collections.Counter(int(round(x / 100)) for x in diff[meas])
    return {
        "音数": n, "整体偏移_秒": round(o, 3), "测得出": m,
        "对": int(ok.sum()), "对 / 测得出": round(float(ok.sum()) / m, 3) if m else 0.0,
        "对 / 全部": round(float(ok.sum()) / n, 3) if n else 0.0,
        "八度错": int(octv.sum()), "不对（非八度）": int(m - ok.sum() - octv.sum()),
        "音高差分布（音符 − 音频，半音：个数）": {f"{k:+d}" if k else "0": v for k, v in hist.most_common(8)},
    }


def same(x: float, y: float) -> bool:
    return bool(np.isfinite(x) and np.isfinite(y) and abs(x - y) <= TOL)


def crosscheck(ref: list, est: list, t: np.ndarray, cents: np.ndarray) -> dict:
    """三方对质：终稿、工具、音频（只看起音对上的配对）。工具和终稿不一样的时候谁对？

    - 终稿和音频一致 → 工具错
    - 工具和音频一致、终稿不同 → 是你改过的音，算给工具（「算上你改过的」F1）
    - 终稿和工具一致、音频不同 → 音频裁判自己可疑，照终稿算对"""
    med = note_medians(ref, t, cents, best_offset(ref, t, cents))
    cat, credit = collections.Counter(), 0
    for i, j, _ in C.pair_onsets(ref, est, C.offset_between(ref, est)):
        r, e, au = ref[i][2], est[j][2], med[i]
        er, ra, ea = same(e, r), same(r, au), same(e, au)
        if not np.isfinite(au):
            k = "音频测不出（照终稿算）"
        elif er:
            k = "三方一致" if ra else "终稿和工具一致、音频不同（音频裁判可疑）"
        elif ra:
            k = "工具错（终稿和音频一致）"
        else:
            k = "你改过的（工具和音频一致）" if ea else "三方都不同"
        cat[k] += 1
        credit += int(er or (ea and not ra))
    nr, ne = len(ref), len(est)
    p, r = (credit / ne if ne else 0.0), (credit / nr if nr else 0.0)
    return {"起音对上的配对": sum(cat.values()), **dict(cat.most_common()),
            "算上你改过的：对的": credit, "算上你改过的：F1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def synth(notes: list) -> np.ndarray:
    """带 6 个泛音的假人声，首尾各 20 ms 淡入淡出。"""
    y = np.zeros(int((max(s + d for s, d, _, _ in notes) + 0.5) * SR), np.float32)
    for s, d, c, _ in notes:
        f = 440.0 * 2 ** ((c / 100 - 69) / 12)
        tt = np.arange(int(d * SR)) / SR
        env = np.clip(np.minimum(tt / 0.02, (d - tt) / 0.02), 0, 1)
        tone = sum(np.sin(2 * np.pi * k * f * tt) / k for k in range(1, 7) if k * f < SR / 2)
        seg = (0.15 * env * tone).astype(np.float32)
        i = int(s * SR)
        y[i:i + len(seg)] += seg[: len(y) - i]
    return y


def selftest(ref: list) -> list[str]:
    fails = []
    base = sorted(ref)[:60]
    s0 = base[0][0]
    base = [(s - s0 + 0.5, d, c, ly) for s, d, c, ly in base]
    t, cents = f0_cents(synth(base), SR)
    r = score(base, t, cents)
    if r["对 / 测得出"] < 0.95 or r["测得出"] < 0.9 * len(base) or abs(r["整体偏移_秒"]) > 0.05:
        fails.append(f"合成假人声：对 {r['对 / 测得出']}、测得出 {r['测得出']}/{len(base)}、偏移 {r['整体偏移_秒']}")
    rng = np.random.default_rng(5)
    med = note_medians(base, t, cents, 0.0)
    for label, shift, frac, want in (("升半音", 100, 5, "不对"), ("升八度", 1200, 10, "八度错")):
        idx = set(rng.choice(len(base), size=len(base) // frac, replace=False).tolist())
        bad = [(s, d, c + shift if k in idx else c, ly) for k, (s, d, c, ly) in enumerate(base)]
        _, ok, octv, meas = classify(bad, med)
        hit = [k for k in idx if meas[k] and (octv[k] if want == "八度错" else (not ok[k] and not octv[k]))]
        n_meas = sum(1 for k in idx if meas[k])
        if not n_meas or len(hit) / n_meas < 0.95:
            fails.append(f"{len(idx)} 个音{label}：判成{want}的 {len(hit)}/{n_meas}")
    o = best_offset([(s + 0.25, d, c, ly) for s, d, c, ly in base], t, cents)
    if abs(o + 0.25) > 0.05:
        fails.append(f"整体挪 0.25 秒：偏移找成 {o:.3f}（应 −0.25）")
    # 三方对质：音频 = base（「Suno 唱的」）；终稿 = 6 个音改了小三度（「你改过的」）；
    # 工具 = 另外 6 个音高八度（「工具错」）。只从音频裁判测对了的音里挑，分类必须一个不差
    good = [k for k in range(len(base)) if same(base[k][2], med[k])]
    pick = rng.permutation(good)
    edited, wrong = set(pick[:6].tolist()), set(pick[6:12].tolist())
    ref_e = [(s, d, c + 300 if k in edited else c, ly) for k, (s, d, c, ly) in enumerate(base)]
    est_w = [(s, d, c + 1200 if k in wrong else c, ly) for k, (s, d, c, ly) in enumerate(base)]
    x = crosscheck(ref_e, est_w, t, cents)
    want = {"工具错（终稿和音频一致）": 6, "你改过的（工具和音频一致）": 6, "算上你改过的：对的": len(base) - 6}
    if any(x.get(k, 0) != v for k, v in want.items()):
        fails.append(f"三方对质：{ {k: x.get(k, 0) for k in want} }（应 {want}）")
    return fails


def load_est(arg: str) -> dict[str, list]:
    path, _, want = arg.partition("::")
    tr = C.midi_tracks(path) if path.lower().endswith((".mid", ".midi")) else C.tracks(C.load_svp(path))
    return {k: v for k, v in tr.items() if not want or k == want}


def main(wav: str, ref_svp: str, ref_track: str, *ests: str) -> int:
    ref_name, ref = C.pick(C.tracks(C.load_svp(ref_svp)), ref_track)
    t0 = time.perf_counter()
    fails = selftest(ref)
    print(f"自检（{time.perf_counter() - t0:.0f} 秒）：",
          "通过（假人声 ≥ 95% 对、升半音 / 升八度 / 平移都测得出，三方对质分类一个不差）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    t0 = time.perf_counter()
    t, cents = cached_f0(pathlib.Path(wav))
    print(f"人声分轨音高：{len(t)} 帧、有声 {np.isfinite(cents).mean():.0%}（{time.perf_counter() - t0:.0f} 秒）")
    rows = {f"{pathlib.Path(ref_svp).parent.name}/{pathlib.Path(ref_svp).name} · {ref_name}": score(ref, t, cents)}
    for e in ests:
        for name, notes in load_est(e).items():
            r = score(notes, t, cents)
            r["三方对质（对终稿）"] = crosscheck(ref, notes, t, cents)
            rows[f"{pathlib.Path(e.partition('::')[0]).name} · {name}"] = r
    for name, r in rows.items():
        print(f"\n{name}")
        for k, v in r.items():
            print(f"  {k}：{v}")
    out = OUT / "m1-01_audio_oracle.json"
    out.write_text(json.dumps({"vocal_stem": wav, "reference": ref_svp, "reference_track": ref_name,
                               "params": {"sr": SR, "hop": HOP, "frame": FRAME, "fmin_hz": round(FMIN, 2),
                                          "fmax_hz": round(FMAX, 2), "middle": MID, "voiced_min": VOICED_MIN,
                                          "tol_cents": TOL},
                               "results": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
