// SV-Agent · Memory 插件（v3 阶段 6，2026-10-01）
//
// 记创作者的反馈、偏好、历史（PRD §6）。创作者 10-01 定：
//   反馈 —— 自动记原话（他评价某首某一版，Agent 原样存下、告诉他一句；他说「这条不算」就删）
//   偏好 —— Agent 提议、他点头才生效（PRD §6.1 ⑧）
//   以前说过的规矩和评价 —— 导进来（标「导入」），他过一遍再生效
//
//   反馈：原话（原样）+ 来源（歌 / 版本 / 位置 / 时间）+ Agent 的一句理解（他可以改）
//   偏好：以后要照着做的规矩 —— 范围（这首歌 / 所有歌，默认这首歌）、强度（必须 / 尽量）、
//         状态（待确认 / 生效 / 被覆盖 / 已停用 / 已删除）；翻唱时能自动用的（现在只有「挑不挑八度」）由 sv-cover 套用，记下用过哪几次
//   历史：每首做过的版本、设置、评价 —— 版本清单在 sv-artifact、设置在 rNN\song.json，这里只把它们和反馈汇总给模型 / 创作者看
//
// 守 PRD §6.5：创作者说「好」只记成那一版的评价，不会因此变成风格偏好（偏好只能由他点头生效）。
// 当前明确指令优先于历史偏好（PRD §6.2）：翻唱时 Agent 照创作者这次说的传了参数，就不套偏好、只提一句。
// 存放：工作区外面 <store>\全局记忆.json、<store>\<歌名>\记忆.json（Agent 的沙箱写不进去）；
//       给人看的清单：<项目>\记忆.md、<store>\全局记忆.md（每次改动重写；改它不算数 —— 要改跟 Agent 说）
// 原话必须原样：插件拿这个会话最近几条创作者消息对一下，对不上就拒绝（不让模型转述）。
//
// 只用 Node 自带模块 + 同仓库的 sv-project / sv-artifact。
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { basename, dirname, isAbsolute, join, resolve } from 'node:path'
import { projectDirOf } from '../sv-project/index.js'
import { readManifest } from '../sv-artifact/index.js'

export const name = 'sv-memory'
export const inject = ['tools', 'systemPrompt']

const SCHEMA = 'sv-agent/memory@1'
const GLOBAL_FILE = '全局记忆.json'
const SONG_FILE = '记忆.json'
const VIEW = '记忆.md'
const RECENT = 12                      // 对原话：这个会话最近 12 条创作者消息
const CONTEXT_PREFS = 10               // 每步给模型的：生效的全局偏好最多 10 条
const CONTEXT_FEEDBACK = 3             // 这首最近 3 条反馈
const PREF_STATES = ['待确认', '生效', '被覆盖', '已停用', '已删除']
const ACTION_KEYS = { octave_pick: (v) => (v ? '挑八度' : '不挑八度') }

