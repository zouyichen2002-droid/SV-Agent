// 《由》曲绘 PV（SV-Agent 10-04 第二版）：创作者给的曲绘为主 —— 每张抠出人物层（analysis/prepare_art.py），
// 背景 / 人物 / 前景三层视差、镜头推拉跟拍子；剧场做点缀（红幕 10-04 删了）：聚光灯和浮尘、星尘粒子、提线、
// 金色裂缝撕开转场（唱到裂缝的那句，下一张曲绘撕开冲出来）、第 32 / 51 / 76 句砸字灭灯、开场和尾声的金线歌名字。
// 歌词竖排毛笔字放在人物对面；桥段横排快写。时间点按第几句歌词找（代码里没有歌词原文）。只由歌曲时间决定。
import type * as THREE from 'three';
import { Scene, type Frame } from '../engine/scene';
import { Layer2D, W, H } from '../engine/gl';
import { clamp, ease, hash, lerp, smoothstep, TAU } from '../engine/util';
import { font, checkFont } from '../engine/type';
import type { Line } from '../engine/lyrics';
import { PAL, FAM, spot, dust, stardust, makeCrack, drawCrack, sungK, lyricWrite, lyricStamp, star4, type C2 } from './theater/kit';
import { revealArt } from './theater/props';

const GLOW = 2.2;

type Art = {
  id: string; w: number; h: number; box: [number, number, number, number]; cen: [number, number]; side: 'left' | 'right'; alpha: boolean;
  full: HTMLImageElement | null; fg: HTMLImageElement | null; bg: HTMLImageElement | null;
};
type Kind = 'intro' | 'verse' | 'chorus' | 'black' | 'inst' | 'bridge' | 'outro';
type Shot = { a: number; b: number; slot: string; kind: Kind; art: number; tin: 'cut' | 'fade' | 'tear' | 'flash' };

function loadImg(src: string | null): Promise<HTMLImageElement | null> {
  if (!src) return Promise.resolve(null);
  return new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = src; });
}
const chars = (l: Line) => [...l.text].filter((ch) => ch.trim());

export default class Quhui extends Scene {
  base = new Layer2D();
  glow = new Layer2D(W, H, 0.5);
  arts: Art[] = [];
  blur: (HTMLCanvasElement | null)[] = [];
  creditPos: [number, number] | null = null;
  subStyle = 'A';
  stopLines: number[] = [];
  fontKey = 'hei';
  subHalo = 0;
  sign: { text: string; x: number; y: number; size: number; halo?: number } | null = null;
  shots: Shot[] = [];
  credits: string[] = [];
  reg: Record<string, Record<string, [number, number, number, 'left' | 'right']>> = {};
  camSpec: Record<string, any> = {};
  par: Record<string, number> = {};
  outroGlyph = true; useKintsugi = true;
  cracks = [makeCrack(980, 120, 1.55, 760, 401, 5), makeCrack(900, 100, 1.62, 780, 402, 5), makeCrack(1020, 90, 1.5, 800, 403, 6)];
  kintsugi = [makeCrack(-20, 160, 0.35, 520, 501, 3), makeCrack(W + 20, 220, 2.8, 520, 502, 3), makeCrack(260, H + 20, -1.2, 420, 503, 3), makeCrack(W - 240, H + 20, -1.9, 420, 504, 3), makeCrack(-20, 760, -0.3, 460, 505, 2)];

  L(n: number): Line { return this.ctx.lyrics.lines[n - 1]!; }
  s(n: number) { return this.L(n).start; }
  e(n: number) { return this.L(n).end; }

