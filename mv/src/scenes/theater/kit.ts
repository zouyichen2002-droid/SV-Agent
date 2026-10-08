// 《由》人偶剧场 MV 的画画工具（SV-Agent 10-04）：舞台、灯、浮尘、提线瓷人偶、裂缝、歌词的几种放法。
// 两层画布：base（正常颜色）+ glow（只画发光的东西，叠加时乘 2 以上 → 超过 1 → 引擎的泛光让它真的发光）。
// 只由歌曲时间决定，没有状态。代码里没有歌词原文（歌词从仓库外的 lyrics.json 读）。
import { W, H } from '../../engine/gl';
import { clamp, ease, hash, lerp, noise1, TAU } from '../../engine/util';
import { font } from '../../engine/type';
import { Lyrics, type Line } from '../../engine/lyrics';

export type C2 = CanvasRenderingContext2D;
type Pt = { x: number; y: number };

export const PAL = {
  ink: '#0B0910', ink2: '#16111f', wall: '#1a1426', wall2: '#0f0b17',
  red: '#7A0F1C', red2: '#B3132A', red3: '#5a0a14',
  bone: '#EFE6D8', bone2: '#d9cdbb', bone3: '#b9ab97',
  gold: '#F2C35A', gold2: '#ffdf8f', violet: '#5B3A8A', tear: '#cfe6ff',
};
export const FAM = 'MaShanZheng';

// ---------------------------------------------------------------- 镜头 / 视差
export interface Cam { x: number; y: number; z: number; rot: number }
export const CAM0: Cam = { x: 0, y: 0, z: 1, rot: 0 };
/** depth：1 = 人偶那一层；>1 越远动得越少；<1 越近动得越多。 */
export function layer(c: C2, cam: Cam, depth: number, fn: () => void) {
  const k = 1 / depth, zz = 1 + (cam.z - 1) * k;
  c.save();
  c.translate(W / 2, H / 2);
  c.rotate(cam.rot * k);
  c.scale(zz, zz);
  c.translate(-W / 2 - cam.x * k, -H / 2 - cam.y * k);
  fn();
  c.restore();
}

// ---------------------------------------------------------------- 舞台
export function backdrop(c: C2, t: number, tint = 1) {
  const g = c.createLinearGradient(0, -200, 0, 900);
  g.addColorStop(0, PAL.wall2); g.addColorStop(0.55, PAL.wall); g.addColorStop(1, '#120d1b');
  c.fillStyle = g; c.fillRect(-600, -400, W + 1200, 1300);
  // 纸纤维：竖的细纹
  c.save(); c.globalAlpha = 0.06 * tint;
  for (let i = 0; i < 90; i++) {
    const x = -500 + ((i * 97.3) % (W + 1000)), a = 0.4 + 0.6 * hash(i, 3);
    c.strokeStyle = hash(i, 7) > 0.5 ? '#3a2f4d' : '#07050b'; c.lineWidth = 1 + 2 * a;
    c.beginPath(); c.moveTo(x, -400); c.bezierCurveTo(x + 20 * noise1(i), 200, x - 20 * noise1(i + 5), 500, x + 10, 900); c.stroke();
  }
  c.restore();
  // 背幕上一圈暗金花纹（拱）
  c.save(); c.strokeStyle = 'rgba(242,195,90,0.10)'; c.lineWidth = 3;
  c.beginPath(); c.ellipse(W / 2, 760, 700, 640, 0, Math.PI, TAU); c.stroke();
  c.beginPath(); c.ellipse(W / 2, 760, 660, 600, 0, Math.PI, TAU); c.stroke();
  c.restore();
}

/** 地板：透视的木板，消失点在 (960, 260)。 */
export function floor(c: C2, y0 = 770) {
  const g = c.createLinearGradient(0, y0, 0, H + 200);
  g.addColorStop(0, '#1c1420'); g.addColorStop(1, '#070508');
  c.fillStyle = g; c.fillRect(-600, y0, W + 1200, H - y0 + 400);
  const vx = W / 2, vy = 260;
  c.save(); c.strokeStyle = 'rgba(0,0,0,0.55)'; c.lineWidth = 2;
  for (let i = -14; i <= 14; i++) {
    const xb = W / 2 + i * 150;
    const k = (y0 - vy) / (H + 300 - vy);
    c.beginPath(); c.moveTo(vx + (xb - vx) * k, y0); c.lineTo(xb, H + 300); c.stroke();
  }
  for (let j = 0; j < 7; j++) {
    const y = y0 + Math.pow(j / 6, 1.8) * (H + 200 - y0);
    c.beginPath(); c.moveTo(-600, y); c.lineTo(W + 600, y); c.stroke();
  }
  // 台口边缘一条亮线
  c.strokeStyle = 'rgba(242,195,90,0.25)'; c.lineWidth = 3;
  c.beginPath(); c.moveTo(-600, y0); c.lineTo(W + 600, y0); c.stroke();
  c.restore();
}

