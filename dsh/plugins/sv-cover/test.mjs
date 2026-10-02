// sv-cover 插件自检（不启动 DSH、不跑真的翻唱链路、不碰真的大模型）：node test.mjs
// 假 Worker（node 小脚本，命令行和 cover_run.py 一样）+ 假的大模型开关 + 假的会话事件；
// 照真的顺序走：创作者贴歌词 → 调 cover_run → 这一轮没说完不能让出大模型 → 说完才让、才跑 → 交付、记状态、载回。
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, findLyrics } from './index.js'
import { readManifest } from '../sv-artifact/index.js'
import { addEntry, readMem, setState, songFile, writeMem } from '../sv-memory/index.js'

const base = mkdtempSync(join(tmpdir(), 'sv-cover-test-'))
const root = join(base, 'ws')
const store = join(base, 'store')
const P = join(root, '测试歌')
let failed = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`ok   ${label}`) } catch (e) { failed += 1; console.log(`FAIL ${label}\n     ${e.stack?.split('\n').slice(0, 2).join(' | ')}`) }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 假 Worker：照 cover_run.py 的样子写 日志\进度.jsonl、rNN\工程、日志\翻唱_rNN.json；按 source 决定成功 / 失败 / 一直跑
const FAKE = join(base, 'fake_worker.mjs')
writeFileSync(FAKE, `
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, basename } from 'node:path'
const [dir, , round, , source, ...rest] = process.argv.slice(2)
mkdirSync(join(dir, '日志'), { recursive: true })
writeFileSync(join(dir, '日志', 'args_' + round + '.json'), JSON.stringify(process.argv.slice(2)))
const note = (步, 状态, 说明 = '') => appendFileSync(join(dir, '日志', '进度.jsonl'), JSON.stringify({ 秒: 0, 步, 状态, 说明 }) + '\\n')
note('开始', '开始'); note('分离', '完成', '核对通过')
if (source.endsWith('FAIL.wav')) { note('找拍子', '失败', '故意失败'); writeFileSync(join(dir, '日志', '翻唱_' + round + '.json'), JSON.stringify({ 结果: '失败', 步: '找拍子', 原因: '故意失败' })); process.exit(1) }
if (source.endsWith('SLOW.wav')) { await new Promise((r) => setTimeout(r, 60000)) }
const name = basename(dir)
mkdirSync(join(dir, round), { recursive: true })
writeFileSync(join(dir, round, name + '_扒谱_' + round + '.svp'), '{"fake":true}')
writeFileSync(join(dir, round, '说明.md'), 'fake')
writeFileSync(join(dir, '日志', '翻唱_' + round + '.json'), JSON.stringify({ 结果: '完成', 总秒: 61, 统计: { 工程: join(dir, round, name + '_扒谱_' + round + '.svp'), 扒出的音: 580, 改八度: 2 } }))
note('结束', '完成')
`)