  async init() {
    const n = this.ctx.lyrics.lines.length;
    let mv: any = {};
    try { mv = await (await fetch('/song/mv.json')).json(); } catch { mv = {}; }
    if (!mv['分段'] && n !== 76) throw new Error(`没有 mv.json 的「分段」时只认《由》（76 句），lyrics.json 里是 ${n} 句`);
    this.stopLines = mv['砸字句'] ?? (mv['分段'] ? [] : [32, 51, 76]);
    this.credits = mv.credits ?? [];
    this.reg = mv['区域'] ?? {}; this.camSpec = mv['镜头'] ?? {}; this.par = mv['视差'] ?? {};
    this.outroGlyph = mv['尾声金字'] !== false; this.useKintsugi = mv['金缮'] !== false;
    const list: any[] = await (await fetch('/song/art/art.json')).json();
    this.arts = await Promise.all(list.map(async (j) => ({
      id: j.id, w: j.w, h: j.h, box: j['人物外框'], cen: j['人物重心'], side: j['字放'], alpha: !!j['透明底'],
      full: await loadImg('/song/' + j.full), fg: await loadImg('/song/' + j.fg), bg: await loadImg(j.bg ? '/song/' + j.bg : null),
    })));
    if (!this.arts.length) throw new Error('MV\\art\\art.json 里没有曲绘（先跑 analysis/prepare_art.py）');
    this.blur = this.arts.map((a) => {
      if (!a.full) return null;
      const cv = document.createElement('canvas'); cv.width = 640; cv.height = 360;
      const x = cv.getContext('2d')!; const sc = Math.max(640 / a.w, 360 / a.h);
      x.filter = 'blur(12px) brightness(0.5)'; x.drawImage(a.full, (640 - a.w * sc) / 2, (360 - a.h * sc) / 2, a.w * sc, a.h * sc);
      return cv;
    });
    this.creditPos = mv['片尾字位置'] ?? null;
    this.sign = mv['片尾署名'] ?? null;
    this.subStyle = (new URLSearchParams(location.search).get('sub') ?? mv['字幕样式'] ?? 'A').toUpperCase();
    this.fontKey = new URLSearchParams(location.search).get('font') ?? mv['字幕字体'] ?? 'hei';
    this.subHalo = mv['字幕暗边'] ?? 0;
    const s = (k: number) => this.s(k), e = (k: number) => this.e(k), D = this.ctx.audio.duration;
    // 分镜：slot 名 → 用第几张曲绘（mv.json 的「曲绘分配」可以改；不给就按顺序轮）
    const order = ['intro', 'v1', 'v1b', 'ch1', 'v2', 'ch2', 'inst', 'br', 'ch3', 'outro'];
    const pick: Record<string, number> = mv['曲绘分配'] ?? {};
    const auto: Record<string, number> = {};
    let k = 0;
    for (const sl of order) {
      if (sl === 'v1') { auto[sl] = auto.intro!; continue; }
      if (sl === 'outro') { auto[sl] = auto.intro!; continue; }
      auto[sl] = k++ % this.arts.length;
    }
    const A = (sl: string) => Math.min(this.arts.length - 1, pick[sl] ?? auto[sl]!);
    const S = (a: number, b: number, slot: string, kind: Kind, tin: Shot['tin']) => this.shots.push({ a, b, slot, kind, art: slot === 'black' ? -1 : A(slot), tin });
    if (mv['分段']) {
      const segs: any[] = mv['分段'];
      const at = (v: any) => typeof v === 'string' && v.startsWith('line:') ? s(Number(v.slice(5))) - 0.35 : Number(v);
      segs.forEach((g, i) => {
        const a = i === 0 ? 0 : at(g.from), b = i + 1 < segs.length ? at(segs[i + 1].from) : D;
        this.shots.push({ a, b, slot: g.slot, kind: g.kind, art: g.kind === 'black' ? -1 : Math.min(this.arts.length - 1, g.art), tin: g.tin ?? 'flash' });
      });
      return;
    }
    S(0, s(4) - 0.4, 'intro', 'intro', 'cut');
    S(s(4) - 0.4, s(14) - 0.3, 'v1', 'verse', 'cut');
    S(s(14) - 0.3, s(23) - 0.35, 'v1b', 'verse', 'fade');
    S(s(23) - 0.35, e(32) + 0.25, 'ch1', 'chorus', 'flash');
    S(e(32) + 0.25, s(33) - 0.3, 'black', 'black', 'flash');
    S(s(33) - 0.3, s(42) - 0.3, 'v2', 'verse', 'fade');
    S(s(42) - 0.3, e(51) + 0.25, 'ch2', 'chorus', 'flash');
    S(e(51) + 0.25, s(52) - 0.35, 'inst', 'inst', 'flash');
    S(s(52) - 0.35, s(67) - 0.35, 'br', 'bridge', 'flash');
    S(s(67) - 0.35, e(76) + 0.25, 'ch3', 'chorus', 'flash');
    S(e(76) + 0.25, D, 'outro', 'outro', 'flash');
  }

