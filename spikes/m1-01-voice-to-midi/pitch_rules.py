# -*- coding: utf-8 -*-
"""拿原唱的音高（pyin）改扒出来的音（10-08《那些我恐惧至极的事》创作者手改 r03 之后，他说「都加上」）。

1. octave_up：扒出来的音比原唱低一个八度 → 往上改（只往上）。
   这首副歌里同一组长音三遍 GAME 都扒成 D4、原唱是 D5：往上改的 7 处 7 处对（6 处和他改的一样，1 处八度对、差半音）；
   往下改的 3 处全错（都在两位歌手叠唱那段，pyin 抓到的是另一个低的声音）→ 只往上。
   《公主》：10 处里 8 处和他的定稿一样、2 处他删了或改成了别的、0 处改错；《刽子手》0 处触发。
   紧跟着的拖音（「-」、和它原来同音高、首尾相接）一起改。
2. split_tail：长音的结尾滑到另一个音、稳在那里 → 从变化的那一刻拆开，后一段写拖音「-」、音高用结尾那个音。
   他在这首里有 9 处这样拆（「er」G4 后面接 F4 那种）：规矩拆的 5 处和他的一样、0 处错、漏 3 处；《公主》错 1 处、漏 1 处。
   条件：音 ≥ 0.4 秒、整个音有声 ≥ 60%；结尾 0.18 秒稳（标准差 < 0.6 半音），而且离这个音的前半段、离这个音本身都 ≥ 1.5 半音
   （只比前半段会把「开头往上兜、结尾回到本音」的也拆了 —— 第一版这样错了一半）；拆出来两段都 ≥ 0.15 秒。

pyin 整首算一次（16 kHz、10 ms 一帧），两条规矩共用。notes：[(起, 长, 音分, 字)]。

接进 song_round 后（10-08）十首回归：念唱和别的音不变；往上改八度另外 4 处（《夜舞》2 处和照钢琴谱改的一样）；
音尾拆音另外 6 处，有对照的 3 处里 2 处音高对、但拆出来的后一段其实是下一个字（前面的字已经错位一格），1 处拆错 —— 不稳，先留着、看创作者听了怎么说。
《影子小姐》（10-09）：往上改八度 1 处（和 pyin 一致，他没改回去），音尾拆音 0 处。

3、4 两条是 10-13《弈》创作者改完 r01 之后加的（他「都加上」）：
3. drop_quiet_orphans：没字的串（连着的「-」、不接在字后面）而且主唱分轨在这串上比整首唱字时的中位轻 ≥ 10 dB → 删。
   四首他改过的（《弈》《影子小姐》《公主》《那些我恐惧至极的事》）：符合的 7 串他全删了（《弈》前奏乐器漏进来 6 串、《影子小姐》1 串），
   他留下的 16 串都在 −5 dB 以内。
4. drop_lyricless_patches：补段里一个字都没放上 → 这段的音删掉（《弈》1:55–2:05 补进来的不是主唱，他整段删了）。
   别的歌有字的补段不动；《调查中（原唱）》3 段、《倒瞰清白》1 段会被删，这两首他没改过、没对照。
"""
from __future__ import annotations

import numpy as np

UP_MIN_VOICED, UP_TOL = 0.6, 0.8                     # 规矩 1：中段有声 ≥ 60%、和高一个八度差 ≤ 0.8 半音
TAIL_MIN_LEN, TAIL_SEC, TAIL_JUMP, TAIL_STD, TAIL_MIN_PART = 0.4, 0.18, 1.5, 0.6, 0.15
ORPHAN_GAP, ORPHAN_QUIET_DB = 0.3, -10.0              # 规矩 3：没字的串（前后空隙 0.3 秒）、比唱字时的中位轻 10 dB 以上
_cache: dict[str, tuple] = {}
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"     # noqa: E731
_N = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
name = lambda p: f"{_N[p % 12]}{p // 12 - 1}"         # noqa: E731


