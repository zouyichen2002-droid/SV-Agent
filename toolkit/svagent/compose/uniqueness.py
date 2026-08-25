"""**独特性检查**：和已有作品有多像。它**不在 `run_all` 里**。

不按序号称呼它 —— 序号会变。`chord_fit` 进 `run_all` 之后
「第八项」就指向别的东西了，而文档里的旧编号不会自己更新。

## 为什么必须先有这个

2026-08-23 创作者听完《夜曲》四个候选的判断：
**「旋律和上一首《宇宙无边无垠》非常像，这是一个不好的情况」**。

八项检查全过、代价 0，而人耳判「像」—— 因为**检查器里没有「独特性」这个维度**。
这与 ADR-0006 是同一类失败：门槛全绿而人耳判否，缺的是没被表达出来的判据。

**先做度量，再做修法。** 没有度量，任何「让它不那么像」的改动都无法验证是否真的有效
（ADR-0009「工具先于特性」同一条逻辑）。

## 实测的相似度（《夜曲A》vs《宇宙无边无垠》）

    时长分布   0.987   ← 根因：_line_rhythm() 是一个公式，所有歌所有句子共用
    音级分布   0.965      同调同音区，主歌 59–67 只有 6 个调内音
    音程分布   0.887      「优先靠近轮廓目标」的步进偏好

节奏型甚至逐句相同：《夜曲》四句全是 `[0.5]*n + [长音]`。

## 四个维度，为什么是这四个

| 维度 | 抓什么 | 为什么单独算 |
|---|---|---|
| `rhythm` | 时长分布 | 实测最大的雍同来源；也最容易改 |
| `interval` | 相邻音程分布 | 旋律的「手势」，比绝对音高更贴近听感 |
| `pitch_class` | 音级分布 | 调性与音区的重合 |
| `cell` | 逐句节奏型的**集合重合率** | 分布相似还可能是巧合，句型逐字相同就是同一个模板 |

分开报是刻意的：合成一个总分会掩盖「到底哪一维在雍同」，
而修法必须对着具体那一维去做。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .checks import Finding, Note, Phrase

# 门槛。**这些是初始值，需要按创作者反馈校准** —— 与 ProsodyCfg 同样的性质。
# 依据：实测两首「非常像」的歌是 rhythm 0.987 / pitch 0.965 / interval 0.887。
#
# **pitch_class 已知是个弱判据，故意放宽到 0.97。** 理由：A 小调与 E 小调
# 共享 7 个音级里的 6 个（只差 F/F#），所以两首**完全不同**的小调歌曲，
# 音级分布本来就在 0.89–0.92。原来定 0.88 是我从单一观察推出来的，站不住。
# 它留着当诊断信息，不当门禁。
DEFAULT_MAX = {"rhythm": 0.90, "interval": 0.80,
               "pitch_class": 0.97, "cell": 0.50}

# 多样性距离的权重。pitch_class 权重压到 0.05，理由同上。
# cell（逐句节奏型重合）权重给得高，因为它是「同一个模板」最直接的证据。
DIVERSITY_W = {"rhythm": 0.35, "interval": 0.35,
               "cell": 0.25, "pitch_class": 0.05}


def distance(a: "Fingerprint", b: "Fingerprint") -> float:
    """两个候选的差异度，0 = 一样，1 = 毫不相干。"""
    sim = a.similarity(b)
    return 1.0 - sum(DIVERSITY_W[k] * sim[k] for k in DIVERSITY_W)


def select_diverse(pool, n: int, *, cost_of, fp_of):
    """从池子里挑 n 个**互相差异最大**的。贪心 max-min（最远点采样）。

    ## 为什么需要这个

    2026-08-23 创作者的要求：**「一次提供多一点方案，而且每个方案之间的
    差异必须比较大」**。

    原来的做法是生成 16 个变体、按代价取**最优的那一个**给他 ——
    于是他永远看不到多样性，只看到「最安全」的那一个。
    这是选择策略的错，不是生成器的错。

    ## 算法

    1. 先按代价选出最好的那个当种子（保证第一个是能用的）
    2. 之后每一轮，挑「**到已选集合的最小距离**最大」的那个

    最大化最小距离（而不是平均距离）是关键：平均距离会被一个极端候选拉高，
    结果选出「三个几乎一样 + 一个怪的」。max-min 保证任意两个之间都拉开。
    """
    if not pool:
        return []
    items = sorted(pool, key=cost_of)
    chosen = [items[0]]
    rest = items[1:]
    while len(chosen) < n and rest:
        best, best_d = None, -1.0
        for cand in rest:
            d = min(distance(fp_of(cand), fp_of(c)) for c in chosen)
            if d > best_d:
                best, best_d = cand, d
        chosen.append(best)
        rest.remove(best)
    return chosen


def pairwise_table(items, *, label_of, fp_of) -> str:
    """把两两差异度打成矩阵 —— 「差异大」这句话必须可核对，不能只是声称。"""
    labs = [label_of(i) for i in items]
    w = max(len(l) for l in labs) if labs else 4
    head = " " * (w + 2) + "  ".join(f"{l:>6}" for l in labs)
    rows = [head]
    for i, a in enumerate(items):
        cells = []
        for j, b in enumerate(items):
            cells.append("     -" if i == j
                         else f"{distance(fp_of(a), fp_of(b)):6.3f}")
        rows.append(f"  {labs[i]:<{w}}" + "  ".join(cells))
    return "\n".join(rows)


def _cos(a: Counter, b: Counter) -> float:
    ks = set(a) | set(b)
    na = math.sqrt(sum(v * v for v in a.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return sum(a.get(k, 0) * b.get(k, 0) for k in ks) / (na * nb)


@dataclass
class Fingerprint:
    """一首歌的旋律指纹。只存分布，不存音符 —— 可以长期留档做对比。"""
    name: str
    rhythm: Counter
    interval: Counter
    pitch_class: Counter
    cells: frozenset          # 逐句节奏型（元组）的集合

    @classmethod
    def of(cls, name: str, notes: list[Note],
           phrases: list[Phrase] | None = None) -> "Fingerprint":
        rhythm = Counter(round(n.duration_beats, 3) for n in notes)
        # 只统计一个八度内的音程 —— 跨乐句的大跳是段落切换，不是旋律手势
        interval = Counter(b.midi - a.midi for a, b in zip(notes, notes[1:])
                           if abs(b.midi - a.midi) <= 12)
        pc = Counter(n.midi % 12 for n in notes)
        cells = set()
        for ph in (phrases or []):
            seg = notes[ph.note_from:ph.note_to]
            if seg:
                cells.add(tuple(round(n.duration_beats, 3) for n in seg))
        return cls(name, rhythm, interval, pc, frozenset(cells))

    def similarity(self, other: "Fingerprint") -> dict[str, float]:
        both = self.cells | other.cells
        cell = (len(self.cells & other.cells) / len(both)) if both else 0.0
        return {"rhythm": _cos(self.rhythm, other.rhythm),
                "interval": _cos(self.interval, other.interval),
                "pitch_class": _cos(self.pitch_class, other.pitch_class),
                "cell": cell}


def check_uniqueness(notes: list[Note], phrases: list[Phrase],
                     against: list[Fingerprint], *, name: str = "候选",
                     max_sim: dict[str, float] | None = None
                     ) -> list[Finding]:
    """与每一首既有作品比。任一维超阈值就报 warn。

    **不报 block。** 「像」是审美判断，不是对错 —— 创作者可能就想要像
    （同一张专辑的姊妹曲）。检查的职责是让他知道，不是替他否决。
    """
    mx = {**DEFAULT_MAX, **(max_sim or {})}
    fp = Fingerprint.of(name, notes, phrases)
    out: list[Finding] = []
    for ref in against:
        sim = fp.similarity(ref)
        over = {k: v for k, v in sim.items() if v > mx[k]}
        if not over:
            continue
        worst = max(over.items(), key=lambda kv: kv[1] - mx[kv[0]])
        detail = "　".join(f"{k} {v:.3f}（阈值 {mx[k]:.2f}）"
                           for k, v in sorted(over.items(),
                                              key=lambda kv: -kv[1]))
        out.append(Finding("uniqueness", "warn", f"vs《{ref.name}》", detail,
                           score=round(worst[1] - mx[worst[0]], 3)))
    return out


def report(notes: list[Note], phrases: list[Phrase],
           against: list[Fingerprint], *, name: str = "候选") -> str:
    """把四个维度都打出来，不只报超阈值的 —— 用于诊断而非门禁。"""
    fp = Fingerprint.of(name, notes, phrases)
    lines = []
    for ref in against:
        sim = fp.similarity(ref)
        lines.append(f"  vs《{ref.name}》　" + "　".join(
            f"{k} {sim[k]:.3f}{'⚠' if sim[k] > DEFAULT_MAX[k] else ''}"
            for k in ("rhythm", "interval", "pitch_class", "cell")))
    return "\n".join(lines) or "  （没有可比对的既有作品）"
