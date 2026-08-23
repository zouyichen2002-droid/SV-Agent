"""配置载入。素材/模型路径一律来自配置，代码里不出现具体路径。

查找顺序：$SVCHAIN_CONFIG → <repo>/config.local.toml → <repo>/config.example.toml
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    pass


def _locate() -> Path:
    env = os.environ.get("SVCHAIN_CONFIG")
    if env:
        p = Path(env)
        if not p.is_file():
            raise ConfigError(f"$SVCHAIN_CONFIG 指向的文件不存在: {p}")
        return p
    for name in ("config.local.toml", "config.example.toml"):
        p = REPO_ROOT / name
        if p.is_file():
            return p
    raise ConfigError(f"找不到配置文件，在 {REPO_ROOT} 下放一个 config.local.toml")


@dataclass(frozen=True)
class Song:
    id: str
    title: str
    bpm: float
    first_beat_s: float
    vocals: Path
    no_vocals: Path
    lyrics: Path
    project: Path | None
    lyrics_skip_before_s: float
    harmony_window_s: tuple[float, float] | None

    def require(self, *fields: str) -> None:
        """用到某个素材前先检查它在这台机器上真的存在，别等到半路才炸。"""
        for f in fields:
            p = getattr(self, f)
            if p is None or not Path(p).exists():
                raise ConfigError(f"曲目 {self.id} 的 {f} 不存在: {p}")


@dataclass(frozen=True)
class PitchCfg:
    sr: int
    hop_s: float
    fmin_hz: float
    fmax_hz: float
    agree_cents: float
    conf_gate: float = 0.2
    min_agree: int = 2
    required: tuple[str, ...] = ()

    @property
    def hop_len(self) -> int:
        n = round(self.sr * self.hop_s)
        if abs(n - self.sr * self.hop_s) > 1e-9:
            raise ConfigError(f"hop_s={self.hop_s} 在 sr={self.sr} 下不是整数样本")
        return n


@dataclass(frozen=True)
class AlignCfg:
    act_rms_db_min: float = -23.0
    act_ratio_db_min: float = 2.0
    act_close_s: float = 0.25
    act_open_s: float = 0.08
    max_shift_s: float = 0.60
    prior_w: float = 0.10
    margin_s: float = 0.40
    decisive_plateau_s: float = 0.30


@dataclass(frozen=True)
class Config:
    source: Path
    models_dir: Path
    cache_dir: Path
    reports_dir: Path
    model_paths: dict[str, Path]
    songs: dict[str, Song]
    pitch: PitchCfg
    align: AlignCfg
    gates: dict[str, dict]

    def gate(self, stage: str) -> dict:
        if stage not in self.gates:
            raise ConfigError(f"配置里没有 {stage!r} 的门槛，有的是 {sorted(self.gates)}")
        return self.gates[stage]

    def song(self, song_id: str) -> Song:
        if song_id not in self.songs:
            raise ConfigError(f"配置里没有曲目 {song_id!r}，有的是 {sorted(self.songs)}")
        return self.songs[song_id]

    def model(self, key: str) -> Path:
        if key not in self.model_paths:
            raise ConfigError(f"配置里没有模型 {key!r}，有的是 {sorted(self.model_paths)}")
        return self.model_paths[key]


def load(path: str | os.PathLike[str] | None = None) -> Config:
    src = Path(path) if path else _locate()
    with src.open("rb") as f:
        raw = tomllib.load(f)

    paths = raw.get("paths", {})
    models_dir = Path(paths.get("models", REPO_ROOT / "models"))
    cache_dir = Path(paths.get("cache", REPO_ROOT / ".cache"))
    reports_dir = Path(paths.get("reports", REPO_ROOT / "eval" / "reports"))

    model_paths = {k: models_dir / v for k, v in raw.get("models", {}).items()}

    songs: dict[str, Song] = {}
    for s in raw.get("songs", []):
        hw = s.get("harmony_window_s")
        songs[s["id"]] = Song(
            id=s["id"],
            title=s.get("title", s["id"]),
            bpm=float(s["bpm"]),
            first_beat_s=float(s.get("first_beat_s", 0.0)),
            vocals=Path(s["vocals"]),
            no_vocals=Path(s["no_vocals"]),
            lyrics=Path(s["lyrics"]),
            project=Path(s["project"]) if s.get("project") else None,
            lyrics_skip_before_s=float(s.get("lyrics_skip_before_s", 0.0)),
            harmony_window_s=(float(hw[0]), float(hw[1])) if hw else None,
        )

    p = raw.get("pitch", {})
    pitch = PitchCfg(
        sr=int(p.get("sr", 16000)),
        hop_s=float(p.get("hop_s", 0.010)),
        fmin_hz=float(p.get("fmin_hz", 70.0)),
        fmax_hz=float(p.get("fmax_hz", 900.0)),
        agree_cents=float(p.get("agree_cents", 50.0)),
        conf_gate=float(p.get("conf_gate", 0.2)),
        min_agree=int(p.get("min_agree", 2)),
        required=tuple(p.get("required", ())),
    )
    a = raw.get("align", {})
    align = AlignCfg(**{k: v for k, v in a.items()
                        if k in AlignCfg.__dataclass_fields__})
    gates = {k: dict(v) for k, v in raw.get("gates", {}).items()}
    return Config(src, models_dir, cache_dir, reports_dir, model_paths, songs,
                  pitch, align, gates)
