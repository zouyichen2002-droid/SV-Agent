# -*- coding: utf-8 -*-
"""M0-02 环境检查：这个独立环境装得上、载得起、跑得通吗？（PRD §14「Python 与音频依赖」）

四项检查：

1. 隔离   环境外面的第三方包一个都看不到：
          搜索路径里不能有环境以外的 site-packages 目录。
          **反向对照**：scipy 装在底座解释器（python.org 3.13）和 miniconda 里，
          librosa 装在 miniconda 里 —— 这两个在这里 import 都必须失败。
          能导入，就说明「独立环境」是假的，它在偷偷用外面的包。
2. 版本   Python 与 numpy 是锁定的版本（pyproject.toml / uv.lock）。
          也是一个对照：底座里的 numpy 是 2.2.6，这里必须是 2.5.3。
3. 能跑   用 M0-01 的 gm.dls 渲染器渲染同一份标准样本，热启动 × 5 计时。
4. 可复现 和 M0-01（miniconda · numpy 2.3.4）渲染出的 WAV 逐字节比较；
          不一样就量差多少 —— 差异本身也是要记下来的事实。

用法（在本目录）：uv run python check_env.py
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
M0_01 = os.path.normpath(os.path.join(HERE, "..", "m0-01-piano-preview"))
sys.path.insert(0, M0_01)

import numpy as np  # noqa: E402

import renderers  # noqa: E402
import sample  # noqa: E402

EXPECT_PYTHON = (3, 13)
EXPECT_NUMPY = "2.5.3"


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def read_pcm(path):
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2")


def main():
    results = {}

    # 1. 隔离
    in_venv = sys.prefix != sys.base_prefix
    # 只看 site-packages：底座的标准库路径出现在 sys.path 里是正常的，外面的第三方包才算泄漏
    root = os.path.normcase(os.path.abspath(sys.prefix))
    leaked = [p for p in sys.path if "site-packages" in p.lower()
              and not os.path.normcase(os.path.abspath(p)).startswith(root)]
    blocked = {}
    for mod in ("scipy", "librosa"):
        try:
            importlib.import_module(mod)
            blocked[mod] = False
        except ImportError:
            blocked[mod] = True
    results["隔离"] = in_venv and not leaked and all(blocked.values())
    print(f"[1 隔离]   虚拟环境 {in_venv} · 漏进来的外部包目录 {leaked or '无'} · "
          f"导入被挡住 {blocked}")
    print(f"           解释器 {sys.executable}")
    print(f"           基于   {sys.base_prefix}")

    # 2. 版本
    py_ok = sys.version_info[:2] == EXPECT_PYTHON
    np_ok = np.__version__ == EXPECT_NUMPY
    results["版本"] = py_ok and np_ok
    print(f"[2 版本]   Python {sys.version.split()[0]}（要 3.13.*：{py_ok}） · "
          f"numpy {np.__version__}（要 {EXPECT_NUMPY}：{np_ok}）")

    # 3. 能跑
    t0 = time.perf_counter()
    rend = renderers.GmDlsPiano().load()
    load_s = time.perf_counter() - t0
    notes = sample.notes_in_seconds()
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "sample_gmdls_env.wav")
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        peak, rms, clipped = renderers.write_wav(path, rend.render(notes))
        times.append(time.perf_counter() - t0)
    results["能跑"] = max(times) <= 30.0 and clipped == 0
    print(f"[3 能跑]   载入 {load_s:.3f} 秒 · 渲染 × 5：中位 {sorted(times)[2]:.3f} · 最慢 {max(times):.3f} 秒 · "
          f"峰值 {peak:.1f} / RMS {rms:.1f} dBFS · 削波 {clipped}")

    # 4. 可复现
    ref = os.path.join(M0_01, "out", "sample_gmdls.wav")
    if not os.path.exists(ref):
        results["可复现"] = None
        print(f"[4 可复现] 灰：找不到 M0-01 的参照文件 {ref}，先在 M0-01 目录跑一次 measure.py")
    else:
        same = sha256(ref) == sha256(path)
        results["可复现"] = same
        if same:
            print(f"[4 可复现] 和 M0-01 逐字节相同 · SHA-256 {sha256(path)[:16]}…")
        else:
            a, b = read_pcm(ref), read_pcm(path)
            n = min(len(a), len(b))
            d = np.abs(a[:n].astype(np.int32) - b[:n].astype(np.int32))
            print(f"[4 可复现] 和 M0-01 不是逐字节相同 · 长度 {len(a)} vs {len(b)} · "
                  f"不同的样本 {int(np.count_nonzero(d))} / {n} · 最大差 {int(d.max())} LSB（16-bit）")

    print()
    for k, v in results.items():
        print(f"  {k:4s} {'绿' if v else ('灰' if v is None else '红')}")


if __name__ == "__main__":
    main()
