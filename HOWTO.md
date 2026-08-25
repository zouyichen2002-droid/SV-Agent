# SV-Agent 使用手册

| | |
|---|---|
| 更新 | 2026-08-25，十项建造完成、《风筝线》端到端跑通之后 |
| 给谁看 | **创作者**（不写代码），以及接手这个项目的下一个 agent |
| 一句话 | 你说人话，agent 干活；**每一步都可度量、可回滚** |

---

## 0. 你只需要记住三条命令

真正日常会用的就这三条。其余全是它们的展开。

```bash
python E:/sv-bridge/scripts/sv.py state          # 这首歌到哪了、下一步谁做
python E:/sv-bridge/scripts/sv.py dash --open    # 一张网页看全部：状态/树/安全/指标/诊断
python E:/sv-bridge/scripts/sv.py why "副歌不够爆"  # 说一句人话，它诊断
```

**更省事的办法：在 Claude Code 对话里打斜杠命令**，不用记路径：

    /sv-state    到哪了
    /sv-dash     开仪表盘
    /sv-why      诊断一句诉求
    /sv-tree     看会话树、回退
    /sv-safety   五盏灯（怀疑出事了就看这个）
    /sv-act      看动作池 / 跑一个动作

---

## 1. 三种用法，按你的场景挑

### A. 跟 agent 说话（最常用）

在 Claude Code 里直接说人话：「副歌太平」「换个和声」「回到上一版」。
agent 会自己去调工具、跑检查、把**数字**给你看。

**这是设计的主路径。** 你不需要知道底下有 12 个动作。

### B. 自己敲命令

想自己掌控节奏时用 `sv.py`。每个子命令都有 `--json`（给脚本用的）。

```bash
python E:/sv-bridge/scripts/sv.py --song zhuimeng state
```

不给 `--song` 就用**最近改动过的那首**。

### C. 让模型自己跑一轮

```bash
python E:/sv-bridge/scripts/sv.py ask "帮我看看这首歌还差什么"
```

模型读上下文 → 调工具 → 看数字 → 给结论。
**每分钟只有 4 次请求**（Mistral 免费档实测），所以它一轮只做一件事。

---

## 2. 开一首新歌

**你只做三件事**：给一句主题、选一版歌词、在 FL 里配器导出。其余我做。

### 你给一句主题

就一句话。**越具体越好写** ——「末班地铁上给自己写的信」比「孤独」好写十倍。
抽象主题不是不能写，但要接受它更容易写成口号。

我会建好 `songs/<slug>/project.json`、从模板生成空 `.svp`。
**你不用在 SynthV 里手工建工程。**

### 你选一版歌词

我出 2 版候选（一次请求出完，不是两次）。你选一版，可以直接改字。
我修字数、韵脚、口号句，再写进 `songs/<slug>/lyrics.txt`。

**这个文件永远是你的。** 想改随时改，改完跟我说一声，我重跑旋律。

### 我做旋律与和声

八项检查必须 0 finding 才往下走。

### 你在 FL 里三步 ← **唯一非你不可的一段**

1. `File → Import → MIDI file`，选 `<歌名>_伴奏.mid`
2. **按通道拆分**，把 5 个 pattern 拖进播放列表，**都对齐第 1 小节**
3. 逐条挂音源，导出到 `<歌名>_伴奏.wav`

为什么必须你来：**FL 的脚本 API 不能加载插件**
（原文 *"We cannot load NEW plugins (FL API limit)"*，见事实 F04）。
任何 agent 都替不了这一步。

音源只推荐你有的（Producer 版：**FLEX · General MIDI Library · FPC**，事实 F05）。

### 我做剩下的

挂音频轨 → **验对齐** → 调教 → 混音。

**对齐不过我不往下走** —— 对不上的话后面全是白做。
判据：偏移 ≤10 ms 且三段极差 ≤5 ms。

---

## 3. 改一首已有的歌

### 说一句人话就行

```bash
python E:/sv-bridge/scripts/sv.py why "副歌不够爆"
```

它会做三件事之一：

| 它说什么 | 意思 |
|---|---|
| 给你几个假设 + 提案 | 指标上看得出问题，它有把握 |
| **「不猜，问你」** | **指标看不出问题，或者两个原因分不开** |
| 「认不出这句话」 | 第一版只敢自动诊断三类，其余一律问 |

**第二种不是缺陷，是设计。** 一个会说「我不确定」的诊断层是可用的，
自信瞎猜的不是。这时候你多给一句具体的（哪一段、什么感觉），或者直接告诉我改哪里。

