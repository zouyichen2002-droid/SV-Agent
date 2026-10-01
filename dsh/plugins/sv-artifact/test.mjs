// sv-artifact 插件自检（不启动 DSH）：node test.mjs
// 照创作者真用的顺序走一遍：Agent 开一版 → 写 → 交付 → 创作者在 SV 里改了存盘 / 另存 / 再改 → 挪走又放回 → 弃用；
// 快照一律直接比对拷出来的文件内容（第二个裁判），最后用真的 fs.watch 测「一存盘就备份」。
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, artifactContext, checkSealed, nextVersionId, readManifest, sealVersion, writeManifest } from './index.js'

const base = mkdtempSync(join(tmpdir(), 'sv-artifact-test-'))
const root = join(base, 'ws')
const store = join(base, 'store')
const P = join(root, '测试歌')
let failed = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`ok   ${label}`) } catch (e) { failed += 1; console.log(`FAIL ${label}\n     ${e.message}`) }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const snaps = (song, version) => { const d = join(store, song, '快照', version); return existsSync(d) ? readdirSync(d).sort() : [] }
// 直接调函数的几项放在项目根外面（不被 fs.watch 盯着），免得和后台的自动检查抢着改清单
const Q = join(base, 'direct', '直测歌')

let dispose = () => {}
try {
  mkdirSync(P, { recursive: true })
  writeFileSync(join(P, 'sv-project.json'), JSON.stringify({ schema: 'sv-agent/project@1', name: '测试歌', kind: 'cover' }))

  await check('下一版编号：空 → r01；有 r01、弃用_r03 → r04；清单里记过 r05 → r06', () => {
    const empty = { versions: [] }
    assert.equal(nextVersionId(P, empty), 'r01')
    mkdirSync(join(P, 'r01')); mkdirSync(join(P, '弃用_r03（试）'))
    assert.equal(nextVersionId(P, empty), 'r04')
    assert.equal(nextVersionId(P, { versions: [{ id: 'r05' }] }), 'r06')
    rmSync(join(P, 'r01'), { recursive: true }); rmSync(join(P, '弃用_r03（试）'), { recursive: true })   // 只删测试自己刚建的
  })

  await check('快照库放在项目根下面 → 拒绝', () => {
    assert.throws(() => apply({ tools: {}, systemPrompt: {}, effect() {} }, { root, store: join(root, 'store') }), /快照库不能放在项目根下面/)
  })

  // ---- 假的 ctx ----
  const tools = new Map()
  const contexts = []
  const guards = []
  const ctx = {
    tools: { register: (t) => { tools.set(t.name, t) }, guard: (g) => { guards.push(g) } },
    systemPrompt: { context: (c) => { contexts.push(c) } },
    effect: (fn) => { dispose = fn() },
  }
  apply(ctx, { root, store })
  const exec = (cwd, name, args) => ({ name, arguments: args, agent: { session: { header: { cwd } } } })
  const run = (name, args, cwd = P) => tools.get(name).execute(args, exec(cwd, name, args))
  const guard = (name, args, cwd = P) => guards[0](exec(cwd, name, args))
  const ctxText = (cwd = P) => contexts[0].text({ agent: { session: { header: { cwd } } } })
  const svp = join(P, 'r01', '测试歌_扒谱_r01.svp')

  await check('登记了 4 个工具、1 段上下文、1 个拦截', () => {
    assert.deepEqual([...tools.keys()].sort(), ['artifact_discard', 'artifact_list', 'artifact_new_version', 'artifact_seal'])
    assert.equal(contexts.length, 1)
    assert.equal(guards.length, 1)
    assert.match(ctxText(), /版本：还没有/)
  })

  await check('开 r01 → 写文件 → 没交付前可以随便改', async () => {
    const out = await run('artifact_new_version', { note: '第一版扒谱' })
    assert.match(out, /开了 r01/)
    writeFileSync(svp, 'agent-v1')
    writeFileSync(join(P, 'r01', '说明.md'), 'readme')
    assert.equal(guard('write', { file_path: svp, content: 'x' }), undefined)
    assert.match(ctxText(), /r01 进行中/)
  })

  await check('交付 r01：清单里记下两个文件的指纹（清单在快照库里，不在项目文件夹里）', async () => {
    const out = await run('artifact_seal', { version: 'r01' })
    assert.match(out, /r01 交付了，2 个文件/)
    const m = readManifest(store, P)
    assert.deepEqual(Object.keys(m.versions[0].files).sort(), ['r01/测试歌_扒谱_r01.svp', 'r01/说明.md'])
    assert.ok(existsSync(join(store, '测试歌', 'artifacts.json')))
    assert.equal(existsSync(join(P, 'artifacts.json')), false)
    await assert.rejects(run('artifact_seal', { version: 'r01' }), /已经在 .* 交付过了/)
  })

  await check('拦截：已交付版本里的写 / 改 / 新加都拒绝；别处不管', () => {
    assert.match(guard('write', { file_path: svp, content: 'x' }) ?? '', /r01 已经在 .* 交付给创作者/)
    assert.match(guard('edit', { file_path: 'r01/说明.md', old_string: 'a', new_string: 'b' }) ?? '', /不能覆盖/, '相对路径按会话目录算')
    assert.match(guard('write', { file_path: join(P, 'r01', '新文件.txt'), content: 'x' }) ?? '', /也不能往里加/)
    assert.equal(guard('write', { file_path: join(P, 'r02', 'x.svp'), content: 'x' }), undefined)
    assert.equal(guard('write', { file_path: join(base, 'elsewhere.txt'), content: 'x' }), undefined)
    assert.equal(guard('read', { file_path: svp }), undefined)
    assert.equal(guard('pwsh', { command: `Set-Content ${svp} x` }), undefined, 'pwsh 拦不住（靠快照兜底）')
  })

  // ---- 直接调函数：创作者的各种改动（在 Q，不在被盯着的根下面）----
  mkdirSync(join(Q, 'r01'), { recursive: true })
  const qsvp = join(Q, 'r01', '直测歌_扒谱_r01.svp')
  writeFileSync(qsvp, 'agent-v1')
  writeFileSync(join(Q, 'r01', '说明.md'), 'readme')
  const m = { schema: 'sv-agent/artifacts@1', versions: [{ id: 'r01', folder: 'r01', created: 'x', by: 'agent', sealed: null, files: {}, discarded: null }], edits: [] }
  sealVersion(Q, m, 'r01')

  await check('没动过：查了不记', () => {
    assert.deepEqual(checkSealed(store, Q, m), [])
  })

  await check('创作者在 SV 里改了存盘 → 记「改了」+ 快照内容就是改后的', () => {
    writeFileSync(qsvp, 'creator-edit-1')
    const found = checkSealed(store, Q, m)
    assert.deepEqual(found.map((e) => [e.kind, e.file]), [['changed', 'r01/直测歌_扒谱_r01.svp']])
    assert.equal(readFileSync(found[0].snapshot, 'utf8'), 'creator-edit-1')
    assert.match(found[0].snapshot, /直测歌_扒谱_r01_作者改_\d{8}-\d{6}\.svp$/)
    assert.deepEqual(checkSealed(store, Q, m), [], '同样的内容不重复拷')
  })

  await check('创作者在这一版里另存了一份 → 「新加了」+ 快照；再改它 → 「改了」（不是又一次新加）', () => {
    const extra = join(Q, 'r01', '直测歌_扒谱_r01_改.svp')
    writeFileSync(extra, 'save-as-1')
    let found = checkSealed(store, Q, m)
    assert.deepEqual(found.map((e) => e.kind), ['added'])
    assert.equal(readFileSync(found[0].snapshot, 'utf8'), 'save-as-1')
    writeFileSync(extra, 'save-as-2')
    found = checkSealed(store, Q, m)
    assert.deepEqual(found.map((e) => e.kind), ['changed'])
    assert.equal(readFileSync(found[0].snapshot, 'utf8'), 'save-as-2')
  })

  await check('挪走一个文件 → 「没了」；原样放回来 → 「放回来了」（不再拷）', () => {
    const readme = join(Q, 'r01', '说明.md')
    renameSync(readme, join(base, '说明.md'))
    assert.deepEqual(checkSealed(store, Q, m).map((e) => e.kind), ['missing'])
    assert.deepEqual(checkSealed(store, Q, m), [], '「没了」只记一次')
    renameSync(join(base, '说明.md'), readme)
    const before = snaps('直测歌', 'r01').length
    assert.deepEqual(checkSealed(store, Q, m).map((e) => e.kind), ['back'])
    assert.equal(snaps('直测歌', 'r01').length, before)
  })

  await check('上下文：r01 已交付、创作者动过几处（改了 2、新加 1、没了 1；放回来不算）', () => {
    assert.match(artifactContext(m), /r01 已交付（创作者动过 4 处，快照已存）/)
  })

  await check('开 r02 → 上下文里 r02 进行中排前面；弃用 r02 → 改名不删、编号不复用', async () => {
    await run('artifact_new_version', { note: '试一版' })
    writeFileSync(join(P, 'r02', 'x.svp'), 'r02')
    assert.match(ctxText(), /版本：r02 进行中；r01 已交付/)
    const out = await run('artifact_discard', { version: 'r02', reason: '测试用' })
    assert.match(out, /r02 弃用了/)
    assert.ok(existsSync(join(P, '弃用_r02（测试用）', 'x.svp')), '文件还在')
    assert.equal(existsSync(join(P, 'r02')), false)
    assert.equal(nextVersionId(P, readManifest(store, P)), 'r03')
    assert.match(ctxText(), /弃用 1 版/)
    await assert.rejects(run('artifact_discard', { version: 'r02', reason: 'x' }), /没有可以弃用的 r02/)
    await assert.rejects(run('artifact_discard', { version: 'r01', reason: 'a/b' }), /reason 里不能有/)
  })

  await check('大厅里用不了版本工具', async () => {
    await assert.rejects(run('artifact_new_version', {}, root), /不在任何项目里/)
    assert.equal(ctxText(root), '')
  })

  await check('真的盯文件：创作者一存盘，约 2 秒后自动备份（不用任何工具调用）', async () => {
    const before = readManifest(store, P).edits.length
    writeFileSync(svp, 'creator-edit-2')
    await sleep(3500)
    const after = readManifest(store, P)
    assert.equal(after.edits.length, before + 1, `应该多 1 条，实际 ${after.edits.length - before}`)
    const last = after.edits.at(-1)
    assert.equal(last.kind, 'changed')
    assert.equal(readFileSync(last.snapshot, 'utf8'), 'creator-edit-2')
  })

  await check('列表里看得到每次改动和快照路径', async () => {
    const out = await run('artifact_list', {})
    assert.match(out, /r01：.* 交付/)
    assert.match(out, /创作者改了 r01\/测试歌_扒谱_r01\.svp；快照 /)
    assert.match(out, /r02：弃用（测试用）/)
  })
} finally {
  try { dispose?.() } catch { /* 已经关了 */ }
  rmSync(base, { recursive: true, force: true })   // 只删这次测试自己建的临时目录
}

console.log(failed === 0 ? '\n全部通过' : `\n${failed} 项没过`)
process.exitCode = failed === 0 ? 0 : 1
