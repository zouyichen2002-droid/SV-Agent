// 《逃跑的天使》手账 MV 的画画工具（SV-Agent 10-03）：配色、基本形、小天使、道具、逐字歌词。
// 全部 Canvas2D、逻辑像素 1920x1080；一切只由时间决定（不用 Math.random）。不写歌词原文（歌词从 song/lyrics.json 来）。
import { Lyrics, type Line } from '../../engine/lyrics';
import { font, layout } from '../../engine/type';
import { clamp, ease, hash, smoothstep, TAU } from '../../engine/util';

export const COL = {
  paper: '#F6EFE3', paper2: '#EDE1CC', line: '#E3D6C0',
  ink: '#3A3340', ink2: '#6B6470',
  gold: '#F2B544', gold2: '#FFE08A',
  pink: '#F4A6B7', pink2: '#FBD3DC',
  blue: '#9CCBEA', blue2: '#CFE6F5',
  mint: '#A9DFC5', red: '#E2614F', orange: '#F29B54',
  gray: '#B8B2AA', gray2: '#8E8780', gray3: '#D9D3CA',
  white: '#FFFDF8', skin: '#FFE3CF', hair: '#F7D58B',
  night: '#1E2238', night2: '#2C3152', suit: '#4B4E63', wood: '#C99A6B',
} as const;

export const FONT = 'KuaiLe';
/** 当前这一帧的底鼓脉冲（journal 每帧设一次）：小天使跟着一压一弹。 */
let KICK = 0;
export const setKick = (k: number) => { KICK = k; };
export type C2 = CanvasRenderingContext2D;

