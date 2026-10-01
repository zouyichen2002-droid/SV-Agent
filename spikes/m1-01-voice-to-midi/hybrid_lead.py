# -*- coding: utf-8 -*-
"""主唱分轨缺了的段，用整条人声补上。

karaoke 模型有时把整段主唱都分进叠唱：《刽子手》2:00–2:20 那段四遍齐唱，主唱分轨 -108 dB、叠唱 -21 dB；开头、结尾也是
（《潮声回响》r05 少了前奏、间奏、尾声的哼唱，同一个毛病）。扒谱在这些段里一个音都没有，歌词全堆成「没地方放」。

规则（每 50 ms 一帧）：整条人声在响（比全曲最响的那帧低不到 35 dB）、而主唱分轨比整条人声低 20 dB 以上，
**并且整条人声和平时的主唱差不多响**（比主唱分轨的典型响度 —— 主唱在响的帧的中位 —— 低不到 8 dB）= 主唱缺了。
最后这条是为了分开「模型把主唱分进了叠唱」（那段和平时主唱一样响：《刽子手》2:10 整条人声 -21 dB，主唱平时 -16 ~ -28）
和「主唱停了、只剩叠唱」（轻得多）—— 后者补进来，叠唱又会被当成主唱扒。
1 秒中值平滑以后连着 ≥ 1 秒才算一段，两头各放宽 0.1 秒；这些段里用整条人声，其余照旧用主唱分轨（叠唱多的地方仍然只有主唱），
接缝 30 ms 交叉淡化。输出和输入一样长、同一个零点；段落表另存 <输出>.json。

先跑自检（造的：主唱 + 齐唱，中间 4 秒主唱分轨是空的 → 只认出那一段、边界差 ≤ 0.15 秒；主唱换气时只剩很轻的齐唱 → 不认；
主唱分轨不缺 → 一段都不认；接缝不跳），不过就不跑。

    E:/sv-agent-data/envs/separator/Scripts/python.exe hybrid_lead.py <整条人声.wav> <主唱.wav> <输出.wav>
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

sys.stdout.reconfigure(encoding="utf-8")
HOP = 0.05
ACTIVE_DB, GAP_DB, LEVEL_DB = 35.0, 20.0, 8.0
SMOOTH_S, MIN_S, PAD_S, FADE_S = 1.0, 1.0, 0.1, 0.03


def frame_db(y: np.ndarray, sr: int) -> np.ndarray:
    m = y.mean(axis=1) if y.ndim == 2 else y
    n = int(sr * HOP)
    k = len(m) // n
    return 20 * np.log10(np.sqrt(np.mean(m[:k * n].reshape(k, n) ** 2, axis=1)) + 1e-9)


def missing_segments(v: np.ndarray, ld: np.ndarray, sr: int) -> list[tuple[float, float]]:
    V, L = frame_db(v, sr), frame_db(ld, sr)
    lead_typical = float(np.median(L[L > L.max() - ACTIVE_DB]))
    miss = (V > V.max() - ACTIVE_DB) & (L < V - GAP_DB) & (V > lead_typical - LEVEL_DB)
    w = int(round(SMOOTH_S / HOP)) | 1
    miss = median_filter(miss.astype(float), size=w, mode="nearest") > 0.5
    segs, i, dur = [], 0, len(v) / sr
    while i < len(miss):
        if miss[i]:
            j = i
            while j + 1 < len(miss) and miss[j + 1]:
                j += 1
            a, b = i * HOP, (j + 1) * HOP
            if b - a >= MIN_S:
                a, b = max(0.0, a - PAD_S), min(dur, b + PAD_S)
                if segs and a <= segs[-1][1]:
                    segs[-1] = (segs[-1][0], b)
                else:
                    segs.append((a, b))
            i = j + 1
        else:
            i += 1
    return segs


def splice(v: np.ndarray, ld: np.ndarray, sr: int, segs: list[tuple[float, float]]) -> np.ndarray:
    m = np.zeros(len(v), np.float32)
    for a, b in segs:
        m[int(a * sr):int(b * sr)] = 1.0
    f = max(1, int(FADE_S * sr))
    m = np.convolve(m, np.ones(f, np.float32) / f, mode="same")          # 0 → 1 的线性过渡，30 ms
    m = m[:, None] if v.ndim == 2 else m
    return (ld * (1 - m) + v * m).astype(np.float32)


def selftest() -> list[str]:
    fails, sr = [], 16000
    t = np.arange(int(sr * 20)) / sr
    lead = 0.3 * np.sin(2 * np.pi * 440 * t) * (np.sin(2 * np.pi * 0.5 * t) > -0.9)
    choir = 0.2 * np.sin(2 * np.pi * 330 * t)
    gap = (t >= 8.0) & (t < 12.0)
    full = np.where(gap, choir, lead + 0.05 * choir)
    ld = np.where(gap, 1e-6 * choir, lead)
    segs = missing_segments(full, ld, sr)
    if len(segs) != 1 or abs(segs[0][0] - 8.0) > 0.15 or abs(segs[0][1] - 12.0) > 0.15:
        fails.append(f"缺的那段没认对：{segs}（应 8.0–12.0）")
    # 主唱换气时只剩很轻的齐唱（2 秒一次、每次 1.2 秒）→ 不许认成缺
    breath = (np.sin(2 * np.pi * 0.5 * t) > 0.3)
    ld2 = np.where(breath, 0.0, lead)
    full2 = ld2 + 0.02 * choir
    if missing_segments(full2, ld2, sr):
        fails.append("主唱换气时只剩很轻的齐唱，被认成了缺")
    if missing_segments(full, full, sr):
        fails.append("主唱分轨不缺也认出了段")
    out = splice(full, ld, sr, segs)
    if np.max(np.abs(np.diff(out))) > 0.5:
        fails.append("接缝跳了")
    if not np.allclose(out[(t > 9) & (t < 11)], full[(t > 9) & (t < 11)], atol=1e-6):
        fails.append("缺的段里不是整条人声")
    if not np.allclose(out[t < 7], ld[t < 7], atol=1e-6):
        fails.append("没缺的地方不是主唱分轨")
    return fails


def main(full_wav: str, lead_wav: str, out_wav: str) -> int:
    fails = selftest()
    print("自检：", "通过（造的「中间 4 秒主唱分轨是空的」只认出那一段、边界差 ≤ 0.15 秒；换气时只剩很轻的齐唱不认；不缺不认；接缝不跳）"
          if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    out = pathlib.Path(out_wav)
    if out.exists():
        raise SystemExit(f"{out} 已经有了 —— 只写新文件")
    v, sr = sf.read(full_wav, dtype="float32", always_2d=True)
    ld, sr2 = sf.read(lead_wav, dtype="float32", always_2d=True)
    if sr != sr2 or len(v) != len(ld):
        raise SystemExit(f"两条不一样长 / 采样率不一样：{len(v)} @ {sr} vs {len(ld)} @ {sr2}")
    segs = missing_segments(v, ld, sr)
    y = splice(v, ld, sr, segs)
    sf.write(str(out), y, sr, subtype="PCM_16")
    V, L = frame_db(v, sr), frame_db(ld, sr)
    rows = [{"从": round(a, 2), "到": round(b, 2), "秒": round(b - a, 2),
             "整条人声 dB 中位": round(float(np.median(V[int(a / HOP):int(b / HOP)])), 1),
             "主唱分轨 dB 中位": round(float(np.median(L[int(a / HOP):int(b / HOP)])), 1)} for a, b in segs]
    # 读回核对：长度一样；段外就是主唱分轨、段里就是整条人声（16 位量化以内）
    back, _ = sf.read(str(out), dtype="float32", always_2d=True)
    inside = np.zeros(len(v), bool)
    for a, b in segs:
        inside[int((a + FADE_S) * sr):int((b - FADE_S) * sr)] = True
    edge = np.zeros(len(v), bool)
    for a, b in segs:
        for x in (a, b):
            edge[max(0, int((x - FADE_S) * sr)):int((x + FADE_S) * sr)] = True
    bad = []
    if len(back) != len(v):
        bad.append("长度不对")
    if inside.any() and np.max(np.abs(back[inside] - v[inside])) > 1e-3:
        bad.append("段里不是整条人声")
    outside = ~inside & ~edge
    if np.max(np.abs(back[outside] - ld[outside])) > 1e-3:
        bad.append("段外不是主唱分轨")
    log = {"整条人声": full_wav, "主唱分轨": lead_wav, "输出": out_wav,
           "规则": {"帧": HOP, "在响": f"比最响低不到 {ACTIVE_DB} dB", "缺": f"主唱比整条人声低 {GAP_DB} dB 以上",
                  "平滑": SMOOTH_S, "最短": MIN_S, "放宽": PAD_S, "交叉淡化": FADE_S},
           "用整条人声的段": rows, "合计秒": round(sum(r["秒"] for r in rows), 2), "核对": bad or "通过"}
    pathlib.Path(str(out) + ".json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt = lambda s: f"{int(s // 60)}:{s % 60:04.1f}"                                 # noqa: E731
    print(f"用整条人声补的段（{len(rows)} 段、共 {log['合计秒']} 秒）：" +
          "；".join(f"{fmt(r['从'])}–{fmt(r['到'])}（整条 {r['整条人声 dB 中位']} dB、主唱 {r['主唱分轨 dB 中位']} dB）" for r in rows))
    print("核对（读回来）：", "通过（长度一样；段里是整条人声、段外是主唱分轨）" if not bad else bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
