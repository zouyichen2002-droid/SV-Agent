// 《由》的提线瓷人偶（SV-Agent 10-04 第二版）：娃娃比例、银白长发（发梢淡紫）、黑色哥特裙 + 深红衬裙、白蕾丝领、球形关节。
// 影子用同一套骨架画成剪影。只由时间决定。
import { clamp, ease, lerp, TAU } from '../../engine/util';
import { PAL, makeCrack, drawCrack, star4, type C2 } from './kit';

export interface Pose {
  x: number; y: number; s: number;      // 胯部位置、缩放
  lean: number; head: number;           // 身体、头的转角
  aL: [number, number]; aR: [number, number];   // 肩、肘（弧度，0 = 垂下；右手正数往右抬，左手负数往左抬）
  lL: [number, number]; lR: [number, number];   // 胯、膝
  hang: number;                         // 0 站着 / 1 软吊着（头低、手垂）
}
export const POSE0: Pose = { x: 960, y: 640, s: 1, lean: 0, head: 0, aL: [-0.12, -0.08], aR: [0.12, 0.08], lL: [0.04, 0], lR: [-0.04, 0], hang: 0 };
export function mixPose(a: Pose, b: Pose, u: number): Pose {
  const m = (x: number, y: number) => lerp(x, y, u);
  return {
    x: m(a.x, b.x), y: m(a.y, b.y), s: m(a.s, b.s), lean: m(a.lean, b.lean), head: m(a.head, b.head),
    aL: [m(a.aL[0], b.aL[0]), m(a.aL[1], b.aL[1])], aR: [m(a.aR[0], b.aR[0]), m(a.aR[1], b.aR[1])],
    lL: [m(a.lL[0], b.lL[0]), m(a.lL[1], b.lL[1])], lR: [m(a.lR[0], b.lR[0]), m(a.lR[1], b.lR[1])], hang: m(a.hang, b.hang),
  };
}

export interface DollLook {
  shadow?: boolean; shadowCol?: string;
  lips?: number; fire?: number; crack?: number; crackGold?: number; heart?: number; hollow?: number;
  horns?: number; crown?: number; stitches?: number; blink?: number;
}

type Pt = { x: number; y: number };
export function rig(p: Pose) {
  const s = p.s;
  const R = (ang: number, len: number, o: Pt): Pt => ({ x: o.x + Math.sin(ang) * len * s, y: o.y + Math.cos(ang) * len * s });
  const hip = { x: p.x, y: p.y };
  const neck = { x: hip.x + Math.sin(p.lean) * 122 * s, y: hip.y - Math.cos(p.lean) * 122 * s };
  const headAng = p.lean + p.head + p.hang * 0.55;
  const headC = { x: neck.x + Math.sin(headAng) * 70 * s, y: neck.y - Math.cos(headAng) * 70 * s };
  const sh = (side: number) => ({ x: neck.x + side * 36 * s * Math.cos(p.lean), y: neck.y + 12 * s + side * 36 * s * Math.sin(p.lean) });
  const shL = sh(-1), shR = sh(1);
  const arm = (o: Pt, a: [number, number]) => {
    const a1 = a[0] * (1 - p.hang * 0.75) + p.lean, a2 = a1 + a[1] * (1 - p.hang * 0.5);
    const el = R(a1, 62, o); const wr = R(a2, 58, el);
    return [el, wr, a2] as const;
  };
  const [elL, wrL, fL] = arm(shL, p.aL), [elR, wrR, fR] = arm(shR, p.aR);
  const hp = (side: number) => ({ x: hip.x + side * 20 * s, y: hip.y + 4 * s });
  const leg = (o: Pt, a: [number, number]) => { const kn = R(a[0], 88, o); const an = R(a[0] + a[1], 86, kn); return [kn, an] as const; };
  const hpL = hp(-1), hpR = hp(1);
  const [knL, anL] = leg(hpL, p.lL), [knR, anR] = leg(hpR, p.lR);
  return { hip, neck, headC, headAng, shL, shR, elL, wrL, elR, wrR, fL, fR, hpL, hpR, knL, anL, knR, anR, s };
}