// ---------------------------------------------------------------- 基本形
export function pen(c: C2, w = 4, col: string = COL.ink) {
  c.lineWidth = w; c.strokeStyle = col; c.lineJoin = 'round'; c.lineCap = 'round';
}
export function rr(c: C2, x: number, y: number, w: number, h: number, r: number) {
  const k = Math.min(r, w / 2, h / 2);
  c.beginPath();
  c.moveTo(x + k, y); c.lineTo(x + w - k, y); c.quadraticCurveTo(x + w, y, x + w, y + k);
  c.lineTo(x + w, y + h - k); c.quadraticCurveTo(x + w, y + h, x + w - k, y + h);
  c.lineTo(x + k, y + h); c.quadraticCurveTo(x, y + h, x, y + h - k);
  c.lineTo(x, y + k); c.quadraticCurveTo(x, y, x + k, y); c.closePath();
}
export function fs(c: C2, fill: string | null, w = 4, stroke: string | null = COL.ink) {
  if (fill) { c.fillStyle = fill; c.fill(); }
  if (stroke && w > 0) { pen(c, w, stroke); c.stroke(); }
}
export function circle(c: C2, x: number, y: number, r: number) { c.beginPath(); c.arc(x, y, Math.max(0.1, r), 0, TAU); }
export function ell(c: C2, x: number, y: number, rx: number, ry: number, rot = 0) {
  c.beginPath(); c.ellipse(x, y, Math.max(0.1, rx), Math.max(0.1, ry), rot, 0, TAU);
}
export function line(c: C2, x1: number, y1: number, x2: number, y2: number, w = 4, col: string = COL.ink) {
  c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); pen(c, w, col); c.stroke();
}
export function poly(c: C2, pts: number[], close = true) {
  c.beginPath(); c.moveTo(pts[0]!, pts[1]!);
  for (let i = 2; i < pts.length; i += 2) c.lineTo(pts[i]!, pts[i + 1]!);
  if (close) c.closePath();
}
/** 一组圆拼成的云：先描粗边再填色，得到整朵云的外轮廓。 */
export function cloud(c: C2, x: number, y: number, s: number, fill: string = COL.white, w = 4, stroke: string = COL.ink) {
  const b = [[-60, 10, 42], [-20, -18, 52], [30, -10, 46], [68, 14, 36], [0, 22, 44]];
  c.save(); c.translate(x, y); c.scale(s, s);
  if (w > 0) { for (const [bx, by, r] of b) { circle(c, bx!, by!, r! + w / s); c.fillStyle = stroke; c.fill(); } }
  for (const [bx, by, r] of b) { circle(c, bx!, by!, r!); c.fillStyle = fill; c.fill(); }
  if (w > 0) {
    // 底下一层淡蓝的阴影（只在云里面）
    c.beginPath();
    for (const [bx, by, r] of b) { c.moveTo(bx! + r!, by!); c.arc(bx!, by!, r!, 0, TAU); }
    c.save(); c.clip();
    const g = c.createLinearGradient(0, -40, 0, 70); g.addColorStop(0, 'rgba(156,203,234,0)'); g.addColorStop(1, 'rgba(156,203,234,0.38)');
    c.fillStyle = g; c.fillRect(-110, -80, 220, 160);
    c.restore();
  }
  c.restore();
}
export function star(c: C2, x: number, y: number, r: number, n = 5, inner = 0.45, rot = -Math.PI / 2) {
  c.beginPath();
  for (let i = 0; i < n * 2; i++) {
    const a = rot + (i * Math.PI) / n, rr2 = i % 2 ? r * inner : r;
    i ? c.lineTo(x + Math.cos(a) * rr2, y + Math.sin(a) * rr2) : c.moveTo(x + Math.cos(a) * rr2, y + Math.sin(a) * rr2);
  }
  c.closePath();
}
export function heart(c: C2, x: number, y: number, s: number) {
  c.beginPath();
  c.moveTo(x, y + s * 0.35);
  c.bezierCurveTo(x - s * 1.1, y - s * 0.35, x - s * 0.55, y - s * 1.05, x, y - s * 0.5);
  c.bezierCurveTo(x + s * 0.55, y - s * 1.05, x + s * 1.1, y - s * 0.35, x, y + s * 0.35);
  c.closePath();
}
export function sparkle(c: C2, x: number, y: number, r: number, col: string = COL.gold) {
  c.beginPath();
  c.moveTo(x, y - r); c.quadraticCurveTo(x, y, x + r, y); c.quadraticCurveTo(x, y, x, y + r);
  c.quadraticCurveTo(x, y, x - r, y); c.quadraticCurveTo(x, y, x, y - r); c.closePath();
  c.fillStyle = col; c.fill();
}
export function text(c: C2, s: string, x: number, y: number, size: number, col: string = COL.ink, align: CanvasTextAlign = 'center', fam = FONT) {
  c.font = font(fam, size); c.fillStyle = col; c.textAlign = align; c.textBaseline = 'middle'; c.fillText(s, x, y);
}
export const R = (i: number, s = 0) => hash(i, s); // 0..1，固定的「随机」
export const osc = (t: number, hz = 1, ph = 0) => Math.sin((t * hz + ph) * TAU);
export const pop = (t: number, t0: number, dur = 0.35) => ease.outBack(clamp((t - t0) / dur));
export const fadeIn = (t: number, t0: number, dur = 0.3) => smoothstep(t0, t0 + dur, t);

/** 整页底色（纸或夜）+ 一点暗角；每格自己画，平移时整页一起动。 */
export function page(c: C2, W: number, H: number, kind: 'paper' | 'night' | 'gray' | 'sky' | 'pink' = 'paper', t = 0) {
  const top = { paper: COL.paper, night: COL.night2, gray: '#E4E0DA', sky: '#DCEEF8', pink: '#FCE9EE' }[kind];
  const bot = { paper: COL.paper2, night: COL.night, gray: '#CFC9C1', sky: '#F6EFE3', pink: '#F6EFE3' }[kind];
  const g = c.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, top); g.addColorStop(1, bot);
  c.fillStyle = g; c.fillRect(-4, -4, W + 8, H + 8);
  // 手账的点格
  c.fillStyle = kind === 'night' ? 'rgba(255,255,255,0.06)' : 'rgba(58,51,64,0.07)';
  for (let y = 60; y < H; y += 60) for (let x = 60; x < W; x += 60) { c.beginPath(); c.arc(x, y, 2.2, 0, TAU); c.fill(); }
  // 纸上淡淡飘着的小涂鸦（星、心、圈），夜里是小星星
  for (let i = 0; i < 14; i++) {
    const x = R(i, 21) * W, y = (R(i, 22) * H - t * (6 + R(i, 23) * 10) + H * 2) % H;
    const a = 0.12 + 0.08 * Math.sin(t * 0.7 + i);
    c.save(); c.translate(x, y); c.rotate(t * 0.2 * (R(i, 24) - 0.5) + i);
    if (kind === 'night') { sparkle(c, 0, 0, 5 + R(i, 25) * 5, `rgba(255,224,138,${a * 2.5})`); c.restore(); continue; }
    c.globalAlpha *= a;
    const kd = i % 3;
    if (kd === 0) { star(c, 0, 0, 14); pen(c, 3, COL.ink); c.stroke(); }
    else if (kd === 1) { heart(c, 0, 4, 16); pen(c, 3, COL.ink); c.stroke(); }
    else { circle(c, 0, 0, 9); pen(c, 3, COL.ink); c.stroke(); }
    c.restore();
  }
}

