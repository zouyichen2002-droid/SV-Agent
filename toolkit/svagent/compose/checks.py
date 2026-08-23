"""对「歌词 + 旋律」这一对做可程序化的音乐性检查。

## 为什么这个模块存在

线 1 的失败教训（ADR-0006）：我设计的门槛全是**逐项局部指标**，全绿而人耳判否。
缺的是能感知**整体**的判据。这个模块补的就是那一类，同时把「算术类」问题
从人耳的工作量里拿掉 —— 创作者应该只判音乐性，不该去数字数、查音域、听倒字。

## 七项检查，分两类

**客观类**（对错分明，超了就是错）

| 检查 | 判据 |
|---|---|
| `count` | 字数 = 非拖腔音符数 |
| `range` | 每个音符在声库舒适音域内 |
| `leap` | 相邻音程不超阈值 |
| `scale` | 调内音比例达标；调外音逐个列出 |
| `cadence` | 句末落音在当前和弦的和弦音上 |
| `phrase` | 乐句内没有异常缺口（**线 1 缺的正是这一类**） |

**启发类**（只缩小范围，不下结论）

| 检查 | 判据 |
|---|---|
| `prosody` | 倒字风险打分 |

## 倒字这一项必须说清它的性质

**它是启发式，不是定理。** 声调与旋律的冲突是否真的让人听错字，
受上下文、语速、演唱者咬字、听者预期共同影响，没有一个封闭的规则集能算准。

所以本实现的定位是：**把 300 个字缩小到 10 个值得你去听的字**。
它的权重和阈值全部可配，并且**应当按创作者的实际否决反馈来校准** ——
这与「门槛前期由人定、改到认可为止」是同一件事。

规则的方向性依据（汉语声调轮廓）：

| 声调 | 轮廓 | 与旋律冲突的形态 |
|---|---|---|
| 1 阴平 | 高平 | 大跳（任意方向）会削弱平稳感，轻度 |
| 2 阳平 | 上升 | 配**下行**易听成 4 声 |
| 3 上声 | 低降升 | 放在乐句最高音、或配大上行，别扭 |
| 4 去声 | 下降 | 配**上行**易听成 2 声 |
| 0 轻声 | 短弱 | 基本不受影响，不计分 |

**字内**（一个字占多个音符，即拖腔）的冲突比**字间**更强：
同一个字内部的音高走向直接对抗声调轮廓，听者没有重新归一化的机会。
所以字内权重更高。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 大调 / 自然小调的音阶度数（半音）
MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
SUSTAIN = "-"          # 拖腔承接音符的歌词标记（与 SynthV 一致）


def note_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


@dataclass
class Note:
    """一个音符。时间用拍（beat）表示，与 tempo 解耦。"""

    index: int
    onset_beats: float
    duration_beats: float
    midi: int
    lyric: str              # 汉字，或 SUSTAIN 表示承接前一个字

    @property
    def end_beats(self) -> float:
        return self.onset_beats + self.duration_beats

    @property
    def is_sustain(self) -> bool:
        return self.lyric == SUSTAIN


@dataclass
class Phrase:
    """一个乐句。`chord_root` / `chord_quality` 用于句末落音检查。"""

    index: int
    note_from: int          # 起始音符下标（含）
    note_to: int            # 结束音符下标（不含）
    chord_root: int | None = None       # 0=C … 11=B
    chord_quality: str = "major"        # major / minor


@dataclass
class Finding:
    kind: str               # count / range / leap / scale / cadence / phrase / prosody
    severity: str           # block / warn / info
    where: str
    detail: str
    score: float = 0.0
    # 涉及的音符下标。`where` 是给人读的，**不要去正则解析它** ——
    # 自修复循环靠这个字段定位要改哪个音符。空元组表示这是全局问题。
    # 放在 score 之后，因为 prosody 是按位置传 score 的。
    targets: tuple[int, ...] = ()

    def __str__(self) -> str:
        s = f"[{self.severity:5s}] {self.kind:8s} {self.where:<14} {self.detail}"
        return s + (f"  (分 {self.score:.2f})" if self.score else "")


@dataclass
class ProsodyCfg:
    """倒字风险的权重与阈值。**全部需要按创作者反馈校准。**"""

    # 字间：本字音符 → 下一字音符 的音程（半音）
    # 阈值由「在专业发行曲上的标记率」定标，见类末尾的实测表
    between_min_semitones: float = 4.0
    w_tone4_up: float = 1.0                # 4 声配上行
    w_tone2_down: float = 1.0              # 2 声配下行
    w_tone3_up: float = 0.6                # 3 声配大上行
    w_tone1_leap: float = 0.3              # 1 声配大跳（任意方向）
    # 字内：同一个字跨多个音符时的内部走向
    # **3.0 不是 2.0**：一个字内部 ±2 半音的移动是普通的颤音/转音/装饰音，
    # 不是声调反转。实测把它从 2.0 提到 3.0，字内触发从 11 降到 2，
    # 再提到 4.0 无变化 —— 说明那 9 个多出来的标记全是恰好 2 半音的装饰音。
    within_min_semitones: float = 3.0
    within_multiplier: float = 1.8         # 字内比字间更强
    # 3 声落在乐句最高音
    w_tone3_peak: float = 0.5
    # 报警门槛
    flag_at: float = 0.8

    # ---- 定标依据（2026-08-22）----
    # 样本：《潮声回响》33 个主唱行 / 284 字，配轨5 的转写旋律。
    # 这是**专业发行曲**，词是听得懂的，所以标记率越低越好（全是误报）。
    #
    #   字内阈值  字间阈值   标记率   字内触发  字间触发
    #      2.0      3.0     7.0%       11        10
    #      3.0      3.0     4.2%        2        10
    #    → 3.0      4.0     2.8%        2         6   ← 采用
    #      4.0      5.0     2.8%        2         6
    #
    # 2.8% 意味着把 284 个字缩到 8 个值得人去听的，这是这个检查器的正确用法。
    # **两条限制**：(1) 样本只有一首歌；(2) 旋律是转写的，转写噪声会专门抬高
    # 「字内」这一类的触发 —— 这也是把字内阈值定在 3.0 的第二个理由。


@dataclass
class CheckCfg:
    # 星尘（五维介质·星尘）的舒适音域，创作者给的是「A2–F#4」。
    # **他用的是 A2 = MIDI 57 的记法**，比「中央C = C4」惯例低一个八度。
    # 交叉验证：他自己写/改过的轨1（174 音符）实测音域恰好是 MIDI 57–78，
    # 跨度 21 半音，与「A2–F#4」的 21 半音严丝合缝。所以是 57–78 而不是 45–66。
    range_lo: int = 57                     # 他记作 A2；C4惯例下是 A3，220.0Hz
    range_hi: int = 78                     # 他记作 F#4；C4惯例下是 F#5，740.0Hz
    range_edge_semitones: int = 2          # 距边界这么近就提醒
    leap_max_semitones: int = 9            # 大六度
    scale_in_key_min: float = 0.90
    phrase_gap_max_beats: float = 1.0      # 乐句内相邻音符的最大间隔
    prosody: ProsodyCfg = field(default_factory=ProsodyCfg)


# ---------------------------------------------------------------- 声调

def tones_of(text: str) -> list[tuple[str, int, str]]:
    """返回 [(字, 声调, 拼音)]。声调 0 表示轻声/无调。

    多音字由 pypinyin 按上下文解（实测 重新→chong2、重量→zhong4），
    所以**必须整句一起传**，逐字调用会丢上下文。
    """
    from pypinyin import Style, pinyin

    chars = [c for c in text if "一" <= c <= "鿿"]
    if not chars:
        return []
    py = pinyin("".join(chars), style=Style.TONE3)
    out = []
    for c, p in zip(chars, py):
        s = p[0]
        t = int(s[-1]) if s and s[-1].isdigit() else 0
        out.append((c, t, s))
    return out


# ---------------------------------------------------------------- 客观检查

def check_count(notes: list[Note], text: str) -> list[Finding]:
    n_char = len([c for c in text if "一" <= c <= "鿿"])
    n_note = len([n for n in notes if not n.is_sustain])
    if n_char == n_note:
        return []
    return [Finding("count", "block", "整体",
                    f"字数 {n_char} ≠ 非拖腔音符数 {n_note}"
                    f"（差 {n_note - n_char:+d}）")]


def check_range(notes: list[Note], cfg: CheckCfg) -> list[Finding]:
    out = []
    for n in notes:
        if n.midi < cfg.range_lo or n.midi > cfg.range_hi:
            out.append(Finding("range", "block", f"音符 {n.index}",
                               f"{note_name(n.midi)} 越界"
                               f"（舒适区 {note_name(cfg.range_lo)}–"
                               f"{note_name(cfg.range_hi)}）",
                               targets=(n.index,)))
        elif (n.midi - cfg.range_lo < cfg.range_edge_semitones
              or cfg.range_hi - n.midi < cfg.range_edge_semitones):
            out.append(Finding("range", "warn", f"音符 {n.index}",
                               f"{note_name(n.midi)} 贴边，长音会吃力",
                               targets=(n.index,)))
    return out


def _phrase_of(phrases: list[Phrase], n: int) -> list[int]:
    """音符下标 → 所属乐句号；不属于任何乐句的记 -1。"""
    owner = [-1] * n
    for ph in phrases:
        for i in range(max(0, ph.note_from), min(n, ph.note_to)):
            owner[i] = ph.index
    return owner


def check_leap(notes: list[Note], cfg: CheckCfg,
               phrases: list[Phrase] | None = None) -> list[Finding]:
    """相邻音程。**跨乐句的不算。**

    实测教训：不做乐句隔离时，段落之间的休止（例如副歌到主歌之间的 2 小节间奏）
    会被当成一个 11 半音的跳进报出来。听者在气口处根本不会把两段连起来听，
    那不是跳进。同一个错也出现在 prosody 的「字间」规则上。
    """
    out = []
    owner = _phrase_of(phrases, len(notes)) if phrases else None
    for i, (a, b) in enumerate(zip(notes, notes[1:])):
        if owner is not None and owner[i] != owner[i + 1]:
            continue
        d = b.midi - a.midi
        if abs(d) > cfg.leap_max_semitones:
            out.append(Finding("leap", "warn", f"音符 {a.index}→{b.index}",
                               f"{note_name(a.midi)}→{note_name(b.midi)} "
                               f"跳 {abs(d)} 半音（上限 {cfg.leap_max_semitones}）",
                               targets=(a.index, b.index)))
    return out


def check_scale(notes: list[Note], key_root: int, quality: str,
                cfg: CheckCfg) -> list[Finding]:
    scale = MAJOR if quality == "major" else MINOR
    outside = [n for n in notes if (n.midi - key_root) % 12 not in scale]
    if not notes:
        return []
    ratio = 1.0 - len(outside) / len(notes)
    out = []
    if ratio < cfg.scale_in_key_min:
        out.append(Finding("scale", "warn", "整体",
                           f"调内音只占 {100*ratio:.1f}%"
                           f"（门槛 {100*cfg.scale_in_key_min:.0f}%），"
                           f"{len(outside)} 个调外音"))
    for n in outside[:12]:
        out.append(Finding("scale", "info", f"音符 {n.index}",
                           f"{note_name(n.midi)} 不在 "
                           f"{NAMES[key_root]}{'大调' if quality=='major' else '小调'} 内",
                           targets=(n.index,)))
    return out


def check_cadence(notes: list[Note], phrases: list[Phrase]) -> list[Finding]:
    out = []
    for ph in phrases:
        # 边界检查：音符列表与乐句下标失同步时要**报告**，不能崩。
        # 实测教训：灵敏度测试里删掉一个音符，这里直接 IndexError ——
        # 检查器崩掉等于没有检查，比漏报更糟。
        if ph.note_to > len(notes) or ph.note_from >= len(notes):
            out.append(Finding("cadence", "block", f"乐句 {ph.index}",
                               f"乐句下标 [{ph.note_from},{ph.note_to}) 超出音符数 "
                               f"{len(notes)}，无法检查"))
            continue
        if ph.chord_root is None or ph.note_to <= ph.note_from:
            continue
        last = notes[ph.note_to - 1]
        triad = (0, 4, 7) if ph.chord_quality == "major" else (0, 3, 7)
        if (last.midi - ph.chord_root) % 12 not in triad:
            out.append(Finding("cadence", "warn", f"乐句 {ph.index}",
                               f"句末 {note_name(last.midi)} 不在 "
                               f"{NAMES[ph.chord_root]}{ph.chord_quality} 的和弦音上",
                               targets=(last.index,)))
    return out


def check_phrase(notes: list[Note], phrases: list[Phrase],
                 cfg: CheckCfg) -> list[Finding]:
    """乐句内的异常缺口。**这是线 1 完全没有的那一类判据。**

    线 1 的产出里一句有 87% 的字有音符，逐项指标很好，
    但缺的那几个字会把乐句撕开 —— 人听的是句子，不是音符。
    """
    out = []
    for ph in phrases:
        if ph.note_to > len(notes) or ph.note_from >= len(notes):
            out.append(Finding("phrase", "block", f"乐句 {ph.index}",
                               f"乐句下标 [{ph.note_from},{ph.note_to}) 超出音符数 "
                               f"{len(notes)}，无法检查"))
            continue
        seg = notes[ph.note_from:ph.note_to]
        for a, b in zip(seg, seg[1:]):
            gap = b.onset_beats - a.end_beats
            if gap > cfg.phrase_gap_max_beats:
                out.append(Finding("phrase", "warn", f"乐句 {ph.index}",
                                   f"音符 {a.index}→{b.index} 之间空 "
                                   f"{gap:.2f} 拍，乐句被撕开",
                                   targets=(a.index, b.index)))
    return out


# ---------------------------------------------------------------- 倒字

def check_prosody(notes: list[Note], text: str, cfg: CheckCfg,
                  phrases: list[Phrase] | None = None) -> list[Finding]:
    """倒字风险。**启发式**，作用是缩小范围而不是下结论，见模块 docstring。

    `phrases` 给了就只在**乐句内**算「字间」音程 —— 跨乐句有气口，
    听者会重新归一化，那里的音程不构成倒字。见 check_leap 的同类说明。
    """
    P = cfg.prosody
    toned = tones_of(text)
    # 把音符按字分组：非拖腔音符开一个新字，后续 SUSTAIN 归到它
    groups: list[list[Note]] = []
    for n in notes:
        if n.is_sustain and groups:
            groups[-1].append(n)
        elif not n.is_sustain:
            groups.append([n])
    if len(groups) != len(toned):
        return [Finding("prosody", "block", "整体",
                        f"字数 {len(toned)} 与字组数 {len(groups)} 不符，"
                        f"无法逐字评估（先修 count）")]
    if not groups:
        return []
    peak = max(n.midi for n in notes)
    # 每个字组归属哪个乐句（用组内第一个音符的下标判定）
    owner = _phrase_of(phrases, len(notes)) if phrases else None
    grp_owner = [owner[g[0].index] if owner and g[0].index < len(owner) else 0
                 for g in groups]

    out = []
    for i, ((ch, tone, py), grp) in enumerate(zip(toned, groups)):
        if tone == 0:
            continue          # 轻声不计
        score = 0.0
        why: list[str] = []

        # 字内走向（拖腔）
        if len(grp) > 1:
            d = grp[-1].midi - grp[0].midi
            if abs(d) >= P.within_min_semitones:
                if tone == 4 and d > 0:
                    score += P.w_tone4_up * P.within_multiplier
                    why.append(f"字内上行 {d:+d} 半音，对抗 4 声的降")
                elif tone == 2 and d < 0:
                    score += P.w_tone2_down * P.within_multiplier
                    why.append(f"字内下行 {d:+d} 半音，对抗 2 声的升")

        # 字间：到下一个字的音程（同一乐句内才算）
        if i + 1 < len(groups) and (owner is None
                                    or grp_owner[i] == grp_owner[i + 1]):
            d = groups[i + 1][0].midi - grp[-1].midi
            if abs(d) >= P.between_min_semitones:
                if tone == 4 and d > 0:
                    score += P.w_tone4_up
                    why.append(f"后接上行 {d:+d} 半音，4 声易听成 2 声")
                elif tone == 2 and d < 0:
                    score += P.w_tone2_down
                    why.append(f"后接下行 {d:+d} 半音，2 声易听成 4 声")
                elif tone == 3 and d > 0:
                    score += P.w_tone3_up
                    why.append(f"后接上行 {d:+d} 半音，3 声别扭")
                elif tone == 1:
                    score += P.w_tone1_leap
                    why.append(f"后接大跳 {d:+d} 半音，削弱 1 声的平稳")

        # 3 声落在乐句最高音
        if tone == 3 and grp[0].midi == peak:
            score += P.w_tone3_peak
            why.append("3 声落在最高音上")

        if score >= P.flag_at:
            out.append(Finding("prosody", "warn", f"第{i+1}字「{ch}」",
                               f"{py}（{tone}声）· " + "；".join(why), score,
                               targets=tuple(x.index for x in grp)))
    return out


# ---------------------------------------------------------------- 汇总

def run_all(notes: list[Note], text: str, key_root: int, quality: str,
            phrases: list[Phrase], cfg: CheckCfg | None = None
            ) -> list[Finding]:
    cfg = cfg or CheckCfg()
    fs: list[Finding] = []
    fs += check_count(notes, text)
    fs += check_range(notes, cfg)
    fs += check_leap(notes, cfg, phrases)
    fs += check_scale(notes, key_root, quality, cfg)
    fs += check_cadence(notes, phrases)
    fs += check_phrase(notes, phrases, cfg)
    fs += check_prosody(notes, text, cfg, phrases)
    order = {"block": 0, "warn": 1, "info": 2}
    return sorted(fs, key=lambda f: (order[f.severity], -f.score, f.kind))


def summarize(fs: list[Finding]) -> str:
    n_b = sum(1 for f in fs if f.severity == "block")
    n_w = sum(1 for f in fs if f.severity == "warn")
    n_i = sum(1 for f in fs if f.severity == "info")
    verdict = "不可写入（有 block）" if n_b else ("可写入，但有待看的告警" if n_w
                                                else "全部通过")
    by: dict[str, int] = {}
    for f in fs:
        by[f.kind] = by.get(f.kind, 0) + 1
    return (f"{verdict}   block {n_b} · warn {n_w} · info {n_i}\n"
            f"  分项: " + "  ".join(f"{k} {v}" for k, v in sorted(by.items())))