  private shotAt(t: number) { let i = 0; for (let k = 0; k < this.shots.length; k++) if (t >= this.shots[k]!.a) i = k; return i; }

  // ------------------------------------------------------------ 镜头：按 mv.json 的「区域」「镜头」取景
  /** 一个区域 → 取景（主体放在字的对面那个三分之一处）。 */
  private target(art: Art, r: string) {
    const R = this.reg[art.id]?.[r] ?? [art.w / 2, art.h / 2, 1, art.side];
    const [rx, ry, z, side] = R;
    const anchor = z < 1 || this.subStyle !== 'B' ? 0.5 : side === 'left' ? 0.6 : 0.4;   // 字在底部（A / C）或整张放下时居中
    return { fx: rx - (anchor - 0.5) * W / (this.baseScale(art) * z), fy: ry, z, side: side as 'left' | 'right' };
  }
  private keysOf(sh: Shot): { t: number; r: string }[] | string {
    const spec = this.camSpec[sh.slot];
    if (typeof spec === 'string') return spec;
    if (!spec || !spec.length) return [{ t: sh.a, r: '全' }];
    return spec.map(([k, r]: [number | string, string]) => ({
      t: k === 'start' ? sh.a : typeof k === 'string' && k.startsWith('+') ? sh.a + parseFloat(k.slice(1)) : this.s(Number(k)) - 0.35, r,
    }));
  }
  private view(sh: Shot, f: Frame, t: number) {
    const art = this.arts[sh.art]!;
    const K = this.keysOf(sh);
    let fx: number, fy: number, z: number, side: 'left' | 'right';
    if (typeof K === 'string') {
      const list = K.replace(/^cycle:/, '').split(',');
      const n = list.length, bar = Math.floor(f.bar), k = ((bar % n) + n) % n;
      const p = this.target(art, list[(k + n - 1) % n]!), c = this.target(art, list[k]!);
      const v = ease.outCubic(clamp(f.barPhase / 0.1));
      fx = lerp(p.fx, c.fx, v); fy = lerp(p.fy, c.fy, v); z = lerp(p.z, c.z, v) * (1 + 0.012 * f.a.kick) * (1 + 0.03 * f.barPhase); side = c.side;
    } else {
      let j = 0;
      for (let i = 0; i < K.length; i++) if (t >= K[i]!.t) j = i;
      const cur = this.target(art, K[j]!.r), prev = j > 0 ? this.target(art, K[j - 1]!.r) : cur;
      const v = ease.inOutCubic(clamp((t - K[j]!.t) / 0.9));
      const push = sh.kind === 'intro' || sh.kind === 'outro' ? 0 : 0.018;
      fx = lerp(prev.fx, cur.fx, v); fy = lerp(prev.fy, cur.fy, v); z = lerp(prev.z, cur.z, v) * (1 + push * clamp((t - K[j]!.t) / Math.max(4, sh.b - K[j]!.t)));
      side = v > 0.5 ? cur.side : prev.side;
    }
    const rot = 0;                                              // 10-04 创作者「动的太猛了」：不转、不呼吸
    return { fx, fy, z, rot, side };
  }

  /** 放大倍数的基准：普通曲绘铺满画面；透明底的立绘按人物外框的高放（整个人放得下）。 */
  private baseScale(art: Art) { return art.alpha ? (H * 0.9) / Math.max(1, art.box[3] - art.box[1]) : Math.max(W / art.w, H / art.h); }

