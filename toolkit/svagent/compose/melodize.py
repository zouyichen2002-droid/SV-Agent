"""从歌词 + 曲式生成旋律候选。**声调在生成时就约束，不留给下游修。**

## 为什么必须在生成时避开倒字

[ADR-0010](../../../specs/adr/0010-self-repair-loop.md) 的结论：
自修复循环把 6 项客观检查全自动搞定，但 `prosody` 到不了 0 ——
倒字的真正修法是换词，而换词被排除在修复循环的搜索空间之外。

所以生成器的职责不是「写得好」，而是**「写出让修复循环能收敛到 0 的候选」**，
其中倒字这一项它必须自己解决。

声调是已知的（pypinyin），所以这是可以算法化的约束，不是审美判断：

    前一个字 4 声 → 到本字不能大幅上行（4 声配上行易听成 2 声）
    前一个字 2 声 → 不能大幅下行（2 声配下行易听成 4 声）
    前一个字 3 声 → 不能大幅上行
    前一个字 1 声 → 避免任意方向的大跳
    本字 3 声      → 不要放在乐句最高点

阈值直接取 `ProsodyCfg` 的那几个，与检查器同源 —— 生成和检查用同一套标准，
否则会出现「生成器觉得没问题、检查器报警」的荒谬情况。

## 其余六项检查是构造性满足的，不是碰运气

| 检查 | 怎么保证 |
|---|---|
| `count` | 一个字一个音符，不产生拖腔 |
| `range` | 音高候选集本身就限制在段落音区内 |
| `scale` | 候选集只含调内音 |
| `leap` | 每步的候选集按上限裁剪 |
| `cadence` | 句末音强制取当前和弦的和弦音 |
| `phrase` | 句内起点连续，句间的气口落在乐句边界外 |

所以生成器交出来的候选**本来就该是 0 finding**。修复循环在这里是安全网，
不是主力 —— 如果它经常需要大改，说明生成器有 bug。

## 生成即搜索

同一段歌词生成 N 个变体（不同随机种子 + 不同轮廓形状），
用 `repair.cost` 打分取最好的。这是个很浅的搜索，但它把「运气」变成「选择」。
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .checks import MAJOR, MINOR, CheckCfg, Note, Phrase, tones_of

# 和弦按**级数**处理，不按绝对名。
#
# 歌词数据里写的是 A 小调的和弦名（Am/Dm/Em/C/F/G），但 SongSpec 会换调 ——
# 实测规格选 C 小调时，「Am」不在调内，句末找不到和弦音直接崩。
# 所以这里把名字解释成「相对主音的半音数 + 大小」，再按 key_root 落到实际音级。
#
#     Am → i(0)   Dm → iv(5)   Em → v(7)
#     C  → III(3) F  → VI(8)   G  → VII(10)
DEGREE_SEMITONE = {"Am": 0, "Dm": 5, "Em": 7, "C": 3, "F": 8, "G": 10}
DEGREE_QUALITY = {"Am": "minor", "Dm": "minor", "Em": "minor",
                  "C": "major", "F": "major", "G": "major"}


def chord_of(name: str, key_root: int) -> tuple[tuple[int, ...], int, str]:
    """和弦名 + 主音 → (三个音级, 根音音级, 大小)。"""
    qual = DEGREE_QUALITY[name]
    root = (key_root + DEGREE_SEMITONE[name]) % 12
    triad = (0, 4, 7) if qual == "major" else (0, 3, 7)
    return tuple((root + t) % 12 for t in triad), root, qual

def phrases_of(sections, key_root: int):
    """SECTIONS + 主音 → `Phrase` 列表（带每句的和弦）。

    **唯一的实现。** 这段构造原来在 `state.check_melody`、`step3` 的候选生成、
    以及新写的 `metrics.chord_fit` 里各有一份 —— 第四份差点也写出来。
    乐句边界一旦分叉，八项检查与诊断指标就会对着不同的句子说话。
    """
    from .checks import Phrase
    out, idx, pi = [], 0, 0
    for _sec, _bar, lines in sections:
        for _text, syls, chord in lines:
            _pcs, root, q = chord_of(chord, key_root)
            out.append(Phrase(pi, idx, idx + len(syls),
                              chord_root=root, chord_quality=q))
            idx += len(syls)
            pi += 1
    return out


# 轮廓形状：给出「归一化位置 → 相对音区高度」的目标曲线
# 末字长音的上限（拍）。见 _line_rhythm 里的说明
MAX_TAIL_BEATS = 4.0

CONTOURS = {
    "拱形": lambda t: 4 * t * (1 - t),          # 中间高，两头低
    "下行": lambda t: 1.0 - t,
    "上行": lambda t: t,
    "波浪": lambda t: 0.5 + 0.5 * __import__("math").sin(6.283 * t),
    "平缓": lambda t: 0.45,
}


def register_of(register: dict, sec_name: str) -> tuple[int, int]:
    """段名 → 音区。「主歌1」回退到「主歌」；「预副」没给就在主歌与副歌之间插值。

    实测踩过：曲式带编号（主歌1/副歌2）时直接 KeyError。
    """
    if sec_name in register:
        return register[sec_name]
    stem = sec_name.rstrip("0123456789")
    if stem in register:
        return register[stem]
    if stem.startswith("预副") and "主歌" in register and "副歌" in register:
        (vlo, vhi), (clo, chi) = register["主歌"], register["副歌"]
        return ((vlo + clo) // 2, (vhi + chi) // 2)
    return register.get("主歌") or next(iter(register.values()))


def scale_pitches(key_root: int, quality: str, lo: int, hi: int) -> list[int]:
    base = MAJOR if quality == "major" else MINOR
    pcs = {(key_root + d) % 12 for d in base}
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


@dataclass
class Plan:
    """一行歌词的生成计划。"""
    text: str
    chord: str
    section: str
    bar0: int               # 起始小节


def _line_rhythm(n_chars: int, cell: tuple[float, ...] = (0.5,),
                 beats_per_line: float = 8.0) -> list[float]:
    """句内节奏：按**节奏细胞**铺走字部分，末字长音，句尾留 1 拍气口。

    `cell` 是这首歌的节奏细胞（如 `(0.75, 0.25)` 长短、`(0.25, 0.5, 0.25)` 切分），
    循环铺满前 n-1 个字。

    **原来这里是一个死公式 `[0.5] * (n-1) + [tail]`**，结果所有歌所有句子的
    节奏型完全一样 —— 实测《夜曲》与《宇宙无边无垠》的时长分布余弦相似度
    **0.987**，是「两首歌听起来像」的头号根因。细胞化是这一项的直接修法。

    句内起点始终连续（`phrase` 检查要的），气口落在乐句边界之外。
    """
    body = beats_per_line - 1.0
    # 末字长音有上限。**不能把剩余时间全给末字** ——
    # 实测每句 4 小节时，末字拿到 11 拍 = 11.5 秒，创作者的反馈是
    # 「听起来都快唱断气了」。一个字唱 3 秒已经很长，4 拍是上限。
    want_tail = min(MAX_TAIL_BEATS, max(0.75, body * 0.35))
    head = [cell[i % len(cell)] for i in range(max(0, n_chars - 1))]
    head_budget = body - want_tail
    if head and head_budget > 0:
        # 等比缩放走字部分去填满 head_budget。
        # 长句（每句 4 小节）会把字距拉开，而不是把时间堆到末字上。
        scale = head_budget / sum(head)
        head = [round(h * scale, 6) for h in head]
    tail = round(body - sum(head), 6)
    return head + [max(0.25, tail)]


def _tone_ok(prev_tone: int, interval: int, cfg: CheckCfg) -> bool:
    """这个音程会不会让前一个字倒。与 check_prosody 同源的判据。"""
    P = cfg.prosody
    if abs(interval) < P.between_min_semitones:
        return True                       # 音程太小，不构成声调冲突
    if prev_tone == 4 and interval > 0:
        return False
    if prev_tone == 2 and interval < 0:
        return False
    if prev_tone == 3 and interval > 0:
        return False
    if prev_tone == 1:
        return False                      # 1 声配大跳，削弱平稳
    return True


def _place_motif(motif: tuple[int, ...], pitches: list[int],
                 chord: tuple[int, ...], tones: list[int], want0: int,
                 cfg: CheckCfg, rng: random.Random) -> list[int] | None:
    """把动机落到具体音高上。返回前 len(motif)+1 个音高，放不下就返回 None。

    动机是音程序列，所以要选一个起点。选法：起点必须是和弦音（句首听感要稳），
    然后在所有可行起点里按「声调违规最少 → 离轮廓目标最近」排序。

    **动机优先于轮廓。** 轮廓只用来在多个可行起点之间挑，不能否决动机 ——
    否则动机会被轮廓磨平，interval 相似度也就压不下来。
    """
    ok_set = set(pitches)
    best = None
    for s0 in (p for p in pitches if p % 12 in chord):
        seq = [s0]
        for iv in motif:
            nxt = seq[-1] + iv
            if nxt not in ok_set:
                seq = None
                break
            seq.append(nxt)
        if seq is None:
            continue
        viol = sum(1 for i in range(len(motif))
                   if i < len(tones) - 1
                   and not _tone_ok(tones[i], seq[i + 1] - seq[i], cfg))
        key = (viol, abs(s0 - want0), rng.random())
        if best is None or key < best[0]:
            best = (key, seq)
    return best[1] if best else None


def melodize_line(plan: Plan, tones: list[int], pitches: list[int],
                  contour, rng: random.Random, cfg: CheckCfg,
                  key_root: int = 9,
                  start_hint: int | None = None,
                  motif: tuple[int, ...] | None = None) -> list[int]:
    """给一行歌词生成音高序列。返回长度 = 字数。

    `motif` 给了就用它铺句首，剩下的交给轮廓走。这样动机在每段的第一句
    复现，既有辨识度又不机械。
    """
    n = len(plan.text)
    chord, _croot, _cq = chord_of(plan.chord, key_root)
    lo, hi = pitches[0], pitches[-1]
    span = max(1, hi - lo)

    def target(i: int) -> int:
        t = i / max(1, n - 1)
        return lo + int(round(contour(t) * span))

    # 句末音必须是和弦音 —— 直接满足 cadence
    tail_cands = [p for p in pitches if p % 12 in chord]
    if not tail_cands:
        # 该段音区里一个和弦音都没有（窄音区 + 某些级数会这样）。
        # 退让成调内最近音，把 cadence 的 warn 留给修复循环 ——
        # **崩掉比报警糟得多**。实测：规格换调后这里直接 ValueError。
        tail_cands = pitches
    tail = min(tail_cands, key=lambda p: abs(p - target(n - 1)))

    seq: list[int] = []
    cur = start_hint if start_hint is not None else None
    # 动机铺句首。留够位置给末字长音，否则动机会顶掉句末的和弦音
    if motif and n >= len(motif) + 2:
        head = _place_motif(motif, pitches, chord, tones, target(0), cfg, rng)
        if head:
            seq = list(head)
            cur = seq[-1]
    for i in range(len(seq), n):
        if i == n - 1:
            seq.append(tail)
            break
        want = target(i)
        if cur is None:
            cands = [p for p in pitches if p % 12 in chord]
        else:
            cands = [p for p in pitches
                     if abs(p - cur) <= cfg.leap_max_semitones]
        # 声调过滤：不能让**前一个字**倒
        if cur is not None and i > 0:
            ok = [p for p in cands if _tone_ok(tones[i - 1], p - cur, cfg)]
            cands = ok or cands          # 全被滤掉时退让，交给修复循环
        # 3 声不要落在会成为最高点的位置
        if tones[i] == 3:
            safe = [p for p in cands if p < hi - 1]
            cands = safe or cands
        # 在目标附近随机挑，越近权重越高
        cands.sort(key=lambda p: (abs(p - want), rng.random()))
        cur = cands[0] if len(cands) < 3 else rng.choice(cands[:3])
        seq.append(cur)
    return seq


def melodize_spec(candidate, spec, cfg: CheckCfg, *, seed: int | None = None,
                  form: list[tuple[str, int]] | None = None):
    """用一份 `SongSpec` 生成。规格里的每一项都真的被消费 —— 见 spec.py 的说明。"""
    from .spec import RHYTHM_CELLS
    return melodize(candidate, bpm=spec.bpm, key_root=spec.key_root,
                    quality=spec.mode, register=spec.register, cfg=cfg,
                    seed=spec.seed if seed is None else seed,
                    contour_names=spec.contours,
                    rhythm_cells=tuple(RHYTHM_CELLS[c]
                                       for c in spec.rhythm_cells),
                    bars_per_line=spec.bars_per_line,
                    motif=spec.motif or None,
                    form=form)


def melodize(candidate, *, bpm: float, key_root: int, quality: str,
             register: dict[str, tuple[int, int]], cfg: CheckCfg,
             seed: int = 0, contour_names: tuple[str, ...] | None = None,
             rhythm_cells: tuple[tuple[float, ...], ...] | None = None,
             bars_per_line: int = 2,
             motif: tuple[int, ...] | None = None,
             form: list[tuple[str, int]] | None = None):
    """给一个候选（段落 → 句子）生成整首旋律。

    返回 (notes, phrases, text, sections) —— sections 的形状与
    `melody_v2.SECTIONS` 一致，好让伴奏生成器不用改。
    """
    _name, _gist, secs = candidate
    rng = random.Random(seed)
    contour_names = contour_names or ("拱形", "下行", "上行", "波浪")
    rhythm_cells = rhythm_cells or ((0.5,),)
    beats_per_line = bars_per_line * 4.0

    notes: list[Note] = []
    phrases: list[Phrase] = []
    text_all = ""
    sections_out = []
    idx = pi = 0
    bar = 0

    # 曲式：[(段名, 小节数)]。没有歌词的段（前奏/间奏/尾奏）只推进小节数。
    # 不给就退回「各段首尾相接」的老行为。
    lyric_secs = {name: lines for name, lines in secs}
    if form is None:
        form = [(name, len(lines) * bars_per_line) for name, lines in secs]
    order = [(n, b) for n, b in form]

    for sec_name, sec_bars in order:
        lines = lyric_secs.get(sec_name)
        if not lines:
            bar += sec_bars          # 器乐段，只占小节
            continue
        lo, hi = register_of(register, sec_name)
        pitches = scale_pitches(key_root, quality, lo, hi)
        # **每句几小节必须从曲式推导，不能独立随机。**
        # 实测：曲式给「主歌1 = 8 小节」（按每句 2 小节算），
        # 而规格随机选了每句 4 小节 —— 4 句需要 16 小节却只有 8 小节，
        # 后两句压到下一段身上，同轨重叠 57 处。SynthV 不支持同轨重叠。
        bpl = max(1, sec_bars // max(1, len(lines)))
        bpl_beats = bpl * 4.0
        sec_lines = []
        prev_tail = None
        for li, (text, chord) in enumerate(lines):
            plan = Plan(text, chord, sec_name, bar + li * bpl)
            tones = [t for _, t, _ in tones_of(text)]
            cname = contour_names[li % len(contour_names)]
            # 动机只给每段第一句 —— 复现要有辨识度，但不能每句都来，
            # 否则整首歌变成一个音型的复读
            seq = melodize_line(plan, tones, pitches, CONTOURS[cname],
                                rng, cfg, key_root=key_root,
                                start_hint=prev_tail,
                                motif=motif if li == 0 else None)
            durs = _line_rhythm(len(text),
                                rhythm_cells[li % len(rhythm_cells)],
                                bpl_beats)
            t = plan.bar0 * 4.0
            first = idx
            syls = []
            for ch, m, d in zip(text, seq, durs):
                notes.append(Note(idx, t, d, m, ch))
                syls.append((ch, m, d))
                t += d
                idx += 1
            _pcs, root, cqual = chord_of(chord, key_root)
            phrases.append(Phrase(pi, first, idx, chord_root=root,
                                  chord_quality=cqual))
            pi += 1
            text_all += text
            sec_lines.append((text, syls, (root, cqual)))
            prev_tail = seq[-1]
        sections_out.append((sec_name, bar, sec_lines))
        # 用曲式给的小节数推进，而不是按句数算 —— 器乐段才能占住位置
        bar += sec_bars

    return notes, phrases, text_all, sections_out