/** 大幕：open 0（合上）→ 1（拉到两边）；上面一排垂幔 + 金流苏。 */
export function curtains(c: C2, t: number, open = 1, sway = 0) {
  const half = W / 2 + 120;
  for (const side of [-1, 1]) {
    const inner = side < 0 ? lerp(W / 2, 230, open) : lerp(W / 2, W - 230, open);
    const outer = side < 0 ? -320 : W + 320;
    const n = 9;
    for (let i = 0; i < n; i++) {
      const u0 = i / n, u1 = (i + 1) / n;
      const x0 = lerp(outer, inner, u0), x1 = lerp(outer, inner, u1);
      const wob = Math.sin(t * 0.9 + i * 1.7) * 6 * (0.3 + sway);
      const g = c.createLinearGradient(x0, 0, x1, 0);
      g.addColorStop(0, PAL.red3); g.addColorStop(0.45, PAL.red2); g.addColorStop(0.6, PAL.red); g.addColorStop(1, PAL.red3);
      c.fillStyle = g;
      c.beginPath();
      c.moveTo(x0 + wob, -300);
      c.lineTo(x1 + wob, -300);
      c.quadraticCurveTo(x1 + wob * 2 + side * 8 * open, 500, x1 + (side < 0 ? 18 : -18) * open + wob, H + 200);
      c.lineTo(x0 + wob, H + 200);
      c.closePath(); c.fill();
    }
    // 收拢处的绑带
    if (open > 0.3) {
      const bx = side < 0 ? inner - 60 : inner + 60;
      c.fillStyle = PAL.gold; c.globalAlpha = 0.75;
      c.fillRect(bx - 50, 600, 100, 16);
      c.globalAlpha = 1;
    }
  }
  // 垂幔
  c.save();
  const vg = c.createLinearGradient(0, -60, 0, 170);
  vg.addColorStop(0, PAL.red3); vg.addColorStop(1, PAL.red);
  c.fillStyle = vg;
  c.beginPath(); c.moveTo(-400, -300); c.lineTo(W + 400, -300); c.lineTo(W + 400, 90);
  for (let i = 12; i >= 0; i--) { const x = -400 + i * ((W + 800) / 12); c.quadraticCurveTo(x + 90, 190, x, 90); }
  c.closePath(); c.fill();
  c.strokeStyle = 'rgba(242,195,90,0.55)'; c.lineWidth = 4;
  c.beginPath(); c.moveTo(W + 400, 92);
  for (let i = 12; i >= 0; i--) { const x = -400 + i * ((W + 800) / 12); c.quadraticCurveTo(x + 90, 192, x, 92); }
  c.stroke();
  c.restore();
}

// ---------------------------------------------------------------- 光
/** 聚光灯：从 (x0,y0) 打到地板 (x1,y1) 的光柱 + 地上的光斑。画在 glow 层（会叠加发光）。 */
export function spot(cg: C2, x0: number, y0: number, x1: number, y1: number, w: number, a = 1, col = '255,236,200') {
  if (a <= 0) return;
  const dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy), nx = -dy / L, ny = dx / L;
  const g = cg.createLinearGradient(x0, y0, x1, y1);
  g.addColorStop(0, `rgba(${col},${0.30 * a})`); g.addColorStop(0.55, `rgba(${col},${0.09 * a})`); g.addColorStop(1, `rgba(${col},${0.03 * a})`);
  cg.fillStyle = g;
  cg.beginPath();
  cg.moveTo(x0 + nx * 18, y0 + ny * 18); cg.lineTo(x0 - nx * 18, y0 - ny * 18);
  cg.lineTo(x1 - nx * w, y1 - ny * w); cg.lineTo(x1 + nx * w, y1 + ny * w);
  cg.closePath(); cg.fill();
  const pg = cg.createRadialGradient(x1, y1, 0, x1, y1, w * 1.15);
  pg.addColorStop(0, `rgba(${col},${0.42 * a})`); pg.addColorStop(1, `rgba(${col},0)`);
  cg.save(); cg.translate(x1, y1); cg.scale(1, 0.26); cg.translate(-x1, -y1);
  cg.fillStyle = pg; cg.beginPath(); cg.arc(x1, y1, w * 1.15, 0, TAU); cg.fill();
  cg.restore();
}

