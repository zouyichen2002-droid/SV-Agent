# v3 阶段 0 · 原样跑通 DSH，弄懂它怎么搭起来的

| | |
|---|---|
| 对应 | PRD §0.4 阶段 0：「原样跑通 DSH（本地模型）；弄懂 Context / Plugin / Service、Session / Tool / Agent Loop」 |
| 日期 | 2026-10-01 |
| 状态 | **跑通了**：本地模型、专用工作区、沙箱把写入关在工作区里、越界要审批；Python 翻唱链路的两个环境在沙箱里能跑、能用显卡；为 16k 上下文配了精简预设「SV 创作」、压缩重配并实测走通。设计见第 5 节，对阶段 1–4 的含义见第 6 节 |
| 版本 | DSH 0.2.0-rc.2（npm 锁版本，开发者预览）· llama.cpp b11259 CUDA 13.4 · Qwen3.8-27B UD-IQ4_XS |

DSH 的东西全在仓库外（`E:\sv-agent-data\dsh`、`E:\sv-agent-data\dsh-home`、`E:\sv-agent-workspace`）；这份材料只记怎么装、测了什么、学到什么。
访问令牌、模型服务密钥都不写进来。

---

## 1. 结论

- **DSH 原样能用**：网页界面 + 本地模型 + 工具调用 + 审批 + 沙箱，第一轮 37 秒答完一个简单问题。
- **沙箱真的关得住**：沙箱里的命令能写工作区，往外写被拒（模型的报告 + 沙箱外独立核对两边都对上）。
- **我们的 Python 能在沙箱里跑**：分离环境（torch、audio-separator）、扒谱环境（onnxruntime + DirectML 显卡）都能启动、能写工作区、往外写被拒 → Cover Skill 不需要放开沙箱。
- **最紧的是上下文**：16k 的窗口，DSH 原装预设每个新会话光固定开销（系统提示词 + 26 个工具说明 + 运行时上下文）就占约 45%（约 7.4K token）；
  而且**原装的压缩在 16k 下从不主动触发**（按「留 65536 token 余量」算出负数，只警告一次）→ 长一点的会话必然撞墙。
  已处理：另建精简预设「SV 创作」（14 个工具）→ **起手降到 28%（约 4.5K）**；压缩按 16k 重配（约 11.3K 开始压）→ `/compact` 实测走通。
  你 10-01 定：**本地为主，上下文不够时用 DeepSeek 接口**（先说过 Mistral，又改成 DeepSeek，「和 dsh 适配性更强」）。
- **其次是内存**：模型服务常驻约 11–13 GB，开着的时候整机可用内存只剩 0.5–1.5 GB → 不用就关，要用 12 秒起来。

## 2. 怎么跑起来的

```
 llama.cpp（CUDA）─ 127.0.0.1:8081，要密钥，跨域只认本机，关 /slots，低优先级
   │  Qwen3.8-27B，上下文 16k，KV 8 位，放不进显存的层自动放 CPU，服务端关思考
   ▼
 DSH web ─ 127.0.0.1:3080（只开本机，令牌登录），遥测关
   │  配置档 web + 我们的补丁 cordis.patch.yml：
   │    ① 模型 → 本地 llama（OpenAI 兼容接口），新会话默认用它
   │    ② 选目录 → 网页里的对话框（不在你桌面上弹 Windows 窗口）
   │    ③ 新会话默认用精简预设「SV 创作」（14 个工具，压缩按 16k 配；原装 standard 留着对照）
   │  权限预设 workspace-write：沙箱只许写工作区，越界的先问你
   ▼
 工作区 E:\sv-agent-workspace（专用空目录，不指向你的 FL / SV 文件夹）
```

| 东西 | 在哪 |
|---|---|
| DSH 本体 | `E:\sv-agent-data\dsh`（npm 装，536 个包，510 MB） |
| DSH 数据（配置档、会话） | `E:\sv-agent-data\dsh-home`（`DSH_HOME`） |
| 配置补丁 | `E:\sv-agent-data\dsh-home\profiles\web\cordis.patch.yml`，改完用 `dsh --profile web --dump-config` 看合并结果 |
| 启动脚本 | `E:\sv-agent-data\dsh\start-llama.sh`、`start-dsh-web.sh` |
| 模型服务密钥 | `E:\sv-agent-data\dsh\llama.key`（两个启动脚本都从这里读；不进仓库） |

