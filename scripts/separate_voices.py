# -*- coding: utf-8 -*-
"""把多声部人声 stem 拆成 主唱 / 和声 两条。

输入是 **Demucs 已经分离出来的 vocals stem**（工程里的轨 3），不是原始混音。
所以这是两级分离：混音 → vocals（Demucs） → 主唱 + 和声（karaoke 模型）。
两级的误差会累积，这一点在 ADR 里要写清。

karaoke 模型的输出命名有个坑：它的 `vocals` = **主唱**，`instrumental` = **和声/伴唱**。
不是「人声 / 伴奏」。

**刻意跑多个不同架构的模型**：分离结果不能用分离器自己验。
  mel_band_roformer_karaoke_gabox   Transformer   vocals SDR 8.69（最高）
  UVR_MDXNET_KARA_2                 ONNX 卷积     vocals SDR 5.43
两者若在同一时段给出一致的主唱/和声划分，可信度远高于单模型。

用法:
    python scripts/separate_voices.py                 # 跑默认两个模型
    python scripts/separate_voices.py --models a b     # 指定
    python scripts/separate_voices.py --list           # 只列可用 karaoke 模型
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import config

DEFAULT_MODELS = [
    "mel_band_roformer_karaoke_gabox.ckpt",
    "UVR_MDXNET_KARA_2.onnx",
]


def patch_librosa_get_duration() -> str:
    """audio-separator 0.44.5 用了 librosa 已删除的 `get_duration(filename=...)`。

    librosa 0.10 把该参数改名为 `path`，1.0.0 里 `filename` 直接不存在，
    于是**推理全部跑完之后**在写文件那一步炸掉（common_separator.py:292）。

    处理方式的取舍：
    - 降 librosa —— 不行，整条管线（RMVPE 前端、activity、音符构建）都依赖 1.0.0
    - 改 site-packages 里的第三方文件 —— 能修但重装就没了，且不留痕迹
    - **在自己进程里包一层 shim** —— 只影响本进程，可见、可撤、不动别人的文件

    选第三个。
    """
    import librosa

    orig = librosa.get_duration
    if getattr(orig, "_svagent_shim", False):
        return "已打过"

    def shim(*a, **kw):
        if "filename" in kw:
            kw["path"] = kw.pop("filename")
        return orig(*a, **kw)

    shim._svagent_shim = True
    librosa.get_duration = shim
    # audio_separator 里是 `import librosa` 后按属性访问，改模块属性即可生效
    return "已注入"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default="chaosheng")
    ap.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    print(f"librosa.get_duration 兼容 shim: {patch_librosa_get_duration()}")
    from audio_separator.separator import Separator

    cfg = config.load()
    song = cfg.song(a.song)
    song.require("vocals")
    root = Path(__file__).resolve().parents[1] / "out" / "sep" / a.song
    models_dir = cfg.models_dir / "separator"
    models_dir.mkdir(parents=True, exist_ok=True)

    if a.list:
        sep = Separator(model_file_dir=str(models_dir), log_level=40)
        for arch, mm in sep.list_supported_model_files().items():
            for name, info in mm.items():
                if "kara" in str(name).lower():
                    fn = info.get("filename") if isinstance(info, dict) else info
                    sdr = ""
                    if isinstance(info, dict):
                        v = (info.get("scores") or {}).get("vocals") or {}
                        if v.get("SDR"):
                            sdr = f"  vocals SDR {v['SDR']:.2f}"
                    print(f"  [{arch:5}] {fn}{sdr}")
        return 0

    print(f"输入 {song.vocals}")
    print(f"模型目录 {models_dir}")
    print(f"输出根目录 {root}\n")

    for m in a.models:
        tag = Path(m).stem
        out = root / tag
        out.mkdir(parents=True, exist_ok=True)
        print(f"=== {m} ===")
        t0 = time.perf_counter()
        sep = Separator(model_file_dir=str(models_dir), output_dir=str(out),
                        output_format="WAV", log_level=40)
        sep.load_model(model_filename=m)
        files = sep.separate(str(song.vocals))
        el = time.perf_counter() - t0
        print(f"  用时 {el:.1f}s")
        for f in files:
            p = out / f if not Path(f).is_absolute() else Path(f)
            size = p.stat().st_size / 1e6 if p.exists() else float("nan")
            print(f"  {p.name}   {size:.1f} MB")
        print()

    print("karaoke 模型的 vocals=主唱、instrumental=和声/伴唱，别按字面理解。")
    print("下一步：scripts/make_listening_checks.py 之外单独出分离对照，人工试听确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