### 想让它真的试

```bash
python E:/sv-bridge/scripts/diagnose.py "副歌不够爆" --trial
```

三个假设**各自在隔离副本里**跑一个动作，量完并排给你看。**真工程不动。**
满意了再加 `--apply`。

### 只改一段

```bash
python E:/sv-bridge/scripts/sv.py act gen_melody --params '{"scope": ["副歌"]}'
```

**只重生成副歌，其余段落逐字段不变。** 局部修改是归因的前提 ——
整首重生成之后，你说「好听了」我也不知道是哪一处起的作用。

### 从旧版本取一段

```bash
python E:/sv-bridge/scripts/sv.py act pick --params '{"from_node":"n0003","sections":["副歌"]}'
```

「回到上一版的副歌，但保留现在的调教」—— 这不是 merge，是取第 N 段。

---

## 4. 出事了怎么办

### 先看五盏灯

```bash
python E:/sv-bridge/scripts/safety.py
```

    ✓ 原子写      有没有崩溃残留
    ✓ 哈希校验    **你手改过的文件，我会拒绝覆盖**
    ✓ 全套快照    存了几个、去重省了多少
    ✓ 可中断      有没有请求停止
    ✓ 循环超时    预算还剩多少

**灰灯不是坏事**，是「还没有可判断的依据」。别把它当问题。

### 哈希那盏灯红了

说明你在 SynthV / 记事本里改过东西。两条路，**都会先自动拍快照，怎么选都丢不了**：

```bash
python E:/sv-bridge/scripts/safety.py --adopt      # 以你的版本为准
python E:/sv-bridge/scripts/safety.py --restore c001  # 回滚到某个快照
```

### 回到之前某一版

```bash
python E:/sv-bridge/scripts/tree.py                    # 看树
python E:/sv-bridge/scripts/tree.py --checkout n0003   # 回去
```

**切走之前会自动存一个节点**，所以随便切。

### 让它停下来

```bash
python E:/sv-bridge/scripts/safety.py --stop     # 下一个动作之前退出
python E:/sv-bridge/scripts/safety.py --resume
```

它**只在两个动作之间退出**，不会掐断正在写的文件。

### 不满意某一版，告诉它

```bash
python E:/sv-bridge/scripts/tree.py --verdict n0003 rejected "太满了"
```

被否决的节点带着**规格特征 + 你的原话**留下来 —— 那是记忆层的原料。

---

## 5. 四条硬规则

### 1. 写 `.svp` 前必须关掉 SynthV

SynthV 开着该文件时我写盘，它内存里的旧内容可能被你保存回去**覆盖掉**。
所有写动作都要 `--closed` 确认，检测到 SynthV 在跑直接拦住。

### 2. 一个项目一套文件，改动写回原处

一个 txt、一个 svp、一个 FL 工程。不因为改动就新建文件。
安全网是快照与会话树，不是文件名后缀。

### 3. 克隆之后先装提交钩子

```bash
git config core.hooksPath .githooks
```

它会在每次 `git commit` 前扫暂存区，命中疑似凭据就**拦住提交**。

Mistral 那份 key **与他人共用、不能轮换**（事实 F18），
所以泄露的代价不是「换一个」，是几个人一起受影响。
`core.hooksPath` 不会跟着 clone 走，**所以这一条要手动装一次**。

### 4. 你随时可以手改，但改完说一声

FL、SynthV、歌词 txt 三处你都可以随时动（事实 F16）。
哈希校验会发现，然后**拒绝覆盖**而不是默默盖掉。

但**跟我说一声更省事** —— 否则我下一个动作会被拦住，我们要多绕一圈。

---

## 6. 想知道更多

| 文件 | 内容 |
|---|---|
| `specs/facts.md` | **17 条环境硬约束**，每条都写了「不知道会怎样」和「怎么学到的」 |
| `specs/agent-architecture-v1.md` | 架构。为什么这么设计 |
| `specs/v1-acceptance-report.md` | 验收报告。**做了什么、量到了什么、还缺什么** |
| `specs/testing-and-acceptance.md` | 每一项的判据与实测数字 |
| `specs/adr/` | 13 份决策记录。每份都写了「什么证据会推翻它」 |

### 一句话概括这套东西的取向

> **模型负责品味，检查负责正确。**
>
> 所以每个动作返回的不是「执行成功」，是 `findings 前后 / 改了几个音符 / 对齐偏移多少毫秒`。
> 你和模型都看数字决定下一步，不看谁的自我感觉。