装的时候踩过的坑：

| 坑 | 原因 | 解法 |
|---|---|---|
| 「添加工作区」按钮消失 | 自动选目录模块会挂**两半**（本机服务 + 网页界面）；关掉它只补回本机那半 | 补丁里两半都插 |
| 补丁报 name mismatch | 补丁不能改已有条目的插件名 | 原条目 `disabled: true`，另 `insert` 一条 |
| 沙箱里的命令全失败 `SetNamedSecurityInfoW failed (Win32 5)` | Windows 沙箱要给工作区打「低完整性」标签，要求你本人对目录有**完全控制**；E 盘根下新建的目录只继承到「修改」 | 你给 `E:\sv-agent-workspace` 加了 admin 完全控制（10-01） |
| 没批准的 5 个安装脚本 | npm 默认不跑 | 查过：在 Windows 上都不需要（一个只在 macOS/Linux 用，node-pty 有现成的 win32-x64 预编译） |
| 16k 下压缩从不触发 | 触发线 = `floor(min(W×0.8, W−输出预留−65536))`，16k 下是负数 → 抛错、只警告一次、跳过（`dsh-compaction-basic\lib\index.js`）；DSH 的日志不打到我们的启动日志里，界面上也看不出来 | 「SV 创作」预设里按模型配 `headroomTokens: 1024`、摘要上限 1024；模型条目加 `maxTokens: 4096` |
| 预设里的行改不动 | 补丁按 id 找行时只往 `group: true` 的分组里钻；预设的子行在 `config.plugins` 里，找不到 | 另建一个预设（官方也说：要么整份覆盖，要么新建） |
| 停服务时子进程常常留着 | Git Bash 下停后台任务不一定连带停掉 node / llama | 停完按端口查进程、核对命令行再单独停 |

## 3. 跑通的证据

