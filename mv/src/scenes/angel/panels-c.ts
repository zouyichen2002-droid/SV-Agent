// 第 38–49 句 + 结尾：孤注一掷 → 翅膀被剥夺 → 心跳停止 → 灵魂轻笑、光环飞走（SV-Agent 10-03）。只画画面，不写歌词原文。
import { clamp, ease, lerp, TAU } from '../../engine/util';
import { COL, R, angel, circle, cloud, ell, fs, heart, line, osc, pen, poly, pop, rr, sparkle, star, text } from './kit';
import type { Panel } from './types';

const pawn = (c: CanvasRenderingContext2D, x: number, y: number, s: number, col: string) => {
  c.save(); c.translate(x, y); c.scale(s, s);
  rr(c, -26, -70, 52, 70, 22); fs(c, col, 4); circle(c, 0, -92, 24); fs(c, COL.skin, 4);
  c.restore();
};
const stars = (c: CanvasRenderingContext2D, t: number, n = 40, h = 700) => {
  for (let i = 0; i < n; i++) sparkle(c, R(i, 1) * 1920, R(i, 2) * h, 4 + R(i, 3) * 6 * (0.6 + 0.4 * osc(t, 0.4 + R(i, 4), R(i, 5))), COL.gold2);
};
const die = (c: CanvasRenderingContext2D, x: number, y: number, s: number, rot: number, n: number) => {
  c.save(); c.translate(x, y); c.rotate(rot); c.scale(s, s);
  rr(c, -60, -60, 120, 120, 22); fs(c, COL.white, 6);
  const P: Record<number, number[][]> = { 1: [[0, 0]], 2: [[-28, -28], [28, 28]], 3: [[-28, -28], [0, 0], [28, 28]], 4: [[-28, -28], [28, -28], [-28, 28], [28, 28]], 5: [[-28, -28], [28, -28], [0, 0], [-28, 28], [28, 28]], 6: [[-28, -30], [28, -30], [-28, 0], [28, 0], [-28, 30], [28, 30]] };
  for (const [px, py] of P[n]!) { circle(c, px!, py!, 10); c.fillStyle = n === 1 ? COL.red : COL.ink; c.fill(); }
  c.restore();
};

