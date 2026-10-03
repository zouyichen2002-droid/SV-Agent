# -*- coding: utf-8 -*-
r"""歌词视频的剪映草稿（v3 视频 · 第一版，2026-10-01）：和成片同一套时间 —— 你在剪映里打开接着改（换字体、加特效、调动效）。

创作者 10-01 定：剪映草稿 + 一份成片；草稿放进剪映的草稿文件夹，只新建「SV-Agent_<歌名>_vNN」，不碰他已有的草稿。
用 pyJianYingDraft 0.3.0（Apache-2.0，创作者 10-01 同意下载，装在 E:\sv-agent-data\envs\video）新建草稿 —— 新版剪映的草稿是加密的，
改已有草稿要解密，**新建不用**；这台机器的剪映 10.7 打开过测试草稿，创作者 10-01 看过：「剪映能打开，字幕也跟得上」。

    画面轨：你给的图，整首缓慢推近 1.00 → 1.08（关键帧）；几张图就平均分
    音频轨：你的成品音频
    歌词轨：一行一段（时间和成片一样：行前 0.5 秒出来）；「卡拉OK」入场动画从出来到这一行唱完匀速变色
            （逐字精确的变色在成片里；剪映里是一行匀速的 —— 剪映的卡拉OK动画不能逐字设时间）
    标题轨、署名轨：第一句之前放标题和署名（有的话；两条轨 —— 同一条轨上的片段不许重叠）

先在内存里把整份草稿做完（读图、读音频、排片段出错都在这一步停），最后才在草稿文件夹里建「SV-Agent_…」写盘：
剪映的草稿文件夹里不会留下写了一半的草稿（10-01 第一次试时留过一个）。

必须用 video 环境跑：
    E:/sv-agent-data/envs/video/Scripts/python.exe jianying_draft.py <逐字时间.json> <音频> <草稿名> --image 图 [--image …]
        [--drafts "G:/JianyingPro Drafts"] [--title 标题] [--credit 署名] [--start 秒 --duration 秒]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pyJianYingDraft as draft
from pyJianYingDraft import ClipSettings, KeyframeProperty, ScriptFile, TextBorder, TextIntro, TextOutro, TextShadow, TextStyle, Timerange, TrackSpec, TrackType
from pyJianYingDraft.metadata.font_meta import FontType

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lyric_video import line_windows  # noqa: E402  和成片同一套显示时间（只用 Python 自带模块，video 环境里也能用）

sys.stdout.reconfigure(encoding="utf-8")
SEC = 1_000_000
W, H, FPS = 1920, 1080, 30
ZOOM_TO = 1.08
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


def us(s: float) -> int:
    return max(0, int(round(s * SEC)))


CUTE_RGB = [(0xF5, 0xA0, 0x4F), (0xF4, 0x7B, 0xAA), (0xA0, 0x7C, 0xF0), (0x5A, 0xA8, 0xF0)]   # 和成片的「可爱」一样：橙、粉、紫、蓝轮着换


def cute_rows(ln: dict, lang: str) -> str:
    """「可爱」：照成片一样在唱的停顿处换行（lyric_rows.phrase_rows）；剪映里一句一段，没法像成片那样一个字一个字地错落、放大短行。"""
    from lyric_rows import phrase_rows, unit_times
    units = ln["单位"]
    sep = " " if lang == "en" else ""
    return "\n".join(sep.join(units[i]["文字"] for i in row) for row in phrase_rows(ln, unit_times(units), lang))


def build(timing: dict, audio: str, images: list[str], title: str | None, credit: str | None,
          start: float = 0.0, duration: float | None = None, fx: str = "平铺", side: str = "auto") -> tuple[ScriptFile, dict]:
    """整份草稿在内存里做好：先排好每条轨的片段（整数微秒的起止，同一条轨上不重叠），再一起放进去。
    fx = 可爱（10-02）：剪映自带的「快乐体」、白字 + 每句轮着换色的描边 + 同色光（阴影：不偏移、扩散大）、放在图里空的那一边、往右上翘 6°；
    「逐字显影」（入场时长 = 这一句唱的时间：唱到哪显到哪，匀速）+「向左模糊」出场 —— 尽量和成片对上；其余样式还是卡拉OK。"""
    audio_mat = draft.AudioMaterial(audio)
    total = duration if duration else audio_mat.duration / SEC - start
    plan: dict[str, list] = {"画面": [], "音频": [], "歌词": [], "标题": [], "署名": []}

    # 画面：平均分给每张图（边界取整数微秒，前一张的尾 = 后一张的头）；每张从 1.00 推近到 1.08
    # 视频底片（10-02《怪物》，8 秒循环）：剪映不会自己循环 → 在它那一段里一节一节接起来（每节是整段视频，最后一节截短），不推近
    n = len(images)
    cuts = [us(total * i / n) for i in range(n + 1)]
    for i, img in enumerate(images):
        if pathlib.Path(img).suffix.lower() in VIDEO_EXT:
            mat = draft.VideoMaterial(img)
            t = cuts[i]
            while t < cuts[i + 1]:
                d = min(mat.duration, cuts[i + 1] - t)
                plan["画面"].append(draft.VideoSegment(mat, Timerange(t, d), source_timerange=Timerange(0, d)))
                t += d
            continue
        seg = draft.VideoSegment(img, Timerange(cuts[i], cuts[i + 1] - cuts[i]))
        seg.add_keyframe(KeyframeProperty.uniform_scale, 0, 1.0)
        seg.add_keyframe(KeyframeProperty.uniform_scale, seg.duration, ZOOM_TO)
        plan["画面"].append(seg)

    # 音频（只出一段时从 start 截）
    plan["音频"].append(draft.AudioSegment(audio_mat, Timerange(0, us(total)), source_timerange=Timerange(us(start), us(total))))

    style = TextStyle(size=9.0, bold=True, color=(1.0, 1.0, 1.0), align=1)
    border = TextBorder(color=(0.06, 0.06, 0.06), width=40.0)
    pos = ClipSettings(transform_y=-0.78)
    lines = timing["行"]
    cute = fx == "可爱" and timing["语言"] == "zh"
    sharp = fx == "凌厉" and timing["语言"] in ("zh", "ja")         # 日语凌厉：剪映的默认字体（霸道楷没有假名）
    if cute or sharp:
        from image_side import line_sides, text_area
        sides = [side] * len(lines) if side in ("left", "right") else line_sides(lines, images, total + start)
        # 和成片一样放在那一边能放字的范围里（左 60–860 / 右 1060–1860 像素）：放在正中，超过范围的宽度剪映自己换行
        area_x = {s_: ((text_area(s_)[0] + text_area(s_)[1]) / 2 - W / 2) / (W / 2) for s_ in ("left", "right")}
        area_w = (text_area("left")[1] - text_area("left")[0]) / W
    for k, (ln, (show, hide)) in enumerate(zip(lines, line_windows(lines))):
        s, e = show - start, hide - start
        if e <= 0 or s >= total:
            continue
        s, e = max(0.0, s), min(total, e)
        if e - s < 0.2:
            continue
        a, b = us(s), us(e)
        text = " ".join(u["文字"] for u in ln["单位"]) if timing["语言"] == "en" else ln["文字"].replace(" ", "")
        sung = max(0.3, min(e, ln["结束"] - start) - s)          # 从出来到这一行唱完：卡拉OK 匀速变色
        if cute:
            rgb = tuple(c / 255 for c in CUTE_RGB[k % len(CUTE_RGB)])
            light = tuple(0.35 + 0.65 * c for c in rgb)
            side_x = area_x[sides[k]]
            seg = draft.TextSegment(cute_rows(ln, timing["语言"]), Timerange(a, b - a), font=FontType.快乐体,
                                    style=TextStyle(size=12.0, color=(1.0, 1.0, 1.0), align=1, line_spacing=2, auto_wrapping=True, max_line_width=area_w),
                                    border=TextBorder(color=rgb, width=60.0), shadow=TextShadow(color=light, alpha=0.85, diffuse=40.0, distance=0.0),
                                    clip_settings=ClipSettings(transform_x=side_x, transform_y=0.14, rotation=-6.0))
            seg.add_animation(TextIntro.逐字显影, duration=min(us(sung), b - a))
            seg.add_animation(TextOutro.向左模糊, duration=min(us(0.35), b - a))
        elif sharp:                                         # 凌厉：剪映的「Aa霸道楷」、白字黑边红影；打字机（唱到哪出到哪）、闪一下退场
            side_x = area_x[sides[k]]
            seg = draft.TextSegment(cute_rows(ln, timing["语言"]), Timerange(a, b - a), font=FontType.Aa霸道楷 if timing["语言"] == "zh" else None,
                                    style=TextStyle(size=15.0, color=(1.0, 1.0, 1.0), align=1, line_spacing=2, auto_wrapping=True, max_line_width=area_w),
                                    border=TextBorder(color=(0.05, 0.05, 0.05), width=30.0),
                                    shadow=TextShadow(color=tuple(c / 255 for c in (0xE5, 0x24, 0x3B)), alpha=1.0, diffuse=0.0, distance=8.0, angle=-45.0),
                                    clip_settings=ClipSettings(transform_x=side_x, transform_y=0.08))
            seg.add_animation(TextIntro.打字机_I, duration=min(us(sung), b - a))
            seg.add_animation(TextOutro.闪动, duration=min(us(0.2), b - a))
        else:
            seg = draft.TextSegment(text, Timerange(a, b - a), style=style, border=border, clip_settings=pos)
            seg.add_animation(TextIntro.卡拉OK, duration=min(us(sung), b - a))
        plan["歌词"].append(seg)
    if lines and (title or credit) and start <= 0.3:
        end = us(max(1.0, lines[0]["开始"] - 0.8))
        if title:
            plan["标题"].append(draft.TextSegment(title, Timerange(us(0.3), end - us(0.3)), style=TextStyle(size=14.0, bold=not cute, align=1),
                                                font=FontType.快乐体 if cute else None,
                                                border=TextBorder(color=tuple(c / 255 for c in CUTE_RGB[0]), width=60.0) if cute else border,
                                                clip_settings=ClipSettings(transform_y=0.08)))
        if credit:
            plan["署名"].append(draft.TextSegment(credit, Timerange(us(0.6), end - us(0.6)), style=TextStyle(size=7.0, align=1),
                                                border=border, clip_settings=ClipSettings(transform_y=-0.12)))

    for name, segs in plan.items():                              # 同一条轨不许重叠：自己先查一遍，说清是哪两段
        segs.sort(key=lambda x: x.start)
        for p, q in zip(segs, segs[1:]):
            if p.start + p.duration > q.start:
                raise SystemExit(f"{name}轨里两段重叠：{p.start / SEC:.3f}–{(p.start + p.duration) / SEC:.3f} 秒 和 {q.start / SEC:.3f} 秒起的")

    script = ScriptFile(W, H, FPS, True)
    kinds = {"画面": TrackType.video, "音频": TrackType.audio}
    for name in plan:
        script.append_track(TrackSpec(kinds.get(name, TrackType.text), name))
    for name, segs in plan.items():
        for seg in segs:
            script.add_segment(seg, name)
    return script, {"秒": round(total, 1), "图": n, "歌词段": len(plan["歌词"]), "标题": bool(plan["标题"]), "署名": bool(plan["署名"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("timing")
    ap.add_argument("audio")
    ap.add_argument("name")
    ap.add_argument("--image", action="append", required=True)
    ap.add_argument("--drafts", default="G:/JianyingPro Drafts")
    ap.add_argument("--title")
    ap.add_argument("--credit")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--fx", default="可爱", help="字幕样式（默认可爱）：「可爱」「凌厉」在剪映里另排（可爱：快乐体彩边逐字显影；凌厉：霸道楷红影打字机）；别的都是卡拉OK")
    ap.add_argument("--side", default="auto", choices=["auto", "left", "right"], help="字放哪边（可爱、凌厉）")
    a = ap.parse_args()
    if not a.name.startswith("SV-Agent_"):
        raise SystemExit("草稿名要以 SV-Agent_ 开头（创作者 10-01：只新建自己的、不碰他已有的）")
    timing = json.loads(pathlib.Path(a.timing).read_text(encoding="utf-8"))
    folder = draft.DraftFolder(a.drafts)
    if folder.has_draft(a.name):
        raise SystemExit(f"剪映草稿文件夹里已经有「{a.name}」了 —— 不覆盖，换个版本号")
    script, info = build(timing, a.audio, a.image, a.title, a.credit, a.start, a.duration, fx=a.fx, side=a.side)
    target = folder.create_draft(a.name, W, H, FPS, allow_replace=False)      # 这时才建文件夹（草稿元信息模板）
    script.dump(target.save_path)
    path = pathlib.Path(a.drafts) / a.name
    print(f"剪映草稿 → {path}（{info['秒']} 秒，图 {info['图']} 张，歌词 {info['歌词段']} 段"
          f"{'，标题' if info['标题'] else ''}{'，署名' if info['署名'] else ''}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
