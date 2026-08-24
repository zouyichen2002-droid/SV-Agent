"""音频电平与频段分析。**原生 numpy，不依赖 FL MCP。**

## 为什么自己实现

原来 `scripts/analyze_mix.py` 从 `fl_studio_mcp.tools.audio` 借两个函数，
代价是整条链依赖一个隔离的 conda env + 一个 48MB 的第三方仓库。
清点之后发现不值：

    analyze_bands   rms / peak / 三段占比 —— 就是一次 STFT，几十行
    audio_analyze   tempo / key —— **两个都不可靠**

`audio_analyze` 那两个估计值实测都靠不住：76 BPM 的歌它报 152（倍频误判，
和音高估计的八度误判同一类问题），key 的文档自己写着「~60-80% 准确，
可能混淆关系大小调」。我们的 tempo 和 key 本来就是已知的（写在 project.json 里），
不需要估计。

所以留下可靠的那部分自己写，去掉整个依赖。

## 一个模块，两个入口共用

`analyze_mix.py` 和 `step5_assemble.py` 都要算频段。
**不能各写一遍** —— 那次对齐验证就是因为两个入口各自组装管线，
一个漏了 `max_shift_s`，产出 0.340 和 0.360 两个不同的数字，**两边都不报错**。
所以这里是唯一实现。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

# 频段边界。250 / 4000 是常规的低-中-高分界：
# 250Hz 以下是基频与浑浊区，250–4k 是人声所在，4k 以上是齿音与空气感
BANDS = (("low", 0.0, 250.0), ("mid", 250.0, 4000.0), ("high", 4000.0, None))

N_FFT = 2048
HOP = 512


@dataclass
class AudioStats:
    path: Path
    sr: int
    channels: int
    duration_s: float
    peak_db: float
    rms_db: float
    bands_pct: dict[str, float]

    def describe(self) -> str:
        b = "　".join(f"{k} {v:.1f}%" for k, v in self.bands_pct.items())
        return (f"{self.duration_s:.2f}s · {self.sr}Hz · {self.channels}ch\n"
                f"    peak {self.peak_db:.1f} dB　rms {self.rms_db:.1f} dB\n"
                f"    {b}")


def _db(x: float) -> float:
    return 20.0 * np.log10(max(1e-9, float(x)))


def analyze(path: Path | str) -> AudioStats:
    p = Path(path)
    info = sf.info(str(p))
    y, sr = sf.read(str(p), always_2d=True)
    mono = y.mean(axis=1).astype(np.float32)

    n = (len(mono) - N_FFT) // HOP
    if n < 2:
        pct = {k: 0.0 for k, _lo, _hi in BANDS}
    else:
        w = np.hanning(N_FFT).astype(np.float32)
        idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
        S = np.abs(np.fft.rfft(mono[idx] * w, axis=1)) ** 2
        f = np.fft.rfftfreq(N_FFT, 1.0 / sr)
        tot = float(S.sum()) or 1.0
        pct = {}
        for name, lo, hi in BANDS:
            m = (f >= lo) & (f < (hi if hi is not None else sr))
            pct[name] = round(100.0 * float(S[:, m].sum()) / tot, 2)

    return AudioStats(
        path=p, sr=sr, channels=info.channels,
        duration_s=info.duration,
        peak_db=round(_db(np.abs(mono).max()), 2),
        rms_db=round(_db(np.sqrt((mono.astype(np.float64) ** 2).mean())), 2),
        bands_pct=pct,
    )


# 经验区间。**不是硬门槛** —— 超出只说明值得看一眼。
# 服务的目标是「人声在前的慢速流行/氛围曲」，换风格要重定。
GUIDE = {
    "peak_db": (-6.0, -0.3, "母带前留 headroom；贴 0 会在后续处理里削顶"),
    "rms_db": (-24.0, -12.0, "整体电平。太低推不起来，太高没有动态"),
    "low": (20.0, 55.0, "<250Hz 占比。过高糊，过低单薄"),
    "mid": (30.0, 70.0, "250–4000Hz 占比。人声就在这一段"),
    "high": (0.5, 25.0, ">4000Hz 占比。过低发闷，过高刺"),
}


def verdict(name: str, v: float) -> str:
    lo, hi, why = GUIDE[name]
    if v < lo:
        return f"低于经验区间 {lo}–{hi}　{why}"
    if v > hi:
        return f"高于经验区间 {lo}–{hi}　{why}"
    return f"在经验区间 {lo}–{hi} 内"


def report(st: AudioStats, *, with_verdict: bool = True) -> str:
    rows = [f"  时长 {st.duration_s:.2f}s　{st.sr}Hz　{st.channels}ch"]
    for k, v in (("peak_db", st.peak_db), ("rms_db", st.rms_db)):
        rows.append(f"  {k:8} {v:7.1f} dB"
                    + (f"　{verdict(k, v)}" if with_verdict else ""))
    for k in ("low", "mid", "high"):
        v = st.bands_pct.get(k, 0.0)
        rows.append(f"  {k:8} {v:6.1f}%"
                    + (f"　{verdict(k, v)}" if with_verdict else ""))
    return "\n".join(rows)


def diff(a: AudioStats, b: AudioStats) -> str:
    """a − b。**差值比绝对值可靠** —— 参考曲替你定义了这个风格该是什么样。"""
    rows = [f"  rms_db  {a.rms_db - b.rms_db:+.1f} dB",
            f"  peak_db {a.peak_db - b.peak_db:+.1f} dB"]
    for k in ("low", "mid", "high"):
        rows.append(f"  {k:6}  "
                    f"{a.bands_pct.get(k, 0) - b.bands_pct.get(k, 0):+.1f} 个百分点")
    return "\n".join(rows)
