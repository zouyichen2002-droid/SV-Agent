# -*- coding: utf-8 -*-
"""建造顺序第 6 项：**按段落取音符** —— `gen_melody(scope=段落)` 与 `pick` 的共同底座。

## 为什么这一项是关键

架构文档 §5：**局部修改是归因的前提。** 整首重生成之后，
创作者说「好听了」时无法判断改善来自哪一处 —— 于是诊断层（第 8 项）
拿不到任何可归因的信号，整条「诊断 → 假设 → 度量」的链就断了。

## 段落归属从歌词算，不从工程读

`read_lead` 已经确立了这条：音符按歌词字序一一对应，
所以**段落 → 音符下标区间**完全由歌词决定。工程里没有段落标记，
也不需要有 —— 少一处会和歌词不同步的真相来源。

## 拼接必须保证「没点名的段落逐字段不变」

这是这一项的验收判据。所以拼接是**按下标替换**，
被替换区间之外的音符对象**原样传递**，不重新构造、不重新计算 ——
「重算一遍应该得到一样的结果」在这个项目里已经被证伪过太多次。

## 时间轴对齐

新旧候选用同一份曲式，所以同一段落的时间跨度理应相同。
但**理应不等于实测**，所以拼接后会把新段落整体平移到旧段落的起点，
并把实际跨度差报出来。差得多就说明曲式假设不成立，
应该看见它而不是让它变成一处静音或一处重叠。
"""
from __future__ import annotations

from dataclasses import dataclass, field

QUARTER_BLICKS = 705600000


@dataclass
class Span:
    """一个段落占的音符下标区间 `[i0, i1)`。"""
    name: str
    i0: int
    i1: int
    n_chars: int

    @property
    def n_notes(self) -> int:
        return self.i1 - self.i0


@dataclass
class SpliceReport:
    """拼接改了什么。**这是「改动高亮」的数据来源。**"""
    sections: list[str] = field(default_factory=list)
    n_replaced: int = 0
    n_kept: int = 0
    shift_blicks: dict = field(default_factory=dict)
    span_delta_beats: dict = field(default_factory=dict)
    bars: dict = field(default_factory=dict)

    def describe(self) -> str:
        out = [f"替换 {len(self.sections)} 段 / {self.n_replaced} 音符，"
               f"其余 {self.n_kept} 个逐字段不变"]
        for s in self.sections:
            d = self.span_delta_beats.get(s, 0.0)
            b = self.bars.get(s)
            out.append(f"    {s}　小节 {b[0]}–{b[1]}" if b else f"    {s}")
            if abs(d) > 0.01:
                out[-1] += f"　跨度变化 {d:+.2f} 拍"
        return "\n".join(out)


def spans(ver) -> list[Span]:
    """歌词版本 → 每个段落的音符下标区间。

    **唯一的段落归属实现。** `read_lead` 按同一条规则消费音符
    （一个字一个音符，按段按句顺序），所以两者必然一致。
    """
    out, idx = [], 0
    for sec_name, lines in ver.sections:
        n = sum(len(text) for text, _chord in lines)
        out.append(Span(sec_name, idx, idx + n, n))
        idx += n
    return out


def bars_of(form, name: str) -> tuple[int, int] | None:
    """段落在曲式里占第几到第几小节（1 起，闭区间）。给「改动高亮」用。"""
    bar = 0
    for sec, nb in form:
        if sec == name:
            return (bar + 1, bar + nb)
        bar += nb
    return None


def match(spans_: list[Span], scope) -> list[Span]:
    """按段名**前缀**匹配 —— 「副歌」命中「副歌1」「副歌2」。

    与 `step3_melody` 的 `--harmony-sections` 同一条规则。
    一个都没命中要**报错**，不能静默返回空 ——
    「我改了副歌」和「我什么都没改」必须区分得开。
    """
    if isinstance(scope, str):
        scope = [scope]
    hit = [s for s in spans_ if any(s.name.startswith(x) for x in scope)]
    if not hit:
        raise ValueError(f"段落 {list(scope)} 一个都没命中。"
                         f"现有段落：{[s.name for s in spans_]}")
    return hit


