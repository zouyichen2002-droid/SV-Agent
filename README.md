# SV-Agent

个人虚拟歌手创作助手（Synthesizer V + FL Studio）。只为一件事：**让作者更好、更快地出歌**。

## 现在到哪了（2026-10-01）

- **翻唱链路走通（M1）**：一首歌（Suno 分轨，或只有整首音频）→ SynthV 工程：主旋律带歌词、对好拍子，伴奏和原曲主唱放在工程里当参考。
  在 5 首歌上走通，作者的评价：「这个翻唱就做完了，基本达到了只需要创作者稍微改动就能发布的程度，甚至某些情况（比如《逃跑的天使》）可以直接发布」。
  详见 [docs/m1/station-end.md](docs/m1/station-end.md)
- **方向（v3）**：从翻唱 / 创作助手往**个人创作工作台**长 —— 作品管理、个人偏好、创作口味、喜爱作品、逆向学习记忆、Skill 接入、GUI 操作、教学……
  以 [DeepSeek Harness（DSH）](https://github.com/deepseek-ai/deepseek-harness) 当 Agent 底座，先原样用、再一步步改，我们只写创作领域的插件；第一个 Skill 就是上面的翻唱链路。
  模型本地为主（llama.cpp + Qwen3.8-27B），上下文不够时用 DeepSeek 的接口
- **阶段 0 完**：DSH 在本机原样跑通（本地模型、专用工作区、沙箱、审批），也弄清楚了它怎么搭起来的 —— 见 [docs/v3/s0-dsh.md](docs/v3/s0-dsh.md)。下一步是阶段 1：Project 插件

> 这是 v2（2026-09 清空重写）。v1 的代码在标签 `v1-archive`；第一个发布在标签 `v0.1.0`（那时只有《傍晚》一首）。需求见 [PRD.md](PRD.md)。

## 翻唱：一首歌怎么走

```
歌：Suno 分轨，或只有整首音频（B 站 / 本地文件）
   │  分离：audio-separator —— Mel-Roformer 分人声 / 伴奏 → karaoke 模型拆主唱 / 叠唱；主唱缺的段用整条人声补
   ▼
主唱
   │  扒谱：Vocal2Midi —— GAME 切音 + Qwen3-ASR 听写歌词；basic-pitch 多声部当挑八度的第二个裁判
   ▼
扒出的音符 + 听写的歌词
   │  修歌词：用作者给的歌词，按拼音全局对齐，只改字、不动音；和听写对不上的整行不放
   │  挑八度：两个八度一起唱的整句取上面那个
   │  作者定的规矩：句首字跑到上一句末尾 → 还回去；长音截两段、后一段写韵母；念唱 → 整句一个音，作者自己调
   ▼
   │  找拍子：整首量速度 → 分段 → 每段找「1」→ 小节线 → 速度表（自由前奏 / 尾声不上网格）→ 吸格线
   ▼
新的 .svp（不碰作者自己的工程）→ 作者听、改剩下的少数地方
```

一首约 30 分钟机器时间（分离在 CPU 上约 25 分钟，最慢），基本不用人看着；现在还要按顺序跑 9 步，没串成一条命令。

### 五首歌

| 曲 | 来源 | 拍子 | 结果 | 作者的评价 |
|---|---|---|---|---|
| 《傍晚》（作者自己的歌） | Suno 分轨 | 131.98 BPM，尾声自由 | 歌词 185 字全对上；打分见下表 | 「这首歌通过了」 |
| 《潮声回响》 | B 站整首 | 分段变速 82.02 → 86.00 → 81.97 | 拆出主唱后，同一句里跳过去又跳回来的 4 处 → 0 | 「扒谱听感还可以 … 比SV的扒谱好太多了」 |
| 《刽子手》 | B 站 | 130 BPM | 作者改第 2 版：317 个音里 249 个没动；之后照作者改的定了三条规矩 | 「可以了」 |
| 《逃跑的天使》 | B 站 | 125 BPM | 583 字放上 579 | 「效果非常好 … 基本能100%正确识别了」 |
| 《天星问》 | 拜年纪 | 77 BPM | 古文听写只有 75%，464 字全放上 | 「可以」 |

**后 4 首是别人的作品：音频、歌词、工程都只在本地用来测试，不进仓库。**

### 《傍晚》上的打分

**演示：[demo/傍晚](demo/傍晚)** —— 作者版和 AI 版工程都在（CC BY-NC 4.0）。对作者终稿打分（起音差 ≤ 50 ms 且音高差 ≤ 50 音分算扒对）：

| 做法 | 音符 F1 | 歌词 |
|---|---|---|
| basic-pitch 直接扒（含「有人声版 − 伴奏版」的做法） | 0.25–0.34 | 没有，或按顺序填、从头错位 |
| Vocal2Midi（GAME），只听写 | 0.573 | 94% |
| **+ 按作者歌词修歌词 + 挑八度（r05）** | 0.542 / **0.681**¹ | **185 / 185** |
| 参照：作者自己 04-12 第一版对 04-17 终稿 | 0.875 | —— |

¹ 1:56–2:14 作者把主唱放在下八度、上八度做成和声；按作者的和声算 0.681（八度错只剩 1 个），按主唱算 0.542。

只有这一首有作者终稿当标准答案；另外 4 首靠作者听和改。

### 做法上的几个要点

每一步都有自检（故意注入缺陷，必须测得出）和第二个裁判（不只拿作者版当答案，也拿录音本身去对质）。

- **切音是最难的**：通用扒谱模型会把一个字切碎、音偏短；专门扒人声的 [GAME](https://github.com/openvpi/GAME) 基本解决（起音 F1 0.50 → 0.78）
- **歌词**：翻唱时作者会给歌词 → 按拼音全局对齐（近似音、多音少字都处理）。**音准优先**：只改字；主唱没唱的句子宁可不放，也不硬塞
- **八度**：Suno 常上下两个八度叠唱，GAME 每个音只能挑一个、会忽上忽下 → 录音里确认两个八度的句子整句取上面那个
- **规矩从作者改的版本学，不凭空造音**：每条规矩都有作者改过的地方当依据，上线前拿别的歌（尤其《傍晚》终稿）当第二个裁判，不能改坏
- **拍子从音频量，不信显示的数**：Suno 显示的速度、SynthV 存的速度都只当候选，两个裁判对上才算
- **不做的**：和声识别（以后和声由我们自己写）、乐器 MIDI（伴奏用分出来的）

## 怎么复现

探针代码在 [spikes/](spikes)，是一次性验证代码，**里面写死了本机路径**（`E:/sv-agent-data/…`），要改成你自己的。
跑一首要按顺序跑的 9 步命令见 [docs/m1/station-end.md](docs/m1/station-end.md) §1。

| 要准备的 | 从哪来 |
|---|---|
| Vocal2Midi（提交 `839155c`） | [Xiantaidu/Vocal2Midi](https://github.com/Xiantaidu/Vocal2Midi)（Apache-2.0） |
| GAME-1.0.3-medium-onnx | [openvpi/GAME](https://github.com/openvpi/GAME/releases) 发布页（MIT） |
| 1218_hfa_model_new_dict | [wolfgitpr/HubertFA](https://github.com/wolfgitpr/HubertFA/releases) 发布页 |
| Qwen3-ASR-1.7B-DML | Hugging Face `xian-taidu/Qwen3-ASR-1.7B-DML` |
| llama.cpp 的 Windows DLL | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp/releases) **b9174**：Vocal2Midi 写死了结构体，只有 2026-01-08 到 05-11 之间的版本对得上 |
| audio-separator + 两个分离模型 | [karaokenerds/python-audio-separator](https://github.com/karaokenerds/python-audio-separator)（MIT，用的 0.47.0）；模型第一次用时自动下载（`vocals_mel_band_roformer.ckpt`、`mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`） |
| basic-pitch | SynthVCopilot pi-agent 的 pi-audio 环境（Python 3.11；numpy 要钉 1.26.4） |
| yt-dlp、ffmpeg | 只有整首音频的歌：下载（不登录、只下音频）和转 wav |
| Synthesizer V Studio 2 Pro + 声库 | 打开和渲染工程 |

《傍晚》存成了基线：标签 `m1-melody-r05-baseline`，回归检查 `spikes/m1-02-harmony/regress_r05.py` 要求逐个音一模一样。

v3 的平台（DSH）在本机怎么搭：补丁、启动脚本和换机器重搭的步骤在 [dsh/](dsh)，为什么这么搭见 [docs/v3/s0-dsh.md](docs/v3/s0-dsh.md)。

## 仓库里有什么

| 位置 | 是什么 |
|---|---|
| [PRD.md](PRD.md) | 产品需求（给作者本人看） |
| [docs/m0/](docs/m0) | 可行性验证记录（SynthV / FL 工程读写、钢琴试听、发布入口等） |
| [docs/m1/](docs/m1) | 翻唱链路的站末材料：五首歌、失败案例、成本 |
| [docs/v3/](docs/v3) | v3 各阶段的笔记（阶段 0：原样跑通 DSH） |
| [dsh/](dsh) | DSH 本机配置的副本 |
| [spikes/m1-01-voice-to-midi/](spikes/m1-01-voice-to-midi) | 扒谱：各种做法的对比、两个裁判、Vocal2Midi、分离、补段、作者定的规矩、一版一版写 SynthV 工程 |
| [spikes/m1-02-harmony/](spikes/m1-02-harmony) | 叠唱检测、挑八度、基线与回归检查 |
| [spikes/m1-03-lyrics/](spikes/m1-03-lyrics) | 按作者给的歌词修歌词 |
| [spikes/m5-00-beat-grid/](spikes/m5-00-beat-grid) | 找拍子：从音频量速度、分段、小节线、速度表 |
| [spikes/m2-01-local-llm/](spikes/m2-01-local-llm) | 本地大模型（Qwen3.8-27B）测速 |
| [demo/傍晚/](demo/傍晚) | 演示：作者版 + AI 版 |

## 许可

- 代码：Apache-2.0（[LICENSE](LICENSE)）
- [demo/傍晚/](demo/傍晚)：CC BY-NC 4.0（署名，不可商用）
- 第三方工具和模型（含 DSH）各有各的许可，本仓库不再分发

## AI 参与说明

《傍晚》的原曲（旋律、编曲、原唱）由 Suno 根据作者的歌词生成；AI 扒谱用到 GAME、Qwen3-ASR、basic-pitch 等模型，分离用到 audio-separator 的模型；
作者版由作者手工完成。本仓库的代码和文档在 AI 编程助手的协助下编写。
