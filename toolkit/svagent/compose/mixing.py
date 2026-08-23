"""混音：往 `.svp` 每条轨的 `mixer.fxParams` 写 EQ / 压缩 / 混响。

## 为什么在 SynthV 里做，而不是 FL

2026-08-23 实测：`.svp` 里**每条轨（包括音频轨）都自带一整套 FX 链**：

    postRoomEq   3 个峰值滤波器（freq / gain / q）+ 低切搁架（freq / gain）
    compressor   enabled / attack / ratio / threshold
    reverb       enabled / type / preDelay / decay / dryWetRatio
    room         enabled / positionX / positionY / size / reflectionGain

所以人声混音可以完全写进文件 —— 和写音符、写调教同一条路：
**文件进、文件出、可校验、可复现、一键撤销**（`enabled` 改回 false）。

FL 那条路要手动挂插件（FL API 不允许加载插件），而且桥断过。

## 两处单位不确定，故意不动

| 字段 | 模板默认 | 为什么不动 |
|---|---|---|
| `compressor.attack` | `0.0` | 不知道是毫秒还是秒。猜错会毁掉辅音起音 |
| `reverb.type` | `"clean"` | 不知道还有哪些合法枚举值 |

其余字段的单位能从模板默认值推出来（freq 是 Hz、gain 是 dB、q 无量纲、
preDelay/decay 是秒、dryWetRatio 是 0–1），可以放心改。

**宁可少改两个字段，也不要猜一个单位。**

## 三条轨的分工

    主旋律   低切去泥 + 3 kHz 提亮（吐字清晰）+ 轻压缩 + 少量混响
    和声     切得更狠 + 3 kHz **压低**（不与主唱抢清晰度）+ 更湿（坐后面）
    伴奏     只在人声泛音频段挖一个浅槽（让位），不动音频文件本身

伴奏那一项是最有效的一件事：人声在 MIDI 60–75，泛音主要落在 1–4 kHz，
所以在 3 kHz 挖 −2.5 dB 就能让人声浮出来，比推人声音量干净得多。
它只改 `.svp` 字段，音频文件一个字节不动。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EqBand:
    freq: float
    gain: float
    q: float = 0.71

    def to_dict(self) -> dict:
        return {"freq": float(self.freq), "gain": float(self.gain),
                "q": float(self.q)}


@dataclass
class TrackMix:
    """一条轨的混音设置。`None` 表示不启用该环节。"""
    gain_db: float = 0.0
    pan: float = 0.0
    eq: list[EqBand] | None = None
    low_shelf: EqBand | None = None
    comp_ratio: float | None = None
    comp_threshold_db: float | None = None
    rev_pre_delay_s: float | None = None
    rev_decay_s: float | None = None
    rev_wet: float | None = None

    def apply(self, mixer: dict) -> dict:
        """就地改一份 mixer 字典的副本并返回。**只碰要改的字段。**"""
        m = {k: (dict(v) if isinstance(v, dict) else v)
             for k, v in mixer.items()}
        m["gainDecibel"] = float(self.gain_db)
        m["pan"] = float(self.pan)
        fx = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in (m.get("fxParams") or {}).items()}

        if self.eq is not None or self.low_shelf is not None:
            eq = dict(fx.get("postRoomEq") or {})
            eq["enabled"] = True
            if self.eq is not None:
                cur = list(eq.get("filters") or [])
                # 模板固定 3 个频段，多给的忽略、少给的保留原值
                for i, band in enumerate(self.eq[:3]):
                    if i < len(cur):
                        cur[i] = band.to_dict()
                    else:
                        cur.append(band.to_dict())
                eq["filters"] = cur
            if self.low_shelf is not None:
                eq["lowShelf"] = {"freq": float(self.low_shelf.freq),
                                  "gain": float(self.low_shelf.gain)}
            fx["postRoomEq"] = eq

        if self.comp_ratio is not None or self.comp_threshold_db is not None:
            c = dict(fx.get("compressor") or {})
            c["enabled"] = True
            if self.comp_ratio is not None:
                c["ratio"] = float(self.comp_ratio)
            if self.comp_threshold_db is not None:
                c["threshold"] = float(self.comp_threshold_db)
            # attack 不动 —— 单位不确定，见模块 docstring
            fx["compressor"] = c

        if self.rev_wet is not None:
            r = dict(fx.get("reverb") or {})
            r["enabled"] = True
            if self.rev_pre_delay_s is not None:
                r["preDelay"] = float(self.rev_pre_delay_s)
            if self.rev_decay_s is not None:
                r["decay"] = float(self.rev_decay_s)
            r["dryWetRatio"] = float(self.rev_wet)
            # type 不动 —— 只知道 "clean" 合法
            fx["reverb"] = r

        m["fxParams"] = fx
        return m


def disable_all(mixer: dict) -> dict:
    """把这条轨的全部 FX 关掉，gain/pan 归零。用于一键撤销。"""
    m = {k: (dict(v) if isinstance(v, dict) else v) for k, v in mixer.items()}
    fx = {k: (dict(v) if isinstance(v, dict) else v)
          for k, v in (m.get("fxParams") or {}).items()}
    for k in ("postRoomEq", "compressor", "reverb", "room"):
        if k in fx:
            fx[k] = dict(fx[k], enabled=False)
    m["fxParams"] = fx
    return m


# ---------------------------------------------------------------- 预设
#
# 慢速小调抒情（本曲：晓风残月，66 BPM，G 小调，人声 MIDI 60–75）。
# 伴奏实测频段：低 51% / 中 49% / 高 0.1% —— 高频几乎是空的，
# 所以人声提亮不会和伴奏抢，反而是让人声浮出来最省力的方式。

def lead_ballad(gain_db: float = 0.0) -> TrackMix:
    """主唱：去泥 + 提清晰度 + 轻压缩 + 少量混响。"""
    return TrackMix(
        gain_db=gain_db, pan=0.0,
        # 人声最低基频 MIDI 60 = 262 Hz，切到 120 Hz 很安全
        low_shelf=EqBand(120.0, -8.0),
        eq=[EqBand(250.0, -2.5, 0.80),    # 挖泥
            EqBand(3000.0, 2.5, 0.90),    # 吐字清晰
            EqBand(9000.0, 1.5, 0.70)],   # 空气感（伴奏这一段是空的）
        comp_ratio=2.5, comp_threshold_db=-14.0,
        rev_pre_delay_s=0.030, rev_decay_s=2.0, rev_wet=0.16)


def harmony_behind(gain_db: float = -6.5) -> TrackMix:
    """和声：坐在主唱后面。切得更狠、清晰度让位、更湿。"""
    return TrackMix(
        gain_db=gain_db, pan=0.0,          # 只有一条和声轨，pan 偏了会不对称
        low_shelf=EqBand(150.0, -8.0),
        eq=[EqBand(400.0, -2.0, 0.80),
            EqBand(3000.0, -2.0, 0.90),    # **压低**，不与主唱抢吐字
            EqBand(8000.0, -1.0, 0.70)],
        comp_ratio=2.0, comp_threshold_db=-16.0,
        rev_pre_delay_s=0.040, rev_decay_s=2.4, rev_wet=0.30)


def accompaniment_carve(gain_db: float = -3.0) -> TrackMix:
    """伴奏：只在人声泛音频段挖一个浅槽让位。**不改音频文件。**"""
    return TrackMix(
        gain_db=gain_db, pan=0.0,
        eq=[EqBand(3000.0, -2.5, 1.20),    # 给人声让出清晰度
            EqBand(250.0, -1.0, 0.90),     # 略减与人声低频的重叠
            EqBand(60.0, 0.0, 0.70)],      # 不动
        rev_wet=None, comp_ratio=None)


def describe(name: str, mixer: dict) -> str:
    fx = mixer.get("fxParams") or {}
    bits = [f"gain {mixer.get('gainDecibel', 0):+.1f} dB",
            f"pan {mixer.get('pan', 0):+.2f}"]
    eq = fx.get("postRoomEq") or {}
    if eq.get("enabled"):
        ls = eq.get("lowShelf") or {}
        fs = [f"{f['freq']:.0f}Hz {f['gain']:+.1f}dB"
              for f in (eq.get("filters") or []) if abs(f.get("gain", 0)) > 0.01]
        bits.append("EQ[低切 " + f"{ls.get('freq', 0):.0f}Hz "
                    f"{ls.get('gain', 0):+.1f}dB" + ("｜" + "｜".join(fs)
                                                     if fs else "") + "]")
    c = fx.get("compressor") or {}
    if c.get("enabled"):
        bits.append(f"压缩 {c.get('ratio')}:1 @{c.get('threshold')}dB")
    r = fx.get("reverb") or {}
    if r.get("enabled"):
        bits.append(f"混响 {r.get('type')} 衰减{r.get('decay')}s "
                    f"湿{r.get('dryWetRatio')}")
    return f"  {name:<18} " + "　".join(bits)