| 测试 | 结果 |
|---|---|
| 第一轮：列出默认工作区（只读） | 37 秒、2 步，沙箱里的 `pwsh` 正常 |
| 第二轮：在 E 盘工作区写文件、跑命令 | 内置写文件工具成功；沙箱里的命令 4 次全失败（权限，见上表）。模型自己去加载权限诊断修复技能、申请 danger-full-access —— 我替你拒了、停了这一轮 |
| 第三轮（你改完权限后）：沙箱里 `pwsh` 查目录 → 在工作区建文件 → 往 `E:\sv-agent-data\dsh\` 写 | 前两步成功；第三步 `Access to the path ... is denied` + `[sandbox: file access denied under workspace-write mode]`；沙箱外核对：那个文件不存在 |
| 直接用 DSH 的沙箱启动器跑我们的 Python（不经过模型） | 两个环境都：导入成功、写工作区成功、写私有临时目录成功、写 `E:\sv-agent-data\dsh\` 和 `AppData\Local` 被拒；扒谱环境建推理会话拿到 `DmlExecutionProvider`（显卡）。沙箱外核对：被拒的文件都不存在、工作区上没多出授权条目、临时目录已清掉 |
| 「SV 创作」预设：只回一个字 | 1 步、10 秒、4.5K token、上下文 28%（原装预设 45%）；轨迹页核对：14 个工具 |
| 「SV 创作」预设：手动压缩 `/compact`（两次） | 第一次「已压缩 3 条历史记录（约 401 tokens）」，41 秒；第二次（压缩参数改成只对本地模型）摘要 422 token 不比原文 402 token 短 → **按设计不替换**（轨迹页记的原话：`summary is not smaller than the shadowed content`），说明摘要请求照常跑完 |

## 4. 安全设置（现在是什么样）

| 项 | 现在 | 为什么 |
|---|---|---|
| 权限预设 | workspace-write + 审批 ask | 沙箱里只许写工作区；越界（例如要 danger-full-access）先问你 |
| 沙箱留下的标记 | 工作区上 3 条常驻改动：能力 SID 写入授权、Everyone 拒绝删除子项、低完整性标签 | DSH 的设计（复用缓存）；**DSH 关了也在，icacls 撤不掉**，只能用它自己的模块撤或删目录；低完整性标签让同账号别的低完整性程序也能写这个目录 → 工作区只放 DSH 的产出 |
| 默认工作区 | DSH 自己建的 `C:\Users\admin\Documents\deepseek-harness\default-workspace`，空，已带同样的标记 | 第一轮测试在那里跑过命令；用不到可以整个删掉（你删） |
| 模型服务 | 要密钥、跨域只认本机来源、关 `/slots` | 默认没密钥且接受任何网页跨域调用 → 浏览器里随便一个网站都能在后台用这个模型、读它正在处理的对话 |
| 遥测 | 关（`DSH_TELEMETRY_DISABLED=1`） | 默认在你点反馈时会把会话片段发到 DeepSeek 的服务器 |
| 联网工具 | `web_search` 走 DeepSeek 在线接口，没配密钥 → 用不了；`web_fetch` 不要密钥，能从本机抓任意网址 | 「SV 创作」预设里都没放；要不要加回来见第 8 节 |
| 模型配置 | 补丁按 id 覆盖时整块替换 → 模型配置里只剩本地这一个，DSH 默认带的 DeepSeek 在线模型被拿掉了 | 正合「本地为主」；以后接 DeepSeek 接口时在补丁里加回来 |
| 插件 | 「添加插件」接受 npm 包名、GitHub 地址、本地目录；**插件以你的权限运行，不进沙箱** | 我们自己写的插件放本地目录挂；别人的插件要先审 |

## 5. DSH 怎么搭起来的

读的是装好的包自带的说明和代码（`E:\sv-agent-data\dsh\node_modules\@deepseek-ai\` 下各包的 README / `lib/`），关键的几条我对着原文核过；
DSH 自己带了一份插件开发指南（`dsh-agent-preset\skills\cordis-plugin-development\`，有模板），阶段 1 照它写。下文的路径都相对这个目录。

### 5.1 一切都是插件：Context / Plugin / Service（Cordis）

```
 ctx（上下文）── 一个依赖容器：读 ctx.tools 就是拿「工具」服务；没在 inject 里声明就读会报错
   │
   ├─ 插件 = 一个 ESM 模块：export function apply(ctx, config) + 可选 inject（要哪些服务）/ Config（配置格式）
   │         或者默认导出一个 Service 类
   ├─ 服务 = class X extends Service（构造时注册）或 ctx.provide(名字, 值)
   └─ 往别的服务里登记东西：ctx.tools.register(…) · ctx.skills.register(…) · ctx.systemPrompt.section(…)
        都算「这个插件的副作用」：插件卸载，它登记的东西自动撤掉；它依赖的服务换了，它自动重载
```

| 要点 | 出处 |
|---|---|
| 插件形态、`inject` / `Config` 二选一的写法 | `cordis-plugin-development\references\host-plugin.md` |
| Service 基类、`ctx.provide` | `cordis\src\service.ts`、`cordis\src\reflect.ts` |
| 生命周期（加载、失败、卸载、依赖变了重跑） | `cordis\src\fiber.ts` |

### 5.2 配置档（Profile）、Bundle、补丁

- **配置档** = 一棵「插件行」的树（每行 `id` / `name` / `config` / `disabled`，可以分组）；内置 `web` / `headless` / `acp` / `sdk` / `sdk-minimal`
- **层序**：各 bundle 自带的补丁 → 配置档的 `cordis.patch.yml`（我们写的那份）→ `DSH_HOME\cordis.patch.yml` → 命令行 `--patch`；`cordis.yml` 每次启动重写，不要改
- **按 id 覆盖时整块替换、不合并**（`cordis-plugin-include\src\index.ts`：`target[key] = value`）→ 我们补丁里的模型配置把 DSH 默认带的 DeepSeek 在线模型**整个去掉了**，只剩本地那一个（正合「全部本地」）
- **我们的插件 = 一个 bundle**：一个本地目录，`package.json` 里写 `"type": "module"` 和 `dsh.bundle.patch`（指向它自己的 `cordis.patch.yml`，里面 `insert` 插件行）；
  装法：`dsh plugin --profile web add <绝对路径>`，或在对话里让 DSH 用 `plugin_manager` 的 `install_bundle`（这个工具只在「Creator」预设里开）；ESM JS（TypeScript 要先编译）
- **插件不进沙箱**：在 DSH 进程里、以你的权限运行 —— 我们自己写的才挂，别人的先审

### 5.3 一轮对话怎么跑、上下文怎么拼

```
 你发一条消息 → 进收件箱
 每一步（step）：
   ① 取收件箱 → ② 拼系统提示词（各段按 order 拼；内容一变，整段重写 → 模型服务的缓存前缀整个失效）
   ③ 运行时上下文：各插件 ctx.systemPrompt.context(...) 的文字拼成一条「Current runtime context…」，内容变了才追加一条新的
   ④ agent/pre-step 钩子（插件可以加消息、拒绝这一步）· 压缩检查（超过触发线先压缩）
   ⑤ 发请求（系统提示词 + 历史 + 工具说明）→ 模型回复
   ⑥ 有工具调用 → 执行（可以并行，默认最多 10 个；要审批的在这里等你点）→ 结果进历史 → 下一步
   ⑦ 没有工具调用 → 这一轮结束
 第一步还会追加：DSH_HOME\AGENTS.md + 工作区一路上的 AGENTS.md / CLAUDE.md（一条提醒消息）、可用技能清单
