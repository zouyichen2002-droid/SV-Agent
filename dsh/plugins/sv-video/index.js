// SV-Agent · 歌词视频插件（v3 视频，2026-10-01）
//
// 在 DSH 的对话里「做歌词视频」→ 后台跑 Python Worker（sv-bridge/worker/video_run.py）→ 项目的 视频\vNN\ 出成片（mp4）+ 剪映草稿 → 交付。
// 创作者 10-01 定：先做歌词视频（图 + 逐字歌词字幕 + 轻微动效）；只用他给的图；剪映草稿 + 一份成片；
//                  草稿放进剪映的草稿文件夹，只新建「SV-Agent_<歌名>_vNN」，不碰他已有的草稿。
//
//   video_run 工具：校验成品音频、图（给文件夹 = 里面的图按文件名排）、工程（不给 = rNN 里最近改过的那份 .svp）→ 定下一版 vNN → 起后台任务就返回
//   后台任务：跑 Worker（渲染只用 CPU、低优先级，不用让出大模型）→ 读 日志\视频进度.jsonl 报进度
//             → 成功：记项目状态，把成片、草稿名、对齐结果、要提醒的告诉 Agent；失败 / 被停：vNN 改名「弃用_vNN（没跑完…）」（不删）
//   做完的 视频\vNN\（有 说明.md）和剪映的草稿文件夹：Agent 用 write / edit 碰 → 拒绝
//
// 只用 Node 自带模块 + 同仓库的 sv-project（项目的规矩）、sv-cover（读进度的函数）。
import { execFile, spawn } from 'node:child_process'
import { closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, renameSync, statSync } from 'node:fs'
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from 'node:path'
import { projectDirOf, readProject, writeProject } from '../sv-project/index.js'
import { readProgress } from '../sv-cover/index.js'

export const name = 'sv-video'
export const inject = ['tools', 'jobs', 'sandbox', 'sandboxPolicy', 'systemPrompt']

const POLL_MS = 2000
const IMAGE_EXT = new Set(['.png', '.jpg', '.jpeg', '.webp', '.bmp'])
const VIDEO_EXT = new Set(['.mp4', '.mov', '.webm', '.mkv', '.m4v', '.avi'])   // 画面也可以是视频：循环铺满（10-02《怪物》：创作者用别的 AI 做的 8 秒循环）
const SIDES = new Set(['left', 'right'])
const AUDIO_EXT = new Set(['.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg'])
const MAX_IMAGES = 30
// 字幕样式（10-01 创作者「接下来尝试一下特效字幕」）：平铺 = 原来的整行卡拉 OK（默认）；别的是 worker/lyric_fx.py 里每个字单独动的特效
// 可爱（10-02 创作者给的参考：B 站《樱草哀歌》/ 星尘infinity —— 「能有一定动效的可爱字体，带颜色」）：站酷快乐体、白字彩边带光、几行错落 / 斜台阶、从左滑进滑出
// 凌厉（10-02 创作者「找一个凌厉的版本」→ 参考 B 站《【文字PV】KING》）：毛笔楷书大字砸进来、竖排小字（也是毛笔楷书，创作者嫌宋体丑）、红色刀痕、画面压暗
export const FX = ['可爱', '凌厉', '平铺', '弹跳', '发光', '浮现', '逐字出现', '竖排古风']
const VIDEO_DIR = /^v(\d{2,})$/
const DISCARDED_DIR = /^弃用_v(\d{2,})/

const pad = (x) => String(x).padStart(2, '0')
const stamp = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
const key = (p) => resolve(p).toLowerCase()
const inside = (p, dir) => { const a = key(p); const b = key(dir).replace(/[\\/]+$/, ''); return a === b || a.startsWith(b + '\\') || a.startsWith(b + '/') }
const byName = (a, b) => basename(a).localeCompare(basename(b), 'zh-Hans-CN', { numeric: true })

const isPicture = (p) => IMAGE_EXT.has(extname(p).toLowerCase()) || VIDEO_EXT.has(extname(p).toLowerCase())

