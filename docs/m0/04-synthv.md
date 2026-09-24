# M0-04 · SynthV：工程读写、脚本能力、导出

| | |
|---|---|
| 对应 | PRD §14「SynthV 工程、脚本或桥接能力 · 指定产品版本验证，记录写入与渲染限制」 |
| 日期 | 2026-09-24 |
| 版本 | **Synthesizer V Studio 2 Pro · 2.2.1** · `G:\Synthesizer V Studio 2 Pro\synthv-studio.exe` |
| 状态 | **进行中。** 查资料的部分已完成；「我们写的 `.svp` SynthV 认不认」**等你在 SynthV 里实测** |
| 代码 | `spikes/m0-04-svp/`（探针，不进产品） |

---

## 1. 已确认：人声导出只能你手点

```
               能不能打开工程   能不能保存   能不能导出音频
  FL 命令行    ✓               ——          ✓        （M0-03）
  SynthV 脚本  ✗               ✗           ✗        ← 官方脚本手册一手确认
  SynthV 界面  ✓               ✓           ✓        只能手点「Bounce to Files」
```

**依据（一手）**：官方脚本手册 <https://resource.dreamtonics.com/scripting/>

- `Project` 类一共 21 个方法，没有保存、打开、渲染、导出；唯一和文件有关的是 `getFileName()`（读当前路径）
- 宿主对象 `SV` 的全部方法里，也没有打开、保存、渲染、导出

**依据（官方用户手册「Render and Export」页）**：导出是在渲染面板里点 **Bounce to Files**；
可选单轨或混音、单声道（默认）或立体声、位深（默认 16）、采样率（默认 44100）。
**没有提到命令行、批量或脚本导出。**

**旁证**：上游桥 0.3.1 的覆盖文档把 *「project save and audio render/export」* 列为官方接口缺失的能力。

**所以这是一处真实存在、绕不过去的人工步骤。** 能做的是把它压到最小 —— 见第 2 节。

---

## 2. 导出设置存在工程文件里 → 你那一下可以只剩一下

SynthV 的 `.svp` 顶层有一个 `renderConfig`：

| 字段 | 默认值 |
|---|---|
| `destination` | 空（输出文件夹） |
| `filename` | 「未命名」 |
| `numChannels` · `bitDepth` · `sampleRate` | 1 · 16 · 44100 |
| `exportMixDown` | 是 |

**如果 SynthV 打开工程时会带上这些设置**，我们生成工程时就能预先填好输出位置和文件名：
你点「Bounce to Files」，文件落在我等着的地方，后面的流程能自动接上。**这一点待实测**（第 4 节）。

---

## 3. `.svp` 的结构（读的是 SynthV 自己存的文件）

来源：你的 SynthV 恢复文件（`%APPDATA%\Dreamtonics\Synthesizer V Studio 2\recovery\`，共 17 个）
和 v1-archive 里那个 SynthV 亲手存的空工程。**只看了结构，没读你工程里的歌词。**

| 项 | 结果 |
|---|---|
| 格式 | 纯 JSON（SV1 的文件末尾有个 NUL 字节，SV2 没有） |
| `version` | **196**（空模板和你最近的工程一致） |
| 顶层 | `version` · `uuid` · `time` · `library` · `tracks` · `renderConfig` · `projectMixer` |
| 速度 | `time.tempo = [{position, bpm}]` —— 比 FL 直白得多，直接是 BPM |
| 时间单位 | blick：1 个四分音符 = 705,600,000 blick。音符的起点和时值都是整数 |
| 音符字段 | 11 个；366 个真音符的默认值完全一致（`singing` · 空重音 · `{evenSyllableDuration: true, muted: false}` · 同一个 takes） |
| 主音符组范围 | `blickAbsoluteEnd = -1`（不设上限，音符不会被截） |

---

## 4. 待实测：我们写的 `.svp`，SynthV 认不认

SynthV 的脚本打不开文件，但能读**当前打开的工程**；上游桥又证明了 SynthV 里的 Lua 能读写文件。所以：

```
  make_test_svp.py ──► m0_04.svp + spec.json（标准答案）
                           │
              你在 SynthV 里打开它，运行「SV-Agent 导出现状」
                           ▼
                  m0_04.svp.dump.json（SynthV 眼里的工程）
                           │
  compare.py ──► 速度、拍号、每个音的起点 / 时值 / 音高 / 歌词，全部精确相等才算绿
```

测试乐谱：**97.5 BPM** · 4/4 · 8 个音 · 歌词「今天的风很温柔啊」· 声库 MEDIUM5·Stardust · 音乐长 7.385 秒。

比对程序已经自检过：一模一样判 0 处不一致；改坏 3 处（速度、一个字、一个音的起点差 1 blick）恰好报出 3 处。

**结果：待填。**

---

## 5. 附带发现（和 V2 有关）

SynthV 安装目录里有 **`audio2score.dnni`**：SynthV 自带的「音频转乐谱」模型。
你之前说过 SynthV 自带的扒谱比 AI 的准 —— V2 做翻唱转写时，它是一个要认真比较的候选。
