// 《由》人偶剧场 MV（SV-Agent 10-04）：一座黑色纸剧场，提线瓷人偶和墙上的影子，丝线 + 裂缝两条线索，
// 三遍副歌背幕沿裂缝撕开、后面是星尘（创作者给的官方图，仓库外 /song/art/）。设计手册在项目的 MV\TREATMENT.md。
// 时间点一律按第几句歌词找（代码里没有歌词原文）。只由歌曲时间决定，没有状态。
import type * as THREE from 'three';
import { Scene, type Frame } from '../engine/scene';
import { Layer2D, W, H } from '../engine/gl';
import { clamp, ease, hash, lerp, smoothstep, TAU } from '../engine/util';
import { font } from '../engine/type';
import type { Line } from '../engine/lyrics';
import {
  PAL, FAM, CAM0, layer, backdrop, floor, curtains, spot, dust, stardust, makeCrack, drawCrack,
  lyricTags, lyricLine, lyricWrite, lyricStamp, star4, type Cam, type C2,
} from './theater/kit';
import { POSE0, doll, strings, mixPose, rig, type Pose, type DollLook } from './theater/doll';
import {
  tearsOnLine, filmOnLine, staffLines, revealArt, quillHand, inkHarbor, popCity, rose, mask, poison, peacockFan,
  umbrella, prayingHands, glassBubble, gear, reveler, inkDoor, net,
} from './theater/props';

const BACK = 1.8;       // 背幕的深度
const FRONT = 0.72;     // 前景大幕
const GLOW = 2.2;       // glow 层叠加的倍数（> 1 才会被泛光抓到）

type Sec = { name: string; a: number; b: number };

function loadImg(src: string): Promise<HTMLImageElement | null> {
  return new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = src; });
}

// 姿势
const P = (o: Partial<Pose>): Pose => ({ ...POSE0, ...o });
const HANG = P({ hang: 1, head: 0.2, aL: [0.05, 0.05], aR: [-0.05, -0.05], lL: [0.1, 0.25], lR: [-0.05, 0.3], y: 590 });
const STAND = P({ hang: 0 });
const LIFT = P({ hang: 0.35, head: -0.12, aL: [0.25, 0.2], aR: [-0.3, -0.25] });
const REACH = P({ hang: 0, lean: 0.12, head: 0.15, aR: [1.5, 0.15], aL: [-0.35, -0.3], lR: [0.18, 0.05], lL: [-0.08, 0] });
const OPEN = P({ hang: 0, head: -0.2, aL: [-1.1, -0.4], aR: [1.1, 0.4] });
const OATH = P({ hang: 0, head: -0.1, aR: [2.7, 0.3], aL: [-0.3, -0.2] });
const FALL = P({ hang: 0.85, lean: 0.55, head: 0.5, y: 700, aL: [-0.6, -0.8], aR: [0.9, 0.6], lL: [1.35, -1.6], lR: [1.15, -1.3] });
const DANCE_A = P({ hang: 0, lean: -0.1, head: -0.15, aL: [-2.5, -0.5], aR: [1.3, 0.6], lL: [-0.25, 0.1], lR: [0.6, -0.9] });
const DANCE_B = P({ hang: 0, lean: 0.1, head: 0.15, aL: [-1.3, -0.6], aR: [2.5, 0.5], lL: [-0.6, 0.9], lR: [0.25, -0.1] });
const CROUCH = P({ hang: 0.3, lean: 0.25, head: 0.35, y: 660, aL: [-0.9, -1.6], aR: [0.9, 1.6], lL: [0.9, -1.4], lR: [-0.2, 0.9] });

type Key = [number, Pose];
function poseAt(ks: Key[], t: number, dur = 0.45): Pose {
  let cur = ks[0]![1];
  for (let i = 1; i < ks.length; i++) {
    const [ti, pi] = ks[i]!;
    if (t < ti) break;
    cur = mixPose(cur, pi, ease.inOutCubic(clamp((t - ti) / dur)));
  }
  return cur;
}

export default class Theater extends Scene {
  base = new Layer2D();
  glow = new Layer2D(W, H, 0.5);
  art: (HTMLImageElement | null)[] = [];
  credits: string[] = [];
  sec: Record<string, Sec> = {};
  dKeys: Key[] = [];
  faceCrack = makeCrack(0, 0, 0, 1, 1);
  backCracks = [makeCrack(1200, 110, 1.66, 640, 301, 4), makeCrack(1180, 100, 1.52, 660, 302, 4), makeCrack(1150, 90, 1.6, 700, 303, 5)];

  L(n: number): Line { return this.ctx.lyrics.lines[n - 1]!; }
  s(n: number) { return this.L(n).start; }
  e(n: number) { return this.L(n).end; }

