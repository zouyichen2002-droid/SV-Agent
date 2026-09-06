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
#
# ## 细胞的绝对值没有意义，只有比例有意义
#
# `melodize._line_rhythm` 会把细胞**等比缩放**去填满预算
# （`scale = head_budget / sum(head)`），所以 (0.75, 0.25) 与 (1.5, 0.5)
# 缩放后完全一样。**加「大颗粒细胞」是无效的修法**（我第一次就想错了）。
#
# 决定最短音有多短的是**比例落差**：
#
#     9 字一句、head_budget 4.55 拍给 8 个字，平均 0.57 拍
#     (0.75, 0.25) 落差 3:1 → 短音 0.284 拍 = 129BPM 下 **132 ms**
#     (0.5,)       落差 1:1 → 每个 0.57 拍 = **265 ms**
#
# 创作者的原话是「特别喜欢发超短的声音」。所以下面按落差补了几个更缓的，
# 而真正的把关在 `usable_cells()` —— 按**毫秒**过滤，不按拍。
RHYTHM_CELLS = {
    "均分八分": (0.5,),
    "长短": (0.75, 0.25),
    "短长": (0.25, 0.75),
    "切分": (0.25, 0.5, 0.25),
    "三连感": (1 / 3, 1 / 3, 1 / 3),
    "前紧后松": (0.25, 0.25, 0.5, 0.5),
    "附点": (0.75, 0.25, 0.5, 0.5),
    # 2026-09-06 新增：落差更缓，快歌下也不会把字压碎
    "缓长短": (0.6, 0.4),                       # 3:2
    "缓切分": (0.4, 0.6, 0.5),
    "波形": (0.5, 0.6, 0.5, 0.4),
    "两长一短": (0.6, 0.6, 0.4),
    "推进": (0.4, 0.5, 0.6, 0.7),               # 逐字变长
    "回落": (0.7, 0.6, 0.5, 0.4),               # 逐字变短
}

# 一个汉字音节唱多短算「碎」。**这个数没有真歌数据支撑** ——
# POP909 没有歌词，看不出一个音是一个字还是一个字里的拖腔，
# 而真歌的短音大量是拖腔（我们是一字一音，每个短音都带辅音）。
# 所以它来自创作者的直接反馈「特别喜欢发超短的声音」，
# 参照的是辅音+元音能被听清的下限。**是判断不是测量，标在这里。**
MIN_SYLLABLE_MS = 190.0


def usable_cells(bpm: float, n_chars: int = 9, bpl_beats: float = 8.0,
                 floor_ms: float = MIN_SYLLABLE_MS) -> list[str]:
    """在这个速度下，哪些细胞不会把字压碎。

    **按毫秒判，不按拍。** 同一个细胞在 66 BPM 是 227 ms（好好的），
    到 129 BPM 就是 116 ms（机关枪）—— 细胞按拍定义，
    而音节舒不舒服按毫秒。这个错配是「超短的声音」的根因。

    复用 `_line_rhythm` 算实际时长，**不另写一套缩放逻辑** ——
    两个实现算同一件事，迟早算出两个不同的数。
    """
    from .melodize import _line_rhythm
    out = []
    for name, cell in RHYTHM_CELLS.items():
        durs = _line_rhythm(n_chars, cell, bpl_beats)
        if min(durs) * 60000.0 / bpm >= floor_ms:
            out.append(name)
    return out

CONTOUR_POOL = ("拱形", "下行", "上行", "波浪", "平缓")