const pad = (x) => String(x).padStart(2, '0')
const stamp = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
const squash = (s) => String(s ?? '').replace(/\s+/g, '').replace(/[“”"]/g, '"').replace(/[‘’']/g, "'")
const short = (s, n = 40) => { const t = String(s ?? '').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n)}…` : t }

// ---------------------------------------------------------------- 文件

export const globalFile = (store) => join(store, GLOBAL_FILE)
export const songFile = (store, projectDir) => join(store, basename(projectDir), SONG_FILE)

export function readMem(file) {
  if (!existsSync(file)) return { schema: SCHEMA, next: 1, entries: [] }
  const m = JSON.parse(readFileSync(file, 'utf8'))
  m.entries ??= []
  m.next ??= m.entries.length + 1
  return m
}

export function writeMem(file, m) {
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(`${file}.tmp`, JSON.stringify(m, null, 2) + '\n', 'utf8')
  renameSync(`${file}.tmp`, file)
}

/** 新的一条：全局的 id 是 g1、g2……，一首歌里的是 s1、s2……（只在这首里唯一）。 */
export function addEntry(m, prefix, entry) {
  const e = { id: `${prefix}${m.next}`, 建于: Date.now(), ...entry, 改动: [{ 时间: entry.来源?.时间 ?? stamp(), 到: entry.状态 }] }
  m.next += 1
  m.entries.push(e)
  return e
}

export function setState(m, id, to, why, now = stamp()) {
  const e = m.entries.find((x) => x.id === id)
  if (!e) throw new Error(`没有 ${id}`)
  const from = e.状态
  if (e.类 === '反馈' && to !== '已删除') throw new Error('反馈只能删（「这条不算」）；要改理解用 understanding')
  if (e.类 === '偏好' && !PREF_STATES.includes(to)) throw new Error(`偏好的状态只能是 ${PREF_STATES.join(' / ')}`)
  e.状态 = to
  e.改动 = [...(e.改动 ?? []), { 时间: now, 从: from, 到: to, 为什么: why }]
  // 同一个范围里、管同一件事（同一个「动作」）的偏好只留一条生效：新的生效 → 旧的「被覆盖」
  if (e.类 === '偏好' && to === '生效' && e.动作) {
    for (const o of m.entries) {
      if (o !== e && o.类 === '偏好' && o.状态 === '生效' && o.动作 && Object.keys(o.动作).some((k) => k in e.动作)) {
        o.状态 = '被覆盖'
        o.改动 = [...(o.改动 ?? []), { 时间: now, 从: '生效', 到: '被覆盖', 为什么: `被 ${e.id} 取代` }]
      }
    }
  }
  return e
}

// ---------------------------------------------------------------- 原话

/** 原话要能在创作者最近的消息里原样找到（去掉空白再比；引号全角半角当一样）。至少 min 个字：
 *  反馈 / 依据默认 2 个字；确认的回答可以只有 1 个字（「嗯」「好」「行」—— 只认提议之后说的，见 memory_confirm）。 */
export function isVerbatim(quote, messages, min = 2) {
  const q = squash(quote)
  if ([...q].length < min) return false
  return messages.some((m) => squash(m).includes(q))
}

// ---------------------------------------------------------------- 翻唱时自动用的（sv-cover 调）

/** 生效的、能自动用的偏好：这首的优先于全局的；同一件事只取一条（最新生效的）。→ [{ key, value, id, scope, label, file }] */
export function coverActions(store, projectDir) {
  const out = new Map()
  const layers = [[globalFile(store), '全局'], [songFile(store, projectDir), '本首']]
  for (const [file, scope] of layers) {
    const m = readMem(file)
    for (const e of m.entries) {
      if (e.类 !== '偏好' || e.状态 !== '生效' || !e.动作) continue
      for (const [k, v] of Object.entries(e.动作)) {
        if (!(k in ACTION_KEYS)) continue
        out.set(k, { key: k, value: v, id: e.id, scope, file, label: `${scope} ${e.id}「${short(e.理解, 24)}」` })
      }
    }
  }
  return [...out.values()]
}

/** 记一次「实际用过」（PRD R10：生成记录列出实际采用的偏好）。 */
export function recordUse(file, id, use) {
  const m = readMem(file)
  const e = m.entries.find((x) => x.id === id)
  if (!e) return
  e.用过 = [...(e.用过 ?? []), { 时间: stamp(), ...use }]
  writeMem(file, m)
}

// ---------------------------------------------------------------- 给模型看的一小段、给人看的清单

const prefLine = (e) => `${e.id} ${short(e.理解, 28)}${e.强度 === '必须' ? '（必须）' : ''}`
/** 处理方式（PRD §6.1）：「流程里照做」= 代码 / 配置已经照做的规矩（只进清单，不每步给模型看 —— 省上下文）；
 *  「翻唱时自动」= 有动作、sv-cover 套用；其余（「Agent 照做」）是要模型在对话里记着的。 */
export const handling = (e) => e.处理方式 ?? (e.动作 ? '翻唱时自动' : 'Agent 照做')

export function memoryContext(g, s, song) {
  const lines = []
  const live = g.entries.filter((e) => e.类 === '偏好' && e.状态 === '生效')
  const gp = live.filter((e) => handling(e) !== '流程里照做')
  const built = live.length - gp.length
  if (gp.length > 0 || built > 0) {
    lines.push(`创作者的偏好（所有歌，生效）：${gp.slice(0, CONTEXT_PREFS).map(prefLine).join('；')}${gp.length > CONTEXT_PREFS ? `；等 ${gp.length} 条` : ''}`
      + `${built > 0 ? `${gp.length > 0 ? '；' : ''}另有 ${built} 条流程里已经照做（memory_list 看）` : ''}`)
  }
  if (s && song) {
    const sp = s.entries.filter((e) => e.类 === '偏好' && e.状态 === '生效')
    const fb = s.entries.filter((e) => e.类 === '反馈' && e.状态 !== '已删除').slice(-CONTEXT_FEEDBACK)
    const parts = []
    if (sp.length > 0) parts.push(`偏好 ${sp.map(prefLine).join('；')}`)
    if (fb.length > 0) parts.push(`他说过 ${fb.map((e) => `${e.来源?.版本 ? `${e.来源.版本}：` : ''}「${short(e.原话, 30)}」`).join('；')}`)
    if (parts.length > 0) lines.push(`这首《${song}》：${parts.join('；')}`)
  }
  const pending = [...g.entries, ...(s?.entries ?? [])].filter((e) => e.类 === '偏好' && e.状态 === '待确认')
  if (pending.length > 0) lines.push(`待创作者确认的偏好 ${pending.length} 条（${pending.slice(0, 3).map((e) => e.id).join('、')}${pending.length > 3 ? ' 等' : ''}）`)
  lines.push('记忆规矩：创作者评价某一版（好 / 不好 / 哪里有问题）→ memory_record 存原话（原样摘他的话），然后告诉他一句；'
    + '看出一条以后要照做的规矩 → memory_record 提议偏好、问他记不记，他说是才 memory_confirm；他说「这条不算」/ 要停用 → memory_change。他说「好」不等于偏好。')
  return lines.join('\n')
}

const entryMd = (e) => {
  const src = e.来源 ?? {}
  const where = [src.版本, src.位置].filter(Boolean).join(' ')
  const head = e.类 === '偏好'
    ? `- **${e.id}**〔${e.状态}〕${e.范围 ?? ''}${e.强度 ? ` · ${e.强度}` : ''} · ${handling(e)}：${e.理解}`
    : `- **${e.id}**${e.状态 === '已删除' ? '〔已删除〕' : ''}${where ? ` ${where}` : ''}：「${e.原话}」`
  const body = []
  if (e.类 === '偏好') body.push(`  依据：「${e.原话}」（${src.时间 ?? ''}，${src.怎么来的 ?? ''}）`)
  else body.push(`  理解：${e.理解 ?? ''}（${src.时间 ?? ''}，${src.怎么来的 ?? ''}）`)
  if (e.确认) body.push(`  你确认：「${e.确认.原话}」（${e.确认.时间}）`)
  if (e.动作) body.push(`  翻唱时自动：${Object.entries(e.动作).map(([k, v]) => ACTION_KEYS[k]?.(v) ?? `${k}=${v}`).join('、')}`)
  if (e.用过?.length) body.push(`  用过 ${e.用过.length} 次：${e.用过.slice(-3).map((u) => `${u.歌 ?? ''} ${u.版本 ?? ''}`.trim()).join('、')}`)
  return [head, ...body].join('\n')
}

export function renderMd(title, m, history = []) {
  const live = m.entries.filter((e) => e.状态 !== '已删除')
  const prefs = live.filter((e) => e.类 === '偏好')
  const fb = live.filter((e) => e.类 === '反馈')
  const lines = [`# ${title}`, '', '> 自动生成（每次有改动就重写）—— 在这里改不算数；要改、要删，跟 Agent 说（比如「s3 这条不算」「g2 停用」）。', '']
  lines.push('## 偏好', '', ...(prefs.length ? prefs.map(entryMd) : ['（还没有）']), '')
  lines.push('## 反馈', '', ...(fb.length ? fb.map(entryMd) : ['（还没有）']), '')
  if (history.length) lines.push('## 做过的版本', '', ...history, '')
  const gone = m.entries.length - live.length
  if (gone) lines.push(`（另有 ${gone} 条已删除，不再给 Agent 看）`, '')
  return lines.join('\n')
}

