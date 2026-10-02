// sv-memory 插件自检（不启动 DSH）：node test.mjs
// 假 ctx（工具、守卫、运行时上下文、会话事件）+ 临时的项目根 / 记忆库 / 版本库，照真的顺序走：
// 创作者评价一版 → 记原话（转述的拒绝）→ 提议偏好 → 他还没回答不许生效 → 他点头才生效 → 翻唱时套用 → 删 / 停用 / 被覆盖。
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, coverActions, globalFile, isVerbatim, memoryContext, readMem, recordUse, renderMd, songFile, writeMem, addEntry, setState } from './index.js'
import { writeManifest } from '../sv-artifact/index.js'

const base = mkdtempSync(join(tmpdir(), 'sv-memory-test-'))
const root = join(base, 'ws')
const store = join(base, 'memory')
const artifacts = join(base, 'snapshots')
const P = join(root, '测试歌')
let failed = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`ok   ${label}`) } catch (e) { failed += 1; console.log(`FAIL ${label}\n     ${e.stack?.split('\n').slice(0, 2).join(' | ')}`) }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

try {
  mkdirSync(P, { recursive: true })
  writeFileSync(join(P, 'sv-project.json'), JSON.stringify({ schema: 'sv-agent/project@1', name: '测试歌', kind: 'cover', status: '刚建', notes: [] }))
  mkdirSync(join(P, 'r01'), { recursive: true })
  mkdirSync(join(P, 'r02'), { recursive: true })
  writeFileSync(join(P, 'r01', 'song.json'), JSON.stringify({ round: 'r01' }))            // 没写 octave_pick = 默认挑八度
  writeFileSync(join(P, 'r02', 'song.json'), JSON.stringify({ octave_pick: false }))
  writeManifest(artifacts, P, { schema: 'sv-agent/artifacts@1', project: '测试歌', versions: [
    { id: 'r01', folder: 'r01', created: '2026-10-01 10:00', sealed: '2026-10-01 10:20', files: {}, discarded: null },
    { id: 'r02', folder: 'r02', created: '2026-10-01 11:00', sealed: '2026-10-01 11:20', files: {}, discarded: null },
  ], edits: [] })

  await check('原话检查：去掉空白、全角半角引号当一样；转述、太短的不算', () => {
    const msgs = ['这版 八度 有几处不对，副歌那里', '另一条']
    assert.ok(isVerbatim('这版八度有几处不对', msgs))
    assert.ok(isVerbatim('副歌那里', msgs))
    assert.ok(!isVerbatim('八度错了好几个', msgs), '转述的不算')
    assert.ok(!isVerbatim('这', msgs), '一个字不算')
    assert.ok(isVerbatim('嗯', ['嗯'], 1), '确认可以只有一个字')
  })

  await check('记忆库放在项目根下面 → 不许', () => {
    assert.throws(() => apply({ tools: { register() {}, guard() {} }, systemPrompt: { context() {} }, on() {} }, { root, store: join(root, 'mem') }), /不能放在项目根下面/)
  })

  // ---- 假 ctx ----
  const tools = new Map()
  const guards = []
  const contexts = []
  const listeners = new Map()
  apply({
    tools: { register: (t) => tools.set(t.name, t), guard: (g) => guards.push(g) },
    systemPrompt: { context: (c) => contexts.push(c) },
    on: (n, fn) => listeners.set(n, fn),
  }, { root, store, artifacts })
  const session = { id: 'sess-1', header: { cwd: P } }
  const userSays = (text) => listeners.get('session/event')(session, { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text }] } })
  const call = (name, args, cwd = P) => tools.get(name).execute(args, { agent: { session: { ...session, header: { cwd } } } })
  const ctxText = (cwd = P) => contexts[0].text({ agent: { session: { header: { cwd } } } })

  await check('登记了 4 个工具、1 段运行时上下文、1 个守卫、会话事件监听', () => {
    assert.deepEqual([...tools.keys()].sort(), ['memory_change', 'memory_confirm', 'memory_list', 'memory_record'])
    assert.equal(contexts.length, 1)
    assert.equal(guards.length, 1)
    assert.ok(listeners.has('session/event'))
  })

  await check('反馈：原样摘原话 → 记在这首、挂在 r02 上；转述的拒绝；没有的版本拒绝；清单文件写出来了', async () => {
    userSays('r02 这版很好，就是 1:16 那句八度不对')
    await assert.rejects(call('memory_record', { kind: '反馈', quote: 'r02 很好但八度错了', understanding: 'x' }), /原样摘/)
    await assert.rejects(call('memory_record', { kind: '反馈', quote: '1:16 那句八度不对', understanding: 'x', version: 'r09' }), /没有 r09/)
    const out = await call('memory_record', { kind: '反馈', quote: '1:16 那句八度不对', understanding: 'r02 的 1:16 那句八度扒错了', version: 'r02', position: '1:16' })
    assert.match(out, /记下了：《测试歌》 s1（r02）/)
    const m = readMem(songFile(store, P))
    assert.equal(m.entries[0].原话, '1:16 那句八度不对')
    assert.equal(m.entries[0].状态, '记下了')
    assert.ok(existsSync(join(P, '记忆.md')))
    assert.match(readFileSync(join(P, '记忆.md'), 'utf8'), /1:16 那句八度不对/)
    assert.match(ctxText(), /他说过 r02：「1:16 那句八度不对」/)
  })

  await check('「他说好」只是反馈：不会变成偏好（PRD §6.5）', () => {
    const m = readMem(songFile(store, P))
    assert.equal(m.entries.filter((e) => e.类 === '偏好').length, 0)
  })

  await check('大厅里（不在哪首歌下面）的反馈记成全局的 g1', async () => {
    userSays('交付以后我直接开 SV 听就行')
    const out = await call('memory_record', { kind: '反馈', quote: '我直接开 SV 听就行', understanding: '不用试听' }, root)
    assert.match(out, /全局 g1/)
    assert.equal(readMem(globalFile(store)).entries[0].id, 'g1')
  })

  let pid
  await check('提议偏好 → 待确认；他还没回答就确认 → 拒绝；他点头以后才生效，原话存下来', async () => {
    userSays('这首以后都别挑八度了')
    const out = await call('memory_record', { kind: '偏好', quote: '这首以后都别挑八度了', understanding: '这首翻唱不挑八度', octave_pick: false })
    pid = /偏好 (s\d+)/.exec(out)[1]
    assert.match(out, /待确认/)
    assert.match(ctxText(), /待创作者确认的偏好 1 条/)
    assert.deepEqual(coverActions(store, P), [], '待确认的不能用')
    await assert.rejects(call('memory_confirm', { id: pid, decision: '生效', answer_quote: '这首以后都别挑八度了' }), /提议之后/)
    await sleep(5)
    userSays('对，记吧')
    await call('memory_confirm', { id: pid, decision: '生效', answer_quote: '对，记吧' })
    const e = readMem(songFile(store, P)).entries.find((x) => x.id === pid)
    assert.equal(e.状态, '生效')
    assert.equal(e.确认.原话, '对，记吧')
    assert.match(ctxText(), new RegExp(`偏好 ${pid} 这首翻唱不挑八度`))
  })

  await check('翻唱时套用：这首的「不挑八度」→ coverActions 给出 false；记一次用过', () => {
    const acts = coverActions(store, P)
    assert.equal(acts.length, 1)
    assert.equal(acts[0].value, false)
    assert.equal(acts[0].scope, '本首')
    recordUse(acts[0].file, acts[0].id, { 歌: '测试歌', 版本: 'r03', 怎么用的: '不挑八度' })
    assert.equal(readMem(songFile(store, P)).entries.find((x) => x.id === pid).用过.length, 1)
  })

  await check('全局说「挑」、这首说「不挑」→ 这首的优先', () => {
    const g = readMem(globalFile(store))
    const e = addEntry(g, 'g', { 类: '偏好', 原话: '默认挑八度', 理解: '默认挑八度', 来源: { 时间: '2026-10-01 12:00', 怎么来的: '测试' }, 范围: '所有歌', 强度: '尽量', 状态: '待确认', 动作: { octave_pick: true } })
    setState(g, e.id, '生效', '测试')
    writeMem(globalFile(store), g)
    const acts = coverActions(store, P)
    assert.equal(acts.find((a) => a.key === 'octave_pick').value, false)
    const other = join(root, '另一首')
    mkdirSync(other, { recursive: true })
    assert.equal(coverActions(store, other).find((a) => a.key === 'octave_pick').value, true, '别的歌照全局的')
  })

  await check('同一件事的新偏好生效 → 旧的变「被覆盖」', async () => {
    userSays('这首还是挑八度吧')
    const out = await call('memory_record', { kind: '偏好', quote: '这首还是挑八度吧', understanding: '这首挑八度', octave_pick: true })
    const nid = /偏好 (s\d+)/.exec(out)[1]
    await sleep(5)
    userSays('嗯')
    await call('memory_confirm', { id: nid, decision: '生效', answer_quote: '嗯' })
    const m = readMem(songFile(store, P))
    assert.equal(m.entries.find((x) => x.id === pid).状态, '被覆盖')
    assert.equal(m.entries.find((x) => x.id === nid).状态, '生效')
    assert.equal(coverActions(store, P).find((a) => a.key === 'octave_pick').value, true)
  })

  await check('改：引的要是记下以后说的话 —— 拿原来那句评价当理由 → 拒绝', async () => {
    await assert.rejects(call('memory_change', { id: 's1', to: '已删除', quote: '1:16 那句八度不对' }), /记下以后说的/)
  })

  await check('改：反馈「这条不算」→ 删；偏好停用 / 重新生效；待确认的不许用 memory_change 直接生效', async () => {
    await sleep(5)
    userSays('s1 这条不算')
    await call('memory_change', { id: 's1', to: '已删除', quote: 's1 这条不算' })
    const m = readMem(songFile(store, P))
    assert.equal(m.entries.find((x) => x.id === 's1').状态, '已删除')
    assert.doesNotMatch(ctxText(), /1:16 那句八度不对/, '删了的不再给模型看')
    assert.doesNotMatch(renderMd('x', m), /1:16 那句八度不对/)
    userSays('这首别挑八度这条先停用')
    const live = m.entries.find((x) => x.类 === '偏好' && x.状态 === '生效').id
    await call('memory_change', { id: live, to: '已停用', quote: '先停用' })
    assert.equal(coverActions(store, P).find((a) => a.key === 'octave_pick').value, true, '停用以后照全局的')
    userSays('这首别挑八度')
    const out = await call('memory_record', { kind: '偏好', quote: '这首别挑八度', understanding: 'y', octave_pick: false })
    const pend = /偏好 (s\d+)/.exec(out)[1]
    await assert.rejects(call('memory_change', { id: pend, to: '生效', quote: '这首别挑八度' }), /memory_confirm/)
  })

  await check('改理解：创作者纠正 → 理解换了、改动记下来', async () => {
    userSays('g1 的意思是试听不用做')
    await call('memory_change', { id: 'g1', understanding: '试听不用做，交付后他直接开 SV 听', quote: '试听不用做' }, root)
    const e = readMem(globalFile(store)).entries.find((x) => x.id === 'g1')
    assert.equal(e.理解, '试听不用做，交付后他直接开 SV 听')
    assert.ok(e.改动.some((c) => c.理解从 === '不用试听'))
  })

  await check('守卫：Agent 用 write / edit 碰 记忆.md → 拒绝；别的文件不管', () => {
    const g = guards[0]
    assert.match(g({ name: 'write', arguments: { file_path: join(P, '记忆.md') } }), /自动生成/)
    assert.match(g({ name: 'edit', arguments: { file_path: join(P, '记忆.md') } }), /自动生成/)
    assert.equal(g({ name: 'write', arguments: { file_path: join(P, 'r03', 'x.txt') } }), undefined)
    assert.equal(g({ name: 'read', arguments: { file_path: join(P, '记忆.md') } }), undefined)
  })

  await check('清单：版本历史带上了每版的设置（r02 不挑八度）', async () => {
    const out = await call('memory_list', {})
    assert.match(out, /r02：2026-10-01 11:20 交付；不挑八度/)
    assert.match(out, /r01：2026-10-01 10:20 交付；挑八度/)
  })

  await check('给模型的那段要短：全局 30 条生效偏好也不超过 1500 字', () => {
    const g = { entries: [] , next: 1 }
    for (let i = 0; i < 30; i += 1) {
      const e = addEntry(g, 'g', { 类: '偏好', 原话: `规矩 ${i}`, 理解: `这是第 ${i} 条比较长的偏好理解，用来测试长度上限会不会被截断`, 来源: { 时间: 't' }, 状态: '待确认' })
      setState(g, e.id, '生效', 't')
    }
    const t = memoryContext(g, null, null)
    assert.ok(t.length < 1500, `长度 ${t.length}`)
    assert.match(t, /等 30 条/)
  })

  await check('「流程里照做」的偏好只进清单、不每步给模型看（省上下文）；只说一共几条', () => {
    const g = { entries: [], next: 1 }
    const a = addEntry(g, 'g', { 类: '偏好', 原话: '音准更重要', 理解: '音准优先：修歌词只改字', 来源: { 时间: 't' }, 状态: '待确认', 处理方式: '流程里照做' })
    const b = addEntry(g, 'g', { 类: '偏好', 原话: '不用这个', 理解: '不做试听', 来源: { 时间: 't' }, 状态: '待确认' })
    setState(g, a.id, '生效', 't')
    setState(g, b.id, '生效', 't')
    const t = memoryContext(g, null, null)
    assert.doesNotMatch(t, /音准优先/)
    assert.match(t, /不做试听/)
    assert.match(t, /另有 1 条流程里已经照做/)
    assert.match(renderMd('x', g), /流程里照做：音准优先/)
  })
} finally {
  rmSync(base, { recursive: true, force: true })   // 只删这次测试自己建的临时目录
}

console.log(failed === 0 ? '\n全部通过' : `\n${failed} 项没过`)
process.exitCode = failed === 0 ? 0 : 1
