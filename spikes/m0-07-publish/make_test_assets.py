# -*- coding: utf-8 -*-
"""M0-07 第 2 步的测试素材：上传页往往要先选文件才展开表单 —— 用这些，绝不用你的真作品。

  out/test_cover.png   3000×3000 纯色封面（静态图，B站不接受动图）
  out/test_audio.wav   M0-04 那段 7.5 秒的测试人声「今天的风很温柔啊」（单声道 16-bit 44.1 kHz）
  out/test_video.mp4   封面静帧 + 测试音频，按 B站官方「关于视频上传」的规格做：
                       H.264 · yuv420p · 8bit · 关键帧每 2 秒一个（要求平均至少 10 秒一个）
                       音频 AAC 320 kbps · **48000 Hz**（从 44.1 kHz 重采样）· 立体声（声道 ≤ 2）

做完用 ffprobe 读回来，逐项核对是否真的达标 —— 做出来不等于做对了。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SRC_WAV = os.path.normpath(os.path.join(HERE, "..", "m0-04-svp", "out", "render", "m0_04_MixDown.wav"))


def run(args):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-800:])
        sys.exit(f"失败：{' '.join(args[:3])} …")
    return r.stdout


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))


def keyframe_gaps(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
               "-show_entries", "frame=pts_time", "-of", "csv=p=0", path])
    # 每行形如「0.000000,」—— 取逗号前的数字
    t = [float(x.split(",")[0]) for x in out.split() if x.split(",")[0].strip()]
    return [round(b - a, 3) for a, b in zip(t, t[1:])], len(t)


def main():
    os.makedirs(os.path.join(OUT, "screenshots"), exist_ok=True)
    cover = os.path.join(OUT, "test_cover.png")
    audio = os.path.join(OUT, "test_audio.wav")
    video = os.path.join(OUT, "test_video.mp4")

    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x2e4a62:s=3000x3000",
         "-frames:v", "1", cover])
    shutil.copyfile(SRC_WAV, audio)
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30", "-i", cover, "-i", audio,
         "-vf", "scale=1920:1920,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
         "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
         "-shortest", "-movflags", "+faststart", video])

    p = probe(video)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    a = next(s for s in p["streams"] if s["codec_type"] == "audio")
    gaps, nkey = keyframe_gaps(video)
    checks = [
        ("视频编码 H.264", v["codec_name"] == "h264", v["codec_name"]),
        ("色彩空间 yuv420", v["pix_fmt"] == "yuv420p", v["pix_fmt"]),
        ("位深 8bit", v.get("bits_per_raw_sample", "8") in ("8", 8), v.get("bits_per_raw_sample", "8")),
        ("分辨率 ≤ 4096×4096", int(v["width"]) <= 4096 and int(v["height"]) <= 4096, f"{v['width']}×{v['height']}"),
        ("关键帧平均至少 10 秒一个", bool(gaps) and max(gaps) <= 10, f"{nkey} 个关键帧，最大间隔 {max(gaps) if gaps else '—'} 秒"),
        ("音频编码 AAC", a["codec_name"] == "aac", a["codec_name"]),
        ("音频码率 ≤ 320 kbps", int(a.get("bit_rate", 0)) <= 320_000, f"{int(a.get('bit_rate', 0)) // 1000} kbps"),
        ("采样率 = 48000", a["sample_rate"] == "48000", a["sample_rate"]),
        ("声道 ≤ 2", int(a["channels"]) <= 2, a["channels"]),
    ]
    print(f"test_video.mp4：{os.path.getsize(video) / 1e6:.2f} MB · {float(p['format']['duration']):.2f} 秒")
    ok = True
    for name, passed, got in checks:
        ok &= passed
        print(f"  {'✓' if passed else '✗'} {name:24s} 实际 {got}")
    print(f"B站规格：{'全部达标' if ok else '有不达标的项'}")
    with open(os.path.join(OUT, "test_video_checks.json"), "w", encoding="utf-8") as f:
        json.dump({n: {"ok": ok_, "got": str(g)} for n, ok_, g in checks}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