/** 这首做过的版本（sv-artifact 的清单 + 每版 song.json 里的设置）。 */
export function versionHistory(projectDir, artifactStore) {
  if (!artifactStore) return []
  let man
  try { man = readManifest(artifactStore, projectDir) } catch { return [] }
  return man.versions.map((v) => {
    let set = ''
    try {
      const cfg = JSON.parse(readFileSync(join(projectDir, v.folder, 'song.json'), 'utf8'))
      set = `${cfg.octave_pick === false ? '不挑八度' : '挑八度'}${cfg.language && cfg.language !== 'zh' ? `、${cfg.language}` : ''}`
    } catch { /* 没有 song.json */ }
    const state = v.discarded ? `弃用（${v.discarded.reason}）` : v.sealed ? `${v.sealed} 交付` : '进行中'
    return `- ${v.id}：${state}${set ? `；${set}` : ''}${v.note ? `；${v.note}` : ''}`
  })
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
const textOf = (content) => (Array.isArray(content) ? content : []).filter((b) => b?.type === 'text' && typeof b.text === 'string').map((b) => b.text).join('\n')

export function apply(ctx, config) {
  const need = (k) => { const v = config?.[k]; if (typeof v !== 'string' || !isAbsolute(v)) throw new Error(`sv-memory：config.${k} 要写绝对路径`); return resolve(v) }
  const ROOT = need('root')
  const STORE = need('store')
  const ARTIFACTS = typeof config?.artifacts === 'string' ? resolve(config.artifacts) : null
  const rootKey = ROOT.toLowerCase().replace(/[\\/]+$/, '')
  const storeKey = STORE.toLowerCase()
  if (storeKey === rootKey || storeKey.startsWith(rootKey + '\\') || storeKey.startsWith(rootKey + '/')) {
    throw new Error('sv-memory：记忆库不能放在项目根下面（Agent 的沙箱能写那里）')
  }
  mkdirSync(STORE, { recursive: true })

  const recent = new Map()          // 会话 id → [{ text, at }]（创作者最近的消息，对原话、看确认是不是在提议之后说的）
  ctx.on('session/event', (session, event) => {
    if (event?.type !== 'user/message' || event.data?.source?.kind !== 'user') return
    const arr = recent.get(session.id) ?? []
    arr.push({ text: textOf(event.data.content), at: Date.now() })
    while (arr.length > RECENT) arr.shift()
    recent.set(session.id, arr)
  })
  const messagesOf = (exec, after = 0) => (recent.get(exec?.agent?.session?.id) ?? []).filter((m) => m.at > after).map((m) => m.text)
  const projectOf = (exec) => projectDirOf(exec?.agent?.session?.header?.cwd, ROOT)

  /** 改完重写给人看的清单。 */
  const refresh = (dir) => {
    const g = readMem(globalFile(STORE))
    writeFileSync(join(STORE, '全局记忆.md'), renderMd('全局记忆（所有歌）', g), 'utf8')
    if (dir) {
      const s = readMem(songFile(STORE, dir))
      writeFileSync(join(dir, VIEW), renderMd(`《${basename(dir)}》的记忆`, s, versionHistory(dir, ARTIFACTS)), 'utf8')
    }
  }
  /** id → 它在哪个文件：g 开头的是全局；s 开头的在当前这首。 */
  const locate = (id, dir) => {
    if (/^g\d+$/.test(id)) return globalFile(STORE)
    if (/^s\d+$/.test(id)) {
      if (dir === null) throw new Error(`${id} 是某一首歌里的；请在那首歌下面的会话里改`)
      return songFile(STORE, dir)
    }
    throw new Error('id 是 g 加数字（全局）或 s 加数字（这首歌），例如 g3、s2')
  }

  ctx.systemPrompt.context({
    name: 'sv:memory',
    order: 320,
    text: (context) => {
      try {
        const dir = projectDirOf(context?.agent?.session?.header?.cwd, ROOT)
        return memoryContext(readMem(globalFile(STORE)), dir ? readMem(songFile(STORE, dir)) : null, dir ? basename(dir) : null)
      } catch { return '' }
    },
  })

  // 给人看的清单是生成的：Agent 用 write / edit 碰它 → 拒绝（要改走 memory_change）
  ctx.tools.guard((exec) => {
    if (exec.name !== 'write' && exec.name !== 'edit') return undefined
    const p = exec.arguments?.file_path
    if (typeof p !== 'string' || p === '') return undefined
    return basename(p) === VIEW ? `${VIEW} 是自动生成的记忆清单，不能直接改；要记、要改、要删，用 memory_record / memory_change` : undefined
  })

  ctx.tools.register(stringTool({
    name: 'memory_record',
    description: '记一条反馈，或提议一条偏好。反馈：创作者评价某一版（好 / 不好 / 哪里有问题）时，原样摘他的原话存下（不要改写），记完告诉他一句。'
      + '偏好：你看出一条以后要照着做的规矩时提议（先「待确认」），然后问他记不记、范围对不对；他说是才用 memory_confirm 生效。他说「好」不等于偏好。',
    parameters: {
      type: 'object',
      properties: {
        kind: { type: 'string', enum: ['反馈', '偏好'] },
        quote: { type: 'string', description: '创作者的原话：从他最近的消息里原样摘一段（偏好就摘依据的那句）' },
        understanding: { type: 'string', description: '你的理解，一句话（他可以改）' },
        version: { type: 'string', description: '说的是哪一版，例如 r02（可省）' },
        position: { type: 'string', description: '哪一段，例如 1:16–1:32、副歌（可省）' },
        scope: { type: 'string', enum: ['这首歌', '所有歌'], description: '偏好的范围，默认这首歌' },
        strength: { type: 'string', enum: ['必须', '尽量'], description: '偏好的强度，默认尽量' },
        octave_pick: { type: 'boolean', description: '偏好如果是「挑不挑八度」：false = 不挑（翻唱时会自动用）' },
      },
      required: ['kind', 'quote', 'understanding'],
    },
    async execute(args, exec) {
      const kind = optString(args, 'kind')
      const quote = optString(args, 'quote')
      const understanding = optString(args, 'understanding')
      if (kind !== '反馈' && kind !== '偏好') throw new Error('kind 要是「反馈」或「偏好」')
      if (!quote || !understanding) throw new Error('要写 quote（原话）和 understanding（理解）')
      if (!isVerbatim(quote, messagesOf(exec))) throw new Error('quote 要原样摘创作者最近的话（一字不改）；找不到这句 —— 不要转述，照他的原文摘')
      const dir = projectOf(exec)
      const version = optString(args, 'version')
      if (version && dir && ARTIFACTS && !readManifest(ARTIFACTS, dir).versions.some((v) => v.id === version)) throw new Error(`这首没有 ${version}`)
      const 来源 = { 时间: stamp(), 怎么来的: '对话', 会话: exec?.agent?.session?.id, ...(version ? { 版本: version } : {}), ...(optString(args, 'position') ? { 位置: optString(args, 'position') } : {}) }
      if (kind === '反馈') {
        const file = dir ? songFile(STORE, dir) : globalFile(STORE)
        const m = readMem(file)
        const e = addEntry(m, dir ? 's' : 'g', { 类: '反馈', 原话: quote, 理解: understanding, 来源, 状态: '记下了' })
        writeMem(file, m)
        refresh(dir)
        return `记下了：${dir ? `《${basename(dir)}》` : '全局'} ${e.id}${version ? `（${version}）` : ''}「${short(quote, 30)}」。告诉创作者一句「记下了」；他说「这条不算」就用 memory_change 删。`
      }
      const scope = optString(args, 'scope') ?? '这首歌'
      if (scope !== '这首歌' && scope !== '所有歌') throw new Error('scope 要是「这首歌」或「所有歌」')
      if (scope === '这首歌' && dir === null) throw new Error('不在任何一首歌里：范围只能是「所有歌」，或请他在那首歌下面开会话')
      const strength = optString(args, 'strength') ?? '尽量'
      if (strength !== '必须' && strength !== '尽量') throw new Error('strength 要是「必须」或「尽量」')
      const 动作 = typeof args?.octave_pick === 'boolean' ? { octave_pick: args.octave_pick } : undefined
      const file = scope === '这首歌' ? songFile(STORE, dir) : globalFile(STORE)
      const m = readMem(file)
      const e = addEntry(m, scope === '这首歌' ? 's' : 'g', { 类: '偏好', 原话: quote, 理解: understanding, 来源, 范围: scope, 强度: strength, 状态: '待确认', ...(动作 ? { 动作 } : {}), 提议于: Date.now() })
      writeMem(file, m)
      refresh(dir)
      return `提议了偏好 ${e.id}（待确认）：${understanding}；范围：${scope}；强度：${strength}${动作 ? `；翻唱时自动${ACTION_KEYS.octave_pick(动作.octave_pick)}` : ''}。`
        + '现在问创作者：记不记、范围对不对。他回答以后用 memory_confirm（照他的原话摘 answer_quote）。'
    },
  }))

  ctx.tools.register(stringTool({
    name: 'memory_confirm',
    description: '创作者对一条「待确认」的偏好表了态以后调：他同意 → 生效；不要 → 删掉。answer_quote 原样摘他这次的回答（要在你提议之后说的）。',
    parameters: {
      type: 'object',
      properties: {
        id: { type: 'string', description: '偏好的 id，例如 s2、g5' },
        decision: { type: 'string', enum: ['生效', '不要'] },
        answer_quote: { type: 'string', description: '创作者这次回答的原话（原样摘）' },
      },
      required: ['id', 'decision', 'answer_quote'],
    },
    async execute(args, exec) {
      const id = optString(args, 'id')
      const decision = optString(args, 'decision')
      const answer = optString(args, 'answer_quote')
      if (!id || !answer || (decision !== '生效' && decision !== '不要')) throw new Error('要写 id、decision（生效 / 不要）、answer_quote')
      const dir = projectOf(exec)
      const file = locate(id, dir)
      const m = readMem(file)
      const e = m.entries.find((x) => x.id === id)
      if (!e || e.类 !== '偏好') throw new Error(`${id} 不是偏好`)
      if (e.状态 !== '待确认') throw new Error(`${id} 现在是「${e.状态}」，不是待确认`)
      if (!isVerbatim(answer, messagesOf(exec, e.提议于 ?? 0), 1)) throw new Error('answer_quote 要原样摘创作者在你提议之后说的话；他还没回答就先等他')
      if (decision === '生效') {
        e.确认 = { 原话: answer, 时间: stamp(), 怎么来的: '对话' }
        setState(m, id, '生效', '创作者同意')
      } else {
        setState(m, id, '已删除', `创作者不要：「${short(answer, 30)}」`)
      }
      writeMem(file, m)
      refresh(dir)
      return decision === '生效' ? `${id} 生效了：${e.理解}` : `${id} 删掉了（不记）`
    },
  }))

  ctx.tools.register(stringTool({
    name: 'memory_change',
    description: '创作者要改一条记忆时调：删掉（「这条不算」）、停用、重新生效偏好，或改你写的理解。quote 原样摘他要你改的那句话。',
    parameters: {
      type: 'object',
      properties: {
        id: { type: 'string', description: '例如 s3、g2' },
        to: { type: 'string', enum: ['已删除', '已停用', '生效'], description: '改成什么状态（只改理解就不写）' },
        understanding: { type: 'string', description: '新的理解（创作者纠正了你的理解时）' },
        quote: { type: 'string', description: '创作者要你改的原话（原样摘）' },
      },
      required: ['id', 'quote'],
    },
    async execute(args, exec) {
      const id = optString(args, 'id')
      const quote = optString(args, 'quote')
      const to = optString(args, 'to')
      const understanding = optString(args, 'understanding')
      if (!id || !quote) throw new Error('要写 id 和 quote')
      if (!to && !understanding) throw new Error('要写 to（状态）或 understanding（新理解）')
      const dir = projectOf(exec)
      const file = locate(id, dir)
      const m = readMem(file)
      const e = m.entries.find((x) => x.id === id)
      if (!e) throw new Error(`没有 ${id}`)
      if (to && e.状态 === '待确认' && to === '生效') throw new Error(`${id} 还在待确认：等创作者回答以后用 memory_confirm`)
      // 要他「这次」说的：记下这条以后的话（10-01 DSH 实测：删一条时模型引了原来那句评价，不是「这条不算」）
      if (!isVerbatim(quote, messagesOf(exec, e.建于 ?? 0), 1)) throw new Error('quote 要原样摘创作者要你改的那句话（在这条记下以后说的）')
      if (understanding) {
        e.改动 = [...(e.改动 ?? []), { 时间: stamp(), 理解从: e.理解, 为什么: `创作者：「${short(quote, 30)}」` }]
        e.理解 = understanding
      }
      if (to) setState(m, id, to, `创作者：「${short(quote, 30)}」`)
      writeMem(file, m)
      refresh(dir)
      return `${id} 改好了：${to ? `状态 → ${to}` : ''}${to && understanding ? '；' : ''}${understanding ? `理解 → ${understanding}` : ''}`
    },
  }))

  ctx.tools.register(stringTool({
    name: 'memory_list',
    description: '列出记忆：全局的，加上当前这首歌的（偏好带状态、反馈带原话、做过的版本）。创作者问「你记了什么」时用。',
    parameters: { type: 'object', properties: {} },
    async execute(_args, exec) {
      const dir = projectOf(exec)
      const g = renderMd('全局记忆（所有歌）', readMem(globalFile(STORE)))
      const s = dir ? renderMd(`《${basename(dir)}》的记忆`, readMem(songFile(STORE, dir)), versionHistory(dir, ARTIFACTS)) : ''
      return [g, s].filter(Boolean).join('\n\n') + `\n（清单文件：${join(STORE, '全局记忆.md')}${dir ? `、${join(dir, VIEW)}` : ''}）`
    },
  }))
}
