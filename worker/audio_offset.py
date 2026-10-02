# -*- coding: utf-8 -*-
r"""成品音频和工程对不对得上（v3 视频，2026-10-01）：算成品音频比工程晚多少秒 —— 歌词字幕整体按这个平移。

创作者的成品是在 FL 里混的：伴奏（分离出来的、或别处的伴奏）+ SV 渲染的主唱。工程的时间零点 = 原曲的零点；
成品要是剪了前奏、前面加了空白，字幕就会整体早 / 晚。伴奏是两边共有的 → 两边「起音包络」做互相关，峰在哪 = 差几秒。
也顺带查出给错音频（另一首歌）：峰很低 → 不可信，不平移、提醒创作者。

    from audio_offset import offset
    r = offset(ffmpeg, 成品, 伴奏)    # → {"晚秒": 1.234, "相关": 0.71, "次峰": 0.22, "可信": True, ...}
    晚秒 > 0：成品比工程晚（前面多了空白）→ 字幕时间 + 晚秒；晚秒 < 0：成品剪掉了开头

只用 numpy + ffmpeg（解码成 8 kHz 单声道）：
    python audio_offset.py <成品音频> <参考音频> [--ffmpeg …]
    python audio_offset.py --selftest
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

import numpy as np

SR = 8000
HOP = 80                     # 10 毫秒一帧
WIN = 256
MAX_LAG_S = 30.0             # 最多差 30 秒
MIN_OVERLAP_S = 30.0         # 至少重叠 30 秒才算
TRUST_CORR = 0.30            # 峰的相关 ≥ 0.30、且比 0.5 秒以外的最高峰高出 0.08 → 可信（阈值的依据见 docs/v3/s10-video.md §3）
TRUST_MARGIN = 0.08


def load(ffmpeg: str, path: str) -> np.ndarray:
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 解不开 {path}：{r.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(r.stdout, dtype=np.float32)


def envelope(x: np.ndarray) -> np.ndarray:
    """起音包络：每 10 毫秒一个值 = 对数频谱比上一帧涨了多少（只算涨的），去掉 1 秒以上的慢起伏，再标准化。"""
    n = 1 + (len(x) - WIN) // HOP
    if n < 10:
        return np.zeros(0)
    win = np.hanning(WIN).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, WIN)[::HOP][:n]
    logm = np.empty((n, WIN // 2 + 1), dtype=np.float32)
    for i in range(0, n, 4096):                       # 分块算，内存不涨
        logm[i:i + 4096] = np.log1p(100.0 * np.abs(np.fft.rfft(frames[i:i + 4096] * win, axis=1)))
    flux = np.concatenate([[0.0], np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)])
    k = 100
    flux = flux - np.convolve(flux, np.ones(k) / k, mode="same")
    return (flux - flux.mean()) / (flux.std() + 1e-9)


def best_lag(a: np.ndarray, b: np.ndarray) -> dict:
    """a 比 b 晚几帧（a[t + k] ≈ b[t]）：FFT 互相关，按重叠长度归一（≈ 皮尔逊相关），找峰、亚帧插值。"""
    la, lb = len(a), len(b)
    nfft = 1 << (la + lb - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft)), nfft)
    max_lag = int(MAX_LAG_S * SR / HOP)
    lags = np.arange(-max_lag, max_lag + 1)
    raw = c[lags % nfft]
    overlap = np.minimum(lb, la - lags) - np.maximum(0, -lags)
    ok = overlap >= min(MIN_OVERLAP_S * SR / HOP, 0.8 * min(la, lb))
    corr = np.where(ok, raw / np.maximum(overlap, 1), -np.inf)
    i = int(np.argmax(corr))
    frac = 0.0
    if 0 < i < len(corr) - 1 and np.isfinite(corr[i - 1]) and np.isfinite(corr[i + 1]):
        y0, y1, y2 = corr[i - 1], corr[i], corr[i + 1]
        den = y0 - 2 * y1 + y2
        frac = float(0.5 * (y0 - y2) / den) if den < 0 else 0.0
    far = np.abs(lags - lags[i]) > int(0.5 * SR / HOP)
    second = float(np.max(corr[far & ok])) if np.any(far & ok) else float("-inf")
    return {"帧": float(lags[i] + frac), "相关": float(corr[i]), "次峰": second}


SEG_S, SEG_HOP_S, SEG_TOL_S = 30.0, 15.0, 0.05


def segments(a: np.ndarray, b: np.ndarray) -> list[dict]:
    """一段一段查（成品里 30 秒一段、每 15 秒一段）：每段在参考里 ±30 秒找自己的峰 → 这段晚几秒。
    段太静、峰不可信 → 晚秒记 None（看不出，不算错）。"""
    n, hop, search = int(SEG_S * SR / HOP), int(SEG_HOP_S * SR / HOP), int(MAX_LAG_S * SR / HOP)
    out = []
    for s in range(0, len(a) - n + 1, hop):
        seg = a[s:s + n]
        lo, hi = max(0, s - search), min(len(b) - n, s + search)     # 参考里的起点 p：成品 s ↔ 参考 p，这段晚 s − p
        if hi < lo:
            out.append({"成品秒": round(s * HOP / SR, 1), "晚秒": None})
            continue
        chunk = b[lo:hi + n]
        nfft = 1 << (len(chunk) + n - 1).bit_length()
        corr = np.fft.irfft(np.fft.rfft(chunk, nfft) * np.conj(np.fft.rfft(seg, nfft)), nfft)[: hi - lo + 1] / n
        i = int(np.argmax(corr))
        far = np.abs(np.arange(len(corr)) - i) > int(0.5 * SR / HOP)
        second = float(np.max(corr[far])) if np.any(far) else float("-inf")
        trusted = corr[i] >= TRUST_CORR and corr[i] - second >= TRUST_MARGIN
        out.append({"成品秒": round(s * HOP / SR, 1), "晚秒": round((s - lo - i) * HOP / SR, 2) if trusted else None,
                    "相关": round(float(corr[i]), 2)})
    return out


def offset(ffmpeg: str, mix: str, ref: str) -> dict:
    """整首差几秒 + 分段核对。「对不上」= 分段里峰可信、却和整首差了 0.05 秒以上的段（成品中间剪过 / 加过段落）。"""
    a, b = envelope(load(ffmpeg, mix)), envelope(load(ffmpeg, ref))
    if len(a) == 0 or len(b) == 0:
        return {"晚秒": 0.0, "相关": 0.0, "次峰": 0.0, "可信": False, "原因": "音频太短", "分段": []}
    r = best_lag(a, b)
    late = round(r["帧"] * HOP / SR, 3)
    trusted = r["相关"] >= TRUST_CORR and r["相关"] - r["次峰"] >= TRUST_MARGIN
    segs = segments(a, b)
    seen = [x for x in segs if x["晚秒"] is not None]
    off = [x for x in seen if abs(x["晚秒"] - late) > SEG_TOL_S] if trusted else seen
    return {"晚秒": late, "相关": round(r["相关"], 3), "次峰": round(r["次峰"], 3), "可信": bool(trusted),
            "成品秒": round(len(a) * HOP / SR, 1), "参考秒": round(len(b) * HOP / SR, 1),
            "分段": segs, "对得上的段": len(seen) - len(off) if trusted else 0, "对不上的段": off, "看不出的段": len(segs) - len(seen)}


def _runs(segs: list[dict]) -> list[tuple[float, float]]:
    """连着的、差得一样（0.05 秒以内）的段并成一截：[(从成品第几秒起, 晚几秒)]。"""
    out: list[tuple[float, float]] = []
    for x in segs:
        if not out or abs(x["晚秒"] - out[-1][1]) > SEG_TOL_S:
            out.append((x["成品秒"], x["晚秒"]))
    return out


def _late(d: float) -> str:
    return "对得上" if abs(d) < 0.02 else f"{'晚' if d > 0 else '早'} {abs(d):.2f} 秒"


def describe(r: dict) -> str:
    """一句话给创作者看。"""
    if not r["可信"]:
        seen = [x for x in r["分段"] if x["晚秒"] is not None]
        if not seen:
            return f"成品音频和这首的伴奏对不上（相关 {r['相关']:.2f}）—— 是不是给错了歌？字幕没平移，多半不同步"
        parts = "；".join(f"第 {s:.0f} 秒起{_late(d)}" for s, d in _runs(seen)[:6])
        return f"成品前后和工程差得不一样（{parts}）—— 中间剪过或加过段落？字幕没平移，有的段会错位"
    head = "成品和工程对得上" if abs(r["晚秒"]) < 0.02 else f"成品比工程{_late(r['晚秒'])}，字幕整体跟着平移了"
    if r["对不上的段"]:
        parts = "；".join(f"第 {s:.0f} 秒起又差 {d - r['晚秒']:+.2f} 秒" for s, d in _runs(r["对不上的段"])[:6])
        head += f"；可是有 {len(r['对不上的段'])} 段和整首差得不一样（{parts}）—— 那几段的字幕会错位"
    return head


def selftest() -> int:
    """合成的「歌」：随机起音的衰减噪声（每个音色不同），伴奏 + 另一条「人声」；平移 / 剪头 / 换一首。"""
    rng = np.random.default_rng(7)

    def song(seconds: float, seed: int) -> np.ndarray:
        g = np.random.default_rng(seed)
        x = np.zeros(int(seconds * SR), dtype=np.float32)
        t = 0.0
        while t < seconds - 1:
            n = int(g.uniform(0.05, 0.4) * SR)
            burst = g.normal(size=n).astype(np.float32) * np.exp(-np.arange(n) / (n / 4)).astype(np.float32)
            burst = np.convolve(burst, g.normal(size=8).astype(np.float32), mode="same")      # 每个音色不一样
            i = int(t * SR)
            x[i:i + n] += burst[: len(x) - i] * g.uniform(0.3, 1.0)
            t += g.choice([0.25, 0.5, 0.5, 0.75, 1.0]) * g.uniform(0.9, 1.1)
        return x

    accomp, vocal, other = song(90, 1), song(90, 2) * 0.6, song(90, 3)
    env_ref = envelope(accomp)
    fails = 0

    def check(name: str, mix: np.ndarray, want: float | None) -> None:
        nonlocal fails
        r = best_lag(envelope(mix + rng.normal(scale=0.02, size=len(mix)).astype(np.float32)), env_ref)
        late = r["帧"] * HOP / SR
        trusted = r["相关"] >= TRUST_CORR and r["相关"] - r["次峰"] >= TRUST_MARGIN
        ok = (not trusted) if want is None else (trusted and abs(late - want) <= 0.015)
        fails += not ok
        print(f"  {'过' if ok else '不过'}  {name}：晚 {late:+.3f} 秒，相关 {r['相关']:.2f}，次峰 {r['次峰']:.2f}，{'可信' if trusted else '不可信'}"
              + (f"（应为 {want:+.3f}）" if want is not None else "（应为不可信）"))

    pad = np.zeros(int(1.234 * SR), dtype=np.float32)
    check("前面加了 1.234 秒空白", np.concatenate([pad, accomp + vocal]), 1.234)
    cut = int(3.5 * SR)
    check("剪掉了前 3.5 秒", (accomp + vocal)[cut:], -3.5)
    check("一样长、对齐", accomp + vocal, 0.0)
    check("给错了歌", other + vocal, None)
    print("自检：" + ("全过" if fails == 0 else f"{fails} 项不过"))
    return 1 if fails else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("mix", nargs="?")
    ap.add_argument("ref", nargs="?")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.mix and a.ref):
        ap.error("要给 成品音频 和 参考音频")
    print(json.dumps(offset(a.ffmpeg, a.mix, a.ref), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