# ---- 两种载体，一个实现 --------------------------------------------------
# `.svp` 的原始 dict（onset/duration 单位 blick）与 melodize 的 `Note` 对象
# （onset_beats/duration_beats 单位拍）都要能拼。写两遍必然分叉，
# 所以在这里统一成三个存取器，拼接逻辑只有一份。

def _onset(n):
    return n["onset"] if isinstance(n, dict) else n.onset_beats


def _dur(n):
    return n["duration"] if isinstance(n, dict) else n.duration_beats


def _shifted(n, d):
    if isinstance(n, dict):
        return dict(n, onset=n["onset"] + d)
    import dataclasses
    return dataclasses.replace(n, onset_beats=n.onset_beats + d)


def _unit(n) -> float:
    """把该载体的时间单位换算成拍，用于报告。"""
    return 1.0 if not isinstance(n, dict) else 1.0 / QUARTER_BLICKS


def splice(current: list, new: list, scope, ver, form=None):
    """把 `new` 里点名段落的音符换进 `current`。→ (音符表, SpliceReport)

    两边可以是 `.svp` 的 dict，也可以是 `checks.Note`，但必须同一种。
    **区间外的元素原样传递（同一个对象），不复制、不重算。**
    """
    if len(current) != len(new):
        raise ValueError(f"两边音符数不同（{len(current)} vs {len(new)}）"
                         f"—— 说明它们不同源，拼接会错位")
    sp = spans(ver)
    total = sp[-1].i1 if sp else 0
    if total != len(current):
        raise ValueError(f"歌词 {total} 字，工程 {len(current)} 音符 —— 不同源")

    targets = match(sp, scope)
    rep = SpliceReport(sections=[s.name for s in targets])
    out = list(current)

    for s in targets:
        old = current[s.i0:s.i1]
        cand = new[s.i0:s.i1]
        if not old or not cand:
            continue
        shift = _onset(old[0]) - _onset(cand[0])
        moved = [_shifted(n, shift) for n in cand]
        out[s.i0:s.i1] = moved

        old_span = _onset(old[-1]) + _dur(old[-1]) - _onset(old[0])
        new_span = _onset(moved[-1]) + _dur(moved[-1]) - _onset(moved[0])
        rep.shift_blicks[s.name] = shift
        rep.span_delta_beats[s.name] = round(
            (new_span - old_span) * _unit(old[0]), 3)
        rep.n_replaced += len(moved)
        if form:
            b = bars_of(form, s.name)
            if b:
                rep.bars[s.name] = b

    rep.n_kept = len(out) - rep.n_replaced
    return out, rep


def diff_sections(before: list, after: list, ver, form=None) -> SpliceReport:
    """比较两份音符表，报出**哪些段落变了、变了几个音符**。

    改动高亮的数据来源。**从文件现算，不解析任何脚本输出** ——
    真正的改动由 `.svp` 决定，打印出来的话只是打印出来的话。
    """
    rep = SpliceReport()
    if len(before) != len(after):
        rep.sections = ["（音符数变了，无法按段落对齐）"]
        rep.n_replaced = len(after)
        return rep
    for s in spans(ver):
        a, b = before[s.i0:s.i1], after[s.i0:s.i1]
        if a == b:
            rep.n_kept += len(a)
            continue
        rep.sections.append(s.name)
        rep.n_replaced += len(b)
        if a and b:
            old_span = _onset(a[-1]) + _dur(a[-1]) - _onset(a[0])
            new_span = _onset(b[-1]) + _dur(b[-1]) - _onset(b[0])
            rep.span_delta_beats[s.name] = round(
                (new_span - old_span) * _unit(a[0]), 3)
        if form:
            bars = bars_of(form, s.name)
            if bars:
                rep.bars[s.name] = bars
    return rep


def unchanged_outside(before: list[dict], after: list[dict], scope, ver) -> bool:
    """点名段落之外的音符是否**逐字段**未变。这一项的验收判据。"""
    sp = spans(ver)
    hit = {id(s) for s in match(sp, scope)}
    for s in sp:
        if id(s) in hit:
            continue
        if before[s.i0:s.i1] != after[s.i0:s.i1]:
            return False
    return True