```

- 没有内建的步数上限；你点停止时，已经流出的字保留，没派发的工具调用记成中止
- 模型请求失败默认重试 5 次（间隔 0.5–10 秒）；流式输出 300 秒没动静算超时
- **插件往对话里加东西的三种办法**（从弱到强；官方要求用够用的最弱那种）：

| 办法 | 适合 | 现成的例子 |
|---|---|---|
| `ctx.systemPrompt.context({ name, order, text })` | 每步都要、变化少的状态（**Project 插件用这个**；`text` 是同步函数，数据要先缓存好） | `dsh-sandbox-policy`（就是第 1 轮里那条「文件策略」） |
| `agent/pre-step` 钩子 | 要异步取数据、要自己的消息类型（以后的创作记忆；消息可以标成 `recall`） | `dsh-time-context` |
| `agent.inject()` | 一次性通知（不会唤醒 Agent） | `dsh-user-approval` |

- **项目状态别放进系统提示词**：系统提示词一变，缓存前缀（现在约 4.5K token）整个作废，本机读提示约 400 token/秒 → 每步多等 10 秒以上；运行时上下文是追加在历史后面的，不破坏前缀

### 5.4 会话（Session）

- 会话 = 只追加的事件日志（`DSH_HOME\sessions\--<工作区路径>--\<会话 id>\session.v4.jsonl.zstd`，每批落盘）
- **日志是唯一的事实来源**：模型看到的一切都要能从日志重建，分叉（fork）、恢复、重放都靠它 → **插件不能自造新的事件类型**（会话会再也打不开）；
  插件自己的数据放 DSH 的存储服务（`ctx.storageDomain`），按会话算出来的状态用 `ctx.sessionProjections`
- 会话的工作目录在创建时定死，之后不能改；它同时是沙箱的写入根
- 压缩：超过触发线，就把较早的一段历史换成一段摘要（另发一次请求生成），最近的一段原样留；摘要不比原文短就不换
- 标题：用同一个模型生成（64 token 以内）

### 5.5 工具（Tool）

- 登记：`ctx.tools.register(defineTool({ name, description, parameters, output, execute }))`；参数用 DSH 自己的写法（每个字段写 `type`，必填加 `required: true`），编译成 JSON Schema
- 出错不会中断这一轮：模型只看到 `Error: …`，自己决定下一步；没声明 `timeoutMs` 就不会被超时截断
- 对某个 Agent 隐藏工具：`ctx.tools.restrict()`（写插件时省上下文的办法；现在我们是直接另建预设、不挂那些工具）；要审批：在 `tools/pre-execute` 返回 `ask`，或 `execute` 里调 `ctx.approval.request`
- 最短的完整例子：`dsh-tool-present\lib\index.js`

### 5.6 技能（Skill）

- 一个技能 = 一个目录里的 `SKILL.md`（开头写 `name`、`description`；建议 8192 字以内）；**只是说明文档，不能自带工具** —— 能执行的工具要插件另外登记，同一个插件可以两样都做
- 放哪：工作区的 `.dsh\skills\<名字>\SKILL.md`（工作区不是 git 仓库时就以工作区为准）、`DSH_HOME\skills\` 等；**有文件监听，改了不用重启**
- 模型先看到「可用技能」清单（就是第 1 轮里那条 `<available_skills>`），调用 `skill` 工具才读全文
- 例子：`dsh-skill-office`（三份 `SKILL.md` + 一个 Python 脚本，结构最像 Cover Skill）

### 5.7 后台任务（Job）

- 不写代码：沙箱里的 `pwsh` 加 `run_in_background: true` 就是后台任务；前台跑过 2 分钟（默认）自动转后台，不杀
- 插件里：`ctx.jobs.start({ kind, label, owner, run })` → 用 `updateProgress` 报进度、`append` 写输出；跑完通知 Agent（Agent 闲着会被唤醒开新一轮），结果在第一次 `job_output` 交付
- 限制：每个会话最多同时 10 个；**DSH 退出任务就没了**（只在进程里）；用户可以在任务列表里点停

### 5.8 审批与沙箱（Policy / Sandbox）

| 预设 | 沙箱 | 审批 |
|---|---|---|
| read-only | 只读 | 问 |
| workspace-write（现在用的） | 只许写工作区 + 私有临时目录 | 越界才问 |
| danger-full-access | 不限 | 不问 |

- 审批只有「允许一次」和「拒绝」，没有「总是允许」；审批请求里不带工具参数
- **插件自己起的子进程默认不进沙箱**，要用 `ctx.sandbox.confine(argv, policy)` 显式包一层（我们实测过：两个 Python 环境包进去都能跑）
- 沙箱只管写：读和联网不受限

### 5.9 网页界面（Web Client）

- 插件的网页那一半写在同一个包里（`package.json` 的 `dsh.client` + `client.js`），用「插槽」（slots）登记 React 组件；右侧栏可以加页签
- 交付文件：`present` 工具 → 回复下面出一张文件卡片（预览、用默认程序打开、在资源管理器里显示）
- 预览：`.svp` 会当纯文本 JSON 显示；**音频不能播**（wav / mp3 等在「无法预览」清单里）—— 要试听得自己写一个预览器（`ctx.documentPreviews.register`）

### 5.10 从界面上直接看到的（「轨迹」页）

```
 系统提示词（约 5,900 字）── 一段段拼出来：每个工具贡献一句自己的用法；
 │                         再加「DSH 本体装在哪」「你在网页界面里」「工作目录是哪」
 工具说明（26 个）───────── ask_user_question · read / write / edit · glob / grep · pwsh · read_image ·
 │                         job_list / job_output / job_kill · subagent / subagent_fork / send_message /
 │                         list_agents / interrupt_agent · workflow · skill · present · todo_write ·
 │                         create_goal / get_goal / update_goal · exit_plan_mode · web_search / web_fetch
 第 1 轮
   用户消息
   上下文 ① 运行时快照：「文件策略 workspace-write，可以改工作区 E:\sv-agent-workspace 下的文件；审批策略 ask」
   上下文 ② <system-reminder> 可用技能清单（现在只有 diagnose-windows-sandbox-acl）
   助手 → 工具调用 → 工具结果 → …… → 助手回答
