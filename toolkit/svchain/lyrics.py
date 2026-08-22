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
# 形如 "ti:" "Vocal:" "作曲 :" 的元数据行
_META = re.compile(r"^[A-Za-z][A-Za-z ./&]*[:：]")


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
        han = tuple(_HAN.findall(text))
        if not han or _META.match(text):
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