let dispose = () => {}
try {
  mkdirSync(join(P, '素材'), { recursive: true })
  writeFileSync(join(P, 'sv-project.json'), JSON.stringify({ schema: 'sv-agent/project@1', name: '测试歌', kind: 'cover', status: '刚建', notes: [] }))
  const wav = (n) => { const p = join(base, n); writeFileSync(p, 'RIFF'); return p }
  const OK = wav('OK.wav'), BAD = wav('FAIL.wav'), SLOW = wav('SLOW.wav')

  check('找歌词：最后一条有「歌词：」的消息，取标记后面的全部', () => {
    assert.equal(findLyrics(['你好', '歌词：\n第一句\n第二句', '开始吧']), '第一句\n第二句')
    assert.equal(findLyrics(['歌词:一句']), '一句')
    assert.equal(findLyrics(['翻唱这首 https://x\n歌词：\nA\nB']), 'A\nB')
    assert.equal(findLyrics(['没有歌词标记的消息', '歌词：']), null)
  })

  // ---- 假 ctx ----
  const tools = new Map()
  const listeners = new Map()
  const jobs = []
  const llamaCalls = []
  const ctx = {
    tools: { register: (t) => { tools.set(t.name, t) } },
    on: (name, fn) => { listeners.set(name, fn) },
    jobs: { start: (spec) => { const id = `cover-${jobs.length + 1}`; const hooks = spec.run({ id, append: (t, o) => { (spec.out ??= []).push([o?.channel, t]) }, updateProgress: () => {} }); jobs.push({ id, spec, hooks }); return id } },
    sandboxPolicy: { resolve: () => ({ mode: 'workspace-write', workspaceRoot: P }) },
    sandbox: { confine: async (argv) => ({ argv }) },
  }
  const fakeLlama = () => ({ stop: async () => { llamaCalls.push('stop'); return '本地大模型让出来了（假）' }, start: async () => { llamaCalls.push('start'); return '本地大模型载回来了（假）' } })
  apply(ctx, { root, store, python: process.execPath, worker: FAKE, sandbox: true, makeLlama: fakeLlama })
  const session = { id: 's1', header: { cwd: P } }
  const userSays = (text) => listeners.get('session/event')(session, { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text }] } })
  const turnEnds = () => listeners.get('session/event')(session, { type: 'turn/end', data: {} })
  const run = (args, cwd = P) => tools.get('cover_run').execute(args, { agent: { session: { ...session, header: { cwd } } } })

  await check('登记了 cover_run 和会话事件监听', () => {
    assert.ok(tools.has('cover_run'))
    assert.ok(listeners.has('session/event'))
  })

  await check('不在项目里 → 拒绝；没给歌词 → 拒绝（不开版本）', async () => {
    await assert.rejects(run({ source: OK }, root), /不在任何项目里/)
    await assert.rejects(run({ source: OK }), /没找到歌词/)
    assert.equal(readManifest(store, P).versions.length, 0)
  })

  const LYRICS = '《测试歌》\n主歌\n第一句，有标点！\n第二句 ４ 秒'
  await check('贴歌词 → 调 cover_run：歌词原样存进项目、开了 r01、任务起来了；这一轮没说完不让出大模型', async () => {
    userSays(`歌词：\n${LYRICS}`)
    userSays('开始翻唱吧')
    const out = await run({ source: OK })
    assert.match(out, /开始了：翻唱《测试歌》r01/)
    assert.equal(readFileSync(join(P, '素材', '歌词_原文.txt'), 'utf8'), LYRICS + '\n', '原样，一个字都不改')
    assert.equal(readManifest(store, P).versions[0].id, 'r01')
    await sleep(300)
    assert.deepEqual(llamaCalls, [], 'Agent 这一轮还没说完：大模型不能让')
    await assert.rejects(run({ source: OK }), /已经在跑了/)
  })

  await check('这一轮说完 → 让出大模型 → 跑 → 交付 r01、记项目状态 → 载回大模型', async () => {
    turnEnds()
    const outcome = await jobs[0].hooks.done
    assert.equal(outcome.status, 'completed', JSON.stringify(outcome))
    assert.match(outcome.result, /已交付 r01（2 个文件）/)
    assert.deepEqual(llamaCalls, ['stop', 'start'])
    const v = readManifest(store, P).versions[0]
    assert.ok(v.sealed, '交付了')
    assert.deepEqual(Object.keys(v.files).sort(), ['r01/测试歌_扒谱_r01.svp', 'r01/说明.md'])
    const proj = JSON.parse(readFileSync(join(P, 'sv-project.json'), 'utf8'))
    assert.match(proj.status, /^r01 翻唱出来了/)
    assert.match(proj.notes.at(-1), /cover_run r01 完成，共 1 分钟/)
    const args = JSON.parse(readFileSync(join(P, '日志', 'args_r01.json'), 'utf8'))
    assert.ok(!args.includes('none'), '用了歌词')
    assert.ok(!args.includes('--octave-pick'), '默认挑八度：不传开关')
    const stdout = jobs[0].spec.out.filter(([c]) => c === 'stdout').map(([, t]) => t).join('')
    assert.match(stdout, /分离 完成/, '模型看得到里程碑')
  })

  await check('Worker 失败 → 任务失败、r02 留着进行中（不交付）、大模型照样载回', async () => {
    llamaCalls.length = 0
    const out = await run({ source: BAD, use_lyrics: false })
    assert.match(out, /r02/)
    turnEnds()
    const outcome = await jobs[1].hooks.done
    assert.equal(outcome.status, 'failed')
    assert.match(outcome.result, /找拍子 故意失败/)
    assert.deepEqual(llamaCalls, ['stop', 'start'])
    const v = readManifest(store, P).versions.find((x) => x.id === 'r02')
    assert.equal(v.sealed, null)
    const args = JSON.parse(readFileSync(join(P, '日志', 'args_r02.json'), 'utf8'))
    assert.deepEqual(args.slice(-2), ['--lyrics', 'none'], '不用歌词时告诉 Worker')
  })

  await check('创作者点停止 → 子程序停掉、任务 killed、大模型载回', async () => {
    llamaCalls.length = 0
    const out = await run({ source: SLOW })
    assert.match(out, /接着上次没跑完的 r02/)
    assert.deepEqual(readManifest(store, P).versions.map((v) => v.id), ['r01', 'r02'], '没有多开 r03')
    turnEnds()
    await sleep(1500)
    jobs[2].hooks.cancel('测试：创作者停掉了')
    const outcome = await jobs[2].hooks.done
    assert.equal(outcome.status, 'killed')
    assert.deepEqual(llamaCalls, ['stop', 'start'])
  })

  await check('换了歌词：旧的两份改名留着（不删），换上新的', async () => {
    writeFileSync(join(P, '素材', '歌词_要唱的字.txt'), '旧的清理结果\n')
    userSays('歌词：\n新的一句')
    await run({ source: OK })
    const files = readdirSync(join(P, '素材')).sort()
    assert.ok(files.some((f) => /^歌词_原文_r02之前\.txt$/.test(f)), files.join(','))
    assert.ok(files.some((f) => /^歌词_要唱的字_r02之前\.txt$/.test(f)), files.join(','))
    assert.equal(readFileSync(join(P, '素材', '歌词_原文.txt'), 'utf8'), '新的一句\n')
    turnEnds()
    await jobs[3].hooks.done
  })

  await check('创作者说「这首不挑八度」→ octave_pick false → 告诉 Worker --octave-pick off（10-01 加的开关，默认开）', async () => {
    const out = await run({ source: OK, octave_pick: false })
    assert.match(out, /这一版不挑八度/)
    turnEnds()
    const outcome = await jobs[4].hooks.done
    assert.equal(outcome.status, 'completed', JSON.stringify(outcome))
    const id = readManifest(store, P).versions.at(-1).id
    const args = JSON.parse(readFileSync(join(P, '日志', `args_${id}.json`), 'utf8'))
    assert.deepEqual(args.slice(-2), ['--octave-pick', 'off'])
  })

  // ---- 阶段 6：记忆里生效的偏好（另起一个带记忆库的插件实例、另一首歌）----
  const memStore = join(base, 'memory')
  const Q = join(root, '记忆歌')
  mkdirSync(join(Q, '素材'), { recursive: true })
  writeFileSync(join(Q, 'sv-project.json'), JSON.stringify({ schema: 'sv-agent/project@1', name: '记忆歌', kind: 'cover', status: '刚建', notes: [] }))
  writeFileSync(join(Q, '素材', '歌词_原文.txt'), '一句\n')
  const mem = readMem(songFile(memStore, Q))
  const pe = addEntry(mem, 's', { 类: '偏好', 原话: '这首不挑八度', 理解: '这首翻唱不挑八度', 来源: { 时间: 't', 怎么来的: '测试' }, 范围: '这首歌', 强度: '尽量', 状态: '待确认', 动作: { octave_pick: false } })
  setState(mem, pe.id, '生效', '测试')
  writeMem(songFile(memStore, Q), mem)
  const tools2 = new Map()
  const listeners2 = new Map()
  const jobs2 = []
  apply({ ...ctx, tools: { register: (t) => tools2.set(t.name, t) }, on: (n, fn) => listeners2.set(n, fn),
    jobs: { start: (spec) => { const jid = `mem-${jobs2.length + 1}`; const hooks = spec.run({ id: jid, append: () => {}, updateProgress: () => {} }); jobs2.push({ id: jid, spec, hooks }); return jid } } },
  { root, store, python: process.execPath, worker: FAKE, sandbox: true, makeLlama: fakeLlama, memory: memStore })
  const s2 = { id: 's2', header: { cwd: Q } }
  const run2 = (args) => tools2.get('cover_run').execute(args, { agent: { session: s2 } })
  const end2 = () => listeners2.get('session/event')(s2, { type: 'turn/end', data: {} })

  await check('记忆：这首记着「不挑八度」、这次没说 → 照偏好不挑；交付后偏好记下「用过」', async () => {
    const out = await run2({ source: OK })
    assert.match(out, /用了偏好 本首 s1/)
    end2()
    const outcome = await jobs2[0].hooks.done
    assert.equal(outcome.status, 'completed', JSON.stringify(outcome))
    const args = JSON.parse(readFileSync(join(Q, '日志', 'args_r01.json'), 'utf8'))
    assert.ok(args.includes('--octave-pick') && args[args.indexOf('--octave-pick') + 1] === 'off', args.join(' '))
    assert.match(args[args.indexOf('--prefs-used') + 1], /用了偏好 本首 s1/)
    const used = readMem(songFile(memStore, Q)).entries.find((x) => x.id === pe.id).用过
    assert.equal(used.length, 1)
    assert.equal(used[0].版本, 'r01')
  })

  await check('记忆：模型照着偏好自己传了 octave_pick false → 也算用了这条（记「用过」、说明里写上）', async () => {
    const before = readMem(songFile(memStore, Q)).entries.find((x) => x.id === pe.id).用过.length
    const out = await run2({ source: OK, octave_pick: false })
    assert.match(out, /用了偏好 本首 s1/)
    end2()
    await jobs2[1].hooks.done
    const args = JSON.parse(readFileSync(join(Q, '日志', 'args_r02.json'), 'utf8'))
    assert.match(args[args.indexOf('--prefs-used') + 1], /用了偏好/)
    assert.equal(readMem(songFile(memStore, Q)).entries.find((x) => x.id === pe.id).用过.length, before + 1)
  })

  await check('记忆：这次明说要挑八度 → 照这次的（当前指令优先），偏好不动、不记「用过」', async () => {
    const out = await run2({ source: OK, octave_pick: true })
    assert.match(out, /这次照创作者现在说的挑八度/)
    end2()
    await jobs2[2].hooks.done
    const args = JSON.parse(readFileSync(join(Q, '日志', 'args_r03.json'), 'utf8'))
    assert.ok(!args.includes('--octave-pick'), args.join(' '))
    const e = readMem(songFile(memStore, Q)).entries.find((x) => x.id === pe.id)
    assert.equal(e.状态, '生效')
    assert.equal(e.用过.length, 2, '前两次用过、这次没用')
  })
} finally {
  try { dispose?.() } catch { /* 没有 */ }
  rmSync(base, { recursive: true, force: true })   // 只删这次测试自己建的临时目录
}

console.log(failed === 0 ? '\n全部通过' : `\n${failed} 项没过`)
process.exitCode = failed === 0 ? 0 : 1