```

## 6. 对阶段 1–4 意味着什么

| 阶段 | 用 DSH 的哪块 | 我们写什么 | 要注意 |
|---|---|---|---|
| 1 Project 插件 | `ctx.systemPrompt.context()` 每步给模型一小段「当前项目」；项目数据存 `ctx.storageDomain`；一个打开 / 切换项目的工具 | 一个 bundle（本地目录，`dsh plugin --profile web add <目录>` 装），挂进「SV 创作」预设 | 那一小段要短（16k）；不碰系统提示词（缓存）；项目目录放在工作区里（沙箱只许写这里） |
| 2 Artifact 插件 | 工具 + `ctx.storageDomain`；交付用 `present` 卡片 | 登记 wav / mid / svp / 歌词和它们的版本；**不覆盖你改过的文件**（新版本另存） | 网页里 `.svp` 只当 JSON 文本显示、音频不能播 → 要试听得写预览器（以后） |
| 3 Cover Skill | `SKILL.md`（流程说明）+ 插件工具：`ctx.jobs.start` 后台跑、`ctx.sandbox.confine` 包进沙箱 | `cover_run`：调现有 Python 链路，产物写项目目录，报进度 | 分离在 CPU 上约 25 分钟 → 必须后台任务；DSH 一退出任务就没了；链路要改成写工作区 |
| 4 对话里真调 | `present` 交付 `.svp` | 端到端：「翻唱这首」→ 后台跑 → 文件卡片 → 用 SV 打开 | 本地模型约 8 tok/s：一个工具包住整条链路，比让模型自己一条条拼命令可靠、省上下文 |

- **Cover Skill 可以在沙箱里跑**（第 3 节实测）：产物写进工作区里的项目目录（以前写 `E:\sv-agent-data\probes`，沙箱里写不了），模型文件只读就行
- 沙箱里的程序不能用管道接别的程序的输出（`pwsh` 工具说明写明会 EPERM）—— 我们的链路现在没这么用；以后加 ffmpeg 之类的要留意
- 备选（不写代码）：只写一份 `SKILL.md`，让模型用沙箱里的 `pwsh` 加 `run_in_background` 跑链路 —— 能跑，但每一步都靠本地模型拼命令、日志进上下文，16k 下不稳；先不走这条
- 插件以你的权限、在 DSH 进程里运行（不进沙箱）→ 插件里启动 Python 时要自己用 `ctx.sandbox.confine` 包进去

## 7. 数字

| 轮 | 步数 | 用时 | 处理 token | 出字 | 缓存命中 | 上下文占用 |
|---|---|---|---|---|---|---|
| 第一轮（列空目录） | 2 | 37 秒 | 14.8K | 7.2 tok/s | 50% | 45% |
| 第二轮（权限出错，被我停掉） | 8 | 约 4 分半 | 55.3K | 7.9 tok/s | 96% | 58% |
| 第三轮（沙箱复测） | 4 | 1 分 28 秒 | 30.8K | 7.1 tok/s | 75% | 49% |
| 「SV 创作」：只回一个字 | 1 | 10 秒 | 4.5K | 13 tok/s | 0%（新前缀） | 28% |
| 「SV 创作」：一句话说明工具 | 1 | 15 秒 | 4.6K | 7.3 tok/s | 92%（复用上一个会话的前缀） | 28% |
| 「SV 创作」：`/compact` | — | 41 秒 / 49 秒 | — | — | — | 27–28% |

- 新会话起手：原装预设约 7.4K token（45%）→「SV 创作」约 4.5K（28%）；开始压缩的线约 11.3K
- 模型服务加载 9–12 秒；常驻私有内存约 11.4 GB；开着时整机可用内存 0.5–1.5 GB（关掉后 14–15 GB）

## 8. 还没定的事

| 事 | 现在 | 谁定 |
|---|---|---|
| 上下文不够时用什么 | **DeepSeek 接口**（你 10-01 定，不用 Mistral）；我先前的补丁把模型配置整块换成只有本地，所以接回 DeepSeek 要在补丁里重新加上它 | 你开账号、自己设 `DEEPSEEK_API_KEY`（我不碰密钥）；我配补丁、定哪些活走它。用它时对话内容（含工具读到的文件、歌词）会发到 DeepSeek 的服务器 |
| 联网工具 | 「SV 创作」里没放：`web_search` 走 DeepSeek 在线接口（接上密钥就能用）；`web_fetch` 能从本机抓任意网址（网页里的文字可能夹带指令） | 你定：要的话一句话加回来 |
| 内存 | 模型开着整机可用约 0.5–1.5 GB | 我：不用就关，要用 12 秒起来；你觉得卡就说 |
| 预设开头那句 | 还是原装的「You are a coding agent…」 | 我：阶段 1 改成创作助手的说法 |
| 默认工作区 | `C:\Users\admin\Documents\deepseek-harness\default-workspace`：空，带常驻权限标记 | 你删（可选） |
| 重复下载的 llama.cpp | `E:\sv-agent-data\tools\llama.cpp-b11259-cuda13.4`（711 MB）、`E:\sv-agent-data\tools\downloads`（550 MB）；在用的是 `...\llama.cpp-b11259-cuda` | 你删（可选） |
