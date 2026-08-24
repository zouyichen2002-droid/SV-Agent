# SV-Agent 创作运行手册

**这份文档的用途：让一个全新的 Claude Code 会话能接着做歌。**
第一句话就把它贴给我，或者直接说「读 `E:\sv-bridge\HOWTO.md`，我要做新歌」。

第一轮完整走通的作品：《晓风残月》（`songs/xiaofeng`），
六步全过，对齐误差 −1.0 ms。设计理由见 [specs/workflow.md](specs/workflow.md)。

---

## 开一首新歌：三件事

### 1. 你做（约 2 分钟）

- 在 SynthV 里**新建一个空工程并保存**，比如 `E:\我的歌\yequ.svp`
- 告我：**题目 + 那个 svp 的路径**

### 2. 我做

建配置目录，之后所有命令都靠环境变量 `SVAGENT_SONG` 选歌：

```bash
python -c "import sys; sys.path.insert(0,r'E:\sv-bridge\toolkit'); from svagent import project; print(project.scaffold('yequ','夜曲',r'E:\我的歌\yequ.svp',bpm=66))"
```

**每首新歌只改 `songs/<slug>/project.json`，不改代码。** 里面是：

| 字段 | 说明 |
|---|---|
| `title` | 歌名 |
| `svp` | SynthV 工程的绝对路径（**你新建的那个**） |
| `bpm` | 48 小节时：62→3:06　66→2:54　70→2:45 |
| `form` | 曲式。默认 48 小节；超过 3:30 要加桥段或第三段副歌 |

`mid` / `wav` 不用填，默认跟着 `svp` 起名。

### 3. 结构模板只需要一次

`songs/_template/empty_v196.svp` 是你空工程的纯净副本，已经有了。
**只有 SynthV 大版本升级后才需要换**——那时重新建个空工程，复制过去。

---

## 随时看一眼：仪表盘

任何时候想知道「这首歌走到哪了、卡在哪、下一条命令是什么」，生成一张页面：

    SVAGENT_SONG=<slug> python E:\sv-bridge\scripts\dashboard.py --open

它写出 `songs/<slug>/dashboard.html` 并用浏览器打开，**每 5 秒自动刷新**
（右上角可以关掉）。所以做歌时把它开在另一个窗口，每跑完一步就会自己更新。

页面上的数字全部来自 `state.inspect()`，**是从文件现算的，不是记下来的** ——
你在 SynthV 里手改了工程，刷新一下就能看见。

第一版只读：所有操作还是在对话里说（「回到上一版」「这版不行」）。
另外四个面板（安全 / 会话树 / 本轮 / 指标）还没建，页面底部列着它们属于第几项。

---

## 六步

每一步的完整命令。`SVAGENT_SONG=<slug>` 是必须的前缀。

### 步骤 1 · 定题目

你做两件：① 题目发我　② 新建空 svp 并保存。

### 步骤 2 · 定歌词（在记事本里改）

我出 **2 版**（不是 6 版——歌词要逐行读，2 版刚好占满注意力），
在最大的那条轴上对立，你选一版或让我重出。

歌词文件：`songs/<slug>/lyrics.txt`，**UTF-8 带 BOM + CRLF**（否则记事本乱码）。

```bash
SVAGENT_SONG=yequ python E:\sv-bridge\toolkit\svagent\compose\lyricfile.py
```
检查格式与字数。改法写在文件开头：保留行首和弦、每行 8–10 字、
和弦只用 `Am Dm Em C F G`（是**级数**不是绝对音高，换调会一起转）。

**歌词文件是和声进行的唯一真相来源。** 不能从旋律反推（实测准确率只有 35%）。

### 步骤 3 · 定主旋律和和声（在 SynthV 里听）

```bash
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step3_melody.py
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step3_melody.py --write --closed
```

出**一条**主旋律 + 多条和声轨（不是 6 版——SynthV 不支持同轨重叠，
和声必须分轨；而且迭代比选择更贴合创作）。

局部修改：

```bash
# 只换和声，主旋律一个音符不动
... step3_melody.py --keep-melody --harmony 低八度 --write --closed
# 和声也覆盖预副
... step3_melody.py --harmony 低八度,下三度 --harmony-sections 副歌,预副 --write --closed
```

和声可选 `低八度 / 下三度 / 上三度 / 下六度`。

### 步骤 4 · 定伴奏（在 FL 里配器）

```bash
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step4_accompaniment.py --write
```

出伴奏 MIDI。然后**你在 FL 里做三件**（FL API 不允许加载插件，只能手动）：

1. 文件 → 导入 → MIDI 文件
2. **确认走带 tempo = 配置里的 bpm**（FL 常常不采用文件里的 tempo，
   这是唯一会毁掉全链路的错）