/** 日历纸一张张从 (x, y) 撕下来，各自朝右上方翻飞、淡出。rate = 每秒几张。 */
export function flyPages(c: C2, x: number, y: number, lt: number, rate: number, n: number) {
  for (let i = 0; i < n; i++) {
    const born = i / rate;
    const life = 1.6;
    const age = ((lt - born) % (n / rate) + n / rate) % (n / rate);
    if (lt < born || age > life) continue;
    const v = age / life;
    const tx = x + 420 + R(i, 1) * 1000, ty = y - 220 - R(i, 2) * 420;
    const px = x + (tx - x) * ease.outQuad(v), py = y + (ty - y) * v - Math.sin(v * Math.PI) * (80 + R(i, 3) * 120);
    c.save(); c.globalAlpha *= 1 - smoothstep(0.7, 1, v);
    c.translate(px, py); c.rotate(v * (4 + R(i, 4) * 6) * (R(i, 5) > 0.5 ? 1 : -1));
    c.scale(1, 0.55 + 0.45 * Math.abs(Math.cos(v * 7 + i)));
    rr(c, -50, -55, 100, 110, 8); fs(c, COL.white, 3);
    line(c, -30, -20, 30, -20, 2, COL.gray3); line(c, -30, 0, 30, 0, 2, COL.gray3);
    c.restore();
  }
}

