// 离线出图 / 出片（来自 pdoom-video 的 scripts/render.ts，MIT；SV-Agent 10-03 改成用 Node 24 跑，不要 bun）。
// 用后台 Chrome 打开页面（?export=1），按歌曲时间一帧一帧画：
//   node scripts/render.ts gpu   --song <MV 文件夹>                        看 Chrome 用的是哪块显卡
//   node scripts/render.ts stills --song <dir> --t 1.5,23,40.2 [--only id1,id2] [--out dir]
//   node scripts/render.ts sheet  --song <dir> --from 20 --to 35 [--n 12] [--cols 4] [--only ids] [--out file.png]   （或 --times a,b,c | --cuts）
//   node scripts/render.ts perf   --song <dir> --from 20 --to 25 [--samples 1] [--shutter 0.5]
//   node scripts/render.ts video  --song <dir> [--from 0] [--to 结尾] [--fps 60] [--crf 16] [--preset slow] [--samples 1|auto] [--shutter 0.5] [--out file.mp4] [--noaudio]
//     --samples N：每帧取 N 个子帧平均（运动模糊 + 时间抗锯齿）；auto：每帧自己定（4、12、36、108、324）
//     --scale N：按 1920x1080 的 N 倍画（--scale 2 = 3840x2160）
//     --query k=v：附加页面参数（journal 认 cover=1：封面模式，不画歌词条和页眉、写大标题）
// --song 也可以用环境变量 MV_SONG_DIR；ffmpeg 默认用 worker/cover_config.json 里那个（--ffmpeg 或 MV_FFMPEG 可以换）。
// 每次自己起一个不热更新的 vite（除非 --url 指定一个已经开着的）；跑的时候把自己、ffmpeg、Chrome 调成「低于正常」。
import { chromium, type Page } from 'playwright-core';
import { WebSocketServer } from 'ws';
import { spawn, execFile } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const mode = argv[0] ?? 'stills';
const opt = (k: string, d?: string) => { const i = argv.indexOf(`--${k}`); return i >= 0 ? argv[i + 1] : d; };
const flag = (k: string) => argv.includes(`--${k}`);
const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO = path.resolve(APP, '..');
const SONG = path.resolve(opt('song') ?? process.env.MV_SONG_DIR ?? '');
if (!opt('song') && !process.env.MV_SONG_DIR) throw new Error('要 --song <那首歌的 MV 文件夹>（或环境变量 MV_SONG_DIR）');
const SCALE = Math.max(1, Math.round(+opt('scale', '1')!));
const OW = 1920 * SCALE, OH = 1080 * SCALE; // output size
const SAMPLES = opt('samples', '1') === 'auto'
  ? { min: +opt('min-samples', '4')!, max: +opt('max-samples', '324')!, tol: +opt('tol', '3')! }
  : +opt('samples', '1')!;
const hist = (h: Record<string, number>) => Object.entries(h).sort((a, b) => +a[0] - +b[0]).map(([k, v]) => `${k}:${v}`).join(' ');
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function ffmpegPath(): string {
  const o = opt('ffmpeg') ?? process.env.MV_FFMPEG;
  if (o) return o;
  const cfg = JSON.parse(readFileSync(path.join(REPO, 'worker', 'cover_config.json'), 'utf8'));
  return cfg.ffmpeg;
}

/** 低于正常：自己、子进程（ffmpeg / vite），以及这次 playwright 开的 Chrome（命令行里有它的临时配置目录）。 */
function lowPriority(pid = 0) {
  try { os.setPriority(pid, os.constants.priority.PRIORITY_BELOW_NORMAL); } catch { /* 调不了就算了 */ }
}
function lowPriorityChrome() {
  if (process.platform !== 'win32') return;
  const ps = "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like '*playwright_chromiumdev_profile*' } | ForEach-Object { try { (Get-Process -Id $_.ProcessId).PriorityClass = 'BelowNormal' } catch {} }";
  execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps], { windowsHide: true }, () => {});
}

async function reachable(url: string) {
  try { const r = await fetch(url, { signal: AbortSignal.timeout(1500) }); return r.ok; } catch { return false; }
}

async function ensureServer(): Promise<{ url: string; stop: () => void }> {
  const given = opt('url');
  if (given && (await reachable(given))) return { url: given, stop: () => {} };
  const port = 5300 + Math.floor(Math.random() * 500);
  const vite = path.join(APP, 'node_modules', 'vite', 'bin', 'vite.js');
  const proc = spawn(process.execPath, [vite, '--port', String(port), '--strictPort'], {
    cwd: APP, stdio: 'ignore', windowsHide: true,
    env: { ...process.env, MV_NO_HMR: '1', MV_SONG_DIR: SONG },
  });
  if (proc.pid) lowPriority(proc.pid);
  const u = `http://localhost:${port}`;
  for (let i = 0; i < 150 && !(await reachable(u)); i++) await sleep(100);
  if (!(await reachable(u))) { proc.kill(); throw new Error('vite 没起来'); }
  return { url: u, stop: () => proc.kill() };
}

