# -*- coding: utf-8 -*-
r"""字放图里哪一边（v3 视频，2026-10-02）：成片的「可爱」字幕（lyric_fx.py）和剪映草稿（jianying_draft.py）共用。

图按成片的样子铺满 1920×1080（多的裁掉），缩成 192×108，比左右各 45% 的明暗变化（相邻像素差的平均）：变化小的那边空、放字。
只用 Pillow + numpy（G:/miniconda 和 video 环境里都有）。
"""
from __future__ import annotations

W, H = 1920, 1080


VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


def first_frame(video: str) -> str:
    """视频的第一帧存成临时 PNG（用 cover_config.json 里的 ffmpeg）。"""
    import json, pathlib, subprocess, tempfile
    ff = json.loads((pathlib.Path(__file__).resolve().parent / "cover_config.json").read_text(encoding="utf-8"))["ffmpeg"]
    out = pathlib.Path(tempfile.mkdtemp()) / "第一帧.png"
    subprocess.run([ff, "-hide_banner", "-v", "error", "-y", "-i", video, "-frames:v", "1", str(out)], check=True)
    return str(out)


def calm_side(image: str | None) -> str:
    """'left' 或 'right'；没有图就放左边；视频看第一帧。
    10-02《怪物》的底片（人物在右、左边是城市灯光）判的是左边 —— 对的（我先看缩略图以为人物在左、判错了，其实是我看错）。
    判不对的图（比如人物在两边都有细节的地方）创作者 / Agent 可以指定 side。"""
    if not image:
        return "left"
    import numpy as np
    from PIL import Image
    import pathlib
    if pathlib.Path(image).suffix.lower() in VIDEO_EXT:
        image = first_frame(image)
    im = Image.open(image).convert("L")
    r = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * r)), max(H, round(im.height * r))))
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    a = np.asarray(im.crop((x0, y0, x0 + W, y0 + H)).resize((192, 108)), dtype=float)
    g = np.abs(np.diff(a, axis=1))[:-1, :] + np.abs(np.diff(a, axis=0))[:, :-1]
    return "left" if g[:, :86].mean() <= g[:, 105:].mean() else "right"


def line_sides(lines: list[dict], images: list[str] | None, total: float | None) -> list[str]:
    """每句放哪边：这句唱的时候是哪张图（几张图平均分整首，和成片一样），放那张图空的那一边。"""
    if not images:
        return ["left"] * len(lines)
    per = (total or (lines[-1]["结束"] + 5)) / len(images)
    sides = [calm_side(img) for img in images]
    return [sides[min(len(images) - 1, int(max(0.0, ln["开始"]) // per))] for ln in lines]
