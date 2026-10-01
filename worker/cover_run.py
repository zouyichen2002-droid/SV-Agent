# -*- coding: utf-8 -*-
r"""Cover Skill 的 Python Worker（v3 阶段 3，2026-10-01）：一首歌 → SynthV 工程。

把 M1 的 9 步（docs/m1/station-end.md §1）串成一条命令，产物都写进项目文件夹（sv-project 插件管的那个）：

    素材\  原曲整首.wav、source.json、歌词_原文.txt（插件从创作者的消息里原样取）、歌词_要唱的字.txt
    分离\  audio-separator 两步（显卡；创作者 10-01 定）+ 主唱缺的段用整条人声补
    拍子\  config.json → tempo_map.json + 节拍器
    扒谱\  Vocal2Midi（GAME + 听写）、basic-pitch 多声部（挑八度的第二个裁判）
    模板\  模板_<歌名>.svp（声库默认星尘，创作者 10-01 定）
    rNN\   song.json → <歌名>_扒谱_rNN.svp（+ 吸格线前、报告 json）+ 说明.md
    日志\  每一步的输出、进度.jsonl（插件读它报进度）、翻唱_rNN.json（总结）

- 每一步做完的跳过：中途断了，再跑一遍接着走（rNN 那一步除外：每一版都写新文件）
- 找拍子单线程约 20 分钟，和补段 / 扒谱 / 多声部并行
- 每一步的输出写进日志文件，不用管道接（DSH 的 Windows 沙箱里，管道接别的程序的输出会 EPERM）
- 一开始把自己调成「低于正常」，起的子程序都跟着低
- 只往项目文件夹里写
- 语言（10-01 加英文、日语）：按歌词认（有假名 → 日语，只有字母 → 英文）。英文、日语把歌词交给 Vocal2Midi 自己对齐，
  不走按拼音修字和中文定的规矩；声库用 SV 的跨语种（轨和每个音都设成那种语言）

    python cover_run.py <项目文件夹> --round rNN --source <链接 | 本地音频 | 已有> [--lyrics <歌词原文.txt>] [--voice 星尘]
                        [--language auto|zh|en|ja] [--config cover_config.json]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
KARAOKE_TAIL = "(Vocals)_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.wav"


class StepFailed(Exception):
    def __init__(self, step: str, why: str):
        super().__init__(f"{step}：{why}")
        self.step, self.why = step, why


def low_priority() -> None:
    if os.name == "nt":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)   # BELOW_NORMAL


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Run:
    def __init__(self, project: pathlib.Path, round_id: str, cfg: dict):
        self.P, self.name, self.round, self.cfg = project, project.name, round_id, cfg
        self.logs = project / "日志"
        self.logs.mkdir(exist_ok=True)
        self.progress = self.logs / "进度.jsonl"
        self.t0 = time.time()
        self.steps: list[dict] = []
        self.spikes = pathlib.Path(cfg["spikes"])
        # 沙箱里 site-packages 写不了：numba（librosa 用）一 import 就在那儿试建临时文件，建不了 Windows 的 tempfile 会一直重试
        # （10-01 实测：沙箱里卡死、CPU 满着跑了十几分钟）→ 缓存放到可写的临时目录。
        # 要设在**自己的进程**里（粗估速度是这个进程自己 import librosa），不只是传给子程序 —— 10-01 第一次只传给了子程序，这一步就卡死了
        os.environ.setdefault("NUMBA_CACHE_DIR", str(pathlib.Path(os.environ.get("TEMP", str(self.logs))) / "numba_cache"))
        os.environ["PYTHONIOENCODING"] = "utf-8"
        self.env = dict(os.environ)

    def note(self, step: str, state: str, detail: str = "") -> None:
        row = {"时间": stamp(), "秒": round(time.time() - self.t0, 1), "步": step, "状态": state, "说明": detail}
        with open(self.progress, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{row['秒']:>7.1f}s] {step} {state} {detail}", flush=True)
        if state in ("完成", "跳过", "失败"):
            self.steps.append(row)

    def _argv_log(self, step: str, argv: list[str]):
        log = self.logs / f"{step}.log"
        fh = open(log, "ab")
        fh.write(f"\n===== {stamp()} {' '.join(map(str, argv))}\n".encode("utf-8"))
        fh.flush()
        return log, fh

    def run(self, step: str, argv: list[str], cwd: pathlib.Path | None = None) -> None:
        log, fh = self._argv_log(step, argv)
        try:
            r = subprocess.run([str(a) for a in argv], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=self.env)
        finally:
            fh.close()
        if r.returncode != 0:
            raise StepFailed(step, f"退出码 {r.returncode}（看 {log}）")

    def start(self, step: str, argv: list[str], cwd: pathlib.Path | None = None):
        log, fh = self._argv_log(step, argv)
        p = subprocess.Popen([str(a) for a in argv], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=self.env)
        return p, fh, log


# ---------------------------------------------------------------- 每一步

def step_source(r: Run, source: str) -> pathlib.Path:
    d = r.P / "素材"
    d.mkdir(exist_ok=True)
    wav = d / "原曲整首.wav"
    if wav.exists():
        r.note("原曲", "跳过", "素材\\原曲整首.wav 已经有了")
        return wav
    if source in ("", "已有"):
        raise StepFailed("原曲", "项目里没有 素材\\原曲整首.wav，又没给来源（链接或本地音频）")
    r.note("原曲", "开始", source)
    info: dict = {}
    if source.startswith(("http://", "https://")):
        r.run("原曲_下载", [r.cfg["yt_dlp"], "--ignore-config", "--no-cookies-from-browser", "--no-cache-dir", "--no-playlist",
                          "-f", "bestaudio", "--write-info-json", "-o", str(d / "原曲_下载.%(ext)s"), source])
        media = [p for p in d.glob("原曲_下载.*") if not p.name.endswith(".info.json") and not p.name.endswith(".part")]
        if len(media) != 1:
            raise StepFailed("原曲", f"下载完找不到唯一的音频文件：{[p.name for p in media]}")
        src = media[0]
        ij = d / "原曲_下载.info.json"
        if ij.exists():
            meta = json.loads(ij.read_text(encoding="utf-8"))
            info = {"页面标题": meta.get("title"), "上传者": meta.get("uploader"), "发布": meta.get("upload_date"),
                    "页面": meta.get("webpage_url"), "时长秒": meta.get("duration"), "格式": meta.get("format")}
        how = f"yt-dlp 不登录、只下音频 → {src.name}"
    else:
        src = pathlib.Path(source)
        if not src.is_file():
            raise StepFailed("原曲", f"本地音频不存在：{src}")
        how = f"本地文件（只读，不改原文件）：{src}"
    r.run("原曲_转换", [r.cfg["ffmpeg"], "-hide_banner", "-nostdin", "-i", str(src), "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", str(wav)])
    meta = {"曲名": r.name, "来源": source, **{k: v for k, v in info.items() if v}, "下载": how,
            "转换": "ffmpeg → 原曲整首.wav（44.1 kHz 立体声 16 位）", "页面声明": "没读页面声明 —— 别人的作品只在本地用，发布前确认授权（PRD §14）",
            "时间": stamp()}
    (d / "source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    r.note("原曲", "完成", wav.name)
    return wav


LANG_NAMES = {"zh": "中文", "en": "英文", "ja": "日语"}
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
HAN = re.compile(r"[㐀-䶿一-鿿]")
JA_RUN = re.compile(r"[ぁ-ゖゝゞァ-ヺー-ヾ㐀-䶿一-鿿々〆ヵヶ]+|[A-Za-z]+|[0-9]+")
EN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
LABEL_LINE = re.compile(r"^[\[【].*[\]】]$")                       # 整行是 [Verse 1]、[Instrumental Drop]、【副歌】这种标签


def detect_language(text: str) -> str:
    """歌词是哪种语言（10-01，创作者给的六首：4 首中文、1 首英文、1 首日语）：
    假名多 → 日语；汉字多 → 中文；只有字母 → 英文；都不够 → 中文（M1 以来的默认）。"""
    kana, han, latin = len(KANA.findall(text)), len(HAN.findall(text)), len(re.findall(r"[A-Za-z]", text))
    if kana >= 20 and kana >= 0.2 * (kana + han):
        return "ja"
    if han >= 20:
        return "zh"
    if latin >= 50:
        return "en"
    return "zh"


def _sung_lines(text: str, spikes: pathlib.Path):
    """去掉空行、《标题》、段落标签（中文那套 + 整行方括号）的每一行。"""
    sys.path.insert(0, str(spikes / "m1-03-lyrics"))
    import clean_lyrics as LC                                    # noqa: E402
    for line in unicodedata.normalize("NFKC", text).replace("’", "'").splitlines():
        s = line.strip()
        if s and not re.fullmatch(r"《[^》]*》", s) and not LC.SECTION.match(s) and not LABEL_LINE.match(s):
            yield s


def clean_lines_other(text: str, lang: str, spikes: pathlib.Path) -> list[str]:
    """英文：每行留单词（连字符拆开、撇号留着）；日语：每行留假名、汉字、字母、数字，标点换成空格。"""
    out = []
    for s in _sung_lines(text, spikes):
        kept = EN_WORD.findall(s) if lang == "en" else JA_RUN.findall(s)
        if kept:
            out.append(" ".join(kept))
    return out


def selftest_language(spikes: pathlib.Path) -> list[str]:
    """认语言、清理歌词的自检（例子是造的，不是哪首歌的歌词）。"""
    fails = []
    zh = "春天来了花开满园小河流水哗啦啦\n" * 3
    ja = "[Verse 1]\n春の風が吹いてる、きみの声が聞こえる\nああ　空を見上げて\n[Chorus]\n" * 2
    en = "[Chorus]\nI can't stop dancing in the moonlight\n(Oh-oh) we're running out of time\n" * 2
    for text, want in ((zh, "zh"), (ja, "ja"), (en, "en"), ("", "zh")):
        if detect_language(text) != want:
            fails.append(f"认语言：{text[:12]!r} → {detect_language(text)}（应 {want}）")
    got = clean_lines_other(ja, "ja", spikes)
    if got[:2] != ["春の風が吹いてる きみの声が聞こえる", "ああ 空を見上げて"] or len(got) != 4:
        fails.append(f"清理日语：{got[:2]}")
    got = clean_lines_other(en, "en", spikes)
    if got[:2] != ["I can't stop dancing in the moonlight", "Oh oh we're running out of time"] or len(got) != 4:
        fails.append(f"清理英文：{got[:2]}")
    return fails


HANZI_DIGITS = "零一二三四五六七八九"


def numbers_to_hanzi(text: str) -> tuple[str, list[str]]:
    """歌词里的数字换成要唱的字（清理时数字会被当标点丢掉）。10-01：《逃跑的天使》里一个全角「４」M1 时是手工改成「四」的。
    一两位数按读法（4 → 四、12 → 十二、25 → 二十五）；三位以上逐个念（2025 → 二零二五）。返回 (新文本, 改了哪些)。"""
    import re
    text = text.translate({ord("０") + i: ord("0") + i for i in range(10)})
    changes: list[str] = []

    def read(m: "re.Match[str]") -> str:
        s = m.group()
        if len(s) >= 3:
            out = "".join(HANZI_DIGITS[int(c)] for c in s)
        else:
            n = int(s)
            if n < 10:
                out = HANZI_DIGITS[n]
            else:
                tens, ones = divmod(n, 10)
                out = ("" if tens == 1 else HANZI_DIGITS[tens]) + "十" + ("" if ones == 0 else HANZI_DIGITS[ones])
        changes.append(f"{s}→{out}")
        return out

    return re.sub(r"[0-9]+", read, text), changes


def step_lyrics(r: Run, raw: pathlib.Path | None, lang_arg: str = "auto") -> tuple[pathlib.Path | None, str]:
    """→ (要唱的字, 语言)。语言没指定就按歌词认（每次都从原文认，接着跑时也一样）；没歌词又没指定 → 中文。"""
    out = r.P / "素材" / "歌词_要唱的字.txt"
    lang = "zh" if lang_arg == "auto" else lang_arg
    if raw is not None and str(raw) == "none":
        r.note("歌词", "跳过", f"这一版不用歌词（创作者说的）：只靠听写（{LANG_NAMES[lang]}）")
        return None, lang
    if raw is None:
        raw = r.P / "素材" / "歌词_原文.txt"
    if not raw.exists():
        r.note("歌词", "跳过", f"没给歌词：只靠听写（字会差一些；{LANG_NAMES[lang]}）")
        return None, lang
    text = raw.read_text(encoding="utf-8")
    if lang_arg == "auto":
        lang = detect_language(text)
    if out.exists():
        r.note("歌词", "跳过", f"素材\\歌词_要唱的字.txt 已经有了（{LANG_NAMES[lang]}）")
        return out, lang
    changes: list[str] = []
    if lang == "zh":
        sys.path.insert(0, str(r.spikes / "m1-03-lyrics"))
        import clean_lyrics as LC                                # noqa: E402
        text, changes = numbers_to_hanzi(text)
        lines = LC.clean_lines(text)
    else:
        fails = selftest_language(r.spikes)
        if fails:
            raise StepFailed("歌词", f"认语言 / 清理的自检不过：{fails}")
        lines = clean_lines_other(text, lang, r.spikes)
    if not lines:
        raise StepFailed("歌词", f"{raw.name} 清理以后一个字都没剩")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if lang == "zh":
        extra = f"；数字换成汉字：{'、'.join(changes)}（听的时候留意读法对不对）" if changes else ""
        r.note("歌词", "完成", f"{len(lines)} 行、{sum(len(x) for x in lines)} 字（去掉了标题、段落标签、标点）{extra}")
    else:
        unit = (f"{sum(len(x.split()) for x in lines)} 个词" if lang == "en"
                else f"{sum(len(x.replace(' ', '')) for x in lines)} 个字")
        r.note("歌词", "完成", f"{LANG_NAMES[lang]}：{len(lines)} 行、{unit}（去掉了段落标签、标点）")
    return out, lang


def step_separate(r: Run, wav: pathlib.Path) -> dict:
    out = r.P / "分离"
    logf = out / "separate_log.json"
    if logf.exists() and not json.loads(logf.read_text(encoding="utf-8")).get("fails"):
        r.note("分离", "跳过", "分离\\ 已经分好、核对通过")
    else:
        r.note("分离", "开始", "人声 / 伴奏 → 主唱 / 叠唱（显卡约 75 秒）")
        r.run("分离", [r.cfg["separator_python"], r.spikes / "m1-01-voice-to-midi" / "separate_stems.py", wav, out, str(r.cfg.get("separation_threads", 8))],
              cwd=r.spikes / "m1-01-voice-to-midi")
        r.note("分离", "完成", "核对通过（长度、零点、加起来 ≈ 原曲、主唱比叠唱响）")
    log = json.loads(logf.read_text(encoding="utf-8"))
    stems = {"人声": log["step1"]["vocals"], "伴奏": log["step1"]["instrumental"], "主唱": log["step2"]["lead"], "叠唱": log["step2"]["backing"]}
    for k, v in stems.items():
        if not pathlib.Path(v).exists():
            raise StepFailed("分离", f"{k} 分轨不见了：{v}")
    if not stems["主唱"].endswith(KARAOKE_TAIL):
        raise StepFailed("分离", f"主唱分轨的名字不对（应该以 {KARAOKE_TAIL} 结尾）：{stems['主唱']}")
    return stems


def step_hybrid(r: Run, stems: dict) -> pathlib.Path:
    out = r.P / "分离" / "主唱_缺的段用整条人声补.wav"
    if out.exists():
        r.note("补段", "跳过", "已经补过")
        return out
    r.note("补段", "开始", "主唱分轨整段没声、整条人声又和平时主唱一样响的地方，用整条人声补")
    r.run("补段", [r.cfg["separator_python"], r.spikes / "m1-01-voice-to-midi" / "hybrid_lead.py", stems["人声"], stems["主唱"], out],
          cwd=r.spikes / "m1-01-voice-to-midi")
    segs = json.loads((out.parent / (out.name + ".json")).read_text(encoding="utf-8"))
    r.note("补段", "完成", f"补了 {len(segs.get('用整条人声的段', []))} 段、共 {segs.get('合计秒', 0)} 秒")
    return out


def tempo_start(r: Run, wav: pathlib.Path, stems: dict):
    d = r.P / "拍子"
    d.mkdir(exist_ok=True)
    tm = d / "tempo_map.json"
    if tm.exists():
        r.note("找拍子", "跳过", "拍子\\tempo_map.json 已经有了")
        return None
    import librosa                                               # noqa: E402
    import numpy as np                                           # noqa: E402
    y, sr = librosa.load(str(wav), sr=22050, mono=True)
    bpm = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    cfg = {"name": r.name, "accomp": stems["伴奏"], "vocal": stems["人声"], "out": str(d), "bpm_center": round(bpm),
           "candidates": [{"from": "整首原曲的起音自相关（librosa beat_track，粗）", "bpm": round(bpm, 2), "first_beat_s": None}]}
    (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    r.note("找拍子", "开始", f"粗估 {bpm:.2f} BPM → 分段、找「1」、小节线、速度表（单线程约 20 分钟，和下面几步一起跑）")
    return r.start("找拍子", [r.cfg["python"], r.spikes / "m5-00-beat-grid" / "tempo_map.py", d / "config.json"], cwd=r.spikes / "m5-00-beat-grid")


def tempo_wait(r: Run, started) -> pathlib.Path:
    tm = r.P / "拍子" / "tempo_map.json"
    if started is not None:
        p, fh, log = started
        code = p.wait()
        fh.close()
        if code != 0 or not tm.exists():
            raise StepFailed("找拍子", f"退出码 {code}（看 {log}）")
        runs = json.loads(tm.read_text(encoding="utf-8")).get("runs", [])
        r.note("找拍子", "完成", "速度：" + "、".join(f"{x['bpm']:.2f}" for x in runs[:4]) + (" 等" if len(runs) > 4 else ""))
    return tm


def step_v2m(r: Run, lead: pathlib.Path, lang: str = "zh", lyrics: pathlib.Path | None = None) -> pathlib.Path:
    """中文：只听写，字到生成工程那步按歌词修（M1 的做法）。
    英文、日语（10-01）：修字是按拼音的用不上 → 把歌词交给 Vocal2Midi，它自己拿歌词对听写（日语读音用 fugashi 替身）。"""
    d = r.P / "扒谱"
    d.mkdir(exist_ok=True)
    if lang == "zh":
        stem, extra, what = f"{r.name}_v2m_asr_主唱补段", ["--asr"], "Vocal2Midi：GAME 切音 + Qwen3-ASR 听写（显卡约 40 秒）"
    else:
        stem = f"{r.name}_v2m_{lang}_主唱补段"
        extra = ["--language", lang] + (["--lyrics", lyrics] if lyrics else ["--asr"])
        what = f"Vocal2Midi（{LANG_NAMES[lang]}）：GAME 切音 + Qwen3-ASR 听写" + ("、拿歌词对齐" if lyrics else "") + "（显卡约 1 分钟）"
    mid = d / f"{stem}.mid"
    if mid.exists():
        r.note("扒谱", "跳过", "扒谱\\ 已经有了")
        return mid
    r.note("扒谱", "开始", what)
    r.run("扒谱", [r.cfg["vocal2midi_python"], r.spikes / "m1-01-voice-to-midi" / "run_vocal2midi.py", lead, d, stem, *extra,
                  "--device", "dml", "--slicing", "heuristic", "--batch-size", "1", "--asr-batch-size", "1", "--low-priority"],
          cwd=r.spikes / "m1-01-voice-to-midi")
    if not mid.exists():
        raise StepFailed("扒谱", f"没出 {mid.name}")
    r.note("扒谱", "完成", mid.name)
    return mid


def step_bp(r: Run, lead: pathlib.Path) -> pathlib.Path:
    out = r.P / "扒谱" / "basic_pitch_raw_主唱补段.json"
    if out.exists():
        r.note("多声部", "跳过", "已经有了")
        return out
    r.note("多声部", "开始", "basic-pitch（挑八度的第二个裁判，约 1 分钟）")
    r.run("多声部", [r.cfg["pi_audio_python"], r.spikes / "m1-02-harmony" / "bp_raw.py", lead, out, str(r.cfg.get("basic_pitch_threads", 4))],
          cwd=r.spikes / "m1-02-harmony")
    r.note("多声部", "完成", out.name)
    return out


def step_template(r: Run, voice: dict, stems: dict, tm: pathlib.Path) -> pathlib.Path:
    d = r.P / "模板"
    d.mkdir(exist_ok=True)
    out = d / f"模板_{r.name}.svp"
    tempo = json.loads(tm.read_text(encoding="utf-8"))["map"]["tempo"]
    if out.exists():
        # 10-01《调查中》：模板那一步自检不过时文件已经写出来了，接着跑把它当成「已经有了」，用的还是出错前的速度表
        # → 模板的速度表得是现在这张，不是就挪开重做（不删）
        if json.loads(out.read_text(encoding="utf-8"))["time"]["tempo"] == tempo:
            r.note("模板", "跳过", "已经有了（速度表和现在的一样）")
            return out
        old = out.with_name(f"{out.stem}_弃用_速度表是旧的_{time.strftime('%m%d%H%M%S')}.svp")
        out.rename(old)
        r.note("模板", "开始", f"原来的模板速度表是旧的，挪成 {old.name}、重做")
    cfg = {"base": voice["base"], "base_voice_track": voice["voice_track"], "base_accomp_track": voice["accomp_track"],
           "base_ref_track": voice["ref_track"], "voice_track_name": voice["voice_track"], "ref_name": "原曲人声（分离，参考，静音）",
           "accomp": stems["伴奏"], "ref_vocal": stems["人声"], "tempo_map": str(tm), "out": str(out)}
    (d / "template.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    r.note("模板", "开始", f"声库 {voice['voice_track']}；速度表用量出来的")
    try:
        r.run("模板", [r.cfg["python"], r.spikes / "m1-01-voice-to-midi" / "make_template.py", d / "template.json"], cwd=r.spikes / "m1-01-voice-to-midi")
    except StepFailed:
        if out.exists():                                         # 自检不过的模板挪开（不删），接着跑时不会被当成「已经有了」
            out.rename(out.with_name(f"{out.stem}_弃用_自检不过_{time.strftime('%m%d%H%M%S')}.svp"))
        raise
    if not out.exists():
        raise StepFailed("模板", f"没出 {out.name}")
    r.note("模板", "完成", out.name)
    return out


def step_round(r: Run, voice: dict, tpl, stems, lead, lyrics, mid, bp, tm, lang: str = "zh") -> dict:
    rdir = r.P / r.round
    rdir.mkdir(exist_ok=True)
    out_svp = rdir / f"{r.name}_扒谱_{r.round}.svp"
    if out_svp.exists():
        raise StepFailed("生成工程", f"{out_svp} 已经有了 —— 每一版都写新文件，另开一版")
    # 你定的规矩（09-30：对不上的行不放 / 长音截两段写韵母 / 念唱）和修字都是按中文拼音定的 → 英文、日语不用
    cfg = {"name": r.name, "template": str(tpl), "vocal_template_track": voice["voice_track"], "vocal_stem": str(lead),
           "ref_vocal_audio": str(lead), "ref_vocal_name": "原曲主唱（分离；主唱缺的段用整条人声补，参考，静音）", "accomp": stems["伴奏"],
           "v2m_mid": str(mid), "bp_raw": str(bp), "tempo_map": str(tm), "rounds": str(r.P), "round": r.round,
           "rules_0930": 3 if lang == "zh" else 0}
    if lang != "zh":
        cfg["language"] = lang
    elif lyrics is not None:
        cfg["lyrics"] = str(lyrics)
    (rdir / "song.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    if lang == "zh":
        r.note("生成工程", "开始", f"{r.round}：修歌词（只改字）、挑八度、你定的规矩、吸格线")
    else:
        r.note("生成工程", "开始", f"{r.round}（{LANG_NAMES[lang]}）：挑八度、吸格线；声库设成 SV 跨语种{LANG_NAMES[lang]}"
                                  "（修字和你定的规矩是按中文定的，这首不用）")
    r.run("生成工程", [r.cfg["python"], r.spikes / "m1-01-voice-to-midi" / "song_round.py", rdir / "song.json"], cwd=r.spikes / "m1-01-voice-to-midi")
    if not out_svp.exists():
        raise StepFailed("生成工程", f"没出 {out_svp.name}")
    report = rdir / f"{r.name}_扒谱_{r.round}.json"
    res = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    stats = {"工程": str(out_svp), "扒出的音": res.get("notes_v2m"), "歌词字数": res.get("lyrics_chars"),
             "改八度": (res.get("octave") or {}).get("changed"), "规矩": res.get("rules_0930")}
    r.note("生成工程", "完成", out_svp.name)
    return stats


def write_readme(r: Run, source: str, lyrics, stats: dict, lang: str = "zh") -> None:
    lyric_text = "创作者给的（素材/歌词_原文.txt → 歌词_要唱的字.txt）" if lyrics else "没给，只靠听写"
    if lyrics and lang != "zh":
        lyric_text += "，Vocal2Midi 拿它对听写（修字是按中文拼音的，这首没修）"
    lines = [f"# 《{r.name}》{r.round}", "", f"- 生成：{stamp()}（cover_run.py，一条命令跑完）", f"- 来源：{source or '项目里已有的原曲'}",
             f"- 歌词：{lyric_text}",
             *([f"- 语言：{LANG_NAMES[lang]}（星尘用 SV 的跨语种：这条轨和每个音都设成{LANG_NAMES[lang]}）"] if lang != "zh" else []),
             f"- 工程：`{pathlib.Path(stats['工程']).name}`（打开就放伴奏和扒谱；原曲主唱那条静音，点开对照）",
             f"- 扒出 {stats.get('扒出的音')} 个音；改了 {stats.get('改八度')} 个八度", "",
             "听的时候：觉得哪里不对就直接在 SV 里改、存盘 —— 插件会自动备份你改的样子，下一版照你改的学。"]
    (r.P / r.round / "说明.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="一首歌 → SynthV 工程（写进项目文件夹）")
    ap.add_argument("project")
    ap.add_argument("--round", required=True)
    ap.add_argument("--source", default="已有")
    ap.add_argument("--lyrics", default=None)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--language", default="auto", choices=["auto", "zh", "en", "ja"], help="唱的语言；auto = 按歌词认")
    ap.add_argument("--config", default=str(HERE / "cover_config.json"))
    a = ap.parse_args()
    low_priority()
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads(pathlib.Path(a.config).read_text(encoding="utf-8"))
    project = pathlib.Path(a.project).resolve()
    if not (project / "sv-project.json").exists():
        print(f"{project} 不是项目（没有 sv-project.json）")
        return 2
    voice_name = a.voice or cfg.get("default_voice")
    voice = cfg["voices"].get(voice_name)
    if voice is None:
        print(f"没有声库「{voice_name}」：配置里只有 {list(cfg['voices'])}")
        return 2
    r = Run(project, a.round, cfg)
    r.note("开始", "开始", f"《{r.name}》{a.round}，声库 {voice_name}")
    try:
        wav = step_source(r, a.source)
        lyrics, lang = step_lyrics(r, pathlib.Path(a.lyrics) if a.lyrics else None, a.language)
        stems = step_separate(r, wav)
        started = tempo_start(r, wav, stems)
        try:
            lead = step_hybrid(r, stems)
            mid = step_v2m(r, lead, lang, lyrics)
            bp = step_bp(r, lead)
        except BaseException:
            if started is not None:
                started[0].kill()
                started[1].close()
            raise
        tm = tempo_wait(r, started)
        tpl = step_template(r, voice, stems, tm)
        stats = step_round(r, voice, tpl, stems, lead, lyrics, mid, bp, tm, lang)
        stats["语言"] = LANG_NAMES[lang]
        write_readme(r, a.source, lyrics, stats, lang)
    except StepFailed as e:
        r.note(e.step, "失败", e.why)
        summary = {"结果": "失败", "步": e.step, "原因": e.why, "各步": r.steps}
        (r.logs / f"翻唱_{a.round}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        return 1
    total = round(time.time() - r.t0)
    summary = {"结果": "完成", "总秒": total, "版本": a.round, "统计": stats, "各步": r.steps}
    (r.logs / f"翻唱_{a.round}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    r.note("结束", "完成", f"共 {total // 60} 分 {total % 60} 秒 → {pathlib.Path(stats['工程']).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
