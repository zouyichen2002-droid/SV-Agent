// 《由》道具：线上的泪 / 胶片 / 五线谱、裂缝里的星尘、写字的手、墨线港口、纸城市、玫瑰、面具、毒药、孔雀羽、雨伞、合十的手、玻璃泡。
// 只由时间决定。base 画正常颜色，cg（glow 层）画发光的部分。
import { W, H } from '../../engine/gl';
import { clamp, ease, hash, lerp, TAU } from '../../engine/util';
import { PAL, star4, stardust, type C2 } from './kit';

type Pt = { x: number; y: number };

/** 在一根线（a→b）上滑下来的泪珠；speed 每秒走过线长的几分之几。 */
export function tearsOnLine(c: C2, cg: C2, a: Pt, b: Pt, t: number, n = 3, seed = 1, alpha = 1) {
  if (alpha <= 0) return;
  for (let i = 0; i < n; i++) {
    const u = (hash(i, seed) + t * (0.16 + 0.1 * hash(i, seed + 1))) % 1;
    const x = lerp(a.x, b.x, u), y = lerp(a.y, b.y, u), r = 4 + 3 * hash(i, seed + 2);
    c.save(); c.globalAlpha = alpha * Math.sin(Math.PI * u);
    c.fillStyle = 'rgba(190,220,255,0.85)';
    c.beginPath(); c.moveTo(x, y - r * 2.2); c.quadraticCurveTo(x + r, y - r * 0.2, x, y + r); c.quadraticCurveTo(x - r, y - r * 0.2, x, y - r * 2.2); c.fill();
    c.restore();
    cg.save(); cg.globalAlpha = 0.8 * alpha * Math.sin(Math.PI * u); cg.fillStyle = PAL.tear;
    cg.beginPath(); cg.arc(x, y - r * 0.3, r * 0.8, 0, TAU); cg.fill(); cg.restore();
  }
}

/** 线上挂的一格格胶片（回忆）。 */
export function filmOnLine(c: C2, cg: C2, a: Pt, b: Pt, t: number, n = 4, seed = 2, alpha = 1) {
  if (alpha <= 0) return;
  for (let i = 0; i < n; i++) {
    const u = (i + 0.5) / n + Math.sin(t * 0.4 + i) * 0.02;
    const x = lerp(a.x, b.x, u), y = lerp(a.y, b.y, u);
    const sw = Math.sin(t * 1.4 + i * 1.3 + seed) * 0.12;
    c.save(); c.globalAlpha = alpha; c.translate(x, y); c.rotate(sw);
    c.fillStyle = '#1a1512'; c.fillRect(-34, 6, 68, 52);
    c.fillStyle = 'rgba(239,230,216,0.85)';
    for (let k = 0; k < 4; k++) { c.fillRect(-30 + k * 17, 9, 8, 5); c.fillRect(-30 + k * 17, 51, 8, 5); }
    const g = c.createLinearGradient(-26, 16, 26, 48);
    g.addColorStop(0, `hsl(${30 + 20 * hash(i, seed)},45%,${55 + 15 * hash(i, seed + 3)}%)`); g.addColorStop(1, '#3a2a22');
    c.fillStyle = g; c.fillRect(-26, 16, 52, 32);
    c.strokeStyle = 'rgba(242,195,90,0.7)'; c.lineWidth = 1.2; c.beginPath(); c.moveTo(0, 6); c.lineTo(0, -6); c.stroke();
    c.restore();
    cg.save(); cg.globalAlpha = 0.25 * alpha; cg.translate(x, y); cg.rotate(sw); cg.fillStyle = '#ffd9a0'; cg.fillRect(-26, 16, 52, 32); cg.restore();
  }
}

