# DSH 本机配置（副本）

v3 阶段 0（2026-10-01）在这台机器上搭 DeepSeek Harness（DSH）用的补丁和启动脚本的**副本**，换机器或出问题时照着重搭。
**补丁和启动脚本：DSH 实际读的是仓库外那几份** —— 改了那边要同步过来；**插件源码只在这里**（`plugins/`，补丁直接用绝对路径指过来，本机没有 pnpm 所以不走 bundle 安装）。为什么这么搭、测了什么，见 `docs/v3/s0-dsh.md`、`s1-project.md`、`s2-artifact.md`。

| 这里 | 实际在用的那份 | 是什么 |
|---|---|---|
| `profile-web.cordis.patch.yml` | `E:\sv-agent-data\dsh-home\profiles\web\cordis.patch.yml` | 我们的补丁层：模型 → 本地 llama（默认 Qwen3.6-35B-A3B、32k；旧的 Qwen3.8-27B、16k 留着）；选目录 → 网页对话框；默认预设「SV 创作」（16 个工具，压缩按模型的窗口配）；挂我们自己的插件 |
| `plugins/` | **只有这里一份**（补丁里用绝对路径直接指过来，不复制） | 我们自己写的 DSH 插件：`sv-project`（阶段 1：一首歌一个工作区，Agent 知道在做哪首歌）、`sv-artifact`（阶段 2：版本、交付后拦住覆盖、创作者改了自动备份）、`sv-cover`（阶段 3：对话里翻唱一首歌）、`sv-memory`（阶段 6：你的反馈、偏好、历史）、`sv-video`（视频：给图和成品音频，出歌词视频的成片 + 剪映草稿）—— 见各自的 README |
| `skills/` | **只有这里一份**（「SV 创作」预设的 skill-filesystem 用 customSkillDirs 指过来） | 我们写的技能说明：`sv-cover`（什么时候、怎么调 cover_run）、`sv-video`（什么时候、怎么调 video_run） |
| `start-llama.sh` | `E:\sv-agent-data\dsh\start-llama.sh` | 本地模型服务（10-03 起）：llama.cpp CUDA 版 + Qwen3.6-35B-A3B（MoE，放不进显存的专家放内存、不映射模型文件），上下文 32k；要密钥、跨域只认本机、关 `/slots`。为什么换见 `docs/v3/moe-trial.md` |
| `start-llama-27b.sh` | `E:\sv-agent-data\dsh\start-llama-27b.sh` | 旧的本地模型（Qwen3.8-27B，16k），留着备用；和上面那个同一个端口，同时只开一个，换的时候 DSH 的默认模型也要一起改 |
| `start-dsh-web.sh` | `E:\sv-agent-data\dsh\start-dsh-web.sh` | DSH 网页界面：只开本机、遥测关、权限预设 workspace-write |

**故意没放进来的**：模型服务密钥（`E:\sv-agent-data\dsh\llama.key`）、DSH 访问令牌（每次启动打在它的输出里）、会话记录（`E:\sv-agent-data\dsh-home\sessions`）、DSH 本体（npm 装的 `node_modules`）。
补丁里也有 DSH 自己写进去的界面设置（`ui-settings-general`），照抄就行。

## 起和停

```
bash E:/sv-agent-data/dsh/start-llama.sh     # 先起模型（约 15 秒）；起来以后把 llama-server 进程调成「低于正常」
bash E:/sv-agent-data/dsh/start-dsh-web.sh   # 再起 DSH；带令牌的访问地址在它的输出里（输出存成文件的话，那个文件别打开给别人看）
```

停：停掉这两个进程。Git Bash 下停外层不一定连带停掉 node / llama-server → 按端口（DSH 3080、模型 8081）查到进程、核对命令行再停。
默认模型实占内存约 10 GB、显存约 10 GB，不用就关。看占多少别看「私有字节 / 提交」：里面约 9.5 GB 是显卡驱动给显存记的账，看「工作集 - 私有」。

## 换机器重搭

1. Node 24；`npm install @deepseek-ai/dsh@0.2.0-rc.2`（锁版本，开发者预览）装到 `E:\sv-agent-data\dsh`
2. llama.cpp b11259 CUDA 版 + 模型文件（10-03 起默认的那个见 `docs/v3/moe-trial.md`；旧的型号和参数见 `docs/v3/s0-dsh.md` §2）
3. 生成模型服务密钥文件 `llama.key`：第一行 `#` 注释，第二行一个随机串（模型服务的两个脚本和 DSH 的启动脚本都从这里读）
4. 补丁放到 `DSH_HOME\profiles\web\cordis.patch.yml`，用 `dsh --profile web --dump-config` 看合并结果（插件那几行写的是本仓库的绝对路径，仓库换了位置要跟着改）
5. 工作区 `E:\sv-agent-workspace`：要给自己加「完全控制」（Windows 沙箱要打低完整性标签；只有「修改」会让沙箱里的命令全失败，见 `docs/v3/s0-dsh.md` §2）
