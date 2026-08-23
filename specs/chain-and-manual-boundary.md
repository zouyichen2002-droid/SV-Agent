# 全链路与手动边界（2026-08-23 取证）

《宇宙无边无垠》走通全链路之后，把每个环节的自动/手动边界逐项验证一遍。
**这份文档的用途是：区分「工具天花板」和「我们还没做的活」。**
前者要接受或绕开，后者才是该干的。

## 链条

    主题 → 歌词 → 主旋律 → 写入 SynthV → 伴奏 MIDI → FL 配器 → 混音 → 对齐 → 成品
            ①      ②          ③            ④          ⑤        ⑥      ⑦      ⑧

| 环节 | 已自动 | 仍需手动 |
|---|---|---|
| ① 歌词 | — | 我手写 + 创作者验收 |
| ② 主旋律 | 七项检查 | 我手写 + 创作者验收 |
| ③ 写入 SynthV | tempo · 建轨 · 音符 · 回读逐字段校验 | 新建工程 · 指派声库 · 保存 |
| ④ 伴奏 MIDI | 生成 + 六项校验 + 预览音频 | **无 —— 唯一全自动的环节** |
| ⑤ FL 配器 | 音源推荐（读实际插件库） | 导入 MIDI · 拖样式进播放列表 · 挂音源 · 调音色 |
| ⑥ 混音 | 参数层全部 + 免驱动音频分析 | 挂效果器插件 |
| ⑦ 对齐 | 互相关 + 自校准 + 偏移/漂移分离 | — |
| ⑧ 成品 | — | FL 导出音频 · 拖进 SV 当音频轨 · 保存 |

## 手动 10 项，按原因分类

### A. 工具能力边界

**SynthV 桥 —— 64 个动作（17 读 / 29 编辑 / 7 删除 / 9 UI / 2 事务）**

| # | 手动的事 | 证据 |
|---|---|---|
| 1 | 新建工程 | 64 个动作里没有 new/open project |
| 2 | 指派声库 | `set_group_voice` 只有 loudness/tension/breathiness/gender/toneShift，无 `database` |
| 3 | 加音频轨（放伴奏） | 全部动作名里没有任何 audio 相关项 |
| 4 | 保存 | 没有 save 动作 |

**FL 桥 —— 67 个工具（混音/效果/插件 26 · 查询 31 · 写音符 5 · 编排 4 · MIDI 导出 1）**

| # | 手动的事 | 证据 |
|---|---|---|
| 5 | 导入 MIDI | 没有这个工具 |
| 6 | 拖样式进播放列表 | 4 个 `fl_arrange_*` 都不能放片段 |
| 7 | 挂音源 | `fl_plugin_list`：**"We cannot load NEW plugins (FL API limit)"** |
| 8 | 音源音色 / 预设 | `fl_list_presets`：**"FL can't LOAD presets via the API"**；且 `fl_plugin_get_params` 强制要 `slot`，**只寻址混音器效果槽，碰不到通道上的音源** |
| 9 | 挂效果器插件 | 同 #7 |
| 10 | 导出音频 | 没有工具；`FLEngine_x64.dll` 里无渲染开关，FL 帮助文档搜 "command line" 零命中 |

**#7 一条同时封死了 #7 #8 #9，还间接封死了 ⑥ 的入口。**
FL 侧唯一绕法是**工程模板**：把「每首歌手动 N 次」变成「一次性手动」。

### B. 尚未自动化（不是天花板，是还没做）

- 主题 → 歌词
- 歌词 → 主旋律

### C. 按设计就该创作者做

- 四道验收（词 / 旋律 / 编排 / 成品）—— 他是判据本身，不是瓶颈
- 驱动级软件安装（loopMIDI 这类）

## 一条贯穿性规律

**唯一全自动的环节（④ 伴奏）是唯一一个输入输出都是文件的环节。**

凡是要读写宿主软件的**运行时状态**，都撞在 API 边界上；
凡是输入输出都是**文件**，都能做到全自动、可校验、可回归。

这条规律直接指向下面的发现。

## 决定性发现：`.svp` 是纯 JSON

2026-08-23 实测 14 个 `.svp` 文件：

```
version 187，顶层键 ['library', 'renderConfig', 'time', 'tracks', 'version']
tracks[i] 键 ['dispColor','dispOrder','groups','mainGroup','mainRef','mixer','name','renderEnabled']
```

两个关键字段都存在：

| 需求 | 字段 | 实测值 |
|---|---|---|
| 指派声库（#2） | `tracks[i].groups[j].database.name` | `"MEDIUM5·Stardust"`（星尘），在样本中出现 16 次 |
| 加音频轨（#3） | `tracks[i].mainRef.audio` | `{filename, duration, bpm, alternativeBPMs, ...}` |
| 新建工程（#1）、保存（#4） | — | 写文件本身就是新建 + 保存 |

**所以直接生成 `.svp` 可以一次性消除 SynthV 侧全部 4 项手动。**
成品从「一个需要六步手工装配的 DAW 状态」变成「一个双击就能听的文件」。

风险：格式无官方文档，`version 187` 意味着版本可能漂移。
缓解：手上有 14 个真实 `.svp` 可反推；且桥本身必然知道 schema，可交叉验证。

## 复现命令

```bash
python E:\sv-bridge\out\melody_v2.py                    # 旋律 + 七项检查
python E:\sv-bridge\scripts\make_accompaniment.py       # 伴奏 MIDI + 预览音频
python E:\sv-bridge\scripts\verify_accompaniment.py     # 六项校验
python E:\sv-bridge\scripts\write_song.py --write       # 写进 SynthV（需桥在线）
python E:\sv-bridge\scripts\verify_alignment.py <FL渲染.wav>
python E:\sv-bridge\scripts\analyze_mix.py <混音.wav>   # 免驱动
cd E:\sv-bridge\toolkit && python -m svagent.flbridge   # FL 桥体检
```