  /** 画一张曲绘（背景层 + 人物层，带视差）；返回人物在屏幕上的外框和脸的位置。 */
  private drawArt(c: C2, sh: Shot, f: Frame, t: number, alpha = 1, extraZ = 1) {
    const art = this.arts[sh.art]!;
    const { fx, fy, z, rot } = this.view(sh, f, t);
    const S0 = this.baseScale(art);
    const covers = z * extraZ * S0 * art.w >= W - 1 && z * extraZ * S0 * art.h >= H - 1;
    if (!covers && !art.alpha && this.blur[sh.art]) { c.save(); c.globalAlpha = alpha; c.drawImage(this.blur[sh.art]!, 0, 0, W, H); c.restore(); }
    const put = (im: HTMLImageElement | null, depth: number) => {
      if (!im) return;
      const k = 1 / depth, zz = (1 + (z * extraZ - 1) * k) * S0 * (depth > 1 && covers ? 1.05 : 1);
      const px = art.w / 2 + (fx - art.w / 2) * k, py = art.h / 2 + (fy - art.h / 2) * k;
      // 不让图的边进画面
      const hw = W / 2 / zz, hh = H / 2 / zz;
      const cx = art.alpha || !covers ? px : clamp(px, hw, art.w - hw), cy = art.alpha || !covers ? py : clamp(py, hh, art.h - hh);
      c.save(); c.globalAlpha = alpha;
      c.translate(W / 2, H / 2); c.rotate(rot * k); c.scale(zz, zz); c.translate(-cx, -cy);
      c.drawImage(im, 0, 0, art.w, art.h);
      c.restore();
      return { zz, cx, cy };
    };
    if (art.alpha) {
      // 透明底的立绘：自己没有背景 → 深色渐变 + 星星
      const g = c.createRadialGradient(W / 2, H * 0.45, 50, W / 2, H * 0.5, W * 0.7);
      g.addColorStop(0, '#2b2046'); g.addColorStop(1, '#0b0910');
      c.save(); c.globalAlpha = alpha; c.fillStyle = g; c.fillRect(0, 0, W, H);
      for (let i = 0; i < 140; i++) { c.fillStyle = `rgba(230,220,255,${0.25 + 0.5 * hash(i, 3)})`; c.fillRect(hash(i, 1) * W, hash(i, 2) * H, 2, 2); }
      c.restore();
    } else if ((this.par[art.id] ?? 0) > 0) put(art.bg ?? art.full, 1 + this.par[art.id]!);
    const m = put(art.alpha || (this.par[art.id] ?? 0) <= 0 ? art.full : art.fg, 1.0) ?? { zz: S0, cx: art.w / 2, cy: art.h / 2 };
    const toScr = (x: number, y: number) => ({ x: W / 2 + (x - m.cx) * m.zz, y: H / 2 + (y - m.cy) * m.zz });
    const [x0, y0, x1, y1] = art.box;
    return { tl: toScr(x0, y0), br: toScr(x1, y1), face: toScr(art.cen[0], y0 + (y1 - y0) * 0.16), cen: toScr(art.cen[0], art.cen[1]) };
  }