def track(vocal_wav: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """→ (每帧时间, 每帧音高（MIDI，没声是 nan）, 每帧有没有声)。同一个文件只算一次。"""
    if vocal_wav not in _cache:
        import librosa
        y, sr = librosa.load(vocal_wav, sr=16000, mono=True)
        f0, voiced, _ = librosa.pyin(y, fmin=70, fmax=1200, sr=sr, frame_length=1024, hop_length=160)
        midi = librosa.hz_to_midi(f0)
        _cache[vocal_wav] = (np.arange(len(midi)) * 160 / sr, midi, voiced & ~np.isnan(midi))
    return _cache[vocal_wav]


def octave_up(notes: list[tuple], trk: tuple) -> tuple[list[tuple], list[str]]:
    T, mid, ok = trk
    order = sorted(range(len(notes)), key=lambda k: notes[k][0])
    out, log, moved = list(notes), [], set()
    for idx, k in enumerate(order):
        s, d, c, ly = notes[k]
        if ly in ("-", ""):
            continue
        m = (T >= s + 0.15 * d) & (T <= s + 0.85 * d)
        v = mid[m & ok]
        if len(v) < 3 or len(v) / max(1, m.sum()) < UP_MIN_VOICED:
            continue
        p = int(round(c / 100))
        if abs(float(np.median(v)) - p - 12) > UP_TOL:
            continue
        out[k] = (s, d, c + 1200.0, ly)
        moved.add(k)
        tail = []
        end = s + d
        for j in order[idx + 1:]:                       # 紧跟着的拖音一起往上
            s2, d2, c2, ly2 = notes[j]
            if ly2 not in ("-", "") or abs(s2 - end) > 0.03 or int(round(c2 / 100)) != p:
                break
            out[j] = (s2, d2, c2 + 1200.0, ly2)
            tail.append(j)
            end = s2 + d2
        log.append(f"{fmt(s)}「{ly}」{name(p)} → {name(p + 12)}（原唱中段在 {float(np.median(v)):.1f}）"
                   + (f"，后面 {len(tail)} 个拖音一起" if tail else ""))
    return out, log


def split_tail(notes: list[tuple], trk: tuple) -> tuple[list[tuple], list[str]]:
    T, mid, ok = trk
    out, log = [], []
    for s, d, c, ly in sorted(notes):
        if ly in ("-", "") or d < TAIL_MIN_LEN:
            out.append((s, d, c, ly))
            continue
        m = (T >= s) & (T < s + d)
        seg, sok = mid[m], ok[m]
        if len(seg) == 0 or sok.mean() < 0.6:
            out.append((s, d, c, ly))
            continue
        half = len(seg) // 2
        head = seg[:half][sok[:half]]
        tn = int(round(TAIL_SEC * 100))
        tail = seg[-tn:][sok[-tn:]]
        p = c / 100
        if len(head) < 5 or len(tail) < 0.6 * tn:
            out.append((s, d, c, ly))
            continue
        h, tl = float(np.median(head)), float(np.median(tail))
        if abs(tl - h) < TAIL_JUMP or abs(tl - p) < TAIL_JUMP or float(np.std(tail)) >= TAIL_STD:
            out.append((s, d, c, ly))
            continue
        # 从后往前找：结尾那个音一直稳着的那段从哪一帧开始
        ts = T[m]
        cut = len(seg) - 1
        while cut > 0 and (not sok[cut - 1] or abs(seg[cut - 1] - tl) <= 0.7):
            cut -= 1
        t = float(ts[cut])
        if t - s < TAIL_MIN_PART or s + d - t < TAIL_MIN_PART:
            out.append((s, d, c, ly))
            continue
        q = int(round(tl))
        out += [(s, t - s, c, ly), (t, s + d - t, float(q * 100), "-")]
        log.append(f"{fmt(s)}「{ly}」{name(int(round(p)))} 结尾滑到 {name(q)} → 在 {fmt(t)} 拆开，后一段写「-」（{s + d - t:.2f} 秒）")
    return out, log


def _orphan_runs(notes: list[tuple]) -> list[tuple[int, int]]:
    """没字的串：连着的「-」（相邻空隙 < ORPHAN_GAP），而且第一个前面 ORPHAN_GAP 秒内没有音（不是接在一个字后面的拖腔）。notes 要排好序。"""
    runs, i = [], 0
    while i < len(notes):
        s, d, c, ly = notes[i]
        if ly == "-" and (i == 0 or s - (notes[i - 1][0] + notes[i - 1][1]) > ORPHAN_GAP):
            j = i
            while j + 1 < len(notes) and notes[j + 1][3] == "-" and notes[j + 1][0] - (notes[j][0] + notes[j][1]) < ORPHAN_GAP:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def drop_quiet_orphans(notes: list[tuple], level) -> tuple[list[tuple], list[str]]:
    """3. 没字、又比整首唱字时轻 ≥ ORPHAN_QUIET_DB 的串 → 删（乐器 / 别的声音漏进主唱分轨）。level(起, 止) → 主唱分轨这段的 dB。"""
    notes = sorted(notes)
    sung = [level(s, s + d) for s, d, c, ly in notes if ly not in ("-", "")]
    if not sung:
        return notes, []
    ref = float(np.median(sung))
    drop, log = set(), []
    for i, j in _orphan_runs(notes):
        s0, e0 = notes[i][0], notes[j][0] + notes[j][1]
        lv = level(s0, e0) - ref
        if lv <= ORPHAN_QUIET_DB:
            drop.update(range(i, j + 1))
            log.append(f"{fmt(s0)}–{fmt(e0)} {j - i + 1} 个没字的音，主唱分轨比唱字时轻 {-lv:.0f} dB → 删")
    return [n for k, n in enumerate(notes) if k not in drop], log


def drop_lyricless_patches(notes: list[tuple], patches: list[tuple[float, float]]) -> tuple[list[tuple], list[str]]:
    """4. 补段（主唱分轨整段没声、用整条人声补的段）里一个字都没放上 → 这段的音删掉（补进来的不是主唱）。"""
    drop, log = set(), []
    for a, b in patches:
        ins = [k for k, n in enumerate(notes) if a - 0.1 <= n[0] < b + 0.1]
        if ins and not any(notes[k][3] not in ("-", "") for k in ins):
            drop.update(ins)
            log.append(f"补段 {fmt(a)}–{fmt(b)} 里 {len(ins)} 个音一个字都没放上 → 删")
    return [n for k, n in enumerate(notes) if k not in drop], log


def stem_level(vocal_wav: str):
    """→ level(起, 止)：主唱分轨这段的 RMS（dB）。"""
    if ("lv", vocal_wav) not in _cache:
        import soundfile as sf
        y, sr = sf.read(vocal_wav, dtype="float32", always_2d=True)
        _cache[("lv", vocal_wav)] = (y.mean(axis=1), sr)
    y, sr = _cache[("lv", vocal_wav)]

    def level(a: float, b: float) -> float:
        seg = y[int(a * sr):max(int(a * sr) + 1, int(b * sr))]
        return float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9))
    return level


