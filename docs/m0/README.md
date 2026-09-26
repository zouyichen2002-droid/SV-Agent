# M0 · 可行性与范围确认

PRD §15：M0 的产物是**验证记录、能力矩阵、V1 清单**；
退出条件是**预览有可行路径 · 工程风险有替代方案**。

## 进度

§14 列了七项必须验证的风险。按「哪一项不验会让整条链路白做」排序：

| 序 | §14 的哪一行 | 状态 | 记录 |
|---|---|---|---|
| **1** | 钢琴预览速度 | **绿** · gm.dls 定为预览音源（你 09-24 确认） | [01-piano-preview.md](01-piano-preview.md) |
| **2** | Python 与音频依赖 | **绿**（V1）· Python 3.13 + numpy 2.5.3；V2 的 CUDA torch 灰（强证据）、basic-pitch 红（原样） | [02-python-env.md](02-python-env.md) |
| **3** | FL 工程读写、tempo、渲染入口 | **绿** · 命令行导出可用；速度在事件 156（BPM × 1000）；**09-26 更正：原读取器读不对 FL 2025 存的工程，已修正并重测**；写音符进 `.flp` 仍是灰 | [03-fl-project.md](03-fl-project.md) |
| **4** | SynthV 工程、脚本或桥接能力 | **绿** · 写的 `.svp` 逐个精确一致、预填导出设置生效；**硬限制：人声导出只能你点一下**；SynthV 打开时会改结构（把音挪进音符库组） | [04-synthv.md](04-synthv.md) |
| 5 | 文件并发编辑 | 未开始 | —— |
| **6** | 所谓 512 音符限制 | **绿** · 是上游桥 0.3.1 自己的每次调用上限，不是 SynthV 的；直写 `.svp` 碰不到 | [06-note-limit.md](06-note-limit.md) |
| 7 | 首批平台发布入口 | 未开始 · **要你本人账号操作** | —— |

**退出条件的前一半（预览有可行路径）已满足。** 后一半（工程风险有替代方案）：FL、SynthV 都有了，还差第 5 项。

**灰 ≠ 绿**（PRD §8.3）：灰是「还没有可判断的依据」，不是「差不多没问题」。

## 本机环境事实（2026-09-24 实查）

| 项 | 值 | 和哪一项有关 |
|---|---|---|
| CPU / 内存 | AMD Ryzen 9 9955HX3D 16 核 · 31.2 GB | 全部 |
| 显卡 | NVIDIA GeForce RTX 5070 Ti Laptop GPU · 12 GB 显存 · 算力 12.0（sm_120，Blackwell）· 驱动 591.97，支持 CUDA 13.1（另有 AMD 核显） | V2 源分离、音高模型 |
| 系统 | Windows 11 家庭中文版 10.0.26200 | 全部 |
| 默认 `python` | 3.13.9 · `G:\miniconda` · 装有 numpy 2.3.4 / scipy 1.16.3 / librosa 1.0.0 / soundfile 0.14.0 / mido | M0-01 用的就是它 |
| **torch** | miniconda 里是 2.13.0 **+cpu**，用不上那块显卡。**同机 ComfyUI 自带的 Python 3.13.14 里是 2.13.0+cu130，在 sm_120 上实测可用** | 第 2 项 · V2 |
| 其他 Python | python.org 的 **3.13.7**（worker 环境的底座，自带 21 个包，含 numpy 2.2.6、scipy 1.16.2）· python.org 的 3.11.6 · uv 管理的 3.11.16 / 3.11.13 | 第 2 项 |
| uv · conda | 都在 `G:\miniconda\Scripts\`；uv 0.12.5。**uv 默认挑 miniconda 当底座，建环境必须显式指定**；缓存在 C 盘、项目在 E 盘，不能硬链接（只是慢一点） | 第 2 项 |
| Node | v24.19.0 · npm 11.17.0。`pnpm` 不在 PATH 上（但 `E:\.pnpm-store` 存在） | M1 起的 TS 主进程 |
| **FL Studio** | **2025 · 25.2.5.5319** · `G:\FL Studio\FL64.exe`（不在默认的 Program Files 下）· 自带 34 个模板、161 个 `.flp` · 本机离线手册只是个壳 | 第 3 项 |
| **SynthV** | **Studio 2 Pro · 2.2.1** · `G:\Synthesizer V Studio 2 Pro\synthv-studio.exe` · 用户数据在 `%APPDATA%\Dreamtonics\Synthesizer V Studio 2`（脚本、恢复文件、缓存）· 工程格式 version 196 · 你常用的声库 MEDIUM5·Stardust | 第 4、5 项 |
| 上游桥 | SynthV Agent Bridge **0.3.1**：Lua 端已装进 SynthV 的脚本目录；仓库在 `E:\SV_MCP`（提交 `5c51bd9`，只读） | 第 4、6 项 |
| ffmpeg | 9.0 完整版（winget 装的） | 发布包转码 |
| FluidSynth / SoundFont | **都没有** | 第 1 项因此改走 gm.dls |
| gm.dls | `C:\Windows\System32\drivers\gm.dls` · 3,440,660 字节 · SHA-256 `3229B09B9D7D9F3F4793B0D9B34FE6ABC75CFA4A2503C0C90F43FF651BA7F2C0` | 第 1 项 |
| POP909 数据集 | `E:\潮声回响\POP909-Dataset-master\POP909-Dataset-master`（仓库外） | V2 校准库：阈值锚真歌 |

这张表是**实查的快照，不是保证**。装了新东西、换了机器，以当时再查的为准。