// ---------------------------------------------------------------- 小天使
export interface AngelOpts {
  t: number;
  mood?: 'happy' | 'calm' | 'sad' | 'tired' | 'blank' | 'cry' | 'laugh' | 'sleep' | 'shock' | 'wink' | 'drool' | 'dead';
  halo?: number; // 0 熄 .. 1 亮
  wings?: number; // 0 没有 .. 1 正常
  flap?: number; // 扇翅膀的速度（Hz）
  armL?: number; armR?: number; // 手臂角度（0 = 垂下，正 = 往外抬）
  walk?: number; // 走路相位（秒）；undefined = 站着
  lean?: number; // 整个身体倾斜
  bow?: number; // 鞠躬 0..1
  suit?: boolean; hat?: boolean; bag?: boolean; badge?: boolean;
  alpha?: number; ghost?: boolean; tie?: string;
  blink?: boolean;
  /** 脚下的影子（默认有；飞着、躺着的时候关掉） */
  shadow?: boolean;
}
export function angel(c: C2, x: number, y: number, s: number, o: AngelOpts) {
  const t = o.t, mood = o.mood ?? 'happy';
  c.save();
  c.globalAlpha *= o.alpha ?? 1;
  c.translate(x, y); c.scale(s, s);
  // 地上的影子（不跟着身体倾斜）
  if (o.shadow !== false && !o.ghost) { ell(c, 0, 4, 66, 13); c.fillStyle = 'rgba(58,51,64,0.13)'; c.fill(); }
  c.rotate(o.lean ?? 0);
  const walking = o.walk !== undefined;
  const wp = walking ? o.walk! * 2.2 : 0;
  const bob = walking ? Math.abs(Math.sin(wp * Math.PI)) * -7 : osc(t, 0.45) * 1.6; // 走路一颠一颠；站着轻轻呼吸
  c.translate(0, bob);
  c.scale(1 + 0.035 * KICK, 1 - 0.045 * KICK); // 跟着底鼓一压
  // 腿 / 幽灵尾巴
  if (o.ghost) {
    c.beginPath(); c.moveTo(-52, -70);
    c.quadraticCurveTo(-60, -30, -44, -10);
    for (let i = 0; i < 4; i++) {
      const x0 = -44 + i * 29.3, wv = osc(t, 1.4, i * 0.25) * 5;
      c.quadraticCurveTo(x0 + 7, -26 + wv, x0 + 14.6, -14 + wv); c.quadraticCurveTo(x0 + 22, -2 + wv, x0 + 29.3, -12);
    }
    c.quadraticCurveTo(60, -30, 52, -70); c.closePath();
    fs(c, 'rgba(255,253,248,0.82)', 4);
  } else {
    const sw = walking ? Math.sin(wp * Math.PI) * 0.38 : 0;
    for (const [side, a] of [[-1, -sw], [1, sw]] as const) {
      c.save(); c.translate(side * 17, -64); c.rotate(a);
      rr(c, -10, 0, 20, 54, 10); fs(c, o.suit ? COL.suit : COL.skin, 4);
      ell(c, side * 5, 56, 16, 10); fs(c, o.suit ? COL.ink2 : COL.pink, 4);
      c.restore();
    }
  }
  c.save();
  // 鞠躬：上半身绕腰转
  const bowA = (o.bow ?? 0) * 1.05;
  c.translate(0, -66); c.rotate(bowA); c.translate(0, 66);
  // 翅膀（身后）：一层层圆羽毛
  const wg = o.wings ?? 1;
  if (wg > 0.01) {
    const fl = Math.sin(t * TAU * (o.flap ?? 0.8)) * 0.2;
    for (const side of [-1, 1]) {
      c.save(); c.translate(side * 22, -136); c.rotate(side * (-0.2 + fl)); c.scale(side * wg, wg);
      wing(c);
      c.restore();
    }
  }
  if (o.bag) { rr(c, -70, -150, 38, 78, 14); fs(c, COL.pink, 4); line(c, -40, -146, -18, -146, 5); }
  // 身体
  if (o.suit) {
    c.beginPath(); c.moveTo(-26, -154); c.lineTo(-50, -64); c.quadraticCurveTo(0, -54, 50, -64); c.lineTo(26, -154); c.closePath();
    fs(c, COL.suit, 4);
    poly(c, [-13, -154, 13, -154, 0, -116]); fs(c, COL.white, 3);
    poly(c, [-5, -140, 5, -140, 8, -100, 0, -90, -8, -100]); fs(c, o.tie ?? COL.red, 3);
    circle(c, 0, -80, 3.5); c.fillStyle = COL.ink; c.fill();
  } else {
    c.beginPath(); c.moveTo(-22, -154);
    c.bezierCurveTo(-34, -122, -50, -92, -60, -64);
    for (let i = 0; i < 4; i++) { const x0 = -60 + i * 30; c.quadraticCurveTo(x0 + 15, -44, x0 + 30, -64); }
    c.bezierCurveTo(50, -92, 34, -122, 22, -154); c.closePath();
    const g = c.createLinearGradient(0, -154, 0, -50); g.addColorStop(0, COL.white); g.addColorStop(1, '#E3ECF4');
    c.fillStyle = g; c.fill(); pen(c, 4); c.stroke();
    ell(c, -11, -150, 14, 8, 0.35); fs(c, COL.pink, 3); ell(c, 11, -150, 14, 8, -0.35); fs(c, COL.pink, 3);
    star(c, 0, -112, 10); fs(c, COL.gold, 2.5);
  }
  if (o.badge) { line(c, 30, -152, 30, -124, 2, COL.ink2); rr(c, 17, -124, 28, 34, 5); fs(c, COL.blue2, 3); }
  // 手臂（胖胖的袖子 + 手）：a = 0 垂下，π/2 平举向外，π 举过头；负的往里收
  const sleeve = o.suit ? COL.suit : COL.white;
  const arm = (side: number, a: number) => {
    const sx = side * 25, sy = -142, len = 54 + 46 * smoothstep(1.9, 2.9, Math.abs(a));
    const hx = sx + side * Math.sin(a) * len, hy = sy + Math.cos(a) * len;
    c.beginPath(); c.moveTo(sx, sy); c.lineTo(hx, hy);
    pen(c, 21, COL.ink); c.stroke(); pen(c, 13, sleeve); c.stroke();
    circle(c, hx, hy, 11); fs(c, COL.skin, 4);
  };
  arm(-1, o.armL ?? 0.25); arm(1, o.armR ?? 0.25);
  // 头
  const hg = c.createRadialGradient(-18, -232, 8, 0, -208, 64); hg.addColorStop(0, '#FFF1E4'); hg.addColorStop(1, COL.skin);
  circle(c, 0, -208, 60); c.fillStyle = hg; c.fill(); pen(c, 4); c.stroke();
  // 头发：圆顶 + 三撮刘海 + 一根呆毛
  c.beginPath(); c.moveTo(-62, -200);
  c.bezierCurveTo(-68, -292, 68, -292, 62, -200);
  c.quadraticCurveTo(54, -228, 38, -218); c.quadraticCurveTo(24, -244, 6, -224);
  c.quadraticCurveTo(-12, -246, -28, -222); c.quadraticCurveTo(-48, -236, -62, -200); c.closePath();
  const hgr = c.createLinearGradient(0, -280, 0, -200); hgr.addColorStop(0, '#FBE3A6'); hgr.addColorStop(1, COL.hair);
  c.fillStyle = hgr; c.fill(); pen(c, 4); c.stroke();
  c.beginPath(); c.moveTo(4, -266); c.bezierCurveTo(8, -304, 44, -300, 32, -278); pen(c, 4); c.stroke();
  c.beginPath(); c.arc(-22, -246, 26, Math.PI * 1.12, Math.PI * 1.55); pen(c, 6, 'rgba(255,255,255,0.75)'); c.stroke();
  face(c, t, mood, o.blink ?? true);
  c.restore();
  // 光环 / 帽子
  const hl = o.halo ?? 1;
  const hy = -66 - 236 * Math.cos(bowA) + osc(t, 0.5) * 3; // 光环跟着头绕腰转（鞠躬）
  if (o.hat) {
    c.save(); c.translate(0, -258);
    ell(c, 0, 8, 76, 16); fs(c, COL.blue, 4);
    c.beginPath(); c.moveTo(-52, 8); c.bezierCurveTo(-52, -62, 52, -62, 52, 8); c.closePath(); fs(c, COL.blue, 4);
    line(c, -48, -6, 48, -6, 7, COL.pink);
    c.restore();
  } else if (hl > 0.01) {
    c.save();
    c.translate(236 * Math.sin(bowA), hy);
    c.shadowColor = `rgba(255,214,110,${0.9 * hl})`; c.shadowBlur = 28 * hl;
    ell(c, 0, 0, 50, 14); pen(c, 10, hl > 0.5 ? COL.gold : mix(COL.gray, COL.gold, hl * 2)); c.stroke();
    c.shadowBlur = 0;
    ell(c, 0, 0, 50, 14); pen(c, 2.5, COL.ink); c.stroke();
    c.beginPath(); c.ellipse(0, 0, 50, 14, 0, Math.PI * 1.15, Math.PI * 1.45); pen(c, 3, `rgba(255,250,220,${hl})`); c.stroke();
    c.restore();
  }
  c.restore();
}