  render(f: Frame, out: THREE.WebGLRenderTarget) {
    const { renderer, comp } = this.ctx;
    const t = f.t, s = (k: number) => this.s(k), e = (k: number) => this.e(k);
    const c = this.base.ctx, cg = this.glow.ctx;
    this.base.clear(PAL.ink); this.glow.clear();
    const i = this.shotAt(t), sh = this.shots[i]!, prev = i > 0 ? this.shots[i - 1]! : null;
    const chorus = sh.kind === 'chorus';

    // ---------- 曲绘 + 转场
    let pos = { tl: { x: 700, y: 200 }, br: { x: 1300, y: 1000 }, face: { x: 960, y: 360 }, cen: { x: 960, y: 600 } };
    const into = t - sh.a;
    const tin: Shot['tin'] = prev && prev.art === sh.art && sh.tin === 'tear' ? 'flash' : sh.tin;   // 同一张图之间不撕开
    const TR = tin === 'tear' ? 0.6 : tin === 'fade' ? 0.7 : 0;
    if (sh.art >= 0) {
      if (prev && prev.art >= 0 && into < TR && tin === 'fade') {
        this.drawArt(c, prev, f, t);
        pos = this.drawArt(c, sh, f, t, ease.inOutQuad(into / TR));
      } else if (prev && prev.art >= 0 && into < TR && tin === 'tear') {
        // 上一张还在，裂缝撕开、下一张从缝里冲出来（缝开到铺满）
        this.drawArt(c, prev, f, t);
        const open = ease.inCubic(clamp(into / TR));
        const im = this.arts[sh.art]!.full;
        revealArt(c, cg, im, 960, 540, 2600 * open + 200, 1500, Math.min(1, open * 1.3), t, 31 + i, 0.02);
      } else pos = this.drawArt(c, sh, f, t);
    }

    // ---------- 剧场点缀
    const blackout = sh.kind === 'black' ? 1 : 0;
    const stops = this.stopLines;
    const stopK = stops.find((k) => t >= s(k) - 0.05 && t < e(k) + 0.25);
    const stopDark = stopK ? clamp((t - s(stopK) - 0.12) / 0.08) * 0.82 : 0;
    // 10-04 创作者：红幕「太掉价」、开头的金线和星点「太丑」→ 聚光灯、浮尘、星尘粒子、提线、副歌前的裂缝都不画了，只要曲绘
    // 尾声：金缮 —— 金线慢慢爬满画面
    if (sh.kind === 'outro' && this.useKintsugi) { const u = clamp((t - sh.a - 1) / 9); this.kintsugi.forEach((k, j) => drawCrack(c, cg, k, clamp(u * 1.2 - j * 0.08), 2, 0.55)); }
    // 红幕边框：10-04 创作者「这个红色幕帘太掉价，直接删除只要曲绘」→ 不画了
    // 开场：黑底上金线描出「由」，再淡入封面
    // 开头：10-04 创作者「第一帧放封面，然后直接进入曲绘」→ 不黑屏、不画金线「由」
    // 黑场 / 砸字句灭灯
    if (blackout || stopDark) { c.save(); c.globalAlpha = Math.max(blackout, stopDark); c.fillStyle = '#05030a'; c.fillRect(0, 0, W, H); c.restore(); }

    // ---------- 开场「由」、尾声「由」+ 片尾字
    if (sh.kind === 'outro') {
      const lt = t - sh.a;
      if (this.outroGlyph) this.glyph(c, cg, clamp((lt - 5) / 4), 1, 360, 430, this.arts[sh.art]!.side === 'left' ? 520 : 1400);
      const ca = clamp((lt - 1.5) / 1.5) * (1 - clamp((t - sh.b + 1.2) / 1.0));
      if (ca > 0 && this.sign) {
        const g = this.sign;
        c.save(); c.globalAlpha = ca; c.font = this.subFont(g.size, 400); (c as any).letterSpacing = `${Math.round(g.size * 0.08)}px`;
        c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillStyle = '#f2ede6';
        // 「暗边」（mv.json 片尾署名.halo，0–1）：底下亮的图（《傍晚》封面的石栏杆）先压一圈暗影再写字
        if (g.halo) { c.shadowColor = `rgba(0,0,0,${g.halo})`; c.shadowBlur = 16; c.fillText(g.text, g.x, g.y); c.fillText(g.text, g.x, g.y); }
        c.shadowColor = 'rgba(0,0,0,0.6)'; c.shadowBlur = 6; c.fillText(g.text, g.x, g.y); c.restore();
      }
    }

    // ---------- 歌词
    this.lyrics(c, cg, f, sh);

    comp.draw(renderer, this.base.upload(), out, { mode: 'replace' as any, opacity: 1 });
    comp.draw(renderer, this.glow.upload(), out, { mode: 'add', opacity: GLOW });

    const stopFlash = stops.reduce((m, k) => Math.max(m, t >= s(k) && t < s(k) + 0.35 ? 1 - (t - s(k)) / 0.35 : 0), 0);
    const tearFlash = tin === 'tear' && into < 0.75 ? Math.max(0, 1 - Math.abs(into - 0.6) / 0.15) : tin === 'flash' && prev && prev.art >= 0 && into < 0.3 ? 1 - into / 0.3 : 0;
    return {
      bloom: 0.6, bloomThreshold: 1.0, bloomKnee: 0.6, bloomRadius: 0.8, halation: 0.18, ca: chorus ? 1.3 : 0.7,
      grain: 0.045, vignette: 0.42, zoom: 1, flash: 0.3 * stopFlash + 0.2 * tearFlash,
      fade: smoothstep(this.ctx.audio.duration - 2.5, this.ctx.audio.duration - 0.2, t),
      shake: [0, 0] as [number, number],
    };
  }

  /** 金线描的「由」。 */
  private glyph(c: C2, cg: C2, p: number, a: number, size: number, y: number, x = W / 2) {
    if (p <= 0 || a <= 0) return;
    const ch = String.fromCharCode(0x7531);
    for (const [cc, lw, al] of [[c, 3, 1], [cg, 5, 0.85]] as const) {
      cc.save(); cc.globalAlpha = a * al; cc.font = font(FAM, size); cc.textAlign = 'center'; cc.textBaseline = 'middle';
      cc.beginPath(); cc.rect(0, y - size * 0.6, W, size * 1.2 * clamp(p)); cc.clip();
      cc.strokeStyle = PAL.gold; cc.lineWidth = lw; cc.lineJoin = 'round'; cc.strokeText(ch, x, y); cc.restore();
    }
  }