SCALE_PCS = {"Major": (0, 2, 4, 5, 7, 9, 11), "NaturalMinor": (0, 2, 3, 5, 7, 8, 10), "HarmonicMinor": (0, 2, 3, 5, 7, 8, 11)}
_ROOTS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def sung_pitch(trk: tuple, scale: dict | None):
    """→ pitch_of(起, 止)：原唱在这段中间（15%–85%）唱的音高中位，取调内最近的音（音分）；有声不到 60% 或不到 3 帧 → None。
    补「下一句的第一个字」那个音用（5. 补的音照原唱，10-15《我奉陪》创作者「都加上」）。scale 是 key_scale.detect 的结果，没有就取最近的半音。"""
    T, mid, ok = trk
    pcs = None
    if scale and scale.get("type") in SCALE_PCS and scale.get("root") in _ROOTS:
        r = _ROOTS.index(scale["root"])
        pcs = {(r + x) % 12 for x in SCALE_PCS[scale["type"]]}

    def pitch_of(a: float, b: float) -> float | None:
        d = b - a
        m = (T >= a + 0.15 * d) & (T <= a + 0.85 * d)
        v = mid[m & ok]
        if len(v) < 3 or len(v) / max(1, m.sum()) < UP_MIN_VOICED:
            return None
        x = float(np.median(v))
        cands = [q for q in range(int(x) - 2, int(x) + 3) if pcs is None or q % 12 in pcs]
        return float(min(cands, key=lambda q: abs(q - x)) * 100)
    return pitch_of


