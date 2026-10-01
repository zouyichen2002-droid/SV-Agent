// SV-Agent · Cover Skill 插件（v3 阶段 3，2026-10-01）
//
// 在 DSH 的对话里「翻唱这首」→ 后台跑 Python Worker（sv-bridge/worker/cover_run.py：M1 的 9 步串成一条）→ 项目里的 rNN\ 出 .svp → 交付。
// 创作者 10-01 定：歌词贴在对话里（以「歌词：」开头），插件原样取、不让模型重抄；跑的时候让出本地大模型，跑完自动载回；
//                  分离用显卡；声库默认星尘。
//
//   cover_run 工具：取歌词 → 开下一版 rNN（sv-artifact 的规矩）→ 起一个后台任务就返回
//   后台任务：等 Agent 这一轮说完 → 卸掉本地大模型 → 把 Worker 包进沙箱跑（只许写这首歌的文件夹）→ 读 日志\进度.jsonl 报进度
//             → 成功：交付 rNN、记项目状态；失败：rNN 留着「进行中」，说哪一步错了 → 载回大模型 → 任务结束，DSH 唤醒 Agent 汇报
//   用户在任务列表里点停止 → 整组子程序停掉 → 载回大模型
//
// 只用 Node 自带模块 + 同仓库的 sv-project / sv-artifact（项目、版本的规矩都用它们测过的函数）。
import { execFile, spawn } from 'node:child_process'
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { constants as osConstants, setPriority } from 'node:os'
import { basename, isAbsolute, join, resolve } from 'node:path'
import { projectDirOf, readProject, writeProject } from '../sv-project/index.js'
import { nextVersionId, readManifest, sealVersion, writeManifest } from '../sv-artifact/index.js'

export const name = 'sv-cover'
export const inject = ['tools', 'jobs', 'sandbox', 'sandboxPolicy']

const RECENT_MESSAGES = 8
const TURN_WAIT_MS = 2 * 60 * 1000        // 最多等 Agent 这一轮说完 2 分钟（它若一直等着任务结果，这一轮不会自己结束）
const LLAMA_UP_MS = 3 * 60 * 1000
const POLL_MS = 2000
const LYRICS_MARK = /^\s*歌词\s*[:：]\s*/m

const pad = (x) => String(x).padStart(2, '0')
const stamp = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const textOf = (content) => (Array.isArray(content) ? content : []).filter((b) => b?.type === 'text' && typeof b.text === 'string').map((b) => b.text).join('\n')

/** 从最近几条用户消息里找歌词：最后一条里有一行以「歌词：」（或「歌词:」）开头的，取它后面的全部。 */
export function findLyrics(messages) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = LYRICS_MARK.exec(messages[i])
    if (m) {
      const text = messages[i].slice(m.index + m[0].length).trim()
      if (text.length > 0) return text
    }
  }
  return null
}

/** 新歌词和项目里已有的不一样：旧的两份改名留着（不删），换上新的；返回说明。 */
export function placeLyrics(projectDir, text, tag) {
  const d = join(projectDir, '素材')
  mkdirSync(d, { recursive: true })
  const raw = join(d, '歌词_原文.txt')
  const clean = join(d, '歌词_要唱的字.txt')
  const body = text.replace(/\r\n/g, '\n').trim() + '\n'
  if (existsSync(raw) && readFileSync(raw, 'utf8') === body) return '歌词和上次一样'
  let moved = ''
  for (const p of [raw, clean]) {
    if (existsSync(p)) {
      renameSync(p, p.replace(/\.txt$/, `_${tag}之前.txt`))
      moved = '（旧的两份改名留着）'
    }
  }
  writeFileSync(raw, body, 'utf8')
  return `歌词存进 素材\\歌词_原文.txt，${[...body.replace(/\s/g, '')].length} 字${moved}`
}

/** 读进度文件里第 n 行以后的（Worker 一行一个 JSON）。 */
export function readProgress(file, fromLine) {
  if (!existsSync(file)) return { rows: [], next: fromLine }
  const lines = readFileSync(file, 'utf8').split('\n').filter((l) => l.trim() !== '')
  const rows = []
  for (const l of lines.slice(fromLine)) { try { rows.push(JSON.parse(l)) } catch { /* 写到一半：下次再读 */ break } }
  return { rows, next: fromLine + rows.length }
}

// ---------------------------------------------------------------- 本地大模型：让出来 / 载回来（Windows）