  // ------------------------------------------------------------ 字幕（10-04）：白色，不发光、不弹跳；三种排法（mv.json「字幕样式」或 ?sub=A|B|C）：
  //   A 横排 · 底部居中（创作者选的）     B 竖排 · 人物对面那侧 + 一条细竖线     C 横排 · 左下角 + 暗红短线 + 「」
  // 字体：创作者「宋体不行，以后都不要宋体」「定死规矩不要宋体」→ 不用宋体（engine/type.ts 的 checkFont 拦）。mv.json「字幕字体」或 ?font=
  private subFont(size: number, weight = 300) {
    const k = this.fontKey;
    const css = k === 'yahei' ? `${size}px "Microsoft YaHei Light", "Microsoft YaHei"`
      : k === 'brush' ? `${size * 1.08}px "MaShanZheng"`
      : k === 'kai' ? `${size * 1.05}px "STKaiti", "KaiTi"`
      : `${weight} ${size}px "Noto Sans SC", "Microsoft YaHei"`;      // hei：思源黑体（细）
    return checkFont(css);
  }

  /** 一句歌词的每个字：唱到之前 0.45 透明，唱到时 0.25 秒变全白。 */
  private charAlpha(l: Line, t: number, k: number) { return 0.55 + 0.45 * clamp(sungK(l, t, k) * 2); }

  private subA(c: C2, l: Line, t: number, a: number, y = 968, size = 50) {
    const cs = chars(l);
    c.save(); c.font = this.subFont(size); (c as any).letterSpacing = `${Math.round(size * 0.16)}px`;
    c.textAlign = 'left'; c.textBaseline = 'middle';
    const ws = cs.map((ch) => c.measureText(ch).width);
    const tot = ws.reduce((s, w) => s + w, 0);
    let x = W / 2 - tot / 2;
    // 「字幕暗边」（mv.json，0–1）：字底下是亮的（《傍晚》封面的石栏杆），没唱到的灰字会看不清 → 先压一圈暗影
    if (this.subHalo) {
      c.shadowColor = `rgba(0,0,0,${this.subHalo})`; c.shadowBlur = 18; c.shadowOffsetY = 0; c.fillStyle = '#f6f1ea';
      let hx = x;
      cs.forEach((ch, k) => { c.globalAlpha = a * this.charAlpha(l, t, k); c.fillText(ch, hx, y); c.fillText(ch, hx, y); hx += ws[k]!; });
    }
    c.shadowColor = 'rgba(0,0,0,0.75)'; c.shadowBlur = 10; c.shadowOffsetY = 2;
    cs.forEach((ch, k) => { c.globalAlpha = a * this.charAlpha(l, t, k); c.fillStyle = '#f6f1ea'; c.fillText(ch, x, y); x += ws[k]!; });
    c.restore();
  }

  private subB(c: C2, l: Line, t: number, a: number, x: number, size = 46) {
    const cs = chars(l), n = cs.length, step = size * 1.32;
    const y0 = 540 - (n - 1) * step / 2;
    c.save(); c.font = this.subFont(size, 400); c.textAlign = 'center'; c.textBaseline = 'middle';
    c.globalAlpha = a * 0.35; c.fillStyle = '#f6f1ea'; c.fillRect(x + size * 0.85, y0 - size * 0.6, 1, (n - 1) * step + size * 1.2);   // 细竖线
    c.shadowColor = 'rgba(0,0,0,0.75)'; c.shadowBlur = 10; c.shadowOffsetY = 2;
    cs.forEach((ch, k) => { c.globalAlpha = a * this.charAlpha(l, t, k); c.fillStyle = '#f6f1ea'; c.fillText(ch, x, y0 + k * step); });
    c.restore();
  }

