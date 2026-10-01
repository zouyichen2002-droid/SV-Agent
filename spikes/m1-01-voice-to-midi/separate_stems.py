# -*- coding: utf-8 -*-
"""换分离模型：创作者 09-30「对于《潮声回响》的人声分离效果不好，至少没有 SUNO 自带的人声分离好」。
audio-separator（MIT）跑两步，CPU、低优先级（他 09-30 说过「好卡啊」）：

① 人声 / 伴奏：vocals_mel_band_roformer.ckpt（audio-separator 自带测试 人声 SDR 中位 12.6 dB；Demucs htdemucs 9.9）
② 主唱 / 叠唱：mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt，喂 ① 的人声，拆成主唱和叠唱

- 模型第一次用时自动下载到 E:/sv-agent-data/models/separation/（创作者 09-30 同意下载这两个，各 870 MB）
- 进程调「低于正常」、torch 限线程；输出写到给的目录（已有的不重算）
- 跑完核对（第二个裁判是原曲本身）：每条输出和输入一样长、同一个零点（互相关）；① 的人声 + 伴奏 ≈ 原曲（相关）；
  ② 的主唱 + 叠唱 ≈ ① 的人声

    E:/sv-agent-data/envs/separator/Scripts/python.exe separate_stems.py <原曲.wav> <输出目录> [线程数，默认 8]
"""
from __future__ import annotations

import ctypes
import json
import math
import pathlib
import sys
import time

import numpy as np
import soundfile as sf
from scipy import signal

sys.stdout.reconfigure(encoding="utf-8")
MODELS = pathlib.Path("E:/sv-agent-data/models/separation")
VOCAL_MODEL = "vocals_mel_band_roformer.ckpt"
KARAOKE_MODEL = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"


def low_priority() -> None:
    if sys.platform == "win32":
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000):   # BELOW_NORMAL_PRIORITY_CLASS
            print("（没调成低优先级）", flush=True)


def mono8k(path: pathlib.Path) -> np.ndarray:
    y, sr = sf.read(str(path), dtype="float32")
    y = y.mean(axis=1) if y.ndim == 2 else y
    return signal.resample_poly(y, 8000, sr).astype(np.float32)