/** 提线：控制十字架在 (bx, by)，线拉到头顶、两手腕、两膝。cut 0..1：从中间断开、下半截掉下去。 */
export function strings(c: C2, cg: C2 | null, p: Pose, bx: number, by: number, sway: number, a = 1, cut = 0, col = PAL.gold) {
  if (a <= 0) return;
  const r = rig(p);
  const barW = 150 * p.s, ang = sway * 0.25;
  const bar = (u: number) => ({ x: bx + Math.cos(ang) * barW * u, y: by + Math.sin(ang) * barW * u });
  const ends: [Pt, Pt][] = [
    [bar(0), { x: r.headC.x, y: r.headC.y - 60 * p.s }], [bar(-1), r.wrL], [bar(1), r.wrR], [bar(-0.42), r.knL], [bar(0.42), r.knR],
  ];
  c.save(); c.globalAlpha = a; c.strokeStyle = '#3a2a1c'; c.lineWidth = 8 * p.s; c.lineCap = 'round';
  const L0 = bar(-1), L1 = bar(1);
  c.beginPath(); c.moveTo(L0.x, L0.y); c.lineTo(L1.x, L1.y); c.moveTo(bx - Math.sin(ang) * 55, by - 55); c.lineTo(bx + Math.sin(ang) * 55, by + 55); c.stroke();
  c.strokeStyle = 'rgba(242,195,90,0.5)'; c.lineWidth = 2; c.beginPath(); c.moveTo(L0.x, L0.y - 3); c.lineTo(L1.x, L1.y - 3); c.stroke();
  c.restore();
  for (const [s0, s1] of ends) {
    const drop = cut > 0 ? ease.inQuad(cut) * 900 : 0;
    const mid = { x: lerp(s0.x, s1.x, 0.45), y: lerp(s0.y, s1.y, 0.45) };
    const draw = (cc: C2, w: number, alpha: number) => {
      cc.save(); cc.globalAlpha = alpha * a; cc.strokeStyle = col; cc.lineWidth = w; cc.beginPath();
      if (cut <= 0) { cc.moveTo(s0.x, s0.y); cc.lineTo(s1.x, s1.y); }
      else {
        cc.moveTo(s0.x, s0.y); cc.quadraticCurveTo(mid.x + 20 * cut, mid.y - 40 * cut, mid.x - 10, mid.y - 60 * cut);
        cc.moveTo(s1.x, s1.y + drop * 0.02); cc.quadraticCurveTo(mid.x, mid.y + drop * 0.5, mid.x + 30 * cut, mid.y + drop);
      }
      cc.stroke(); cc.restore();
    };
    draw(c, 1.3, 0.85);
    if (cg) draw(cg, 2.2, 0.35);
  }
}

const OUT = 'rgba(28,18,32,0.55)';

