# -*- coding: utf-8 -*-
r"""给 SV 工程加八度和声（v3，2026-10-02）：主轨在指定段落的音复制一份、移一个八度，放成新轨 —— 不改原来的任何轨。

创作者 10-02（《怪物》）：「之前那个svg忘记加和声了，正好我们现在也解决一下和声的问题」→「这样，和声就先直接在歌曲的某些部分加8度的和声吧」。
八度和声 = 主旋律原样上 / 下一个八度（不是另编旋律）；放哪几段由调用的人定（这首放的是歌词重复、原曲那里也有叠唱的两段副歌）。

    下八度、上八度各一条轨；--on 定默认开哪条，另一条静音（在 SV 里点开就能比）；音量比主轨低 --gain 分贝
    复制的音：起止、歌词、音素、属性（日语跨语种那些）都原样带上，只改音高；新的 uuid
    时间换算照工程自己的速度表（blick → 秒）；音的开头落在 [开始, 结束) 里才复制，不放宽
    （第一版两头各放宽 0.05 秒，《怪物》第二段多带了上一句最后一个音 → 去掉了；每段两头复制了哪个音、紧挨着没复制的是哪个，都打出来核对）

    python add_octave_harmony.py <工程.svp> <新工程.svp> --section 40.1-55.7 [--section …] [--on below|above] [--gain -6] [--track 主轨名]
    python add_octave_harmony.py <工程.svp> <新工程.svp> --lines 14-18,44-48 [--lyrics 歌词_要唱的字.txt] [--readme]
        （按句子：用做字幕那套代码对出每句唱的起止，取第一句第一个字到最后一句最后一个字。
          创作者 10-03：和声不进 DSH、不做成通用技能 —— 他说哪几句要加，我手动跑）
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import secrets
import sys

BLICK = 705600000           # 一拍（四分音符）
EDGE = 0.001                # 按句子取时两头的余量（秒）：逐字时间四舍五入到毫秒


def blick_to_sec(svp: dict):
    pts = sorted((t["position"], t["bpm"]) for t in svp["time"]["tempo"])

    def f(b: float) -> float:
        s, lp, lb = 0.0, 0, pts[0][1]
        for p, bpm in pts:
            if p >= b:
                break
            s += (p - lp) / BLICK * 60 / lb
            lp, lb = p, bpm
        return s + (b - lp) / BLICK * 60 / lb
    return f


def main_track(svp: dict, name: str | None) -> dict:
    """主轨：给了名字用它；没给 → 没静音、音最多的那条音符轨。"""
    lib = {g["uuid"]: g for g in svp.get("library", [])}

    def count(t: dict) -> int:
        return len(t["mainGroup"].get("notes", [])) + sum(len(lib.get(r["groupID"], {}).get("notes", [])) for r in t.get("groups", []))
    tracks = [t for t in svp["tracks"] if name is None or t.get("name") == name]
    if name is not None and not tracks:
        raise SystemExit(f"工程里没有轨「{name}」：{[t.get('name') for t in svp['tracks']]}")
    cands = [t for t in tracks if count(t) > 0 and not t.get("mixer", {}).get("mute")]
    if not cands:
        raise SystemExit("工程里没有在放的音符轨")
    return max(cands, key=count)


def track_notes(svp: dict, track: dict) -> list[dict]:
    """这条轨所有的音（组里的换成绝对位置、带上组的移调），深拷贝。"""
    lib = {g["uuid"]: g for g in svp.get("library", [])}
    out = []
    for n in track["mainGroup"].get("notes", []):
        out.append(copy.deepcopy(n))
    for ref in track.get("groups", []):
        g = lib.get(ref["groupID"])
        for n in (g or {}).get("notes", []):
            m = copy.deepcopy(n)
            m["onset"] = n["onset"] + ref.get("blickOffset", 0)
            m["pitch"] = n["pitch"] + ref.get("pitchOffset", 0)
            out.append(m)
    return sorted(out, key=lambda n: n["onset"])


def new_id() -> str:
    return secrets.token_hex(8)


def harmony_track(main: dict, notes: list[dict], shift: int, name: str, muted: bool, gain: float, order: int) -> dict:
    t = copy.deepcopy(main)
    t["name"] = name
    t["dispOrder"] = order
    t["dispColor"] = "ff7db0e8" if shift < 0 else "ffe8a07d"
    group = t["mainGroup"]
    group["uuid"] = new_id()
    group["name"] = name
    group["notes"] = []
    for n in notes:
        m = copy.deepcopy(n)
        m["uuid"] = new_id()
        m["pitch"] = n["pitch"] + shift
        group["notes"].append(m)
    t["groups"] = []                                   # 不引用组：音都直接放在这条轨上
    t["mainRef"]["uuid"] = new_id()
    t["mainRef"]["groupID"] = group["uuid"]
    t["mainRef"]["mute"] = False
    mixer = t.setdefault("mixer", {})
    mixer["gainDecibel"] = float(mixer.get("gainDecibel", 0.0)) + gain
    mixer["mute"] = muted
    mixer["solo"] = False
    return t


HERE = pathlib.Path(__file__).resolve().parent


def lyric_lines(svp_path: pathlib.Path, lyrics: pathlib.Path) -> list[dict]:
    """每句歌词唱的起止（秒）：用做字幕那套代码（lyric_timing.py，vocal2midi 环境）把工程里的音对回歌词。"""
    import subprocess, tempfile
    cfg = json.loads((HERE / "cover_config.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "逐字时间.json"
        log = pathlib.Path(td) / "lyric_timing.log"
        with open(log, "w", encoding="utf-8") as fh:
            r = subprocess.run([cfg["vocal2midi_python"], str(HERE / "lyric_timing.py"), str(svp_path), str(lyrics), str(out)],
                               stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        if r.returncode != 0 or not out.exists():
            tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:] or [""]
            raise ValueError(f"对不出每句的时间（lyric_timing 退出码 {r.returncode}）：{tail[0][:200]}")
        return json.loads(out.read_text(encoding="utf-8"))["行"]


def parse_lines(spec: str) -> list[tuple[int, int]]:
    """「14-18,44-48」「第14～18句、第44～48句」「20」这类写法 → [(14, 18), (44, 48)]。"""
    import re
    s = re.sub(r"[第句\s]", "", spec.strip())
    s = re.sub(r"[～~—–－到至]", "-", s)
    out = []
    for part in re.split(r"[,，、;；]+", s):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"看不懂「{part}」：写成 14-18、44-48 这样（第几句到第几句）")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out.append((min(a, b), max(a, b)))
    if not out:
        raise ValueError("没说加在哪几句")
    return out


def write_readme(path: pathlib.Path, src: pathlib.Path, info: dict) -> None:
    on = "下八度" if info["默认开"] == "below" else "上八度"
    off = "上八度" if on == "下八度" else "下八度"
    where = "、".join(f"第 {a}–{b} 句（{mmss(lo)}–{mmss(hi)}）" if a != b else f"第 {a} 句（{mmss(lo)}–{mmss(hi)}）"
                      for (a, b), (lo, hi) in zip(info["句"], info["段"])) if info.get("句") else "、".join(f"{mmss(lo)}–{mmss(hi)}" for lo, hi in info["段"])
    lines = [f"# 《{info['歌']}》{info['版本']}：{info['来源版本']} + 八度和声", "",
             f"- 来源：`{src.parent.name}\\{src.name}`（{info['来源版本']} 里最近改过的那份）。原来的轨一个字没动",
             f"- 加在：{where}",
             f"- 「和声 · {on}」开着；「和声 · {off}（静音，想要就打开）」静音。两条都比主唱低 {abs(info['音量']):g} dB，声库和主唱一样",
             f"- 各 {info['复制的音']} 个音（主旋律这几段 {info['主旋律这几段']} → 下八度 {info['下八度']}、上八度 {info['上八度']}）：起止、歌词、属性原样，只改音高",
             "", "在 SV 里打开听；想换另一个八度就切换两条的静音。听好了导出新混音，再说「用新混音出视频」。"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mmss(s: float) -> str:
    return f"{int(s // 60)}:{s % 60:04.1f}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("svp")
    ap.add_argument("out")
    ap.add_argument("--section", action="append", default=[], help="秒，比如 40.1-55.7（音的开头落在里面就复制）")
    ap.add_argument("--lines", default=None, help="第几句：14-18,44-48 —— 按每句歌词唱的时间取，要歌词（--lyrics）")
    ap.add_argument("--lyrics", default=None, help="歌词（要唱的字）：默认 <项目>\\素材\\歌词_要唱的字.txt")
    ap.add_argument("--on", default="below", choices=["below", "above"], help="默认开哪条（另一条静音）")
    ap.add_argument("--gain", type=float, default=-6.0, help="比主轨低多少分贝")
    ap.add_argument("--track", default=None)
    ap.add_argument("--readme", action="store_true", help="在新工程旁边写 说明.md")
    a = ap.parse_args()
    src = pathlib.Path(a.svp)
    out = pathlib.Path(a.out)

    def fail(why: str) -> int:
        print(why)
        return 1

    if out.exists():
        return fail(f"{out} 已经有了 —— 不覆盖")
    svp = json.loads(src.read_text(encoding="utf-8"))
    sec = blick_to_sec(svp)
    sections, line_ranges = [], None
    try:
        for s in a.section:
            lo, hi = (float(x) for x in s.split("-"))
            sections.append((lo, hi))
        if a.lines:
            line_ranges = parse_lines(a.lines)
            lyrics = pathlib.Path(a.lyrics) if a.lyrics else src.parent.parent / "素材" / "歌词_要唱的字.txt"
            if not lyrics.exists():
                return fail(f"找不到歌词：{lyrics}（按句子加和声要用歌词对时间）")
            rows = lyric_lines(src, lyrics)
            by_no = {ln["行"]: ln for ln in rows}
            for x, y in line_ranges:
                if x not in by_no or y not in by_no:
                    return fail(f"没有第 {x if x not in by_no else y} 句（歌词一共 {max(by_no)} 句）")
                lo, hi = by_no[x].get("开始"), by_no[y].get("结束")
                if lo is None or hi is None:
                    return fail(f"第 {x}–{y} 句在工程里对不上音（没有时间）")
                # 逐字时间是四舍五入到毫秒的（差 ≤ 0.5 ms）：两头都往前挪 1 ms —— 不漏这一段第一个音、也不带上下一句紧挨着的第一个音
                # （10-04《由》第三段：开始记成 177.747，那个音其实在 177.7466，比开始早、没复制上）
                sections.append((lo - EDGE, hi - EDGE))
    except ValueError as e:
        return fail(str(e))
    if not sections:
        return fail("没说加在哪：--lines（第几句 / 副歌）或 --section（秒）")
    main_t = main_track(svp, a.track)
    notes = track_notes(svp, main_t)
    picked = [n for n in notes if any(lo <= sec(n["onset"]) < hi for lo, hi in sections)]
    if not picked:
        return fail("这几段里一个音都没有")
    say = lambda n: f"{sec(n['onset']):.3f} 秒「{n.get('lyrics', '')}」" if n else "（没有）"
    edges = []
    for lo, hi in sections:                       # 每段两头：复制的第一个 / 最后一个音，紧挨着没复制的前一个 / 后一个音
        inside = [n for n in notes if lo <= sec(n["onset"]) < hi]
        before = [n for n in notes if sec(n["onset"]) < lo]
        after = [n for n in notes if sec(n["onset"]) >= hi]
        edges.append({"段": [lo, hi], "前面没复制的": say(before[-1] if before else None), "复制的第一个": say(inside[0] if inside else None),
                      "复制的最后一个": say(inside[-1] if inside else None), "后面没复制的": say(after[0] if after else None), "音数": len(inside)})
    order = max(t.get("dispOrder", 0) for t in svp["tracks"]) + 1
    below = harmony_track(main_t, picked, -12, "和声 · 下八度" + ("" if a.on == "below" else "（静音，想要就打开）"), a.on != "below", a.gain, order)
    above = harmony_track(main_t, picked, +12, "和声 · 上八度" + ("" if a.on == "above" else "（静音，想要就打开）"), a.on != "above", a.gain, order + 1)
    svp["tracks"] += [below, above]
    # 导出设置指向这一版自己（和 song_round.py 一样）：第一版照抄了来源的，《怪物》r03 在 SV 里导出会落进 r01\render、文件名带 r01
    svp["renderConfig"].update(destination=str(out.parent / "render").replace("\\", "/"), filename=out.stem, numChannels=2)   # 10-08：单声道导出会糊（见 song_round）
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(svp, ensure_ascii=False), encoding="utf-8")
    name = lambda p: ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][p % 12] + str(p // 12 - 1)
    ps = [n["pitch"] for n in picked]
    info = {"结果": "完成", "主轨": main_t.get("name"), "句": [list(r) for r in line_ranges] if line_ranges else None,
            "段": [[round(lo, 3), round(hi, 3)] for lo, hi in sections], "两头": edges, "复制的音": len(picked),
            "主旋律这几段": f"{name(min(ps))}–{name(max(ps))}", "下八度": f"{name(min(ps) - 12)}–{name(max(ps) - 12)}",
            "上八度": f"{name(min(ps) + 12)}–{name(max(ps) + 12)}", "默认开": a.on, "音量": a.gain, "工程": str(out),
            "歌": src.parent.parent.name, "版本": out.parent.name, "来源版本": src.parent.name}
    if a.readme:
        write_readme(out.parent / "说明.md", src, info)
        info["说明"] = str(out.parent / "说明.md")
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
