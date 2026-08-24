# -*- coding: utf-8 -*-
"""分析一条渲染出来的混音：电平、headroom、低中高频段平衡。

## 2026-08-23 重写：去掉 FL MCP 依赖

原版从 `fl_studio_mcp.tools.audio` 借两个函数，代价是依赖一个隔离的
conda env + 一个 48MB 的第三方仓库。清点之后发现不值：

- `analyze_bands`（rms/peak/三段占比）就是一次 STFT，几十行，自己写
- `audio_analyze`（tempo/key）**两个估计都不可靠**：76 BPM 的歌它报 152
  （倍频误判），key 的文档自己写着「~60-80% 准确」。
  而我们的 tempo 和 key 本来是已知的（写在 `project.json` 里），不需要估计

创作者拍板把 FL 桥从第一版逻辑里删除，这个脚本是最后一处依赖，一起去掉。
现在整条链**不依赖 loopMIDI、不依赖 FL MCP、不需要 FL 开着**。

分析实现在 `svagent.audio`，`step5_assemble.py` 用的是同一个模块 ——
两个入口各自实现同一段分析必然产出两个不同数字，那个坑在对齐验证时踩过。

用法:
    python scripts/analyze_mix.py <混音.wav>
    python scripts/analyze_mix.py <混音.wav> --ref <参考曲.wav>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))
sys.stdout.reconfigure(encoding="utf-8")

from svagent import audio as A


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mix", help="要分析的 wav")
    ap.add_argument("--ref", default=None, help="参考曲 wav（可选）")
    a = ap.parse_args()

    mix = Path(a.mix).resolve()
    if not mix.exists():
        raise SystemExit(f"找不到 {mix}")
    st = A.analyze(mix)
    print("=" * 66)
    print(f"混音　{mix}")
    print("=" * 66)
    print(A.report(st))

    if a.ref:
        ref = Path(a.ref).resolve()
        if not ref.exists():
            raise SystemExit(f"找不到 {ref}")
        rt = A.analyze(ref)
        print()
        print("=" * 66)
        print(f"参考　{ref}")
        print("=" * 66)
        print(A.report(rt))
        print("\n差值（混音 − 参考）：")
        print(A.diff(st, rt))
        print("\n  差值比绝对值可靠 —— 参考曲替你定义了这个风格该是什么样。")

    print("\n" + "=" * 66)
    print("提醒：频段占比只在真实音源渲染的音频上有意义。")
    print("正弦预览测出低频占 90%+ 是正弦没有泛音，不是编排问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