/** 画人偶（或影子）。 */
export function doll(c: C2, cg: C2 | null, p: Pose, look: DollLook = {}, t = 0) {
  const r = rig(p), s = p.s, sh = !!look.shadow;
  const SC = look.shadowCol ?? '#050307';
  const col = (normal: string) => (sh ? SC : normal);
  const hc = r.headC;
  const line = (lw = 2) => { if (!sh) { c.strokeStyle = OUT; c.lineWidth = lw; c.stroke(); } };

  // ---- 后面的长发（只到腰下一点，比肩宽一点）
  {
    const top = hc.y - 40 * s, bot = r.hip.y + 40 * s, wob = Math.sin(t * 0.8) * 5 * s;
    const g = sh ? null : c.createLinearGradient(0, top, 0, bot);
    if (g) { g.addColorStop(0, '#f1eef8'); g.addColorStop(0.7, '#dcd6ee'); g.addColorStop(1, '#b9a6e0'); }
    c.fillStyle = g ?? SC;
    c.beginPath();
    c.moveTo(hc.x - 50 * s, hc.y - 10 * s);
    c.bezierCurveTo(hc.x - 70 * s, hc.y + 80 * s, hc.x - 72 * s + wob, bot - 60 * s, hc.x - 64 * s + wob, bot);
    for (let i = 0; i <= 6; i++) { const x = hc.x - 64 * s + wob + i * (128 / 6) * s; c.quadraticCurveTo(x + 10 * s, bot + 16 * s, x + (128 / 6) * s, bot); }
    c.bezierCurveTo(hc.x + 72 * s + wob, bot - 60 * s, hc.x + 70 * s, hc.y + 80 * s, hc.x + 50 * s, hc.y - 10 * s);
    c.closePath(); c.fill(); line(1.5);
    if (!sh) {
      c.strokeStyle = 'rgba(130,112,170,0.35)'; c.lineWidth = 1.5;
      for (let i = -4; i <= 4; i++) { c.beginPath(); c.moveTo(hc.x + i * 11 * s, hc.y + 40 * s); c.quadraticCurveTo(hc.x + i * 14 * s + wob, (hc.y + bot) / 2, hc.x + i * 13 * s + wob, bot - 6 * s); c.stroke(); }
    }
  }

  const skin = (a: Pt, b: Pt, w0: number, w1: number, colr = PAL.bone) => {
    const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
    c.fillStyle = col(colr); c.beginPath();
    c.moveTo(a.x + nx * w0 * s, a.y + ny * w0 * s); c.lineTo(b.x + nx * w1 * s, b.y + ny * w1 * s);
    c.arc(b.x, b.y, w1 * s, Math.atan2(ny, nx), Math.atan2(ny, nx) + Math.PI);
    c.lineTo(a.x - nx * w0 * s, a.y - ny * w0 * s); c.closePath(); c.fill(); line(1.5);
  };
  const joint = (q: Pt, rr: number) => {
    if (sh) return;
    c.fillStyle = PAL.bone2; c.beginPath(); c.arc(q.x, q.y, rr * s, 0, TAU); c.fill(); line(1.2);
    c.fillStyle = 'rgba(255,255,255,0.7)'; c.beginPath(); c.arc(q.x - rr * 0.3 * s, q.y - rr * 0.3 * s, rr * 0.35 * s, 0, TAU); c.fill();
  };
  const sleeve = (o: Pt, el: Pt) => {
    c.fillStyle = col('#16101c');
    c.beginPath(); c.ellipse(lerp(o.x, el.x, 0.3), lerp(o.y, el.y, 0.3), 17 * s, 23 * s, Math.atan2(el.y - o.y, el.x - o.x) - Math.PI / 2, 0, TAU); c.fill(); line(1.5);
    if (!sh) { c.strokeStyle = 'rgba(242,195,90,0.6)'; c.lineWidth = 1.5; c.beginPath(); c.ellipse(lerp(o.x, el.x, 0.48), lerp(o.y, el.y, 0.48), 12 * s, 5 * s, Math.atan2(el.y - o.y, el.x - o.x) - Math.PI / 2, 0, TAU); c.stroke(); }
  };
  const hand = (wr: Pt, ang: number) => {
    c.save(); c.translate(wr.x, wr.y); c.rotate(-ang);
    c.fillStyle = col(PAL.bone); c.beginPath(); c.ellipse(0, 9 * s, 7.5 * s, 11 * s, 0, 0, TAU); c.fill(); line(1.2);
    c.restore();
  };
  const legDraw = (hp: Pt, kn: Pt, an: Pt) => {
    skin(hp, kn, 13, 10, '#f3ede4'); joint(kn, 9.5); skin(kn, an, 10, 7, '#f3ede4');
    c.fillStyle = col('#0e0a12'); c.beginPath(); c.ellipse(an.x + 3 * s, an.y + 6 * s, 14 * s, 8 * s, 0, 0, TAU); c.fill();
    if (!sh) { c.fillStyle = PAL.red2; c.fillRect(an.x - 6 * s, an.y - 3 * s, 12 * s, 3 * s); }
  };

  // ---- 后臂、两条腿（腿都在裙子底下：只露出裙摆下面那截）
  skin(r.shL, r.elL, 8.5, 7.5); skin(r.elL, r.wrL, 7.5, 6); hand(r.wrL, r.fL); sleeve(r.shL, r.elL); joint(r.elL, 7);
  legDraw(r.hpL, r.knL, r.anL);
  legDraw(r.hpR, r.knR, r.anR);

  // ---- 裙子：深红衬裙 + 黑色外裙（金边、褶）
  {
    const hip = r.hip, w = 86 * s, sw = Math.sin(t * 1.3) * 5 * s, len = 100 * s;
    const skirt = (wd: number, ln: number, fill: string, trim: boolean) => {
      c.fillStyle = fill; c.beginPath();
      c.moveTo(hip.x - 28 * s, hip.y - 16 * s);
      c.bezierCurveTo(hip.x - 50 * s, hip.y + 10 * s, hip.x - wd + sw, hip.y + ln * 0.6, hip.x - wd + sw, hip.y + ln);
      const n = 9;
      for (let i = 0; i < n; i++) { const x0 = hip.x - wd + sw + i * (2 * wd / n); c.quadraticCurveTo(x0 + wd / n, hip.y + ln + 13 * s, x0 + 2 * wd / n, hip.y + ln); }
      c.bezierCurveTo(hip.x + wd + sw, hip.y + ln * 0.6, hip.x + 50 * s, hip.y + 10 * s, hip.x + 28 * s, hip.y - 16 * s);
      c.closePath(); c.fill(); line(1.5);
      if (trim && !sh) {
        c.strokeStyle = 'rgba(242,195,90,0.85)'; c.lineWidth = 2.2; c.beginPath();
        for (let i = 0; i < n; i++) { const x0 = hip.x - wd + sw + i * (2 * wd / n); if (!i) c.moveTo(x0, hip.y + ln); c.quadraticCurveTo(x0 + wd / n, hip.y + ln + 13 * s, x0 + 2 * wd / n, hip.y + ln); }
        c.stroke();
        c.strokeStyle = 'rgba(0,0,0,0.45)'; c.lineWidth = 2;
        for (const k of [-0.55, -0.2, 0.2, 0.55]) { c.beginPath(); c.moveTo(hip.x + k * 40 * s, hip.y); c.lineTo(hip.x + k * wd + sw, hip.y + ln - 4 * s); c.stroke(); }
      }
    };
    skirt(w + 10 * s, len + 16 * s, col(PAL.red), false);
    skirt(w, len, col('#120d17'), true);
  }

  // ---- 上身：黑色胸衣 + 深红系带 + 白蕾丝领
  {
    const nk = r.neck, hp = r.hip;
    c.fillStyle = col('#120d17');
    c.beginPath(); c.moveTo(r.shL.x - 4 * s, r.shL.y - 2 * s); c.lineTo(r.shR.x + 4 * s, r.shR.y - 2 * s);
    c.lineTo(hp.x + 27 * s, hp.y - 14 * s); c.lineTo(hp.x - 27 * s, hp.y - 14 * s); c.closePath(); c.fill(); line(1.5);
    if (!sh) {
      c.strokeStyle = PAL.red2; c.lineWidth = 2;
      c.beginPath(); for (let i = 0; i < 6; i++) { const u = i / 5; const y = lerp(nk.y + 30 * s, hp.y - 20 * s, u), x = lerp(nk.x, hp.x, u); c.lineTo(x + (i % 2 ? 7 : -7) * s, y); } c.stroke();
      // 蕾丝领
      c.fillStyle = '#f4efe6';
      c.beginPath(); c.moveTo(nk.x - 30 * s, nk.y + 8 * s);
      for (let i = 0; i <= 6; i++) { const x = nk.x - 30 * s + i * 10 * s; c.quadraticCurveTo(x + 5 * s, nk.y + 26 * s, x + 10 * s, nk.y + 10 * s); }
      c.lineTo(nk.x + 30 * s, nk.y + 2 * s); c.lineTo(nk.x - 30 * s, nk.y + 2 * s); c.closePath(); c.fill(); line(1.2);
      c.fillStyle = PAL.red2;
      c.beginPath(); c.ellipse(nk.x - 9 * s, nk.y + 16 * s, 9 * s, 5 * s, 0.4, 0, TAU); c.ellipse(nk.x + 9 * s, nk.y + 16 * s, 9 * s, 5 * s, -0.4, 0, TAU); c.fill();
      c.beginPath(); c.arc(nk.x, nk.y + 16 * s, 3.5 * s, 0, TAU); c.fill();
    }
  }
  // 胸口的锁 / 光
  if (!sh && (look.heart ?? 0) > 0) {
    const hx = lerp(r.neck.x, r.hip.x, 0.42), hy = lerp(r.neck.y, r.hip.y, 0.42), hh = look.heart!;
    c.save(); c.globalAlpha = Math.min(1, hh * 1.5); c.fillStyle = PAL.gold; heart(c, hx, hy, 14 * s); c.restore();
    if (cg) { cg.save(); cg.globalAlpha = hh; cg.fillStyle = PAL.gold2; heart(cg, hx, hy, 20 * s); cg.restore(); }
  }

  // ---- 前臂
  skin(r.shR, r.elR, 8.5, 7.5); skin(r.elR, r.wrR, 7.5, 6); hand(r.wrR, r.fR); sleeve(r.shR, r.elR); joint(r.elR, 7);

  // 金线缝补
  if (!sh && (look.stitches ?? 0) > 0) {
    const st = look.stitches!;
    c.strokeStyle = PAL.gold; c.lineWidth = 2;
    const sew = (a: Pt, b: Pt) => { for (let i = 0; i < 5; i++) { const u = (i + 0.5) / 5; if (u > st) break; const x = lerp(a.x, b.x, u), y = lerp(a.y, b.y, u); c.beginPath(); c.moveTo(x - 6, y - 5); c.lineTo(x + 6, y + 5); c.moveTo(x + 6, y - 5); c.lineTo(x - 6, y + 5); c.stroke(); } };
    sew(r.elR, r.wrR); sew(r.knR, r.anR); sew(r.neck, r.hip);
    if (cg) { cg.save(); cg.globalAlpha = 0.6 * st; cg.strokeStyle = PAL.gold; cg.lineWidth = 3; cg.beginPath(); cg.moveTo(r.neck.x, r.neck.y + 20); cg.lineTo(r.hip.x, r.hip.y - 10); cg.stroke(); cg.restore(); }
  }

  // ---- 头
  c.save();
  c.translate(hc.x, hc.y); c.rotate(r.headAng);
  // 脖子
  c.fillStyle = col(PAL.bone2); c.fillRect(-9 * s, 40 * s, 18 * s, 34 * s);
  // 脸（瓷的光泽）
  {
    const g = sh ? null : c.createRadialGradient(-14 * s, -14 * s, 6 * s, 0, 0, 64 * s);
    if (g) { g.addColorStop(0, '#fffaf2'); g.addColorStop(0.7, PAL.bone); g.addColorStop(1, PAL.bone2); }
    c.fillStyle = g ?? SC;
    c.beginPath(); c.ellipse(0, 0, 50 * s, 58 * s, 0, 0, TAU); c.fill(); line(2);
  }
  if (!sh) {
    const bl = look.blink ?? 0, hol = look.hollow ?? 0, f = look.fire ?? 0;
    // 腮红
    c.fillStyle = 'rgba(222,120,140,0.28)';
    c.beginPath(); c.ellipse(-28 * s, 24 * s, 10 * s, 5.5 * s, 0, 0, TAU); c.fill(); c.beginPath(); c.ellipse(28 * s, 24 * s, 10 * s, 5.5 * s, 0, 0, TAU); c.fill();
    // 眼睛
    for (const ex of [-19, 19]) {
      c.save(); c.translate(ex * s, 6 * s); c.scale(1, Math.max(0.08, 1 - bl));
      c.fillStyle = '#fff'; c.beginPath(); c.ellipse(0, 0, 13 * s, 16 * s, 0, 0, TAU); c.fill();
      if (hol > 0.5) { c.fillStyle = '#000'; c.beginPath(); c.ellipse(0, 0, 12 * s, 15 * s, 0, 0, TAU); c.fill(); }
      else {
        const ig = c.createLinearGradient(0, -14 * s, 0, 14 * s);
        if (f > 0) { ig.addColorStop(0, '#ffcf6a'); ig.addColorStop(1, '#ff6a2a'); } else { ig.addColorStop(0, '#5a3d8a'); ig.addColorStop(1, '#c7a6f0'); }
        c.fillStyle = ig; c.beginPath(); c.ellipse(0, 1 * s, 10 * s, 13 * s, 0, 0, TAU); c.fill();
        c.fillStyle = f > 0 ? '#5a1500' : '#1b1028'; c.beginPath(); c.ellipse(0, 2 * s, 4.5 * s, 6.5 * s, 0, 0, TAU); c.fill();
        c.fillStyle = '#fff'; c.beginPath(); c.arc(-4 * s, -5 * s, 3.2 * s, 0, TAU); c.fill(); c.beginPath(); c.arc(4 * s, 6 * s, 1.6 * s, 0, TAU); c.fill();
      }
      c.strokeStyle = '#1a1020'; c.lineWidth = 2.6 * s; c.beginPath(); c.ellipse(0, 0, 13 * s, 16 * s, 0, Math.PI * 1.08, Math.PI * 1.92); c.stroke();
      c.restore();
      // 睫毛
      c.strokeStyle = '#1a1020'; c.lineWidth = 2 * s;
      c.beginPath(); c.moveTo((ex + (ex < 0 ? -12 : 12)) * s, -4 * s); c.lineTo((ex + (ex < 0 ? -17 : 17)) * s, -9 * s); c.stroke();
      if (cg && f > 0 && hol < 0.5) {
        cg.save(); cg.translate(hc.x, hc.y); cg.rotate(r.headAng);
        cg.fillStyle = `rgba(255,170,70,${0.9 * f})`; cg.beginPath(); cg.ellipse(ex * s, 7 * s, 8 * s, 11 * s, 0, 0, TAU); cg.fill();
        for (let k = 0; k < 3; k++) { const fl = 12 + 9 * Math.sin(t * 9 + k * 2 + ex); cg.beginPath(); cg.ellipse(ex * s + (k - 1) * 4 * s, (-8 - fl * 0.6) * s, 3 * s, fl * 0.5 * s, 0, 0, TAU); cg.fill(); }
        cg.restore();
      }
    }
    // 眉、鼻、嘴
    c.strokeStyle = 'rgba(120,100,140,0.7)'; c.lineWidth = 1.6 * s;
    c.beginPath(); c.moveTo(-27 * s, -18 * s); c.quadraticCurveTo(-19 * s, -22 * s, -11 * s, -19 * s); c.moveTo(27 * s, -18 * s); c.quadraticCurveTo(19 * s, -22 * s, 11 * s, -19 * s); c.stroke();
    c.fillStyle = 'rgba(200,150,150,0.6)'; c.beginPath(); c.arc(0, 18 * s, 1.5 * s, 0, TAU); c.fill();
    const lp = look.lips ?? 0;
    c.fillStyle = lp > 0 ? `rgb(${lerp(214, 179, lp)},${lerp(150, 19, lp)},${lerp(160, 42, lp)})` : '#d6a0a8';
    c.beginPath(); c.moveTo(-7 * s, 33 * s); c.quadraticCurveTo(0, (37 + 3 * lp) * s, 7 * s, 33 * s); c.quadraticCurveTo(0, 30 * s, -7 * s, 33 * s); c.fill();
  }
  // 刘海 + 两边垂下的鬓发
  {
    const hair = sh ? SC : '#f1eef8';
    c.fillStyle = hair;
    c.beginPath(); c.moveTo(-54 * s, 10 * s); c.quadraticCurveTo(-58 * s, -66 * s, 0, -66 * s); c.quadraticCurveTo(58 * s, -66 * s, 54 * s, 10 * s);
    const tips = [-54, -36, -18, 0, 18, 36, 54];
    for (let i = tips.length - 1; i > 0; i--) { const x1 = tips[i]! * s, x0 = tips[i - 1]! * s; c.quadraticCurveTo((x1 + x0) / 2, (i % 2 ? -26 : -14) * s, x0, (i % 2 ? -8 : -18) * s); }
    c.closePath(); c.fill(); line(1.5);
    for (const side of [-1, 1]) {
      const g = sh ? null : c.createLinearGradient(0, 0, 0, 130 * s);
      if (g) { g.addColorStop(0, '#f1eef8'); g.addColorStop(1, '#bba8e2'); }
      c.fillStyle = g ?? SC;
      c.beginPath(); c.moveTo(side * 44 * s, -30 * s);
      c.quadraticCurveTo(side * 62 * s, 50 * s, side * 50 * s + Math.sin(t + side) * 3 * s, 128 * s);
      c.lineTo(side * 38 * s, 120 * s); c.quadraticCurveTo(side * 46 * s, 40 * s, side * 30 * s, -20 * s); c.closePath(); c.fill(); line(1.2);
    }
    if (!sh) {
      // 蝴蝶结 + 小金星
      c.fillStyle = PAL.red2;
      c.beginPath(); c.ellipse(-46 * s, -52 * s, 15 * s, 9 * s, -0.6, 0, TAU); c.ellipse(-24 * s, -62 * s, 15 * s, 9 * s, 0.3, 0, TAU); c.fill();
      c.fillStyle = PAL.red; c.beginPath(); c.arc(-35 * s, -57 * s, 5 * s, 0, TAU); c.fill();
      c.fillStyle = PAL.gold; star4(c, 30 * s, -48 * s, 8 * s);
    }
  }
  // 皇冠
  if ((look.crown ?? 0) > 0) {
    const cy = -64 * s - (1 - ease.outCubic(look.crown!)) * 240 * s;
    c.fillStyle = sh ? SC : PAL.gold;
    c.beginPath(); c.moveTo(-36 * s, cy + 10 * s);
    for (let i = 0; i <= 4; i++) { const x = -36 * s + i * 18 * s; c.lineTo(x, cy - (i % 2 ? 6 : 30) * s); c.lineTo(x + 9 * s, cy); }
    c.lineTo(36 * s, cy + 10 * s); c.closePath(); c.fill(); line(1.5);
    if (!sh) { c.fillStyle = PAL.red2; c.beginPath(); c.arc(0, cy - 2 * s, 5 * s, 0, TAU); c.fill(); }
    if (cg && !sh) { cg.save(); cg.translate(hc.x, hc.y); cg.rotate(r.headAng); cg.strokeStyle = PAL.gold; cg.lineWidth = 4; cg.globalAlpha = 0.8; cg.beginPath(); cg.moveTo(-20 * s, cy + 2 * s); cg.lineTo(14 * s, cy - 14 * s); cg.stroke(); cg.restore(); }
  }
  // 影子的角
  if (sh && (look.horns ?? 0) > 0) {
    const hh = look.horns!;
    for (const side of [-1, 1]) {
      c.beginPath(); c.moveTo(side * 26 * s, -52 * s);
      c.quadraticCurveTo(side * 72 * s, -92 * s * hh, side * 52 * s, -156 * s * hh);
      c.quadraticCurveTo(side * 44 * s, -98 * s * hh, side * 12 * s, -60 * s); c.closePath(); c.fill();
    }
  }
  c.restore();
  // 脸上的裂缝（尾声金缮：变稳定的金线）
  if (!sh && (look.crack ?? 0) > 0) {
    const k = makeCrack(0, 0, 1.15, 96, 77, 2);
    c.save(); c.translate(hc.x, hc.y); c.rotate(r.headAng); c.scale(s, s); c.translate(-28, -50);
    if (cg) { cg.save(); cg.translate(hc.x, hc.y); cg.rotate(r.headAng); cg.scale(s, s); cg.translate(-28, -50); }
    drawCrack(c, cg, k, look.crack!, 2.4, 0.6 + 0.8 * (look.crackGold ?? 0));
    c.restore(); if (cg) cg.restore();
  }
}

export function heart(c: C2, x: number, y: number, r: number) {
  c.beginPath();
  c.moveTo(x, y + r * 0.9);
  c.bezierCurveTo(x - r * 1.6, y - r * 0.2, x - r * 0.6, y - r * 1.3, x, y - r * 0.45);
  c.bezierCurveTo(x + r * 0.6, y - r * 1.3, x + r * 1.6, y - r * 0.2, x, y + r * 0.9);
  c.fill();
}

export const _unused = clamp;