/** 五线谱：五根平行的金线（a→b），音符顺着走。 */
export function staffLines(c: C2, cg: C2, a: Pt, b: Pt, t: number, alpha = 1, gap = 18) {
  if (alpha <= 0) return;
  const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy), nx = -dy / L, ny = dx / L;
  for (let k = -2; k <= 2; k++) {
    const o = k * gap;
    for (const cc of [c, cg]) {
      cc.save(); cc.globalAlpha = alpha * (cc === c ? 0.85 : 0.45); cc.strokeStyle = PAL.gold; cc.lineWidth = cc === c ? 1.6 : 3;
      cc.beginPath(); cc.moveTo(a.x + nx * o, a.y + ny * o); cc.lineTo(b.x + nx * o, b.y + ny * o); cc.stroke(); cc.restore();
    }
  }
  for (let i = 0; i < 7; i++) {
    const u = (hash(i, 31) + t * 0.08) % 1, lineK = Math.floor(hash(i, 32) * 9) - 4;
    const x = lerp(a.x, b.x, u) + nx * lineK * gap / 2, y = lerp(a.y, b.y, u) + ny * lineK * gap / 2;
    c.save(); c.globalAlpha = alpha * Math.sin(Math.PI * u); c.fillStyle = PAL.bone;
    c.beginPath(); c.ellipse(x, y, 9, 6.5, -0.4, 0, TAU); c.fill();
    c.fillRect(x + 7, y - 38, 2.5, 38); c.restore();
    cg.save(); cg.globalAlpha = 0.5 * alpha * Math.sin(Math.PI * u); cg.fillStyle = PAL.gold2; cg.beginPath(); cg.arc(x, y, 9, 0, TAU); cg.fill(); cg.restore();
  }
}

/** 背幕沿一道竖缝撕开，后面是星尘的图在光里；open 0..1。cover：图铺满开口的外接框。 */
export function revealArt(c: C2, cg: C2, img: HTMLImageElement | null, cx: number, cy: number, w: number, h: number, open: number, t: number, seed = 5, zoomDrift = 0.04) {
  if (open <= 0) return;
  // 撕口：一道竖的、歪歪扭扭、左右不对称的口子（不是对称的椭圆）
  const n = 26, pts: Pt[] = [], back: Pt[] = [];
  const eo = ease.outCubic(open);
  for (let i = 0; i <= n; i++) {
    const v = i / n, y = cy - h / 2 + v * h;
    const prof = Math.pow(Math.sin(Math.PI * v), 0.45) * (0.75 + 0.25 * Math.sin(v * 7 + seed));
    const spine = Math.sin(v * 3.1 + seed) * w * 0.12 + (hash(i >> 1, seed + 9) - 0.5) * 40;   // 缝本身的走向
    const jagL = (hash(i, seed) - 0.5) * 70, jagR = (hash(i, seed + 1) - 0.5) * 70;
    const half = (w / 2) * prof * eo;
    pts.push({ x: cx + spine - half * (0.8 + 0.4 * hash(i, seed + 3)) + jagL * eo, y: y + (hash(i, seed + 5) - 0.5) * 18 });
    back.push({ x: cx + spine + half * (0.8 + 0.4 * hash(i, seed + 4)) + jagR * eo, y: y + (hash(i, seed + 6) - 0.5) * 18 });
  }
  const poly = [...pts, ...back.reverse()];
  c.save();
  c.beginPath(); poly.forEach((q, i) => (i ? c.lineTo(q.x, q.y) : c.moveTo(q.x, q.y))); c.closePath(); c.clip();
  if (img) {
    const s = Math.max(w / img.width, h / img.height) * (1.02 + zoomDrift * open);
    const iw = img.width * s, ih = img.height * s;
    c.drawImage(img, cx - iw / 2, cy - ih / 2 - 10 * open, iw, ih);
    // 光从缝里往外：中间亮、边上暗
    const g = c.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.65);
    g.addColorStop(0, 'rgba(255,240,210,0.08)'); g.addColorStop(1, 'rgba(10,6,16,0.45)');
    c.fillStyle = g; c.fillRect(cx - w, cy - h, w * 2, h * 2);
  } else { c.fillStyle = '#2b2046'; c.fillRect(cx - w, cy - h, w * 2, h * 2); }
  c.restore();
  // 撕开的纸边：base 一道骨白毛边，glow 一圈金光
  c.save(); c.strokeStyle = 'rgba(239,230,216,0.8)'; c.lineWidth = 3;
  c.beginPath(); poly.forEach((q, i) => (i ? c.lineTo(q.x, q.y) : c.moveTo(q.x, q.y))); c.closePath(); c.stroke(); c.restore();
  cg.save(); cg.strokeStyle = PAL.gold; cg.lineWidth = 10 * open; cg.globalAlpha = 0.9;
  cg.beginPath(); poly.forEach((q, i) => (i ? cg.lineTo(q.x, q.y) : cg.moveTo(q.x, q.y))); cg.closePath(); cg.stroke(); cg.restore();
  stardust(cg, t, cx, cy, Math.max(w, h) * 0.9, Math.round(160 * open), open, seed + 40, Math.PI);
  stardust(cg, t + 1.3, cx, cy, Math.max(w, h) * 0.9, Math.round(160 * open), open, seed + 80, 0);
}

