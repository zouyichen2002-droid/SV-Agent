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
OUT = pathlib.Path("E:/sv-agent-data/probes/m1-03-lyrics")
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"


def repair(notes: list, chars: list[str], pys: list[str]) -> tuple[list, list[dict]]:
    notes = sorted(notes)
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


def sung_differently(asr_notes: list, chars: list[str], pys: list[str], log: list[dict]) -> list[dict]:
    """只靠听写那一版：歌词里的字，听写出来明显不一样（不是近似音）→ Suno 可能唱成了别的字。
    修歌词时动过的地方（漂移处）不报 —— 那里只靠听写的对齐本来就乱，报出来是噪声。"""
    touched = {x["时间"] for x in log}
    sung = [n for n in sorted(asr_notes) if n[3] not in E.SKIP]
    ops = A.align(pys, [n[3] for n in sung])
    out = []
    for i, j, k in ops:
        if k == "不一样" and fmt(sung[j][0]) not in touched:
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