def selftest() -> list[str]:
    """造一段音高轨：① 原唱高一个八度的音 → 往上、后面的拖音跟着；低一个八度的不往下；② 结尾滑走的拆开，开头兜一下的不拆。"""
    fails = []
    T = np.arange(0, 6, 0.01)
    mid = np.full(len(T), np.nan)
    ok = np.zeros(len(T), bool)

    def sing(a, b, p):
        m = (T >= a) & (T < b)
        mid[m], ok[m] = p, True
    sing(0.0, 0.5, 74.0)          # 扒成 62、原唱 74 → 往上
    sing(0.5, 0.8, 74.0)          # 紧跟的拖音
    sing(1.0, 1.5, 55.0)          # 扒成 67、原唱 55（低一个八度）→ 不往下
    sing(2.0, 2.4, 67.0); sing(2.4, 2.8, 65.0)       # 「er」G4 后面滑到 F4 → 拆
    sing(3.0, 3.2, 63.0); sing(3.2, 3.8, 67.0)       # 开头从 D#4 兜上来、结尾回到 G4 → 不拆
    trk = (T, mid, ok)
    notes = [(0.0, 0.5, 6200.0, "a"), (0.5, 0.3, 6200.0, "-"), (1.0, 0.5, 6700.0, "b"), (2.0, 0.8, 6700.0, "c"), (3.0, 0.8, 6700.0, "d")]
    up, log = octave_up(notes, trk)
    if [round(n[2]) for n in up] != [7400, 7400, 6700, 6700, 6700] or len(log) != 1:
        fails.append(f"往上改八度不对：{[round(n[2]) for n in up]} {log}")
    sp, log = split_tail(notes, trk)
    got = [(round(n[0], 2), round(n[2]), n[3]) for n in sp if 1.9 < n[0] < 4]
    if got != [(2.0, 6700, "c"), (2.4, 6500, "-"), (3.0, 6700, "d")] or len(log) != 1:
        fails.append(f"音尾拆音不对：{got} {log}")
    # ③ 没字的串：轻的删、响的留、接在字后面的拖腔不算串；④ 补段里没字的删、有字的留
    lv = {0: -40.0, 1: -20.0, 2: -21.0}
    level = lambda a, b: lv[0] if a < 2 or a >= 7.3 else lv[1] if a < 6 else lv[2]   # noqa: E731
    ns = [(0.0, 0.5, 6000.0, "-"), (0.6, 0.5, 6200.0, "-"),                   # 前奏：轻、没字 → 删
          (3.0, 0.4, 6400.0, "a"), (3.4, 0.4, 6400.0, "-"), (3.8, 0.3, 6200.0, "-"),   # 接在字后面的拖腔 → 不动
          (5.0, 0.4, 6000.0, "-"), (6.5, 0.4, 6400.0, "b"),                  # 响、没字 → 不动
          (7.8, 0.4, 6000.0, "-")]                                            # 字后面隔了 0.9 秒、轻 → 是串，删
    kept, log = drop_quiet_orphans(ns, level)
    if [n[0] for n in kept] != [3.0, 3.4, 3.8, 5.0, 6.5] or len(log) != 2:
        fails.append(f"删没字的轻串不对：{[n[0] for n in kept]} {log}")
    kept, log = drop_lyricless_patches(ns, [(0.0, 1.2), (2.9, 4.2)])
    if [n[0] for n in kept] != [3.0, 3.4, 3.8, 5.0, 6.5, 7.8] or len(log) != 1:
        fails.append(f"删没字的补段不对：{[n[0] for n in kept]} {log}")
    # ⑤ 补的音照原唱：从 E4 兜到 G4（中位 66.5）在 C 和声小调里取 G4；没声 → None；没给调式 → 最近的半音
    T2 = np.arange(0, 2, 0.01)
    m2 = np.where(T2 < 0.1, 64.0, np.where(T2 < 0.3, 66.5, 67.0))
    m2[T2 >= 1.0] = np.nan
    trk2 = (T2, m2, ~np.isnan(m2))
    po = sung_pitch(trk2, {"type": "HarmonicMinor", "root": "C"})
    if po(0.0, 0.29) != 6700.0 or po(1.2, 1.5) is not None:
        fails.append(f"补的音照原唱不对：{po(0.0, 0.29)} {po(1.2, 1.5)}")
    m3 = np.full(len(T2), 66.2)
    if sung_pitch((T2, m3, np.ones(len(T2), bool)), None)(0.0, 0.5) != 6600.0:
        fails.append("没给调式时 66.2 该取最近的半音 F#4")
    if sung_pitch(trk2, {"type": "Major", "root": "C"})(0.12, 0.28) != 6700.0:
        fails.append("C 大调里 66.5 该取 G4")
    return fails


if __name__ == "__main__":
    print(selftest())