/** 写字的手：一只大手（剪影 + 金边）拿着羽毛笔，笔尖在 (x,y)。 */
export function quillHand(c: C2, cg: C2, x: number, y: number, s = 1, a = 1, t = 0) {
  if (a <= 0) return;
  const OUTL = 'rgba(28,18,32,0.75)';
  c.save(); c.globalAlpha = a; c.translate(x, y); c.scale(s, s); c.rotate(0.62 + Math.sin(t * 7) * 0.03);
  // 袖子从右上方伸进来（深红、金边袖口）
  c.save(); c.translate(70, -150); c.rotate(-0.25);
  c.fillStyle = PAL.red3; c.fillRect(-46, -520, 92, 470);
  c.fillStyle = PAL.red; c.fillRect(-52, -70, 104, 46); c.strokeStyle = PAL.gold; c.lineWidth = 4; c.strokeRect(-52, -70, 104, 46);
  c.restore();
  // 羽毛笔：深紫羽片 + 金羽杆
  c.fillStyle = '#2b1a3f';
  c.beginPath(); c.moveTo(0, -58); c.bezierCurveTo(40, -140, 46, -260, 6, -372); c.bezierCurveTo(-30, -270, -34, -150, 0, -58); c.closePath(); c.fill();
  c.strokeStyle = 'rgba(190,160,255,0.35)'; c.lineWidth = 1.3;
  for (let i = 0; i < 16; i++) { const yy = -80 - i * 18; c.beginPath(); c.moveTo(1, yy); c.lineTo(26 - Math.abs(i - 8) * 1.2, yy - 16); c.moveTo(1, yy); c.lineTo(-22 + Math.abs(i - 8) * 1.2, yy - 14); c.stroke(); }
  c.strokeStyle = PAL.gold; c.lineWidth = 3; c.beginPath(); c.moveTo(0, -16); c.lineTo(4, -370); c.stroke();
  c.fillStyle = '#121014'; c.beginPath(); c.moveTo(0, 0); c.lineTo(-5, -22); c.lineTo(5, -22); c.closePath(); c.fill();
  // 手：瓷白、描边；拇指和食指捏住笔
  c.fillStyle = PAL.bone; c.strokeStyle = OUTL; c.lineWidth = 2.5;
  c.beginPath(); c.ellipse(38, -96, 44, 32, -0.35, 0, TAU); c.fill(); c.stroke();              // 手掌
  for (const [fx, fy, rot] of [[58, -64, 0.2], [66, -82, 0.1], [68, -102, 0]] as const) {     // 蜷起来的三根手指
    c.beginPath(); c.ellipse(fx, fy, 14, 10, rot, 0, TAU); c.fill(); c.stroke();
  }
  c.beginPath(); c.ellipse(10, -62, 9, 26, -0.15, 0, TAU); c.fill(); c.stroke();               // 食指顺着笔杆
  c.beginPath(); c.ellipse(-12, -90, 11, 24, 0.55, 0, TAU); c.fill(); c.stroke();              // 拇指
  c.fillStyle = 'rgba(214,120,130,0.25)'; c.beginPath(); c.ellipse(40, -100, 18, 10, -0.35, 0, TAU); c.fill();
  c.restore();
  cg.save(); cg.globalAlpha = 0.9 * a; cg.fillStyle = PAL.gold2; cg.beginPath(); cg.arc(x, y, 8 * s, 0, TAU); cg.fill(); cg.restore();
}

