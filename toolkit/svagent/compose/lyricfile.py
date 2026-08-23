"""读创作者手改的歌词文本文件。

## 为什么歌词要放在纯文本里

工作流（`specs/workflow.md`）步骤 2 明确「**在文本编辑器中做**」。
之前歌词写在 `songs/yequ/lyrics.py` 里是 Python 数据结构 ——
创作者不写代码，改一个字要动 Python 字面量，这是个不该有的门槛。

纯文本的代价是要写解析器，收益是**他改完直接生效，不经过我**。
这在整条链上是唯一一处「创作者直接编辑机器输入」的地方，值得为它写代码。

## 格式

    ## A ｜标题
    主旨：一句话

    主歌
      Am  歌词一行
      F   歌词一行

    副歌
      C   歌词一行

规则：

- `## 版本号 ｜标题` 开一个新版本（全角或半角竖线都认）
- `主旨：` 后面是这一版的一句话主旨，可省
- 单独一行的段名（主歌/副歌/预副/桥段…）开一个新段落
- 缩进行 = `和弦<空白>歌词`
- `#`（单个）开头、以及 `---` 分隔线，都是注释，忽略
- 空行忽略

## 容错的取向：**报错，不猜**

歌词是创作者手写的，格式错误必然发生。但**静默跳过一行比报错糟得多** ——
少一行词会让 `count` 检查失败，而他不知道为什么。
所以每一处无法解析的内容都收集成 `Problem` 一起报出来。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CHORDS = ("Am", "Dm", "Em", "C", "F", "G")
SECTION_WORDS = ("主歌", "副歌", "预副", "桥段", "间奏", "前奏", "尾奏", "副歌2")

_VERSION = re.compile(r"^##\s*(\S+?)\s*[｜|]\s*(.*)$")
_GIST = re.compile(r"^主旨[：:]\s*(.*)$")
_LINE = re.compile(r"^\s+(" + "|".join(CHORDS) + r")\s+(\S.*)$")


@dataclass
class Problem:
    lineno: int
    text: str
    why: str

    def __str__(self) -> str:
        return f"第 {self.lineno} 行：{self.why}　|{self.text}|"


@dataclass
class Version:
    key: str                        # A / B / …
    title: str
    gist: str = ""
    sections: list = field(default_factory=list)   # [(段名, [(歌词, 和弦)])]

    @property
    def n_chars(self) -> int:
        return sum(len(t) for _, lines in self.sections for t, _ in lines)

    @property
    def n_lines(self) -> int:
        return sum(len(lines) for _, lines in self.sections)

    def as_candidate(self):
        """转成 melodize 认的形状：(名字, 主旨, [(段名, [(歌词, 和弦)])])。"""
        return (f"{self.key}｜{self.title}", self.gist, self.sections)


def parse(path: Path | str) -> tuple[dict[str, Version], list[Problem]]:
    """→ ({版本号: Version}, [解析问题])。"""
    # utf-8-sig：文件带 BOM（为了中文 Windows 的记事本不乱码），
    # 用 utf-8 读会把 BOM 当成正文第一个字符，第一行就解析不了。
    text = Path(path).read_text(encoding="utf-8-sig")
    versions: dict[str, Version] = {}
    problems: list[Problem] = []
    cur: Version | None = None
    sec: str | None = None

    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        # 注释与分隔线
        if stripped.startswith("---") or (stripped.startswith("#")
                                          and not stripped.startswith("##")):
            continue

        m = _VERSION.match(stripped)
        if m:
            cur = Version(key=m.group(1), title=m.group(2).strip())
            versions[cur.key] = cur
            sec = None
            continue

        if cur is None:
            continue                      # 头部说明文字

        m = _GIST.match(stripped)
        if m:
            cur.gist = m.group(1).strip()
            continue

        # 段名：不缩进、且是已知段落词
        if line[:1] not in " \t" and any(stripped.startswith(w)
                                         for w in SECTION_WORDS):
            sec = stripped
            cur.sections.append((sec, []))
            continue

        m = _LINE.match(line)
        if m:
            if sec is None:
                problems.append(Problem(i, stripped, "歌词出现在段名之前"))
                continue
            cur.sections[-1][1].append((m.group(2).strip(), m.group(1)))
            continue

        # 还没进入任何段落、又不缩进 → 当作主旨的续行。
        # 主旨可以写好几行（实测我自己就写了两行，被误报成格式错误）。
        # 这样宽容是安全的：主旨不参与演唱，认错了也不会丢词。
        if sec is None and line[:1] not in " \t":
            cur.gist = (cur.gist + " " + stripped).strip()
            continue

        # 缩进了但没匹配上 —— 大概率是和弦名写错
        if line[:1] in " \t":
            first = stripped.split()[0] if stripped.split() else ""
            why = (f"和弦「{first}」不在 {'/'.join(CHORDS)} 里"
                   if first not in CHORDS else "格式是「和弦<空格>歌词」")
            problems.append(Problem(i, stripped, why))
        else:
            problems.append(Problem(i, stripped, "无法识别（段名？请检查拼写）"))

    return versions, problems


def lint(versions: dict[str, Version], *, lo: int = 7, hi: int = 11
         ) -> list[Problem]:
    """字数与结构的体检。不查音乐性 —— 那是 checks.py 的事。"""
    out = []
    for key, v in versions.items():
        if not v.sections:
            out.append(Problem(0, key, "这一版没有任何段落"))
        for sec, lines in v.sections:
            if not lines:
                out.append(Problem(0, f"{key}/{sec}", "这一段没有歌词"))
            for t, _c in lines:
                n = len(t)
                if not (lo <= n <= hi):
                    out.append(Problem(0, f"{key}/{sec}｜{t}",
                                       f"{n} 字，建议 {lo}–{hi}"))
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    p = (sys.argv[1] if len(sys.argv) > 1
         else r"E:\sv-bridge\songs\xiaofeng\lyrics.txt")
    vs, probs = parse(p)
    print(f"{p}\n解析出 {len(vs)} 版\n")
    for k, v in vs.items():
        print(f"── {k}｜{v.title}　{v.n_lines} 句 / {v.n_chars} 字")
        print(f"   {v.gist}")
        for sec, lines in v.sections:
            chords = "–".join(c for _, c in lines)
            print(f"   {sec}　{chords}")
    if probs:
        print(f"\n✗ 解析问题 {len(probs)} 处：")
        for x in probs:
            print("  ", x)
    warn = lint(vs)
    if warn:
        print(f"\n⚠ 字数/结构提醒 {len(warn)} 处：")
        for x in warn:
            print("  ", x)
    if not probs and not warn:
        print("\n✓ 格式与字数全部通过")