const powershell = (cmd) => new Promise((res) => {
  execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', cmd], { windowsHide: true, timeout: 30000 }, (err, stdout) => res(err ? '' : String(stdout).trim()))
})

/** 端口上在听的进程，要命令行里同时有 llama-server 和这个端口才算我们的。 */
export async function llamaPid(port) {
  const out = await powershell(`$c = Get-NetTCPConnection -LocalPort ${Number(port)} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; `
    + `if ($c) { $p = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $c.OwningProcess); "$($c.OwningProcess)|$($p.CommandLine)" }`)
  if (!out) return null
  const [pid, ...rest] = out.split('|')
  const cmd = rest.join('|')
  return /llama-server/i.test(cmd) && cmd.includes(`--port ${port}`) ? Number(pid) : null
}

async function portFree(port, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    const out = await powershell(`if (Get-NetTCPConnection -LocalPort ${Number(port)} -State Listen -ErrorAction SilentlyContinue) { 'busy' } else { 'free' }`)
    if (out === 'free') return true
    await sleep(1000)
  }
  return false
}

export function makeLlama(cfg) {
  if (!cfg) return { stop: async () => 'no-llama', start: async () => 'no-llama' }
  return {
    async stop() {
      const pid = await llamaPid(cfg.port)
      if (pid === null) return '本地大模型没开着'
      try { process.kill(pid) } catch { /* 已经退了 */ }
      return (await portFree(cfg.port, 30000)) ? `本地大模型让出来了（进程 ${pid}）` : `本地大模型（进程 ${pid}）没停下来`
    },
    async start() {
      if ((await llamaPid(cfg.port)) !== null) return '本地大模型已经开着'
      const fd = openSync(cfg.log, 'w')
      const child = spawn(cfg.start[0], cfg.start.slice(1), { detached: true, windowsHide: true, stdio: ['ignore', fd, fd] })
      child.unref()
      closeSync(fd)
      const t0 = Date.now()
      while (Date.now() - t0 < LLAMA_UP_MS) {
        await sleep(POLL_MS)
        try {
          const r = await fetch(`http://127.0.0.1:${cfg.port}/health`)
          if (r.ok) {
            const pid = await llamaPid(cfg.port)
            if (pid !== null) { try { setPriority(pid, osConstants.priority.PRIORITY_BELOW_NORMAL) } catch { /* 调不了就算了 */ } }
            return `本地大模型载回来了（${Math.round((Date.now() - t0) / 1000)} 秒）`
          }
        } catch { /* 还没起来 */ }
      }
      return '本地大模型 3 分钟内没起来 —— 请看 llama-server.log'
    },
  }
}

