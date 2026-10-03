# -*- coding: utf-8 -*-
r"""特效字幕（v3 视频，2026-10-01）：每个字（日语、英文是每个词）单独一条字幕，按它自己唱的时间动。

创作者 10-01：「接下来尝试一下特效字幕」→ 先出几种样片给他挑；原来的整行卡拉 OK 叫「平铺」（lyric_video.py 里，默认不变）。

    弹跳      唱到的字跳一下、变色
    发光      唱到的字亮起来、背后一圈光晕，唱完留一点余光
    浮现      整行的字一个个从下面飘上来；唱到的字慢慢变色（像卡拉 OK 填色）；唱完一个个往上飘走
    逐字出现  先只有很淡的影子；唱到哪个字，哪个字「弹」出来
    竖排古风  华文行楷，竖着排在右边；唱到哪个字，哪个字像墨一样晕开、先金色后白；下一句出来时这一句往左挪、变淡，再退场

每个字单独放（\pos 定在它自己的位置）→ 要自己排版：字宽从字体文件读（fontTools）。
libass 把字体的 winAscent + winDescent 当成「字号」那么高（libass ass_font.c：set_font_metrics 换成 OS/2 的 win 值，再按 REAL_DIM 设大小）
→ 一个字的宽 = 字宽 × 字号 ÷ (winAscent + winDescent)，再加字距（样式里的 Spacing）。
排得对不对：python lyric_fx.py --calibrate —— 同一行让 libass 自己排（红）、我们一个字一个字排（绿）盖上去，数露出来的红像素。

只用 Python 自带模块 + fontTools（G:/miniconda 里有）：
    python lyric_fx.py --calibrate [--ffmpeg …]
    （平时由 lyric_video.py --fx <样式> 调 write_fx_ass）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

from fontTools.ttLib import TTFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lyric_video import FONTS, H, W, ass_header, esc, line_windows, title_events, ts  # noqa: E402
from image_side import calm_side, line_sides, text_area  # noqa: E402,F401  字放哪边、放多宽（剪映草稿也用同一份）
from lyric_rows import phrase_rows, unit_times  # noqa: E402  单位唱的时间、一句拆成几行（剪映草稿也用同一份）

try:                               # 下载来的字体（不装进系统）：cover_config.json 的 fonts_dir
    FONTS_DIR = pathlib.Path(json.loads((pathlib.Path(__file__).resolve().parent / "cover_config.json").read_text(encoding="utf-8"))["fonts_dir"])
except Exception:
    FONTS_DIR = pathlib.Path("E:/sv-agent-data/fonts")
FONT_FILES = {                     # ASS 里写的字体名 → 用到的那个字重的文件（样式是粗体就是粗体文件）
    "Microsoft YaHei": "C:/Windows/Fonts/msyhbd.ttc",
    "Yu Gothic": "C:/Windows/Fonts/YuGothB.ttc",
    "Segoe UI": "C:/Windows/Fonts/segoeuib.ttf",
    "STXingkai": "C:/Windows/Fonts/STXINGKA.TTF",
    "ZCOOL KuaiLe": str(FONTS_DIR / "ZCOOLKuaiLe-Regular.ttf"),
    "Ma Shan Zheng": str(FONTS_DIR / "MaShanZheng-Regular.ttf"),
    "Yuji Syuku": str(FONTS_DIR / "YujiSyuku-Regular.ttf"),
}
SIZE, SPACING, BOTTOM = 76, 2, H - 96          # 和「平铺」一样：76 号、字距 2、底边离画面下沿 96
V_FONT, V_SIZE, V_X, V_GAP = "STXingkai", 92, W - 330, 150     # 竖排：华文行楷 92 号，当前这句的中线在 x = 1590，上一句往左挪 150
WHITE, ACCENT, GLOW, GOLD, DARK = "&HFFFFFF&", "&H80F0FF&", "&H40A0FF&", "&H60D0FF&", "&H101010&"
UNSUNG = 0x60                                    # 没唱到的字：填色 60（和「平铺」的半透明白一样）


class Font:
    _cache: dict[str, "Font"] = {}

    def __init__(self, family: str):
        t = TTFont(FONT_FILES[family], fontNumber=0, lazy=True)
        os2 = t["OS/2"]
        self.k = os2.usWinAscent + os2.usWinDescent
        self.upem = t["head"].unitsPerEm
        self.cmap = t.getBestCmap()
        self.hmtx = t["hmtx"].metrics

    @classmethod
    def get(cls, family: str) -> "Font":
        if family not in cls._cache:
            cls._cache[family] = cls(family)
        return cls._cache[family]

    def width(self, text: str, size: float, spacing: float = SPACING) -> float:
        """一段字在 libass 里占多宽（每个字后面都加字距，和 libass 一样）。字体里没有的字：libass 会换字体，按一个全角算。"""
        w = 0.0
        for ch in text:
            g = self.cmap.get(ord(ch))
            adv = self.hmtx[g][0] if g in self.hmtx else self.upem
            w += adv * size / self.k + spacing
        return w


def layout_h(texts: list[str], lang: str, family: str, size: float = SIZE, max_w: float = W - 240) -> tuple[list[float], float]:
    """横排一行：每个单位的中心 x；太长就整行缩小到放得下（返回缩小后的字号）。英文词之间一个空格。"""
    font = Font.get(family)
    sep = " " if lang == "en" else ""
    for _ in range(2):
        ws = [font.width(t, size) for t in texts]
        sw = font.width(sep, size) if sep else 0.0
        total = sum(ws) + sw * (len(ws) - 1)
        if total <= max_w:
            break
        size = float(int(size * max_w / total))     # 缩到整数字号：10-01 排版核对，57.3 号时 libass 的字宽和算的差得越来越多（两头差 8 像素），整数号对得上
    x = W / 2 - total / 2
    centers = []
    for w in ws:
        centers.append(x + w / 2)
        x += w + sw
    return centers, size


def ms(sec: float) -> int:
    return max(0, round(sec * 1000))


def _rgb(c: str) -> tuple[int, int, int]:
    v = int(c[2:-1], 16)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def lerp(c0: str, c1: str, f: float) -> str:
    a, b = _rgb(c0), _rgb(c1)
    m = [round(x + (y - x) * f) for x, y in zip(a, b)]
    return f"&H{m[0]:02X}{m[1]:02X}{m[2]:02X}&"


def sing(t0: float, a: float, b: float, gradual: bool, color: str = ACCENT) -> str:
    """一条字幕从 t0 开始时这个字该是什么颜色，以及之后怎么变：唱之前白、半透明；唱到（a）变成 color、不透明。
    gradual：从 a 到 b 慢慢变（像卡拉 OK 填色）；否则 60 毫秒变完。t0 在变的中间：先算好那一刻的颜色。"""
    end = b if gradual and b - a > 0.06 else a + 0.06
    if t0 >= end:
        return f"\\1c{color}\\1a&H00&"
    if t0 <= a:
        return f"\\1c{WHITE}\\1a&H{UNSUNG:02X}&\\t({ms(a - t0)},{ms(end - t0)},\\1c{color}\\1a&H00&)"
    f = (t0 - a) / (end - a)
    return f"\\1c{lerp(WHITE, color, f)}\\1a&H{round(UNSUNG * (1 - f)):02X}&\\t(0,{ms(end - t0)},\\1c{color}\\1a&H00&)"


def dlg(layer: int, t0: float, t1: float, style: str, tags: str, text: str) -> str | None:
    t0, t1 = round(max(0.0, t0), 2), round(t1, 2)
    if t1 - t0 < 0.02:
        return None
    return f"Dialogue: {layer},{ts(t0)},{ts(t1)},{style},,0,0,0,,{{{tags}}}{esc(text)}"


# ---------------------------------------------------------------- 横排的四种

def fx_bounce(u: str, x: float, yc: float, a: float, b: float, S: float, E: float, fs: str) -> list:
    """弹跳：唱到时 0.10 秒跳起（字高的 20%、放大到 115%），0.16 秒落回；之后一直是亮色。"""
    up, J, K = 0.20 * SIZE, 0.10, 0.16
    a = min(max(a, S), E)
    return [
        dlg(1, S, a, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}\\fad(150,0)" + sing(S, a, b, False), u),
        dlg(1, a, min(E, a + J), "FX", f"\\an5\\move({x:.1f},{yc:.1f},{x:.1f},{yc - up:.1f}){fs}\\1c{ACCENT}\\1a&H00&\\t(0,{ms(J)},\\fscx115\\fscy115)", u),
        dlg(1, a + J, min(E, a + J + K), "FX", f"\\an5\\move({x:.1f},{yc - up:.1f},{x:.1f},{yc:.1f}){fs}\\1c{ACCENT}\\1a&H00&\\fscx115\\fscy115\\t(0,{ms(K)},\\fscx100\\fscy100)", u),
        dlg(1, a + J + K, E, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}\\1c{ACCENT}\\1a&H00&\\fad(0,200)", u),
    ]


def fx_glow(u: str, x: float, yc: float, a: float, b: float, S: float, E: float, fs: str) -> list:
    """发光：字本身唱到时变亮；后面一层只留描边、糊开 = 光晕：唱到时从 130% 收回来、最亮，唱完 0.6 秒内暗成余光。"""
    d = ms(b - a)
    return [
        dlg(0, a - 0.02, E, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}\\1a&HFF&\\3c{GLOW}\\4a&HFF&\\bord7\\blur10\\3a&HFF&\\fscx130\\fscy130"
            f"\\t(0,100,\\3a&H20&\\fscx100\\fscy100)\\t({d + 100},{d + 700},\\3a&H90&)\\fad(0,200)", u),
        dlg(1, S, E, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}\\fad(150,200)" + sing(S, a, b, False, "&HE0F4FF&"), u),
    ]


def fx_float(u: str, x: float, yc: float, a: float, b: float, S: float, E: float, fs: str, i: int, n: int) -> list:
    """浮现：第 i 个字晚 i × 35 毫秒（整行最多 0.45 秒）从下面 22 像素飘上来、由糊变清；唱到时从 a 到 b 慢慢变色；
    退场从第一个字开始，一个个往上飘 18 像素、淡掉。"""
    step = min(0.035, 0.45 / max(1, n))
    si = S + i * step
    h0 = si + 0.35
    xo = E - 0.35 - (n - 1 - i) * step              # 这个字开始退场的时间（最后一个字正好在 E 退完）
    h1 = max(h0, xo)
    return [
        dlg(1, si, min(h0, E), "FX", f"\\an5\\move({x:.1f},{yc + 22:.1f},{x:.1f},{yc:.1f}){fs}\\fad(300,0)\\blur5\\t(0,350,\\blur0)" + sing(si, a, b, True), u),
        dlg(1, h0, h1, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}" + sing(h0, a, b, True), u),
        dlg(1, h1, min(E, h1 + 0.35), "FX", f"\\an5\\move({x:.1f},{yc:.1f},{x:.1f},{yc - 18:.1f}){fs}\\fad(0,330)\\t(0,350,\\blur4)" + sing(h1, a, b, True), u),
    ]


def fx_appear(u: str, x: float, yc: float, a: float, b: float, S: float, E: float, fs: str) -> list:
    """逐字出现：唱到之前只有很淡的影子；唱到时从 150%、糊的「弹」到 100%、清楚，唱的时候亮色、唱完 0.5 秒内变白。"""
    d = ms(b - a)
    a0 = max(S, a - 0.03)
    return [
        dlg(1, S, a0, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}\\fad(150,0)\\1a&HD0&\\3a&HB0&\\4a&HFF&", u),
        dlg(1, a0, E, "FX", f"\\an5\\pos({x:.1f},{yc:.1f}){fs}\\1c{ACCENT}\\fscx150\\fscy150\\blur6\\alpha&H80&"
            f"\\t(0,150,\\fscx100\\fscy100\\blur0\\alpha&H00&)\\t({d + 150},{d + 650},\\1c{WHITE})\\fad(0,200)", u),
    ]


HORIZONTAL = {"弹跳": fx_bounce, "发光": fx_glow, "浮现": fx_float, "逐字出现": fx_appear}


def horizontal_events(timing: dict, preset: str) -> list[str]:
    lang = timing["语言"]
    family = FONTS.get(lang, "Microsoft YaHei")
    fn = HORIZONTAL[preset]
    out = []
    lines = timing["行"]
    for ln, (S, E) in zip(lines, line_windows(lines)):
        S = max(S, 0.0)
        if E - S < 0.05:
            continue
        units = ln["单位"]
        xs, size = layout_h([x["文字"] for x in units], lang, family)
        fs = f"\\fs{size:.1f}" if size < SIZE - 0.05 else ""
        yc = BOTTOM - size / 2                       # 字框的中线（\an5 定中心，放大缩小绕着字自己的中心）
        for i, (u, x, (a, b)) in enumerate(zip(units, xs, unit_times(units))):
            if preset == "浮现":
                evs = fn(u["文字"], x, yc, a, b, S, E, fs, i, len(units))
            else:
                evs = fn(u["文字"], x, yc, a, b, S, E, fs)
            out += [e for e in evs if e]
    return out


# ---------------------------------------------------------------- 竖排古风

def vertical_events(timing: dict) -> list[str]:
    """竖排古风：这一句竖着排在右边（字多了就缩小，整列最高 860 像素），上下居中。
    出来时先是很淡的影子；唱到哪个字，哪个字从糊、大一点晕开到清楚（墨晕），唱的时候金色、唱完变白；
    下一句出来的那一刻，这一句往左挪 150 像素、变淡，再下一句出来时淡出；
    下一句要等 4 秒以上（间奏）：这一句唱完 4 秒原地淡出，不挪。
    下一句最早在这一句唱完 0.05 秒后才出影子（10-01 样片：两句挨着时下一句的影子提前出在同一列，和还没挪走的这一句叠在一起）。"""
    font = Font.get(V_FONT)
    lines = timing["行"]
    out = []
    LINGER = 4.0
    shows = []
    for k, ln in enumerate(lines):
        s = max(0.0, ln["开始"] - 0.6)
        if k > 0:
            s = max(s, lines[k - 1]["结束"] + 0.05)
        shows.append(s)
    for k, ln in enumerate(lines):
        units = ln["单位"]
        chars = [(c, ui) for ui, u in enumerate(units) for c in u["文字"] if not c.isspace()]
        if not chars:
            continue
        times = unit_times(units)
        n = len(chars)
        size = V_SIZE
        em = size * font.upem / font.k
        step = em * 1.04
        if step * n > 860:
            size = float(int(size * 860 / (step * n)))   # 整数字号（和横排一样）
            em = size * font.upem / font.k
            step = em * 1.04
        fs = f"\\fs{size:.1f}" if size < V_SIZE - 0.05 else ""
        top = H / 2 - step * n / 2
        S = shows[k]
        if k + 1 < len(lines) and shows[k + 1] <= ln["结束"] + LINGER:
            mv = shows[k + 1]                                           # 下一句出来：挪到左边
            gone = shows[k + 2] if k + 2 < len(lines) else ln["结束"] + LINGER + 2.0
            gone = max(min(gone, ln["结束"] + LINGER + 2.0), mv + 1.1)   # 在左边至少待 0.5 秒（挪 0.6 秒），最多到唱完后 6 秒
        else:
            mv, gone = None, ln["结束"] + LINGER                        # 间奏长、或者最后一句：原地淡出
        for j, (c, ui) in enumerate(chars):
            a, b = times[ui]
            y = top + step * (j + 0.5)
            a0 = max(S, a - 0.05)
            last = mv if mv is not None else gone
            d = ms(b - a)
            out.append(dlg(1, S, a0, "FXV", f"\\an5\\pos({V_X},{y:.1f}){fs}\\fad(300,0)\\1a&HD8&\\3a&HC8&", c))
            out.append(dlg(1, a0, last, "FXV", f"\\an5\\pos({V_X},{y:.1f}){fs}\\1c{GOLD}\\blur10\\alpha&HFF&\\fscx125\\fscy125"
                           f"\\t(0,450,\\blur0.6\\alpha&H00&\\fscx100\\fscy100)\\t({d + 200},{d + 900},\\1c{WHITE})"
                           + ("" if mv is not None else "\\fad(0,500)"), c))
            if mv is not None:
                out.append(dlg(1, mv, mv + 0.6, "FXV", f"\\an5\\move({V_X},{y:.1f},{V_X - V_GAP},{y:.1f}){fs}\\1c{WHITE}\\t(0,600,\\alpha&H90&)", c))
                out.append(dlg(1, mv + 0.6, gone, "FXV", f"\\an5\\pos({V_X - V_GAP},{y:.1f}){fs}\\1c{WHITE}\\alpha&H90&\\fad(0,500)", c))
    return [e for e in out if e]


# ---------------------------------------------------------------- 可爱（照创作者 10-02 给的参考：B 站《樱草哀歌》/ 星尘infinity，心脏扭蛋_rabbitrite）

CUTE_FONT = "ZCOOL KuaiLe"                       # 站酷快乐体（Google Fonts，OFL；创作者 10-02 选的、同意下载，放在 fonts_dir，不装进系统）
CUTE_SIZE = 120                                  # 普通行 120 号；三个字以内的短行放大到 1.4 倍（参考里「一直到」「白裙裾」是大字，150 像素以上高）
CUTE_BIG = 1.4
CUTE_COLORS = ["&H4FA0F5&", "&HAA7BF4&", "&HF07CA0&", "&HF0A85A&"]   # 每句轮着换描边色：橙 #F5A04F、粉 #F47BAA、紫 #A07CF0、蓝 #5AA8F0
CUTE_DRIFT = 16                                  # 整块每秒往右漂 16 像素
CUTE_DRIFT_MAX = 100                             # 一句最多漂 100 像素（长句漂得慢一点）：漂的那段也得在放字的范围里
CUTE_IN, CUTE_OUT = 0.25, 0.35                   # 滑进来 0.25 秒；滑出去 0.35 秒
CUTE_AREA_W = text_area("left")[1] - text_area("left")[0]   # 字放在图里空的那一边：800 像素宽（image_side.text_area；10-02 前是 880、而且整块可能伸出去）
CUTE_AREA_H = 760                                # 整块最高 760 像素


def _jitter(seed: int) -> float:
    """固定的「随机」：同一句每次出来都一样（-1 … 1）。"""
    x = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    return (x % 2001) / 1000.0 - 1.0


def fit_area(items: list[dict], side: str, drift: float = 0.0) -> tuple[float, float]:
    """整块放进这一边能放字的范围（image_side.text_area）：按整块的外框居中，不是按某个字居中；放不下就整块缩小。
    10-02《怪物》雨夜底片：凌厉原来按大字居中，右边小字列多的句子整块往右伸出去，压到了人物的手。
    drift：这一句里整块还要往右漂多远（可爱）。返回 (bx, f)：bx 加到每项的 x 上；f 是缩成几倍（各项的 x、y、size、w、h 已经乘过）。"""
    x0, x1 = text_area(side)
    lo = min(it["x"] - it["w"] / 2 for it in items)
    hi = max(it["x"] + it["w"] / 2 for it in items)
    f = min(1.0, (x1 - x0 - drift) / (hi - lo))
    if f < 1.0:
        for it in items:
            for k_ in ("x", "y", "size", "w", "h"):
                it[k_] *= f
        lo, hi = lo * f, hi * f
    return x0 + (x1 - x0 - drift - (hi - lo)) / 2 - lo, f


def cute_layout(ln: dict, k: int, lang: str, family: str) -> list[dict]:
    """排一句：返回每个单位的 {x, y（相对整块中心）, size, rot}。三种排法轮着来（参考视频里都有）：
    行块 —— 拆成几行、短行放大、整块逆时针转 6°（往右上翘）；下台阶 —— 一个字比前一个往右下错一点；上台阶 —— 往右上错。
    单位多于 9 个、或英文：只用行块。"""
    import math
    font = Font.get(family)
    units = ln["单位"]
    times = unit_times(units)
    n = len(units)
    kind = "行块" if (n > 9 or lang == "en") else ("行块", "下台阶", "上台阶")[k % 3]
    items = []
    if kind == "行块":
        rows = phrase_rows(ln, times, lang)
        y = 0.0
        sep = " " if lang == "en" else ""
        for ri, row in enumerate(rows):
            size = CUTE_SIZE * (CUTE_BIG if sum(len(units[i]["文字"]) for i in row) <= 3 and lang != "en" else 1.0)
            em = size * font.upem / font.k
            x = (0.0, -0.45, -0.85)[ri % 3] * em           # 越往下的行越往左起（参考里「雨幕」比「一直到」靠左、「白裙裾」更靠左）
            for i in row:
                w = font.width(units[i]["文字"], size)
                items.append({"i": i, "x": x + w / 2, "y": y + em / 2, "size": size, "rot": 0.0, "w": w, "h": em})
                x += w + 3 + (font.width(sep, size) if sep else 0)
            y += em * 1.12
        angle = 6.0
    else:
        dy = 0.42 if kind == "下台阶" else -0.48
        x = y = 0.0
        for i in range(n):
            size = CUTE_SIZE * (1 + 0.07 * _jitter(k * 131 + i))
            em = size * font.upem / font.k
            w = font.width(units[i]["文字"], size)
            items.append({"i": i, "x": x + w / 2, "y": y, "size": size, "rot": 6.0 * _jitter(k * 977 + i * 7), "w": w, "h": em})
            x += w * 0.92
            y += em * dy * max(1, len(units[i]["文字"])) ** 0.5
        angle = 0.0
    # 整块转 angle 度（逆时针，往右上翘）：坐标自己转，每个字再转同样的角度
    cx = (min(it["x"] for it in items) + max(it["x"] for it in items)) / 2
    cy = (min(it["y"] for it in items) + max(it["y"] for it in items)) / 2
    th = math.radians(angle)
    for it in items:
        dx, dyy = it["x"] - cx, it["y"] - cy
        it["x"], it["y"] = dx * math.cos(th) + dyy * math.sin(th), -dx * math.sin(th) + dyy * math.cos(th)
        it["rot"] += angle
    # 太宽、太高：整块缩小到放得下 —— 按每个单位真的宽、高算（10-02 日语样片：一个词好几个字，原来只算中心，斜台阶的开头跑出了画面左边）
    span_w = max(it["x"] + it["w"] / 2 for it in items) - min(it["x"] - it["w"] / 2 for it in items)
    span_h = max(it["y"] + it["h"] / 2 for it in items) - min(it["y"] - it["h"] / 2 for it in items)
    f = min(1.0, CUTE_AREA_W / span_w, CUTE_AREA_H / span_h)
    if f < 1.0:
        for it in items:
            for key in ("x", "y", "size", "w", "h"):
                it[key] *= f
    return items


def cute_events(timing: dict, sides: list[str]) -> list[str]:
    """可爱：白字 + 彩色描边 + 一圈同色的柔光（后面一层只留描边、糊开）；每句换一种描边色、换一种排法。
    唱到的字从左边 70 像素滑进来、由糊变清、从 86% 弹到原样（字先带一点描边色，0.3 秒变白）；整块一直慢慢往右漂（一句最多 100 像素）；
    这一句退场时每个字往左滑 160 像素、糊掉、淡出（参考里是带动态模糊滑出去）。sides：每句放左边还是右边。"""
    lang = timing["语言"]
    family = CUTE_FONT if lang == "zh" else FONTS.get(lang, "Microsoft YaHei")   # 快乐体没有假名、英文也一般 → 日英先用原来的字体
    lines = timing["行"]
    out = []
    for k, (ln, (S, E)) in enumerate(zip(lines, line_windows(lines))):
        S = max(S, 0.0)
        if E - S < 0.3:
            continue
        color = CUTE_COLORS[k % len(CUTE_COLORS)]
        glow = lerp(color, WHITE, 0.35)
        tint = lerp(WHITE, color, 0.45)
        items = cute_layout(ln, k, lang, family)
        side = sides[k] if k < len(sides) else "left"
        speed = min(CUTE_DRIFT, CUTE_DRIFT_MAX / (E - S))
        bx, _ = fit_area(items, side, speed * (E - S))                 # 整块连同往右漂的那段都在这一边能放字的范围里
        by = H * 0.43 + 30 * _jitter(k * 17 + 3)
        # 留在画面里（保险）：左右离边至少 50 像素，上 60、下 80
        left = bx + min(it["x"] - it["w"] / 2 for it in items)
        right = bx + max(it["x"] + it["w"] / 2 for it in items) + speed * (E - S)
        top = by + min(it["y"] - it["h"] / 2 for it in items)
        bottom = by + max(it["y"] + it["h"] / 2 for it in items)
        bx += max(0.0, 50 - left) - max(0.0, right - (W - 50))
        by += max(0.0, 60 - top) - max(0.0, bottom - (H - 80))
        times = unit_times(ln["单位"])
        n = len(items)
        x = lambda t, it: bx + it["x"] + speed * (t - S)
        for j, it in enumerate(items):
            a, b = times[it["i"]]
            t_in = min(max(S, a - 0.10), E - CUTE_OUT - 0.05)
            t_out = max(t_in + CUTE_IN, E - CUTE_OUT - 0.012 * (n - 1 - j))          # 退场从第一个字开始，一个接一个
            t_end = min(E, t_out + CUTE_OUT)
            y = by + it["y"]
            text = ln["单位"][it["i"]]["文字"]
            base = f"\\an5\\fn{family}\\b{0 if family == CUTE_FONT else 1}\\fs{it['size']:.1f}\\frz{it['rot']:.1f}\\shad0"
            main = f"{base}\\bord7\\3c{color}"
            halo = f"{base}\\bord17\\blur13\\1a&HFF&\\3c{glow}"
            x_in0, x_in1 = x(t_in, it) - 70, x(t_in + CUTE_IN, it)
            out += [
                dlg(1, t_in, t_in + CUTE_IN, "FX", f"{main}\\move({x_in0:.1f},{y:.1f},{x_in1:.1f},{y:.1f})\\1c{tint}\\alpha&HFF&\\blur6\\fscx86\\fscy86"
                    f"\\t(0,{ms(CUTE_IN)},\\alpha&H00&\\blur0.8\\fscx100\\fscy100\\1c{WHITE})", text),
                dlg(0, t_in, t_in + CUTE_IN, "FX", f"{halo}\\move({x_in0:.1f},{y:.1f},{x_in1:.1f},{y:.1f})\\3a&HFF&\\t(0,{ms(CUTE_IN)},\\3a&H40&)", text),
                dlg(1, t_in + CUTE_IN, t_out, "FX", f"{main}\\move({x_in1:.1f},{y:.1f},{x(t_out, it):.1f},{y:.1f})\\1c{WHITE}\\blur0.8", text),
                dlg(0, t_in + CUTE_IN, t_out, "FX", f"{halo}\\move({x_in1:.1f},{y:.1f},{x(t_out, it):.1f},{y:.1f})\\3a&H40&", text),
                dlg(1, t_out, t_end, "FX", f"{main}\\move({x(t_out, it):.1f},{y:.1f},{x(t_out, it) - 160:.1f},{y:.1f})\\1c{WHITE}\\blur0.8"
                    f"\\t(0,{ms(CUTE_OUT)},\\alpha&HFF&\\blur8)", text),
                dlg(0, t_out, t_end, "FX", f"{halo}\\move({x(t_out, it):.1f},{y:.1f},{x(t_out, it) - 160:.1f},{y:.1f})\\3a&H40&\\t(0,{ms(CUTE_OUT)},\\3a&HFF&)", text),
            ]
    return [e for e in out if e]


# ---------------------------------------------------------------- 凌厉（10-02：创作者「找一个凌厉的版本」→ 参考 B 站《【文字PV】KING》）

SHARP_BRUSH = "Ma Shan Zheng"            # 马善政毛笔楷书（Google Fonts，OFL；创作者 10-02 选的、同意下载）—— 创作者 10-02：参考里的大字「这是楷书」
# 竖排小字：也用马善政。第一版是思源宋体最粗一档，创作者 10-02：「字体换一下，这个宋体太丑了，其他还行」→ 同一帧比了三种（马善政 / 思源黑体最粗 / 微软雅黑粗），他选马善政
SHARP_SMALL = SHARP_BRUSH
SHARP_BRUSH_JA = "Yuji Syuku"           # 日语：佑字肅（Google Fonts，OFL；创作者 10-02 选的、同意下载）—— 马善政没有假名、而且是简体字形
SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ")
LONG_MARKS = set("ー〜～")              # 竖排时要转成竖的
SHARP_RED = "&H3B24E5&"                  # 红 #E5243B
SHARP_BIG = 400                          # 大字最大字号（马善政的字框高 = 字号 × 1000 / 1373：400 号约 290 像素；第一版 330 不够大）
SHARP_BIG_W = 900                        # 大字那一截最宽 900 像素
SHARP_COL = 96                           # 竖排小字字号（第一版 78 太小）
SHARP_AREA_W, SHARP_AREA_H = CUTE_AREA_W, 900    # 整块最宽、最高：和「可爱」一样放在 image_side.text_area 里（800 宽）
# （10-02《怪物》：1000 宽时右边那列碰到人物 → 880；换雨夜底片后发现整块是按大字居中的、会伸出 880 → 改成按外框放进 text_area）
# 底图：压暗、加一点对比、降饱和、暗角、颗粒 —— 出片前对每张图只做一次（lyric_video.py）：颗粒固定在图上、跟着推近走，
# 编码器能预测（10-02 第一版每一帧现加会变的颗粒：25 秒的样片 305 MB）
SHARP_GRADE = "eq=brightness=-0.14:contrast=1.08:saturation=0.5,vignette=angle=PI/3.6,noise=alls=10:allf=u"


def sharp_layout(ln: dict, lang: str) -> dict:
    """排一句（位置都相对整块中心）：拆成几截（lyric_rows.phrase_rows）；最短的那一截（一样短取后面的）是「大字」——毛笔楷书、横着、放大；
    在它前面唱的几截竖排在左边、后面唱的竖排在右边（也是毛笔楷书、小一号，一截一列，一个字一格，红白相间）。英文不竖排：小字一截一行，放在大字上下。
    返回 {items: [...], slash: (x0, y0, x1, y1)}；每项 {i（第几个单位）, text, x, y, size, font, color, w, h, big}。"""
    units = ln["单位"]
    rows = phrase_rows(ln, unit_times(units), lang)
    key = min(range(len(rows)), key=lambda r: (sum(len(units[i]["文字"]) for i in rows[r]), -r))
    brush = {"zh": SHARP_BRUSH, "ja": SHARP_BRUSH_JA}.get(lang, FONTS.get(lang, "Microsoft YaHei"))
    serif = {"zh": SHARP_SMALL, "ja": SHARP_BRUSH_JA}.get(lang, FONTS.get(lang, "Microsoft YaHei"))
    fb, fs_ = Font.get(brush), Font.get(serif)
    sep = " " if lang == "en" else ""
    widths = lambda size: [fb.width(units[i]["文字"], size, 0) for i in rows[key]]
    gap = lambda size: fb.width(sep, size, 0) if sep else 0.0
    size = SHARP_BIG
    w_all = sum(widths(size)) + gap(size) * (len(rows[key]) - 1)
    if w_all > SHARP_BIG_W:                               # 大字太宽：缩到放得下（整数字号）
        size = float(int(size * SHARP_BIG_W / w_all))
        w_all = sum(widths(size)) + gap(size) * (len(rows[key]) - 1)
    em = size * fb.upem / fb.k
    items, x = [], -w_all / 2
    for i, w in zip(rows[key], widths(size)):
        items.append({"i": i, "text": units[i]["文字"], "x": x + w / 2, "y": 0.0, "size": size, "font": brush, "color": WHITE, "w": w, "h": em, "big": True})
        x += w + gap(size)
    c_em = SHARP_COL * fs_.upem / fs_.k
    if lang == "en":                                      # 英文：小字一截一行，前面的在上、后面的在下
        for side, order in ((-1, [r for r in range(len(rows)) if r < key][::-1]), (1, [r for r in range(len(rows)) if r > key])):
            for n_, r in enumerate(order):
                ww = [fs_.width(units[i]["文字"], SHARP_COL, 0) for i in rows[r]]
                sp = fs_.width(" ", SHARP_COL, 0)
                xx = -(sum(ww) + sp * (len(ww) - 1)) / 2
                yy = side * (em / 2 + c_em * (0.9 + 1.15 * n_))
                for i, w in zip(rows[r], ww):
                    items.append({"i": i, "text": units[i]["文字"], "x": xx + w / 2, "y": yy, "size": SHARP_COL, "font": serif,
                                  "color": SHARP_RED if r % 2 else WHITE, "w": w, "h": c_em, "big": False})
                    xx += w + sp
    else:                                                 # 中文、日语：竖排，一截一列，一个字一格
        top = -em / 2 - c_em * 0.4
        for side, order in ((-1, [r for r in range(len(rows)) if r < key][::-1]), (1, [r for r in range(len(rows)) if r > key])):
            for n_, r in enumerate(order):
                cx = side * (w_all / 2 + c_em * (0.9 + 1.25 * n_))
                color = SHARP_RED if (n_ + (side > 0)) % 2 == 0 else WHITE
                yy = top
                for i in rows[r]:
                    for ch in units[i]["文字"]:
                        # 日语竖排的规矩：小假名（っゃゅょ…）靠格子右上；长音「ー」转成竖的
                        dx, dy = (0.14 * c_em, -0.14 * c_em) if ch in SMALL_KANA else (0.0, 0.0)
                        items.append({"i": i, "text": ch, "x": cx + dx, "y": yy + c_em / 2 + dy, "size": SHARP_COL, "font": serif, "color": color,
                                      "w": c_em, "h": c_em, "big": False, "rot": -90.0 if ch in LONG_MARKS else 0.0})
                        yy += c_em * 1.06
    slash = (-w_all / 2 - 60, em * 0.42, w_all / 2 + 60, -em * 0.36)     # 刀痕：从大字左下斜着划到右上，两头各长 60 像素
    span_w = max(it["x"] + it["w"] / 2 for it in items) - min(it["x"] - it["w"] / 2 for it in items)
    span_h = max(it["y"] + it["h"] / 2 for it in items) - min(it["y"] - it["h"] / 2 for it in items)
    f = min(1.0, SHARP_AREA_W / span_w, SHARP_AREA_H / span_h)
    if f < 1.0:                                           # 太大：整块缩小
        for it in items:
            for k_ in ("x", "y", "size", "w", "h"):
                it[k_] *= f
        slash = tuple(v * f for v in slash)
    return {"items": items, "slash": slash}


def sharp_events(timing: dict, sides: list[str]) -> list[str]:
    """凌厉：每个字唱到时一下砸进来（从 175%（小字 140%）、糊的 0.08 秒收成原样、清楚）；大字落下时抖两下（各 0.05 秒）；
    大字后面一道红色刀痕 0.09 秒从左往右划开、0.5 秒后暗下去；这一句唱完硬切，大字留一下红色残影（0.07 秒）。
    大字：白字 + 黑边 + 红色投影（往右下错开）；小字：毛笔楷书，红白相间，黑边。字放在图里空的那一边，整块不出画面。"""
    import math
    lang = timing["语言"]
    lines = timing["行"]
    out = []
    for k, (ln, (S, E)) in enumerate(zip(lines, line_windows(lines))):
        S = max(S, 0.0)
        if E - S < 0.3:
            continue
        lay = sharp_layout(ln, lang)
        items = lay["items"]
        side = sides[k] if k < len(sides) else "left"
        bx, f = fit_area(items, side)                                   # 按整块外框放进这一边能放字的范围
        x0_, y0_, x1_, y1_ = (v * f for v in lay["slash"])
        a0, a1 = (v - bx for v in text_area(side))                      # 刀痕两头伸出大字 60 像素：也别伸出放字的范围（沿着刀痕截短，角度不变）
        if x0_ < a0:
            y0_, x0_ = y0_ + (y1_ - y0_) * (a0 - x0_) / (x1_ - x0_), a0
        if x1_ > a1:
            y1_, x1_ = y1_ - (y1_ - y0_) * (x1_ - a1) / (x1_ - x0_), a1
        lay["slash"] = (x0_, y0_, x1_, y1_)
        by = H * 0.46
        left = bx + min(it["x"] - it["w"] / 2 for it in items)
        right = bx + max(it["x"] + it["w"] / 2 for it in items)
        top = by + min(it["y"] - it["h"] / 2 for it in items)
        bottom = by + max(it["y"] + it["h"] / 2 for it in items)
        bx += max(0.0, 50 - left) - max(0.0, right - (W - 50))          # 留在画面里
        by += max(0.0, 50 - top) - max(0.0, bottom - (H - 60))
        times = unit_times(ln["单位"])
        for it in items:
            a = times[it["i"]][0]
            t0 = min(max(S, a - 0.03), E - 0.2)
            x, y = bx + it["x"], by + it["y"]
            bold = 0 if it["font"] in (SHARP_BRUSH, SHARP_SMALL, SHARP_BRUSH_JA) else 1
            # \fsp0：排版按不加字距算的（FX 样式默认字距 2 —— 多字的词 libass 会排宽，10-02 放字范围检查查出来的）
            look = (f"\\an5\\fn{it['font']}\\b{bold}\\fs{it['size']:.1f}\\fsp0" + (f"\\frz{it['rot']:.0f}" if it.get("rot") else "") + f"\\1c{it['color']}\\3c{DARK}"
                    + (f"\\bord3\\4c{SHARP_RED}\\4a&H00&\\xshad7\\yshad5" if it["big"] else "\\bord2.5\\shad0"))
            text = esc(it["text"])
            land = 0.08
            pop = "\\fscx175\\fscy175" if it["big"] else "\\fscx140\\fscy140"
            layer = 2 if it["big"] else 1
            ev = [dlg(layer, t0, t0 + land, "FX", f"{look}\\pos({x:.1f},{y:.1f}){pop}\\blur8\\alpha&H50&\\t(0,{ms(land)},0.6,\\fscx100\\fscy100\\blur0\\alpha&H00&)", "")]
            if it["big"]:                                                    # 落下抖两下，停住；唱完硬切，留一下红色残影
                ev += [dlg(2, t0 + land, t0 + land + 0.05, "FX", f"{look}\\pos({x + 7:.1f},{y - 5:.1f})", ""),
                       dlg(2, t0 + land + 0.05, t0 + land + 0.10, "FX", f"{look}\\pos({x - 5:.1f},{y + 4:.1f})", ""),
                       dlg(2, t0 + land + 0.10, E, "FX", f"{look}\\pos({x:.1f},{y:.1f})", ""),
                       dlg(1, E, E + 0.07, "FX", f"\\an5\\fn{it['font']}\\b{bold}\\fs{it['size']:.1f}\\fsp0\\1c{SHARP_RED}\\bord0\\shad0\\alpha&H70&\\pos({x + 14:.1f},{y:.1f})", "")]
            else:
                ev.append(dlg(1, t0 + land, E, "FX", f"{look}\\pos({x:.1f},{y:.1f})", ""))
            out += [e + text for e in ev if e]
        big = [it for it in items if it["big"]]
        if big:                                                              # 刀痕
            a_big = min(max(S, times[big[0]["i"]][0] - 0.03), E - 0.2)
            x0, y0, x1, y1 = lay["slash"]
            L = math.hypot(x1 - x0, y1 - y0)
            ang = math.degrees(math.atan2(-(y1 - y0), x1 - x0))               # ASS 的 \frz 逆时针为正（屏幕的 y 朝下）
            px, py = bx + x0, by + y0
            for th, dy, alpha, delay in ((30, 0, "&H00&", 0.0), (9, 34, "&H40&", 0.03)):   # 一头粗一头尖的刀光（第二版 16 像素像激光线 → 30）；下面再一道细的，晚 0.03 秒
                shape = f"m 0 {-th / 2:.1f} l {L:.1f} 0 l 0 {th / 2:.1f}"
                qx, qy = px - dy * math.sin(math.radians(ang)), py + dy * math.cos(math.radians(ang))
                e = dlg(0, a_big + delay, E, "FX", f"\\an7\\pos({qx:.1f},{qy:.1f})\\org({qx:.1f},{qy:.1f})\\frz{ang:.1f}\\1c{SHARP_RED}\\alpha{alpha}\\bord0\\shad0\\p1"
                        f"\\fscx0\\t(0,90,\\fscx100)\\t(500,900,\\alpha&HB0&)", "")
                if e:
                    out.append(e + shape)
    return out


def fonts_needed(preset: str, lang: str) -> list[str]:
    """渲染时要另外给 libass 的字体文件（不装进系统，ffmpeg 的 ass 滤镜用 fontsdir 读）。"""
    if preset == "凌厉" and lang == "ja":
        return [FONT_FILES[SHARP_BRUSH_JA]]
    if lang != "zh":
        return []
    return {"可爱": [FONT_FILES[CUTE_FONT]], "凌厉": sorted({FONT_FILES[SHARP_BRUSH], FONT_FILES[SHARP_SMALL]})}.get(preset, [])


PRESETS = (*HORIZONTAL, "竖排古风", "可爱", "凌厉")


def write_fx_ass(timing: dict, path: pathlib.Path, preset: str, title: str | None, credit: str | None,
                 images: list[str] | None = None, total: float | None = None, side: str | None = None) -> int:
    """side：left / right 就整首都放那边（判不对的图用；10-02 加的）；不给或 auto = 自动（图里空的那一边）。"""
    if preset not in PRESETS:
        raise SystemExit(f"没有这种特效字幕：{preset}（有：平铺、{'、'.join(PRESETS)}）")
    lang = timing["语言"]
    if preset == "竖排古风" and lang == "en":
        raise SystemExit("竖排古风只给中文、日语的歌用（英文竖着排读不了）")
    family = FONTS.get(lang, "Microsoft YaHei")
    styles = (f"Style: FX,{family},{SIZE},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,{SPACING},0,1,4,2,5,0,0,0,1",
              f"Style: FXV,{V_FONT},{V_SIZE},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,3,1,5,0,0,0,1")
    ev = title_events(timing["行"], title, credit)
    if preset == "竖排古风":
        ev += vertical_events(timing)
    sides = [side] * len(timing["行"]) if side in ("left", "right") else None
    if preset == "可爱":
        ev += cute_events(timing, sides or line_sides(timing["行"], images, total))
    elif preset == "凌厉":
        ev += sharp_events(timing, sides or line_sides(timing["行"], images, total))
    else:
        ev += horizontal_events(timing, preset)
    head = ass_header(lang, styles)
    if preset == "凌厉" and lang in ("zh", "ja"):     # 标题、署名用毛笔字：白字、黑边（标题加红色投影）
        brush = SHARP_BRUSH if lang == "zh" else SHARP_BRUSH_JA
        head = [re.sub(r"^Style: Title,[^,]+,\d+,([^,]+),([^,]+),([^,]+),[^,]+,1,",
                       lambda m: f"Style: Title,{brush},150,{m.group(1)},{m.group(2)},{m.group(3)},&H00{SHARP_RED[2:-1]},0,", h)
                for h in head]
        head = [re.sub(r"^Style: Credit,[^,]+,\d+,", f"Style: Credit,{brush},56,", h) for h in head]
    if preset == "可爱" and lang == "zh":            # 标题、署名也用快乐体：白字、橙色描边
        head = [re.sub(r"^Style: (Title|Credit),[^,]+,(\d+),([^,]+),([^,]+),[^,]+,", lambda m: f"Style: {m.group(1)},{CUTE_FONT},{m.group(2)},{m.group(3)},{m.group(4)},&H00{CUTE_COLORS[0][2:-1]},", h)
                .replace(",1,0,0,0,100,100,4,0,1,5,", ",0,0,0,0,100,100,4,0,1,6,") for h in head]
    path.write_text("\n".join(head + ev) + "\n", encoding="utf-8-sig")
    return len(ev)


# ---------------------------------------------------------------- 排版核对

CAL_LINES = [   # 自己写的句子（不是哪首歌的歌词）；最后一行故意很长，测「放不下就缩小」
    ("zh", list("测试一下特效字幕的位置对不对呀")),
    ("ja", ["これ", "は", "テスト", "の", "文章", "です", "よ", "ね"]),
    ("en", ["The", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]),
    ("zh", list("一二三四五六七八九十百千万亿兆京垓秭穰沟涧正载极恒河沙阿僧祇那由他不可思议")),
]
CAL_TOL = 2          # 每个单位和 libass 自己排的差不超过 2 像素（10-01：中文、日文差 0；英文词与词之间的空格有一点误差，最多差 2）


def calibrate(ffmpeg: str) -> int:
    """同一行：libass 自己排一整行；我们排的每个单位单独画一张。每个单位在整行图里左右挪多少才重合（按列的像素和对齐）= 我们排偏了多少。"""
    import numpy as np
    from PIL import Image
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)

        def render(lines_: list[str], name: str, head_: list[str]) -> "np.ndarray":
            ass = tdp / f"{name}.ass"
            ass.write_text("\n".join(head_ + lines_) + "\n", encoding="utf-8-sig")
            subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d=1",
                            "-vf", f"ass={ass.name}", "-frames:v", "1", f"{name}.png"], cwd=td, check=True)
            return np.asarray(Image.open(tdp / f"{name}.png").convert("L"), dtype=float)[H - 330:H].sum(axis=0)

        for idx, (lang, units) in enumerate(CAL_LINES):
            family = FONTS[lang]
            xs, size = layout_h(units, lang, family)
            sep = " " if lang == "en" else ""
            fs = f"\\fs{size:.1f}" if size < SIZE - 0.05 else ""
            head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
                    "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
                    "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                    f"Style: C,{family},{SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,{SPACING},0,1,0,0,2,120,120,96,1",
                    "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
            whole = render([f"Dialogue: 0,0:00:00.00,0:00:05.00,C,,0,0,0,,{{{fs}}}{sep.join(units)}"], f"w{idx}", head)
            shifts = []
            for j, (u, x) in enumerate(zip(units, xs)):
                one = render([f"Dialogue: 0,0:00:00.00,0:00:05.00,C,,0,0,0,,{{\\an5\\pos({x:.1f},{BOTTOM - size / 2:.1f}){fs}}}{u}"], f"u{idx}_{j}", head)
                cols = np.nonzero(one > 0)[0]
                lo, hi = int(cols.min()), int(cols.max())
                shifts.append(min(range(-12, 13), key=lambda s: float(np.abs(whole[lo + s:hi + s + 1] - one[lo:hi + 1]).sum())))
            worst = max(abs(s) for s in shifts)
            ok = worst <= CAL_TOL
            fails += not ok
            print(f"  {'过' if ok else '不过'}  {family}（{lang}，{len(units)} 个单位{'，放不下、缩到 ' + format(size, '.1f') + ' 号' if fs else ''}）："
                  f"每个单位要挪 {' '.join(f'{s:+d}' for s in shifts)} 像素才和 libass 排的重合，最多差 {worst}")
    print("排版核对：" + ("全过" if fails == 0 else f"{fails} 行不过"))
    return 1 if fails else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--ffmpeg", default=None)
    a = ap.parse_args()
    ffmpeg = a.ffmpeg or json.loads((pathlib.Path(__file__).resolve().parent / "cover_config.json").read_text(encoding="utf-8"))["ffmpeg"]
    if a.calibrate:
        return calibrate(ffmpeg)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