/** 一只翅膀：根在 (0,0)，往 +x、往上展开；下边是一圈往外鼓的圆羽毛。 */
function wing(c: C2) {
  c.beginPath();
  c.moveTo(0, 8);
  c.bezierCurveTo(8, -52, 70, -100, 142, -96);
  c.bezierCurveTo(156, -95, 160, -80, 150, -70);
  const pts = [[150, -70], [132, -42], [106, -20], [74, -4], [38, 10]];
  for (let i = 0; i < pts.length - 1; i++) {
    const [x1, y1] = pts[i]!, [x2, y2] = pts[i + 1]!;
    const dx = x2! - x1!, dy = y2! - y1!, L = Math.hypot(dx, dy) || 1;
    c.quadraticCurveTo((x1! + x2!) / 2 + (dy / L) * 18, (y1! + y2!) / 2 - (dx / L) * 18, x2!, y2!);
  }
  c.quadraticCurveTo(18, 22, 0, 8); c.closePath();
  const g = c.createLinearGradient(0, -96, 40, 20); g.addColorStop(0, COL.white); g.addColorStop(1, '#D9E8F4');
  c.fillStyle = g; c.fill(); pen(c, 4); c.stroke();
  c.beginPath(); c.moveTo(22, -14); c.quadraticCurveTo(70, -58, 124, -74); pen(c, 3, '#BFD3E3'); c.stroke();
  c.beginPath(); c.moveTo(36, 0); c.quadraticCurveTo(70, -26, 104, -38); pen(c, 3, '#BFD3E3'); c.stroke();
}