/** 浮尘：在光柱里慢慢漂的亮点（位置只由时间和编号决定）。 */
export function dust(cg: C2, t: number, x0: number, y0: number, x1: number, y1: number, w: number, n = 70, a = 1, seed = 1) {
  if (a <= 0) return;
  cg.save();
  for (let i = 0; i < n; i++) {
    const u = (hash(i, seed) + t * (0.012 + 0.02 * hash(i, seed + 1))) % 1;
    const v = (hash(i, seed + 2) - 0.5) * 2;
    const x = lerp(x0, x1, u) + v * lerp(18, w, u) + Math.sin(t * 0.6 + i) * 10;
    const y = lerp(y0, y1, u) + Math.cos(t * 0.5 + i * 1.3) * 8;
    const tw = 0.5 + 0.5 * Math.sin(t * (1.5 + hash(i, seed + 3) * 2) + i);
    const r = 1.2 + 2.2 * hash(i, seed + 4);
    cg.fillStyle = `rgba(255,240,210,${(0.25 + 0.6 * tw) * a})`;
    cg.beginPath(); cg.arc(x, y, r, 0, TAU); cg.fill();
  }
  cg.restore();
}

/** 星尘粒子：从一点往外涌、带一点旋，紫金白三色。 */
export function stardust(cg: C2, t: number, cx: number, cy: number, spread: number, n: number, a = 1, seed = 9, dir = -Math.PI / 2) {
  if (a <= 0) return;
  cg.save();
  for (let i = 0; i < n; i++) {
    const life = 2.2 + 1.6 * hash(i, seed);
    const ph = ((t + hash(i, seed + 1) * life) % life) / life;
    const ang = dir + (hash(i, seed + 2) - 0.5) * 2.6 + ph * 0.8 * (hash(i, seed + 5) - 0.5);
    const r = spread * Math.pow(ph, 0.7) * (0.4 + hash(i, seed + 3));
    const x = cx + Math.cos(ang) * r, y = cy + Math.sin(ang) * r * 0.8;
    const fade = Math.sin(Math.PI * ph);
    const k = hash(i, seed + 4);
    const col = k < 0.45 ? '255,226,150' : k < 0.75 ? '205,180,255' : '255,255,255';
    const s = (1.5 + 3.5 * hash(i, seed + 6)) * (1 - 0.5 * ph);
    cg.fillStyle = `rgba(${col},${0.95 * fade * a})`;
    if (hash(i, seed + 7) > 0.85) { star4(cg, x, y, s * 2.4); }
    else { cg.beginPath(); cg.arc(x, y, s, 0, TAU); cg.fill(); }
  }
  cg.restore();
}
export function star4(c: C2, x: number, y: number, r: number) {
  c.beginPath();
  c.moveTo(x, y - r); c.quadraticCurveTo(x, y, x + r, y); c.quadraticCurveTo(x, y, x, y + r);
  c.quadraticCurveTo(x, y, x - r, y); c.quadraticCurveTo(x, y, x, y - r);
  c.fill();
}

