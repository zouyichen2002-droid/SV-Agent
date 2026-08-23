"""把一句稀疏的主题补全成一份完整的曲目规格。

## 这个模块的来源

2026-08-23 创作者的诊断：**「是不是因为我提供的关键词太少了：只有一个『夜曲』。
如果用户提供的限定词太少的话，再加更多的随机约束条件，合成一个 prompt
再提供进去」**。

这个诊断比「在生成端加随机」准一层：**输入里没有区分信息，输出就不可能有区分。**
只给两个字，系统只能落回默认值，而默认值和上一首是同一套 —— 雍同是结构决定的。

## 附带的好处：剪枝前移到规格层

与其让创作者听 4 首歌（4 分钟），不如先给他看 4 份规格
（调 / 速度 / 节奏细胞 / 织体 / 音区 / 动机），在生成之前就砍掉三个。
**剪枝成本从「听」降到「看」。**

## 关键约束：规格里的每一项都必须有旋钮可拧

这是这个模块最容易做错的地方。往规格里写「空灵」「克制」这类词毫无意义 ——
生成器接不上，等于自我安慰。所以本模块**只允许出现已经接到实际参数的字段**，
每个字段旁边注明它被谁消费。

字段与消费方：

    bpm            → melodize 的时间轴、伴奏 tempo
    key_root/mode  → melodize 的音高候选集
    register       → melodize 每段的音区
    contours       → melodize 的轮廓形状序列
    rhythm_cells   → melodize 的句内节奏（**0.987 雍同的根因就在这里**）
    pad_style      → 伴奏垫的节奏型
    arp_figure     → 伴奏上层音型
    bass_groove    → 贝斯律动（**「伴奏听起来一样」的根因之一**）
    drum_pick      → 每个密度档的具体鼓型
    bars_per_line  → 句长

没接上的想法先不要写进来。宁可规格短，不要规格假。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# 调：只用小调族，夜曲/慢歌的常用落点。数字是主音音级。
# 每个调都标了它在星尘舒适区（57–78）里能给多少活动空间。
KEYS = [
    (9, "minor", "A 小调"), (2, "minor", "D 小调"),
    (4, "minor", "E 小调"), (7, "minor", "G 小调"),
    (11, "minor", "B 小调"), (0, "minor", "C 小调"),
]

# 节奏细胞：句内「走字」部分的时长模式，会循环铺满。
# **这是修 0.987 雍同的核心** —— 原来只有 (0.5,) 一种。
RHYTHM_CELLS = {
    "均分八分": (0.5,),
    "长短": (0.75, 0.25),
    "短长": (0.25, 0.75),
    "切分": (0.25, 0.5, 0.25),
    "三连感": (1 / 3, 1 / 3, 1 / 3),
    "前紧后松": (0.25, 0.25, 0.5, 0.5),
    "附点": (0.75, 0.25, 0.5, 0.5),
}

CONTOUR_POOL = ("拱形", "下行", "上行", "波浪", "平缓")

# ---------------------------------------------------------------- 伴奏律动
#
# 2026-08-23 创作者的诊断：**「不是旋律像，而是伴奏，就是那个 4/4 拍的伴奏
# 基本一样」**。实测：伴奏四个声部的节奏型跨歌**重合 100%**。
#
# 那之前我在这里放了一个 `TEXTURES` 字段，却**从没接到伴奏生成器上** ——
# 我自己在本文件开头写过「规格里的每一项都必须有旋钮可拧」，然后违反了它。
# 现在这四个字段全部真的被 `make_accompaniment.build_parts()` 消费。
#
# **名字必须与 make_accompaniment 里的表一致**，`candidates.py` 启动时会校验。
PAD_POOL = ("sustain", "half", "pulse", "offbeat")
ARP_POOL = ("updown", "up", "broken", "pulse16", "sparse")
BASS_POOL = ("1-3", "four", "sync", "long", "push")
DRUM_POOL = {                       # 密度档 → 可选写法
    "hat":   ("hat-4", "hat-8", "half"),
    "build": ("kick-2", "backbeat", "hat-8"),
    "full":  ("ballad", "four-fl", "backbeat", "half"),
    "none":  ("none",),
}


def _make_motif(rng: random.Random, used: set[tuple[int, ...]],
                leap_max: int = 9) -> tuple[int, ...]:
    """生成一个动机：**音程序列**，不是绝对音高，所以可以移调复用。

    动机是「这首歌是这首歌」的机制。规格补全（换调/换速度/换节奏细胞）
    能把 rhythm 相似度从 0.987 压到 0.003，但 **interval 压不下来**
    （实测仍有 0.93）—— 因为旋律手势来自「轮廓 + 步进偏好」这个机制本身，
    换调换速度都碰不到它。动机是直接往手势里注入特征。

    三条约束，缺一条动机就不像动机：

    1. **必须有一个 ≥3 半音的音程**，否则全是级进，听不出是个「型」
    2. **必须有一次方向反转**，否则就是一段音阶跑动，没有形状
    3. **累积跨度 ≤ leap_max**，否则移调后必然出音域
    """
    steps = (-7, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7)
    for _ in range(200):
        n = rng.choice((3, 3, 4))
        m = tuple(rng.choice(steps) for _ in range(n))
        if max(abs(x) for x in m) < 3:
            continue                      # 全级进，不成型
        dirs = [1 if x > 0 else -1 for x in m]
        if len(set(dirs)) < 2:
            continue                      # 单向跑动，没有形状
        run = [0]
        for x in m:
            run.append(run[-1] + x)
        if max(run) - min(run) > leap_max:
            continue                      # 跨度太大，移调后会出音域
        if m in used:
            continue
        return m
    return (2, 3, -2)                     # 兜底


def motif_name(m: tuple[int, ...]) -> str:
    """给动机一个人能读的名字，用于规格展示与剪枝。"""
    return " ".join(f"{x:+d}" for x in m) + f"（{len(m)+1} 音）"


@dataclass
class SongSpec:
    theme: str
    bpm: float
    key_root: int
    mode: str
    key_name: str
    register: dict[str, tuple[int, int]]
    contours: tuple[str, ...]
    rhythm_cells: tuple[str, ...]         # 每句轮换用
    pad_style: str
    arp_figure: str
    bass_groove: str
    drum_pick: dict          # 密度档 → 具体鼓型
    motif: tuple[int, ...] = ()        # 音程序列，可移调复用
    bars_per_line: int = 2
    seed: int = 0
    notes_from_user: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        reg = "　".join(f"{k} {v[0]}–{v[1]}" for k, v in self.register.items())
        return (f"{self.bpm:.0f} BPM · {self.key_name} · 每句 "
                f"{self.bars_per_line} 小节\n"
                f"    音区    {reg}\n"
                f"    轮廓    {' → '.join(self.contours)}\n"
                f"    节奏细胞 {' / '.join(self.rhythm_cells)}\n"
                f"    动机    "
                f"{motif_name(self.motif) if self.motif else '无'}\n"
                f"    伴奏律动 垫={self.pad_style} 琶音={self.arp_figure} "
                f"贝斯={self.bass_groove} 鼓={self.drum_pick.get('full')}")


def _register_for(key_root: int, rng: random.Random
                  ) -> dict[str, tuple[int, int]]:
    """按调选段落音区，两端都不碰声库舒适区的边（57–78）。

    主歌坐低、副歌抬高 —— 这是《宇宙无边无垠》验收通过的做法。
    但**每首歌的具体落点要变**，否则「同音区」本身就是雍同来源：
    实测主歌 59–67 只有 6 个调内音，可区分的旋律本来就极少。
    """
    lo_floor, hi_ceil = 59, 76           # 避开 57 和 78 两个边
    verse_lo = rng.choice([lo_floor, lo_floor + 1, lo_floor + 2])
    verse_span = rng.choice([9, 10, 11])          # 比原来的 8 宽
    verse_hi = min(verse_lo + verse_span, hi_ceil - 4)
    chorus_lo = rng.choice([verse_hi - 2, verse_hi - 1, verse_hi])
    chorus_hi = min(chorus_lo + rng.choice([9, 10, 11]), hi_ceil)
    return {"主歌": (verse_lo, verse_hi), "副歌": (chorus_lo, chorus_hi)}


def expand(theme: str, *, seed: int = 0,
           avoid: list["SongSpec"] | None = None,
           user_notes: tuple[str, ...] = ()) -> SongSpec:
    """把一句主题补全成完整规格。

    `avoid` 给了既有作品的规格时，会**主动避开**它们的调与节奏细胞 ——
    「不要和上一首像」这件事在规格层就能部分解决，不必等到生成后再检查。
    """
    # **不能用内置 hash()**：Python 对字符串的 hash 每个进程都加随机盐，
    # 于是同一个主题同一个 seed 在两次运行里得到不同的规格 ——
    # 实测「只改和声」那次，调性从 C 小调莫名变成 G 小调。
    # 可复现是这条链的基本要求（种子固定就该出同样的东西）。
    import zlib
    rng = random.Random(zlib.crc32(f"{theme}|{seed}".encode("utf-8")))
    used_keys = {(s.key_root, s.mode) for s in (avoid or [])}
    used_cells = {c for s in (avoid or []) for c in s.rhythm_cells}
    used_grooves = {(s.pad_style, s.arp_figure, s.bass_groove)
                    for s in (avoid or [])}

    keys = [k for k in KEYS if (k[0], k[1]) not in used_keys] or KEYS
    key_root, mode, key_name = rng.choice(keys)

    cells = [c for c in RHYTHM_CELLS if c not in used_cells] or list(RHYTHM_CELLS)
    rng.shuffle(cells)
    n_cells = rng.choice([2, 2, 3])
    chosen_cells = tuple(cells[:n_cells])

    contours = list(CONTOUR_POOL)
    rng.shuffle(contours)
    # 动机也要避开既有作品的 —— 这是 interval 相似度唯一的修法
    motif = _make_motif(rng, {s.motif for s in (avoid or []) if s.motif})

    # 律动组合也要和既有的不同 —— 这是「伴奏听起来一样」的直接修法
    for _ in range(60):
        g = (rng.choice(PAD_POOL), rng.choice(ARP_POOL), rng.choice(BASS_POOL))
        if g not in used_grooves:
            break
    pad_style, arp_figure, bass_groove = g

    return SongSpec(
        theme=theme,
        bpm=float(rng.choice([58, 62, 66, 70, 74, 80, 86])),
        key_root=key_root, mode=mode, key_name=key_name,
        register=_register_for(key_root, rng),
        contours=tuple(contours[:4]),
        rhythm_cells=chosen_cells,
        pad_style=pad_style,
        arp_figure=arp_figure,
        bass_groove=bass_groove,
        drum_pick={lvl: rng.choice(opts) for lvl, opts in DRUM_POOL.items()},
        motif=motif,
        bars_per_line=rng.choice([2, 2, 2, 4]),
        seed=seed,
        notes_from_user=user_notes,
    )


def expand_many(theme: str, n: int, *, avoid: list[SongSpec] | None = None,
                user_notes: tuple[str, ...] = ()) -> list[SongSpec]:
    """出 n 份互不相同的规格，供创作者在**生成之前**剪枝。"""
    out: list[SongSpec] = []
    acc = list(avoid or [])
    for i in range(n):
        s = expand(theme, seed=i, avoid=acc, user_notes=user_notes)
        out.append(s)
        acc.append(s)          # 后面的规格也避开前面刚生成的
    return out
