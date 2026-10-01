// SV-Agent · Artifact 插件（v3 阶段 2，2026-10-01）
//
// 管每首歌的版本，保证不覆盖创作者改过的文件。创作者 10-01 定：「自动备份 + 拦住覆盖」；试听先不做（放到阶段 5）。
//
//   项目文件夹（sv-project 插件管的那个）里一版一个 rNN\ 文件夹（和 M1 一样）；弃用的改名「弃用_rNN…」，不删
//   artifact_new_version → 建下一个 rNN\，Agent / 以后的 Cover Skill 往里写
//   artifact_seal        → 交付：记下这一版每个文件的指纹（sha256）= 交给创作者时的样子
//   之后创作者在 SV 里改了存盘（指纹变了）或在这一版里另存了新文件 → 马上拷一份到快照库（工作区外面，Agent 的沙箱写不进去），清单里记下
//   Agent 用 write / edit 碰已交付版本里的任何文件 → 直接拒绝（另开一版）
//   清单也放在快照库里（Agent 改不了）：<store>\<歌名>\artifacts.json，快照在 <store>\<歌名>\快照\rNN\
//
// pwsh 跑的是任意命令，拦不住 → 真正的保险是快照（改动一出现就拷走）；DSH 关着时的改动，下次启动时补查。
// 只用 Node 自带模块 + 同仓库的 sv-project（判断「这个目录属于哪个项目」用它测过的函数）。
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, watch, writeFileSync } from 'node:fs'
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from 'node:path'
import { listProjects, projectDirOf } from '../sv-project/index.js'

export const name = 'sv-artifact'
export const inject = ['tools', 'systemPrompt']

const MANIFEST = 'artifacts.json'
const SCHEMA = 'sv-agent/artifacts@1'
const VERSION_DIR = /^r(\d{2,})$/
const DISCARDED_DIR = /^弃用_r(\d{2,})/
const SNAPSHOT_MAX = 50 * 1024 * 1024        // 单个文件超过 50 MB 只记、不拷（版本里通常只有工程、MIDI、说明，几百 KB）
const DEBOUNCE_MS = 2000                       // SV 存盘会连写几次：最后一次动静之后 2 秒再查
const FILES_MAX = 500                          // 一版最多记 500 个文件

const pad = (x, n = 2) => String(x).padStart(n, '0')
const stamp = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
const fileStamp = (d = new Date()) => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
const key = (p) => resolve(p).toLowerCase()
const inside = (p, dir) => { const a = key(p); const b = key(dir).replace(/[\\/]+$/, ''); return a === b || a.startsWith(b + '\\') || a.startsWith(b + '/') }
const sha256 = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')
const relp = (p, base) => relative(base, p).split('\\').join('/')   // 清单里统一用 / 分隔

// ---------------------------------------------------------------- 清单

export function storeDir(store, projectDir) { return join(store, basename(projectDir)) }

export function readManifest(store, projectDir) {
  const file = join(storeDir(store, projectDir), MANIFEST)
  if (!existsSync(file)) return { schema: SCHEMA, project: basename(projectDir), versions: [], edits: [] }
  const m = JSON.parse(readFileSync(file, 'utf8'))
  m.versions ??= []
  m.edits ??= []
  return m
}

export function writeManifest(store, projectDir, m) {
  const dir = storeDir(store, projectDir)
  mkdirSync(dir, { recursive: true })
  const file = join(dir, MANIFEST)
  writeFileSync(`${file}.tmp`, JSON.stringify(m, null, 2) + '\n', 'utf8')
  renameSync(`${file}.tmp`, file)
}

// ---------------------------------------------------------------- 版本

/** 下一版编号：看项目文件夹里的 rNN / 弃用_rNN 和清单里记过的，取最大 + 1（弃用的号也不复用）。 */
export function nextVersionId(projectDir, m) {
  let max = 0
  for (const e of readdirSync(projectDir, { withFileTypes: true })) {
    if (!e.isDirectory()) continue
    const hit = VERSION_DIR.exec(e.name) ?? DISCARDED_DIR.exec(e.name)
    if (hit) max = Math.max(max, Number(hit[1]))
  }
  for (const v of m.versions) { const hit = /^r(\d+)$/.exec(v.id); if (hit) max = Math.max(max, Number(hit[1])) }
  return `r${pad(max + 1)}`
}

