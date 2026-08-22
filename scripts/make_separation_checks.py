# -*- coding: utf-8 -*-
"""生成主唱/和声分离的可听对照，让人用耳朵判分离到底成不成。

每个模型出三个文件（立体声，靠左右平衡隔离单声道听）：

  <模型>_主唱L_和声R.wav   左=主唱  右=和声
      听点：右声道里是不是真的只剩和声？主唱有没有漏过去？
  <模型>_原始L_和声R.wav   左=原始混合人声  右=和声
      听点：右边拉出来的东西，在左边听得到吗？听不到 = 分离器造的
  <模型>_原始L_主唱R.wav   左=原始混合人声  右=主唱
      听点：右边的主唱有没有把和声一起带走（那样和声轨就空了）

再对复音最密集的几个时段出短片段，不用听整首。这几个时段来自
eval/polyphony.py 的实测（RMVPE 多峰率最高的窗口）。

用法: python scripts/make_separation_checks.py [song_id]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svchain import config

SR = 44100
# 来自 eval/polyphony.py：RMVPE 多峰率最高的 10s 窗口
HOT = [(80.0, 90.0), (105.0, 115.0), (145.0, 155.0), (170.0, 180.0)]


def load(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), always_2d=True)
    if sr != SR:
        raise SystemExit(f"{path.name} 是 {sr}Hz，期望 {SR}Hz")
    return y.mean(axis=1)


def norm(x: np.ndarray, peak: float = 0.6) -> np.ndarray:
    m = float(np.abs(x).max())
    return (x / m * peak) if m > 1e-9 else x


def write(path: Path, left: np.ndarray, right: np.ndarray) -> None:
    n = min(left.size, right.size)
    a = np.stack([left[:n], right[:n]], axis=1)
    pk = float(np.abs(a).max())
    if pk > 0.99:
        a = a * (0.99 / pk)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), a, SR, subtype="PCM_16")
    print(f"    {path.name}  {n/SR:.1f}s")


def rms_db(x: np.ndarray) -> float:
    return 10.0 * np.log10(float((x ** 2).mean()) + 1e-12)


def main() -> int:
    song_id = sys.argv[1] if len(sys.argv) > 1 else "chaosheng"
    cfg = config.load()
    song = cfg.song(song_id)
    song.require("vocals")
    root = Path(__file__).resolve().parents[1] / "out" / "sep" / song_id
    if not root.is_dir():
        print(f"没有分离结果，先跑 scripts/separate_voices.py（期望 {root}）")
        return 1

    mix = load(Path(song.vocals))
    out_root = Path(__file__).resolve().parents[1] / "out" / f"listen_{song_id}" / "06_分离对照"
    print(f"原始混合人声 {Path(song.vocals).name}  电平 {rms_db(mix):.1f}dB\n")

    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        lead = backing = None
        for f in d.glob("*.wav"):
            n = f.name.lower()
            if "vocals" in n:
                lead = f
            elif "instrumental" in n:
                backing = f
        if not (lead and backing):
            print(f"=== {d.name} === 缺 stem，跳过（找到 {[f.name for f in d.glob('*.wav')]}）")
            continue
        print(f"=== {d.name} ===")
        L = load(lead)
        B = load(backing)
        n = min(mix.size, L.size, B.size)
        print(f"  主唱 {rms_db(L[:n]):6.1f}dB   和声 {rms_db(B[:n]):6.1f}dB   "
              f"差 {rms_db(L[:n])-rms_db(B[:n]):+.1f}dB")
        # 残差检查：主唱+和声 是否约等于原始（分离器有没有丢能量）
        resid = mix[:n] - (L[:n] + B[:n])
        print(f"  重构残差 {rms_db(resid):6.1f}dB"
              f"（相对原始 {rms_db(resid)-rms_db(mix[:n]):+.1f}dB）"
              + ("  ← 残差很小，两条 stem 基本是原始的完整分解"
                 if rms_db(resid) - rms_db(mix[:n]) < -20 else
                 "  ← 残差偏大，有能量既不在主唱也不在和声里"))

        mn, Ln, Bn = norm(mix[:n]), norm(L[:n]), norm(B[:n])
        od = out_root / d.name
        write(od / f"{d.name}_主唱L_和声R.wav", Ln, Bn)
        write(od / f"{d.name}_原始L_和声R.wav", mn, Bn)
        write(od / f"{d.name}_原始L_主唱R.wav", mn, Ln)
        for t0, t1 in HOT:
            i0, i1 = int(t0 * SR), min(int(t1 * SR), n)
            if i1 <= i0:
                continue
            write(od / f"热点_{t0:.0f}-{t1:.0f}s_主唱L_和声R.wav",
                  Ln[i0:i1], Bn[i0:i1])
        print()

    print(f"全部写在 {out_root}")
    print("听点：右声道拉出来的和声，在「原始L_和声R」的左声道里能不能听到。")
    print("听不到 = 分离器造出来的，不是原本存在的声音。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