export const PANELS_C: Panel[] = [
  // 38 筹码全推出去，骰子在转
  {
    bg: 'paper', tr: 'zoom',
    draw: ({ c, t, lt, k }) => {
      ell(c, 960, 700, 820, 300); fs(c, '#4E9A7A', 8);
      ell(c, 960, 700, 760, 260); pen(c, 4, 'rgba(255,253,248,0.5)'); c.stroke();
      const push = ease.outCubic(clamp(lt / 1.2));
      for (let s = 0; s < 4; s++) for (let i = 0; i < 6; i++) {
        const x = lerp(360 + s * 70, 900 + s * 50, push), y = 800 - i * 18;
        ell(c, x, y, 50, 18); fs(c, [COL.red, COL.blue, COL.gold, COL.ink2][s]!, 4);
      }
      const roll = clamp(lt / 1.8);
      die(c, lerp(1500, 1250, roll), 620 - Math.abs(Math.sin(roll * 9)) * 120 * (1 - roll), 1, lt * 12 * (1 - roll), 1 + Math.floor(R(Math.floor(lt * 10), 3) * 6) * (roll < 1 ? 1 : 0) + (roll >= 1 ? 6 - 1 : 0));
      die(c, lerp(1640, 1420, roll), 680 - Math.abs(Math.sin(roll * 7)) * 100 * (1 - roll), 0.9, -lt * 10 * (1 - roll), roll >= 1 ? 6 : 1 + Math.floor(R(Math.floor(lt * 10), 4) * 6));
      angel(c, 340, 1000, 1.05, { t, mood: 'wink', halo: 0.6, wings: 0.4, armL: 1.5, armR: 1.5, lean: 0.1 - k * 0.05 });
    },
  },
  // 39 云上几位神仙往下看，下面是人间的灰雨，他们看不见
  {
    bg: 'sky', tr: 'up',
    draw: ({ c, t, lt }) => {
      c.fillStyle = '#C9C4BE'; c.fillRect(0, 560, 1920, 520);
      for (let i = 0; i < 60; i++) { const u = (lt * 1.2 + R(i, 2)) % 1; const x = R(i, 3) * 1920, y = 560 + u * 500; line(c, x, y, x - 8, y + 30, 3, COL.gray2); }
      for (let i = 0; i < 12; i++) pawn(c, 120 + i * 150, 1060, 0.9, COL.gray2);
      for (let i = 0; i < 3; i++) {
        const x = 480 + i * 480, y = 300 + Math.sin(t + i) * 10;
        cloud(c, x, y + 70, 1.8, COL.white, 5);
        circle(c, x, y - 40, 70); fs(c, COL.skin, 5);
        c.beginPath(); c.moveTo(x - 60, y - 10); c.quadraticCurveTo(x, y + 110, x + 60, y - 10); fs(c, COL.white, 5);
        c.save(); c.shadowColor = 'rgba(255,214,110,0.9)'; c.shadowBlur = 20; ell(c, x, y - 130, 60, 15); pen(c, 9, COL.gold); c.stroke(); c.restore();
        for (const sx of [-24, 24]) { c.beginPath(); c.arc(x + sx, y - 46, 10, Math.PI * 0.1, Math.PI * 0.9); pen(c, 4); c.stroke(); }
      }
    },
  },
  // 40 笑脸面具和哭脸面具来回翻
  {
    bg: 'pink', tr: 'pan',
    draw: ({ c, t, lt }) => {
      for (let i = 0; i < 2; i++) {
        const flip = Math.cos(lt * Math.PI * 1.2 + i * Math.PI);
        const happy = flip > 0; // 两张一正一反：一张笑的时候另一张哭
        c.save(); c.translate(620 + i * 680, 500); c.scale(Math.max(0.04, Math.abs(flip)), 1);
        c.beginPath(); c.moveTo(-200, -220); c.quadraticCurveTo(0, -300, 200, -220); c.quadraticCurveTo(230, 120, 0, 240); c.quadraticCurveTo(-230, 120, -200, -220); c.closePath();
        fs(c, happy ? COL.gold2 : COL.blue2, 8);
        for (const sx of [-80, 80]) { c.beginPath(); happy ? c.arc(sx, -40, 40, Math.PI * 1.1, Math.PI * 1.9) : c.arc(sx, -70, 40, Math.PI * 0.1, Math.PI * 0.9); pen(c, 10); c.stroke(); }
        c.beginPath(); happy ? c.arc(0, 40, 90, Math.PI * 0.15, Math.PI * 0.85) : c.arc(0, 160, 80, Math.PI * 1.2, Math.PI * 1.8); pen(c, 12); c.stroke();
        if (!happy) { ell(c, 80, 60, 14, 22); fs(c, COL.blue, 0, null); }
        c.restore();
      }
      void t;
    },
  },
  // 41 羽毛一片片掉，翅膀被线拽走
  {
    bg: 'gray', tr: 'down',
    draw: ({ c, t, lt, p }) => {
      const pull = ease.inCubic(clamp((p - 0.15) / 0.7));
      for (const sd of [-1, 1]) line(c, 960 + sd * 120, -20, 960 + sd * (150 + pull * 200), 540 - pull * 560, 3, COL.ink2);
      angel(c, 960, 1000, 1.3, { t, mood: 'sad', halo: 0.5 - p * 0.3, wings: 1 - pull * 0.95, flap: 0.3 });
      for (let i = 0; i < 18; i++) {
        const u = clamp((lt - i * 0.12) / 2.2);
        if (u <= 0) continue;
        const x = 960 + (R(i, 1) - 0.5) * 700 + Math.sin(u * 8 + i) * 50, y = 560 + u * 480;
        c.save(); c.translate(x, y); c.rotate(Math.sin(u * 6 + i) * 0.9);
        ell(c, 0, 0, 16, 40); fs(c, COL.white, 3); line(c, 0, -36, 0, 40, 2, COL.gray2);
        c.restore();
      }
    },
  },
  // 42 人生传送带：上学、上班、结婚、买房的箱子一个个过
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt }) => {
      rr(c, -40, 700, 2000, 90, 45); fs(c, COL.gray2, 7);
      for (let i = 0; i < 12; i++) { const x = ((i * 180 + lt * 260) % 2160) - 120; circle(c, x, 745, 30); fs(c, COL.gray, 4); }
      const icons: ((s: number) => void)[] = [
        () => { rr(c, -50, -40, 100, 80, 6); fs(c, COL.blue, 4); line(c, 0, -40, 0, 40, 4); },
        () => { rr(c, -55, -35, 110, 75, 8); fs(c, COL.wood, 4); line(c, -20, -35, -20, -50, 5); line(c, 20, -35, 20, -50, 5); line(c, -20, -50, 20, -50, 5); },
        () => { circle(c, 0, 0, 40); pen(c, 10, COL.gold); c.stroke(); star(c, 0, -46, 16, 4); fs(c, COL.blue2, 3); },
        () => { poly(c, [-60, 0, 0, -55, 60, 0]); fs(c, COL.red, 4); rr(c, -45, 0, 90, 60, 4); fs(c, COL.white, 4); },
      ];
      for (let i = 0; i < 6; i++) {
        const x = ((i * 380 + lt * 260) % 2280) - 180;
        c.save(); c.translate(x, 600);
        rr(c, -110, -100, 220, 200, 14); fs(c, '#E8C08A', 6);
        c.translate(0, 0); icons[i % 4]!(1);
        c.restore();
      }
      angel(c, 960, 700 - Math.abs(Math.sin(t * 5)) * 8, 0.75, { t, mood: 'tired', halo: 0.4, wings: 0.15, walk: lt });
    },
  },
  // 43 一封写着「幸福」的信，一直没人拆
  {
    bg: 'paper', tr: 'pan',
    draw: ({ c, t, lt, p }) => {
      c.save(); c.translate(960, 470); c.rotate(-0.05 + Math.sin(t) * 0.01);
      rr(c, -380, -240, 760, 480, 16); fs(c, COL.white, 8);
      poly(c, [-380, -240, 0, 40, 380, -240], false); pen(c, 7); c.stroke();
      heart(c, 0, 50, 70); fs(c, COL.red, 5);
      text(c, '幸福', 0, 170, 76, COL.ink);
      c.restore();
      // 时间过去：灰一层层落上来
      c.fillStyle = `rgba(184,178,170,${0.45 * p})`; c.fillRect(570, 220, 780, 500);
      for (let i = 0; i < 20; i++) { const u = (lt * 0.15 + R(i, 1)) % 1; circle(c, 600 + R(i, 2) * 720, 140 + u * 600, 3); c.fillStyle = 'rgba(142,135,128,0.6)'; c.fill(); }
      angel(c, 1650, 1000, 0.85, { t, mood: 'blank', halo: 0.35, wings: 0.1, walk: lt });
    },
  },
  // 44 心电图 → 一条直线
  {
    bg: 'night', tr: 'cut', text: { size: 92, y: 860 }, post: ({ lt, dur }) => ({ flash: lt > dur * 0.45 ? 0.45 * Math.pow(0.5, (lt - dur * 0.45) / 0.18) : 0 }),
    draw: ({ c, lt, dur }) => {
      const flat = clamp((lt - dur * 0.45) / 0.15);
      c.beginPath();
      for (let x = 0; x <= 1920; x += 6) {
        const ph = ((x / 1920) * 3 - lt * 1.2) % 1;
        const beat = (ph + 1) % 1;
        const y = 420 - (1 - flat) * (beat > 0.4 && beat < 0.48 ? (beat < 0.44 ? (beat - 0.4) * 6000 : (0.48 - beat) * 6000) : 0);
        x ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.shadowColor = 'rgba(169,223,197,0.9)'; c.shadowBlur = 18; pen(c, 7, COL.mint); c.stroke(); c.shadowBlur = 0;
    },
  },
  // 45 笼子合上，光环暗下去
  {
    bg: 'gray', tr: 'cut',
    draw: ({ c, t, lt, p }) => {
      angel(c, 960, 960, 1.2, { t, mood: 'sad', halo: 0.6 - p * 0.55, wings: 0.12 });
      const yb = lerp(-700, 0, ease.outCubic(clamp(lt / 0.8)));
      c.save(); c.translate(0, yb);
      for (let i = 0; i <= 10; i++) line(c, 640 + i * 64, 260, 640 + i * 64, 1000, 9, COL.ink2);
      c.beginPath(); c.moveTo(640, 260); c.quadraticCurveTo(960, 40, 1280, 260); pen(c, 12, COL.ink2); c.stroke();
      rr(c, 600, 980, 720, 40, 10); fs(c, COL.ink2, 0, null);
      c.restore();
    },
  },
  // 46 躺着，蜡烛烧短
  {
    bg: 'night', tr: 'pan',
    draw: ({ c, t, p }) => {
      rr(c, 260, 760, 1000, 110, 24); fs(c, COL.gray2, 5);
      line(c, 300, 870, 300, 960, 8, COL.gray2); line(c, 1220, 870, 1220, 960, 8, COL.gray2);
      rr(c, 300, 640, 230, 110, 50); fs(c, COL.white, 5);
      angel(c, 492, 813, 0.62, { t, mood: 'sleep', halo: 0.25 - p * 0.2, wings: 0, blink: false, shadow: false, lean: -0.5 });
      c.beginPath(); c.moveTo(340, 752); c.quadraticCurveTo(760, 700 + Math.sin(t * 0.8) * 4, 1230, 742); c.lineTo(1230, 860); c.lineTo(340, 860); c.closePath(); fs(c, COL.white, 5);
      const h = 300 * (1 - p * 0.8);
      rr(c, 1380, 900 - h, 90, h, 10); fs(c, COL.white, 5);
      const fl = 1 + Math.sin(t * 13) * 0.08;
      c.save(); c.translate(1425, 900 - h - 46); c.scale(fl, fl);
      c.shadowColor = 'rgba(255,214,110,0.9)'; c.shadowBlur = 40;
      c.beginPath(); c.moveTo(0, -50); c.quadraticCurveTo(34, 0, 0, 34); c.quadraticCurveTo(-34, 0, 0, -50); c.fillStyle = COL.gold; c.fill();
      c.restore();
      rr(c, 1340, 900, 170, 24, 8); fs(c, COL.gray2, 4);
    },
  },
  // 47 土丘和小花；剖面里小天使还睁着眼
  {
    bg: 'paper', tr: 'down',
    draw: ({ c, t }) => {
      c.fillStyle = '#B98D66'; c.fillRect(0, 520, 1920, 560);
      for (let i = 0; i < 40; i++) { circle(c, R(i, 1) * 1920, 560 + R(i, 2) * 500, 6 + R(i, 3) * 8); c.fillStyle = 'rgba(58,51,64,0.12)'; c.fill(); }
      c.beginPath(); c.moveTo(560, 524); c.quadraticCurveTo(960, 330, 1360, 524); c.closePath(); fs(c, '#C79B72', 6);
      line(c, 0, 522, 1920, 522, 6);
      for (let i = 0; i < 5; i++) {
        const x = 700 + i * 130, y = 460 - Math.sin((i + 0.5) / 5 * Math.PI) * 60;
        line(c, x, y + 50, x, y, 4, COL.mint);
        for (let j = 0; j < 5; j++) { circle(c, x + Math.cos(j * 1.256 + t) * 16, y + Math.sin(j * 1.256 + t) * 16, 12); fs(c, [COL.pink, COL.gold2, COL.white][i % 3]!, 3); }
      }
      rr(c, 600, 720, 720, 200, 30); fs(c, '#8E6A4E', 5);
      rr(c, 630, 760, 150, 80, 36); fs(c, COL.white, 4);
      angel(c, 760, 915, 0.55, { t, mood: 'blank', halo: 0.15, wings: 0, shadow: false, lean: -0.5 });
      c.beginPath(); c.moveTo(690, 850); c.quadraticCurveTo(1000, 815, 1290, 840); c.lineTo(1290, 905); c.lineTo(690, 905); c.closePath(); fs(c, COL.white, 4);
    },
  },
  // 48 灵魂飘起来轻笑，倒数 4、3、2、1
  {
    bg: 'night', tr: 'up', text: { y: 980 },
    draw: ({ c, t, lt, dur }) => {
      stars(c, t, 50, 1080);
      const n = 4 - Math.min(3, Math.floor((lt / dur) * 4));
      const u = ((lt / dur) * 4) % 1;
      c.save(); c.translate(1420, 430); c.scale(1.2 - u * 0.2, 1.2 - u * 0.2);
      c.globalAlpha = 1 - u * 0.6;
      text(c, String(n), 0, 0, 380, COL.gold2);
      c.restore();
      angel(c, 700, 860 - lt * 60 + Math.sin(t * 2) * 14, 1.15, { t, mood: 'happy', halo: 0.9, wings: 0.3, ghost: true, alpha: 0.85, armL: 1.0, armR: 1.0 });
    },
  },
  // 49 光环自己飞走，飞回星空
  {
    bg: 'night', tr: 'pan', text: { size: 84, y: 960 }, post: ({ k }) => ({ zoom: 1 + 0.012 * k }),
    draw: ({ c, t, lt, dur }) => {
      stars(c, t, 60, 1080);
      const u = ease.inOutCubic(clamp(lt / (dur * 0.85)));
      const x = lerp(760, 1500, u), y = lerp(780, 160, u) + Math.sin(u * TAU) * 60;
      for (let i = 1; i < 14; i++) {
        const v = clamp(u - i * 0.025);
        sparkle(c, lerp(760, 1500, v), lerp(780, 160, v) + Math.sin(v * TAU) * 60, 16 - i, COL.gold);
      }
      c.save(); c.translate(x, y); c.rotate(-0.2 + u * 0.6);
      c.shadowColor = 'rgba(255,214,110,1)'; c.shadowBlur = 50;
      ell(c, 0, 0, 90, 26); pen(c, 16, COL.gold); c.stroke();
      c.restore();
      angel(c, 640, 980, 0.9, { t, mood: 'sleep', halo: 0, wings: 0, alpha: 0.35 * (1 - u), ghost: true, blink: false });
    },
  },
  // 结尾：手账合上，标题、原曲
  {
    bg: 'sky', tr: 'zoom', text: null,
    draw: ({ c, t, lt, dur }) => {
      for (let i = 0; i < 5; i++) { const x = ((R(i, 3) * 2200 + t * 20) % 2300) - 180; cloud(c, x, 140 + R(i, 5) * 300, 0.6, 'rgba(255,253,248,0.9)', 0); }
      cloud(c, 960, 880, 3.2, COL.white, 5);
      const s = 0.85 + 0.15 * ease.outCubic(clamp(lt / 0.8));
      c.save(); c.translate(960, 560); c.scale(s, s);
      rr(c, -330, -230, 660, 460, 26); fs(c, COL.pink, 6);
      rr(c, -300, -200, 600, 400, 18); fs(c, COL.pink2, 0, null);
      c.save(); c.setLineDash([12, 12]); ell(c, 0, -90, 70, 18); pen(c, 8, COL.gold); c.stroke(); c.restore();
      text(c, '《逃跑的天使》', 0, 30, 74, COL.ink);
      text(c, '原曲 伊野奏', 0, 130, 40, COL.ink2);
      c.restore();
      // 最后一秒淡出
      c.fillStyle = `rgba(30,34,56,${clamp((lt - (dur - 1.2)) / 1.2)})`; c.fillRect(-10, -10, 1940, 1100);
    },
  },
];

void [heart, poly, pop];