3. 五条轨挂音源。你的 FL 是 **Producer Edition**，
   零风险方案是 **FLEX + General Midi Library**（GM 音色号天然对得上）
   + **FPC**（鼓）：

   | 轨 | 搜什么 |
   |---|---|
   | Pad | `Warm Pad` / `Harmo Pad` |
   | Bass | `bass`（Acoustic Bass 也很好） |
   | Arp | `Crystal` / `bell` |
   | Counter | `Choir Aahs` |
   | Drums | FPC，或 GM 库里的 `kit` |

4. 导出 → Wave 文件 → 配置里的 `wav` 路径。
   **完整歌曲 / 44100 / 关归一化。**

### 步骤 5 · 伴奏进 SV + 调教

```bash
# 先验对齐（不通就别往下走）
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step5_assemble.py
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step5_assemble.py --write --closed
# 再调教
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step5_tune.py
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step5_tune.py --write --closed
```

对齐判据：**实际偏移 ≤10 ms 且三段极差 ≤5 ms**。
偏移是常量可以修（挪音频轨），**漂移不行**（tempo 不一致，回 FL 重渲）。

调教强度：`--scale 0.6` 调松，`--harmony-scale 0.3` 单独压和声，
`--clear` 全部清空。

### 步骤 6 · 混音

```bash
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step6_mix.py
SVAGENT_SONG=yequ python E:\sv-bridge\scripts\step6_mix.py --write --closed
```

只改 `.svp` 的 EQ / 压缩 / 混响 / gain / pan，**音频文件一个字节不动**，
`--clear --write --closed` 一键撤销。

---

## 三条硬规则

### 1. 写 svp 前必须关掉 SynthV

所有写工程的脚本**默认拒绝**，必须显式加 `--closed`；检测到 SynthV 进程
在跑还会再拦一次。

理由：SynthV 开着文件时我写盘，它内存里的旧内容可能被你「保存」回去，
**覆盖掉我刚写的**。实测差点发生过。

### 2. 一个项目一套文件，改动写回原处

不因为修改就新建文件。四个文件固定：

    songs/<slug>/lyrics.txt      歌词
    <svp>                        SynthV 工程（成品）
    <svp 同名>_伴奏.mid          伴奏 MIDI
    <svp 同名>_伴奏.wav          FL 渲染的伴奏（**别挪**，工程按绝对路径引用）

每次写前自动备份到 `<svp 目录>/_backup/`，带时间戳。

### 3. tempo 只在配置里定一次

一个 SynthV 工程只有一条时间轴。BPM 是**歌曲级决定**，
不能作为版本间的差异。改 BPM 就改 `project.json` 然后重跑步骤 3 起。

---

## 永久手动的部分（工具能力边界，不是待办）

| 环节 | 为什么 |
|---|---|
| 新建 svp | SynthV 桥 64 个动作里没有 new/open project |
| FL 导入 MIDI、挂音源、导出音频 | **FL 脚本 API 不允许加载插件**（工具自己写的） |
| 四道验收（词/旋律/编排/成品） | 你是判据本身，不是瓶颈 |

反过来，**这些原本以为要手动的其实不用**：指派声库、加音频轨、保存
（都写进 `.svp` 字段）；调教与混音（同上）。

---

## 已经踩过的坑（不要重犯）

| 坑 | 现在怎么防 |
|---|---|
| 句长独立随机 → **同轨重叠 57 处 + 11.5 秒断气音** | 每句小节数从曲式推导；末字长音上限 4 拍 |
| 「和声出界就移八度」→ **回到原音变成同音齐唱** | 改成换音程，并如实报出实际构成 |
| 声库只挂 `groups[].database` → 界面显示「未设置默认歌声」 | 同时挂 `mainRef.database` |
| 从别人的 `.svp`（v187）反推 schema → 少六处字段 | 以你的空工程（v196）为模板注入 |
| `hash()` 每进程加盐 → 只想改和声却连旋律一起变 | 改用 `zlib.crc32`；并提供 `--keep-melody` |
| 把「插件数据库」当已授权列表 → 推荐了 All Plugins 版的插件 | 只推 FLEX + FPC + 核心自带 |
| 拿成品伴奏当试听垫 → 「听起来都一样」 | 步骤 3 直接在 SynthV 里用星尘听 |
| 无 BOM 的 UTF-8 → 记事本乱码 | 歌词写 `utf-8-sig` + CRLF |

---

## 还缺的（想做时告我）

- **第九项检查：整句与和弦的贴合度。** `check_cadence` 只看末音；
  《晓风残月》有 4 句和弦音占比低于 30%（最低 12%），加伴奏后和声感偏模糊。
- **乐谱驱动的闪避 + 母带 LUFS 归一。** 要重写伴奏 wav，属于混音的下一档。
- **步骤 2 的歌词目前是我手写的**，不是生成的。接 Mistral API 是下一步。
- **零自动化测试。** 敏感度测试只是临时跑的命令行。
- **remix** 连定义都还没有（注意：V 家流程最后那步是混音，remix 是另一件事）。