/** 墨线画：港口（海浪、码头、灯塔、纸船），p 0..1 一笔笔画出来。 */
export function inkHarbor(c: C2, cg: C2, x: number, y: number, p: number, t: number, a = 1) {
  if (p <= 0 || a <= 0) return;
  c.save(); c.globalAlpha = a; c.strokeStyle = '#e8dcc6'; c.lineWidth = 3; c.lineCap = 'round';
  const seg = (k: number, fn: () => void) => { if (p > k) { c.save(); c.globalAlpha = a * clamp((p - k) / 0.12); fn(); c.restore(); } };
  seg(0, () => { for (let r = 0; r < 3; r++) { c.beginPath(); for (let i = 0; i <= 40; i++) { const xx = x - 520 + i * 26, yy = y + r * 26 + Math.sin(i * 0.8 + t * 2 + r) * 7; i ? c.lineTo(xx, yy) : c.moveTo(xx, yy); } c.stroke(); } });
  seg(0.2, () => { c.beginPath(); c.moveTo(x - 520, y - 10); c.lineTo(x - 180, y - 10); c.lineTo(x - 180, y - 40); c.lineTo(x - 520, y - 40); c.stroke(); for (let i = 0; i < 6; i++) { c.beginPath(); c.moveTo(x - 500 + i * 60, y - 10); c.lineTo(x - 500 + i * 60, y + 40); c.stroke(); } });
  seg(0.4, () => { c.beginPath(); c.moveTo(x + 330, y - 20); c.lineTo(x + 350, y - 230); c.lineTo(x + 390, y - 230); c.lineTo(x + 410, y - 20); c.stroke(); c.strokeRect(x + 345, y - 270, 50, 40); });
  seg(0.55, () => { cg.save(); cg.globalAlpha = a * (0.6 + 0.4 * Math.sin(t * 3)); cg.fillStyle = PAL.gold2; cg.beginPath(); cg.arc(x + 370, y - 250, 22, 0, TAU); cg.fill(); cg.restore(); });
  for (let b = 0; b < 3; b++) seg(0.6 + b * 0.1, () => { const bx = x - 100 + b * 150 + Math.sin(t + b) * 12, by = y + 6 + Math.sin(t * 1.6 + b) * 5; c.beginPath(); c.moveTo(bx - 40, by - 8); c.lineTo(bx + 40, by - 8); c.lineTo(bx + 26, by + 10); c.lineTo(bx - 26, by + 10); c.closePath(); c.moveTo(bx, by - 8); c.lineTo(bx - 4, by - 48); c.lineTo(bx + 22, by - 14); c.stroke(); });
  c.restore();
}

/** 立体纸城市：一排房子从地板弹起来（p 0..1），窗户亮金光。 */
export function popCity(c: C2, cg: C2, x: number, y: number, p: number, t: number, a = 1, n = 11) {
  if (p <= 0 || a <= 0) return;
  for (let i = 0; i < n; i++) {
    const u = clamp((p - i * 0.05) / 0.4), e = ease.outBack(u);
    if (u <= 0) continue;
    const bw = 90 + 60 * hash(i, 41), bh = (180 + 260 * hash(i, 42)) * e;
    const bx = x - (n * 120) / 2 + i * 120 + (hash(i, 43) - 0.5) * 30;
    c.save(); c.globalAlpha = a;
    c.fillStyle = i % 2 ? '#2a2033' : '#211a2a'; c.fillRect(bx, y - bh, bw, bh);
    c.fillStyle = '#16111f';
    if (hash(i, 44) > 0.5) { c.beginPath(); c.moveTo(bx - 6, y - bh); c.lineTo(bx + bw / 2, y - bh - 60 * e); c.lineTo(bx + bw + 6, y - bh); c.fill(); }
    c.strokeStyle = 'rgba(242,195,90,0.4)'; c.lineWidth = 2; c.strokeRect(bx, y - bh, bw, bh);
    c.restore();
    for (let wy = 0; wy < Math.floor(bh / 46); wy++) for (let wx = 0; wx < 2; wx++) {
      if (hash(i * 13 + wy, wx + 7) < 0.45) continue;
      const on = 0.6 + 0.4 * Math.sin(t * 2 + i + wy);
      const xx = bx + 16 + wx * (bw - 48), yy = y - bh + 18 + wy * 46;
      c.fillStyle = 'rgba(255,214,140,0.85)'; c.fillRect(xx, yy, 16, 22);
      cg.save(); cg.globalAlpha = 0.6 * on * a; cg.fillStyle = PAL.gold2; cg.fillRect(xx - 2, yy - 2, 20, 26); cg.restore();
    }
  }
}

