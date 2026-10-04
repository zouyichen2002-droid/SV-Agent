// 开场 + 第 0–17 句：天上 → 当小孩上学（SV-Agent 10-03）。只画画面，不写歌词原文。
import { clamp, ease, lerp, smoothstep, TAU } from '../../engine/util';
import { COL, R, angel, flyPages, circle, cloud, ell, fadeIn, fs, heart, line, lyric, osc, pen, poly, pop, rr, sparkle, star, text, mix } from './kit';
import type { Panel, PD } from './types';

const groundHill = (c: CanvasRenderingContext2D, col = COL.mint) => {
  c.beginPath(); c.moveTo(-10, 860); c.quadraticCurveTo(960, 740, 1930, 860); c.lineTo(1930, 1090); c.lineTo(-10, 1090); c.closePath(); fs(c, col, 4);
};
const paperSheet = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, rot: number, mark = true) => {
  c.save(); c.translate(x, y); c.rotate(rot);
  rr(c, -w / 2, -h / 2, w, h, 6); fs(c, COL.white, 3);
  for (let i = 0; i < 4; i++) line(c, -w / 2 + 14, -h / 2 + 22 + i * 18, w / 2 - 14, -h / 2 + 22 + i * 18, 2, COL.gray3);
  if (mark) { c.beginPath(); c.arc(w / 2 - 22, -h / 2 + 20, 11, 0, TAU); pen(c, 3, COL.red); c.stroke(); }
  c.restore();
};
const bgClouds = (c: CanvasRenderingContext2D, t: number, n = 5, s = 0.8) => {
  for (let i = 0; i < n; i++) {
    const x = ((R(i, 3) * 2200 + t * (14 + R(i, 4) * 20)) % 2300) - 180;
    cloud(c, x, 120 + R(i, 5) * 360, s * (0.55 + R(i, 6) * 0.5), 'rgba(255,253,248,0.9)', 0);
  }
};

