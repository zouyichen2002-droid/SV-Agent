"""音频载入 + f0 轨迹磁盘缓存。

缓存键包含文件 mtime/size 与估计器参数 —— 换了素材或改了参数就自动失效，
避免"改了参数但读到旧结果"这类静默错误。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .pitch.base import PitchTrack


def load_mono(path: str | Path, sr: int) -> np.ndarray:
    import librosa
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y.astype(np.float32)


def _key(path: Path, est_name: str, params: dict, sr: int, hop_s: float) -> str:
    st = path.stat()
    blob = json.dumps({"f": path.name, "size": st.st_size, "mtime": int(st.st_mtime),
                       "est": est_name, "sr": sr, "hop": hop_s,
                       "params": {k: str(v) for k, v in sorted(params.items())}},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def cached_track(cache_dir: Path, audio_path: Path, est, sr: int, hop_s: float,
                 n_frames: int, fmin: float, fmax: float,
                 force: bool = False) -> tuple[PitchTrack, bool]:
    """返回 (轨迹, 是否命中缓存)。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    probe = getattr(est, "cache_params", None)
    if probe is None:
        raise TypeError(f"{type(est).__name__} 没有 cache_params —— "
                        f"缓存键就不完整了，拒绝缓存以免读到过期结果")
    params = {**probe, "fmin": fmin, "fmax": fmax}
    k = _key(audio_path, est.name, params, sr, hop_s)
    f = cache_dir / f"f0_{est.name}_{k}.npz"
    if f.is_file() and not force:
        d = np.load(f, allow_pickle=False)
        if int(d["f0"].size) == n_frames:
            return PitchTrack(est.name, est.family, hop_s, d["f0"], d["conf"],
                              {"cache": f.name}), True
    y = load_mono(audio_path, sr)
    tr = est.estimate(y, sr, n_frames, fmin=fmin, fmax=fmax, hop_s=hop_s)
    np.savez_compressed(f, f0=tr.f0_hz, conf=tr.confidence)
    return tr, False
