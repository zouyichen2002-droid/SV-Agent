"""LRC 歌词解析。

**歌词属第三方版权内容。** 本模块把文本读进内存供对齐使用，
但任何报告/日志都只输出时间与字数，不输出歌词文本。`.lrc` 已被 .gitignore 排除。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_HAN = re.compile(r"[一-鿿]")

# 制作名单行。判据是「行首 1–8 个非冒号字符后紧跟冒号」，中英文都要认。
#
# 第一版只写了 `^[A-Za-z][A-Za-z ./&]*[:：]`，只认拉丁字母开头，
# 于是《潮声回响》前 10 行的中文名单全部漏过，被当成演唱行：
#   作词 ：大九_LN / 作曲 ：李建衡 / 编曲 ：… / 制作人 ：… / 吉他：RK
#   和声 ：刘潇阳 李建衡 罗文 / 调声 ：… / 混音/母带 ：… / 监制 ：… / 策划 ：…
# 结果演唱行数是 52 而非 42。声学侧当时已经测出那 10 行（2.45–13.11s）没有人声，
# 但把原因记成「未解释」—— 真因就是它们不是唱的。
#
# 注意 `和声 ：刘潇阳 李建衡 罗文` 这行：它含「和声」二字但不是和声演唱行，
# 名单判定必须先于和声判定。
_META = re.compile(r"^[^:：\s]{1,8}\s*[:：]")

# 行尾混入的分类标签之类的杂物。《潮声回响》最后一行是
# 「在真实中 光与影都自由 计算机与视频游戏」，尾部 8 个字是分类标签，
# 不剔掉会把该行字数从 10 记成 18。
_TRAILING_JUNK = ("计算机与视频游戏",)


@dataclass(frozen=True)
class LyricLine:
    index: int
    t_s: float
    is_harmony: bool
    chars: tuple[str, ...] = field(repr=False)

    @property
    def n_chars(self) -> int:
        return len(self.chars)

    def __str__(self) -> str:  # 刻意不含歌词文本
        kind = "和声" if self.is_harmony else "主唱"
        return f"L{self.index:02d} {self.t_s:7.2f}s {kind} {self.n_chars:2d}字"


def parse(path: str | Path, skip_before_s: float = 0.0) -> list[LyricLine]:
    """按时间排序的演唱行。

    判定规则（与 specs/benchmark-facts-chaosheng.md §6 一致）：
    - 必须有 `[mm:ss.xx]` 时间戳且含汉字
    - 形如 `xx:` 的元数据行剔除
    - 含 `(` 或 `（` 的算和声行
    - `skip_before_s` 之前的整行丢弃（《潮声回响》前 10 行经判定在本 render 里无人声）
    """
    rows: list[tuple[float, bool, tuple[str, ...]]] = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        s = raw.strip()
        m = _TS.match(s)
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        text = _TS.sub("", s).strip()
        # 名单判定必须在和声判定之前：`和声 ：刘潇阳 …` 含「和声」但不是演唱行
        if _META.match(text):
            continue
        for junk in _TRAILING_JUNK:
            if text.endswith(junk):
                text = text[: -len(junk)].rstrip()
        han = tuple(_HAN.findall(text))
        if not han:
            continue
        if t < skip_before_s:
            continue
        rows.append((t, ("(" in text or "（" in text), han))
    rows.sort(key=lambda r: r[0])
    return [LyricLine(i, t, h, c) for i, (t, h, c) in enumerate(rows)]


def summary(lines: list[LyricLine]) -> str:
    main = [l for l in lines if not l.is_harmony]
    harm = [l for l in lines if l.is_harmony]
    return (f"演唱行 {len(lines)} = 主唱 {len(main)}行/{sum(l.n_chars for l in main)}字"
            f" + 和声 {len(harm)}行/{sum(l.n_chars for l in harm)}字"
            f"   {lines[0].t_s:.2f}–{lines[-1].t_s:.2f}s" if lines else "无演唱行")