/** 一朵玫瑰（深红，螺旋花瓣），p 0..1 开放。 */
export function rose(c: C2, x: number, y: number, r: number, p: number, rot = 0) {
  if (p <= 0) return;
  const e = ease.outBack(clamp(p));
  c.save(); c.translate(x, y); c.rotate(rot); c.scale(e, e);
  for (let k = 0; k < 3; k++) {
    const rr = r * (1 - k * 0.28);
    c.fillStyle = k === 0 ? '#7A0F1C' : k === 1 ? '#9e1426' : '#c21b33';
    for (let i = 0; i < 5; i++) {
      const a = i * TAU / 5 + k * 0.6;
      c.beginPath(); c.ellipse(Math.cos(a) * rr * 0.45, Math.sin(a) * rr * 0.45, rr * 0.62, rr * 0.42, a, 0, TAU); c.fill();
    }
  }
  c.strokeStyle = 'rgba(40,0,8,0.6)'; c.lineWidth = 2;
  c.beginPath(); for (let i = 0; i < 40; i++) { const a = i * 0.45, rr = r * 0.05 + i * r * 0.012; i ? c.lineTo(Math.cos(a) * rr, Math.sin(a) * rr) : c.moveTo(Math.cos(a) * rr, Math.sin(a) * rr); } c.stroke();
  c.restore();
}

/** 戏剧面具（笑 / 哭），tear：嘴角撕裂 0..1。 */
export function mask(c: C2, cg: C2 | null, x: number, y: number, s: number, happy: boolean, rot = 0, tear = 0, col = PAL.bone) {
  c.save(); c.translate(x, y); c.rotate(rot); c.scale(s, s);
  c.fillStyle = col;
  c.beginPath(); c.moveTo(-60, -50); c.quadraticCurveTo(0, -80, 60, -50); c.quadraticCurveTo(70, 30, 0, 80); c.quadraticCurveTo(-70, 30, -60, -50); c.fill();
  c.fillStyle = '#0b0910';
  for (const ex of [-24, 24]) { c.beginPath(); c.ellipse(ex, -14, 15, happy ? 8 : 10, happy ? 0 : (ex < 0 ? 0.3 : -0.3), 0, TAU); c.fill(); }
  c.beginPath();
  if (happy) { c.moveTo(-32, 20); c.quadraticCurveTo(0, 56 + tear * 10, 32, 20); c.quadraticCurveTo(0, 38, -32, 20); }
  else { c.moveTo(-28, 44); c.quadraticCurveTo(0, 18, 28, 44); c.quadraticCurveTo(0, 30, -28, 44); }
  c.fill();
  if (tear > 0) {
    c.strokeStyle = '#0b0910'; c.lineWidth = 3;
    for (const side of [-1, 1]) { c.beginPath(); c.moveTo(side * 32, 20); c.lineTo(side * (32 + 26 * tear), 20 - 22 * tear); c.lineTo(side * (40 + 30 * tear), 6 - 36 * tear); c.stroke(); }
    if (cg) { cg.save(); cg.translate(x, y); cg.rotate(rot); cg.scale(s, s); cg.strokeStyle = PAL.red2; cg.lineWidth = 5; for (const side of [-1, 1]) { cg.beginPath(); cg.moveTo(side * 32, 20); cg.lineTo(side * (32 + 26 * tear), 20 - 22 * tear); cg.stroke(); } cg.restore(); }
  }
  c.restore();
}