function face(c: C2, t: number, mood: string, blink: boolean) {
  const ey = -200, ex = 21;
  const bl = blink && (t * 0.37 % 1 > 0.965) ? 0.12 : 1; // 偶尔眨眼
  c.fillStyle = COL.ink; c.strokeStyle = COL.ink;
  const dots = (sy = 1) => {
    for (const sx of [-ex, ex]) {
      ell(c, sx, ey, 7, 9 * bl * sy); c.fillStyle = COL.ink; c.fill();
      if (bl > 0.5) { circle(c, sx + 2.6, ey - 3.6, 2.8); c.fillStyle = COL.white; c.fill(); }
    }
  };
  const arcs = (up: boolean) => {
    for (const sx of [-ex, ex]) { c.beginPath(); up ? c.arc(sx, ey + 4, 9, Math.PI * 1.1, Math.PI * 1.9) : c.arc(sx, ey - 6, 9, Math.PI * 0.1, Math.PI * 0.9); pen(c, 4); c.stroke(); }
  };
  const lines = () => { for (const sx of [-ex, ex]) line(c, sx - 9, ey, sx + 9, ey, 4); };
  switch (mood) {
    case 'happy': case 'calm': dots(); break;
    case 'wink': dots(); break;
    case 'sad': dots(); line(c, -ex - 10, ey - 18, -ex + 8, ey - 24, 3); line(c, ex + 10, ey - 18, ex - 8, ey - 24, 3); break;
    case 'tired': lines(); line(c, -ex - 8, ey + 10, -ex + 8, ey + 10, 2, COL.ink2); line(c, ex - 8, ey + 10, ex + 8, ey + 10, 2, COL.ink2); break;
    case 'blank': for (const sx of [-ex, ex]) { circle(c, sx, ey, 10); fs(c, COL.white, 3); circle(c, sx, ey, 2.5); c.fillStyle = COL.ink; c.fill(); } break;
    case 'cry': case 'sleep': case 'dead': arcs(false); break;
    case 'laugh': for (const sx of [-1, 1]) { c.beginPath(); c.moveTo(sx * ex - 9 * sx, ey - 8); c.lineTo(sx * ex + 7 * sx, ey); c.lineTo(sx * ex - 9 * sx, ey + 8); pen(c, 4); c.stroke(); } break;
    case 'shock': for (const sx of [-ex, ex]) { circle(c, sx, ey, 9); fs(c, COL.white, 3); } break;
    case 'drool': arcs(true); break;
  }
  if (mood === 'dead') { for (const sx of [-ex, ex]) { line(c, sx - 8, ey - 8, sx + 8, ey + 8, 4); line(c, sx - 8, ey + 8, sx + 8, ey - 8, 4); } }
  // 腮红
  if (mood !== 'dead' && mood !== 'blank') {
    c.fillStyle = 'rgba(244,166,183,0.75)'; ell(c, -36, -180, 11, 6); c.fill(); ell(c, 36, -180, 11, 6); c.fill();
  }
  // 嘴
  const my = -172;
  c.beginPath();
  switch (mood) {
    case 'happy': case 'wink': c.arc(0, my - 6, 10, Math.PI * 0.15, Math.PI * 0.85); pen(c, 4); c.stroke(); break;
    case 'laugh': c.moveTo(-16, my - 6); c.quadraticCurveTo(0, my + 26, 16, my - 6); c.closePath(); fs(c, COL.red, 4); break;
    case 'drool': c.moveTo(-14, my - 4); c.quadraticCurveTo(0, my + 16, 14, my - 4); c.closePath(); fs(c, COL.red, 3);
      ell(c, 10, my + 16 + (t * 2 % 1) * 10, 4, 7); c.fillStyle = COL.blue; c.fill(); break;
    case 'shock': ell(c, 0, my, 8, 11); fs(c, COL.ink, 0, null); break;
    case 'sad': case 'cry': c.arc(0, my + 6, 10, Math.PI * 1.15, Math.PI * 1.85); pen(c, 4); c.stroke(); break;
    default: c.moveTo(-9, my); c.lineTo(9, my); pen(c, 4); c.stroke();
  }
}