def lag_corr(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    c = signal.correlate(x, y, mode="full", method="fft")
    lags = signal.correlation_lags(n, n, mode="full")
    m = np.abs(lags) <= 4000
    i = int(np.argmax(c[m]))
    return float(-lags[m][i] / 8.0), float(c[m][i] / math.sqrt(float(np.dot(x, x)) * float(np.dot(y, y)) + 1e-12))


def lead_wins(ld: np.ndarray, bk: np.ndarray) -> tuple[float, float]:
    """100 ms 一帧（8 kHz），两条里至少一条有声（离整首最响 40 dB 以内）的帧里：主唱更响的占几成、主唱减叠唱的中位 dB。"""
    n = min(len(ld), len(bk)) // 800
    db = lambda x: 10 * np.log10(np.mean(x[: n * 800].reshape(n, 800) ** 2, axis=1) + 1e-12)   # noqa: E731
    a, b = db(ld), db(bk)
    on = (a > max(a.max(), b.max()) - 40) | (b > max(a.max(), b.max()) - 40)
    if not on.any():
        return 0.0, 0.0
    return float(np.mean(a[on] > b[on])), float(np.median(a[on] - b[on]))


def pick(files: list[str], out: pathlib.Path, src: pathlib.Path, *words: str) -> pathlib.Path:
    """按括号里的名字挑输出（不分大小写）：各模型起名不一样 —— vocals_mel_band_roformer 叫 (vocals) / (other)，
    karaoke 叫 (Vocals) / (Instrumental)（这个模型的用途是「去掉主唱」：Vocals = 主唱，Instrumental = 剩下的叠唱）。
    **只看输入文件名后面新加的那段**：第二步的输入名里本来就带「(vocals)」，09-30 就这么把主唱、叠唱标反过一次。"""
    tail = {}
    for f in files:
        name = pathlib.Path(f).name
        if not name.startswith(src.stem):
            raise SystemExit(f"输出名 {name} 不是以输入名 {src.stem} 开头的，认不出")
        tail[f] = name[len(src.stem):].lower()
    for w in words:
        hit = [f for f in files if f"({w.lower()})" in tail[f]]
        if hit:
            p = pathlib.Path(hit[0])
            return p if p.is_absolute() else out / p
    raise SystemExit(f"输出里找不到 {words}：{files}")


def done(out: pathlib.Path, src: pathlib.Path, model: str) -> list[str]:
    """这个模型对这个输入已经分过了（输出都在）→ 不重算。
    输出名里的模型名和 audio-separator 一样截到第一个点（…_sdr_10.1956.ckpt → …_sdr_10）。"""
    stem = model.split(".")[0]
    return sorted(str(p) for p in out.glob(f"{src.stem}_(*)_{stem}.wav"))


def main(src: str, out_dir: str, threads: str = "8") -> int:
    low_priority()
    import torch
    torch.set_num_threads(int(threads))
    # 10-01 换显卡（创作者同意下 CUDA 版 torch 2.14.0+cu130）：有显卡 audio-separator 就自动用，用的是 32 位（不是半精度）。
    # 《逃跑的天使》对 CPU 版：波形差约 1%（信噪比 36–42 dB；试过关掉 TF32，一模一样 → 不是 TF32 来的）；
    # 拿去扒谱，音符 F1 0.994 —— 比 Vocal2Midi 同一份主唱跑两次的差别（0.991）还小 → 创作者定用显卡。分离 25 分钟 → 约 75 秒
    from audio_separator.separator import Separator

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    log = {"input": src, "threads": int(threads)}
    sep = Separator(model_file_dir=str(MODELS), output_dir=str(out), output_format="WAV")

    t0 = time.perf_counter()
    files1 = done(out, pathlib.Path(src), VOCAL_MODEL)
    if len(files1) < 2:
        sep.load_model(model_filename=VOCAL_MODEL)
        files1 = sep.separate(src)
    vocals, inst = pick(files1, out, pathlib.Path(src), "vocals"), pick(files1, out, pathlib.Path(src), "instrumental", "other")
    log["step1"] = {"model": VOCAL_MODEL, "seconds": round(time.perf_counter() - t0, 1), "vocals": str(vocals), "instrumental": str(inst)}
    print(f"① 人声 / 伴奏：{log['step1']['seconds']} 秒 → {vocals.name} · {inst.name}", flush=True)

    t0 = time.perf_counter()
    files2 = done(out, vocals, KARAOKE_MODEL)
    if len(files2) < 2:
        sep.load_model(model_filename=KARAOKE_MODEL)
        files2 = sep.separate(str(vocals))
    lead = pick(files2, out, vocals, "vocals", "lead")
    back = pathlib.Path(next(f for f in files2 if pathlib.Path(f).name != lead.name))
    back = back if back.is_absolute() else out / back
    log["step2"] = {"model": KARAOKE_MODEL, "seconds": round(time.perf_counter() - t0, 1), "lead": str(lead), "backing": str(back)}
    print(f"② 主唱 / 叠唱：{log['step2']['seconds']} 秒 → {lead.name} · {back.name}", flush=True)

    # 核对：原曲当第二个裁判
    full = mono8k(pathlib.Path(src))
    v, a, ld, bk = (mono8k(p) for p in (vocals, inst, lead, back))
    checks = {}
    for name, x in (("人声", v), ("伴奏", a), ("主唱", ld), ("叠唱", bk)):
        checks[name] = {"秒": round(len(x) / 8000, 3)}
    lag1, r1 = lag_corr(full, v + a)
    lag2, r2 = lag_corr(v, ld + bk)
    checks["人声 + 伴奏 对 原曲"] = {"晚 ms": round(lag1, 3), "相关": round(r1, 4)}
    checks["主唱 + 叠唱 对 人声"] = {"晚 ms": round(lag2, 3), "相关": round(r2, 4)}
    e = lambda x: round(10 * math.log10(float(np.mean(x ** 2)) + 1e-12), 1)                   # noqa: E731
    checks["响度 dB"] = {"原曲": e(full), "人声": e(v), "伴奏": e(a), "主唱": e(ld), "叠唱": e(bk)}
    log["checks"] = checks
    fails = []
    if abs(len(v) - len(full)) > 8 or abs(len(ld) - len(full)) > 8:
        fails.append("长度和原曲不一样")
    if abs(lag1) > 1.0 or r1 < 0.95:
        fails.append(f"人声 + 伴奏 和原曲对不上（晚 {lag1:.1f} ms、相关 {r1:.3f}）")
    if abs(lag2) > 1.0 or r2 < 0.95:
        fails.append(f"主唱 + 叠唱 和人声对不上（晚 {lag2:.1f} ms、相关 {r2:.3f}）")
    if e(ld) <= e(bk):     # 上面几条对主唱 / 叠唱是对称的，标反了查不出来 —— 主唱一般比叠唱响
        # 整首比不过时再逐段看（10-01《倒瞰清白》，川剧帮腔：整首叠唱 -23.9 dB 比主唱 -24.5 dB 响，可 100 ms 一帧看，
        # 主唱更响的占 59%、中位 +5.4 dB，只有帮腔那几段是叠唱响 —— 没标反）。真标反时（09-30《潮声回响》）主唱只在约 31% 的时候更响
        frac, med = lead_wins(ld, bk)
        checks["主唱更响的时间"] = {"占有声的帧": round(frac, 3), "中位差 dB": round(med, 1)}
        if not (frac > 0.5 and med > 0):
            fails.append(f"主唱（{e(ld)} dB）不比叠唱（{e(bk)} dB）响，逐段看也只有 {frac:.0%} 的时候更响（中位 {med:+.1f} dB）—— 可能标反了，去听")
    log["fails"] = fails
    (out / "separate_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v2 in checks.items():
        print(f"  {k}：{v2}")
    print("核对：", "通过（长度、零点对上；分出来的加起来 ≈ 原来的）" if not fails else fails)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