const killTree = (pid) => new Promise((res) => {
  execFile('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () => res())
})

// ---------------------------------------------------------------- 插件

const textBlock = (s) => [{ type: 'text', text: s }]

export function apply(ctx, config) {
  const need = (k) => { const v = config?.[k]; if (typeof v !== 'string' || !isAbsolute(v)) throw new Error(`sv-cover：config.${k} 要写绝对路径`); return resolve(v) }
  const ROOT = need('root')
  const STORE = need('store')
  const PYTHON = need('python')
  const WORKER = need('worker')
  const useSandbox = config.sandbox !== false
  const llama = config.makeLlama ? config.makeLlama(config.llama) : makeLlama(config.llama)   // makeLlama：自检时换成假的

  const recent = new Map()          // 会话 id → 最近几条用户消息的文字
  const turnWaiters = new Map()     // 会话 id → 等「这一轮说完」的回调
  const running = new Map()         // 项目文件夹 → 任务 id（一首歌同时只跑一个）

  ctx.on('session/event', (session, event) => {
    if (event?.type === 'user/message' && event.data?.source?.kind === 'user') {
      const arr = recent.get(session.id) ?? []
      arr.push(textOf(event.data.content))
      while (arr.length > RECENT_MESSAGES) arr.shift()
      recent.set(session.id, arr)
    } else if (event?.type === 'turn/end') {
      const ws = turnWaiters.get(session.id) ?? []
      turnWaiters.delete(session.id)
      for (const w of ws) w()
    }
  })

  const waitTurnEnd = (sessionId) => new Promise((res) => {
    const timer = setTimeout(res, TURN_WAIT_MS)
    const arr = turnWaiters.get(sessionId) ?? []
    arr.push(() => { clearTimeout(timer); res() })
    turnWaiters.set(sessionId, arr)
  })

  ctx.tools.register({
    name: 'cover_run',
    description: '翻唱当前项目这首歌：用创作者给的来源（B 站等链接、本地音频，或项目里已有的原曲）和歌词（创作者最近一条以「歌词：」开头的消息，插件原样取），'
      + '在后台跑完整条翻唱链路（分离、扒谱、修歌词、挑八度、找拍子、生成 SV 工程），产物写进项目里新开的 rNN，跑完自动交付。'
      + '约 15–25 分钟；这段时间本地大模型会让出来，跑完载回后你会被唤醒，再把结果告诉创作者。调用后简短告诉创作者已开始、要等多久，然后结束这一轮，不要等任务。',
    parameters: {
      type: 'object',
      properties: {
        source: { type: 'string', description: '原曲：http(s) 链接、本地音频的绝对路径，或「已有」（项目里已经有 素材\\原曲整首.wav）' },
        use_lyrics: { type: 'boolean', description: '用不用创作者给的歌词（默认用；创作者说这首没有歌词时填 false，只靠听写）' },
        octave_pick: { type: 'boolean', description: '挑八度（默认开）：只有创作者说这首「不挑八度」时才填 false —— 音高全照 Vocal2Midi 扒的，不按《傍晚》学来的规矩改八度' },
        note: { type: 'string', description: '这一版要做什么，一句话，可省' },
      },
      required: ['source'],
    },
    output: { schema: { type: 'string' }, render: (_args, value) => textBlock(value) },
    async execute(args, exec) {
      const session = exec?.agent?.session
      const dir = projectDirOf(session?.header?.cwd, ROOT)
      if (!session || dir === null) throw new Error('这个会话不在任何项目里；请创作者在侧栏那首歌下面开会话（或先用 project_create 建项目）')
      const project = readProject(dir)
      if (!project || project.error) throw new Error(project?.error ?? `${dir} 不是项目`)
      if (running.has(dir)) throw new Error(`这首歌已经在跑了（任务 ${running.get(dir)}）；等它跑完，或在任务列表里停掉`)
      const source = typeof args?.source === 'string' ? args.source.trim() : ''
      if (source === '') throw new Error('要写 source：链接、本地音频路径，或「已有」')
      if (source === '已有' && !existsSync(join(dir, '素材', '原曲整首.wav'))) throw new Error('项目里还没有 素材\\原曲整首.wav；请给链接或本地音频')
      if (!/^https?:\/\//.test(source) && source !== '已有' && !(isAbsolute(source) && existsSync(source))) throw new Error(`找不到本地音频：${source}`)

      // 版本：最近一版还没交付、也还没出工程（上次失败或被停掉）→ 接着用它（Worker 做完的步会跳过）；否则开下一版
      const m = readManifest(STORE, dir)
      const svpOf = (v) => join(dir, v.folder, `${basename(dir)}_扒谱_${v.id}.svp`)
      const resume = [...m.versions].reverse().find((v) => !v.discarded && !v.sealed && !existsSync(svpOf(v)))
      const id = resume ? resume.id : nextVersionId(dir, m)

      // 歌词：从创作者最近的消息里原样取（不让模型重抄）
      const useLyrics = args?.use_lyrics !== false
      const octavePick = args?.octave_pick !== false              // 创作者 10-01 定：加开关、默认开着
      let lyricNote = '这一版不用歌词，只靠听写'
      if (useLyrics) {
        const text = findLyrics(recent.get(session.id) ?? [])
        if (text !== null) lyricNote = placeLyrics(dir, text, id)
        else if (existsSync(join(dir, '素材', '歌词_原文.txt'))) lyricNote = '这次的消息里没有「歌词：」，用项目里已有的歌词'
        else throw new Error('没找到歌词：请创作者发一条以「歌词：」开头的消息（下面贴上歌词）再翻唱；这首没有歌词就把 use_lyrics 填 false')
      }

      // 开下一版（sv-artifact 的规矩：一版一个 rNN，交付后不许改）；接着上次的就不再开
      if (!resume) {
        mkdirSync(join(dir, id))
        const note = typeof args?.note === 'string' && args.note.trim() ? args.note.trim() : '翻唱（cover_run）'
        m.versions.push({ id, folder: id, created: stamp(), by: 'agent', note, sealed: null, files: {}, discarded: null })
        writeManifest(STORE, dir, m)
      } else {
        mkdirSync(join(dir, id), { recursive: true })
      }

      const label = `翻唱《${basename(dir)}》${id}`
      let child = null
      let cancelled = null
      const jobId = ctx.jobs.start({
        kind: 'cover',
        label,
        owner: session.id,
        run(job) {
          const log = (line) => { job.append(line + '\n', { channel: 'log' }); job.updateProgress(line) }
          let llamaStopped = false
          // 读 Worker 的进度：「完成 / 失败」给模型看（stdout），其余只给界面看（log）；跑的过程中每 2 秒读一次，Worker 退出后再补读一次
          let progressLine = 0
          const pump = () => {
            const { rows, next } = readProgress(join(dir, '日志', '进度.jsonl'), progressLine)
            progressLine = next
            for (const r of rows) {
              const text = `${r.步} ${r.状态}${r.说明 ? `：${r.说明}` : ''}`
              job.append(text + '\n', { channel: r.状态 === '完成' || r.状态 === '失败' ? 'stdout' : 'log' })
              job.updateProgress(text)
            }
          }
          // 进度文件里可能有上一版留下的行：从现在的末尾开始读
          progressLine = readProgress(join(dir, '日志', '进度.jsonl'), 0).next
          const body = async () => {
            await waitTurnEnd(session.id)
            if (cancelled) return { status: 'killed', detail: cancelled, result: `${label} 还没开始就停掉了；${id} 留着「进行中」` }
            const s = await llama.stop()
            llamaStopped = !/没开着|no-llama/.test(s)
            log(s)
            if (cancelled) return { status: 'killed', detail: cancelled, result: `${label} 还没开始就停掉了；${id} 留着「进行中」` }
            const outFile = join(dir, '日志', `cover_${id}.out`)
            mkdirSync(join(dir, '日志'), { recursive: true })
            let argv = [PYTHON, WORKER, dir, '--round', id, '--source', source, ...(useLyrics ? [] : ['--lyrics', 'none']),
              ...(octavePick ? [] : ['--octave-pick', 'off'])]
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
            const summaryFile = join(dir, '日志', `翻唱_${id}.json`)
            const summary = existsSync(summaryFile) ? JSON.parse(readFileSync(summaryFile, 'utf8')) : null
            if (cancelled) {
              return { status: 'killed', detail: cancelled, result: `${label} 被停掉了；${id} 留着「进行中」（做完的步下次跳过）` }
            } else if (code === 0 && summary?.结果 === '完成') {
              const m2 = readManifest(STORE, dir)
              const files = sealVersion(dir, m2, id, '翻唱跑完自动交付')
              writeManifest(STORE, dir, m2)
              const p = readProject(dir)
              if (p && !p.error) {
                p.status = `${id} 翻唱出来了（${stamp()}），等创作者听`
                p.notes = [...(Array.isArray(p.notes) ? p.notes : []), `${stamp()}：cover_run ${id} 完成，共 ${Math.round(summary.总秒 / 60)} 分钟`]
                p.updated = stamp()
                writeProject(dir, p)
              }
              const st = summary.统计 ?? {}
              return { status: 'completed', result: `${label} 跑完了，${Math.round(summary.总秒 / 60)} 分钟；已交付 ${id}（${files.length} 个文件）。`
                + `工程：${st.工程}；扒出 ${st.扒出的音} 个音，改了 ${st.改八度} 个八度。说明在 ${join(dir, id, '说明.md')}；用 present 把工程交给创作者听。` }
            }
            const why = summary?.原因 ?? `Worker 退出码 ${code}（看 ${outFile}）`
            return { status: 'failed', detail: why, result: `${label} 没跑完：${summary?.步 ?? ''} ${why}。${id} 留着「进行中」；修好以后再跑一次会接着做（做完的步跳过）` }
          }
          // 不管成功、失败、被停、还是插件自己出错：让出过的大模型一定载回来
          const done = body()
            .catch((e) => ({ status: 'failed', detail: String(e?.message ?? e), result: `${label} 插件出错：${e?.message ?? e}；${id} 留着「进行中」` }))
            .then(async (outcome) => { if (llamaStopped) log(await llama.start()); return outcome })
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
      return `开始了：${label}（后台任务 ${jobId}${resume ? `；接着上次没跑完的 ${id}，做完的步跳过` : ''}）。${lyricNote}${octavePick ? '' : '；这一版不挑八度'}。来源：${source}。约 15–25 分钟（分离约 2 分钟、找拍子十几分钟）；`
        + '这段时间本地大模型会让出来，聊不了天；跑完自动载回，你会被唤醒、再告诉创作者结果。现在简短告诉创作者，然后结束这一轮。'
    },
  })
}