/** 两个 #rrggbb 颜色按 k 混合。 */
export function mix(a: string, b: string, k: number) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const ch = (sh: number) => Math.round(((pa >> sh) & 255) * (1 - k) + ((pb >> sh) & 255) * k);
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}

// ---------------------------------------------------------------- 逐字歌词
export interface LyricStyle {
  x?: number; y?: number; size?: number; color?: string; dim?: string; maxW?: number;
  rot?: number; fam?: string; chalk?: boolean; shadow?: string | null; typewriter?: boolean; jitter?: number;
  /** 字后面的纸条（手账胶带）；false = 不要（黑板、屏幕上的字） */
  plate?: string | false;
}
/**
 * 一句歌词：整句先淡淡显出，唱到哪个字哪个字弹出来、变实。字和逐字时间一一对应（中文一个字一个单位）；
 * 对不上时退回按整句进度。typewriter：没唱到的字不显示（打字机）。
 */
export function lyric(c: C2, l: Line, t: number, st: LyricStyle = {}) {
  const fam = st.fam ?? FONT;
  const maxW = st.maxW ?? 1500;
  let size = st.size ?? 66;
  let lay = layout(l.text, fam, size);
  if (lay.width > maxW) { size = (size * maxW) / lay.width; lay = layout(l.text, fam, size); }
  const x0 = (st.x ?? 960) - lay.width / 2, y = st.y ?? 950;
  const oneToOne = l.words.length === lay.glyphs.length;
  const sungChars = Lyrics.lineCharProgress(l, t);
  c.save();
  if (st.rot) { c.translate(st.x ?? 960, y); c.rotate(st.rot); c.translate(-(st.x ?? 960), -y); }
  if (st.plate !== false) {
    // 纸条 + 两头的胶带
    const px = x0 - size * 0.55, pw = lay.width + size * 1.1, ph = size * 1.45;
    rr(c, px, y - ph / 2, pw, ph, size * 0.3);
    c.fillStyle = st.plate ?? 'rgba(255,253,248,0.86)'; c.fill();
    for (const [tx, col] of [[px + 8, 'rgba(244,166,183,0.75)'], [px + pw - 8, 'rgba(156,203,234,0.75)']] as const) {
      c.save(); c.translate(tx, y - ph / 2 + 4); c.rotate(tx < 960 ? -0.5 : 0.5);
      c.fillStyle = col; c.fillRect(-size * 0.5, -size * 0.16, size, size * 0.32); c.restore();
    }
  }
  c.font = font(fam, size); c.textBaseline = 'middle'; c.textAlign = 'center';
  lay.glyphs.forEach((g, i) => {
    const w = oneToOne ? l.words[i]! : null;
    const k = w ? clamp((t - w.start) / 0.14) : clamp(sungChars - i);
    if (st.typewriter && k <= 0) return;
    const sc = k > 0 ? 0.55 + 0.45 * ease.outBack(k) : 1;
    const jy = st.jitter ? Math.sin(t * 9 + i) * st.jitter : 0;
    c.save();
    c.translate(x0 + g.x + g.w / 2, y + jy - (k > 0 && k < 1 ? 10 * Math.sin(Math.PI * k) : 0));
    c.scale(sc, sc);
    if (k > 0 && st.shadow !== null) { c.fillStyle = st.shadow ?? 'rgba(58,51,64,0.16)'; c.fillText(g.ch, 4, 5); }
    c.fillStyle = k > 0 ? (st.color ?? COL.ink) : (st.dim ?? 'rgba(58,51,64,0.16)');
    if (st.chalk && k > 0) { c.globalAlpha *= 0.92; }
    c.fillText(g.ch, 0, 0);
    c.restore();
  });
  c.restore();
}