/** 画面：每一项是图或视频的绝对路径，或文件夹（里面的图、视频按文件名排，不往下层找）。 */
export function expandImages(list) {
  if (!Array.isArray(list) || list.length === 0) throw new Error('要给画面：images 填图 / 视频（或放它们的文件夹）的绝对路径')
  const out = []
  for (const raw of list) {
    const p = typeof raw === 'string' ? raw.trim() : ''
    if (!isAbsolute(p) || !existsSync(p)) throw new Error(`找不到图：${raw}（要写绝对路径）`)
    if (statSync(p).isDirectory()) {
      const found = readdirSync(p, { withFileTypes: true }).filter((e) => e.isFile() && isPicture(e.name)).map((e) => join(p, e.name)).sort(byName)
      if (found.length === 0) throw new Error(`文件夹里没有图或视频：${p}（认 ${[...IMAGE_EXT, ...VIDEO_EXT].join(' ')}）`)
      out.push(...found)
    } else if (isPicture(p)) {
      out.push(p)
    } else {
      throw new Error(`不是图也不是视频：${p}（认 ${[...IMAGE_EXT, ...VIDEO_EXT].join(' ')}）`)
    }
  }
  if (out.length > MAX_IMAGES) throw new Error(`图太多了（${out.length} 张）：最多 ${MAX_IMAGES} 张，整首平均分`)
  return out
}

const svpsIn = (folder) => {
  try { return readdirSync(folder).filter((f) => f.toLowerCase().endsWith('.svp') && !f.endsWith('_吸格线前.svp')).map((f) => join(folder, f)) } catch { return [] }
}
const newest = (files) => files.reduce((a, b) => (a === null || statSync(b).mtimeMs > statSync(a).mtimeMs ? b : a), null)

/** 默认的工程：没弃用的 rNN 里最近改过的 .svp（创作者在 SV 里改了存盘、或另存了一份，都是他最后动的那份）；吸格线前的备份不算。 */
export function pickSvp(projectDir) {
  const rounds = readdirSync(projectDir, { withFileTypes: true }).filter((e) => e.isDirectory() && /^r\d{2,}$/.test(e.name))
  return newest(rounds.flatMap((e) => svpsIn(join(projectDir, e.name))))
}

/** svp 参数：不填 → pickSvp；rNN → 那一版里最近改过的；绝对路径 → 那个文件。 */
export function resolveSvp(projectDir, arg) {
  const v = typeof arg === 'string' ? arg.trim() : ''
  if (v === '') {
    const p = pickSvp(projectDir)
    if (p === null) throw new Error('项目里还没有翻唱出来的工程（rNN 里没有 .svp）：先翻唱，或者 svp 填工程的绝对路径')
    return p
  }
  if (/^r\d{2,}$/.test(v)) {
    const p = newest(svpsIn(join(projectDir, v)))
    if (p === null) throw new Error(`${v} 里没有 .svp`)
    return p
  }
  if (!isAbsolute(v) || !existsSync(v) || !v.toLowerCase().endsWith('.svp')) throw new Error(`找不到工程：${v}（rNN，或 .svp 的绝对路径）`)
  return v
}

/** 这首歌的视频版本：视频\vNN\（有 说明.md = 做好了）和 视频\弃用_vNN…\。 */
export function videoVersions(projectDir) {
  const d = join(projectDir, '视频')
  let entries
  try { entries = readdirSync(d, { withFileTypes: true }) } catch { return [] }
  const out = []
  for (const e of entries) {
    if (!e.isDirectory()) continue
    const live = VIDEO_DIR.exec(e.name)
    const gone = DISCARDED_DIR.exec(e.name)
    if (!live && !gone) continue
    const n = Number((live ?? gone)[1])
    const done = live ? existsSync(join(d, e.name, '说明.md')) : false
    out.push({ id: `v${pad(n)}`, n, folder: e.name, done, discarded: Boolean(gone),
      when: done ? stamp(statSync(join(d, e.name, '说明.md')).mtime) : null })
  }
  return out.sort((a, b) => a.n - b.n || Number(a.discarded) - Number(b.discarded))
}