  private subC(c: C2, l: Line, t: number, a: number, y = 940, size = 50) {
    const cs = ['\u300c', ...chars(l), '\u300d'];
    c.save(); c.font = this.subFont(size); (c as any).letterSpacing = `${Math.round(size * 0.12)}px`;
    c.textAlign = 'left'; c.textBaseline = 'middle';
    let x = 170;
    c.globalAlpha = a * 0.9; c.fillStyle = '#8f1d2a'; c.fillRect(110, y - 1, 46, 2);                // 暗红短线
    c.shadowColor = 'rgba(0,0,0,0.75)'; c.shadowBlur = 10; c.shadowOffsetY = 2;
    cs.forEach((ch, k) => {
      const al = k === 0 || k === cs.length - 1 ? 0.7 : this.charAlpha(l, t, k - 1);
      c.globalAlpha = a * al; c.fillStyle = '#f6f1ea'; c.fillText(ch, x, y); x += c.measureText(ch).width;
    });
    c.restore();
  }

  /** 三句「停止……」：灭灯的黑底上，大号细宋体慢慢浮现（字距慢慢收拢）。 */
  private subStop(c: C2, l: Line, t: number, a: number) {
    const u = ease.outCubic(clamp((t - l.start) / 0.9));
    c.save(); c.font = this.subFont(96, 300); (c as any).letterSpacing = `${Math.round(48 - 24 * u)}px`;
    c.textAlign = 'center'; c.textBaseline = 'middle'; c.globalAlpha = a * clamp((t - l.start + 0.05) / 0.5);
    c.fillStyle = '#f6f1ea'; c.fillText(chars(l).join(''), W / 2 + 12, 540);
    c.restore();
  }

  private lyrics(c: C2, cg: C2, f: Frame, sh: Shot) {
    const t = f.t, Ls = this.ctx.lyrics.lines;
    const art = sh.art >= 0 ? this.arts[sh.art]! : null;
    const leftSide = art ? this.view(sh, f, t).side === 'left' : true;
    const st = this.subStyle;
    // 字幕底下一层很淡的暗色，曲绘太亮时字也看得清（A / C 在底部，B 在字那一侧）
    if (sh.kind !== 'black') {
      if (st === 'B') {
        const g = c.createLinearGradient(leftSide ? 0 : W, 0, leftSide ? 420 : W - 420, 0);
        g.addColorStop(0, 'rgba(6,4,10,0.42)'); g.addColorStop(1, 'rgba(6,4,10,0)');
        c.fillStyle = g; c.fillRect(leftSide ? 0 : W - 420, 0, 420, H);
      } else {
        const g = c.createLinearGradient(0, H, 0, H - 260);
        g.addColorStop(0, 'rgba(6,4,10,0.5)'); g.addColorStop(1, 'rgba(6,4,10,0)');
        c.fillStyle = g; c.fillRect(0, H - 260, W, 260);
      }
    }
    // 每句什么时候出、什么时候收：同一位置（A / C）上一句完全收掉、下一句才出（10-04 v07：有一句和下一句叠了 0.25 秒）。
    // B 两列交替，可以多留一会
    const hide = (k: number) => { const l = Ls[k - 1]!, nx = Ls[k] ?? null; return st === 'B' ? l.end + 0.5 : Math.min(l.end + 0.5, nx ? nx.start - 0.02 : 1e9); };
    for (let n = 1; n <= Ls.length; n++) {
      const l = Ls[n - 1]!;
      const a1 = hide(n);
      const a0 = st === 'B' || n === 1 ? l.start - 0.3 : Math.max(l.start - 0.3, hide(n - 1));
      if (t < a0 || t > a1) continue;
      const fin = Math.min(0.3, Math.max(0.08, l.start - a0)), fout = Math.min(0.25, Math.max(0.08, a1 - l.end + 0.08));   // 紧挨着下一句：唱完才快收
      const a = clamp((t - a0) / fin) * (1 - clamp((t - (a1 - fout)) / fout));
      if (this.stopLines.includes(n)) { this.subStop(c, l, t, a); continue; }
      if (st === 'B' && !(n >= 52 && n <= 66)) {
        const col = n % 2 === 1 ? 0 : 1;
        const x = leftSide ? [150, 250][col]! : [W - 150, W - 250][col]!;
        this.subB(c, l, t, a, x);
      } else if (st === 'C') this.subC(c, l, t, a);
      else this.subA(c, l, t, a);
    }
  }
}

export const _u = TAU;
