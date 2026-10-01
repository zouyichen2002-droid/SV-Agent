# sv-cover · Cover Skill 插件（v3 阶段 3）

在 DSH 的对话里说「翻唱这首」→ 后台跑 `sv-bridge/worker/cover_run.py`（M1 的 9 步串成一条）→ 项目里新开的 `rNN\` 出 `.svp` → 自动交付。

创作者 10-01 定：
- **歌词贴在对话里**（一条以「歌词：」开头的消息）：插件从消息里**原样**取、存进 `素材\歌词_原文.txt`，不让本地模型重抄（重抄一首要两三分钟，还可能抄错字）
- **跑的时候让出本地大模型**，跑完自动载回再告诉创作者结果（这段时间不能聊天，但电脑不卡、显卡空出来）
- 分离用显卡；声库默认星尘

```
 cover_run 工具（模型调）
   ① 找歌词：这个会话里创作者最近一条有「歌词：」的消息 → 原样存（换了歌词：旧的两份改名留着，不删）
   ② 开下一版 rNN（sv-artifact 的规矩）
   ③ 起一个后台任务（ctx.jobs.start），马上返回 —— 模型跟创作者说一声就结束这一轮
 后台任务
   ④ 等这一轮说完（看会话里的 turn/end；最多等 2 分钟，免得模型一直等着任务、两边卡死）
   ⑤ 让出本地大模型（端口上的进程、命令行要是 llama-server 才停）
   ⑥ 起 Worker（配置 sandbox: true 时包进沙箱 ctx.sandbox.confine；现在是 false，见下）；每 2 秒读 日志\进度.jsonl：
      「完成 / 失败」给模型看，其余只给界面看；Worker 退出后再补读一次
   ⑦ 成功：交付 rNN、记项目状态；失败：rNN 留着「进行中」，说是哪一步
   ⑧ 不管成功、失败、被停、插件自己出错：让出过的大模型一定载回（调成「低于正常」）
   ⑨ 任务结束 → DSH 唤醒模型 → 它用 present 把工程交给创作者
 创作者在任务列表里点停止 → 整组子程序停掉（taskkill /T）→ 载回大模型
```

技能说明在 `../../skills/sv-cover/SKILL.md`（「SV 创作」预设的 `skill-filesystem` 配了 `customSkillDirs` 指过去）。

**Worker 现在不进沙箱**（补丁里 `sandbox: false`，10-01）：Vocal2Midi 的听写写死了另起进程（multiprocessing），Windows 上走命名管道，DSH 沙箱不许开 → WinError 5。
Worker 是我们自己的固定流程：模型只能给「来源」和「用不用歌词」，插件先校验（链接只许 http(s)、本地文件要存在、或「已有」）；Worker 只往这首歌的项目文件夹里写。细节见 `docs/v3/s3-cover.md` §5.1。

语言（10-01）：插件不用管 —— Worker 按歌词自己认（有假名 → 日语，只有字母 → 英文），英文 / 日语的 svp 声库设成 SV 跨语种。

挑八度开关（创作者 10-01 定：加开关、默认开着）：`cover_run` 的 `octave_pick`，创作者说「这首不挑八度」时 Agent 填 false → Worker `--octave-pick off`，
这一版音高全照 Vocal2Midi 扒的；`说明.md` 里写明这一版开没开。为什么要这个开关：`docs/v3/s3-cover.md` §3.5。

## 怎么挂的

和 sv-project / sv-artifact 一样：只用 Node 自带模块 + 同仓库的两个插件，在配置档补丁里用绝对路径挂成全局一行（见 `../../profile-web.cordis.patch.yml`）。
要的 DSH 服务：`tools`、`jobs`、`sandbox`、`sandboxPolicy`（都在全局那一层）；用 `session/event` 事件记最近的用户消息、等 `turn/end`。

## 自检

```
node test.mjs
```

假 Worker（node 小脚本，命令行和 cover_run.py 一样）+ 假的大模型开关 + 假的会话事件，照真的顺序走：
贴歌词 → 调 cover_run → 这一轮没说完不让出大模型 → 说完才让、才跑 → 交付、记状态、载回；另外测失败、点停止、不用歌词、换了歌词。
10-01 故意改坏两处验证测试会响：不等这一轮说完就让出大模型 → 1 项没过；Worker 退出后不补读进度 → 1 项没过。
