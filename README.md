# SV-Agent

个人虚拟歌手创作助手（Synthesizer V + FL Studio）。只为一件事：**让作者更好、更快地出歌**。

现在先做**翻唱**：作者在 Suno 上用歌词生成歌、分好轨，系统把分轨变成 SynthV / FL 里能接着做的工程，作者在里面完成。
创作（从零写歌）排在翻唱完全做通之后。

> 这是 v2（2026-09 清空重写）。v1 的代码在标签 `v1-archive`。需求见 [PRD.md](PRD.md)。

## 第一个成果：Suno 人声分轨 → SynthV 主旋律（带歌词）

```
Suno 人声分轨
   │  Vocal2Midi：GAME 切音 + Qwen3-ASR 听写歌词
   ▼
扒出的音符 + 听写的歌词
   │  按作者给的歌词修歌词：按拼音全局对齐，处理字数和音数对不上（只改字，不动音）
   ▼
   │  挑八度：Suno 上下两个八度一起唱的句子，整句取上面那个
   ▼
新的 .svp（不碰作者自己的工程）→ 作者手改剩下的少数几个音
```

**演示：[demo/傍晚](demo/傍晚)** —— 作者版和 AI 版工程都在（CC BY-NC 4.0）。作者对着自己的版本听过：**基本可用，剩下少数几个音手改**。

都在《傍晚》上、对作者版打分（起音差 ≤ 50 ms 且音高差 ≤ 50 音分算扒对）：

| 做法 | 音符 F1 | 歌词 |
|---|---|---|
| basic-pitch 直接扒（含「有人声版 − 伴奏版」的做法） | 0.25–0.34 | 没有，或按顺序填、从头错位 |
| Vocal2Midi（GAME），只听写 | 0.573 | 94% |
| **+ 按作者歌词修歌词 + 挑八度（r05）** | 0.542 / **0.681**¹ | **185 / 185** |
| 参照：作者自己 04-12 第一版对 04-17 终稿 | 0.875 | —— |

¹ 1:56–2:14 作者把主唱放在下八度、上八度做成和声；按作者的和声算 0.681（八度错只剩 1 个），按主唱算 0.542。

**只测了一首歌**。几处分界线是在这首上定的，换歌要重新验。

### 做法上的几个要点

每一步都有自检（故意注入缺陷，必须测得出）和第二个裁判（不只拿作者版当答案，也拿人声分轨本身的音高去对质）。

- **切音是最难的**：通用扒谱模型会把一个字切碎、音偏短；专门扒人声的 [GAME](https://github.com/openvpi/GAME) 基本解决（起音 F1 0.50 → 0.78）
- **歌词**：翻唱时作者会给歌词 → 按拼音全局对齐（近似音、多音少字都处理）。**音准优先**：让模型按歌词重切音会把几个音弄差，所以只改字
- **八度**：Suno 常上下两个八度叠唱，GAME 每个音只能挑一个、会忽上忽下 → 录音里确认两个八度的句子整句取上面那个（高声部优势）。
  逐音挑、按前后接得顺挑、按响度挑都试过，和作者的判断对不上
- **和声识别不做**：这首的「和声」是八度叠唱；以后和声由我们自己写

## 怎么复现

探针代码在 [spikes/](spikes)，是一次性验证代码，**里面写死了本机路径**（`E:/sv-agent-data/…`），要改成你自己的。

| 要准备的 | 从哪来 |
|---|---|
| Vocal2Midi（提交 `839155c`） | [Xiantaidu/Vocal2Midi](https://github.com/Xiantaidu/Vocal2Midi)（Apache-2.0） |
| GAME-1.0.3-medium-onnx | [openvpi/GAME](https://github.com/openvpi/GAME/releases) 发布页（MIT） |
| 1218_hfa_model_new_dict | [wolfgitpr/HubertFA](https://github.com/wolfgitpr/HubertFA/releases) 发布页 |
| Qwen3-ASR-1.7B-DML | Hugging Face `xian-taidu/Qwen3-ASR-1.7B-DML` |
| llama.cpp 的 Windows DLL | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp/releases) **b9174**：Vocal2Midi 写死了结构体，只有 2026-01-08 到 05-11 之间的版本对得上 |
| basic-pitch | SynthVCopilot pi-agent 的 pi-audio 环境（Python 3.11；numpy 要钉 1.26.4） |
| Synthesizer V Studio 2 Pro + 声库 | 打开和渲染工程 |

```bash
# 1. 扒音符 + 听写歌词（vocal2midi 环境）
python spikes/m1-01-voice-to-midi/run_vocal2midi.py <人声分轨.wav> <输出目录> <名字> --asr
# 2. 按作者给的歌词修歌词（只改字）
python spikes/m1-03-lyrics/repair_lyrics.py <上一步的.mid> <版名> <上一步的.mid>
# 3. 挑八度，写成新的 .svp（要先存下 basic-pitch 的原样输出，见 spikes/m1-02-harmony/README.md）
python spikes/m1-02-harmony/pick_octave.py <上一步的音符.json> <版名>
```

《傍晚》这一版存成了基线：标签 `m1-melody-r05-baseline`，回归检查 `spikes/m1-02-harmony/regress_r05.py` 要求逐个音一模一样。

## 仓库里有什么

| 位置 | 是什么 |
|---|---|
| [PRD.md](PRD.md) | 产品需求（给作者本人看） |
| [docs/m0/](docs/m0) | 可行性验证记录（SynthV / FL 工程读写、钢琴试听、发布入口等） |
| [spikes/m1-01-voice-to-midi/](spikes/m1-01-voice-to-midi) | 扒谱：各种做法的对比、两个裁判、Vocal2Midi、一版一版写 SynthV 工程 |
| [spikes/m1-02-harmony/](spikes/m1-02-harmony) | 叠唱检测、挑八度、基线与回归检查 |
| [spikes/m1-03-lyrics/](spikes/m1-03-lyrics) | 按作者给的歌词修歌词 |
| [spikes/m2-01-local-llm/](spikes/m2-01-local-llm) | 本地大模型（Qwen3.8-27B）测速 |
| [demo/傍晚/](demo/傍晚) | 演示：作者版 + AI 版 |

## 许可

- 代码：Apache-2.0（[LICENSE](LICENSE)）
- [demo/傍晚/](demo/傍晚)：CC BY-NC 4.0（署名，不可商用）
- 第三方工具和模型各有各的许可，本仓库不再分发

## AI 参与说明

《傍晚》的原曲（旋律、编曲、原唱）由 Suno 根据作者的歌词生成；AI 扒谱用到 GAME、Qwen3-ASR、basic-pitch 等模型；
作者版由作者手工完成。本仓库的代码和文档在 AI 编程助手的协助下编写。