# 句末长音占句子时长的比例。**原来写死 0.35，是「同一种感觉」的结构签名。**
#
# 量出来（末音 ÷ 句内均值，300 首真歌 vs 本项目三首）：
#
#     真歌   p25 1.60　中位 2.93　p75 5.34　p90 7.99   跨度 5 倍
#     我们   4.31　4.31　4.31                         三首完全一样
#
# 下面这些值换算成同一个比例是 1.3 / 2.2 / 3.2 / 4.3 / 6.0（9 字句），
# 正好铺满真歌的 p20–p80。**按句轮换**，所以一首歌里也有长有短。
# 只用 (最短, 最长) 两个端点 —— `_tail_for` 在段内线性推进，
# 中间值由它算，不从这里挑。端点按真歌分布反推：
# 比例 1.6 / 2.9 / 5.3 对应 9 字句的 frac 约 0.17 / 0.26 / 0.39。
TAIL_FRACS = {
    "平收":   (0.12, 0.18),      # 比例约 1.1 → 1.7，几乎不拖
    "短收":   (0.15, 0.24),      #      1.4 → 2.5
    "常规":   (0.20, 0.32),      #      1.9 → 3.8   ← 覆盖真歌中位
    "推向段末": (0.14, 0.36),      #      1.3 → 4.5，段内落差最大
    "长拖":   (0.28, 0.42),      #      3.1 → 5.8   ← 真歌 p75 附近
}

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
    tail_fracs: tuple[float, ...] = (0.35,)   # 句末长音占比，按句轮换
    tail_name: str = "常规"                   # 上面那组的档名，供 avoid 用
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

    主歌坐低、副歌抬高 —— 这是流行歌的通行做法。
    但**每首歌的具体落点要变**，否则「同音区」本身就是雍同来源：
    实测主歌 59–67 只有 6 个调内音，可区分的旋律本来就极少。
    """
    # 2026-09-06 重写。旧版有一处**系统性**的窄化，不是随机波动：
    #
    #     verse_hi  = min(verse_lo + span, hi_ceil - 4)        ≤ 72
    #     chorus_lo = choice([verse_hi-2, verse_hi-1, verse_hi])
    #     chorus_hi = min(chorus_lo + choice([9,10,11]), 76)   ← 被 76 截断
    #
    # 意图是给副歌 9–11 个半音，但副歌起点贴着主歌顶端，再加 9–11
    # 必然撞天花板，于是被截成 4–6。实测《月亮不靠岸》副歌音区
    # **只有 3 个半音宽**，八句的句内极差全是 3。
    #
    # 拿 593 首真歌比出来的账（见 reference.py）：
    #
    #     每句极差中位   真歌 p10 5.0 / 中位 8.5     我们 3.0 —— 第 0.3 百分位
    #
    # 而同一首歌的**主歌**句极差中位是 9.0，与真歌持平 —— 生成器有能力，
    # 是音区没给够。所以修的是音区，不是轮廓表。
    #
    # 新规则：**宽度优先于抬升。** 撞天花板就整体下移，绝不压缩宽度 ——
    # 抬升少 2 个半音听得出「副歌没起来」，宽度少 6 个半音听起来是「念经」。
    lo_floor, hi_ceil = 58, 77           # 星尘舒适区 57–78，两端各留 1
    verse_lo = rng.choice([lo_floor, lo_floor + 1, lo_floor + 2])
    verse_span = rng.choice([9, 10, 11])
    verse_hi = verse_lo + verse_span

    lift = rng.choice([5, 6, 7])                  # 副歌整体上抬多少
    chorus_span = rng.choice([9, 10, 11])
    chorus_lo = verse_lo + lift
    chorus_hi = chorus_lo + chorus_span
    if chorus_hi > hi_ceil:                       # 撞顶：下移，**不缩宽**
        chorus_lo -= chorus_hi - hi_ceil
        chorus_hi = hi_ceil
    return {"主歌": (verse_lo, verse_hi), "副歌": (chorus_lo, chorus_hi)}


def expand(theme: str, *, seed: int = 0,
           avoid: list["SongSpec"] | None = None,
           user_notes: tuple[str, ...] = (),
           bpm: float | None = None) -> SongSpec:
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

    # **速度先定，细胞后挑** —— 顺序反了就会重演那个错配：
    # 细胞按 58–86 的慢速表挑，实际却在 129 BPM 上铺，于是把字压成 132 ms。
    # 曲目真实的速度在 project.json 里（`bpm` 参数），规格自己那个只是兜底。
    song_bpm = float(bpm) if bpm else float(
        rng.choice([58, 62, 66, 70, 74, 80, 86]))
    ok = usable_cells(song_bpm)
    cells = [c for c in ok if c not in used_cells] or ok or list(RHYTHM_CELLS)
    rng.shuffle(cells)
    n_cells = rng.choice([2, 2, 3])
    chosen_cells = tuple(cells[:n_cells])

    # 句末长音的形态也要按歌变 —— 写死一个值就是「同一种感觉」的来源
    tail_name = rng.choice([t for t in TAIL_FRACS
                            if t not in {s.tail_name for s in (avoid or [])
                                         if hasattr(s, "tail_name")}]
                           or list(TAIL_FRACS))
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
        bpm=song_bpm,
        key_root=key_root, mode=mode, key_name=key_name,
        register=_register_for(key_root, rng),
        contours=tuple(contours[:4]),
        rhythm_cells=chosen_cells,
        tail_fracs=TAIL_FRACS[tail_name],
        tail_name=tail_name,
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
                user_notes: tuple[str, ...] = (),
                bpm: float | None = None) -> list[SongSpec]:
    """出 n 份互不相同的规格，供创作者在**生成之前**剪枝。

    `bpm` **必须在这里传进来**，不能等规格出来之后再覆盖 ——
    节奏细胞是按速度筛的（`usable_cells`），先挑细胞后改速度
    等于按 66 BPM 的标准挑了细胞、拿到 129 BPM 上去铺。
    实测那样会把汉字压成 132 ms，创作者的反馈是「特别喜欢发超短的声音」。
    """
    out: list[SongSpec] = []
    acc = list(avoid or [])
    for i in range(n):
        s = expand(theme, seed=i, avoid=acc, user_notes=user_notes, bpm=bpm)
        out.append(s)
        acc.append(s)          # 后面的规格也避开前面刚生成的
    return out