/** 下一版编号：视频\ 里的 vNN / 弃用_vNN 和剪映草稿文件夹里的 SV-Agent_<歌名>_vNN，取最大 + 1（号不复用）。 */
export function nextVideoId(projectDir, drafts) {
  let max = 0
  for (const v of videoVersions(projectDir)) max = Math.max(max, v.n)
  const prefix = `SV-Agent_${basename(projectDir)}_v`
  try {
    for (const e of readdirSync(drafts, { withFileTypes: true })) {
      if (e.isDirectory() && e.name.startsWith(prefix)) { const n = /^(\d{2,})$/.exec(e.name.slice(prefix.length)); if (n) max = Math.max(max, Number(n[1])) }
    }
  } catch { /* 草稿文件夹不在：Worker 会报 */ }
  return `v${pad(max + 1)}`
}

/** 每一步那一小段：最近两版的状态；还没做过视频就不说。 */
export function videoContext(projectDir) {
  const vs = videoVersions(projectDir)
  if (vs.length === 0) return ''
  const items = vs.slice(-2).reverse().map((v) => (v.discarded ? `${v.id} 弃用（${v.folder}）` : v.done ? `${v.id} 做好了（${v.when}）` : `${v.id} 在做 / 没做完`))
  return `歌词视频：${items.join('；')}。做好的不能改，要改就用 video_run 再做一版。`
}

/** 拒绝的理由：做好的 视频\vNN\ 里的文件、剪映的草稿文件夹。 */
export function protectedReason(absPath, root, drafts) {
  if (drafts && inside(absPath, drafts)) return '剪映的草稿文件夹只许 video_run 新建草稿，别的不能碰；创作者要改就在剪映里改'
  const dir = projectDirOf(dirname(absPath), root)
  if (dir === null) return undefined
  const rel = relative(join(dir, '视频'), absPath).split('\\')
  if (rel.length < 2 || rel[0] === '..' || !VIDEO_DIR.test(rel[0])) return undefined
  if (!existsSync(join(dir, '视频', rel[0], '说明.md'))) return undefined
  return `歌词视频 ${rel[0]} 已经做好交给创作者了，里面的文件不能改、不能往里加；要改就用 video_run 再做一版`
}

