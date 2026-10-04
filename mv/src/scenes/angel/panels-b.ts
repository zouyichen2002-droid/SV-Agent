// 第 18–37 句：第二次下凡当社畜 → 麻木 → 逃跑（SV-Agent 10-03）。只画画面，不写歌词原文。
import { clamp, ease, lerp, smoothstep, TAU } from '../../engine/util';
import { COL, R, angel, flyPages, circle, cloud, ell, fs, heart, line, lyric, osc, pen, poly, pop, rr, sparkle, star, text } from './kit';
import type { Panel } from './types';

// 封面模式（?cover=1&angelx=…）：副歌那一页的小天使挪到指定的 x
const AXQ = new URLSearchParams(location.search).get('angelx');
const COVER_AX = AXQ ? Number(AXQ) : null;

const C2 = (c: CanvasRenderingContext2D) => c;
const bgClouds = (c: CanvasRenderingContext2D, t: number, n = 5, col = 'rgba(255,253,248,0.9)') => {
  for (let i = 0; i < n; i++) {
    const x = ((R(i, 3) * 2200 + t * (14 + R(i, 4) * 20)) % 2300) - 180;
    cloud(c, x, 120 + R(i, 5) * 360, 0.5 + R(i, 6) * 0.45, col, 0);
  }
};
const clockFace = (c: CanvasRenderingContext2D, x: number, y: number, r: number, hA: number, mA: number) => {
  circle(c, x, y, r); fs(c, COL.white, 6);
  for (let i = 0; i < 12; i++) { const a = (i / 12) * TAU; line(c, x + Math.cos(a) * r * 0.8, y + Math.sin(a) * r * 0.8, x + Math.cos(a) * r * 0.9, y + Math.sin(a) * r * 0.9, 4); }
  line(c, x, y, x + Math.cos(hA - Math.PI / 2) * r * 0.5, y + Math.sin(hA - Math.PI / 2) * r * 0.5, 9);
  line(c, x, y, x + Math.cos(mA - Math.PI / 2) * r * 0.75, y + Math.sin(mA - Math.PI / 2) * r * 0.75, 6);
};
const pawn = (c: CanvasRenderingContext2D, x: number, y: number, s: number, col: string) => {
  c.save(); c.translate(x, y); c.scale(s, s);
  rr(c, -26, -70, 52, 70, 22); fs(c, col, 4); circle(c, 0, -92, 24); fs(c, COL.skin, 4);
  c.restore();
};

