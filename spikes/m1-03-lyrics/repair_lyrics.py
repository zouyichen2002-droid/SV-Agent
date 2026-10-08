# -*- coding: utf-8 -*-
"""M1-03：AI 修歌词 —— 创作者给的歌词，换到扒谱的每个音上（C03 的一部分）。

创作者 09-29：「主旋律我认为做的很不错了，保留这个方法。加一个AI介入：翻唱的时候我会主动和你说歌词，这样你就可能主动去修改歌词
……有可能会出现漂移，比如实际是120个字但是MIDI扒出来只有115个……这个先尝试一下，AI修复歌词」。

底子：Vocal2Midi 的「给原歌词」模式（它在扒谱前就用歌词去对听写结果，《傍晚》185 字对上 182 个）。
这里再按拼音全局对齐（lyric_align，标成「-」的音当空位）把剩下的修掉：
1. 对上的音 → 换成歌词里那个字的拼音（终稿用的就是拼音）
2. 有字没地方放、附近有够长的空位（≥ 0.15 秒）→ 放进空位；空位旁边没多余的字 → 留「-」当拖音
3. 真没空位（字比音多，就是「漂移」）→ 把前一个音对半拆开，后一半给这个字（前一个太短就拆后一个）
4. 多出来的音（歌词里没有这个字）→ 改成「-」
5. 另拿「只靠听写」那一版对一遍歌词：Suno 唱得和歌词明显不一样的地方（听写出来是另一个字，不是近似音）照歌词放，但列出来
每一处改动都列出来（时间、原来是什么、改成什么），让创作者一眼看完。

自检（不过就不用）：造一段歌词当音，注入空位、近似音、删一个音（考拆音）、多一个音 → 修完的歌词必须和原文一字不差，动作数对得上。

    E:/sv-agent-data/envs/vocal2midi/Scripts/python.exe repair_lyrics.py <底子.mid> <版名> [<只靠听写的.mid>]
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-01-voice-to-midi"))
import eval_lyrics as E  # noqa: E402
import lyric_align as A  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SPLIT_MIN_SEC = 0.3
TIME_SPLIT_MIN_SEC = 0.06    # 照强制对齐的时间切音时，切出来的每一段至少这么长（10-06）
GAP_FILL_MIN_SEC, GAP_FILL_MAX_SEC = 0.1, 0.25   # 字的时间落在两个音中间的空档里：空档至少这么长才补一个音，补的音最长这么长
OUT = pathlib.Path("E:/sv-agent-data/probes/m1-03-lyrics")
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"


def repair(notes: list, chars: list[str], pys: list[str], ops: list | None = None,
           times: list | None = None) -> tuple[list, list[dict]]:
    """ops：哪个字配哪个音（lyric_align.align 的格式）；不给就整首拼音对齐。10-06 起有强制对齐时由 lyric_fuse.fuse_ops 给（notes 要已经排好序）。
    times：每个字强制对齐出来的起音（不是锚点的给 None）—— 没地方放的字先照这个时间放（落在拖音上就放上去，落在别的音中间就从那里切开），
    放不了再走原来的对半拆。"""
    notes = sorted(notes)
    if ops is None:
        ops = A.align(pys, [n[3] for n in notes], [n[1] for n in notes])
    out: list[list] = [list(n) for n in notes]
    char_of = [None] * len(out)                           # 每个音配上的是歌词里第几个字
    log, pending = [], []
    for i, j, k in ops:
        if j is not None and i is not None:
            if out[j][3] != pys[i]:
                log.append({"时间": fmt(out[j][0]), "动作": "补空位" if k == "补空位" else "换字",
                            "原来": out[j][3], "改成": f"{pys[i]}（{chars[i]}）"})
            out[j][3], char_of[j] = pys[i], i
        elif j is not None:
            if out[j][3] != "-":
                log.append({"时间": fmt(out[j][0]), "动作": "歌词里没有 → 拖音", "原来": out[j][3], "改成": "-"})
            out[j][3] = "-"
        else:
            pending.append(i)
    # 拆音：没地方放的字，找它前面最近的、已经配了字的音；太短就找后面的
    for i in pending:
        if times is not None and times[i] is not None:
            # 10-06《公主》：GAME 在唱得快的地方把几个字并成一个音（副歌里重复的快句），音太短、对半拆不了 →
            # 强制对齐知道这个字从哪一刻开始：落在拖音上就放上去；落在别的音中间就从那一刻切开（音高不动），后一段给这个字
            t = times[i]
            j = next((j for j in range(len(out)) if out[j][0] <= t <= out[j][0] + out[j][1] and char_of[j] is None), None)
            if j is None:
                j = next((j for j in range(len(out)) if out[j][0] <= t < out[j][0] + out[j][1] and out[j][1] >= 2 * TIME_SPLIT_MIN_SEC), None)
                if j is not None:                         # 离音的两头太近 → 切在离头尾至少 TIME_SPLIT_MIN_SEC 的地方
                    t = min(max(t, out[j][0] + TIME_SPLIT_MIN_SEC), out[j][0] + out[j][1] - TIME_SPLIT_MIN_SEC)
            if j is None:
                # 落在两个音中间的空档（GAME 没切出这个字）：空档够长就补一个音，音高照前一个音（没有就照后一个），要创作者听
                g = next((g for g in range(len(out) + 1)
                          if (g == 0 or out[g - 1][0] + out[g - 1][1] <= t) and (g == len(out) or t < out[g][0])), None)
                if g is not None and 0 < g < len(out):
                    a_, b_ = out[g - 1][0] + out[g - 1][1], out[g][0]
                    lo = max((char_of[k] for k in range(g) if char_of[k] is not None), default=-1)
                    hi = min((char_of[k] for k in range(g, len(out)) if char_of[k] is not None), default=len(pys))
                    if b_ - a_ >= GAP_FILL_MIN_SEC and lo < i < hi:
                        s0 = max(a_, min(t, b_ - GAP_FILL_MIN_SEC))
                        new = [s0, min(b_ - s0, GAP_FILL_MAX_SEC), out[g - 1][2], pys[i]]
                        out.insert(g, new)
                        char_of.insert(g, i)
                        log.append({"时间": fmt(s0), "动作": "补音（GAME 没切出这个字，音高照前一个音，要你听）", "原来": "",
                                    "改成": f"{pys[i]}（{chars[i]}，{new[1]:.2f} 秒）"})
                        continue
            ok = j is not None
            if ok:
                lo = max((char_of[k] for k in range(j) if char_of[k] is not None), default=-1)
                hi = min((char_of[k] for k in range(j + 1, len(out)) if char_of[k] is not None), default=len(pys))
                ok = lo < i < hi and (char_of[j] is None or char_of[j] < i)
            if ok and char_of[j] is None:
                log.append({"时间": fmt(out[j][0]), "动作": "补空位", "原来": out[j][3], "改成": f"{pys[i]}（{chars[i]}）"})
                out[j][3], char_of[j] = pys[i], i
                continue
            if ok:
                s, d, c, ly = out[j]
                out[j] = [s, t - s, c, ly]
                out.insert(j + 1, [t, s + d - t, c, pys[i]])
                char_of.insert(j + 1, i)
                log.append({"时间": fmt(s), "动作": "拆音（字比音多）", "原来": f"{ly}（{d:.2f} 秒）",
                            "改成": f"{ly} + {pys[i]}（照强制对齐的时间切在 {fmt(t)}：{t - s:.2f} + {s + d - t:.2f} 秒）"})
                continue
        before = [j for j in range(len(out)) if char_of[j] is not None and char_of[j] < i]
        after = [j for j in range(len(out)) if char_of[j] is not None and char_of[j] > i]
        cand = ([before[-1]] if before else []) + ([after[0]] if after else [])
        host = next((j for j in cand if out[j][1] >= SPLIT_MIN_SEC), None)
        if host is None:
            log.append({"时间": fmt(out[cand[0]][0]) if cand else "?", "动作": "没地方放（前后的音都太短，要你手放）",
                        "原来": "", "改成": f"{pys[i]}（{chars[i]}）"})
            continue
        s, d, c, ly = out[host]
        half = d / 2
        first, second = [s, half, c, ly], [s + half, d - half, c, pys[i]]
        if char_of[host] > i:                             # 拆的是后面那个音：前一半给这个字
            first, second = [s, half, c, pys[i]], [s + half, d - half, c, ly]
        out[host] = first
        out.insert(host + 1, second)
        char_of.insert(host + 1, i)
        if char_of[host] > i:
            char_of[host], char_of[host + 1] = i, char_of[host + 1] if False else char_of[host]
        log.append({"时间": fmt(s), "动作": "拆音（字比音多）", "原来": f"{ly}（{d:.2f} 秒）",
                    "改成": f"{first[3]} + {second[3]}（各 {half:.2f} 秒）"})
    return [tuple(n) for n in sorted(out)], log


def selftest_times() -> list[str]:
    """10-06 照强制对齐的时间放字：一个长音里并了两个字 → 照时间切开；一个字落在空档里 → 补一个音；次序不对的不放。"""
    fails = []
    pys = ["a", "b", "c", "d"]
    notes = [(0.0, 0.5, 6000.0, "a"), (1.0, 0.4, 6200.0, "d")]          # b 并在 a 里（0.3 秒处）、c 落在 0.5–1.0 的空档里（0.7 秒）
    ops = [(0, 0, "一样"), (1, None, "只在A"), (2, None, "只在A"), (3, 1, "一样")]
    out, log = repair(notes, ["甲", "乙", "丙", "丁"], pys, ops=ops, times=[0.0, 0.3, 0.7, 1.0])
    if [n[3] for n in out] != pys:
        fails.append(f"照时间切音 / 补音后的字不对：{[n[3] for n in out]}")
    elif abs(out[1][0] - 0.3) > 1e-9 or abs(out[0][1] - 0.3) > 1e-9 or out[1][2] != 6000.0:
        fails.append(f"切的位置或音高不对：{out[:2]}")
    elif abs(out[2][0] - 0.7) > 1e-9 or out[2][2] != 6000.0:
        fails.append(f"补的音位置或音高不对：{out[2]}")
    # 字的时间落在后面那个字的音里（次序反了）→ 不该照时间放
    out, log = repair(notes, ["甲", "乙", "丙", "丁"], pys, ops=[(0, 0, "一样"), (1, None, "只在A"), (2, None, "只在A"), (3, 1, "一样")],
                      times=[0.0, 1.2, None, 1.0])
    if any("照强制对齐" in x["改成"] for x in log):
        fails.append("次序反了也照时间切了音")
    return fails


def sung_differently(asr_notes: list, chars: list[str], pys: list[str], log: list[dict]) -> list[dict]:
    """只靠听写那一版：歌词里的字，听写出来明显不一样（不是近似音）→ Suno 可能唱成了别的字。
    漂移处（补空位、拆音）前后 1 秒不报 —— 那里只靠听写的对齐本来就乱，报出来是噪声。
    （09-29 第一版把所有改过的地方都排除了 → 以 r01 为底子时「换字」全被排除、一处都不报，已改。）"""
    sec = lambda t: int(t.split(":")[0]) * 60 + float(t.split(":")[1])
    drift = [sec(x["时间"]) for x in log if x["动作"] in ("补空位", "拆音（字比音多）")]
    sung = [n for n in sorted(asr_notes) if n[3] not in E.SKIP]
    ops = A.align(pys, [n[3] for n in sung])
    out = []
    for i, j, k in ops:
        if k == "不一样" and all(abs(sung[j][0] - t) > 1.0 for t in drift):
            out.append({"时间": fmt(sung[j][0]), "你的歌词": f"{chars[i]}（{pys[i]}）", "Suno 唱的像": sung[j][3]})
    return out


def selftest(chars: list[str], pys: list[str]) -> list[str]:
    n = 20
    base = [(i * 0.5, 0.4, 6000.0, pys[i]) for i in range(n)]
    bad = [list(x) for x in base]
    bad[3][3] = "-"                                       # 空位
    bad[5][3] = A._norm(pys[5]) + "g" if not pys[5].endswith("g") else pys[5][:-1]   # 近似音
    del bad[8]                                            # 少一个音 → 要拆前一个
    bad.insert(11, [bad[10][0] + 0.2, 0.1, 6000.0, "a"])  # 多一个音 → 改拖音
    got, log = repair([tuple(x) for x in bad], chars[:n], pys[:n])
    words = [x[3] for x in got if x[3] != "-"]
    fails = []
    if words != pys[:n]:
        fails.append(f"修完不是原文：{words} vs {pys[:n]}")
    acts = sorted(x["动作"] for x in log)
    if acts.count("拆音（字比音多）") != 1 or acts.count("歌词里没有 → 拖音") != 1 or acts.count("补空位") != 1:
        fails.append(f"动作数不对：{acts}")
    return fails


def main(base_mid: str, rnd: str, asr_mid: str | None = None) -> int:
    chars, pys = E.text_pinyin(E.LYRICS)
    fails = selftest(chars, pys)
    print("自检：", "通过（空位、近似音、少一个音要拆、多一个音 —— 修完和原文一字不差）" if not fails else "不通过")
    for f in fails:
        print("  ✗", f)
    if fails:
        return 1
    fixed, log = repair(E.load(base_mid), chars, pys)
    diff = sung_differently(E.load(asr_mid), chars, pys, log) if asr_mid else []
    res = {"底子": base_mid, "改动": log, "Suno 可能唱得和歌词不一样": diff, "修完": E.evaluate(fixed)}
    print(f"\n改动 {len(log)} 处：")
    for x in log:
        print(f"  {x['时间']}  {x['动作']}：{x['原来']} → {x['改成']}")
    print(f"\nSuno 可能唱得和你的歌词不一样 {len(diff)} 处（照你的歌词放了）：")
    for x in diff:
        print(f"  {x['时间']}  你的歌词 {x['你的歌词']}，Suno 唱的像「{x['Suno 唱的像']}」")
    print("\n修完：")
    for k, v in res["修完"].items():
        print(f"  {k}：{v}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{rnd}_lyrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"{rnd}_notes.json").write_text(json.dumps(fixed, ensure_ascii=False), encoding="utf-8")
    print(f"\n结果：{OUT / f'{rnd}_lyrics.json'} · 修完的音：{OUT / f'{rnd}_notes.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
