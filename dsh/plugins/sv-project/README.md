# sv-project · Project 插件（v3 阶段 1）

让 DSH 里的 Agent 知道**现在在做哪首歌、做到哪了**。

创作者 10-01 定：**一首歌 = DSH 的一个工作区**。每首歌一个文件夹 `E:\sv-agent-workspace\<歌名>\`，里面一份 `sv-project.json`；
DSH 侧栏按工作区分组 → 一首歌一组；在哪首歌下面开会话，Agent 就在做哪首；沙箱只许写这首歌的文件夹。
项目根 `E:\sv-agent-workspace` 本身是「大厅」，不属于任何一首歌。

## 它做什么

| | 怎么做 | 为什么这么做 |
|---|---|---|
| 每一步给模型一小段「当前项目」 | `ctx.systemPrompt.context()`：歌名、类型、可写文件夹、状态、外部素材、项目里每类文件几个、最新工程；在大厅里列出项目名 | 运行时上下文追加在历史后面，不碰系统提示词 → 模型服务的缓存前缀不作废；没变化时一字不差，DSH 就不重复追加 |
| `project_list` | 列出所有项目（名字、翻唱 / 原创、状态、文件夹） | |
| `project_status` | 当前项目的详情：来源、状态、每类文件几个和最新的是哪个、外部素材（找不到的会标出来）、备注 | 每一步那一小段要短（16k 上下文），细节按需查 |
| `project_create` | 新建：建文件夹 + `sv-project.json` + 登记成工作区（`workspaceRegistry.create`）→ 侧栏里出现；同名文件夹里已有 `sv-project.json` 就只登记、不改内容（认领） | 不用你手动去点「添加工作区」 |
| `project_update` | 改状态、来源，或追加一条带时间的备注（只改 `sv-project.json`） | 让 JSON 一直是合法的，不靠模型手改 |

## `sv-project.json`

```json
{
  "schema": "sv-agent/project@1",
  "name": "天星问",
  "kind": "cover",
  "created": "2026-10-01 14:05",
  "updated": "2026-10-01 14:05",
  "source": "来源说明（链接、Suno 分轨、本地文件……）",
  "status": "一句话状态",
  "external": [{ "label": "各版工程", "path": "E:\\sv-agent-data\\probes\\...\\rounds_天星问" }],
  "notes": ["带时间的备注"]
}
```

- `kind`：`cover` 翻唱 / `original` 原创
- `external`：项目文件夹外面的素材（**只读引用**，不搬不复制）—— M1 做过的 5 首，原来的探针文件都留在原处
- 清点文件时不进 `.`、`_`、`弃用` 开头的文件夹，往下最多 3 层、最多 2000 个条目

## 怎么挂的

本机没有 pnpm，所以不走 `dsh plugin add`：插件只用 Node 自带模块（不 import DSH 的包），
在配置档补丁（`E:\sv-agent-data\dsh-home\profiles\web\cordis.patch.yml`，副本见 `../../profile-web.cordis.patch.yml`）里用绝对路径挂成全局一行：

```yaml
- insert:
    - id: sv-project
      name: E:/sv-bridge/dsh/plugins/sv-project/index.js
      config:
        root: E:/sv-agent-workspace
```

工具对象照 `dsh-tools` 的 `defineTool` 生成的形状手写（参数 / 输出都是 JSON Schema，`execute` 返回字符串）；参数类型自己校验。
插件在 DSH 进程里、以创作者的权限运行（不进沙箱）→ 只往项目根下面写，歌名严格检查（不能带路径符号、不能以 `.` `_` `弃用` 开头）。
改了 `index.js` 要重启 DSH（DSH 只热重载补丁文件，不看插件源码）。

## 自检

```
node test.mjs
```

在临时目录里搭一个项目根，测纯逻辑，再用假的 `ctx` 调四个工具；写出来的 JSON 另外直接读回核对。
10-01 故意改坏两处验证测试会响：「在根下面」只比前缀（`E:\ws2` 被当成在 `E:\ws` 下面）→ 2 项没过；清点不跳过弃用文件夹 → 3 项没过。