async function openPage(url: string) {
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: !flag('headed'),
    args: ['--use-angle=d3d11', '--force_high_performance_gpu', '--enable-gpu-rasterization', '--ignore-gpu-blocklist',
      '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'],
  });
  lowPriorityChrome();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const logs: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') logs.push(`[${m.type()}] ${m.text()}`); });
  page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`));
  page.on('response', (r) => { if (r.status() >= 400) logs.push(`[http ${r.status()}] ${r.url()}`); });
  const only = opt('only');
  await page.goto(`${url}/?export=1${only ? `&only=${only}` : ''}${SCALE !== 1 ? `&scale=${SCALE}` : ''}${opt('query') ? `&${opt('query')}` : ''}`);
  await page.waitForFunction(() => (window as any).__mv?.ready || (window as any).__mv?.error, null, { timeout: 120000 });
  const err = await page.evaluate(() => (window as any).__mv.error);
  if (err) throw new Error(`app failed to boot:\n${err}\n${logs.join('\n')}`);
  const size: [number, number] = await page.evaluate(() => [(window as any).__mv.width ?? 1920, (window as any).__mv.height ?? 1080]);
  if (size[0] !== OW || size[1] !== OH) throw new Error(`app renders ${size[0]}x${size[1]}, expected ${OW}x${OH} (--scale ${SCALE})`);
  const sceneErrors: string[] = await page.evaluate(() => (window as any).__mv.errors);
  if (sceneErrors.length) console.error('SCENE ERRORS:\n' + sceneErrors.join('\n'));
  return { browser, page, logs };
}

async function stills(page: Page, times: number[], outDir: string) {
  mkdirSync(outDir, { recursive: true });
  const files: string[] = [];
  for (const t of times) {
    const k: number = await page.evaluate(([t, s, sh]) => (window as any).__mv.still(t, s, sh), [t, SAMPLES, +opt('shutter', '0.5')!] as const);
    const f = path.join(outDir, `f_${t.toFixed(2).padStart(7, '0')}.png`);
    if (typeof SAMPLES !== 'number') console.log(`t=${t}: ${k} sub-frames`);
    // at scale > 1 the canvas is shown downscaled on the page: save the full-res pixel buffer instead
    if (SCALE !== 1) writeFileSync(f, Buffer.from(await page.evaluate(() => (window as any).__mv.png()), 'base64'));
    else await page.screenshot({ path: f, clip: { x: 0, y: 0, width: 1920, height: 1080 } });
    files.push(f);
  }
  return files;
}

async function sheet(page: Page, times: number[], cols: number, out: string) {
  const dataUrl: string = await page.evaluate(async ({ times, cols }) => {
    const P = (window as any).__mv;
    const cw = 480, ch = 270, pad = 4, lab = 18;
    const rows = Math.ceil(times.length / cols);
    const cv = document.createElement('canvas');
    cv.width = cols * (cw + pad) + pad; cv.height = rows * (ch + lab + pad) + pad;
    const c = cv.getContext('2d')!;
    c.fillStyle = '#222'; c.fillRect(0, 0, cv.width, cv.height);
    const src = document.getElementById('c') as HTMLCanvasElement;
    times.forEach((t: number, i: number) => {
      P.still(t);
      const x = pad + (i % cols) * (cw + pad), y = pad + Math.floor(i / cols) * (ch + lab + pad);
      c.drawImage(src, x, y + lab, cw, ch);
      c.fillStyle = '#ddd'; c.font = '13px monospace'; c.fillText(`${t.toFixed(2)}s`, x + 2, y + 13);
    });
    return cv.toDataURL('image/png');
  }, { times, cols });
  mkdirSync(path.dirname(out), { recursive: true });
  writeFileSync(out, Buffer.from(dataUrl.split(',')[1]!, 'base64'));
}

async function video(page: Page, from: number, to: number, fps: number, out: string) {
  mkdirSync(path.dirname(out), { recursive: true });
  const crf = opt('crf', '16')!;
  const audio = opt('audio', path.join(SONG, 'audio.wav'))!;
  const args = ['-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${OW}x${OH}`, '-r', String(fps), '-i', 'pipe:0'];
  if (!flag('noaudio')) args.push('-ss', String(from), '-t', String(to - from), '-i', audio);
  // Frames are sRGB (toSRGB in the final pass): convert with the BT.709 matrix and tag the stream,
  // otherwise ffmpeg converts with BT.601 while players decode untagged HD as BT.709.
  args.push('-vf', 'vflip,scale=out_color_matrix=bt709,setparams=color_primaries=bt709:color_trc=bt709', '-c:v', 'libx264', '-preset', opt('preset', 'slow')!, '-crf', crf, '-pix_fmt', 'yuv420p', '-tune', 'grain', '-x264-params', opt('x264', 'aq-mode=3')!);
  if (!flag('noaudio')) args.push('-c:a', 'aac', '-b:a', '320k', '-shortest');
  args.push('-movflags', '+faststart', out);
  const ff = spawn(ffmpegPath(), args, { stdio: ['pipe', 'inherit', 'inherit'], windowsHide: true });
  if (ff.pid) lowPriority(ff.pid);
  let frames = 0;
  const total = Math.round(to * fps) - Math.round(from * fps);
  const t0 = performance.now();
  const wss = new WebSocketServer({ port: 0, maxPayload: Math.max(64 * 1024 * 1024, OW * OH * 4 + 1024) });
  await once(wss, 'listening');
  const port = (wss.address() as { port: number }).port;
  wss.on('connection', (ws) => {
    let chain = Promise.resolve();
    ws.on('message', (msg: Buffer) => {
      // 一帧一帧按顺序交给 ffmpeg；ffmpeg 来不及就等它（4K 时内存不会越堆越多）
      chain = chain.then(async () => {
        if (!ff.stdin!.write(msg)) await once(ff.stdin!, 'drain');
        frames++;
        ws.send(String(frames)); // ack: the page keeps at most a few frames ahead of ffmpeg
        if (frames % 60 === 0 || frames === total) {
          const el = (performance.now() - t0) / 1000;
          process.stdout.write(`\r${frames}/${total} frames  ${(frames / el).toFixed(1)} fps  eta ${((total - frames) / (frames / el)).toFixed(0)}s   `);
        }
      });
    });
  });
  const used: Record<string, number> = await page.evaluate((o) => (window as any).__mv.stream(o), { from, to, fps, ws: `ws://localhost:${port}`, samples: SAMPLES, shutter: +opt('shutter', '0.5')!, inflight: 4 });
  while (frames < total) await sleep(20);
  ff.stdin!.end();
  await once(ff, 'exit');
  wss.close();
  console.log(`\nwrote ${out} (${frames} frames in ${((performance.now() - t0) / 1000).toFixed(1)}s)`);
  console.log(`sub-frames per frame (count:frames): ${hist(used)}`);
}

