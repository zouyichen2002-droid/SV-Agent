"""一首歌的项目配置。**每首新歌只改这个 JSON，不改代码。**

## 为什么需要它

第一轮 test（晓风残月）走通之后，六个步骤脚本里的路径是写死的 ——
`LYRICS = songs/xiaofeng/lyrics.txt`、`PROJECT = E:/潮声回响/test2.svp`。
换一首歌就要改代码，而创作者不写代码。

所以抽成配置：`songs/<slug>/project.json`，脚本靠环境变量 `SVAGENT_SONG`
选择当前是哪一首。命令行上就是

    SVAGENT_SONG=yequ python scripts/step3_melody.py --write --closed

## 「一个项目一套文件」在这里落地

创作者定的规则：一个项目就是一个 txt、一个 svp、一个 FL 工程。
配置里把这四个路径固定下来，所有步骤都写回同一份，不因为改动就新建文件。

    lyrics     歌词 txt（唯一真相来源，含和声进行）
    svp        SynthV 工程（成品）
    mid        伴奏 MIDI（导入 FL 用）
    wav        FL 渲染的伴奏（工程按绝对路径引用，别挪）
    flp        FL 工程（可选，创作者自己存）

备份统一去 `svp` 同级的 `_backup/`。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SONGS = ROOT / "songs"
TEMPLATE = SONGS / "_template" / "empty_v196.svp"

# 曲式的默认值：48 小节 ≈ 2:54 @66BPM，在工作流要求的 2.5–5 分钟内。
# 更长的歌要在 project.json 里自己给 form（加桥段或第三段副歌）。
DEFAULT_FORM = [["前奏", 4], ["主歌1", 8], ["预副1", 4], ["副歌1", 8],
                ["间奏", 2], ["主歌2", 8], ["预副2", 4], ["副歌2", 8],
                ["尾奏", 2]]


@dataclass
class SongProject:
    slug: str
    title: str
    lyrics: Path
    svp: Path
    bpm: float
    form: list[tuple[str, int]]
    mid: Path
    wav: Path
    flp: Path | None = None
    notes: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def n_bars(self) -> int:
        return sum(b for _n, b in self.form)

    @property
    def backup_dir(self) -> Path:
        return self.svp.parent / "_backup"

    @property
    def agent_dir(self) -> Path:
        """agent 自己的账本与 checkpoint。**不进 git**，也不是真相来源 ——
        删掉它只会丢掉「上次是我写的」这条出处记录，六步状态照样算得出来。
        """
        return SONGS / self.slug / ".agent"

    @property
    def stop_file(self) -> Path:
        """建这个文件 = 让 agent 在下一个动作之前停下。"""
        return self.agent_dir / ".stop"

    @property
    def acc_flp(self) -> Path:
        """agent 生成的 FL 工程。**跟 `mid` 一样是派生物，不是创作者的原件。**

        `self.flp` 是创作者手挂音源、手编排的那份，是**模板与素材来源**；
        这一份是拿它当模板拼出来的产物。两者分开，是因为覆盖 `flp`
        等于把他一小时的配器与编排冲掉 —— 就算快照能取回文件，
        他也得重新听一遍才知道丢了什么。
        """
        return self.mid.with_suffix(".flp")

    @property
    def sources(self) -> list[Path]:
        """状态由这些文件决定 —— 任何一个变了，观察结果就可能变。

        **放在这里，不放在仪表盘里。** 将来多一个来源（比如 checkpoint 目录），
        监视器要自动跟上；写死在前端的列表迟早漏一个，
        表现就是「文件改了但页面不动」，而且不报错。
        """
        out = [config_path(self.slug), TEMPLATE, self.lyrics,
               self.svp, self.mid, self.wav, self.acc_flp]
        # FL 工程也进来（配置里给了 flp 才有）。**创作者会随时改 FL**
        # （事实 F16），而那一侧我们看不见过程，只能看到导出的 wav 变了。
        # 把 FLP 纳入快照，他的编曲工作才能被回滚 —— 否则一小时的配器
        # 在会话树上一点痕迹都没有。
        if self.flp:
            out.append(self.flp)
        return out

    @property
    def duration_s(self) -> float:
        return self.n_bars * 4 * 60.0 / self.bpm

    def describe(self) -> str:
        d = self.duration_s
        return (f"{self.slug}｜{self.title}　{self.bpm:.0f} BPM · "
                f"{self.n_bars} 小节 · {int(d//60)}:{int(d%60):02d}\n"
                f"    歌词 {self.lyrics}\n"
                f"    工程 {self.svp}\n"
                f"    伴奏 {self.mid.name} / {self.wav.name}")


def config_path(slug: str) -> Path:
    return SONGS / slug / "project.json"


def load(slug: str) -> SongProject:
    p = config_path(slug)
    if not p.exists():
        avail = sorted(d.name for d in SONGS.iterdir()
                       if d.is_dir() and (d / "project.json").exists())
        raise SystemExit(
            f"找不到 {p}\n现有的歌：{avail or '（一首都没有）'}\n"
            f"新建一首：svagent.project.scaffold('<slug>', '<标题>', '<svp路径>')")
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    base = p.parent
    svp = Path(d["svp"])
    return SongProject(
        slug=slug,
        title=d.get("title", slug),
        lyrics=Path(d.get("lyrics") or (base / "lyrics.txt")),
        svp=svp,
        bpm=float(d.get("bpm", 66.0)),
        form=[(n, int(b)) for n, b in (d.get("form") or DEFAULT_FORM)],
        mid=Path(d["mid"]) if d.get("mid")
        else svp.with_name(svp.stem + "_伴奏.mid"),
        wav=Path(d["wav"]) if d.get("wav")
        else svp.with_name(svp.stem + "_伴奏.wav"),
        flp=Path(d["flp"]) if d.get("flp") else None,
        notes=d.get("notes", ""),
        raw=d,
    )


def current() -> SongProject:
    """当前项目。由环境变量 `SVAGENT_SONG` 决定，否则取**最近改动的那一首**。

    原来是「按字母序取最后一个」。第二首歌一建出来，
    默认项目就从 `xiaofeng` 静默变成了 `zhuimeng` —— 四个测试当场挂掉，
    而如果没有测试，表现会是「创作者跑 `sv state` 看到的是另一首歌」。

    **按字母序排是个任意规则，按最近改动排才对应「我正在做哪一首」。**
    这个洞只有第二首歌出现时才会露头。
    """
    slug = os.environ.get("SVAGENT_SONG")
    if not slug:
        cands = [(d / "project.json") for d in SONGS.iterdir()
                 if d.is_dir() and (d / "project.json").exists()]
        if not cands:
            raise SystemExit("songs/ 下没有任何 project.json")
        slug = max(cands, key=lambda p: p.stat().st_mtime).parent.name
    return load(slug)


def scaffold(slug: str, title: str, svp: str, *, bpm: float = 66.0,
             form: list | None = None, notes: str = "") -> Path:
    """新建一首歌的配置目录。**不创建 svp** —— 那是创作者在 SynthV 里建的。"""
    d = SONGS / slug
    d.mkdir(parents=True, exist_ok=True)
    cfg = {
        "title": title,
        "svp": str(Path(svp)),
        "bpm": bpm,
        "form": form or DEFAULT_FORM,
        "notes": notes,
    }
    p = d / "project.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    ly = d / "lyrics.txt"
    if not ly.exists():
        # 带 BOM + CRLF，否则中文 Windows 的记事本会乱码（实测踩过）
        with open(ly, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(f"# {title}\n\n（歌词待写）\n")
    return p


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("songs/ 下的项目：")
    for dd in sorted(SONGS.iterdir()):
        if dd.is_dir() and (dd / "project.json").exists():
            print("  " + load(dd.name).describe().replace("\n", "\n  "))
    print(f"\n当前（SVAGENT_SONG={os.environ.get('SVAGENT_SONG') or '未设置'}）：")
    print("  " + current().describe().replace("\n", "\n  "))


# =========================================================================
# 开一首新歌
#
# 为什么不做成动作池里的一个动作 —— `Runner(self.proj)` 把每个动作都绑在
# **一首已存在的歌**上。「新建」不属于任何一首歌，硬塞进去是把非本歌的
# 操作塞进本歌的框里，回滚、钩子、幂等报告全都对不上。
# =========================================================================

def slugify(title: str) -> str:
    """中文标题 → ASCII 目录名。

    走拼音（`pypinyin`，事实：本机 0.55.0）。装不上就退回一串十六进制 ——
    **退回来的名字难看，但不会静默生成一个和别人重名的目录**。
    """
    try:
        from pypinyin import lazy_pinyin
        s = "".join(lazy_pinyin(title))
    except Exception:
        import hashlib
        s = "song" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:6]
    s = "".join(c for c in s.lower() if c.isalnum())
    return s[:24] or "song"


def new_song(title: str, *, theme: str = "", bpm: float | None = None,
             slug: str | None = None, form: list | None = None,
             svp: str | Path | None = None, rng=None) -> SongProject:
    """开一首新歌。→ 建好的 `SongProject`。

    **撞名直接拒绝，不追加序号。** 悄悄建成 `haifeng2` 的话，
    之后 `SVAGENT_SONG=haifeng` 会跑到旧的那首上，而且哪儿都不报错。

    `bpm` 留空就按真歌分布取一个（`reference.pick_bpm`）——
    **不写死一个默认值**：每首新歌同一个速度，是「怎么一直是那几首歌的
    感觉」的来源之一。

    `.svp` 这里不建，第 ③ 步 `step3_melody` 会从模板整份写出来
    （`Builder.save(force=True)`）。创作者**不需要**先去 SynthV 建工程。
    """
    from . import reference as RF

    title = (title or "").strip()
    if not title:
        raise ValueError("歌名不能是空的")
    slug = (slug or slugify(title)).strip()
    if not slug.isascii() or not slug.replace("_", "").isalnum():
        raise ValueError(f"目录名 {slug!r} 只能是 ASCII 字母数字和下划线")

    d = SONGS / slug
    if (d / "project.json").exists():
        raise FileExistsError(
            f"已经有一首叫 {slug!r} 的歌了（{load(slug).title}）。"
            "换个名字，或者直接改那一首。")

    if bpm is None:
        bpm = RF.pick_bpm(rng)
    bpm = float(bpm)
    if not 40.0 <= bpm <= 200.0:
        raise ValueError(f"BPM {bpm} 不在 40–200 之间")

    svp = Path(svp) if svp else (d / f"{title}.svp")
    scaffold(slug, title, str(svp), bpm=bpm, form=form, notes=theme)
    p = load(slug)
    # **一出生就是完整的。** 少这一步的话，第一次点 gen_melody 会崩在
    # 「读旧工程」那行，报一句 `[Errno 2]` —— 而这是新歌的必经之路。
    ensure_svp(p)
    # FL 那边同理：没有 flp 字段，第 ④ 步 build_flp 会停在
    # 「需要一份已经挂好音源的工程当模板」。模板是共用的，接上就行。
    ensure_flp(p)
    return load(slug)


def ensure_svp(proj: "SongProject") -> str | None:
    """`.svp` 不在就从模板拷一份空工程出来。→ 干了什么，或者 `None`（本来就有）。

    ## 为什么需要这个

    `scaffold()` 的文档说「svp 由创作者在 SynthV 里建」。**那句话过期了** ——
    现在第 ③ 步会从模板整份写出来。但中间有个坑：`_a_gen_melody` 在调 step3
    **之前**先读一遍旧工程（为了报「改了哪几个音」），文件不在就
    `FileNotFoundError`，而它只 `except ToolError`。

    结果是「新歌第一次做旋律」这个最正常的情况直接崩，
    报错还是个裸异常，创作者只能看到一句 `[Errno 2]`。

    ## 为什么是拷模板，不是新写一个

    `.svp` 是 SynthV 的工程格式，版本敏感。模板
    （`songs/_template/empty_v196.svp`，1 轨 0 音符）是**从真 SynthV 里存出来的**，
    照抄一定能打开；自己拼一个 JSON 只能赌它认。

    ## 它不覆盖

    已经有文件就一个字节都不碰，直接返回 `None`。
    创作者可能正开着 SynthV 编辑它 —— 这条是硬的。
    """
    import shutil
    if proj.svp.exists():
        return None
    if not TEMPLATE.exists():
        raise FileNotFoundError(
            f"模板不在：{TEMPLATE}。它是从真 SynthV 存出来的空工程，"
            "丢了得重新存一份，不能自己拼。")
    proj.svp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE, proj.svp)
    return (f"从模板建了空工程 {proj.svp.name}"
            f"（{TEMPLATE.name}，{proj.svp.stat().st_size} B，1 轨 0 音符）")


def default_flp() -> Path | None:
    """已有歌里用得最多、且真实存在的那份 FL 模板。→ 没有就 `None`。

    ## 为什么是「从已有歌里推」而不是写死一个路径

    那份模板是创作者自己挂的（本机在 `E:\潮声回响\test2\test2.flp`，
    5 条通道：Harmo Pad / Acoustic Bass / Crystal / Choir Aahs / FPC）。
    把它写进库里，等于把**一台机器的目录布局**钉进代码 ——
    他换个位置就得改代码，而他不写代码。

    从「已经在用的值」里推，换位置只要改一首歌的 `project.json`，
    后面的新歌自动跟上。

    ## 为什么按「用得最多」选

    `追逐梦想` 指着另一份 `Project_test1.flp`（早期的）。按出现次数选，
    自然收敛到当前在用的那份，而不是看 `songs/` 的字母序碰上谁。
    """
    from collections import Counter
    votes: Counter[str] = Counter()
    for d in sorted(SONGS.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        cfg = d / "project.json"
        if not cfg.exists():
            continue
        try:
            v = json.loads(cfg.read_text(encoding="utf-8")).get("flp")
        except Exception:
            continue
        if v and Path(v).exists():
            votes[str(v)] += 1
    return Path(votes.most_common(1)[0][0]) if votes else None


def ensure_flp(proj: "SongProject") -> str | None:
    """`flp` 字段是空的就填上共用模板。→ 干了什么，或者 `None`。

    ## 这里「建」的是什么，说清楚免得误会

    `proj.flp` 是**素材来源**：一份已经挂好音源的 FL 工程。
    `proj.acc_flp`（`<歌名>_伴奏.flp`）才是**产物**，由 `build_flp` 拼出来。

    音源块只能从装过那个插件的工程里搬，**凭空造不出来** ——
    所以这里不是「生成一个空 flp」，是「把新歌接到那份挂好音源的模板上」。
    真正凭空建的是 `.svp`（见 [ensure_svp]），因为 SynthV 的空工程能照抄模板。

    ## 它不改已经填了的

    创作者可能故意给某首歌换了模板。填过就不动。
    """
    if proj.flp:
        return None
    tmpl = default_flp()
    if tmpl is None:
        return None                      # 没有可推的 —— 交给 build_flp 去报
    cfg = config_path(proj.slug)
    d = json.loads(cfg.read_text(encoding="utf-8"))
    d["flp"] = str(tmpl)
    cfg.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    proj.flp = tmpl
    return f"FL 模板接到 {tmpl}（{len(_flp_channels(tmpl))} 条通道已挂音源）"


def _flp_channels(p: Path) -> list:
    """模板里有哪几条通道。只为报告用，读不了就算了。"""
    try:
        from . import flp as FL
        return FL.instruments(FL.Doc(*FL.parse(p.read_bytes())))
    except Exception:
        return []