/** 毒药瓶：紫黑液体发一点光。 */
export function poison(c: C2, cg: C2, x: number, y: number, s: number, tilt = 0, a = 1) {
  if (a <= 0) return;
  c.save(); c.globalAlpha = a; c.translate(x, y); c.rotate(tilt); c.scale(s, s);
  c.fillStyle = 'rgba(200,190,220,0.25)'; c.beginPath(); c.arc(0, 30, 46, 0, TAU); c.fill(); c.fillRect(-14, -40, 28, 50);
  c.fillStyle = '#3b1a52'; c.beginPath(); c.arc(0, 34, 40, 0.15, Math.PI - 0.15); c.fill();
  c.fillStyle = '#6b2b1a'; c.fillRect(-16, -54, 32, 16);
  c.fillStyle = PAL.bone; c.font = '28px serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('☠', 0, 22);
  c.restore();
  cg.save(); cg.globalAlpha = 0.55 * a; cg.translate(x, y); cg.rotate(tilt); cg.scale(s, s); cg.fillStyle = '#b06cff'; cg.beginPath(); cg.arc(0, 40, 30, 0, TAU); cg.fill(); cg.restore();
}

/** 孔雀羽扇：open 0..1 展开，groove：羽眼上一道发光暗槽。 */
export function peacockFan(c: C2, cg: C2, x: number, y: number, s: number, open: number, groove: number, t: number) {
  if (open <= 0) return;
  const n = 13, span = 2.4 * ease.outCubic(open);
  c.save(); c.translate(x, y); c.scale(s, s);
  for (let i = 0; i < n; i++) {
    const a = -Math.PI / 2 - span / 2 + span * (i / (n - 1)) + Math.sin(t * 1.2 + i) * 0.02;
    c.save(); c.rotate(a + Math.PI / 2);
    c.strokeStyle = '#2f5d3a'; c.lineWidth = 3; c.beginPath(); c.moveTo(0, 0); c.lineTo(0, -300); c.stroke();
    const g = c.createRadialGradient(0, -260, 4, 0, -260, 60);
    g.addColorStop(0, '#0b1a4a'); g.addColorStop(0.35, '#1d6b8a'); g.addColorStop(0.6, '#2f8a4a'); g.addColorStop(1, 'rgba(47,138,74,0)');
    c.fillStyle = g; c.beginPath(); c.ellipse(0, -250, 46, 80, 0, 0, TAU); c.fill();
    c.fillStyle = '#c9a43a'; c.beginPath(); c.ellipse(0, -262, 14, 20, 0, 0, TAU); c.fill();
    c.fillStyle = '#0a0f2a'; c.beginPath(); c.ellipse(0, -262, 7, 11, 0, 0, TAU); c.fill();
    if (i === 6 && groove > 0) { cg.save(); cg.translate(x, y); cg.scale(s, s); cg.rotate(a + Math.PI / 2); cg.strokeStyle = PAL.gold; cg.lineWidth = 6; cg.globalAlpha = groove; cg.beginPath(); cg.moveTo(0, -300); cg.lineTo(0, -300 + 120 * groove); cg.stroke(); cg.restore(); }
    c.restore();
  }
  c.restore();
}

/** 雨伞：open 0..1 撑开，伞沿一道暗槽发光。 */
export function umbrella(c: C2, cg: C2, x: number, y: number, s: number, open: number, groove: number, rot = 0) {
  if (open <= 0) return;
  c.save(); c.translate(x, y); c.rotate(rot); c.scale(s, s);
  const sp = ease.outBack(open);
  c.strokeStyle = '#2a1f17'; c.lineWidth = 6; c.beginPath(); c.moveTo(0, -10); c.lineTo(0, 240); c.arc(-20, 240, 20, 0, Math.PI); c.stroke();
  c.fillStyle = '#120d18';
  c.beginPath(); c.moveTo(-220 * sp, 0);
  for (let i = 0; i < 6; i++) { const x0 = -220 * sp + i * (440 * sp / 6); c.quadraticCurveTo(x0 + 220 * sp / 6, -30, x0 + 440 * sp / 6, 0); }
  c.quadraticCurveTo(0, -260 * sp, -220 * sp, 0); c.fill();
  c.strokeStyle = 'rgba(242,195,90,0.5)'; c.lineWidth = 2;
  for (let i = 0; i <= 6; i++) { c.beginPath(); c.moveTo(0, -175 * sp); c.lineTo(-220 * sp + i * (440 * sp / 6), 0); c.stroke(); }
  if (groove > 0) { cg.save(); cg.translate(x, y); cg.rotate(rot); cg.scale(s, s); cg.strokeStyle = PAL.gold; cg.lineWidth = 7; cg.globalAlpha = groove; cg.beginPath(); cg.moveTo(-220 * sp, 0); cg.quadraticCurveTo(-200 * sp, -10, -220 * sp + 440 * sp * groove, 0); cg.stroke(); cg.restore(); }
  c.restore();
}