// ---------------------------------------------------------------- 裂缝
export interface Crack { pts: { x: number; y: number }[][]; len: number[] }
/** 一道带分叉的裂缝（seed 定形状）：从 (x,y) 往 ang 方向走 L 像素。 */
export function makeCrack(x: number, y: number, ang: number, L: number, seed: number, branches = 3): Crack {
  const pts: { x: number; y: number }[][] = [];
  const walk = (x0: number, y0: number, a0: number, len: number, s: number) => {
    const p = [{ x: x0, y: y0 }];
    const steps = Math.max(4, Math.round(len / 14));
    let a = a0, xx = x0, yy = y0;
    for (let i = 1; i <= steps; i++) {
      a += (hash(i, s) - 0.5) * 0.9;
      a = lerp(a, a0, 0.25);
      xx += Math.cos(a) * len / steps; yy += Math.sin(a) * len / steps;
      p.push({ x: xx, y: yy });
    }
    return p;
  };
  const main = walk(x, y, ang, L, seed);
  pts.push(main);
  for (let b = 0; b < branches; b++) {
    const at = Math.floor((0.25 + 0.5 * hash(b, seed + 11)) * (main.length - 1));
    const q = main[at]!;
    const da = (hash(b, seed + 12) > 0.5 ? 1 : -1) * (0.5 + 0.6 * hash(b, seed + 13));
    pts.push(walk(q.x, q.y, ang + da, L * (0.25 + 0.3 * hash(b, seed + 14)), seed + 20 + b));
  }
  const len = pts.map((p) => p.reduce((s, q, i) => (i ? s + Math.hypot(q.x - p[i - 1]!.x, q.y - p[i - 1]!.y) : 0), 0));
  return { pts, len };
}
/** 画裂缝到进度 p：base 层一道黑缝，glow 层一道金光（分叉晚一点长出来）。 */
export function drawCrack(c: C2, cg: C2 | null, k: Crack, p: number, w = 3, glow = 1, gold = PAL.gold) {
  if (p <= 0) return;
  k.pts.forEach((path, bi) => {
    const pp = bi === 0 ? clamp(p * 1.15) : clamp((p - 0.35) / 0.65);
    if (pp <= 0) return;
    const want = k.len[bi]! * pp;
    const seg: { x: number; y: number }[] = [path[0]!];
    let acc = 0;
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1]!, b = path[i]!, d = Math.hypot(b.x - a.x, b.y - a.y);
      if (acc + d >= want) { const u = (want - acc) / d; seg.push({ x: lerp(a.x, b.x, u), y: lerp(a.y, b.y, u) }); break; }
      seg.push(b); acc += d;
    }
    const ww = bi === 0 ? w : w * 0.6;
    const stroke = (cc: C2, col: string, lw: number) => {
      cc.strokeStyle = col; cc.lineWidth = lw; cc.lineJoin = 'round'; cc.lineCap = 'round';
      cc.beginPath(); seg.forEach((q, i) => (i ? cc.lineTo(q.x, q.y) : cc.moveTo(q.x, q.y))); cc.stroke();
    };
    stroke(c, '#050307', ww + 1.5);
    stroke(c, gold, ww * 0.45);
    if (cg && glow > 0) { cg.globalAlpha = glow; stroke(cg, gold, ww * 2.6); stroke(cg, '#fff3c8', ww * 0.9); cg.globalAlpha = 1; }
  });
}

// 提线瓷人偶在 doll.ts（10-04 第二版）

// ---------------------------------------------------------------- 歌词
/** 这句唱到第几个字（小数）：words 和字一一对应时按每个字的时间。 */
export function sungK(l: Line, t: number, i: number) {
  const w = l.words.length === [...l.text].length ? l.words[i] : null;
  return w ? clamp((t - w.start) / 0.12) : clamp(Lyrics.lineCharProgress(l, t) - i);
}
const chars = (l: Line) => [...l.text].filter((ch) => ch.trim());

/** 挂签：每个字一张小纸签挂在一根横线上，轻轻晃；唱到的字变金发光。 */
export function lyricTags(c: C2, cg: C2, l: Line, t: number, x: number, y: number, size = 64, gap = 1.25, a = 1) {
  const cs = chars(l), n = cs.length, step = size * gap, x0 = x - (n - 1) * step / 2;
  c.save(); c.globalAlpha = a;
  c.strokeStyle = 'rgba(242,195,90,0.7)'; c.lineWidth = 1.5;
  c.beginPath(); c.moveTo(x0 - step, y - size * 1.2); c.quadraticCurveTo(x, y - size * 0.95, x0 + n * step, y - size * 1.2); c.stroke();
  cs.forEach((ch, i) => {
    const k = sungK(l, t, i);
    const sw = Math.sin(t * 1.7 + i * 0.9) * 0.06 + (k > 0 && k < 1 ? Math.sin(k * Math.PI) * 0.18 : 0);
    const cx = x0 + i * step, top = y - size * 1.08 + Math.sin(i / Math.max(1, n - 1) * Math.PI) * size * 0.12;
    c.save(); c.translate(cx, top); c.rotate(sw);
    c.strokeStyle = 'rgba(242,195,90,0.7)'; c.beginPath(); c.moveTo(0, 0); c.lineTo(0, size * 0.25); c.stroke();
    c.fillStyle = k > 0 ? '#efe2c4' : 'rgba(239,230,216,0.28)';
    c.fillRect(-size * 0.5, size * 0.25, size, size * 1.15);
    c.fillStyle = k > 0 ? PAL.red3 : 'rgba(20,14,24,0.55)';
    c.font = font(FAM, size * 0.86); c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText(ch, 0, size * 0.84);
    c.restore();
    if (k > 0) {
      cg.save(); cg.globalAlpha = 0.35 * a * (1 - 0.6 * clamp(k)); cg.translate(cx, top); cg.rotate(sw);
      cg.fillStyle = PAL.gold2; cg.fillRect(-size * 0.55, size * 0.2, size * 1.1, size * 1.25); cg.restore();
    }
  });
  c.restore();
}

