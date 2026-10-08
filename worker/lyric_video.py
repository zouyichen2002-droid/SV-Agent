# -*- coding: utf-8 -*-
r"""歌词视频（v3 视频 · 第一版，2026-10-01）：你给的图 + 逐字歌词字幕 + 轻微动效 + 你的成品音频 → 1080p 成片（mp4）。

创作者 10-01 定：先做歌词视频；只用他给的图（不生成）；剪映草稿 + 一份成片（草稿见 jianying_draft.py）。

    字幕：lyric_timing.py 出的逐字时间 → ASS（逐字变色，像卡拉 OK；一行唱完前不换行；行前 0.5 秒先出来）
    画面：图铺满 1920×1080（裁掉多的）、整首缓慢推近 1.00 → 1.08；底部压一条渐暗，字更清楚
    开头：第一句之前放标题和署名（有的话）
    编码：显卡 h264_nvenc（没有就用 libx264），AAC 320k —— B 站的收稿要求还没核实（PRD §13：要按官方资料和你的账号实操定），先用最常见的

只用 Python 自带模块 + ffmpeg（特效字幕 --fx 另要 fontTools，见 lyric_fx.py）：
    python lyric_video.py <逐字时间.json> <音频> <输出文件夹> --image 图1 [--image 图2 …] [--title 标题] [--credit 署名]
                          [--fx 可爱|凌厉|平铺|弹跳|发光|浮现|逐字出现|竖排古风] [--start 秒 --duration 秒（只出一段，试用）] [--ffmpeg ffmpeg.exe]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
W, H, FPS = 1920, 1080, 30
LEAD, TAIL = 0.5, 0.6                      # 一行提前 0.5 秒出来；唱完再留 0.6 秒（不压到下一行）
SHADE_H, SHADE_A = 420, 0.6                # 底部渐暗：420 像素高，最底下 60% 黑
FONTS = {"zh": "Microsoft YaHei", "ja": "Yu Gothic", "en": "Segoe UI"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}   # 底片也可以是视频（10-02《怪物》：创作者用别的 AI 做的 8 秒循环）


def ts(s: float) -> str:
    s = max(0.0, s)
    h, rem = divmod(int(round(s * 100)), 360000)
    m, rem = divmod(rem, 6000)
    sec, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def esc(t: str) -> str:
    return t.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def karaoke_text(line: dict, shown_at: float, lang: str) -> str:
    """一行的卡拉 OK 标签：每个单位一个 \\kf（变色时长 = 它唱多久）；单位之间的空档是不带字的 \\k；没时间的单位时长 0（跟下一个一起亮）。"""
    out, cur = [], shown_at
    sep = " " if lang == "en" else ""
    for i, u in enumerate(line["单位"]):
        text = esc(u["文字"]) + (sep if i < len(line["单位"]) - 1 else "")
        if u["开始"] is None:
            out.append(f"{{\\kf0}}{text}")
            continue
        gap = u["开始"] - cur
        if gap > 0.005:
            out.append(f"{{\\k{round(gap * 100)}}}")
        dur = max(0.0, u["结束"] - u["开始"])
        out.append(f"{{\\kf{round(dur * 100)}}}{text}")
        cur = u["开始"] + dur
    return "".join(out)


def line_windows(lines: list[dict]) -> list[tuple[float, float]]:
    """每行什么时候出来、什么时候收：行前 0.5 秒出来、唱完留 0.6 秒，**下一行出来之前一定收掉**
    （10-01：两行挨得很近时（空档不到 0.1 秒）原来会叠 0.1 秒 —— 字幕里看不出，剪映的同一条轨上不许重叠）。jianying_draft.py 也用这个。"""
    out = []
    for k, ln in enumerate(lines):
        show = ln["开始"] - LEAD
        if k > 0:
            show = max(show, min(lines[k - 1]["结束"] + 0.05, ln["开始"] - 0.05))
        hide = ln["结束"] + TAIL
        if k + 1 < len(lines):
            hide = min(hide, max(ln["结束"] + 0.05, lines[k + 1]["开始"] - LEAD))
        out.append([show, hide])
    for k in range(len(out) - 1):
        out[k][1] = min(out[k][1], out[k + 1][0])
    return [(a, b) for a, b in out]


def ass_header(lang: str, extra_styles: tuple[str, ...] = ()) -> list[str]:
    """字幕文件开头：画面大小、样式（歌词、标题、署名 + 特效字幕要的）。lyric_fx.py 也用。"""
    font = FONTS.get(lang, "Microsoft YaHei")
    return [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # 变色后（Primary）亮黄白；变色前（Secondary）半透明白；黑描边 + 轻阴影
        f"Style: Lyric,{font},76,&H0080F0FF,&H60FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,2,0,1,4,2,2,120,120,96,1",
        f"Style: Title,{font},96,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,4,0,1,5,2,5,120,120,0,1",
        f"Style: Credit,{font},48,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,2,0,1,3,1,5,120,120,0,1",
        *extra_styles,
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def title_events(lines: list[dict], title: str | None, credit: str | None) -> list[str]:
    """第一句之前：标题、署名（淡入淡出）。"""
    ev = []
    if lines and (title or credit):
        t_end = max(1.0, lines[0]["开始"] - 0.8)
        fade = "{\\fad(600,500)}"
        if title:
            ev.append(f"Dialogue: 0,{ts(0.3)},{ts(t_end)},Title,,0,0,0,,{fade}{{\\pos({W // 2},{H // 2 - 40})}}{esc(title)}")
        if credit:
            ev.append(f"Dialogue: 0,{ts(0.6)},{ts(t_end)},Credit,,0,0,0,,{fade}{{\\pos({W // 2},{H // 2 + 60})}}{esc(credit)}")
    return ev


def write_ass(timing: dict, path: pathlib.Path, title: str | None, credit: str | None) -> int:
    """「平铺」：一行一条，整行卡拉 OK 逐字变色。时间都是整首的时间（只出一段时 render 把画面的时间挪过去，字幕不用改）。"""
    lang = timing["语言"]
    lines = timing["行"]
    ev = title_events(lines, title, credit)
    for ln, (show, hide) in zip(lines, line_windows(lines)):
        show = max(show, 0.0)                 # 出来的时间早于 0 秒：从 0 秒出，卡拉 OK 也从那儿算（不然整行变色晚）
        if hide <= 0 or hide - show < 0.05:
            continue
        ev.append(f"Dialogue: 1,{ts(show)},{ts(hide)},Lyric,,0,0,0,,{{\\fad(150,200)}}{karaoke_text(ln, show, lang)}")
    path.write_text("\n".join(ass_header(lang) + ev) + "\n", encoding="utf-8-sig")
    return len(ev)


def has_nvenc(ffmpeg: str) -> bool:
    """真开一次试试（编 0.1 秒）：10-01 这台机器的 ffmpeg 9.0 列表里有 h264_nvenc，可要 610 以上的显卡驱动（本机 591）→ 一开就失败。"""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", "color=s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return False
    return r.returncode == 0


def render(ffmpeg: str, images: list[str], audio: str, ass: pathlib.Path, out: pathlib.Path, total: float,
           start: float = 0.0, duration: float | None = None, fontsdir: str | None = None, shade: bool = True,
           video_grade: str | None = None) -> list[str]:
    """一张图：整首推近 1.00 → 1.08；几张图：平均分时长、交叉淡化 1 秒（第一版先这样，段落换图以后再说）。
    视频底片：循环铺满它那一段（-stream_loop），不推近（底片自己会动）；video_grade：给视频底片加的调色（凌厉：暗角）。"""
    # 死规矩（创作者 10-04「定死规矩不要宋体」）：字幕里出现宋体一类的字体就报错、不出片
    import font_rules
    font_rules.check_ass(pathlib.Path(ass).read_text(encoding="utf-8-sig"), pathlib.Path(ass).name)
    seg = duration if duration else total - start
    n = len(images)
    per = seg / n
    frames = max(1, round(per * FPS))
    inputs, chains = [], []
    for i, img in enumerate(images):
        if pathlib.Path(img).suffix.lower() in VIDEO_EXT:
            inputs += ["-stream_loop", "-1", "-t", f"{per + (1.0 if n > 1 else 0):.3f}", "-i", img]
            chains.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,format=yuv420p"
                          + (f",{video_grade}" if video_grade else "") + f"[i{i}]")
            continue
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{per + (1.0 if n > 1 else 0):.3f}", "-i", img]
        chains.append(f"[{i}:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                      f"zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},setsar=1[i{i}]")
    if n == 1:
        last = "[i0]"
    else:
        last = "[i0]"
        for i in range(1, n):
            chains.append(f"{last}[i{i}]xfade=transition=fade:duration=1:offset={per * i - 1:.3f}[x{i}]")
            last = f"[x{i}]"
    # 只出一段（试用 / 样片）：烧字幕前把画面的时间挪到整首里的那一段，烧完再挪回 0 —— 字幕文件一直用整首的时间
    #（10-01 特效字幕：每个字的动画时间是相对它那条字幕开头算的，不能像原来那样把字幕整体往前挪、截掉开头）
    burn = f"ass=filename={ass.name}:fontsdir={fontsdir}" if fontsdir else f"ass={ass.name}"      # fontsdir：下载来的字体（不装进系统）
    sub = f"setpts=PTS+{start:.3f}/TB,{burn},setpts=PTS-STARTPTS" if start > 0 else burn
    if shade:
        # 底部从上往下渐暗（字更清楚；10-01 第一版是一块硬边的暗条，难看），再烧字幕
        chains.append(f"color=c=black:s={W}x{SHADE_H}:r={FPS},format=rgba,geq=r=0:g=0:b=0:a='255*{SHADE_A}*pow(Y/H\\,1.6)'[shade]")
        chains.append(f"{last}[shade]overlay=0:{H - SHADE_H}:shortest=1,format=yuv420p,{sub}[v]")
    else:
        # 「可爱」「凌厉」的字在画面中间、自己带描边：不压底部（可爱的参考是明亮的浅色画面；凌厉整个画面另外调暗）
        chains.append(f"{last}format=yuv420p,{sub}[v]")
    enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0"] if has_nvenc(ffmpeg) else ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-y", *inputs, "-ss", f"{start:.3f}", *(["-t", f"{duration:.3f}"] if duration else []), "-i", audio,
            "-filter_complex", ";".join(chains), "-map", "[v]", "-map", f"{n}:a", *enc, "-r", str(FPS),
            "-c:a", "aac", "-b:a", "320k", "-shortest", "-movflags", "+faststart", str(out)]
    return argv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("timing")
    ap.add_argument("audio")
    ap.add_argument("out_dir")
    ap.add_argument("--image", action="append", required=True)
    ap.add_argument("--title")
    ap.add_argument("--credit")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--name", default="歌词视频")
    ap.add_argument("--fx", default="可爱", help="字幕样式：可爱（默认，创作者 10-02 定）、凌厉、平铺（原来的整行卡拉 OK），或 lyric_fx.py 里别的特效（弹跳、发光、浮现、逐字出现、竖排古风）")
    ap.add_argument("--side", default="auto", choices=["auto", "left", "right"], help="字放哪边（可爱、凌厉）：auto = 图里空的那一边")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    a = ap.parse_args()
    timing = json.loads(pathlib.Path(a.timing).read_text(encoding="utf-8"))
    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ass = out / f"{a.name}.ass"
    probe = subprocess.run([a.ffmpeg, "-hide_banner", "-i", a.audio], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe)
    total = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else (timing["行"][-1]["结束"] + 5)
    fontsdir = None
    if a.fx == "平铺":
        n = write_ass(timing, ass, a.title, a.credit)
    else:
        import lyric_fx
        n = lyric_fx.write_fx_ass(timing, ass, a.fx, a.title, a.credit, images=a.image, total=total, side=a.side)
        need = lyric_fx.fonts_needed(a.fx, timing["语言"])
        if need:                                   # 字体拷一份到这一版的 _fonts（ASCII 名字，ffmpeg 的滤镜参数里不用转义）
            fd = out / "_fonts"
            fd.mkdir(exist_ok=True)
            for f in need:
                if not pathlib.Path(f).is_file():
                    raise SystemExit(f"找不到字体 {f}（cover_config.json 的 fonts_dir）")
                shutil.copy2(f, fd / pathlib.Path(f).name)
            fontsdir = "_fonts"
    mp4 = out / f"{a.name}.mp4"
    if mp4.exists():
        raise SystemExit(f"{mp4} 已经有了 —— 每一版写新文件")
    images = a.image
    if a.fx == "凌厉":                             # 底图先调一次（压暗、降饱和、暗角、固定的颗粒），存进这一版的 _底图\，再拿它出片
        import lyric_fx
        gd = out / "_底图"
        gd.mkdir(exist_ok=True)
        images = []
        for i, img in enumerate(a.image, 1):
            if pathlib.Path(img).suffix.lower() in VIDEO_EXT:      # 视频底片不在这里调（每一帧都在变，颗粒会让文件变得很大）：出片时只加暗角
                images.append(img)
                continue
            g = gd / f"凌厉_{i:02d}.png"
            r0 = subprocess.run([a.ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-y", "-i", img, "-vf",
                                 f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},{lyric_fx.SHARP_GRADE}",
                                 "-frames:v", "1", str(g)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r0.returncode != 0 or not g.exists():
                raise SystemExit(f"底图调不了：{img}：{r0.stderr[-300:]}")
            images.append(str(g))
    argv = render(a.ffmpeg, images, a.audio, ass, mp4, total, a.start, a.duration, fontsdir=fontsdir, shade=a.fx not in ("可爱", "凌厉"),
                  video_grade="vignette=angle=PI/4.5" if a.fx == "凌厉" else None)
    (out / f"{a.name}_ffmpeg.txt").write_text(" ".join(f'"{x}"' if " " in x else x for x in argv) + "\n", encoding="utf-8")
    log = out / f"{a.name}_ffmpeg.log"
    with open(log, "wb") as fh:
        r = subprocess.run(argv, cwd=out, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not mp4.exists():
        print(f"ffmpeg 失败（退出码 {r.returncode}），看 {log}")
        return 1
    print(f"字幕 {n} 条 → {ass}；成片 → {mp4}（{mp4.stat().st_size / 1e6:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