  async init() {
    this.art = await Promise.all(['/song/art/1_night.png', '/song/art/2_halo.png', '/song/art/3_stand.png'].map(loadImg));
    try { const j = await (await fetch('/song/mv.json')).json(); this.credits = j.credits ?? []; } catch { this.credits = []; }
    const n = this.ctx.lyrics.lines.length;
    if (n !== 76) throw new Error(`《由》应该是 76 句，lyrics.json 里是 ${n} 句`);
    const D = this.ctx.audio.duration;
    const S = (name: string, a: number, b: number) => (this.sec[name] = { name, a, b });
    S('intro', 0, this.s(4) - 0.4);
    S('v1', this.s(4) - 0.4, this.s(14) - 0.3);
    S('v1b', this.s(14) - 0.3, this.s(23) - 0.4);
    S('ch1', this.s(23) - 0.4, this.e(32) + 0.3);
    S('int1', this.e(32) + 0.3, this.s(33) - 0.3);
    S('v2', this.s(33) - 0.3, this.s(42) - 0.25);
    S('ch2', this.s(42) - 0.25, this.e(51) + 0.3);
    S('inst', this.e(51) + 0.3, this.s(52) - 0.3);
    S('br', this.s(52) - 0.3, this.s(67) - 0.4);
    S('ch3', this.s(67) - 0.4, this.e(76) + 0.3);
    S('outro', this.e(76) + 0.3, D);
    const s = (k: number) => this.s(k);
    // 人偶的姿势（按句子）
    this.dKeys = [
      [0, HANG], [s(4), P({ ...HANG, head: 0.05, hang: 0.8 })], [s(5), LIFT], [s(6), STAND], [s(9), P({ ...STAND, head: -0.08 })],
      [s(11), OPEN], [s(13), P({ ...STAND, head: 0.35 })],
      [s(14), REACH], [s(16), P({ ...REACH, aR: [1.2, 0.5] })], [s(17), STAND], [s(18), P({ ...STAND, head: 0.2, aR: [0.6, 1.2] })],
      [s(20), P({ ...STAND, hang: 0.15, lean: -0.05, aL: [-0.5, -0.3], aR: [0.5, 0.3] })], [s(22), P({ ...STAND, head: -0.25 })],
      [s(23), P({ ...STAND, head: -0.2 })], [s(25), P({ ...STAND, lean: -0.12, head: -0.3, aL: [-0.8, -1.5], aR: [0.8, 1.5] })],
      [s(27), P({ ...STAND, head: 0.25, aR: [2.2, 1.6] })], [s(29), P({ ...STAND, head: -0.1 })], [s(31), FALL], [s(32), FALL],
      [this.sec.int1!.a, P({ ...FALL, hang: 1 })],
      [s(33), P({ ...HANG, hang: 0.5 })], [s(34), STAND], [s(36), P({ ...STAND, aL: [-0.3, -2.0], aR: [0.3, 2.0], head: 0.3 })],
      [s(38), P({ ...STAND, head: 0.4 })], [s(39), P({ ...STAND, head: -0.05 })], [s(41), P({ ...STAND, aR: [1.0, 0.5], head: 0.1 })],
      [s(42), P({ ...STAND, head: -0.15 })], [s(44), P({ ...STAND, aL: [-1.4, -0.3], aR: [1.4, 0.3] })], [s(46), P({ ...STAND, head: 0.25, aR: [2.2, 1.6] })],
      [s(48), P({ ...STAND, head: -0.1, aR: [1.2, 0.4] })], [s(50), FALL], [s(51), FALL],
      [this.sec.inst!.a + 1.0, CROUCH], [this.sec.inst!.a + 4.0, STAND],
      [s(52), P({ ...STAND, x: 1460, s: 0.78, y: 650 })],
      [s(59), P({ ...OPEN, x: 1460, s: 0.78, y: 650 })], [s(61), P({ ...STAND, x: 1460, s: 0.78, y: 650 })],
      [s(62), P({ ...CROUCH, x: 1460, s: 0.78, y: 690 })], [s(64), P({ ...STAND, x: 1460, s: 0.78, y: 650, head: 0.2 })],
      [s(66), P({ ...OPEN, x: 1460, s: 0.78, y: 650 })],
      [s(67), P({ ...STAND, head: -0.15 })], [s(69), OATH], [s(70), DANCE_A], [s(71), P({ ...STAND, head: 0.25, aR: [2.2, 1.6] })],
      [s(73), P({ ...STAND, aR: [2.6, 0.2] })], [s(74), OPEN], [s(75), P({ ...STAND, lean: -0.1, head: -0.35, hang: 0.2 })], [s(76), P({ ...STAND, head: -0.3 })],
      [this.sec.outro!.a + 2.5, P({ ...STAND, head: -0.05 })], [this.sec.outro!.a + 9, OPEN],
    ];
  }

  // ------------------------------------------------------------ 状态
  /** 三遍副歌里唱到裂缝的那句前后：背幕撕开的程度（0..1，人偶让开、影子隐去用）。 */
  revealAmt(t: number) {
    let m = 0;
    for (const k of [30, 49, 74]) {
      const a = this.s(k) - 0.4, b = k === 74 ? this.e(76) : this.e(k + 1);
      m = Math.max(m, ease.inOutCubic(clamp((t - a) / 0.6)) * (1 - ease.inOutCubic(clamp((t - b) / 0.6))));
    }
    return m;
  }
  private inSec(t: number) { for (const k in this.sec) { const v = this.sec[k]!; if (t >= v.a && t < v.b) return v; } return this.sec.outro!; }

  private dollPose(f: Frame): { pose: Pose; sway: number } {
    const t = f.t;
    let pose = poseAt(this.dKeys, t);
    const sec = this.inSec(t).name;
    // 纯音乐：八音盒转圈舞
    if (sec === 'inst') {
      const v = this.sec.inst!, lt = t - v.a;
      if (lt > 4.5) {
        const ph = Math.sin((t - v.a) * TAU / (60 / this.ctx.audio.bpm * 2));
        pose = mixPose(DANCE_A, DANCE_B, 0.5 + 0.5 * ph);
        const spin = (lt - 4.5) * (0.6 + 0.04 * (lt - 4.5));
        pose = { ...pose, x: 960 + Math.sin(spin) * 40, s: 1 + 0.03 * Math.cos(spin) };
      }
    }
    // 副歌三的华尔兹
    if (t >= this.s(70) && t < this.s(71)) {
      const ph = Math.sin((t - this.s(70)) * TAU / (60 / this.ctx.audio.bpm * 3));
      pose = { ...mixPose(DANCE_A, DANCE_B, 0.5 + 0.5 * ph), x: 880 + 60 * ph };
    }
    // 背幕撕开时往左让开（不挡星尘）
    const rv = this.revealAmt(t);
    if (rv > 0) pose = { ...pose, x: lerp(pose.x, 560, rv) };
    // 提线木偶的晃 + 呼吸 + 底鼓一顶
    const sway = Math.sin(t * 0.9) * 0.6 + Math.sin(t * 2.3) * 0.15;
    pose = { ...pose, x: pose.x + sway * 6, y: pose.y - f.a.kick * 6 * (1 - pose.hang), head: pose.head + Math.sin(t * 1.1) * 0.03 };
    return { pose, sway };
  }