/** 合十的手（剪影），crack：裂开 0..1。 */
export function prayingHands(c: C2, cg: C2, x: number, y: number, s: number, crack: number, a = 1) {
  if (a <= 0) return;
  const split = ease.inCubic(clamp(crack)) * 60;
  for (const side of [-1, 1]) {
    c.save(); c.globalAlpha = a; c.translate(x + side * split, y + split * 0.6); c.rotate(side * split * 0.004); c.scale(s, s);
    c.fillStyle = PAL.bone2;
    c.beginPath(); c.moveTo(0, -160); c.quadraticCurveTo(side * 60, -120, side * 64, 20); c.quadraticCurveTo(side * 60, 90, side * 30, 140); c.lineTo(0, 140); c.closePath(); c.fill();
    c.strokeStyle = 'rgba(80,60,60,0.5)'; c.lineWidth = 2;
    for (let i = 0; i < 3; i++) { c.beginPath(); c.moveTo(side * 6, -130 + i * 30); c.quadraticCurveTo(side * 40, -100 + i * 30, side * 50, -40 + i * 30); c.stroke(); }
    c.restore();
  }
  if (crack > 0 && crack < 1) { cg.save(); cg.globalAlpha = a * (1 - crack); cg.fillStyle = PAL.gold2; cg.fillRect(x - 4, y - 160 * s, 8, 300 * s); cg.restore(); }
}

/** 一个玻璃泡，里面一个小舞台（晃）。 */
export function glassBubble(c: C2, cg: C2, x: number, y: number, r: number, t: number, a = 1, crack = 0) {
  if (a <= 0) return;
  c.save(); c.globalAlpha = a; c.translate(x + Math.sin(t * 1.3) * 8, y + Math.cos(t * 1.1) * 6);
  c.fillStyle = 'rgba(160,140,200,0.12)'; c.beginPath(); c.arc(0, 0, r, 0, TAU); c.fill();
  c.fillStyle = '#2a0a12'; c.fillRect(-r * 0.55, r * 0.2, r * 1.1, r * 0.3);
  c.fillStyle = PAL.red; c.fillRect(-r * 0.55, -r * 0.4, r * 0.18, r * 0.6); c.fillRect(r * 0.37, -r * 0.4, r * 0.18, r * 0.6);
  c.fillStyle = PAL.bone; c.beginPath(); c.arc(0, r * 0.02, r * 0.09, 0, TAU); c.fill(); c.fillRect(-r * 0.05, r * 0.1, r * 0.1, r * 0.14);
  c.strokeStyle = 'rgba(255,255,255,0.5)'; c.lineWidth = 3; c.beginPath(); c.arc(0, 0, r, 0, TAU); c.stroke();
  c.strokeStyle = 'rgba(255,255,255,0.6)'; c.beginPath(); c.arc(-r * 0.3, -r * 0.35, r * 0.35, Math.PI * 1.1, Math.PI * 1.45); c.stroke();
  c.restore();
  cg.save(); cg.globalAlpha = 0.3 * a; cg.strokeStyle = '#d8c8ff'; cg.lineWidth = 6; cg.beginPath(); cg.arc(x + Math.sin(t * 1.3) * 8, y + Math.cos(t * 1.1) * 6, r, 0, TAU); cg.stroke(); cg.restore();
}

/** 齿轮。 */
export function gear(c: C2, x: number, y: number, r: number, rot: number, teeth = 10, col = '#3a2f22') {
  c.save(); c.translate(x, y); c.rotate(rot); c.fillStyle = col;
  c.beginPath();
  for (let i = 0; i < teeth * 2; i++) { const a = i * Math.PI / teeth, rr = i % 2 ? r : r * 1.18; c.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); }
  c.closePath(); c.fill();
  c.fillStyle = '#0b0910'; c.beginPath(); c.arc(0, 0, r * 0.35, 0, TAU); c.fill();
  c.restore();
}

