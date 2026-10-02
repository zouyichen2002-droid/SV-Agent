// sv-video 插件自检（不启动 DSH、不跑真的渲染）：node test.mjs
// 假 Worker（node 小脚本，命令行和 video_run.py 一样）+ 假的 ctx；
// 照真的顺序走：校验参数 → 定版本号 → 后台跑 → 成功记状态 / 失败和被停的改名「弃用_vNN（…）」；另测拦写、上下文那一小段。
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, discardUnfinishedRetry, expandImages, nextVideoId, pickSvp, protectedReason, resolveSvp, videoContext } from './index.js'

const base = mkdtempSync(join(tmpdir(), 'sv-video-test-'))
const root = join(base, 'ws')
const drafts = join(base, '剪映草稿')
const P = join(root, '测试歌')
let failed = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`ok   ${label}`) } catch (e) { failed += 1; console.log(`FAIL ${label}\n     ${e.stack?.split('\n').slice(0, 2).join(' | ')}`) }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 假 Worker：照 video_run.py 的样子写 日志\视频进度.jsonl、视频\vNN\说明.md、日志\视频_vNN.json；按音频名决定成功 / 失败 / 一直跑
const FAKE = join(base, 'fake_worker.mjs')
writeFileSync(FAKE, `
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, basename } from 'node:path'
const argv = process.argv.slice(2)
const dir = argv[0]
const opt = (k) => argv[argv.indexOf(k) + 1]
const v = opt('--version'), audio = opt('--audio')
mkdirSync(join(dir, '日志'), { recursive: true })
writeFileSync(join(dir, '日志', 'args_' + v + '.json'), JSON.stringify(argv))
const note = (步, 状态, 说明 = '') => appendFileSync(join(dir, '日志', '视频进度.jsonl'), JSON.stringify({ 秒: 0, 版本: v, 步, 状态, 说明 }) + '\\n')
note('开始', '开始'); note('检查', '完成', '工程 r01')
mkdirSync(join(dir, '视频', v, '素材'), { recursive: true })
if (audio.endsWith('FAIL.wav')) { note('成片', '失败', '故意失败'); writeFileSync(join(dir, '日志', '视频_' + v + '.json'), JSON.stringify({ 结果: '失败', 步: '成片', 原因: '故意失败' })); process.exit(1) }
if (audio.endsWith('SLOW.wav')) { await new Promise((r) => setTimeout(r, 60000)) }
if (audio.endsWith('CRASH.wav')) { process.exit(1) }
note('对齐', '提醒', '成品前后和工程差得不一样')
writeFileSync(join(dir, '视频', v, '说明.md'), 'fake')
writeFileSync(join(dir, '日志', '视频_' + v + '.json'), JSON.stringify({ 结果: '完成', 总秒: 150, 版本: v, 成片: join(dir, '视频', v, basename(dir) + '_歌词视频_' + v + '.mp4'),
  工程: opt('--svp'), 字幕行: 50, 没出字幕的行: [7], 对齐: '成品比工程晚 1.50 秒，字幕整体跟着平移了', 提醒: ['第 90 秒起又差 -10.00 秒'] }))
note('结束', '完成')
`)

