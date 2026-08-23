# ADR-0009 — 直接生成 `.svp` 文件，不再靠桥装配工程

| | |
|---|---|
| 状态 | **已接受** |
| 日期 | 2026-08-23 |
| 决策者 | 用户从四个方案中选定「零手动交付：直写 .svp」；生成器选「先用我，流程通了再换 Mistral」 |
| 影响范围 | 交付形态。**不取代** SynthV 桥 —— 桥仍用于调教与回读校验 |

## 背景

《宇宙无边无垠》走通全链路后清点手动步骤，共 10 项
（见 [chain-and-manual-boundary.md](../chain-and-manual-boundary.md)）。
用户提出一个准确的判断：**「看起来这个更适合做 workflow，但我想做一个真正的全自动创作助手」**。

清点手动项时浮现出一条规律，它比清单本身重要：

> **唯一全自动的环节（伴奏 MIDI）是唯一一个输入输出都是文件的环节。**
> 凡是要读写宿主软件的运行时状态，都撞在 API 边界上。

## 关键发现：`.svp` 是纯 JSON

实测 14 个真实 `.svp`（`version 187`）：

    顶层           ['library', 'renderConfig', 'time', 'tracks', 'version']
    音符在          library[i].notes（不在 track 上）
    轨道引用组      tracks[i].groups[j].groupID → library[i].uuid
    **声库**        tracks[i].groups[j].database.name = "MEDIUM5·Stardust"
    **音频轨**      tracks[i].mainRef.isInstrumental = true
                    + mainRef.audio = {filename, duration, bpm,
                                       alternativeBPMs, beatLocations}
    音符字段        musicalType="singing" · onset/duration（blicks）
                    · lyrics · phonemes · accent · pitch · detune
                    · attributes{evenSyllableDuration, muted} · takes
    beatLocations   **单位是秒**，间距 60/bpm

## 拍板

**直接生成 `.svp`。** 一次性消除 SynthV 侧全部 4 项手动：

| 原手动项 | 怎么消除 |
|---|---|
| 新建工程 | 写文件本身就是新建 |
| 指派声库 | `groups[j].database.name` |
| 加音频轨放伴奏 | `mainRef.isInstrumental` + `mainRef.audio` |
| 保存 | 写文件本身就是保存 |

### 为什么先做交付管道，而不是先做生成能力

这是本 ADR 唯一需要论证的地方 —— 直觉会说「agent 的核心是生成」。

**理由是反馈回路的成本。** 现在用户要听到任何结果，得做约 6 步手工
（FL 导出 → 拖进 SV → 指派声库 → 保存 → 播放）。这个成本是后面
**所有**迭代的乘数：发散 10 个候选没有意义，因为他听不过来 10 次 6 步手工。

先把「双击一个文件就能听」做出来，后面每一次生成迭代都便宜。
**工具先于特性**：先降低反馈成本，再提高产出速度。

### 附带的结构性收益：FL 从必经环节降级为可选

我们本来就会合成伴奏预览音频（`make_accompaniment.py` 的正弦渲染）。
把它作为 `mainRef.audio` 写进 `.svp`，就得到一个**零手动步骤**的完整交付物。
音色不如 FL，但链路是通的。

于是 FL 变成**可选的音色升级路径**，而不是必经环节。
这同时把 FL 侧那 6 项手动从「阻塞主线」降级为「想要更好音色时才付的代价」。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 格式无官方文档 | 手上有 14 个真实 `.svp` 可反推；schema 已逐字段取证 |
| `version 187` 可能漂移 | 写入时记录版本号；打开失败就重新取证。**不猜字段** |
| ~~写出 SynthV 打不开的文件~~　**2026-08-23 已消解：用户实际打开成功** | 生成后**回读校验**：用桥读 SynthV 实际加载的音符，与源模块逐字段比对（沿用 `write_song.py` 的做法） |
| 覆盖用户已有工程 | 目标文件已存在时**拒绝写入**，除非显式 `--force` |

## 什么证据会推翻它

- SynthV 打不开生成的文件，且逐字段比对找不出差异（说明有未取证的必需字段）
- 版本升级后格式不兼容且无法反推
- 回读校验发现音符被静默改动（比打不开更糟）

## 不做什么

**不取代桥。** 桥仍然是唯一能做以下事的通道：调教（转音、参数曲线）、
读取 SynthV 的实际状态、回读校验。直写 `.svp` 解决的是**装配**，不是**编辑**。