lowPriority();
const { url, stop } = await ensureServer();
const { browser, page, logs } = await openPage(url);
try {
  if (mode === 'gpu') {
    console.log(await page.evaluate(() => {
      const gl = document.createElement('canvas').getContext('webgl2')!;
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    }));
  } else if (mode === 'stills') {
    const times = (opt('t') ?? '0').split(',').map(Number);
    const files = await stills(page, times, opt('out', path.join(SONG, 'out', 'stills'))!);
    console.log(files.join('\n'));
  } else if (mode === 'sheet') {
    const from = +opt('from', '0')!, to = +opt('to', '10')!, n = +opt('n', '12')!;
    let times = Array.from({ length: n }, (_, i) => from + ((to - from) * i) / Math.max(1, n - 1));
    if (opt('times')) times = opt('times')!.split(',').map(Number);
    if (flag('cuts')) {
      // 4 frames around every timeline boundary: 2 frames before, 2 after
      const tl: { id: string; start: number }[] = await page.evaluate(() => (window as any).__mv.timeline);
      times = tl.slice(1).flatMap((e) => [e.start - 0.1, e.start - 1 / 60, e.start + 1 / 60, e.start + 0.1]);
    }
    const out = opt('out', path.join(SONG, 'out', 'sheets', `sheet_${from}-${to}.png`))!;
    await sheet(page, times, +opt('cols', '4')!, out);
    console.log(out);
  } else if (mode === 'perf') {
    const from = +opt('from', '0')!, to = +opt('to', '5')!;
    const r = await page.evaluate(async ({ from, to, samples, shutter }) => {
      const P = (window as any).__mv;
      const ms: number[] = [];
      const buf = new Uint8Array(P.width * P.height * 4);
      P.still(from);
      const used: Record<number, number> = {};
      for (let t = from; t < to; t += 1 / 60) {
        const a = performance.now();
        const k = P.engine.render(t, 1 / 60, false, samples, shutter);
        used[k] = (used[k] ?? 0) + 1;
        await P.engine.readPixelsAsync(buf);
        ms.push(performance.now() - a);
      }
      ms.sort((a, b) => a - b);
      return { n: ms.length, avg: ms.reduce((a, b) => a + b, 0) / ms.length, p50: ms[ms.length >> 1], p95: ms[Math.floor(ms.length * 0.95)], max: ms[ms.length - 1], used };
    }, { from, to, samples: SAMPLES, shutter: +opt('shutter', '0.5')! });
    console.log(`frames ${r.n}  avg ${r.avg.toFixed(1)}ms  p50 ${r.p50.toFixed(1)}  p95 ${r.p95.toFixed(1)}  max ${r.max.toFixed(1)}  sub-frames ${hist(r.used)}`);
  } else if (mode === 'video') {
    const dur: number = await page.evaluate(() => (window as any).__mv.duration);
    const out = path.resolve(opt('out', path.join(SONG, 'out', 'mv.mp4'))!);
    await video(page, +opt('from', '0')!, +opt('to', String(dur))!, +opt('fps', '60')!, out);
  } else {
    throw new Error(`不认识的模式：${mode}`);
  }
  if (logs.length) console.error('BROWSER LOG:\n' + logs.slice(0, 40).join('\n'));
} finally {
  await browser.close();
  stop();
}
