# -*- coding: utf-8 -*-
"""M0-05 的测试文件：SynthV 一份、FL 两份。全是测试文件，不碰你的工程。

  out/m0_05.svp        和 M0-04 同一份乐谱（97.5 BPM · 8 个音 ·「今天的风很温柔啊」）
  out/flp_open.flp     FL 空模板的拷贝 —— 你在 FL 里开着的那个
  out/flp_render.flp   FL 空模板的另一份拷贝 —— FL 开着时，我用命令行导出的那个

.svp 的写法直接复用 M0-04 已经被 SynthV 验证过的生成器。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(HERE, "..", "m0-04-svp"))
import make_test_svp  # noqa: E402

FL_EMPTY = r"G:\FL Studio\Data\Templates\Empty\Empty.flp"


def main():
    os.makedirs(os.path.join(OUT, "render"), exist_ok=True)
    database, source = make_test_svp.voice_database()
    svp = os.path.join(OUT, "m0_05.svp")
    with open(svp, "w", encoding="utf-8") as f:
        json.dump(make_test_svp.build("m0_05", os.path.join(OUT, "render"), database), f, ensure_ascii=False)
    print(f"写出 {svp}（声库 {database.get('name')}）")
    for name in ("flp_open.flp", "flp_render.flp"):
        shutil.copyfile(FL_EMPTY, os.path.join(OUT, name))
        print(f"拷贝 {os.path.join(OUT, name)}")


if __name__ == "__main__":
    main()
