// SV-Agent · Project 插件（v3 阶段 1，2026-10-01）
//
// 一首歌 = DSH 的一个工作区（创作者 10-01 定：「一首歌一个工作区」）：文件夹 <root>\<歌名>\，里面一份 sv-project.json。
// 这个插件做三件事：
//   ① 每一步给模型一小段「当前项目」—— 用运行时上下文（systemPrompt.context），追加在历史后面、不碰系统提示词（不破坏缓存前缀）
//   ② 工具：project_list / project_status / project_create / project_update
//   ③ 新建（或认领已有的）项目时登记成 DSH 工作区（workspaceRegistry.create）→ 侧栏里马上出现
//
// 只用 Node 自带模块：本机没有 pnpm，插件用绝对路径挂在配置档补丁里，从外部目录 import DSH 的包不保证能解析。
// 工具对象照 dsh-tools 的 defineTool 生成的形状手写（参数 / 输出都是 JSON Schema，execute 返回字符串）。
// 插件在 DSH 进程里、以创作者的权限运行（不进沙箱）→ 只往 <root> 下面写，名字严格检查。
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'

export const name = 'sv-project'
export const inject = ['tools', 'systemPrompt', 'workspaceRegistry']

const PROJECT_FILE = 'sv-project.json'
const SCHEMA = 'sv-agent/project@1'
const SKIP_DIR = /^(\.|_|弃用)/              // 隐藏的、下划线开头的、「弃用…」的文件夹不清点、不算项目
const SCAN_DEPTH = 3                          // 项目文件夹往下最多看 3 层
const SCAN_LIMIT = 2000                       // 最多看 2000 个条目（每一步都要算，不能慢）
const LOBBY_LIST = 12                         // 大厅里最多列 12 个项目名
const KINDS = { cover: '翻唱', original: '原创' }
const CATEGORIES = [
  ['工程', (n) => /\.svpk?$/i.test(n)],
  ['MIDI', (n) => /\.midi?$/i.test(n)],
  ['音频', (n) => /\.(wav|mp3|m4a|flac|ogg|aac|opus)$/i.test(n)],
  ['歌词', (n) => /\.lrc$/i.test(n) || (/\.txt$/i.test(n) && /歌词|lyric/i.test(n))],
]
const BAD_NAME = /[<>:"/\\|?*\u0000-\u001f]/

const same = (a, b) => resolve(a).toLowerCase() === resolve(b).toLowerCase()   // Windows 路径不分大小写
/** p 是不是 top 本身或在它下面（按路径分隔符判断：E:\ws2 不算在 E:\ws 下面）。 */
const under = (p, top) => {
  const a = resolve(p).toLowerCase()
  const b = resolve(top).toLowerCase().replace(/[\\/]+$/, '')
  return a === b || a.startsWith(b + '\\') || a.startsWith(b + '/')
}
/** 没用 defineTool，参数校验自己做：给了就必须是字符串。 */
const optString = (args, key) => {
  const v = args?.[key]
  if (v === undefined || v === null) return undefined
  if (typeof v !== 'string') throw new Error(`${key} 要是字符串`)
  return v.trim() === '' ? undefined : v.trim()
}
const stamp = (d = new Date()) => {
  const p = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 歌名能不能当文件夹名：不能有路径符号、不能以 . _ 弃用 开头、不能太长；返回错误说明或 null。 */
export function nameProblem(n) {
  if (typeof n !== 'string' || n.trim() === '') return '歌名不能为空'
  const t = n.trim()
  if (t !== n) return '歌名前后不能有空格'
  if (BAD_NAME.test(t)) return '歌名里不能有 < > : " / \\ | ? * 这些字符'
  if (SKIP_DIR.test(t)) return '歌名不能以 . _ 或「弃用」开头（这些文件夹不算项目）'
  if (/[. ]$/.test(t)) return '歌名不能以点或空格结尾'
  if (/^(con|prn|aux|nul|com\d|lpt\d)$/i.test(t)) return '这个名字是 Windows 保留名'
  if ([...t].length > 60) return '歌名太长（最多 60 个字）'
  return null
}

/** 读一个项目文件；不是项目返回 null，坏了返回 { error }。 */
export function readProject(dir) {
  const file = join(dir, PROJECT_FILE)
  if (!existsSync(file)) return null
  try {
    const data = JSON.parse(readFileSync(file, 'utf8'))
    if (typeof data?.name !== 'string' || !(data.kind in KINDS)) return { error: `${PROJECT_FILE} 缺 name 或 kind 不对（cover / original）` }
    return data
  } catch (e) {
    return { error: `${PROJECT_FILE} 读不了：${e.message}` }
  }
}

/** 先写临时文件再改名，写一半出错不会留下半个 JSON。 */
export function writeProject(dir, data) {
  const file = join(dir, PROJECT_FILE)
  const tmp = `${file}.tmp`
  writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n', 'utf8')
  renameSync(tmp, file)
}

/** 会话工作目录属于哪个项目：从 cwd 往上找 sv-project.json，到 root 为止（root 本身是大厅，不是项目）。 */
export function projectDirOf(cwd, root) {
  if (typeof cwd !== 'string' || cwd === '') return null
  let dir = resolve(cwd)
  const top = resolve(root)
  if (!under(dir, top)) return null
  while (!same(dir, top)) {
    if (existsSync(join(dir, PROJECT_FILE))) return dir
    const up = dirname(dir)
    if (up === dir) return null
    dir = up
  }
  return null
}

/** root 下面一层里所有项目（按名字排）。 */
export function listProjects(root) {
  if (!existsSync(root)) return []
  const out = []
  for (const e of readdirSync(root, { withFileTypes: true })) {
    if (!e.isDirectory() || SKIP_DIR.test(e.name)) continue
    const dir = join(root, e.name)
    const data = readProject(dir)
    if (data !== null) out.push({ dir, data })
  }
  return out.sort((a, b) => a.dir.localeCompare(b.dir, 'zh'))
}

/** 清点项目文件夹：每类几个、每类最新的是哪个（不进 . _ 弃用 开头的文件夹）。 */
export function inventory(dir) {
  const counts = Object.fromEntries([...CATEGORIES.map(([c]) => c), '其他'].map((c) => [c, 0]))
  const newest = {}
  let seen = 0
  let truncated = false
  const walk = (d, depth) => {
    let entries
    try { entries = readdirSync(d, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      if (seen >= SCAN_LIMIT) { truncated = true; return }
      seen += 1
      const p = join(d, e.name)
      if (e.isDirectory()) {
        if (!SKIP_DIR.test(e.name) && depth < SCAN_DEPTH) walk(p, depth + 1)
        continue
      }
      if (!e.isFile() || (depth === 1 && e.name === PROJECT_FILE) || e.name.endsWith('.tmp')) continue
      const cat = (CATEGORIES.find(([, test]) => test(e.name)) ?? ['其他'])[0]
      counts[cat] += 1
      let mtime = 0
      try { mtime = statSync(p).mtimeMs } catch { /* 刚被挪走 */ }
      if (newest[cat] === undefined || mtime > newest[cat].mtime) newest[cat] = { path: p, mtime }
    }
  }
  walk(dir, 1)
  return { counts, newest, truncated }
}

const rel = (p, dir) => (under(p, dir) ? resolve(p).slice(resolve(dir).length).replace(/^[\\/]/, '') : p)

/** 每一步给模型的那一小段（要短、要稳：没变化就一字不差，DSH 只在内容变了时才追加新的一条）。 */
export function contextText(cwd, root) {
  if (typeof cwd !== 'string' || cwd === '') return ''
  if (same(cwd, root)) {
    const projects = listProjects(root)
    const names = projects.slice(0, LOBBY_LIST).map(({ data }) => (data.error ? '（坏了）' : `${data.name}（${KINDS[data.kind]}）`))
    const more = projects.length > LOBBY_LIST ? ` 等 ${projects.length} 个` : ''
    return [
      `SV 项目大厅（${resolve(root)}）：这里不属于任何一首歌。`,
      projects.length === 0 ? '还没有项目。' : `已有项目 ${projects.length} 个：${names.join('、')}${more}。`,
      '新建或认领项目用 project_create；要做某首歌，请创作者在侧栏那首歌下面开新会话。',
    ].join('\n')
  }
  const dir = projectDirOf(cwd, root)
  if (dir === null) return ''
  const data = readProject(dir)
  if (data === null) return ''
  if (data.error) return `SV 项目文件夹 ${dir}：${data.error}`
  const inv = inventory(dir)
  const parts = Object.entries(inv.counts).map(([c, n]) => `${c} ${n}`).join(' · ')
  const latest = inv.newest['工程'] ? `；最新工程 ${rel(inv.newest['工程'].path, dir)}（${stamp(new Date(inv.newest['工程'].mtime))}）` : ''
  const lines = [
    `SV 项目：《${data.name}》（${KINDS[data.kind]}）`,
    `- 文件夹：${dir}（只有这里能写；别覆盖创作者改过的文件，新版本另存新文件）`,
  ]
  if (data.status) lines.push(`- 状态：${data.status}`)
  if (Array.isArray(data.external) && data.external.length > 0) {
    lines.push(`- 外部素材（只读）：${data.external.map((x) => x.label).join('；')}`)   // 名字里常带顿号，用分号隔开
  }
  lines.push(`- 项目文件夹里：${parts}${latest}${inv.truncated ? '（文件太多，只数了前一部分）' : ''}`)
  lines.push('细节用 project_status；记状态 / 备注用 project_update。')
  return lines.join('\n')
}

/** project_status 的完整说明。 */
export function statusText(dir) {
  const data = readProject(dir)
  if (data === null) return `${dir} 不是项目（没有 ${PROJECT_FILE}）`
  if (data.error) return `${dir}：${data.error}`
  const inv = inventory(dir)
  const lines = [`《${data.name}》（${KINDS[data.kind]}）`, `文件夹：${dir}`]
  if (data.created) lines.push(`建于：${data.created}`)
  if (data.updated) lines.push(`最后更新：${data.updated}`)
  if (data.source) lines.push(`来源：${data.source}`)
  if (data.status) lines.push(`状态：${data.status}`)
  lines.push(`文件：${Object.entries(inv.counts).map(([c, n]) => `${c} ${n}`).join(' · ')}${inv.truncated ? '（文件太多，只数了前一部分）' : ''}`)
  for (const [c, x] of Object.entries(inv.newest)) lines.push(`  最新${c}：${rel(x.path, dir)}（${stamp(new Date(x.mtime))}）`)
  if (Array.isArray(data.external) && data.external.length > 0) {
    lines.push('外部素材（只读，不在项目文件夹里）：')
    for (const x of data.external) lines.push(`  - ${x.label}：${x.path}${existsSync(x.path) ? '' : '（找不到了）'}`)
  }
  if (Array.isArray(data.notes) && data.notes.length > 0) {
    lines.push('备注：')
    for (const n of data.notes) lines.push(`  - ${n}`)
  }
  return lines.join('\n')
}

const text = (s) => [{ type: 'text', text: s }]
const stringTool = (def) => ({ ...def, output: { schema: { type: 'string' }, render: (_args, value) => text(value) } })

export const __test = { PROJECT_FILE, SCHEMA, KINDS }

export function apply(ctx, config) {
  const root = config?.root
  if (typeof root !== 'string' || !isAbsolute(root)) throw new Error('sv-project：config.root 要写项目根目录的绝对路径')
  const ROOT = resolve(root)
  if (!existsSync(ROOT)) throw new Error(`sv-project：项目根目录不存在：${ROOT}`)

  const cwdOf = (exec) => exec?.agent?.session?.header?.cwd
  const currentDir = (exec) => {
    const dir = projectDirOf(cwdOf(exec), ROOT)
    if (dir === null) throw new Error('这个会话不在任何项目里（在大厅或别的目录）；请创作者在侧栏那首歌下面开会话，或先用 project_create')
    return dir
  }
  const register = async (dir, title) => {
    try {
      const ws = await ctx.workspaceRegistry.create(dir, title)
      return `已登记成工作区「${ws.title}」，侧栏里能看到`
    } catch (e) {
      return `文件夹有了，但登记到侧栏失败（${e.message}）；可以在侧栏用「添加工作区」手动加 ${dir}`
    }
  }

  ctx.systemPrompt.context({
    name: 'sv:project',
    order: 300,
    text: (context) => {
      try { return contextText(context?.agent?.session?.header?.cwd, ROOT) } catch { return '' }
    },
  })

  ctx.tools.register(stringTool({
    name: 'project_list',
    description: '列出所有 SV 项目（一首歌一个项目）：名字、翻唱还是原创、状态、文件夹。',
    parameters: { type: 'object', properties: {} },
    async execute() {
      const projects = listProjects(ROOT)
      if (projects.length === 0) return `还没有项目（根目录 ${ROOT}）`
      return projects.map(({ dir, data }) => (data.error
        ? `- ${dir}：${data.error}`
        : `- 《${data.name}》（${KINDS[data.kind]}）${data.status ? `：${data.status}` : ''}\n  ${dir}`)).join('\n')
    },
  }))

  ctx.tools.register(stringTool({
    name: 'project_status',
    description: '看当前会话所在项目的详情：来源、状态、项目文件夹里每类文件几个和最新的是哪个、外部素材（只读）、备注。',
    parameters: { type: 'object', properties: {} },
    async execute(_args, exec) {
      return statusText(currentDir(exec))
    },
  }))

  ctx.tools.register(stringTool({
    name: 'project_create',
    description: '新建一个 SV 项目（一首歌）：在项目根目录下建同名文件夹和 sv-project.json，并登记成工作区（侧栏里出现）。'
      + '如果同名文件夹里已经有 sv-project.json，就只登记、不改内容（认领已有项目）。',
    parameters: {
      type: 'object',
      properties: {
        name: { type: 'string', description: '歌名，也是文件夹名' },
        kind: { type: 'string', enum: ['cover', 'original'], description: 'cover = 翻唱，original = 原创；新建时必填，认领已有项目时不用' },
        source: { type: 'string', description: '来源：链接、Suno 分轨、本地文件路径等，可省' },
        note: { type: 'string', description: '一条备注，可省' },
      },
      required: ['name'],
    },
    async execute(args) {
      const problem = nameProblem(args.name)
      if (problem !== null) throw new Error(problem)
      const dir = join(ROOT, args.name)
      if (existsSync(dir)) {
        const data = readProject(dir)
        if (data === null) throw new Error(`文件夹 ${dir} 已经有了，但不是项目（没有 ${PROJECT_FILE}）；换个名字，或请创作者先看看里面是什么`)
        if (data.error) throw new Error(`${dir}：${data.error}`)
        // 只回一句：10-01 实测一次认领 5 首，每首都附上完整详情，16k 上下文一下用掉一半（详情要看用 project_status）
        return `《${data.name}》已经是项目了，内容没动。${await register(dir, data.name)}。`
      }
      const kind = optString(args, 'kind')
      const source = optString(args, 'source')
      const note = optString(args, 'note')
      if (!(kind in KINDS)) throw new Error('新建项目要写 kind：cover（翻唱）或 original（原创）')
      mkdirSync(dir)
      const now = stamp()
      const data = { schema: SCHEMA, name: args.name, kind, created: now, updated: now }
      if (source) data.source = source
      data.status = '刚建'
      data.external = []
      data.notes = note ? [`${now}：${note}`] : []
      writeProject(dir, data)
      return `新建了项目《${args.name}》（${KINDS[kind]}）：${dir}。${await register(dir, args.name)}；要做这首歌，请在侧栏《${args.name}》下面开新会话。`
    },
  }))

  ctx.tools.register(stringTool({
    name: 'project_update',
    description: '更新当前项目的状态、来源，或加一条备注（只改 sv-project.json，不动别的文件）。',
    parameters: {
      type: 'object',
      properties: {
        status: { type: 'string', description: '新的状态，一句话（例如「r02 已交给创作者听」）' },
        source: { type: 'string', description: '新的来源说明' },
        note: { type: 'string', description: '追加一条备注（自动带上时间）' },
      },
    },
    async execute(args, exec) {
      const dir = currentDir(exec)
      const data = readProject(dir)
      if (data === null || data.error) throw new Error(data?.error ?? `${dir} 不是项目`)
      const status = optString(args, 'status')
      const source = optString(args, 'source')
      const note = optString(args, 'note')
      if (!status && !source && !note) throw new Error('status、source、note 至少写一个')
      const now = stamp()
      if (status) data.status = status
      if (source) data.source = source
      if (note) data.notes = [...(Array.isArray(data.notes) ? data.notes : []), `${now}：${note}`]
      data.updated = now
      writeProject(dir, data)
      return `已更新《${data.name}》。\n${statusText(dir)}`
    },
  }))
}