/** 一版文件夹里的所有文件（相对项目文件夹、/ 分隔），跳过 .tmp。 */
export function versionFiles(projectDir, folder) {
  const out = []
  const walk = (d) => {
    let entries
    try { entries = readdirSync(d, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      if (out.length >= FILES_MAX) return
      const p = join(d, e.name)
      if (e.isDirectory()) walk(p)
      else if (e.isFile() && !e.name.endsWith('.tmp')) out.push(relp(p, projectDir))
    }
  }
  walk(join(projectDir, folder))
  return out.sort()
}

const liveVersion = (m, id) => m.versions.find((v) => v.id === id && !v.discarded)

/** 交付：记下这一版每个文件的指纹。 */
export function sealVersion(projectDir, m, id, note) {
  const v = liveVersion(m, id)
  if (!v) throw new Error(`没有进行中的 ${id}（用 artifact_list 看有哪几版）`)
  if (v.sealed) throw new Error(`${id} 已经在 ${v.sealed} 交付过了；要改就另开一版`)
  const files = versionFiles(projectDir, v.folder)
  if (files.length === 0) throw new Error(`${id} 里还没有文件`)
  v.files = Object.fromEntries(files.map((f) => {
    const p = join(projectDir, f)
    return [f, { sha256: sha256(p), size: statSync(p).size }]
  }))
  v.sealed = stamp()
  if (note) v.sealNote = note
  return files
}

/** 这个路径是不是在已交付（没弃用）的某一版里：是就返回拒绝的理由。 */
export function protectedReason(absPath, projectDir, m) {
  for (const v of m.versions) {
    if (!v.sealed || v.discarded) continue
    const folder = join(projectDir, v.folder)
    if (inside(absPath, folder)) {
      const edited = m.edits.some((e) => e.version === v.id)
      return `${v.id} 已经在 ${v.sealed} 交付给创作者${edited ? '，创作者还改过' : ''}，里面的文件不能覆盖、修改，也不能往里加；`
        + '要改就用 artifact_new_version 另开一版，在新版本里写'
    }
  }
  return undefined
}

// ---------------------------------------------------------------- 查创作者的改动 + 快照

const lastEdit = (m, version, file) => [...m.edits].reverse().find((e) => e.version === version && e.file === file)

function snapshot(store, projectDir, version, file, abs, now) {
  const size = statSync(abs).size
  if (size > SNAPSHOT_MAX) return { snapshot: null, note: `文件 ${Math.round(size / 1048576)} MB，超过 50 MB 只记不拷` }
  const ext = extname(file)
  const flat = file.slice(version.folder.length + 1).split('/').join('__')
  const base = flat.slice(0, flat.length - ext.length)
  const dir = join(storeDir(store, projectDir), '快照', version.id)
  mkdirSync(dir, { recursive: true })
  const target = join(dir, `${base}_作者改_${fileStamp(now)}${ext}`)
  copyFileSync(abs, target)
  return { snapshot: target }
}

/** 查已交付的每一版：文件变了 / 多了 / 没了 → 记下来；变了和多了的拷进快照库。返回这次新记的条目。 */
export function checkSealed(store, projectDir, m, now = new Date()) {
  const found = []
  for (const v of m.versions) {
    if (!v.sealed || v.discarded) continue
    const current = new Set(versionFiles(projectDir, v.folder))
    // 要看的文件：交付时的 + 以后记过的（创作者另存的）+ 现在在的
    const files = new Set([...Object.keys(v.files ?? {}), ...m.edits.filter((e) => e.version === v.id).map((e) => e.file), ...current])
    for (const file of files) {
      const abs = join(projectDir, file)
      const base = v.files?.[file]                 // 交付时的指纹；创作者另存的文件没有
      const prev = lastEdit(m, v.id, file)         // 上一次记下的改动
      if (!current.has(file)) {
        if (prev?.kind !== 'missing') found.push({ version: v.id, file, kind: 'missing', detected: stamp(now) })
        continue
      }
      let hash
      try { hash = sha256(abs) } catch { continue }   // 正被 SV 占着写：下次再查
      // 上一次已知的样子：没记过改动 → 交付时的；上次记的是「没了」→ 不知道（一定要记）；否则 → 上次记的
      const last = prev === undefined ? base?.sha256 : prev.kind === 'missing' ? undefined : prev.sha256
      if (hash === last) continue
      if (prev?.kind === 'missing' && base !== undefined && hash === base.sha256) {
        found.push({ version: v.id, file, kind: 'back', sha256: hash, detected: stamp(now) })   // 原样放回来了：不用再拷
        continue
      }
      const kind = base === undefined && (prev === undefined || prev.kind === 'missing') ? 'added' : 'changed'
      found.push({ version: v.id, file, kind, sha256: hash, detected: stamp(now), ...snapshot(store, projectDir, v, file, abs, now) })
    }
  }
  m.edits.push(...found)
  return found
}

// ---------------------------------------------------------------- 给模型看的

const KIND_TEXT = { changed: '改了', added: '新加了', missing: '挪走 / 删了', back: '又放回来了' }

/** 每一步那一小段：最近 3 版的状态（要短、要稳）。 */
export function artifactContext(m) {
  const live = m.versions.filter((v) => !v.discarded)
  const discarded = m.versions.length - live.length
  if (live.length === 0) {
    return `版本：${discarded > 0 ? `只有弃用的 ${discarded} 版` : '还没有'}。新一版用 artifact_new_version（建 rNN 文件夹），做完用 artifact_seal 交付。`
  }
  const items = live.slice(-3).reverse().map((v) => {
    if (!v.sealed) return `${v.id} 进行中`
    const n = m.edits.filter((e) => e.version === v.id && e.kind !== 'back').length
    return `${v.id} 已交付${n > 0 ? `（创作者动过 ${n} 处，快照已存）` : ''}`
  })
  const older = live.length > 3 ? `；更早的 ${live.length - 3} 版` : ''
  return `版本：${items.join('；')}${older}${discarded > 0 ? `；弃用 ${discarded} 版` : ''}。已交付的版本不能改、不能往里写，要改就另开一版。`
}

export function listText(projectDir, m) {
  if (m.versions.length === 0) return `《${basename(projectDir)}》还没有版本`
  const lines = [`《${basename(projectDir)}》的版本（${projectDir}）：`]
  for (const v of m.versions) {
    const state = v.discarded ? `弃用（${v.discarded.reason}）→ ${v.discarded.folder}` : v.sealed ? `${v.sealed} 交付` : '进行中'
    lines.push(`- ${v.id}：${state}；${v.created} 建${v.note ? `，${v.note}` : ''}`)
    const files = Object.keys(v.files ?? {})
    if (files.length > 0) lines.push(`  交付时的文件：${files.slice(0, 8).join('、')}${files.length > 8 ? ` 等 ${files.length} 个` : ''}`)
    for (const e of m.edits.filter((x) => x.version === v.id)) {
      lines.push(`  ${e.detected} 创作者${KIND_TEXT[e.kind]} ${e.file}${e.snapshot ? `；快照 ${e.snapshot}` : e.note ? `；${e.note}` : ''}`)
    }
  }
  return lines.join('\n')
}

// ---------------------------------------------------------------- 插件

const text = (s) => [{ type: 'text', text: s }]
const stringTool = (def) => ({ ...def, output: { schema: { type: 'string' }, render: (_args, value) => text(value) } })
const optString = (args, k) => {
  const v = args?.[k]
  if (v === undefined || v === null) return undefined
  if (typeof v !== 'string') throw new Error(`${k} 要是字符串`)
  return v.trim() === '' ? undefined : v.trim()
}

export function apply(ctx, config) {
  const { root, store } = config ?? {}
  if (typeof root !== 'string' || !isAbsolute(root)) throw new Error('sv-artifact：config.root 要写项目根目录的绝对路径')
  if (typeof store !== 'string' || !isAbsolute(store)) throw new Error('sv-artifact：config.store 要写快照库的绝对路径（要在工作区外面）')
  const ROOT = resolve(root)
  const STORE = resolve(store)
  if (inside(STORE, ROOT)) throw new Error('sv-artifact：快照库不能放在项目根下面（Agent 的沙箱能写那里）')
  mkdirSync(STORE, { recursive: true })

  const projectOf = (exec) => {
    const dir = projectDirOf(exec?.agent?.session?.header?.cwd, ROOT)
    if (dir === null) throw new Error('这个会话不在任何项目里；请在侧栏那首歌下面开会话')
    return dir
  }
  const check = (projectDir) => {
    const m = readManifest(STORE, projectDir)
    if (!m.versions.some((v) => v.sealed && !v.discarded)) return []
    const found = checkSealed(STORE, projectDir, m)
    if (found.length > 0) writeManifest(STORE, projectDir, m)
    return found
  }

  // DSH 关着时创作者改过的：启动时补查一遍
  for (const { dir } of listProjects(ROOT)) { try { check(dir) } catch { /* 坏清单：工具调用时再报 */ } }

  // 盯着整个项目根：已交付版本里有动静 → 2 秒后查这个项目
  ctx.effect(() => {
    const timers = new Map()
    let watcher
    try {
      watcher = watch(ROOT, { recursive: true }, (_event, filename) => {
        if (typeof filename !== 'string' || filename.endsWith('.tmp')) return
        const dir = projectDirOf(dirname(join(ROOT, filename)), ROOT)
        if (dir === null) return
        clearTimeout(timers.get(dir))
        timers.set(dir, setTimeout(() => { timers.delete(dir); try { check(dir) } catch { /* 下次再查 */ } }, DEBOUNCE_MS))
      })
    } catch { /* 盯不了就只在启动和工具调用时查 */ }
    return () => { watcher?.close(); for (const t of timers.values()) clearTimeout(t) }
  })

  ctx.systemPrompt.context({
    name: 'sv:artifacts',
    order: 310,
    text: (context) => {
      try {
        const dir = projectDirOf(context?.agent?.session?.header?.cwd, ROOT)
        return dir === null ? '' : artifactContext(readManifest(STORE, dir))
      } catch { return '' }
    },
  })

  // Agent 用 write / edit 碰已交付版本 → 拒绝
  ctx.tools.guard((exec) => {
    if (exec.name !== 'write' && exec.name !== 'edit') return undefined
    const p = exec.arguments?.file_path
    if (typeof p !== 'string' || p === '') return undefined
    const cwd = exec.agent?.session?.header?.cwd
    const abs = isAbsolute(p) ? resolve(p) : resolve(cwd ?? ROOT, p)
    const dir = projectDirOf(dirname(abs), ROOT)
    if (dir === null) return undefined
    try { return protectedReason(abs, dir, readManifest(STORE, dir)) } catch { return undefined }
  })

  ctx.tools.register(stringTool({
    name: 'artifact_list',
    description: '列出当前项目的所有版本：进行中 / 已交付 / 弃用，交付时的文件，创作者后来改了什么、快照存在哪。',
    parameters: { type: 'object', properties: {} },
    async execute(_args, exec) {
      const dir = projectOf(exec)
      check(dir)
      return listText(dir, readManifest(STORE, dir))
    },
  }))

  ctx.tools.register(stringTool({
    name: 'artifact_new_version',
    description: '在当前项目里开新的一版：建下一个 rNN 文件夹（r01、r02……），之后这一版的工程、MIDI、说明都写进去。返回文件夹路径和命名建议。',
    parameters: { type: 'object', properties: { note: { type: 'string', description: '这一版要做什么，一句话' } } },
    async execute(args, exec) {
      const dir = projectOf(exec)
      const note = optString(args, 'note')
      const m = readManifest(STORE, dir)
      const id = nextVersionId(dir, m)
      mkdirSync(join(dir, id))
      m.versions.push({ id, folder: id, created: stamp(), by: 'agent', ...(note ? { note } : {}), sealed: null, files: {}, discarded: null })
      writeManifest(STORE, dir, m)
      return `开了 ${id}：${join(dir, id)}\n文件名建议：${basename(dir)}_<内容>_${id}.svp（例如 ${basename(dir)}_扒谱_${id}.svp）；做完用 artifact_seal 交付。`
    },
  }))

  ctx.tools.register(stringTool({
    name: 'artifact_seal',
    description: '交付一版：记下这一版每个文件的指纹（交给创作者时的样子）。交付以后这一版不能再改、不能往里写；创作者之后改了会自动备份到快照库。',
    parameters: {
      type: 'object',
      properties: {
        version: { type: 'string', description: '版本号，例如 r03' },
        note: { type: 'string', description: '交付说明，可省' },
      },
      required: ['version'],
    },
    async execute(args, exec) {
      const dir = projectOf(exec)
      const id = optString(args, 'version')
      if (!id) throw new Error('要写 version，例如 r03')
      const m = readManifest(STORE, dir)
      const files = sealVersion(dir, m, id, optString(args, 'note'))
      writeManifest(STORE, dir, m)
      return `${id} 交付了，${files.length} 个文件：${files.slice(0, 8).join('、')}${files.length > 8 ? ' 等' : ''}。`
    },
  }))

  ctx.tools.register(stringTool({
    name: 'artifact_discard',
    description: '弃用一版：把 rNN 文件夹改名成「弃用_rNN（原因）」，不删任何文件；编号不会再用。',
    parameters: {
      type: 'object',
      properties: {
        version: { type: 'string', description: '版本号，例如 r03' },
        reason: { type: 'string', description: '为什么弃用，一句话（会写进文件夹名）' },
      },
      required: ['version', 'reason'],
    },
    async execute(args, exec) {
      const dir = projectOf(exec)
      const id = optString(args, 'version')
      const reason = optString(args, 'reason')
      if (!id || !reason) throw new Error('要写 version 和 reason')
      if (/[<>:"/\\|?*]/.test(reason)) throw new Error('reason 里不能有 < > : " / \\ | ? *（要写进文件夹名）')
      const m = readManifest(STORE, dir)
      const v = liveVersion(m, id)
      if (!v) throw new Error(`没有可以弃用的 ${id}`)
      check(dir)   // 改名前先把创作者的改动备份下来
      const folder = `弃用_${id}（${reason.slice(0, 40)}）`
      renameSync(join(dir, v.folder), join(dir, folder))
      const m2 = readManifest(STORE, dir)
      const v2 = liveVersion(m2, id)
      v2.discarded = { at: stamp(), reason, folder }
      writeManifest(STORE, dir, m2)
      return `${id} 弃用了：${join(dir, folder)}（文件都还在）`
    },
  }))
}