/** 投影 / 刻字：一行毛笔字，唱到的字骨白→金并发光；可以带透视（floorK > 0：越往后越小）。 */
export function lyricLine(c: C2, cg: C2, l: Line, t: number, x: number, y: number, size = 76, a = 1, opt: { rot?: number; floorK?: number; col?: string; dim?: string; glow?: number } = {}) {
  const cs = chars(l), n = cs.length;
  if (!n) return;
  c.save(); c.globalAlpha = a; c.font = font(FAM, size);
  const ws = cs.map((ch) => c.measureText(ch).width * 1.02);
  const tot = ws.reduce((s, w) => s + w, 0);
  let xx = x - tot / 2;
  cs.forEach((ch, i) => {
    const k = sungK(l, t, i);
    const cx = xx + ws[i]! / 2; xx += ws[i]!;
    const pop = k > 0 && k < 1 ? 1 + 0.25 * Math.sin(k * Math.PI) : 1;
    c.save(); c.translate(cx, y); if (opt.rot) c.rotate(opt.rot); c.scale(pop, pop);
    c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillStyle = 'rgba(0,0,0,0.55)'; c.fillText(ch, 3, 4);
    c.fillStyle = k > 0 ? (opt.col ?? PAL.gold2) : (opt.dim ?? 'rgba(239,230,216,0.45)');
    c.fillText(ch, 0, 0);
    c.restore();
    if (k > 0 && (opt.glow ?? 1) > 0) {
      cg.save(); cg.globalAlpha = a * (opt.glow ?? 1) * (0.55 + 0.45 * (1 - clamp(k))); cg.font = font(FAM, size * pop);
      cg.translate(cx, y); if (opt.rot) cg.rotate(opt.rot);
      cg.textAlign = 'center'; cg.textBaseline = 'middle'; cg.fillStyle = PAL.gold; cg.fillText(ch, 0, 0); cg.restore();
    }
  });
  c.restore();
}

/** 书写：羽毛笔一个字一个字写出来（每个字从左往右露出来），返回笔尖位置。 */
export function lyricWrite(c: C2, cg: C2, l: Line, t: number, x: number, y: number, size = 70, a = 1, col = '#e8dcc6') {
  const cs = chars(l);
  c.save(); c.globalAlpha = a; c.font = font(FAM, size);
  const ws = cs.map((ch) => c.measureText(ch).width * 1.04);
  const tot = ws.reduce((s, w) => s + w, 0);
  let xx = x - tot / 2, tip: Pt | null = null, last: Pt | null = null;
  cs.forEach((ch, i) => {
    const k = sungK(l, t, i);
    const w = ws[i]!;
    if (k > 0) last = { x: xx + w * clamp(k * 1.4), y: y + size * 0.1 };
    if (k > 0) {
      c.save(); c.beginPath(); c.rect(xx - 4, y - size, w * clamp(k * 1.4) + 8, size * 2); c.clip();
      c.textAlign = 'left'; c.textBaseline = 'middle'; c.fillStyle = col; c.fillText(ch, xx, y);
      c.restore();
      if (k < 1) tip = { x: xx + w * clamp(k * 1.4), y: y + size * 0.15 * Math.sin(k * 9) };
      if (k < 1) { cg.save(); cg.globalAlpha = 0.5 * a; cg.font = font(FAM, size); cg.textAlign = 'left'; cg.textBaseline = 'middle'; cg.fillStyle = PAL.gold; cg.fillText(ch, xx, y); cg.restore(); }
    }
    xx += w;
  });
  c.restore();
  return (tip ?? last) as Pt | null;       // 两个字之间：笔停在刚写完的地方
}

/** 印章：整句一下砸下来（定格那一刻用）。 */
export function lyricStamp(c: C2, cg: C2, l: Line, t: number, x: number, y: number, size = 150, a = 1) {
  const u = clamp((t - l.start) / 0.12);
  const sc = 1.5 - 0.5 * ease.outCubic(u);
  c.save(); c.globalAlpha = a * u; c.translate(x, y); c.scale(sc, sc);
  c.font = font(FAM, size); c.textAlign = 'center'; c.textBaseline = 'middle';
  c.fillStyle = 'rgba(0,0,0,0.6)'; c.fillText(chars(l).join(''), 6, 8);
  c.fillStyle = PAL.bone; c.fillText(chars(l).join(''), 0, 0);
  c.restore();
  cg.save(); cg.globalAlpha = a * u * 0.5; cg.translate(x, y); cg.scale(sc, sc); cg.font = font(FAM, size); cg.textAlign = 'center'; cg.textBaseline = 'middle';
  cg.fillStyle = PAL.gold; cg.fillText(chars(l).join(''), 0, 0); cg.restore();
}