export const PANELS_A: Panel[] = [
  // 开场：云上一本合着的手账，标题写出来，镜头推进
  {
    bg: 'sky', text: null,
    draw: ({ c, t, lt }) => {
      bgClouds(c, t, 6, 1);
      cloud(c, 960, 860, 3.2, COL.white, 5);
      const s = 0.6 + 0.4 * pop(t, 0.05, 0.6);
      const zoom = 1 + 0.25 * ease.inCubic(clamp((lt - 1.4) / 0.9));
      c.save(); c.translate(960, 560); c.scale(s * zoom, s * zoom);
      rr(c, -330, -230, 660, 460, 26); fs(c, COL.pink, 6);
      rr(c, -300, -200, 600, 400, 18); fs(c, COL.pink2, 0, null);
      line(c, -330, -170, -300, -170, 5); line(c, -330, 170, -300, 170, 5);
      // 光环 + 标题
      c.save(); c.shadowColor = 'rgba(255,214,110,0.9)'; c.shadowBlur = 24;
      ell(c, 0, -90, 70, 18); pen(c, 10, COL.gold); c.stroke(); c.restore();
      const n = Math.floor(clamp((lt - 0.2) / 1.0) * 7);
      text(c, '《逃跑的天使》'.slice(0, n), 0, 40, 74, COL.ink);
      c.restore();
      sparkle(c, 960 + 90 * zoom, 470, 18 * pop(t, 0.5) * (0.6 + 0.4 * osc(t, 2)), COL.gold);
    },
  },
  // 0 云上的小天使，日历一页页飞走，她一点没变
  {
    bg: 'sky', tr: 'zoom',
    draw: ({ c, t, lt, k }) => {
      bgClouds(c, t, 5);
      cloud(c, 980, 820, 2.6, COL.white, 5);
      angel(c, 980, 760 - k * 10, 1.25, { t, mood: 'happy', halo: 1, flap: 0.6, armL: 0.4, armR: 2.3 });
      // 日历
      c.save(); c.translate(430, 470);
      rr(c, -110, -120, 220, 240, 14); fs(c, COL.white, 5);
      rr(c, -110, -120, 220, 60, 14); fs(c, COL.red, 5);
      text(c, String(1 + Math.floor(lt * 3) % 31), 0, 40, 96, COL.ink);
      c.restore();
      flyPages(c, 430, 470, lt, 3, 9);
    },
  },
  // 1 坐降落伞下来，落地戴上帽子遮住光环
  {
    bg: 'sky', tr: 'down',
    draw: ({ c, t, lt, dur }) => {
      bgClouds(c, t, 4);
      groundHill(c);
      const land = Math.min(dur * 0.62, 2.1);
      const y = lerp(260, 820, ease.outCubic(clamp(lt / land)));
      const sway = lt < land ? osc(t, 0.6) * 0.12 : 0;
      c.save(); c.translate(960, y); c.rotate(sway);
      if (lt < land + 0.3) {
        const a = 1 - clamp((lt - land) / 0.3);
        c.globalAlpha = a;
        c.beginPath(); c.moveTo(-230, -470); c.quadraticCurveTo(0, -700, 230, -470); c.quadraticCurveTo(0, -520, -230, -470); fs(c, COL.pink, 5);
        line(c, -225, -470, -40, -250, 3); line(c, 225, -470, 40, -250, 3); line(c, 0, -500, 0, -260, 3);
        c.globalAlpha = 1;
      }
      angel(c, 0, 0, 1.1, { t, mood: lt > land ? 'wink' : 'happy', halo: 1, wings: lt > land ? 0.35 : 0.8, armL: 2.6, armR: 2.6, hat: lt > land + 0.25, shadow: lt > land });
      c.restore();
    },
  },
  // 2 背上书包走向学校
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt, p, k }) => {
      c.save(); c.shadowColor = 'rgba(255,214,110,0.8)'; c.shadowBlur = 40; circle(c, 240, 190, 78); c.fillStyle = COL.gold2; c.fill(); c.restore();
      for (let i = 0; i < 8; i++) { const a = (i / 8) * TAU + t * 0.4; line(c, 240 + Math.cos(a) * 100, 190 + Math.sin(a) * 100, 240 + Math.cos(a) * 128, 190 + Math.sin(a) * 128, 6, COL.gold); }
      line(c, 0, 820, 1920, 820, 5);
      rr(c, 1030, 590, 40, 232, 10); fs(c, COL.wood, 5); cloud(c, 1050, 540, 1.0, COL.mint, 5);
      // 学校
      c.save(); c.translate(1420, 820);
      rr(c, -260, -420, 520, 420, 8); fs(c, COL.white, 5);
      poly(c, [-300, -420, 0, -600, 300, -420]); fs(c, COL.red, 5);
      circle(c, 0, -480, 46); fs(c, COL.white, 4);
      line(c, 0, -480, 0, -510, 4); line(c, 0, -480, 22 * Math.cos(t), -480 + 22 * Math.sin(t), 4);
      for (const wx of [-180, -60, 60, 180]) { rr(c, wx - 40, -360, 80, 90, 6); fs(c, COL.blue2, 4); }
      rr(c, -60, -170, 120, 170, 8); fs(c, COL.wood, 4);
      // 铃铛
      c.save(); c.translate(240, -440); c.rotate(Math.sin(t * 18) * 0.35 * k);
      c.beginPath(); c.moveTo(-26, 30); c.quadraticCurveTo(-26, -30, 0, -30); c.quadraticCurveTo(26, -30, 26, 30); c.closePath(); fs(c, COL.gold, 4);
      c.restore();
      c.restore();
      const x = lerp(260, 900, p);
      angel(c, x, 820, 1.05, { t, mood: 'happy', walk: lt, bag: true, halo: 1, wings: 0.6, armL: 0.3, armR: -0.2 });
    },
  },
  // 3 小剧场：看电视、跳绳、书上冒星星
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt, k }) => {
      const box = (i: number, x: number, draw: () => void) => {
        const s = pop(lt, i * 0.95, 0.4);
        if (s <= 0) return;
        c.save(); c.translate(x, 460); c.scale(s, s); c.rotate((i - 1) * 0.04);
        rr(c, -270, -300, 540, 600, 16); fs(c, COL.white, 6);
        c.save(); rr(c, -262, -292, 524, 584, 12); c.clip(); draw(); c.restore();
        c.restore();
      };
      box(0, 380, () => {
        rr(c, -170, -150, 340, 230, 14); fs(c, COL.ink2, 5);
        rr(c, -150, -132, 300, 192, 8); fs(c, COL.blue, 0, null);
        for (let i = 0; i < 3; i++) { c.beginPath(); c.moveTo(-150, -60 + i * 40); for (let x = -150; x <= 150; x += 10) c.lineTo(x, -60 + i * 40 + Math.sin(x * 0.05 + t * 4 + i) * 8); pen(c, 4, COL.white); c.stroke(); }
        angel(c, 0, 300, 0.6, { t, mood: 'calm', halo: 1, wings: 0.5 });
      });
      box(1, 960, () => {
        // 绳子两头在手上，一圈圈甩过头顶和脚下；甩到脚下的时候正好跳起来
        const ph = t * 1.04 * TAU, s = 0.75, a = 1.15;
        const jump = Math.max(0, -Math.cos(ph)) * 90;
        const ay = 250 - jump;
        const hx = (25 + Math.sin(a) * 54) * s, hy = ay + (-142 + Math.cos(a) * 54) * s;
        const top = ay - 330 * s, bot = 262;
        const cy = (top + bot) / 2 - Math.cos(ph) * (bot - top) / 2;
        const rope = () => { c.beginPath(); c.moveTo(-hx, hy); c.quadraticCurveTo(0, 2 * cy - hy, hx, hy); pen(c, 6, COL.red); c.stroke(); };
        if (Math.sin(ph) > 0) rope();
        ell(c, 0, 262, 60 * (1 - jump / 200), 10); c.fillStyle = 'rgba(58,51,64,0.12)'; c.fill();
        angel(c, 0, ay, s, { t, mood: 'laugh', halo: 1, wings: 0.6, armL: a, armR: a, shadow: false });
        if (Math.sin(ph) <= 0) rope();
      });
      box(2, 1540, () => {
        c.save(); c.translate(0, 120);
        poly(c, [-200, 0, 0, 30, 0, 130, -200, 100]); fs(c, COL.white, 5);
        poly(c, [200, 0, 0, 30, 0, 130, 200, 100]); fs(c, COL.white, 5);
        c.restore();
        for (let i = 0; i < 6; i++) {
          const u = (lt * 0.8 + i / 6) % 1;
          star(c, Math.sin(i * 2.1) * 140 * u, 100 - u * 380, 26 * (1 - u * 0.5)); fs(c, i % 2 ? COL.gold : COL.pink, 3);
        }
      });
      void k;
    },
  },
  // 4 试卷像雨一样落下，越堆越高
  {
    bg: 'gray', tr: 'up',
    draw: ({ c, t, lt, p }) => {
      const pile = 40 + p * 420;
      for (let i = 0; i < 26; i++) {
        const y = 1080 - (i / 26) * pile;
        if (i / 26 > p + 0.05) break;
        paperSheet(c, 960 + (R(i, 1) - 0.5) * 900, y, 170, 120, (R(i, 2) - 0.5) * 0.6);
      }
      for (let i = 0; i < 14; i++) {
        const u = ((lt * 0.9 + R(i, 7)) % 1);
        paperSheet(c, 160 + R(i, 8) * 1600 + Math.sin(u * 6 + i) * 60, -100 + u * (1080 - pile + 100), 150, 105, Math.sin(u * 5 + i) * 0.8);
      }
      angel(c, 960, 1080 - pile + 30, 1.0, { t, mood: 'shock', halo: 0.9, wings: 0.5, armL: 2.8, armR: 2.8 });
    },
  },
  // 5 作业堆成山，老师的手指指着
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt, k }) => {
      for (let i = 0; i < 12; i++) {
        const w = 360 - i * 18, y = 1000 - i * 46;
        rr(c, 1300 - w / 2 + (R(i, 3) - 0.5) * 30, y - 40, w, 44, 6); fs(c, [COL.blue, COL.pink, COL.mint, COL.gold][i % 4]!, 4);
      }
      angel(c, 620, 900, 1.05, { t, mood: 'tired', halo: 0.85, wings: 0.45, bag: true, armL: 0.1, armR: 0.1 });
      rr(c, 1236, 418, 128, 40, 6); fs(c, COL.white, 3); line(c, 1280, 424, 1320, 452, 6, COL.red); line(c, 1320, 424, 1280, 452, 6, COL.red);
      const bs = pop(lt, 0.5, 0.35);
      c.save(); c.translate(1640, 420); c.scale(bs, bs);
      ell(c, 0, 0, 110, 70); fs(c, COL.white, 5); poly(c, [-30, 56, -70, 110, 10, 66]); fs(c, COL.white, 0, null);
      text(c, '!!', 0, 0, 72, COL.red);
      c.restore();
      // 老师的手
      const tap = Math.sin(t * TAU * 2.08) * 18 * (0.5 + k);
      c.save(); c.translate(1500 - lt * 20, 160 + tap); c.rotate(0.55);
      rr(c, -420, -46, 380, 92, 30); fs(c, COL.suit, 5);
      rr(c, -60, -44, 120, 88, 30); fs(c, COL.skin, 5);
      rr(c, 40, -16, 120, 32, 16); fs(c, COL.skin, 5);
      c.restore();
    },
  },
  // 6 戴墨镜的坏孩子踩滑板晃过去
  {
    bg: 'pink', tr: 'pan',
    draw: ({ c, t, p }) => {
      line(c, 0, 850, 1920, 850, 5);
      const x = lerp(-150, 2050, p);
      c.save(); c.translate(x, 840 + Math.sin(t * 9) * 4);
      rr(c, -110, -16, 220, 24, 12); fs(c, COL.orange, 4);
      circle(c, -70, 20, 16); fs(c, COL.ink, 0, null); circle(c, 70, 20, 16); fs(c, COL.ink, 0, null);
      angel(c, 0, -14, 1.0, { t, mood: 'calm', halo: 0, wings: 0, armL: 1.6, armR: 1.4, lean: -0.12, shadow: false });
      rr(c, -52, -228, 104, 30, 10); fs(c, COL.ink, 3);
      c.restore();
      for (let i = 0; i < 4; i++) {
        const u = (t * 0.7 + i * 0.25) % 1;
        text(c, '♪', x - 120 - i * 40, 520 - u * 220, 56 * (1 - u * 0.4), COL.ink2);
      }
      angel(c, 300, 850, 0.7, { t, mood: 'blank', halo: 0.9, wings: 0.4, bag: true });
    },
  },
  // 7 从教室窗户溜出去
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt, p }) => {
      rr(c, 560, 180, 800, 600, 10); fs(c, COL.blue2, 8);
      cloud(c, 820, 400, 0.9, COL.white, 0); cloud(c, 1180, 300, 0.7, COL.white, 0);
      line(c, 960, 180, 960, 780, 8); line(c, 560, 480, 1360, 480, 8);
      rr(c, 520, 780, 880, 40, 8); fs(c, COL.wood, 6);
      const ax = lerp(760, 1500, ease.inOutCubic(clamp(p * 1.25)));
      const ay = 780 - Math.sin(clamp(p * 1.25) * Math.PI) * 120;
      angel(c, ax, ay, 0.95, { t, mood: 'wink', halo: 1, wings: 0.7, flap: 2, bag: true, lean: 0.25, armL: 2.4, armR: 1.0, shadow: false });
      void lt;
    },
  },
  // 8 巨大的压板往下压：一个顶着、一个鞠躬
  {
    bg: 'gray', tr: 'down',
    draw: ({ c, t, lt, k }) => {
      const press = 610 + Math.min(lt, 3) * 8 + k * 12;
      line(c, 0, 1000, 1920, 1000, 5);
      angel(c, 620, 1000, 1.25, { t, mood: 'tired', halo: 0.7, wings: 0.4, armL: Math.PI - 0.35, armR: Math.PI - 0.35 });
      angel(c, 1320, 1000, 1.25, { t, mood: 'tired', halo: 0.7, wings: 0.4, bow: 0.6 + 0.25 * Math.abs(Math.sin(t * Math.PI * 2.08 / 2)) });
      for (let i = 0; i < 3; i++) { const u = (t * 0.9 + i / 3) % 1; ell(c, 540 + i * 70, 560 - u * 60, 6, 10); c.fillStyle = `rgba(156,203,234,${1 - u})`; c.fill(); }
      rr(c, 160, press - 120, 1600, 120, 8); fs(c, COL.gray2, 6);
      for (let i = 0; i < 9; i++) line(c, 240 + i * 180, press - 100, 240 + i * 180, press - 20, 4, COL.ink2);
      rr(c, 900, -10, 120, press - 110, 0); fs(c, COL.gray, 6);
    },
  },
  // 9 名牌上的名字被擦掉，小天使慢慢透明
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt, p }) => {
      c.save(); c.translate(1340, 470); c.rotate(-0.06);
      rr(c, -260, -150, 520, 300, 18); fs(c, COL.white, 6);
      rr(c, -260, -150, 520, 80, 18); fs(c, COL.blue, 6);
      const w = 360 * (1 - clamp(lt / 3.2));
      if (w > 4) { c.beginPath(); c.moveTo(-180, 40); for (let x = 0; x < w; x += 12) c.lineTo(-180 + x, 40 + Math.sin(x * 0.12) * 18); pen(c, 7); c.stroke(); }
      const ex = -180 + w + 20;
      c.save(); c.translate(ex, 20 + Math.sin(t * 20) * 6); c.rotate(0.5);
      rr(c, -30, -70, 60, 120, 10); fs(c, COL.pink, 5); rr(c, -30, 30, 60, 30, 6); fs(c, COL.white, 5);
      c.restore();
      c.restore();
      angel(c, 620, 900, 1.25, { t, mood: 'calm', halo: 1, wings: 0.8, alpha: 1 - 0.85 * smoothstep(0.25, 0.95, p) });
      if (p > 0.6) { c.save(); c.globalAlpha = (p - 0.6) * 2; c.setLineDash([12, 12]); ell(c, 620, 900 - 352, 58, 16); pen(c, 5, COL.gold); c.stroke(); c.restore(); }
    },
  },
  // 10 头顶一朵雨云，眼泪喷泉
  {
    bg: 'gray', tr: 'pan',
    draw: ({ c, t, lt }) => {
      for (let i = 0; i < 40; i++) {
        const u = (lt * 1.3 + R(i, 2)) % 1;
        const x = 700 + R(i, 3) * 520, y = 330 + u * 600;
        line(c, x, y, x - 6, y + 28, 4, COL.blue);
      }
      cloud(c, 960, 280, 2.1, COL.gray, 5);
      angel(c, 960, 960, 1.3, { t, mood: 'cry', halo: 0.6, wings: 0.5 });
      for (const sd of [-1, 1]) {
        for (let i = 0; i < 10; i++) {
          const u = (lt * 1.6 + i / 10) % 1;
          const x = 960 + sd * (26 + u * 260), y = 960 - 1.3 * 200 - Math.sin(u * Math.PI) * 140 + u * 120;
          circle(c, x, y, 9 * (1 - u * 0.4)); fs(c, COL.blue, 0, null);
        }
      }
    },
  },
  // 11 梦的泡泡：月亮、星星、一行行小诗
  {
    bg: 'night', tr: 'up',
    draw: ({ c, t, lt }) => {
      for (let i = 0; i < 40; i++) sparkle(c, R(i, 1) * 1920, R(i, 2) * 700, 4 + R(i, 3) * 6 * (0.6 + 0.4 * osc(t, 0.5 + R(i, 4), R(i, 5))), COL.gold2);
      const s = pop(lt, 0.1, 0.6);
      c.save(); c.translate(1150, 420); c.scale(s, s);
      cloud(c, 0, 0, 3.4, COL.white, 6);
      c.beginPath(); c.arc(-150, -20, 70, 0, TAU); c.fillStyle = COL.gold2; c.fill();
      c.beginPath(); c.arc(-120, -40, 62, 0, TAU); c.fillStyle = COL.white; c.fill();
      for (let i = 0; i < 4; i++) {
        const len = 260 * clamp((lt - 0.4 - i * 0.5) / 0.6);
        if (len > 2) line(c, -40, -60 + i * 40, -40 + len, -60 + i * 40, 6, [COL.pink, COL.blue, COL.mint, COL.gold][i]!);
      }
      c.restore();
      for (let i = 0; i < 3; i++) { circle(c, 700 + i * 90, 760 - i * 90, 16 + i * 10); fs(c, COL.white, 4); }
      angel(c, 460, 960, 1.0, { t, mood: 'sleep', halo: 0.9, wings: 0.6, lean: -0.15, blink: false });
    },
  },
  // 12 夜里的床，数羊，zzz
  {
    bg: 'night', tr: 'pan',
    draw: ({ c, t, lt }) => {
      rr(c, 220, 700, 900, 160, 30); fs(c, COL.wood, 6);
      rr(c, 220, 500, 70, 360, 20); fs(c, COL.wood, 6);
      rr(c, 300, 560, 230, 110, 50); fs(c, COL.white, 5);
      angel(c, 492, 713, 0.62, { t, mood: 'sleep', halo: 0.8, wings: 0, blink: false, shadow: false, lean: -0.5 });
      c.beginPath(); c.moveTo(340, 652); c.quadraticCurveTo(700, 600 + Math.sin(t * 1.3) * 8, 1090, 640); c.lineTo(1090, 790); c.lineTo(340, 790); c.closePath(); fs(c, COL.pink2, 5);
      for (let i = 0; i < 4; i++) line(c, 470 + i * 150, 660 - i * 6, 470 + i * 150, 780, 3, 'rgba(244,166,183,0.9)');
      for (let i = 0; i < 3; i++) {
        const u = (lt * 0.6 + i / 3) % 1;
        text(c, 'Z', 520 + u * 160 + i * 20, 560 - u * 260, 40 + u * 40, `rgba(255,253,248,${1 - u})`);
      }
      line(c, 1300, 820, 1700, 820, 6, COL.wood); line(c, 1500, 820, 1500, 700, 8, COL.wood);
      const jump = (lt * 0.9) % 1;
      const sx = lerp(1200, 1800, jump), sy = 760 - Math.sin(jump * Math.PI) * 220;
      cloud(c, sx, sy, 0.75, COL.white, 4);
      circle(c, sx + 70, sy - 10, 26); fs(c, COL.ink2, 4);
    },
  },
  // 13 钟和日历乱转，前面的路分叉
  {
    bg: 'paper', tr: 'zoom',
    draw: ({ c, t, lt }) => {
      c.beginPath(); c.moveTo(960, 1100); c.lineTo(960, 760);
      c.moveTo(960, 760); c.quadraticCurveTo(700, 600, 320, 520);
      c.moveTo(960, 760); c.lineTo(960, 430);
      c.moveTo(960, 760); c.quadraticCurveTo(1220, 600, 1600, 520);
      pen(c, 40, COL.gray3); c.stroke();
      for (const [x, y] of [[320, 450], [960, 360], [1600, 450]]) text(c, '?', x!, y! + Math.sin(t * 3 + x!) * 10, 110, COL.ink2);
      c.save(); c.translate(400, 210);
      circle(c, 0, 0, 110); fs(c, COL.white, 6);
      line(c, 0, 0, Math.cos(lt * 9) * 80, Math.sin(lt * 9) * 80, 7); line(c, 0, 0, Math.cos(lt * 2) * 55, Math.sin(lt * 2) * 55, 9);
      c.restore();
      angel(c, 960, 960, 1.05, { t, mood: 'blank', halo: 0.75, wings: 0.4, bag: true });
    },
  },
  // 14 黑板写满公式，这句写在黑板上
  {
    bg: 'paper', tr: 'pan', text: null,
    draw: ({ c, t, lt, l }) => {
      rr(c, 120, 90, 1680, 760, 18); fs(c, COL.wood, 10);
      rr(c, 150, 120, 1620, 700, 8); fs(c, '#2F5A4C', 0, null);
      const n = Math.floor(clamp(lt / 3.6) * 60);
      for (let i = 0; i < n; i++) {
        const x = 190 + (i % 6) * 260 + R(i, 1) * 40, y = 170 + Math.floor(i / 6) * 62;
        if (y > 640) break;
        c.font = '34px KuaiLe'; c.fillStyle = 'rgba(255,253,248,0.55)'; c.textAlign = 'left'; c.textBaseline = 'middle';
        c.fillText(['∫x²dx', 'Δy/Δx', 'sin²+cos²', 'πr²', '√(a+b)', 'Σn=∞', 'f(x)=?', 'log₂8', 'e^iπ', '3x+7=y'][Math.floor(R(i, 2) * 10)]!, x, y);
      }
      if (l) lyric(c, l, t, { y: 720, size: 64, color: '#FFFDF8', dim: 'rgba(255,253,248,0.18)', shadow: null, chalk: true, maxW: 1500, plate: false });
      angel(c, 1700, 1060, 0.8, { t, mood: 'shock', halo: 0.7, wings: 0.4 });
    },
  },
  // 15 眼前一片模糊，眼镜起雾
  {
    bg: 'paper', tr: 'cut', text: null,
    draw: ({ c, t, lt, p, l }) => {
      const blur = 2 + p * 16;
      c.save(); c.filter = `blur(${blur.toFixed(1)}px)`;
      rr(c, 120, 90, 1680, 760, 18); fs(c, COL.wood, 10);
      rr(c, 150, 120, 1620, 700, 8); fs(c, '#2F5A4C', 0, null);
      for (let i = 0; i < 54; i++) {
        c.font = '34px KuaiLe'; c.fillStyle = 'rgba(255,253,248,0.5)'; c.textAlign = 'left';
        c.fillText(['∫x²dx', 'Δy/Δx', 'πr²', '√(a+b)', 'Σn=∞', 'f(x)=?'][i % 6]!, 190 + (i % 6) * 260, 170 + Math.floor(i / 6) * 62);
      }
      if (l) lyric(c, l, t, { y: 720, size: 64, color: '#FFFDF8', dim: 'rgba(255,253,248,0.18)', shadow: null, maxW: 1500, plate: false });
      c.restore();
      // 起雾的眼镜（前景，清楚的）
      c.save(); c.translate(960, 980);
      for (const sd of [-1, 1]) { circle(c, sd * 170, 0, 130); c.fillStyle = `rgba(255,253,248,${0.25 + 0.5 * p})`; c.fill(); pen(c, 12); c.stroke(); }
      line(c, -40, -20, 40, -20, 12);
      c.restore();
      void lt;
    },
  },
  // 16 彩色贴纸被灰色印章一个个盖掉
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt }) => {
      const pos = [[420, 330], [760, 520], [1120, 300], [1460, 520], [600, 760], [1300, 760]];
      pos.forEach(([x, y], i) => {
        const s = pop(lt, i * 0.12, 0.4);
        c.save(); c.translate(x!, y!); c.scale(s, s); c.rotate((R(i, 1) - 0.5) * 0.5);
        if (i % 3 === 0) { star(c, 0, 0, 90); fs(c, COL.gold, 5); }
        else if (i % 3 === 1) { heart(c, 0, 20, 100); fs(c, COL.pink, 5); }
        else { for (let j = 0; j < 5; j++) { circle(c, Math.cos(j * 1.256) * 50, Math.sin(j * 1.256) * 50, 40); fs(c, COL.blue, 4); } circle(c, 0, 0, 34); fs(c, COL.gold2, 4); }
        const st = lt - 0.8 - i * 0.32;
        if (st > 0) {
          const sc = 1 + 0.6 * (1 - clamp(st / 0.12));
          c.scale(sc, sc); circle(c, 0, 0, 105); fs(c, 'rgba(142,135,128,0.92)', 6, COL.ink2);
          line(c, -50, -50, 50, 50, 10, COL.white); line(c, -50, 50, 50, -50, 10, COL.white);
        }
        c.restore();
      });
      void t;
    },
  },
  // 17 试卷上一个大红「0」，身上挂着价签「?」
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt }) => {
      c.save(); c.translate(1330, 470); c.rotate(0.05);
      rr(c, -300, -380, 600, 760, 10); fs(c, COL.white, 6);
      for (let i = 0; i < 12; i++) line(c, -240, -250 + i * 50, 240, -250 + i * 50, 3, COL.gray3);
      const s = pop(lt, 0.4, 0.45);
      c.save(); c.translate(80, -180); c.scale(s, s); c.rotate(-0.15);
      ell(c, 0, 0, 70, 105); pen(c, 22, COL.red); c.stroke();
      ell(c, 0, 0, 150, 125, -0.1); pen(c, 9, COL.red); c.stroke();
      c.restore();
      c.restore();
      angel(c, 560, 960, 1.25, { t, mood: 'sad', halo: 0.6, wings: 0.4 });
      c.save(); c.translate(560, 960 - 1.25 * 120); c.rotate(Math.sin(t * 3) * 0.12);
      line(c, 0, -40, 0, 30, 3); rr(c, -60, 30, 120, 80, 12); fs(c, COL.gold2, 4); text(c, '?', 0, 72, 60, COL.ink);
      c.restore();
    },
  },
];

void [heart, mix];