const killTree = (pid) => new Promise((res) => {
  execFile('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () => res())
})

const safeReason = (s) => String(s).replace(/[<>:"/\\|?*\r\n]/g, ' ').trim().slice(0, 30)

/** 没做完的一版改名「弃用_vNN（原因）」（不删）；改不了（被占着）就留着、说一声。 */
export function discardUnfinished(projectDir, id, reason) {
  const from = join(projectDir, '视频', id)
  if (!existsSync(from) || existsSync(join(from, '说明.md'))) return null
  const to = join(projectDir, '视频', `弃用_${id}（${safeReason(reason)}）`)
  try { renameSync(from, to); return to } catch { return null }
}

/** 同上，改不了就隔 0.5 秒再试，最多 10 次：10-01 DSH 里试，渲染刚被停掉时 ffmpeg 的文件还没放开，一次改名失败、v02 就一直留着没改。 */
export async function discardUnfinishedRetry(projectDir, id, reason, tries = 10, waitMs = 500) {
  for (let i = 0; i < tries; i += 1) {
    const moved = discardUnfinished(projectDir, id, reason)
    if (moved !== null || !existsSync(join(projectDir, '视频', id)) || existsSync(join(projectDir, '视频', id, '说明.md'))) return moved
    await new Promise((r) => setTimeout(r, waitMs))
  }
  return null
}

// ---------------------------------------------------------------- 插件

const textBlock = (s) => [{ type: 'text', text: s }]
const optString = (args, k) => (typeof args?.[k] === 'string' && args[k].trim() !== '' ? args[k].trim() : undefined)

export function apply(ctx, config) {
  const need = (k) => { const v = config?.[k]; if (typeof v !== 'string' || !isAbsolute(v)) throw new Error(`sv-video：config.${k} 要写绝对路径`); return resolve(v) }
  const ROOT = need('root')
  const PYTHON = need('python')
  const WORKER = need('worker')
  const DRAFTS = need('drafts')
  const useSandbox = config.sandbox !== false
  const running = new Map()         // 项目文件夹 → 任务 id（一首歌同时只做一个视频）

  ctx.systemPrompt.context({
    name: 'sv:video',
    order: 330,
    text: (context) => {
      try {
        const dir = projectDirOf(context?.agent?.session?.header?.cwd, ROOT)
        return dir === null ? '' : videoContext(dir)
      } catch { return '' }
    },
  })

  ctx.tools.guard((exec) => {
    if (exec.name !== 'write' && exec.name !== 'edit') return undefined
    const p = exec.arguments?.file_path
    if (typeof p !== 'string' || p === '') return undefined
    const cwd = exec.agent?.session?.header?.cwd
    const abs = isAbsolute(p) ? resolve(p) : resolve(cwd ?? ROOT, p)
    try { return protectedReason(abs, ROOT, DRAFTS) } catch { return undefined }
  })

  ctx.tools.register({
    name: 'video_run',
    description: '给当前项目这首歌做歌词视频：创作者给的图 + 他的成品音频 + 逐字变色的歌词字幕（时间从 SV 工程来）+ 轻微推近，'
      + '在后台出一份 1080p 成片（mp4）和一份剪映草稿（剪映里打开就能接着改），写进项目里新开的 视频\\vNN。'
      + '字幕默认「可爱」，可以换样式（fx：凌厉、平铺、弹跳、发光、浮现、逐字出现、竖排古风）。自动核对成品音频和工程差几秒、字幕跟着平移。约 3–5 分钟，不用让出大模型。调用后简短告诉创作者已开始、要等多久，然后结束这一轮，不要等任务。',
    parameters: {
      type: 'object',
      properties: {
        audio: { type: 'string', description: '成品音频（创作者混好的整首）的绝对路径' },
        images: { type: 'array', items: { type: 'string' }, description: '画面：图或视频的绝对路径，一个或几个（几个就整首平均分、交叉淡化；视频会循环铺满它那一段）；也可以填放它们的文件夹（按文件名排）' },
        svp: { type: 'string', description: '字幕时间用哪个 SV 工程：不填 = rNN 里最近改过的那份；填 rNN = 那一版里的；或 .svp 的绝对路径' },
        title: { type: 'string', description: '开头的标题，不填 = 《歌名》' },
        credit: { type: 'string', description: '标题下面那行小字（例如「翻唱：小鳄鱼aligator」）；创作者没说就不填、不放' },
        side: { type: 'string', enum: ['left', 'right'], description: '字放哪边：left / right；不填 = 自动（看画面哪边空）。创作者说了「字放左边 / 右边」才填' },
        skip: { type: 'array', items: { type: 'string' }, description: '不出字幕的词（不分大小写、不管标点），比如创作者说「ah 都不要字幕」就填 ["ah"]；没说就不填' },
        fx: { type: 'string', enum: FX, description: '字幕样式：可爱（默认：快乐体、白字彩色描边带光、一句拆成几行错落或斜台阶，字放在图里空的一边）、凌厉（毛笔楷书大字砸进来、旁边竖排小字红白相间、红色刀痕、画面压暗，像 KING 那种文字 PV）、平铺（原来的整行逐字变色）、弹跳、发光、浮现、逐字出现、竖排古风（华文行楷竖排，给古风歌）；创作者没说就不填' },
      },
      required: ['audio', 'images'],
    },
    output: { schema: { type: 'string' }, render: (_args, value) => textBlock(value) },
    async execute(args, exec) {
      const session = exec?.agent?.session
      const dir = projectDirOf(session?.header?.cwd, ROOT)
      if (!session || dir === null) throw new Error('这个会话不在任何项目里；请创作者在侧栏那首歌下面开会话')
      const project = readProject(dir)
      if (!project || project.error) throw new Error(project?.error ?? `${dir} 不是项目`)
      if (running.has(dir)) throw new Error(`这首歌的视频已经在做了（任务 ${running.get(dir)}）；等它做完，或在任务列表里停掉`)
      const audio = optString(args, 'audio')
      if (!audio) throw new Error('要写 audio：成品音频的绝对路径（创作者没给就问他要）')
      if (!isAbsolute(audio) || !existsSync(audio) || !statSync(audio).isFile()) throw new Error(`找不到成品音频：${audio}（要写绝对路径）`)
      if (!AUDIO_EXT.has(extname(audio).toLowerCase())) throw new Error(`不是音频：${audio}（认 ${[...AUDIO_EXT].join(' ')}）`)
      const images = expandImages(args?.images)
      const svp = resolveSvp(dir, args?.svp)
      if (!existsSync(join(dir, '素材', '歌词_要唱的字.txt'))) throw new Error('项目里没有 素材\\歌词_要唱的字.txt（翻唱时生成的）：没有歌词就出不了字幕')
      const id = nextVideoId(dir, DRAFTS)
      const title = optString(args, 'title')
      const credit = optString(args, 'credit')
      const skip = Array.isArray(args?.skip) ? args.skip.map((w) => (typeof w === 'string' ? w.trim() : '')).filter(Boolean) : []
      if (skip.some((w) => w.length > 20)) throw new Error('skip 里的词太长了（一个词最多 20 个字）')
      const side = optString(args, 'side') ?? 'auto'
      if (side !== 'auto' && !SIDES.has(side)) throw new Error(`side 只能是 left 或 right（不填 = 自动）：${side}`)
      const fx = optString(args, 'fx') ?? '可爱'                     // 创作者 10-02：「效果不错，把可爱设成默认样式」
      if (!FX.includes(fx)) throw new Error(`没有这种字幕样式：${fx}（有：${FX.join('、')}）`)
      const draftName = `SV-Agent_${basename(dir)}_${id}`
      const label = `歌词视频《${basename(dir)}》${id}`

      let child = null
      let cancelled = null
      const jobId = ctx.jobs.start({
        kind: 'video',
        label,
        owner: session.id,
        run(job) {
          let progressLine = readProgress(join(dir, '日志', '视频进度.jsonl'), 0).next     // 上一版留下的行不再读
          const pump = () => {
            const { rows, next } = readProgress(join(dir, '日志', '视频进度.jsonl'), progressLine)
            progressLine = next
            for (const r of rows) {
              const text = `${r.步} ${r.状态}${r.说明 ? `：${r.说明}` : ''}`
              job.append(text + '\n', { channel: ['完成', '失败', '提醒'].includes(r.状态) ? 'stdout' : 'log' })
              job.updateProgress(text)
            }
          }
          const body = async () => {
            mkdirSync(join(dir, '日志'), { recursive: true })
            const outFile = join(dir, '日志', `video_${id}.out`)
            let argv = [PYTHON, WORKER, dir, '--version', id, '--audio', audio, ...images.flatMap((p) => ['--image', p]), '--svp', svp, '--drafts', DRAFTS, '--fx', fx, '--side', side, ...skip.flatMap((w) => ['--skip', w]),
              ...(title ? ['--title', title] : []), ...(credit ? ['--credit', credit] : [])]
            if (useSandbox) {
              const policy = ctx.sandboxPolicy.resolve({ session })
              if (policy.mode !== 'danger-full-access') argv = (await ctx.sandbox.confine(argv, policy)).argv
            }
            const fd = openSync(outFile, 'a')
            const code = await new Promise((res) => {
              child = spawn(argv[0], argv.slice(1), { cwd: dir, stdio: ['ignore', fd, fd] })
              child.on('exit', (c) => res(c ?? 1))
              child.on('error', () => res(127))
            })
            closeSync(fd)
            child = null
            pump()
            const summaryFile = join(dir, '日志', `视频_${id}.json`)
            let summary = null
            try { summary = JSON.parse(readFileSync(summaryFile, 'utf8')) } catch { /* 没写出来 */ }
            if (cancelled) {
              const moved = await discardUnfinishedRetry(dir, id, '停掉了')
              return { status: 'killed', detail: cancelled, result: `${label} 被停掉了${moved ? `；没做完的改名留着：${moved}` : `；${join(dir, '视频', id)} 改不了名（文件还被占着），留着没动`}` }
            }
            if (code === 0 && summary?.结果 === '完成') {
              const p = readProject(dir)
              if (p && !p.error) {
                p.status = `歌词视频 ${id} 做好了（${stamp()}），等创作者看`
                p.notes = [...(Array.isArray(p.notes) ? p.notes : []), `${stamp()}：video_run ${id} 完成，${Math.round(summary.总秒 / 60)} 分钟`]
                p.updated = stamp()
                writeProject(dir, p)
              }
              const warn = Array.isArray(summary.提醒) && summary.提醒.length > 0 ? `要提醒创作者：${summary.提醒.join('；')}。` : ''
              const missing = summary.没出字幕的行?.length ? `没出字幕的行：第 ${summary.没出字幕的行.join('、')} 行（工程里没唱这几行）。` : ''
              // 成片多长、后台用了多久分开写（10-02：Agent 把后台用时说成了成片多长，下一版又照抄上一版的数）
              const length = summary.成片时长 ? `成片 ${summary.成片时长}（整首）` : '成片时长没量到'
              return { status: 'completed', result: `${label} 做好了：${length}，后台用了 ${summary.后台用时 ?? `${Math.max(1, Math.round(summary.总秒 / 60))} 分钟`}（这是做的时间，不是成片多长）。成片：${summary.成片}；`
                + `剪映草稿：「${draftName}」（创作者在剪映的草稿列表里打开就能改）；字幕 ${summary.字幕行} 行，时间从 ${summary.工程}；对齐：${summary.对齐}。`
                + `${missing}${warn}说明在 ${join(dir, '视频', id, '说明.md')}；用 present 把成片和说明交给创作者。` }
            }
            // 没写总结就退出了：不是哪一步报错，是中途被结束了（任务管理器、taskkill）或者崩了 —— 直说，免得 Agent 一个个翻日志找报错
            //（10-01 DSH 里试：我在外面结束了渲染，结果只说「退出码 1」，模型翻了 4 个日志、上下文用到 73% 还在找）
            // 0xC0000142（Windows：程序初始化失败）：Worker 一行都没跑到 —— 是 DSH 自己起不了子程序（10-02：启动 DSH 的那个后台窗口被关掉以后，
            // DSH 还活着，但起的 Python 全都这样死；重开 DSH 就好），不是这首歌、也不是参数的问题，重试没用
            const dllInit = code === 3221225794 || code === -1073741502
            const why = summary?.原因 ?? (dllInit
              ? `Worker 一启动就退出了（退出码 0xC0000142：Windows 程序初始化失败，一行都没跑到）：是 DSH 自己起不了子程序，要重开 DSH；不是这首歌或参数的问题，别重试，先告诉创作者`
              : `Worker 中途退出了、没写总结（退出码 ${code}）：多半是被结束了或者崩了，不是哪一步报的错；输出在 ${outFile}`)
            const moved = await discardUnfinishedRetry(dir, id, `没跑完 ${summary?.步 ?? ''}`)
            const left = moved ? `。没做完的改名留着：${moved}`
              : !existsSync(join(dir, '视频', id)) ? `。${id} 的文件夹还没建，什么都没留下` : `。${join(dir, '视频', id)} 改不了名（文件还被占着），留着没动`
            return { status: 'failed', detail: why, result: `${label} 没做完：${summary?.步 ?? ''} ${why}${left}` }
          }
          const done = body()
            .catch((e) => ({ status: 'failed', detail: String(e?.message ?? e), result: `${label} 插件出错：${e?.message ?? e}` }))
            .finally(() => running.delete(dir))
          const timer = setInterval(pump, POLL_MS)
          done.finally(() => clearInterval(timer))
          return {
            cancel(reason) {
              cancelled = reason || '创作者停掉了'
              if (child?.pid) killTree(child.pid)
            },
            done,
          }
        },
      })
      running.set(dir, jobId)
      const svpRel = relative(dir, svp).startsWith('..') ? svp : relative(dir, svp)
      const nVid = images.filter((p) => VIDEO_EXT.has(extname(p).toLowerCase())).length
      return `开始了：${label}（后台任务 ${jobId}）。画面 ${images.length} 个${nVid ? `（${nVid} 个是视频，循环铺满）` : ''}；${side === 'auto' ? '' : `字放${side === 'left' ? '左' : '右'}边；`}${skip.length ? `不出字幕：${skip.join('、')}；` : ''}音频 ${basename(audio)}；字幕时间用工程 ${svpRel}${args?.svp ? '' : '（rNN 里最近改过的那份）'}；`
        + `标题 ${title ?? `《${basename(dir)}》`}${credit ? `，署名「${credit}」` : '，不放署名'}；字幕样式「${fx}」。约 3–5 分钟；做好了你会被唤醒、再告诉创作者。现在简短告诉创作者，然后结束这一轮。`
    },
  })
}
