// sv-project 插件自检（不启动 DSH）：node test.mjs
// 在临时目录里搭一个项目根，测纯逻辑 + 用假的 ctx 调四个工具；写出来的 JSON 另外直接读回核对（第二个裁判）。
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, contextText, inventory, listProjects, nameProblem, projectDirOf, readProject } from './index.js'

const base = mkdtempSync(join(tmpdir(), 'sv-project-test-'))
const root = join(base, 'ws')
const sibling = join(base, 'ws2')            // 名字是 root 的前缀加一个字：不能被当成 root 下面
let failed = 0
const check = (label, fn) => {
  try { fn(); console.log(`ok   ${label}`) } catch (e) { failed += 1; console.log(`FAIL ${label}\n     ${e.message}`) }
}
const put = (p, body = 'x', mtimeSec) => {
  mkdirSync(join(p, '..'), { recursive: true })
  writeFileSync(p, body)
  if (mtimeSec !== undefined) utimesSync(p, mtimeSec, mtimeSec)
}

try {
  // ---- 搭场景 ----
  const A = join(root, '天星问')
  put(join(A, 'sv-project.json'), JSON.stringify({ schema: 'sv-agent/project@1', name: '天星问', kind: 'cover', status: 'r01；创作者「可以」',
    external: [{ label: '探针', path: join(base, 'probe') }], notes: ['导入'] }))
  put(join(A, 'r01', '天星问_r01.svp'), 'svp1', 1_700_000_000)
  put(join(A, 'r02', '天星问_r02.svp'), 'svp2', 1_700_000_500)   // 最新的工程
  put(join(A, '弃用_r00', 'old.svp'), 'old', 1_800_000_000)       // 更新但在弃用里：不能算
  put(join(A, '.cache', 'hidden.svp'), 'h', 1_800_000_000)         // 隐藏文件夹：不能算
  put(join(A, '歌词.txt'))
  put(join(A, '原曲整首.wav'))
  put(join(A, 'notes.txt'))
  put(join(A, 'a', 'b', 'c', 'too_deep.svp'))                      // 第 4 层：超过 SCAN_DEPTH，不算
  mkdirSync(join(root, '空文件夹'), { recursive: true })            // 没有 sv-project.json：不是项目
  put(join(root, '弃用_旧歌', 'sv-project.json'), JSON.stringify({ name: '旧歌', kind: 'cover' }))   // 弃用的：不列
  put(join(sibling, '假项目', 'sv-project.json'), JSON.stringify({ name: '假', kind: 'cover' }))

  // ---- 纯逻辑 ----
  check('歌名检查', () => {
    assert.equal(nameProblem('天星问'), null)
    assert.equal(nameProblem('逃跑的天使 (live)'), null)
    for (const bad of ['', ' 前空格', 'a/b', 'a\\b', 'a:b', '_x', '.x', '弃用_x', 'con', 'x.', 'x'.repeat(61), 42]) {
      assert.notEqual(nameProblem(bad), null, `应该拒绝 ${JSON.stringify(bad)}`)
    }
  })
  check('列项目：只认根下一层、有 sv-project.json、不是弃用的', () => {
    assert.deepEqual(listProjects(root).map(({ data }) => data.name), ['天星问'])
  })
  check('会话目录 → 项目', () => {
    assert.equal(projectDirOf(join(A, 'r01'), root), A)
    assert.equal(projectDirOf(A, root), A)
    assert.equal(projectDirOf(root, root), null, '根本身是大厅')
    assert.equal(projectDirOf(join(sibling, '假项目'), root), null, 'ws2 不在 ws 下面')
    assert.equal(projectDirOf(join(root, '空文件夹'), root), null)
    assert.equal(projectDirOf(undefined, root), null)
  })
  check('清点：跳过弃用 / 隐藏 / 太深，最新工程是 r02', () => {
    const inv = inventory(A)
    assert.deepEqual(inv.counts, { 工程: 2, MIDI: 0, 音频: 1, 歌词: 1, 其他: 1 })
    assert.ok(inv.newest['工程'].path.endsWith(join('r02', '天星问_r02.svp')), inv.newest['工程'].path)
  })
  check('大厅的上下文', () => {
    const t = contextText(root, root)
    assert.match(t, /SV 项目大厅/)
    assert.match(t, /已有项目 1 个：天星问（翻唱）/)
  })
  check('项目里的上下文：歌名、可写文件夹、状态、最新工程；两次一字不差', () => {
    const t = contextText(join(A, 'r02'), root)
    assert.match(t, /《天星问》（翻唱）/)
    assert.ok(t.includes(`文件夹：${A}`), t)
    assert.match(t, /状态：r01；创作者「可以」/)
    assert.match(t, /外部素材（只读）：探针/)
    assert.match(t, /最新工程 r02\\天星问_r02\.svp/)
    assert.equal(contextText(join(A, 'r02'), root), t)
    assert.equal(contextText(join(sibling, '假项目'), root), '', '根外面的目录不出上下文')
  })
  check('上下文够短（< 400 字）', () => {
    assert.ok([...contextText(A, root)].length < 400)
  })

  // ---- 用假 ctx 调工具 ----
  const tools = new Map()
  const contexts = []
  const registered = []
  const ctx = {
    tools: { register: (t) => { tools.set(t.name, t) } },
    systemPrompt: { context: (c) => { contexts.push(c) } },
    workspaceRegistry: { create: async (path, title) => { registered.push([path, title]); return { id: 'w', path, title } } },
  }
  apply(ctx, { root })
  const session = (cwd) => ({ agent: { session: { header: { cwd } } } })
  const run = (name, args, cwd) => tools.get(name).execute(args, session(cwd))

  check('登记了 4 个工具和 1 段上下文', () => {
    assert.deepEqual([...tools.keys()].sort(), ['project_create', 'project_list', 'project_status', 'project_update'])
    assert.equal(contexts.length, 1)
    assert.equal(contexts[0].text({ agent: { session: { header: { cwd: A } } } }), contextText(A, root))
    for (const t of tools.values()) {
      assert.equal(t.parameters.type, 'object')
      assert.deepEqual(t.output.render({}, 'hi'), [{ type: 'text', text: 'hi' }])
    }
  })

  const results = {}
  results.create = await run('project_create', { name: '新歌', kind: 'original', note: '先写词' }, root)
  results.adopt = await run('project_create', { name: '天星问' }, root)
  results.badKind = await run('project_create', { name: '没写类型' }, root).catch((e) => `ERR ${e.message}`)
  results.notProject = await run('project_create', { name: '空文件夹', kind: 'cover' }, root).catch((e) => `ERR ${e.message}`)
  results.badName = await run('project_create', { name: '../逃出去', kind: 'cover' }, root).catch((e) => `ERR ${e.message}`)
  results.update = await run('project_update', { status: 'r02 已交', note: '拍子再听一遍' }, join(A, 'r02'))
  results.updateEmpty = await run('project_update', {}, A).catch((e) => `ERR ${e.message}`)
  results.updateLobby = await run('project_update', { status: 'x' }, root).catch((e) => `ERR ${e.message}`)
  results.status = await run('project_status', {}, A)
  results.list = await run('project_list', {}, root)

  check('新建：文件夹 + JSON + 登记工作区', () => {
    const dir = join(root, '新歌')
    const data = JSON.parse(readFileSync(join(dir, 'sv-project.json'), 'utf8'))   // 直接读文件，不信工具的返回
    assert.equal(data.schema, 'sv-agent/project@1')
    assert.equal(data.name, '新歌')
    assert.equal(data.kind, 'original')
    assert.match(data.notes[0], /先写词$/)
    assert.deepEqual(registered[0], [dir, '新歌'])
    assert.match(results.create, /新建了项目《新歌》（原创）/)
  })
  check('认领已有项目：只登记、内容不变', () => {
    const before = readFileSync(join(A, 'sv-project.json'), 'utf8')
    assert.match(results.adopt, /已经是项目了，内容没动/)
    assert.ok([...results.adopt].length < 120, `认领只回一句（一次认领好几首时不能撑爆上下文）：${[...results.adopt].length} 字`)
    assert.deepEqual(registered[1], [A, '天星问'])
    assert.ok(JSON.parse(before).status, '原来的内容还在')
  })
  check('拒绝：没写类型 / 文件夹不是项目 / 歌名带路径', () => {
    assert.match(results.badKind, /^ERR 新建项目要写 kind/)
    assert.match(results.notProject, /^ERR .*不是项目/)
    assert.match(results.badName, /^ERR 歌名里不能有/)
    assert.equal(existsSync(join(base, '逃出去')), false)
    assert.equal(existsSync(join(root, '没写类型')), false, '出错时不能留下空文件夹')
  })
  check('更新：状态和备注写进文件；没 .tmp 残留；大厅里不能更新', () => {
    const data = readProject(A)
    assert.equal(data.status, 'r02 已交')
    assert.match(data.notes.at(-1), /拍子再听一遍$/)
    assert.equal(data.notes[0], '导入', '原来的备注还在')
    assert.deepEqual(readdirSync(A).filter((n) => n.endsWith('.tmp')), [])
    assert.match(results.updateEmpty, /^ERR status、source、note 至少写一个/)
    assert.match(results.updateLobby, /^ERR 这个会话不在任何项目里/)
  })
  check('详情和列表', () => {
    assert.match(results.status, /最新工程：r02\\天星问_r02\.svp/)
    assert.match(results.status, /探针：.*（找不到了）/)
    assert.match(results.list, /《天星问》（翻唱）：r02 已交/)
    assert.match(results.list, /《新歌》（原创）：刚建/)
  })
} finally {
  rmSync(base, { recursive: true, force: true })   // 只删这次测试自己建的临时目录
}

console.log(failed === 0 ? '\n全部通过' : `\n${failed} 项没过`)
process.exitCode = failed === 0 ? 0 : 1