try {
  mkdirSync(join(P, '素材'), { recursive: true })
  mkdirSync(drafts, { recursive: true })
  writeFileSync(join(P, 'sv-project.json'), JSON.stringify({ schema: 'sv-agent/project@1', name: '测试歌', kind: 'cover', status: '刚建', notes: [] }))
  const file = (n, body = 'x') => { const p = join(base, n); writeFileSync(p, body); return p }
  const OK = file('成品.wav'), BAD = file('FAIL.wav'), SLOW = file('SLOW.wav'), CRASH = file('CRASH.wav')
  const IMG = file('封面.png')
  const IMGDIR = join(base, '图们')
  mkdirSync(IMGDIR)
  for (const n of ['图10.jpg', '图2.png', '说明.txt', '图1.webp']) writeFileSync(join(IMGDIR, n), 'x')

  await check('画面：图、视频（10-02 起可以给视频）、文件夹（按文件名排，图2 在 图10 前面；别的文件跳过）；找不到、不是图也不是视频、没给 → 拒绝', () => {
    assert.deepEqual(expandImages([IMG]), [IMG])
    const VID = file('底片.mp4')
    assert.deepEqual(expandImages([VID, IMG]), [VID, IMG], '视频也收')
    assert.deepEqual(expandImages([IMGDIR]).map((p) => p.slice(IMGDIR.length + 1)), ['图1.webp', '图2.png', '图10.jpg'])
    assert.throws(() => expandImages([join(base, '没有.png')]), /找不到图/)
    assert.throws(() => expandImages([OK]), /不是图也不是视频/)
    assert.throws(() => expandImages([]), /要给画面/)
    assert.throws(() => expandImages(['相对路径.png']), /绝对路径/)
  })

  await check('工程：默认用 rNN 里最近改过的 .svp（另存的也算，吸格线前的备份不算）；rNN、绝对路径也行', () => {
    assert.throws(() => resolveSvp(P, undefined), /还没有翻唱出来的工程/)
    mkdirSync(join(P, 'r01'))
    mkdirSync(join(P, 'r02'))
    mkdirSync(join(P, '弃用_r03（测试）'))
    const a = join(P, 'r01', '测试歌_扒谱_r01.svp'), b = join(P, 'r02', '测试歌_扒谱_r02.svp')
    const c = join(P, 'r01', '测试歌_扒谱_r01_我改的.svp'), d = join(P, 'r02', '测试歌_扒谱_r02_吸格线前.svp')
    const e = join(P, '弃用_r03（测试）', '测试歌_扒谱_r03.svp')
    for (const p of [a, b, c, d, e]) writeFileSync(p, '{}')
    const t = (p, s) => utimesSync(p, s, s)
    t(a, 1000); t(b, 2000); t(c, 3000); t(d, 4000); t(e, 5000)
    assert.equal(pickSvp(P), c, '他另存的那份最新')
    assert.equal(resolveSvp(P, ''), c)
    assert.equal(resolveSvp(P, 'r02'), b, 'r02 里吸格线前的不算')
    assert.equal(resolveSvp(P, a), a)
    assert.throws(() => resolveSvp(P, 'r09'), /r09 里没有/)
    assert.throws(() => resolveSvp(P, join(base, '没有.svp')), /找不到工程/)
  })

  await check('版本号：视频\\ 里的 vNN、弃用_vNN 和剪映里的 SV-Agent_<歌名>_vNN 都算，取最大 + 1', () => {
    assert.equal(nextVideoId(P, drafts), 'v01')
    mkdirSync(join(P, '视频', '弃用_v02（没跑完 成片）'), { recursive: true })
    assert.equal(nextVideoId(P, drafts), 'v03')
    mkdirSync(join(drafts, 'SV-Agent_测试歌_v05'))
    mkdirSync(join(drafts, 'SV-Agent_别的歌_v09'))
    assert.equal(nextVideoId(P, drafts), 'v06', '别的歌的草稿不算')
  })

  // ---- 假 ctx ----
  const tools = new Map()
  const guards = []
  const contexts = []
  const jobs = []
  const ctx = {
    tools: { register: (t) => { tools.set(t.name, t) }, guard: (fn) => { guards.push(fn) } },
    systemPrompt: { context: (c) => { contexts.push(c) } },
    jobs: { start: (spec) => { const id = `video-${jobs.length + 1}`; const hooks = spec.run({ id, append: (t, o) => { (spec.out ??= []).push([o?.channel, t]) }, updateProgress: () => {} }); jobs.push({ id, spec, hooks }); return id } },
    sandboxPolicy: { resolve: () => ({ mode: 'workspace-write', workspaceRoot: P }) },
    sandbox: { confine: async (argv) => ({ argv }) },
  }
  apply(ctx, { root, python: process.execPath, worker: FAKE, drafts, sandbox: true })
  const session = { id: 's1', header: { cwd: P } }
  const run = (args, cwd = P) => tools.get('video_run').execute(args, { agent: { session: { ...session, header: { cwd } } } })

  await check('登记了 video_run、拦写、上下文', () => {
    assert.ok(tools.has('video_run'))
    assert.equal(guards.length, 1)
    assert.equal(contexts[0].name, 'sv:video')
  })

  await check('不在项目里、没给音频、音频不对、没有歌词 → 拒绝（不起任务）', async () => {
    await assert.rejects(run({ audio: OK, images: [IMG] }, root), /不在任何项目里/)
    await assert.rejects(run({ images: [IMG] }), /要写 audio/)
    await assert.rejects(run({ audio: join(base, '没有.wav'), images: [IMG] }), /找不到成品音频/)
    await assert.rejects(run({ audio: IMG, images: [IMG] }), /不是音频/)
    await assert.rejects(run({ audio: OK, images: [IMG] }), /歌词_要唱的字/)
    assert.equal(jobs.length, 0)
  })

  writeFileSync(join(P, '素材', '歌词_要唱的字.txt'), '一句\n')
  await check('做视频：参数原样交给 Worker（图按顺序、工程、标题、署名）→ 成功：记项目状态，结果里有成片、草稿名、对齐、要提醒的', async () => {
    const out = await run({ audio: OK, images: [IMGDIR, IMG], title: '【星尘】测试歌', credit: '翻唱：小鳄鱼aligator' })
    assert.match(out, /开始了：歌词视频《测试歌》v06/)
    assert.match(out, /r01[\\/]测试歌_扒谱_r01_我改的\.svp（rNN 里最近改过的那份）/)
    await assert.rejects(run({ audio: OK, images: [IMG] }), /已经在做了/)
    const outcome = await jobs[0].hooks.done
    assert.equal(outcome.status, 'completed', JSON.stringify(outcome))
    assert.match(outcome.result, /做好了（3 分钟）/)
    assert.match(outcome.result, /剪映草稿：「SV-Agent_测试歌_v06」/)
    assert.match(outcome.result, /对齐：成品比工程晚 1\.50 秒/)
    assert.match(outcome.result, /要提醒创作者：第 90 秒起又差/)
    assert.match(outcome.result, /没出字幕的行：第 7 行/)
    const args = JSON.parse(readFileSync(join(P, '日志', 'args_v06.json'), 'utf8'))
    const imgs = args.flatMap((x, i) => (x === '--image' ? [args[i + 1]] : []))
    assert.deepEqual(imgs.map((p) => p.split(/[\\/]/).pop()), ['图1.webp', '图2.png', '图10.jpg', '封面.png'])
    assert.equal(args[args.indexOf('--svp') + 1], join(P, 'r01', '测试歌_扒谱_r01_我改的.svp'))
    assert.equal(args[args.indexOf('--drafts') + 1], drafts, '草稿文件夹由插件传给 Worker（只有一处配置）')
    assert.equal(args[args.indexOf('--title') + 1], '【星尘】测试歌')
    assert.equal(args[args.indexOf('--credit') + 1], '翻唱：小鳄鱼aligator')
    assert.equal(args[args.indexOf('--fx') + 1], '可爱', '没说样式 → 可爱（创作者 10-02 定的默认）')
    assert.equal(args[args.indexOf('--side') + 1], 'auto', '没说放哪边 → 自动')
    const proj = JSON.parse(readFileSync(join(P, 'sv-project.json'), 'utf8'))
    assert.match(proj.status, /^歌词视频 v06 做好了/)
    assert.match(proj.notes.at(-1), /video_run v06 完成/)
    const stdout = jobs[0].spec.out.filter(([c]) => c === 'stdout').map(([, t]) => t).join('')
    assert.match(stdout, /对齐 提醒/, '模型看得到要提醒的')
  })

  await check('没填标题、署名 → 不传（Worker 用《歌名》、不放署名）；填 rNN → 用那一版的工程', async () => {
    const out = await run({ audio: OK, images: [IMG], svp: 'r02' })
    assert.match(out, /不放署名/)
    await jobs[1].hooks.done
    const args = JSON.parse(readFileSync(join(P, '日志', 'args_v07.json'), 'utf8'))
    assert.ok(!args.includes('--title') && !args.includes('--credit'), args.join(' '))
    assert.equal(args[args.indexOf('--svp') + 1], join(P, 'r02', '测试歌_扒谱_r02.svp'))
  })

  await check('Worker 失败 → 任务失败、没做完的 vNN 改名「弃用_vNN（没跑完 成片）」（不删）', async () => {
    await run({ audio: BAD, images: [IMG] })
    const outcome = await jobs[2].hooks.done
    assert.equal(outcome.status, 'failed')
    assert.match(outcome.result, /成片 故意失败/)
    const names = readdirSync(join(P, '视频'))
    assert.ok(names.includes('弃用_v08（没跑完 成片）'), names.join(','))
    assert.ok(!names.includes('v08'))
    assert.ok(existsSync(join(P, '视频', '弃用_v08（没跑完 成片）', '素材')), '里面的东西都还在')
  })

  await check('创作者点停止 → 子程序停掉、任务 killed、改名「弃用_vNN（停掉了）」；下一版号接着往上', async () => {
    await run({ audio: SLOW, images: [IMG] })
    await sleep(1500)
    jobs[3].hooks.cancel('测试：创作者停掉了')
    const outcome = await jobs[3].hooks.done
    assert.equal(outcome.status, 'killed')
    assert.ok(readdirSync(join(P, '视频')).includes('弃用_v09（停掉了）'))
    assert.equal(nextVideoId(P, drafts), 'v10')
  })

  await check('拦写：做好的 视频\\vNN\\、剪映草稿文件夹 → 拒绝；没做完的、项目别处 → 不拦', () => {
    const g = (p) => guards[0]({ name: 'write', arguments: { file_path: p }, agent: { session } })
    assert.match(g(join(P, '视频', 'v06', '说明.md')), /v06 已经做好/)
    assert.match(g(join(P, '视频', 'v06', '素材', '新.png')), /不能改、不能往里加/)
    assert.match(g(join(drafts, 'SV-Agent_测试歌_v06', 'draft_content.json')), /剪映的草稿文件夹/)
    assert.match(g(join(drafts, '创作者自己的草稿', 'x.json')), /剪映的草稿文件夹/)
    mkdirSync(join(P, '视频', 'v11'))
    assert.equal(g(join(P, '视频', 'v11', 'x.txt')), undefined, '没做完的不拦')
    assert.equal(g(join(P, '笔记.md')), undefined)
    assert.equal(guards[0]({ name: 'read', arguments: { file_path: join(P, '视频', 'v06', '说明.md') }, agent: { session } }), undefined, '只拦 write / edit')
    assert.equal(protectedReason(join(base, '别处.txt'), root, drafts), undefined)
  })

  await check('上下文：最近两版的状态；还没做过视频的歌不说', () => {
    const t = videoContext(P)
    assert.match(t, /^歌词视频：v11 在做 \/ 没做完；v09 弃用/)
    const Q = join(root, '别的歌')
    mkdirSync(Q)
    assert.equal(videoContext(Q), '')
    assert.equal(contexts[0].text({ agent: { session } }), t)
  })
  await check('字幕样式：填了就原样交给 Worker；填错了 → 拒绝（不起任务）', async () => {
    const before = jobs.length
    await assert.rejects(run({ audio: OK, images: [IMG], fx: '爆炸' }), /没有这种字幕样式：爆炸/)
    assert.equal(jobs.length, before)
    const out = await run({ audio: OK, images: [IMG], fx: '竖排古风' })
    assert.match(out, /字幕样式「竖排古风」/)
    await jobs.at(-1).hooks.done
    const id = out.match(/》(v\d+)/)[1]
    const args = JSON.parse(readFileSync(join(P, '日志', `args_${id}.json`), 'utf8'))
    assert.equal(args[args.indexOf('--fx') + 1], '竖排古风')
  })
  await check('改名重试：文件被占着改不了时隔一会儿再试（10-01 DSH 里刚停掉时一次没改成）', async () => {
    const d = join(P, '视频', 'v20')
    mkdirSync(d, { recursive: true })
    const { openSync, closeSync } = await import('node:fs')
    const fd = openSync(join(d, '占着.mp4'), 'w')
    let released = false
    setTimeout(() => { closeSync(fd); released = true }, 700)
    const moved = await discardUnfinishedRetry(P, 'v20', '测试', 10, 200)
    assert.ok(released, '要等文件放开才改得了')
    assert.ok(moved && moved.endsWith('弃用_v20（测试）'), String(moved))
    assert.ok(existsSync(join(moved, '占着.mp4')), '里面的东西都还在')
  })
  await check('Worker 没写总结就退出（被结束了 / 崩了）→ 结果直说「中途退出、不是哪一步报的错」，没做完的照样改名', async () => {
    const out = await run({ audio: CRASH, images: [IMG] })
    const id = out.match(/》(v\d+)/)[1]
    const outcome = await jobs.at(-1).hooks.done
    assert.equal(outcome.status, 'failed')
    assert.match(outcome.result, /中途退出了、没写总结/)
    assert.match(outcome.result, /不是哪一步报的错/)
    assert.ok(readdirSync(join(P, '视频')).some((n) => n.startsWith(`弃用_${id}（没跑完`)), readdirSync(join(P, '视频')).join(','))
  })
  await check('字放哪边：填 right 就原样交给 Worker；填错了 → 拒绝（不起任务）', async () => {
    const before = jobs.length
    await assert.rejects(run({ audio: OK, images: [IMG], side: '中间' }), /side 只能是 left 或 right/)
    assert.equal(jobs.length, before)
    const out = await run({ audio: OK, images: [IMG], side: 'right' })
    assert.match(out, /字放右边/)
    await jobs.at(-1).hooks.done
    const id = out.match(/》(v\d+)/)[1]
    const args = JSON.parse(readFileSync(join(P, '日志', `args_${id}.json`), 'utf8'))
    assert.equal(args[args.indexOf('--side') + 1], 'right')
  })
} finally {
  rmSync(base, { recursive: true, force: true })   // 只删这次测试自己建的临时目录
}

console.log(failed === 0 ? '\n全部通过' : `\n${failed} 项没过`)
process.exitCode = failed === 0 ? 0 : 1