  private look(t: number): DollLook {
    const s = (k: number) => this.s(k);
    const lips = clamp((t - s(9)) / 0.8);
    const fire = t >= s(10) && t < s(11) + 0.5 ? clamp((t - s(10)) / 0.4) * (1 - clamp((t - s(11)) / 0.5)) : t >= s(26) && t < s(27) ? 0.6 : 0;
    const crack = clamp((t - s(22)) / 1.4) * 0.45 + clamp((t - s(31)) / 1.0) * 0.2 + clamp((t - s(50)) / 1.0) * 0.15 + clamp((t - s(74)) / 1.0) * 0.2;
    const heart = t >= s(11) && t < s(14) ? clamp((t - s(11)) / 0.5) : t >= s(36) && t < s(37) ? 1 : 0;
    const crown = t >= s(29) - 0.2 && t < s(31) + 0.5 ? clamp((t - s(29) + 0.2) / 0.6) * (1 - clamp((t - s(31)) / 0.5)) : 0;
    const stitches = t >= s(33) && t < s(42) ? clamp((t - s(34)) / 2) : 0;
    const hollow = t >= s(39) && t < s(40) ? 1 : 0;
    const crackGold = clamp((t - this.sec.outro!.a - 1) / 6);
    const blink = (() => { const ph = (t + 0.3) % 4.7; return ph < 0.12 ? Math.sin(ph / 0.12 * Math.PI) : 0; })();
    return { lips, fire, crack, heart, crown, stitches, hollow, crackGold, blink };
  }

  // ------------------------------------------------------------ 镜头
  /** 关键句的特写：镜头推到人偶的脸 / 胸口（按第几句；前后 0.4 秒推进推出）。 */
  private closeUp(t: number, base: Cam, pose: Pose): Cam {
    const CU: [number, 'face' | 'chest' | 'upper', number][] = [
      [9, 'face', 2.3], [10, 'face', 2.6], [11, 'chest', 2.0], [12, 'chest', 2.2], [22, 'face', 2.4],
      [27, 'upper', 1.7], [36, 'chest', 2.0], [39, 'face', 2.6], [46, 'upper', 1.7], [69, 'upper', 1.5], [71, 'upper', 1.7],
    ];
    const r = rig(pose);
    let out = base;
    for (const [k, what, z] of CU) {
      const a = this.s(k) - 0.25, b = this.e(k) + 0.1;
      const u = ease.inOutCubic(clamp((t - a) / 0.4)) * (1 - ease.inOutCubic(clamp((t - b) / 0.4)));
      if (u <= 0) continue;
      const q = what === 'face' ? r.headC : what === 'chest' ? { x: lerp(r.neck.x, r.hip.x, 0.42), y: lerp(r.neck.y, r.hip.y, 0.42) } : { x: r.neck.x + 60, y: r.neck.y - 10 };
      const target: Cam = { x: q.x - W / 2, y: q.y - H / 2, z, rot: 0 };
      out = { x: lerp(out.x, target.x, u), y: lerp(out.y, target.y, u), z: lerp(out.z, target.z, u), rot: lerp(out.rot, 0, u) };
    }
    return out;
  }

  private cam(f: Frame): Cam {
    const t = f.t, sec = this.inSec(t);
    const lt = t - sec.a, dur = sec.b - sec.a, u = clamp(lt / dur);
    let cam: Cam = { ...CAM0 };
    const chorus = sec.name.startsWith('ch');
    if (sec.name === 'intro') cam = { x: 0, y: 40 * (1 - u), z: 1.18 - 0.18 * ease.inOutCubic(u), rot: 0 };
    else if (sec.name === 'v1' || sec.name === 'v1b' || sec.name === 'v2') cam = { x: Math.sin(t * 0.13) * 50, y: -60 + Math.sin(t * 0.09) * 15, z: 1.12 + 0.14 * ease.inOutQuad(u), rot: Math.sin(t * 0.07) * 0.01 };
    else if (chorus) {
      // 每小节换一次景：远 / 近 / 偏左 / 偏右
      const bar = Math.floor(f.bar), k = ((bar % 4) + 4) % 4;
      const shots: Cam[] = [{ x: 0, y: 0, z: 1.0, rot: 0 }, { x: 0, y: -150, z: 1.42, rot: 0 }, { x: -170, y: -60, z: 1.2, rot: -0.02 }, { x: 170, y: -60, z: 1.2, rot: 0.02 }];
      const prev = shots[(k + 3) % 4]!, cur = shots[k]!, v = ease.outCubic(clamp(f.barPhase / 0.12));
      cam = { x: lerp(prev.x, cur.x, v), y: lerp(prev.y, cur.y, v), z: lerp(prev.z, cur.z, v), rot: lerp(prev.rot, cur.rot, v) };
    } else if (sec.name === 'inst') cam = { x: Math.sin(lt * 0.4) * 80, y: -40, z: 1.05 + 0.25 * smoothstep(0.3, 1, u), rot: Math.sin(lt * 0.5) * 0.02 * u };
    else if (sec.name === 'br') cam = { x: -60 + 120 * u, y: -10, z: 1.0 + 0.06 * u, rot: 0 };
    else if (sec.name === 'outro') cam = { x: 0, y: -60 * ease.inOutCubic(u), z: 1.25 - 0.2 * ease.inOutCubic(u), rot: 0 };
    return cam;
  }

