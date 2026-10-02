# -*- coding: utf-8 -*-
r"""歌词视频的 Python Worker（v3 视频，2026-10-01）：一首歌 → 成片（mp4）+ 剪映草稿。几步串成一条命令，产物写进项目的 视频\vNN\。

创作者 10-01 定：先做歌词视频（图 + 逐字歌词字幕 + 轻微动效）；只用他给的图；剪映草稿 + 一份成片；
草稿放进剪映的草稿文件夹，只新建「SV-Agent_<歌名>_vNN」。测试片段他看过：「剪映能打开，字幕也跟得上」。

    检查      音频、图、工程、歌词都在；这一版的文件夹和草稿名都还没用过
    素材      他给的图和成品音频拷进 视频\vNN\素材\（剪映草稿指着这份 —— 原文件挪了、删了，草稿也不会丢素材）
    逐字时间  lyric_timing.py（vocal2midi 环境）：SV 工程 + 素材\歌词_要唱的字.txt → 每行、每个字什么时候唱
              工程默认用 rNN 里最近改过的那份 .svp（他在 SV 里改了存盘、或另存了一份，用的都是他最后动的那份）
    对齐      audio_offset.py：成品音频比工程晚几秒（伴奏两边共有，起音包络互相关）→ 字幕整体平移；
              前后差得不一样（中间剪过段落）、或者根本对不上（给错了歌）→ 不平移、提醒
    成片      lyric_video.py（ffmpeg）：图 + 逐字卡拉 OK 字幕 + 推近 + 成品音频 → 视频\vNN\<歌名>_歌词视频_vNN.mp4
    剪映草稿  jianying_draft.py（video 环境，pyJianYingDraft）→ <剪映草稿文件夹>\SV-Agent_<歌名>_vNN
    说明      视频\vNN\说明.md（最后写：有它 = 这一版做完了）；进度一行一个 JSON 在 日志\视频进度.jsonl（插件读它）；总结在 日志\视频_vNN.json

    python video_run.py <项目文件夹> --version vNN --audio <成品音频> --image <图> [--image …] [--svp <工程>] [--title …] [--credit …] [--drafts <剪映草稿文件夹>]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}   # 底片也可以是视频（循环铺满；10-02《怪物》）
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
SHIFT_MIN = 0.02             # 差不到 20 毫秒不平移


def low_priority() -> None:
    """把自己调成「低于正常」，起的子程序都跟着低。10-01 才发现原来那一行在 64 位 Python 上没生效：
    不声明参数类型时 GetCurrentProcess 的伪句柄被截成 32 位 → SetPriorityClass 返回 0、优先级还是「正常」。"""
    if os.name != "nt":
        return
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000):          # BELOW_NORMAL_PRIORITY_CLASS
        print(f"调不了优先级（错误 {ctypes.get_last_error()}），照常优先级跑", flush=True)


class StepFailed(Exception):
    def __init__(self, step: str, why: str):
        super().__init__(f"{step}：{why}")
        self.step, self.why = step, why


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def pick_svp(project: pathlib.Path) -> pathlib.Path | None:
    """rNN 文件夹（没弃用的）里最近改过的 .svp；吸格线前的备份不算。"""
    cands = [p for d in project.iterdir() if d.is_dir() and re.fullmatch(r"r\d{2,}", d.name)
             for p in d.glob("*.svp") if not p.stem.endswith("_吸格线前")]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def find_reference(project: pathlib.Path) -> pathlib.Path | None:
    """对齐用的参考：翻唱时分离出来的伴奏（成品里也是它）；没有就用原曲。"""
    log = project / "分离" / "separate_log.json"
    try:
        p = pathlib.Path(json.loads(log.read_text(encoding="utf-8"))["step1"]["instrumental"])
        if p.is_file():
            return p
    except Exception:
        pass
    p = project / "素材" / "原曲整首.wav"
    return p if p.is_file() else None


def shift_timing(t: dict, d: float) -> dict:
    """所有时间 + d 秒；挪到 0 秒以前的字不要了（成品剪掉了开头），整行都没了的记进「没出字幕的行」。"""
    keep = []
    for ln in t["行"]:
        units = []
        for u in ln["单位"]:
            if u["开始"] is not None:
                u["开始"], u["结束"] = round(u["开始"] + d, 3), round(u["结束"] + d, 3)
                if u["结束"] <= 0:
                    continue
                u["开始"] = max(0.0, u["开始"])
            units.append(u)
        timed = [u for u in units if u["开始"] is not None]
        if not timed:
            t["没出字幕的行"].append({"行": ln["行"], "文字": ln["文字"], "原因": "成品里没有这一段（剪掉了开头）"})
            continue
        ln["单位"], ln["开始"], ln["结束"] = units, min(u["开始"] for u in timed), max(u["结束"] for u in timed)
        keep.append(ln)
    t["行"] = keep
    t["统计"]["出字幕的行"] = len(keep)
    return t


def copy_inputs(out: pathlib.Path, audio: pathlib.Path, images: list[pathlib.Path]) -> tuple[pathlib.Path, list[pathlib.Path]]:
    d = out / "素材"
    d.mkdir()
    a2 = d / audio.name
    shutil.copy2(audio, a2)
    imgs = []
    for i, img in enumerate(images, 1):
        dst = d / img.name
        if dst.exists():
            dst = d / f"{i:02d}_{img.name}"
        shutil.copy2(img, dst)
        imgs.append(dst)
    return a2, imgs


class Run:
    def __init__(self, project: pathlib.Path, version: str):
        self.P, self.v = project, version
        self.logs = project / "日志"
        self.logs.mkdir(exist_ok=True)
        self.progress = self.logs / "视频进度.jsonl"
        self.t0 = time.time()
        self.steps: list[dict] = []
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def note(self, step: str, state: str, detail: str = "") -> None:
        row = {"时间": stamp(), "秒": round(time.time() - self.t0, 1), "版本": self.v, "步": step, "状态": state, "说明": detail}
        with open(self.progress, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{row['秒']:>6.1f}s] {step} {state} {detail}", flush=True)
        if state in ("完成", "失败", "跳过", "提醒"):
            self.steps.append(row)

    def run(self, step: str, argv: list) -> str:
        log = self.logs / f"视频_{self.v}_{step}.log"
        with open(log, "wb") as fh:
            fh.write(f"===== {stamp()} {' '.join(map(str, argv))}\n".encode("utf-8"))
            fh.flush()
            r = subprocess.run([str(x) for x in argv], cwd=HERE, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=self.env)
        text = log.read_text(encoding="utf-8", errors="replace")
        if r.returncode != 0:
            tail = [x for x in text.strip().splitlines() if x.strip()][-1:] or [""]
            raise StepFailed(step, f"退出码 {r.returncode}：{tail[0][:200]}（全文看 {log}）")
        return text


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="一首歌 → 歌词视频（成片 + 剪映草稿）")
    ap.add_argument("project")
    ap.add_argument("--version", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--image", action="append", required=True)
    ap.add_argument("--svp", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--credit", default=None)
    ap.add_argument("--fx", default="可爱", help="字幕样式：可爱（默认，创作者 10-02 定）、凌厉、平铺（原来的整行卡拉 OK）、弹跳、发光、浮现、逐字出现、竖排古风（lyric_fx.py）")
    ap.add_argument("--drafts", default=None, help="剪映的草稿文件夹（插件传；不给用 cover_config.json 的 jianying_drafts）")
    ap.add_argument("--side", default="auto", choices=["auto", "left", "right"], help="字放哪边（可爱、凌厉）：auto = 图里空的那一边")
    ap.add_argument("--config", default=str(HERE / "cover_config.json"))
    a = ap.parse_args()
    low_priority()
    cfg = json.loads(pathlib.Path(a.config).read_text(encoding="utf-8"))
    project = pathlib.Path(a.project).resolve()
    if not (project / "sv-project.json").exists():
        print(f"{project} 不是项目（没有 sv-project.json）")
        return 2
    if not re.fullmatch(r"v\d{2,}", a.version):
        print("版本号要是 v01、v02 这样")
        return 2
    r = Run(project, a.version)
    out = project / "视频" / a.version
    draft_name = f"SV-Agent_{project.name}_{a.version}"
    title = a.title if a.title is not None else f"《{project.name}》"
    credit = a.credit or None
    warnings: list[str] = []
    r.note("开始", "开始", f"《{project.name}》歌词视频 {a.version}")
    try:
        audio = pathlib.Path(a.audio)
        if not audio.is_file() or audio.suffix.lower() not in AUDIO_EXT:
            raise StepFailed("检查", f"成品音频不对：{audio}（要存在、是 {'/'.join(sorted(AUDIO_EXT))}）")
        images = [pathlib.Path(x) for x in a.image]
        bad = [str(x) for x in images if not x.is_file() or x.suffix.lower() not in IMAGE_EXT | VIDEO_EXT]
        if bad:
            raise StepFailed("检查", f"画面不对：{bad}（要存在、是图 {'/'.join(sorted(IMAGE_EXT))} 或视频 {'/'.join(sorted(VIDEO_EXT))}）")
        svp = pathlib.Path(a.svp) if a.svp else pick_svp(project)
        if svp is None or not svp.is_file():
            raise StepFailed("检查", f"找不到 SV 工程（{svp or '项目里没有翻唱出来的 rNN'}）")
        lyrics = project / "素材" / "歌词_要唱的字.txt"
        if not lyrics.is_file():
            raise StepFailed("检查", f"找不到 {lyrics}（翻唱时生成的；没有歌词就没法出字幕）")
        fx_ok = ("可爱", "凌厉", "平铺", "弹跳", "发光", "浮现", "逐字出现", "竖排古风")
        if a.fx not in fx_ok:
            raise StepFailed("检查", f"没有这种字幕样式：{a.fx}（有：{'、'.join(fx_ok)}）")
        if out.exists():
            raise StepFailed("检查", f"{out} 已经有了 —— 每一版写新文件夹，另开一版")
        drafts = pathlib.Path(a.drafts or cfg["jianying_drafts"])
        if not drafts.is_dir():
            raise StepFailed("检查", f"剪映草稿文件夹不在：{drafts}")
        if (drafts / draft_name).exists():
            raise StepFailed("检查", f"剪映草稿文件夹里已经有「{draft_name}」了 —— 不覆盖")
        out.mkdir(parents=True)
        n_vid = sum(1 for x in images if x.suffix.lower() in VIDEO_EXT)
        r.note("检查", "完成", f"工程 {svp.parent.name}\\{svp.name}；音频 {audio.name}；画面 {len(images)} 个" + (f"（{n_vid} 个是视频，循环铺满）" if n_vid else ""))

        audio, images = copy_inputs(out, audio, images)
        r.note("素材", "完成", f"图和成品音频拷进 视频\\{a.version}\\素材\\（剪映草稿指着这份）")

        timing = out / "逐字时间.json"
        r.note("逐字时间", "开始", "SV 工程里每个音 → 对回歌词原文的字")
        r.run("逐字时间", [cfg["vocal2midi_python"], HERE / "lyric_timing.py", svp, lyrics, timing])
        t = json.loads(timing.read_text(encoding="utf-8"))
        s = t["统计"]
        r.note("逐字时间", "完成", f"{t['语言']}：出字幕 {s['出字幕的行']} 行；{s['有时间的单位']} / {s['单位']} 个字（词）有时间"
               + (f"；{len(t['没出字幕的行'])} 行没对上、没出字幕（第 {'、'.join(str(x['行']) for x in t['没出字幕的行'])} 行）" if t["没出字幕的行"] else ""))

        ref = find_reference(project)
        if ref is None:
            align = {"说明": "项目里没有伴奏、也没有原曲，没法核对成品音频和工程对不对得上；字幕按工程的时间"}
            warnings.append(align["说明"])
            r.note("对齐", "跳过", align["说明"])
        else:
            r.note("对齐", "开始", f"成品音频 对 {ref.name}")
            sys.path.insert(0, str(HERE))
            import audio_offset as O
            try:
                res = O.offset(cfg["ffmpeg"], str(audio), str(ref))
            except Exception as e:
                raise StepFailed("对齐", f"算不出来：{e}")
            align = {"参考": str(ref), **{k: v for k, v in res.items() if k != "分段"}, "说明": O.describe(res)}
            raw = out / "逐字时间_工程时间.json"
            if res["可信"] and abs(res["晚秒"]) >= SHIFT_MIN:
                shutil.copy2(timing, raw)
                t = shift_timing(t, res["晚秒"])
                align["平移秒"] = res["晚秒"]
            t["对齐"] = align
            timing.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
            if not res["可信"] or res["对不上的段"]:
                warnings.append(align["说明"])
            r.note("对齐", "提醒" if (not res["可信"] or res["对不上的段"]) else "完成", align["说明"])

        name = f"{project.name}_歌词视频_{a.version}"
        r.note("成片", "开始", "ffmpeg：图 + 逐字字幕 + 推近 + 成品音频 → 1080p mp4")
        argv = [sys.executable, HERE / "lyric_video.py", timing, audio, out, "--name", name, "--title", title, "--fx", a.fx, "--side", a.side, "--ffmpeg", cfg["ffmpeg"]]
        for img in images:
            argv += ["--image", img]
        if credit:
            argv += ["--credit", credit]
        r.run("成片", argv)
        mp4 = out / f"{name}.mp4"
        if not mp4.exists():
            raise StepFailed("成片", f"没出 {mp4.name}")
        r.note("成片", "完成", f"{mp4.name}（{mp4.stat().st_size / 1e6:.1f} MB）")

        r.note("剪映草稿", "开始", f"pyJianYingDraft 新建「{draft_name}」")
        argv = [cfg["video_python"], HERE / "jianying_draft.py", timing, audio, draft_name, "--drafts", drafts, "--title", title, "--fx", a.fx, "--side", a.side]
        for img in images:
            argv += ["--image", img]
        if credit:
            argv += ["--credit", credit]
        r.run("剪映草稿", argv)
        if not (drafts / draft_name / "draft_content.json").exists():
            raise StepFailed("剪映草稿", "草稿文件没写出来")
        r.note("剪映草稿", "完成", str(drafts / draft_name))

        lines = [f"# 《{project.name}》歌词视频 {a.version}", "", f"- 生成：{stamp()}（video_run.py，一条命令跑完）",
                 f"- 成片：`{mp4.name}`（1080p 30 帧；字幕样式「{a.fx}」{'：整行逐字变色' if a.fx == '平铺' else '：每个字按自己唱的时间动'}；"
                 + ("视频底片循环铺满" if all(pathlib.Path(x).suffix.lower() in VIDEO_EXT for x in a.image)
                    else "图缓慢推近、视频底片循环" if any(pathlib.Path(x).suffix.lower() in VIDEO_EXT for x in a.image) else "整首缓慢推近") + "）",
                 f"- 剪映草稿：「{draft_name}」（在剪映的草稿列表里；"
                 + ("歌词一句一段：快乐体、彩色描边带光、逐字显影（唱到哪显到哪，匀速）、向左模糊出场；没有成片那样错落的排法"
                    if a.fx == "可爱" and t["语言"] == "zh" else
                    f"歌词一句一段：{'毛笔楷书（剪映的「Aa霸道楷」）' if t['语言'] == 'zh' else '剪映的默认字体（霸道楷没有假名）'}、白字红影、打字机（唱到哪出到哪，匀速）、闪一下退场；没有成片那样的大字 + 竖排 + 刀痕"
                    if a.fx == "凌厉" and t["语言"] in ("zh", "ja") else "歌词一行一段、卡拉OK 匀速变色"
                    + ("" if a.fx == "平铺" else f"；「{a.fx}」只在成片里，剪映里要特效就用它自带的文字动画"))
                 + " —— 逐字精确的在成片里）",
                 f"- 字幕时间：从 `{svp}` 来（{t['语言']}；{t['统计']['出字幕的行']} 行出字幕）"
                 + (f"；没出字幕的 {len(t['没出字幕的行'])} 行：第 {'、'.join(str(x['行']) for x in t['没出字幕的行'])} 行" if t["没出字幕的行"] else ""),
                 f"- 对齐：{align['说明']}",
                 f"- 音频：`{a.audio}`（拷了一份在 素材\\）", "- 画面：" + "、".join(f"`{x}`" + ("（视频，循环）" if pathlib.Path(x).suffix.lower() in VIDEO_EXT else "") for x in a.image) + ("" if a.side == "auto" else f"；字放{'左' if a.side == 'left' else '右'}边（指定的）"),
                 f"- 标题：{title}" + (f"；署名：{credit}" if credit else "；没放署名"), ""]
        if warnings:
            lines += ["**要看一下：**", *[f"- {w}" for w in warnings], ""]
        lines.append("想改字体、配色、动效：直接在剪映里改那份草稿；要换图 / 换音频 / 字幕时间不对：跟 Agent 说，另出一版。")
        (out / "说明.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except StepFailed as e:
        r.note(e.step, "失败", e.why)
        (r.logs / f"视频_{a.version}.json").write_text(json.dumps({"结果": "失败", "步": e.step, "原因": e.why, "各步": r.steps}, ensure_ascii=False, indent=1), encoding="utf-8")
        return 1
    total = round(time.time() - r.t0)
    summary = {"结果": "完成", "总秒": total, "版本": a.version, "成片": str(mp4), "剪映草稿": str(drafts / draft_name), "工程": str(svp),
               "语言": t["语言"], "字幕行": t["统计"]["出字幕的行"], "没出字幕的行": [x["行"] for x in t["没出字幕的行"]],
               "对齐": align["说明"], "提醒": warnings, "各步": r.steps}
    (r.logs / f"视频_{a.version}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    r.note("结束", "完成", f"共 {total // 60} 分 {total % 60} 秒 → {mp4.name} + 剪映草稿「{draft_name}」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