export const PANELS_B: Panel[] = [
  // 18 回到云上（第二遍）：同样的构图，颜色灰一点、日历飞得更快
  {
    bg: 'gray', tr: 'zoom',
    draw: ({ c, t, lt, k }) => {
      bgClouds(c, t, 5, 'rgba(255,253,248,0.6)');
      cloud(c, 980, 820, 2.6, '#EFECE7', 5);
      angel(c, 980, 760 - k * 10, 1.25, { t, mood: 'calm', halo: 0.85, flap: 0.5, armL: 0.3, armR: 0.3 });
      c.save(); c.translate(430, 470);
      rr(c, -110, -120, 220, 240, 14); fs(c, COL.white, 5);
      rr(c, -110, -120, 220, 60, 14); fs(c, COL.gray2, 5);
      text(c, String(1 + Math.floor(lt * 6) % 31), 0, 40, 96, COL.ink);
      c.restore();
      flyPages(c, 430, 470, lt, 5, 14);
    },
  },
  // 19 第二次下凡，这次拎着公文包
  {
    bg: 'gray', tr: 'down',
    draw: ({ c, t, lt, dur }) => {
      c.beginPath(); c.moveTo(-10, 860); c.quadraticCurveTo(960, 780, 1930, 860); c.lineTo(1930, 1090); c.lineTo(-10, 1090); c.closePath(); fs(c, COL.gray, 4);
      const land = Math.min(dur * 0.6, 2.0);
      const y = lerp(260, 830, ease.outCubic(clamp(lt / land)));
      c.save(); c.translate(960, y); c.rotate(lt < land ? osc(t, 0.6) * 0.1 : 0);
      if (lt < land + 0.3) {
        c.globalAlpha = 1 - clamp((lt - land) / 0.3);
        c.beginPath(); c.moveTo(-230, -470); c.quadraticCurveTo(0, -700, 230, -470); c.quadraticCurveTo(0, -520, -230, -470); fs(c, COL.gray2, 5);
        line(c, -225, -470, -40, -250, 3); line(c, 225, -470, 40, -250, 3);
        c.globalAlpha = 1;
      }
      angel(c, 0, 0, 1.1, { t, mood: 'calm', halo: 0.8, wings: 0.5, armL: 2.6, armR: 0.2, suit: lt > land, shadow: lt > land });
      rr(c, 52, -96, 90, 66, 8); fs(c, COL.wood, 4); line(c, 80, -96, 80, -110, 4); line(c, 114, -96, 114, -110, 4); line(c, 80, -110, 114, -110, 4);
      c.restore();
    },
  },
  // 20 穿西装戴工牌，公司大楼，背后一个大齿轮
  {
    bg: 'gray', tr: 'pan',
    draw: ({ c, t, k }) => {
      c.save(); c.translate(1400, 560); c.rotate(t * 0.6);
      for (let i = 0; i < 12; i++) { c.save(); c.rotate((i / 12) * TAU); rr(c, -26, -330, 52, 70, 8); fs(c, COL.gray2, 5); c.restore(); }
      circle(c, 0, 0, 280); fs(c, COL.gray2, 5); circle(c, 0, 0, 90); fs(c, '#E4E0DA', 5);
      c.restore();
      rr(c, 160, 160, 520, 900, 6); fs(c, '#D7D2CB', 5);
      for (let y = 220; y < 1000; y += 110) for (let x = 210; x < 640; x += 110) { rr(c, x, y, 70, 70, 4); fs(c, COL.blue2, 3); }
      angel(c, 1100, 980 - k * 8, 1.35, { t, mood: 'blank', halo: 0.6, wings: 0.25, suit: true, badge: true, armL: 0.1, armR: 0.1 });
    },
  },
  // 21 钟指六点下班，咖啡店约会，冒小气球
  {
    bg: 'pink', tr: 'pan',
    draw: ({ c, t, lt }) => {
      clockFace(c, 260, 230, 120, Math.PI, 0);
      rr(c, 760, 760, 400, 30, 10); fs(c, COL.wood, 5); line(c, 960, 790, 960, 1000, 8);
      for (const x of [880, 1040]) { rr(c, x - 30, 700, 60, 64, 10); fs(c, COL.white, 4); line(c, x + 30, 716, x + 46, 740, 4); }
      angel(c, 640, 1000, 1.15, { t, mood: 'happy', halo: 0.75, wings: 0.4, suit: true, armL: 0.4, armR: 1.4 });
      pawn(c, 1300, 1000, 1.5, COL.blue);
      for (let i = 0; i < 4; i++) {
        const u = (lt * 0.5 + i / 4) % 1;
        const x = 960 + Math.sin(u * 5 + i) * 120, y = 640 - u * 520;
        line(c, x, y + 50, x + Math.sin(u * 8) * 10, y + 120, 2, COL.ink2);
        if (i % 2) { heart(c, x, y + 20, 46); fs(c, COL.pink, 4); } else { ell(c, x, y, 38, 46); fs(c, [COL.gold2, COL.blue, COL.mint][i % 3]!, 4); }
      }
    },
  },
  // 22 钟针飞转过午夜，台灯、咖啡杯越摞越高
  {
    bg: 'night', tr: 'up',
    draw: ({ c, t, lt, p }) => {
      clockFace(c, 1600, 250, 140, lt * 3, lt * 36);
      c.save(); c.translate(560, 560);
      poly(c, [-60, -40, 60, -40, 120, 70, -120, 70]); fs(c, COL.gold2, 5);
      line(c, 0, 70, 0, 260, 8); ell(c, 0, 270, 90, 18); fs(c, COL.ink2, 4);
      c.restore();
      c.save(); c.globalAlpha = 0.25; c.beginPath(); c.moveTo(440, 630); c.lineTo(680, 630); c.lineTo(900, 1000); c.lineTo(220, 1000); c.closePath(); c.fillStyle = COL.gold2; c.fill(); c.restore();
      angel(c, 820, 990, 0.95, { t, mood: 'tired', halo: 0.5, wings: 0.2, suit: true, armL: 1.2, armR: 1.2 });
      rr(c, 160, 840, 1300, 40, 8); fs(c, COL.wood, 5); rr(c, 200, 880, 1220, 200, 0); fs(c, '#A97E58', 5);
      const n = 2 + Math.floor(p * 9);
      for (let i = 0; i < n; i++) { rr(c, 1180 - 50 + Math.sin(i) * 6, 840 - (i + 1) * 64, 100, 60, 10); fs(c, COL.white, 4); }
    },
  },
  // 23 字打在电脑屏幕上；跟拍子鞠躬；举手请示
  {
    bg: 'gray', tr: 'pan', text: null,
    draw: ({ c, t, l, f }) => {
      rr(c, 420, 110, 1080, 600, 24); fs(c, COL.ink2, 8);
      rr(c, 460, 150, 1000, 520, 10); fs(c, '#F4F7F9', 0, null);
      rr(c, 860, 710, 200, 90, 6); fs(c, COL.gray2, 5); rr(c, 700, 790, 520, 40, 10); fs(c, COL.gray2, 5);
      if (l) lyric(c, l, t, { y: 410, size: 58, maxW: 900, typewriter: true, plate: false, shadow: null });
      if (Math.floor(t * 2) % 2) line(c, 1380, 380, 1380, 440, 5, COL.ink);
      const bow = 0.15 + 0.75 * Math.pow(Math.sin(f.beatPhase * Math.PI), 2);
      angel(c, 330, 1010, 1.0, { t, mood: 'tired', halo: 0.5, wings: 0.15, suit: true, bow });
      pawn(c, 1660, 1060, 2.0, COL.suit);
      rr(c, 1700, 700, 110, 110, 30); fs(c, COL.white, 5); text(c, '!', 1755, 755, 84, COL.red);
    },
  },
  // 24 外卖盒、肚子打旋；锅里结蜘蛛网
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t }) => {
      c.save(); c.translate(1380, 600);
      poly(c, [-170, -120, 170, -120, 130, 160, -130, 160]); fs(c, COL.white, 6);
      c.beginPath(); c.moveTo(-100, -120); c.quadraticCurveTo(0, -260, 100, -120); pen(c, 8); c.stroke();
      line(c, 40, -150, 200, -330, 8, COL.wood); line(c, 70, -140, 230, -300, 8, COL.wood);
      c.restore();
      c.save(); c.translate(1500, 980); ell(c, 0, 0, 170, 40); fs(c, COL.gray2, 5);
      for (let i = 0; i < 6; i++) { const a = (i / 6) * Math.PI; line(c, 0, -30, Math.cos(a) * 150, -30 + Math.sin(a) * -30, 2, COL.gray); }
      c.restore();
      angel(c, 640, 980, 1.25, { t, mood: 'sad', halo: 0.5, wings: 0.15, suit: true, armL: -0.4, armR: -0.4 });
      c.save(); c.translate(640, 980 - 1.25 * 100); c.rotate(t * 6);
      c.beginPath(); for (let a = 0; a < 12; a += 0.2) c.lineTo(Math.cos(a) * a * 3.2, Math.sin(a) * a * 3.2); pen(c, 4, COL.red); c.stroke();
      c.restore();
    },
  },
  // 25 回家瘫在沙发拿手柄，睡着了
  {
    bg: 'night', tr: 'pan',
    draw: ({ c, t, p }) => {
      rr(c, 1260, 300, 520, 330, 18); fs(c, COL.ink2, 8);
      rr(c, 1280, 320, 480, 290, 8); fs(c, '#6FB3E0', 0, null);
      for (let i = 0; i < 5; i++) { rr(c, 1320 + i * 80, 520 - Math.abs(Math.sin(t * 3 + i)) * 120, 50, 40, 6); fs(c, [COL.pink, COL.gold, COL.mint][i % 3]!, 3); }
      rr(c, 220, 700, 900, 260, 60); fs(c, COL.red, 6); rr(c, 260, 600, 820, 180, 50); fs(c, '#C84E3E', 6);
      angel(c, 660, 900, 1.1, { t, mood: p < 0.5 ? 'tired' : 'sleep', halo: 0.45, wings: 0.1, suit: true, lean: p < 0.5 ? 0 : -0.3, armL: 1.0, armR: 1.0, blink: false, shadow: false });
      rr(c, 610, 760, 100, 50, 22); fs(c, COL.ink2, 4);
    },
  },
  // 26 地球是三明治：两片面包夹着一层层小人
  {
    bg: 'paper', tr: 'up',
    draw: ({ c, t, k }) => {
      const sq = 1 - k * 0.06;
      c.save(); c.translate(960, 520); c.scale(1, sq);
      rr(c, -560, -330, 1120, 150, 70); fs(c, '#E8C08A', 7);
      for (let i = 0; i < 16; i++) { ell(c, -470 + i * 62 + (i % 2) * 14, -290 + (i % 3) * 22, 9, 5, 0.4); c.fillStyle = '#FFF6E0'; c.fill(); }
      circle(c, 0, 0, 230); fs(c, COL.blue, 7);
      c.save(); circle(c, 0, 0, 226); c.clip();
      for (let i = 0; i < 5; i++) { ell(c, Math.cos(i * 2 + t * 0.3) * 150, Math.sin(i * 1.7) * 140, 70, 46, i); fs(c, COL.mint, 4); }
      c.restore();
      for (let row = 0; row < 2; row++) for (let i = 0; i < 14; i++) {
        const x = -540 + i * 80 + (row ? 40 : 0);
        if (Math.abs(x) < 240 && row === 0) continue;
        c.save(); c.translate(x, row ? 300 : 150); c.rotate(Math.sin(t * 3.2 + i * 0.9 + row) * 0.09);
        pawn(c, 0, 0, 0.8, [COL.gray2, COL.blue, COL.pink][(i + row) % 3]!);
        if ((i + row) % 2) { const u = (t * 0.8 + i * 0.37) % 1; ell(c, 20, -96 + u * 30, 5, 8); c.fillStyle = `rgba(156,203,234,${1 - u})`; c.fill(); }
        if ((i + row) % 4 === 1) { rr(c, -30, -150, 60, 34, 4); fs(c, '#E8C08A', 3); }
        c.restore();
      }
      rr(c, -560, 300, 1120, 150, 70); fs(c, '#E8C08A', 7);
      rr(c, -540, 318, 1080, 114, 56); pen(c, 4, 'rgba(201,154,107,0.6)'); c.stroke();
      c.restore();
    },
  },
  // 27 灵魂电量 100% → 5%，然后翅膀一张从窗户逃出去
  {
    bg: 'gray', tr: 'pan',
    draw: ({ c, t, p }) => {
      const lv = clamp(1 - p / 0.55) * 0.95 + 0.05;
      c.save(); c.translate(500, 420);
      rr(c, -230, -110, 460, 220, 26); fs(c, COL.white, 8); rr(c, 230, -40, 30, 80, 8); fs(c, COL.ink, 0, null);
      rr(c, -210, -90, 420 * lv, 180, 16); fs(c, lv > 0.3 ? COL.mint : COL.red, 0, null);
      text(c, `${Math.round(lv * 100)}%`, 0, 0, 80, COL.ink);
      c.restore();
      rr(c, 1080, 180, 640, 560, 10); fs(c, COL.blue2, 8);
      line(c, 1400, 180, 1400, 740, 8);
      const esc = clamp((p - 0.6) / 0.4);
      const ax = lerp(760, 1700, ease.inQuad(esc)), ay = lerp(940, 300, ease.inQuad(esc));
      angel(c, ax, ay, 1.1, { t, mood: esc > 0 ? 'happy' : 'tired', halo: 0.5 + esc * 0.5, wings: 0.25 + esc * 0.9, flap: 2.5, suit: esc < 0.3, lean: esc * 0.5, armL: esc * 2.5, armR: esc * 2.5, shadow: esc <= 0 });
    },
  },
  // 28 狂笑：「哈」字乱弹，背景转圈
  {
    bg: 'pink', tr: 'zoom',
    draw: ({ c, t, lt, k }) => {
      c.save(); c.translate(960, 540); c.rotate(t * 0.8);
      for (let i = 0; i < 16; i++) { c.rotate(TAU / 16); poly(c, [0, 0, 1400, -120, 1400, 120]); c.fillStyle = i % 2 ? 'rgba(242,181,68,0.18)' : 'rgba(244,166,183,0.18)'; c.fill(); }
      c.restore();
      for (let i = 0; i < 12; i++) {
        const a = lt - i * 0.18;
        if (a < 0) continue;
        const x = 960 + Math.cos(i * 2.4) * (300 + i * 40), y = 470 + Math.sin(i * 1.9) * 300;
        c.save(); c.translate(x, y + Math.sin(t * 8 + i) * 16); c.rotate(Math.sin(t * 4 + i) * 0.4); c.scale(pop(lt, i * 0.18, 0.3), pop(lt, i * 0.18, 0.3));
        text(c, '哈', 0, 0, 90 + R(i, 2) * 60, i % 2 ? COL.red : COL.ink);
        c.restore();
      }
      angel(c, 960, 900 - k * 18, 1.3, { t, mood: 'laugh', halo: 1, wings: 0.8, flap: 3, armL: 2.6, armR: 2.6, lean: Math.sin(t * 6) * 0.08 });
    },
  },
  // 29 一排明信片（山、海、摩天轮、演唱会），勾选框全空
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt }) => {
      const cards: ((x: number) => void)[] = [
        () => { poly(c, [-150, 80, -40, -70, 30, 20, 80, -30, 150, 80]); fs(c, COL.mint, 4); },
        () => { rr(c, -150, 0, 300, 90, 0); fs(c, COL.blue, 0, null); circle(c, 60, -40, 36); fs(c, COL.gold2, 4); },
        () => { circle(c, 0, -10, 90); fs(c, null, 6); for (let i = 0; i < 8; i++) { const a = (i / 8) * TAU + t * 0.5; circle(c, Math.cos(a) * 90, -10 + Math.sin(a) * 90, 14); fs(c, COL.pink, 3); } line(c, 0, -10, -60, 90, 6); line(c, 0, -10, 60, 90, 6); },
        () => { for (let i = 0; i < 5; i++) { pawn(c, -120 + i * 60, 90, 0.7, COL.ink2); } star(c, 0, -60, 40); fs(c, COL.gold, 4); },
      ];
      cards.forEach((draw, i) => {
        const s = pop(lt, i * 0.45, 0.4);
        if (s <= 0) return;
        c.save(); c.translate(300 + i * 440, 470 + (i % 2 ? 30 : -20)); c.scale(s, s); c.rotate((i - 1.5) * 0.06);
        rr(c, -190, -200, 380, 400, 12); fs(c, COL.white, 6);
        c.save(); rr(c, -170, -180, 340, 240, 6); c.clip(); c.fillStyle = COL.blue2; c.fillRect(-170, -180, 340, 240); c.translate(0, -40); draw(0); c.restore();
        rr(c, -30, 100, 60, 60, 8); fs(c, COL.white, 5);
        c.restore();
      });
    },
  },
  // 30 张嘴，气泡里只有「……」，字掉下来
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt }) => {
      angel(c, 620, 980, 1.35, { t, mood: 'shock', halo: 0.45, wings: 0.2, suit: true });
      const s = pop(lt, 0.15, 0.4);
      c.save(); c.translate(1250, 380); c.scale(s, s);
      ell(c, 0, 0, 380, 220); fs(c, COL.white, 7);
      poly(c, [-260, 140, -380, 300, -150, 190]); fs(c, COL.white, 0, null);
      c.beginPath(); c.moveTo(-262, 150); c.lineTo(-380, 300); c.lineTo(-170, 196); pen(c, 7); c.stroke();
      for (let i = 0; i < 6; i++) { circle(c, -150 + i * 60, 0, 14 * (0.5 + 0.5 * osc(t, 1.5, i * 0.15))); fs(c, COL.ink, 0, null); }
      c.restore();
      for (let i = 0; i < 8; i++) {
        const u = clamp((lt - 0.6 - i * 0.18) / 1.2);
        if (u <= 0) continue;
        c.save(); c.translate(1100 + i * 50, 560 + ease.inQuad(u) * 500); c.rotate(u * 4 + i);
        text(c, ['啊', '我', '你', '嗯', '是', '说', '想', '不'][i]!, 0, 0, 56, `rgba(58,51,64,${1 - u})`);
        c.restore();
      }
    },
  },
  // 31 一颗心插着温度计，结冰
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, p, k }) => {
      const col = p < 0.5 ? COL.pink : COL.blue2;
      c.save(); c.translate(960, 560); c.scale(1 + k * 0.05, 1 + k * 0.05);
      heart(c, 0, 80, 320); fs(c, col, 8);
      for (let i = 0; i < 7; i++) {
        const u = clamp(p * 1.4 - i * 0.1);
        if (u <= 0) continue;
        c.save(); c.translate(Math.cos(i * 1.7) * 150, Math.sin(i * 2.3) * 90 - 40); c.scale(u, u);
        for (let j = 0; j < 3; j++) { c.rotate(Math.PI / 3); line(c, -36, 0, 36, 0, 6, COL.white); }
        c.restore();
      }
      c.restore();
      c.save(); c.translate(1220, 330); c.rotate(0.6);
      rr(c, -26, -200, 52, 300, 26); fs(c, COL.white, 6);
      circle(c, 0, 110, 46); fs(c, COL.blue, 6);
      rr(c, -10, 110 - 220 * (1 - p * 0.9), 20, 220 * (1 - p * 0.9), 8); fs(c, COL.blue, 0, null);
      c.restore();
      void t;
    },
  },
  // 32 架子上的游戏盒还包着膜、落灰
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t }) => {
      for (const y of [420, 760]) { rr(c, 300, y, 1320, 30, 6); fs(c, COL.wood, 5); }
      for (let r = 0; r < 2; r++) for (let i = 0; i < 7; i++) {
        const x = 360 + i * 180, y = (r ? 760 : 420) - 250;
        rr(c, x, y, 140, 250, 8); fs(c, [COL.red, COL.blue, COL.mint, COL.gold, COL.pink][(i + r * 2) % 5]!, 5);
        rr(c, x + 16, y + 20, 108, 120, 6); fs(c, 'rgba(255,253,248,0.7)', 3);
        line(c, x + 20, y + 8, x + 120, y + 240, 3, 'rgba(255,255,255,0.8)');
      }
      for (let i = 0; i < 30; i++) {
        const u = (t * 0.08 + R(i, 1)) % 1;
        circle(c, 300 + R(i, 2) * 1320, 140 + u * 760, 3 + R(i, 3) * 3); c.fillStyle = 'rgba(142,135,128,0.5)'; c.fill();
      }
      c.beginPath(); c.moveTo(300, 120); c.quadraticCurveTo(360, 170, 300, 240); c.moveTo(300, 120); c.quadraticCurveTo(380, 150, 440, 120);
      c.moveTo(300, 170); c.quadraticCurveTo(340, 165, 360, 130); pen(c, 2, COL.gray2); c.stroke();
    },
  },
  // 33 两颗心中间一个「=」
  {
    bg: 'pink', tr: 'pan',
    draw: ({ c, t, lt, k }) => {
      const s1 = pop(lt, 0.1, 0.4), s2 = pop(lt, 0.6, 0.4), s3 = pop(lt, 1.1, 0.4);
      c.save(); c.translate(560, 520); c.scale(s1 * (1 + k * 0.06), s1 * (1 + k * 0.06)); heart(c, 0, 80, 230); fs(c, COL.red, 8); c.restore();
      c.save(); c.translate(960, 480); c.scale(s3, s3); rr(c, -90, -50, 180, 34, 12); fs(c, COL.ink, 0, null); rr(c, -90, 20, 180, 34, 12); fs(c, COL.ink, 0, null); c.restore();
      c.save(); c.translate(1360, 520); c.scale(s2, s2); heart(c, 0, 80, 230); c.setLineDash([22, 18]); pen(c, 8, COL.ink2); c.stroke(); c.restore();
      void t;
    },
  },
  // 34 一个大桃子，小天使流口水
  {
    bg: 'pink', tr: 'zoom',
    draw: ({ c, t, k }) => {
      c.save(); c.translate(1260, 500 + Math.sin(t * 3) * 10); c.scale(1 + k * 0.05, 1 + k * 0.05);
      c.beginPath(); c.moveTo(0, -260); c.bezierCurveTo(260, -280, 330, 120, 0, 260); c.bezierCurveTo(-330, 120, -260, -280, 0, -260); c.closePath();
      const g = c.createRadialGradient(-80, -60, 40, 0, 0, 320); g.addColorStop(0, '#FFE1C8'); g.addColorStop(0.6, '#FFB3A0'); g.addColorStop(1, '#F07F8A');
      c.fillStyle = g; c.fill(); pen(c, 8); c.stroke();
      c.beginPath(); c.moveTo(0, -250); c.quadraticCurveTo(-40, 0, 0, 250); pen(c, 5, 'rgba(58,51,64,0.35)'); c.stroke();
      c.beginPath(); c.moveTo(10, -260); c.bezierCurveTo(120, -380, 260, -330, 250, -270); c.bezierCurveTo(160, -250, 60, -250, 10, -260); fs(c, COL.mint, 6);
      c.restore();
      for (let i = 0; i < 4; i++) sparkle(c, 1260 + Math.cos(i * 1.6 + t) * 380, 500 + Math.sin(i * 2.1 + t) * 300, 22, COL.gold);
      angel(c, 560, 980, 1.3, { t, mood: 'drool', halo: 0.6, wings: 0.4, armL: 0.9, armR: 0.9 });
    },
  },
  // 35 梦想气球往上飘，被针扎破，笑出来
  {
    bg: 'sky', tr: 'pan',
    draw: ({ c, t, lt }) => {
      const pop_t = 1.7;
      const by = 560 - lt * 90;
      if (lt < pop_t) {
        line(c, 1100, by + 170, 1080 + Math.sin(t * 4) * 20, by + 360, 3, COL.ink2);
        ell(c, 1100, by, 150, 175); fs(c, COL.gold2, 7);
        star(c, 1100, by, 60); fs(c, COL.white, 4);
      } else {
        const u = clamp((lt - pop_t) / 0.5);
        for (let i = 0; i < 12; i++) { const a = (i / 12) * TAU; line(c, 1100 + Math.cos(a) * (60 + u * 160), by + Math.sin(a) * (60 + u * 160), 1100 + Math.cos(a) * (100 + u * 220), by + Math.sin(a) * (100 + u * 220), 7, COL.gold); }
        text(c, 'POP', 1100, by, 120 * ease.outBack(clamp(u * 2)), COL.red);
      }
      c.save(); c.translate(1100 + 280 - Math.min(lt, pop_t) * 100, by - 220); c.rotate(-2.4);
      line(c, 0, 0, 0, 160, 7, COL.gray2); circle(c, 0, 170, 16); fs(c, COL.red, 4);
      c.restore();
      angel(c, 560, 980, 1.25, { t, mood: lt < pop_t ? 'calm' : 'laugh', halo: 0.6, wings: 0.4, armL: lt < pop_t ? 1.6 : 2.6, armR: 0.3 });
    },
  },
  // 36 副歌：小天使在城市上空狂奔、飞，速度线
  {
    bg: 'sky', tr: 'zoom', text: { size: 80 }, post: ({ k }) => ({ zoom: 1 + 0.016 * k }),
    draw: ({ c, t, lt, k }) => {
      // 傍晚的天：桃色 → 奶油，一个大太阳在楼后面
      const sky = c.createLinearGradient(0, 0, 0, 1080);
      sky.addColorStop(0, '#F6A99A'); sky.addColorStop(0.45, '#FCDDBB'); sky.addColorStop(1, '#FFF3E0');
      c.fillStyle = sky; c.fillRect(-10, -10, 1940, 1100);
      c.save(); c.shadowColor = 'rgba(255,214,110,0.9)'; c.shadowBlur = 80;
      circle(c, 1420, 560, 210); c.fillStyle = '#FFE3A0'; c.fill(); c.restore();
      for (let layer = 0; layer < 2; layer++) {
        const sp = layer ? 520 : 260, col = layer ? '#8F7FA6' : '#C2B3D3', base = layer ? 1080 : 980;
        for (let i = -1; i < 12; i++) {
          const w = 160 + R(i, layer) * 120, h = 220 + R(i, layer + 5) * (layer ? 360 : 300);
          const x = ((i * 220 - lt * sp) % 2640 + 2640) % 2640 - 360;
          rr(c, x, base - h, w, h + 20, 6); fs(c, col, layer ? 4 : 0, layer ? COL.ink : null);
          for (let y = base - h + 30, j = 0; y < base - 40; y += 60, j++) {
            for (const wx of [x + 24, x + w - 54]) {
              const lit = R(i * 31 + j * 7 + (wx > x + 30 ? 1 : 0), layer + 11) > 0.45;
              rr(c, wx, y, 30, 30, 3); c.fillStyle = lit ? (layer ? '#FFE08A' : 'rgba(255,240,200,0.8)') : 'rgba(255,253,248,0.35)'; c.fill();
            }
          }
        }
      }
      for (let i = 0; i < 14; i++) {
        const x = ((R(i, 9) * 1920 - lt * 1800) % 2200 + 2200) % 2200 - 140, y = 160 + R(i, 8) * 560;
        line(c, x, y, x + 120 + R(i, 7) * 160, y, 5, 'rgba(255,253,248,0.9)');
      }
      angel(c, COVER_AX ?? 900 + Math.sin(t * 1.5) * 60, 600 + Math.sin(t * 3) * 40 - k * 20, 1.35, { t, mood: 'laugh', halo: 1, wings: 1.25, flap: 4, armL: 2.6, armR: 2.0, lean: 0.35, shadow: false });
      for (let i = 0; i < 6; i++) sparkle(c, 760 - i * 70 + Math.sin(t * 5 + i) * 10, 330 + Math.sin(i * 1.3 + t * 2) * 40, 12 - i, COL.gold);
    },
  },
  // 37 小天使捧着地球雪花球摇晃
  {
    bg: 'night', tr: 'up',
    draw: ({ c, t, lt }) => {
      for (let i = 0; i < 30; i++) sparkle(c, R(i, 1) * 1920, R(i, 2) * 600, 4 + R(i, 3) * 6, COL.gold2);
      const sh = Math.sin(lt * 9) * 0.18 * clamp(1 - lt / 4);
      c.save(); c.translate(960, 560); c.rotate(sh);
      rr(c, -230, 210, 460, 110, 20); fs(c, COL.wood, 6);
      circle(c, 0, 0, 250); fs(c, 'rgba(207,230,245,0.55)', 7);
      circle(c, 0, 60, 120); fs(c, COL.blue, 5);
      ell(c, -40, 30, 50, 30, 0.4); fs(c, COL.mint, 4); ell(c, 50, 100, 40, 24, -0.3); fs(c, COL.mint, 4);
      for (let i = 0; i < 40; i++) {
        const a = R(i, 4) * TAU + lt * (0.5 + R(i, 5)), r = 40 + R(i, 6) * 190;
        circle(c, Math.cos(a) * r, Math.sin(a) * r * 0.9 - (lt * 30 * R(i, 7)) % 60, 5); c.fillStyle = COL.white; c.fill();
      }
      c.restore();
      angel(c, 960, 1060, 0.9, { t, mood: 'blank', halo: 0.55, wings: 0.4, armL: 2.4, armR: 2.4 });
    },
  },
];

void [C2, smoothstep, lyric, star, pen, circle];