/** 剪纸狂欢者（剪影跳舞），chain：套上镣铐 0..1。 */
export function reveler(c: C2, cg: C2, x: number, y: number, s: number, t: number, i: number, chain: number) {
  const b = Math.sin(t * 5 + i) * (1 - chain);
  c.save(); c.translate(x, y); c.scale(s, s); c.fillStyle = '#07050b';
  c.beginPath(); c.arc(0, -150 + b * 8, 22, 0, TAU); c.fill();
  c.beginPath(); c.moveTo(-20, -126); c.lineTo(20, -126); c.lineTo(34, -40); c.lineTo(-34, -40); c.closePath(); c.fill();
  c.lineWidth = 12; c.lineCap = 'round'; c.strokeStyle = '#07050b';
  const arm = (side: number) => { const a = side * (1.6 + b * 0.6) * (1 - chain) + side * 0.25 * chain; c.beginPath(); c.moveTo(side * 16, -118); c.lineTo(side * 16 + Math.sin(a) * 60, -118 - Math.cos(a) * 60); c.stroke(); };
  arm(-1); arm(1);
  c.beginPath(); c.moveTo(-14, -40); c.lineTo(-22 - b * 10, 0); c.moveTo(14, -40); c.lineTo(22 + b * 10, 0); c.stroke();
  mask(c, null, 0, -152 + b * 8, 0.22, i % 2 === 0, 0, 0, PAL.bone);
  c.restore();
  if (chain > 0) {
    cg.save(); cg.globalAlpha = chain; cg.strokeStyle = PAL.gold; cg.lineWidth = 4;
    cg.beginPath(); cg.arc(x - 18 * s, y - 96 * s, 10 * s, 0, TAU); cg.arc(x + 18 * s, y - 96 * s, 10 * s, 0, TAU); cg.stroke();
    cg.beginPath(); cg.moveTo(x - 18 * s, y - 96 * s); cg.quadraticCurveTo(x, y - 60 * s, x + 18 * s, y - 96 * s); cg.stroke(); cg.restore();
  }
}

/** 一扇墨线画的门（p 画出来），knock：敲门时门轻震。 */
export function inkDoor(c: C2, cg: C2, x: number, y: number, p: number, knock: number, a = 1) {
  if (p <= 0 || a <= 0) return;
  c.save(); c.globalAlpha = a * clamp(p * 2); c.translate(x + knock * 6, y);
  c.strokeStyle = '#e8dcc6'; c.lineWidth = 4;
  c.beginPath(); c.moveTo(-90, 0); c.lineTo(-90, -230); c.quadraticCurveTo(0, -320, 90, -230); c.lineTo(90, 0); c.stroke();
  c.beginPath(); c.moveTo(-60, -20); c.lineTo(-60, -210); c.quadraticCurveTo(0, -280, 60, -210); c.lineTo(60, -20); c.stroke();
  c.fillStyle = PAL.gold; c.beginPath(); c.arc(45, -110, 7, 0, TAU); c.fill();
  c.restore();
  if (knock > 0) { cg.save(); cg.globalAlpha = knock * a; cg.strokeStyle = PAL.gold2; cg.lineWidth = 5; for (let r = 1; r <= 3; r++) { cg.beginPath(); cg.arc(x + 45, y - 110, 20 * r * (1 + (1 - knock)), -0.8, 0.8); cg.stroke(); } cg.restore(); }
}

/** 一张网撒下来（p 0..1）。 */
export function net(c: C2, cg: C2, cx: number, p: number, a = 1) {
  if (p <= 0) return;
  const top = -200 + ease.outCubic(p) * 500;
  c.save(); c.globalAlpha = a * 0.8; c.strokeStyle = '#d6c8b0'; c.lineWidth = 1.5;
  for (let i = -10; i <= 10; i++) {
    c.beginPath(); c.moveTo(cx + i * 60, top - 300); c.quadraticCurveTo(cx + i * 70, top + 200, cx + i * 88, top + 560); c.stroke();
  }
  for (let j = 0; j < 9; j++) {
    const y = top - 260 + j * 90;
    c.beginPath(); c.moveTo(cx - 700, y + 40); c.quadraticCurveTo(cx, y + 90 * Math.sin(p * 3), cx + 700, y + 40); c.stroke();
  }
  c.restore();
}