  // ------------------------------------------------------------ 画
  render(f: Frame, out: THREE.WebGLRenderTarget) {
    const { renderer, comp } = this.ctx;
    const t = f.t, sec = this.inSec(t), s = (k: number) => this.s(k), e = (k: number) => this.e(k);
    const c = this.base.ctx, cg = this.glow.ctx;
    this.base.clear(PAL.ink); this.glow.clear();
    const { pose, sway } = this.dollPose(f);
    const cam = this.closeUp(t, this.cam(f), pose);
    const look = this.look(t);
    const chorus = sec.name.startsWith('ch');

    // 停：三句「停止……」的定格 / 灭灯
    const stops = [32, 51, 76].map((k) => ({ k, a: s(k), b: e(k) }));
    const stopNow = stops.find((x) => t >= x.a - 0.05 && t < x.b + 0.25);
    const blackout = (stopNow && stopNow.k !== 76 ? clamp((t - stopNow.a - 0.2) / 0.08) : 0)
      || (sec.name === 'int1' ? 1 : 0)
      || (sec.name === 'inst' && t > sec.b - 0.6 ? 1 : 0);

    // 灯的颜色按段落
    const lightCol = sec.name === 'ch1' ? '255,200,170' : sec.name === 'v2' ? '200,190,255' : sec.name === 'ch2' ? '220,255,210' : sec.name === 'ch3' || sec.name === 'outro' ? '255,226,170' : '255,236,205';
    const spotA = sec.name === 'intro' ? smoothstep(s(1) - 0.6, s(1) - 0.3, t) : 1;

    // ---------- 背幕层
    layer(c, cam, BACK, () => {
      backdrop(c, t);
      // 裂缝：主歌一末尾开始在背幕上长；副歌那句撕开
      const opens: { k: number; img: number; seed: number; ci: number }[] = [{ k: 30, img: 0, seed: 11, ci: 0 }, { k: 49, img: 1, seed: 12, ci: 1 }, { k: 74, img: 2, seed: 13, ci: 2 }];
      for (const o of opens) {
        const grow = clamp((t - s(o.k - 8)) / 6);
        const until = o.k === 74 ? e(76) + 0.2 : o.k === 49 ? s(51) - 0.05 : e(o.k + 2);
        const open = t >= s(o.k) - 0.15 && t < until ? ease.outCubic(clamp((t - s(o.k) + 0.15) / 0.7)) * (1 - clamp((t - until + 0.5) / 0.5)) : 0;
        // 裂缝撕开以后就不画那道金线了（不然金线划过星尘的脸）
        if (t < s(o.k) + 0.3 && grow > 0 && t > s(o.k - 8)) drawCrack(c, cg, this.backCracks[o.ci]!, grow * 0.8, 4, 0.8 * (1 - clamp(open * 2)));
        if (open > 0) {
          if (o.img === 2) {
            revealArt(c, cg, null, 1160, 470, 940, 900, open, t, o.seed);
            const im = this.art[2];
            if (im) { // 立绘：透明底，站在裂缝里的光中
              const hh = 760, ww = hh * im.width / im.height;
              c.save(); c.globalAlpha = open; c.drawImage(im, 1160 - ww / 2, 470 - hh / 2 + 20 * (1 - open), ww, hh); c.restore();
            }
          } else revealArt(c, cg, this.art[o.img] ?? null, 1170, 440, 1060, 760, open, t, o.seed);
        }
      }
      // 墙上的影子（主歌一 7–8 句以后出现；副歌长角、抱住；尾声回到脚下）
      const shA = clamp((t - s(7)) / 1.2) * (t < this.sec.inst!.a ? 1 : t >= s(67) ? 1 : 0.0) * (1 - clamp((t - this.sec.outro!.a - 4) / 3)) * (1 - this.revealAmt(t));
      if (shA > 0 && !(t >= s(70) && t < s(71))) {
        const hug = (t >= s(25) && t < s(27)) || (t >= s(75) && t < s(76) + 0.4);
        const sp: Pose = hug ? { ...pose, x: pose.x + 40, y: pose.y + 10, s: pose.s * 1.45, aL: [-1.0, -1.7], aR: [1.0, 1.7], lean: 0.1, hang: 0 }
          : { ...pose, x: pose.x + 330 + Math.sin(t * 0.3) * 20, y: pose.y + 40, s: pose.s * 1.35, head: -pose.head * 0.6 + (t >= s(16) && t < s(18) ? Math.sin(t * 40) * 0.05 : 0) };
        const reach = t >= s(14) && t < s(16) ? { aL: [-1.5, -0.15] as [number, number] } : {};
        c.save(); c.globalAlpha = 0.82 * shA;
        doll(c, null, { ...sp, ...reach }, { shadow: true, shadowCol: '#050307', horns: chorus && sec.name !== 'ch3' ? clamp((t - s(25)) / 0.8) * (t < s(27) + 1 ? 1 : 0.6) : 0 }, t);
        c.restore();
      }
    });

    // ---------- 地板 + 舞台上的东西
    layer(c, cam, 1.08, () => { floor(c); });

    layer(c, cam, 1, () => {
      // 光柱打在人偶身上
      spot(cg, 960 + Math.sin(t * 0.3) * 30, -120, pose.x, 820, chorus ? 300 : 250, (1 - blackout) * spotA, lightCol);
      if (chorus) { spot(cg, 260, -80, 760, 840, 120, 0.32 * (1 - blackout), '255,120,110'); spot(cg, 1660, -80, 1160, 840, 120, 0.32 * (1 - blackout), sec.name === 'ch2' ? '120,255,170' : '190,150,255'); }
      dust(cg, t, 960, -60, pose.x, 800, 240, 80, (1 - blackout) * spotA, 7);

      // 纯音乐：布景片倒下
      if (sec.name === 'inst') {
        const lt = t - sec.a;
        for (let i = 0; i < 6; i++) {
          const fall = ease.inCubic(clamp((lt - 0.4 - i * 0.5) / 0.7));
          const bx = 150 + i * 300 + (i % 2 ? 40 : -40);
          c.save(); c.translate(bx, 780); c.rotate((i % 2 ? 1 : -1) * fall * 1.45);
          c.fillStyle = i % 2 ? '#241a2e' : '#1d1526'; c.fillRect(-90, -420, 180, 420);
          c.strokeStyle = 'rgba(242,195,90,0.3)'; c.lineWidth = 3; c.strokeRect(-90, -420, 180, 420);
          c.restore();
        }
        // 八音盒转台 → 星尘旋涡（越转越快）→ 最后两秒收进人偶 → 最后一拍全黑
        const lt2 = lt - 4.5, D = sec.b - sec.a;
        if (lt2 > 0) {
          const build = clamp((lt2 - 6) / Math.max(1, D - 4.5 - 8.5)), end = clamp((t - (sec.b - 2.4)) / 1.8);
          c.save(); c.fillStyle = '#2a1f17'; c.beginPath(); c.ellipse(pose.x, 806, 160, 34, 0, 0, TAU); c.fill();
          c.strokeStyle = PAL.gold; c.lineWidth = 3; c.stroke(); c.restore();
          this.spiral(cg, t, pose.x, 560, (160 + 420 * build) * (1 - 0.85 * ease.inCubic(end)), Math.round(90 + 330 * clamp(lt2 / 8)), 1 - 0.5 * end, 0.35 + 1.8 * build + 3 * end);
          stardust(cg, t, pose.x, 600, 520 * (1 - 0.7 * end), Math.round(80 + 160 * clamp(lt2 / 20)), clamp(lt2 / 3) * (1 - end), 21, -Math.PI / 2);
          // 跟强拍：背幕一下一下换颜色发亮（深红 / 紫 / 金）
          if (lt2 > 6) {
            const bp = Math.pow(1 - f.barPhase, 3) * clamp((lt2 - 6) / 2) * (1 - end);
            const colr = ['255,90,110', '170,130,255', '255,214,120'][((Math.floor(f.bar) % 3) + 3) % 3]!;
            const g = cg.createRadialGradient(960, 420, 40, 960, 420, 900);
            g.addColorStop(0, `rgba(${colr},${0.16 * bp})`); g.addColorStop(1, `rgba(${colr},0)`);
            cg.fillStyle = g; cg.fillRect(0, -200, W, H + 400);
          }
        }
      }
      // 1:17 那几秒黑场：八音盒的发条钥匙转一下、闪一下
      if (sec.name === 'int1') {
        const lt = t - sec.a, k = Math.pow(1 - clamp(lt / 0.6), 2);
        c.save(); c.translate(960, 560); c.rotate(lt * 2.2); c.strokeStyle = 'rgba(242,195,90,0.55)'; c.lineWidth = 6;
        c.beginPath(); c.arc(-22, 0, 16, 0, TAU); c.arc(22, 0, 16, 0, TAU); c.moveTo(0, 0); c.lineTo(0, 60); c.stroke(); c.restore();
        cg.save(); cg.fillStyle = `rgba(255,226,150,${0.35 + 0.65 * k})`; star4(cg, 960, 560, 26 + 40 * k); cg.restore();
      }

      // 提线 + 线上的东西（泪 / 胶片 / 五线谱）
      const bx = pose.x + sway * 40, by = 90 - (1 - pose.hang) * 30;
      const cut = t >= s(76) ? clamp((t - s(76) - 0.15) / 1.6) : 0;
      const free = sec.name === 'outro' || sec.name === 'inst' && t - sec.a > 4.5;
      const strA = (free ? 0 : 1) * (sec.name === 'br' ? 0.55 : 1);
      if (!(t >= s(70) && t < s(71))) strings(c, cg, pose, bx, by, sway, strA, cut);
      if (sec.name === 'outro') strings(c, cg, pose, bx, by - 40, sway, clamp(1 - (t - sec.a) / 2.5), 1);
      // 线上挂的
      const lines: [{ x: number; y: number }, { x: number; y: number }][] = [[{ x: bx - 170, y: by }, { x: pose.x - 250, y: 900 }], [{ x: bx + 170, y: by }, { x: pose.x + 260, y: 900 }], [{ x: bx - 60, y: by }, { x: pose.x - 520, y: 1000 }], [{ x: bx + 60, y: by }, { x: pose.x + 540, y: 1000 }]];
      if (sec.name === 'ch1') {
        const wrapA = clamp((t - s(23)) / 1.0) * (1 - this.revealAmt(t));
        lines.slice(0, 2).forEach(([a, b], i) => {
          c.save(); c.globalAlpha = wrapA; c.strokeStyle = PAL.gold; c.lineWidth = 1.4; c.beginPath(); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y); c.stroke(); c.restore();
          tearsOnLine(c, cg, a, b, t, 3, 50 + i, wrapA);
        });
      }
      if (sec.name === 'ch2' && this.revealAmt(t) < 0.5) lines.slice(0, 2).forEach(([a, b], i) => { c.save(); c.strokeStyle = PAL.gold; c.lineWidth = 1.4; c.beginPath(); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y); c.stroke(); c.restore(); filmOnLine(c, cg, a, b, t, 3, 60 + i, clamp((t - s(42)) / 1.0)); });
      if (sec.name === 'ch3' && t < s(76)) lines.slice(0, 2).forEach(([a, b]) => staffLines(c, cg, a, b, t, clamp((t - s(67)) / 1.0)));

      // 主歌二：齿轮、面具、玻璃泡
      if (sec.name === 'v2') {
        const a = clamp((t - s(35)) / 0.5) * (1 - clamp((t - s(37)) / 0.5));
        if (a > 0) { c.save(); c.globalAlpha = a; gear(c, 560, 640, 70, t * 1.2); gear(c, 470, 560, 46, -t * 1.8, 8); gear(c, 1380, 620, 60, -t, 9); c.restore(); }
        const ma = clamp((t - s(40)) / 0.5) * (1 - clamp((t - s(41)) / 0.5));
        if (ma > 0) for (let i = 0; i < 6; i++) { const mx = [300, 470, 640, 1280, 1450, 1620][i]!, my = 470 + (i % 3) * 50 + Math.sin(t * 1.3 + i) * 12; c.save(); c.globalAlpha = ma; c.strokeStyle = PAL.gold; c.beginPath(); c.moveTo(mx, 80); c.lineTo(mx, my - 60); c.stroke(); c.restore(); c.save(); c.globalAlpha = ma; mask(c, cg, mx, my, 0.75, i % 2 === 1, Math.sin(t + i) * 0.2); c.restore(); }
        const ga = clamp((t - s(41)) / 0.4) * (1 - clamp((t - s(42) + 0.2) / 0.3));
        if (ga > 0) glassBubble(c, cg, 1380, 380, 120, t, ga);
      }
      // 副歌：毒药、皇冠道具、孔雀羽、雨伞、狂欢者、笑脸撕裂
      const poisonK = [27, 46, 71].find((k) => t >= s(k) - 0.2 && t < e(k + 1) + 0.3);
      if (poisonK) { const u = clamp((t - s(poisonK)) / 0.5); poison(c, cg, pose.x + 130, 420 - 60 * u, 1.1, -0.6 * clamp((t - s(poisonK + 1)) / 0.4), u * (1 - clamp((t - e(poisonK + 1)) / 0.3))); }
      if (sec.name === 'ch2') {
        const ra = clamp((t - s(44)) / 0.4) * (1 - clamp((t - s(46)) / 0.4));
        if (ra > 0) { c.save(); c.globalAlpha = ra; for (let i = 0; i < 6; i++) reveler(c, cg, [250, 470, 690, 1230, 1450, 1670][i]!, 860, 2.0, t, i, clamp((t - s(44) - 1.0) / 0.6)); c.restore(); }
        const ta = clamp((t - s(45)) / 0.3) * (1 - clamp((t - s(46)) / 0.3));
        if (ta > 0) { c.save(); c.globalAlpha = ta; mask(c, cg, 1440, 400, 1.6, true, 0.08, clamp((t - s(45) - 0.4) / 0.8)); c.restore(); }
        const fa = clamp((t - s(48)) / 0.4) * (1 - clamp((t - s(49) - 0.2) / 0.4));
        if (fa > 0) { c.save(); c.globalAlpha = fa; peacockFan(c, cg, pose.x, 520, 0.95, clamp((t - s(48)) / 0.7), clamp((t - s(48) - 0.6) / 0.8), t); c.restore(); }
      }
      if (sec.name === 'ch3') {
        const ua = clamp((t - s(73)) / 0.3) * (1 - clamp((t - s(74)) / 0.3));
        if (ua > 0) umbrella(c, cg, pose.x + 120, 330, 0.9, clamp((t - s(73)) / 0.5), clamp((t - s(73) - 0.5) / 1.0), 0.15);
        const la = clamp((t - s(69) - 1.0) / 0.3) * (1 - clamp((t - s(70)) / 0.3));
        if (la > 0) { c.save(); c.globalAlpha = la; mask(c, cg, 1420, 360, 1.3, true, Math.sin(t * 14) * 0.12); c.restore(); }
      }
      // 停止祷告：合十的手裂开
      const ph = t >= s(32) - 0.3 && t < e(32) + 0.3 ? 1 : 0;
      if (ph) prayingHands(c, cg, 960, 300, 1.1, clamp((t - s(32) - 0.15) / 0.5), 1 - clamp((t - e(32)) / 0.3));
      // 停止创造：羽毛笔折断
      if (t >= s(51) - 0.2 && t < e(51) + 0.3) {
        const br = clamp((t - s(51) - 0.1) / 0.3);
        c.save(); c.translate(960, 330); c.rotate(-0.3 - br * 0.6); c.fillStyle = PAL.bone; c.fillRect(-6, -200, 12, 200 - 30 * br); c.restore();
        c.save(); c.translate(960 + 60 * br, 330 + 120 * br); c.rotate(0.4 + br * 1.2); c.fillStyle = PAL.bone; c.fillRect(-6, 0, 12, 120); c.restore();
      }

      // 桥段：写满字的大纸、手、港口……（画在人偶后面；人偶站在纸的右边）
      if (sec.name === 'br') this.bridge(c, cg, f);
      // 第三段副歌第 75–76 句：裂缝里的光把人偶整个包住
      if (t >= s(75) - 0.2 && t < s(76) + 0.2) {
        const wa = clamp((t - s(75) + 0.2) / 0.6) * (1 - clamp((t - s(76)) / 0.2));
        const g = cg.createRadialGradient(pose.x, pose.y - 120, 20, pose.x, pose.y - 120, 360);
        g.addColorStop(0, `rgba(255,226,170,${0.22 * wa})`); g.addColorStop(1, 'rgba(255,226,170,0)');
        cg.fillStyle = g; cg.fillRect(pose.x - 400, pose.y - 520, 800, 800);
      }
      // 人偶本人
      c.save(); c.globalAlpha = 1 - blackout * 0.85;
      doll(c, cg, pose, look, t);
      c.restore();
      // 华尔兹：影子从墙上下来当舞伴
      if (t >= s(70) && t < s(71)) {
        const ph2 = Math.sin((t - s(70)) * TAU / (60 / this.ctx.audio.bpm * 3));
        const partner: Pose = { ...mixPose(DANCE_B, DANCE_A, 0.5 + 0.5 * ph2), x: 1060 - 60 * ph2, s: 1.05 };
        doll(c, null, partner, { shadow: true, shadowCol: '#0a0710' }, t);
        for (let i = 0; i < 26; i++) { const fx = 300 + hash(i, 5) * 1320 + Math.sin(t + i) * 30, fy = 200 + hash(i, 6) * 600 + Math.cos(t * 0.7 + i) * 20; cg.fillStyle = `rgba(255,236,150,${0.5 + 0.5 * Math.sin(t * 3 + i)})`; cg.beginPath(); cg.arc(fx, fy, 3, 0, TAU); cg.fill(); }
      }
    });

    // ---------- 前景大幕（开场拉开；尾声合上一半）
    layer(c, cam, FRONT, () => {
      const open = sec.name === 'intro' ? ease.inOutCubic(clamp((t - s(1) + 0.2) / 3.5)) : sec.name === 'outro' ? 1 - 0.35 * ease.inOutCubic(clamp((t - sec.b + 8) / 6)) : 1;
      curtains(c, t, open, chorus ? 0.6 : 0.2);
    });

    // ---------- 开场的「由」、尾声的金缮「由」和片尾字
    if (sec.name === 'intro') this.titleGlyph(c, cg, t, clamp((t - 0.5) / 2.0), 1 - clamp((t - s(1) - 1.4) / 0.8));
    if (sec.name === 'outro') {
      const lt = t - sec.a;
      this.titleGlyph(c, cg, t, clamp((lt - 6) / 5), 1, 520, 300);
      const ca = clamp((lt - 12) / 1.5) * (1 - clamp((t - sec.b + 1.2) / 1.0));
      if (ca > 0 && this.credits.length) {
        // 片尾字：右边一列（不压在地上的光斑里）
        c.save(); c.globalAlpha = ca; c.font = font(FAM, 46); c.textAlign = 'left'; c.textBaseline = 'middle';
        this.credits.forEach((line, i) => { c.fillStyle = 'rgba(0,0,0,0.6)'; c.fillText(line, 1323, 563 + i * 70); c.fillStyle = PAL.bone; c.fillText(line, 1320, 560 + i * 70); });
        c.restore();
        cg.save(); cg.globalAlpha = 0.25 * ca; cg.fillStyle = PAL.gold; cg.fillRect(1300, 520, 3, 70 * this.credits.length); cg.restore();
      }
    }

    // ---------- 歌词
    this.lyrics(c, cg, f, pose, blackout);

    comp.draw(renderer, this.base.upload(), out, { mode: 'replace' as any, opacity: 1 });
    comp.draw(renderer, this.glow.upload(), out, { mode: 'add', opacity: GLOW });

    // 后期
    const stopFlash = stops.reduce((m, x) => Math.max(m, t >= x.a && t < x.a + 0.4 ? 1 - (t - x.a) / 0.4 : 0), 0);
    const tearOpen = [30, 49, 74].reduce((m, k) => Math.max(m, t >= s(k) - 0.1 && t < s(k) + 0.5 ? 1 - (t - s(k) + 0.1) / 0.6 : 0), 0);
    const fadeIn = 1 - smoothstep(0, 1.2, t);
    const fadeOut = smoothstep(this.ctx.audio.duration - 2.5, this.ctx.audio.duration - 0.2, t);
    return {
      bloom: 0.7, bloomThreshold: 1.0, bloomKnee: 0.6, bloomRadius: 0.8, halation: 0.2, ca: chorus ? 1.4 : 0.8,
      grain: 0.05, vignette: 0.45, zoom: 1 + 0.006 * f.a.kick * (chorus ? 1.6 : 1),
      flash: 0.55 * stopFlash + 0.45 * tearOpen, fade: Math.max(fadeIn, fadeOut),
      shake: (stopNow ? [Math.sin(t * 90) * 6 * clamp(1 - (t - stopNow.a) / 0.3), Math.cos(t * 80) * 4 * clamp(1 - (t - stopNow.a) / 0.3)] : [0, 0]) as [number, number],
    };
  }

  /** 星尘旋涡：三条旋臂的光点绕 (cx,cy) 转，speed 越大转得越快。 */
  private spiral(cg: C2, t: number, cx: number, cy: number, R: number, n: number, a: number, speed: number) {
    if (a <= 0 || R <= 1) return;
    cg.save();
    for (let i = 0; i < n; i++) {
      const arm = i % 3, rr = R * Math.sqrt(hash(i, 71));
      const ang = arm * TAU / 3 + rr * 0.011 + t * speed * (1.2 - rr / (R * 1.4)) + (hash(i, 72) - 0.5) * 0.5;
      const x = cx + Math.cos(ang) * rr, y = cy + Math.sin(ang) * rr * 0.42;
      const tw = 0.5 + 0.5 * Math.sin(t * 4 + i);
      const k = hash(i, 73);
      cg.fillStyle = `rgba(${k < 0.4 ? '255,226,150' : k < 0.75 ? '205,180,255' : '255,255,255'},${(0.35 + 0.65 * tw) * a})`;
      if (hash(i, 74) > 0.9) star4(cg, x, y, 5 + 4 * tw); else { cg.beginPath(); cg.arc(x, y, 1.5 + 2 * hash(i, 75), 0, TAU); cg.fill(); }
    }
    cg.restore();
  }

  /** 金线写的「由」：p 0..1 金线从上往下描出来。 */
  private titleGlyph(c: C2, cg: C2, t: number, p: number, a: number, size = 380, y = 470) {
    if (p <= 0 || a <= 0) return;
    const ch = String.fromCharCode(0x7531);
    for (const [cc, lw, alpha] of [[c, 3, 1], [cg, 5, 0.85]] as const) {
      cc.save(); cc.globalAlpha = a * alpha; cc.font = font(FAM, size); cc.textAlign = 'center'; cc.textBaseline = 'middle';
      cc.beginPath(); cc.rect(0, y - size * 0.6, W, size * 1.2 * clamp(p)); cc.clip();
      cc.strokeStyle = PAL.gold; cc.lineWidth = lw; cc.lineJoin = 'round'; cc.strokeText(ch, W / 2, y);
      cc.restore();
    }
  }

  private bridge(c: C2, cg: C2, f: Frame) {
    const t = f.t, s = (k: number) => this.s(k), e = (k: number) => this.e(k);
    // 背景纸：桥段整段是一张被写满的大纸（左边；人偶站在右边）
    const pa = clamp((t - this.sec.br!.a) / 0.6) * (1 - clamp((t - this.sec.br!.b + 0.4) / 0.4));
    const PX0 = 110, PX1 = 1250, PY0 = 110, PY1 = 700;
    c.save(); c.globalAlpha = 0.92 * pa; c.fillStyle = '#1b1520'; c.fillRect(PX0, PY0, PX1 - PX0, PY1 - PY0);
    c.strokeStyle = 'rgba(242,195,90,0.35)'; c.lineWidth = 3; c.strokeRect(PX0, PY0, PX1 - PX0, PY1 - PY0);
    c.strokeStyle = 'rgba(242,195,90,0.08)'; c.lineWidth = 1; for (let y = PY0 + 60; y < PY1; y += 60) { c.beginPath(); c.moveTo(PX0 + 30, y); c.lineTo(PX1 - 30, y); c.stroke(); }
    c.restore();
    // 当前在写哪一句；写好的往上推、变淡（像一页往上卷）
    let k = 52;
    for (let i = 52; i <= 66; i++) if (t >= s(i) - 0.1) k = i;
    const roll = ease.outCubic(clamp((t - s(k) + 0.1) / 0.35));
    c.save(); c.beginPath(); c.rect(PX0, PY0, PX1 - PX0, PY1 - PY0); c.clip();
    cg.save(); cg.beginPath(); cg.rect(PX0, PY0, PX1 - PX0, PY1 - PY0); cg.clip();
    for (let j = 0; j <= 3; j++) {
      const i = k - j;
      if (i < 52) break;
      const y = 560 - (j - 1 + roll) * 120;
      const fade = j === 0 ? 1 : j === 1 ? 0.45 : j === 2 ? 0.22 : 0.1 * (1 - roll);
      const size = [...this.L(i).text].length > 11 ? 54 : 64;
      const tip = lyricWrite(c, cg, this.L(i), t, 680, y, size, pa * fade);
      if (j === 0 && tip) quillHand(c, cg, tip.x, tip.y, 0.8, pa, t);
    }
    c.restore(); cg.restore();
    // 56 撒网、58 港口、62 巨掌、64 门、65 城市、66 玫瑰
    if (t >= s(56) && t < s(57) + 0.5) net(c, cg, 960, clamp((t - s(56)) / 0.8), 1 - clamp((t - s(57)) / 0.5));
    if (t >= s(58) - 0.2 && t < s(60)) inkHarbor(c, cg, 700, 770, clamp((t - s(58) + 0.2) / 1.6), t, 1 - clamp((t - s(59) - 0.6) / 0.6));
    if (t >= s(62) && t < e(62) + 0.4) {
      const u = ease.outCubic(clamp((t - s(62)) / 0.5)), aa = 1 - clamp((t - e(62)) / 0.4);
      c.save(); c.globalAlpha = aa; c.fillStyle = '#060409'; c.translate(960, -620 + 560 * u);
      c.beginPath(); c.ellipse(0, 0, 520, 420, 0, 0, TAU); c.fill();
      for (let i = 0; i < 5; i++) { c.save(); c.rotate(-0.9 + i * 0.45); c.beginPath(); c.ellipse(0, 380, 70, 200, 0, 0, TAU); c.fill(); c.restore(); }
      c.restore();
    }
    const knock = [0, 1, 2].reduce((m, i) => { const tk = this.ctx.audio.beats.find((b) => b >= s(64)) ?? s(64); const x = tk + i * 60 / this.ctx.audio.bpm; return Math.max(m, t >= x && t < x + 0.25 ? 1 - (t - x) / 0.25 : 0); }, 0);
    if (t >= s(64) - 0.2 && t < s(65) + 0.2) inkDoor(c, cg, 960, 760, clamp((t - s(64) + 0.2) / 0.5), knock, 1 - clamp((t - s(65)) / 0.2));
    if (t >= s(65) - 0.1) popCity(c, cg, 900, 790, clamp((t - s(65) + 0.1) / 1.2), t, 1);
    if (t >= s(66) - 0.1) for (let i = 0; i < 9; i++) rose(c, 190 + i * 195 + (i % 2) * 40, 860 + (i % 3) * 50, 62 + 18 * hash(i, 3), clamp((t - s(66) - i * 0.05) / 0.5), i);
    // 59–60 登场：一道追光
    if (t >= s(59) && t < s(61)) spot(cg, 1460, -100, 1460, 820, 180, clamp((t - s(59)) / 0.2) * (1 - clamp((t - s(61) + 0.3) / 0.3)), '255,240,200');
  }

  private lyrics(c: C2, cg: C2, f: Frame, pose: Pose, blackout: number) {
    const t = f.t, Ls = this.ctx.lyrics.lines;
    for (let n = 1; n <= Ls.length; n++) {
      const l = Ls[n - 1]!;
      const a0 = l.start - 0.35, a1 = l.end + (n === 31 || n === 50 || n === 75 ? 0.2 : 0.45);
      if (t < a0 || t > a1) continue;
      const a = clamp((t - a0) / 0.3) * (1 - clamp((t - (a1 - 0.3)) / 0.3));
      if (n >= 52 && n <= 66) continue;                 // 桥段由那只手写
      if (n === 32 || n === 51 || n === 76) { lyricStamp(c, cg, l, t, 960, 900, 150, a); continue; }
      if (n <= 3) { lyricLine(c, cg, l, t, 960, 900, 46, a * 0.85, { dim: 'rgba(239,230,216,0.25)', glow: 0.4 }); continue; }
      const sec = this.inSec(l.start).name;
      const len = [...l.text].length;
      if (sec === 'v1' || sec === 'v2') {
        if (len >= 5) lyricTags(c, cg, l, t, 960, 230, 62, 1.25, a);
        else lyricLine(c, cg, l, t, pose.x + 430, 470, 84, a, { rot: -0.04 });
      } else if (sec === 'v1b') {
        lyricLine(c, cg, l, t, 960, 950, 80, a);
      } else {
        // 副歌：大字投在一边（单数句左、双数句右），不压人偶的脸
        const left = n % 2 === 1;
        const x = left ? 430 : 1490;
        lyricLine(c, cg, l, t, x, n % 4 < 2 ? 330 : 520, len >= 7 ? 64 : 82, a * (1 - blackout * 0.6), { rot: left ? -0.03 : 0.03 });
      }
    }
  }
}

// 星光小装饰（给片尾用）
export function sparkleRow(cg: C2, t: number, y: number) { for (let i = 0; i < 9; i++) { cg.fillStyle = `rgba(255,226,150,${0.5 + 0.5 * Math.sin(t * 2 + i)})`; star4(cg, 560 + i * 100, y, 6); } }
