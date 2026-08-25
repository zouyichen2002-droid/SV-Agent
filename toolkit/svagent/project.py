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
    def sources(self) -> list[Path]:
        """状态由这些文件决定 —— 任何一个变了，观察结果就可能变。

        **放在这里，不放在仪表盘里。** 将来多一个来源（比如 checkpoint 目录），
        监视器要自动跟上；写死在前端的列表迟早漏一个，
        表现就是「文件改了但页面不动」，而且不报错。
        """
        out = [config_path(self.slug), TEMPLATE, self.lyrics,
               self.svp, self.mid, self.wav]
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
