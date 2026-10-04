// 《逃跑的天使》手账 MV（SV-Agent 10-03）：一句歌词一格画面，换格在那句开始唱之前 0.35 秒（平移 / 翻页 / 推近）。
// 格的内容在 angel/panels-*.ts；画画工具在 angel/kit.ts。只由歌曲时间决定，没有状态。
import type * as THREE from 'three';
import { Scene, type Frame } from '../engine/scene';
import { Layer2D, W, H } from '../engine/gl';
import { clamp, ease, TAU } from '../engine/util';
import { COL, lyric, page, rr, setKick, sparkle, text } from './angel/kit';
import type { Panel, PD } from './angel/types';
import { PANELS_A } from './angel/panels-a';
import { PANELS_B } from './angel/panels-b';
import { PANELS_C } from './angel/panels-c';

const TR = 0.35;
const COVER = new URLSearchParams(location.search).get('cover') === '1';

export default class Journal extends Scene {
  layer = new Layer2D();
  panels: Panel[] = [];
  t0: number[] = [];

  init() {
    const L = this.ctx.lyrics.lines;
    this.panels = [...PANELS_A, ...PANELS_B, ...PANELS_C];
    if (this.panels.length !== L.length + 2) throw new Error(`格数 ${this.panels.length} ≠ 歌词 ${L.length} 句 + 2`);
    this.t0 = [0, ...L.map((l) => l.start), L[L.length - 1]!.end + 0.5];
  }

  private dur(k: number) {
    return (this.t0[k + 1] ?? this.ctx.audio.duration) - this.t0[k]!;
  }

  private drawPanel(c: CanvasRenderingContext2D, k: number, f: Frame) {
    const P = this.panels[k]!;
    const L = this.ctx.lyrics.lines;
    const l = k >= 1 && k <= L.length ? L[k - 1]! : null;
    const t = f.t, dur = this.dur(k), lt = t - this.t0[k]!;
    const d: PD = { c, t, lt, p: clamp(lt / dur), dur, l, k: f.a.kick, beat: f.beat, bar: f.bar, f, i: k };
    // 镜头缓推：每格慢慢推近 3.5%、往一个方向漂一点（歌词纸条不动）
    const u = ease.inOutQuad(clamp(lt / Math.max(dur, 0.5)));
    const zk = 1.0 + 0.035 * u, ang = k * 2.39996;
    c.save();
    c.translate(W / 2 + Math.cos(ang) * 16 * u, H / 2 + Math.sin(ang) * 10 * u); c.scale(zk, zk); c.translate(-W / 2, -H / 2);
    page(c, W, H, P.bg ?? 'paper', t);
    c.save();
    P.draw(d);
    c.restore();
    if (k >= 1 && k <= L.length && !COVER) this.header(c, k, P.bg === 'night');
    c.restore();
    if (l && P.text !== null && !COVER) {
      const dark = P.bg === 'night' ? { color: '#FFFDF8', dim: 'rgba(255,253,248,0.22)', plate: 'rgba(30,34,56,0.62)', shadow: 'rgba(0,0,0,0.35)' } : {};
      lyric(c, l, t, { ...dark, ...(P.text ?? {}) });
    }
  }

  render(f: Frame, out: THREE.WebGLRenderTarget) {
    const { renderer, comp } = this.ctx;
    const t = f.t;
    setKick(f.a.kick);
    let k = 0;
    for (let i = 1; i < this.panels.length; i++) if (t >= this.t0[i]! - (this.panels[i]!.tr === 'cut' ? 0 : TR)) k = i;
    const L = this.layer, c = L.ctx;
    L.clear();
    const P = this.panels[k]!;
    const into = this.t0[k]! - t; // > 0：还在转场里
    if (k > 0 && into > 0 && P.tr !== 'cut') {
      const u = ease.inOutCubic(clamp(1 - into / TR));
      const kind = P.tr ?? 'pan';
      c.save();
      if (kind === 'pan') c.translate(-W * u, 0);
      else if (kind === 'up') c.translate(0, -H * 0.35 * u);
      else if (kind === 'down') c.translate(0, H * 0.35 * u);
      else if (kind === 'zoom') { c.translate(W / 2, H / 2); c.scale(1 + 0.25 * u, 1 + 0.25 * u); c.translate(-W / 2, -H / 2); }
      this.drawPanel(c, k - 1, f);
      c.restore();
      c.save();
      if (kind === 'pan') c.translate(W * (1 - u), 0);
      else if (kind === 'up') c.translate(0, H * (1 - u));
      else if (kind === 'down') c.translate(0, -H * (1 - u));
      else if (kind === 'zoom') { c.globalAlpha = u; c.translate(W / 2, H / 2); c.scale(0.85 + 0.15 * u, 0.85 + 0.15 * u); c.translate(-W / 2, -H / 2); }
      this.drawPanel(c, k, f);
      c.restore();
      // 新的一页压在旧的上面：页边一道阴影
      if (kind === 'pan' || kind === 'up' || kind === 'down') {
        const e = kind === 'pan' ? W * (1 - u) : kind === 'up' ? H * (1 - u) : H * u;
        const g = kind === 'pan' ? c.createLinearGradient(e - 50, 0, e, 0) : kind === 'up' ? c.createLinearGradient(0, e - 50, 0, e) : c.createLinearGradient(0, e + 50, 0, e);
        g.addColorStop(0, 'rgba(58,51,64,0)'); g.addColorStop(1, 'rgba(58,51,64,0.22)');
        c.fillStyle = g;
        if (kind === 'pan') c.fillRect(e - 50, 0, 50, H); else if (kind === 'up') c.fillRect(0, e - 50, W, 50); else c.fillRect(0, e, W, 50);
      }
      this.spark(c, kind, u);
    } else {
      this.drawPanel(c, k, f);
    }
    if (COVER && new URLSearchParams(location.search).get('title') !== '0') {
      // 封面：左上一块纸，大标题 + 原曲
      c.save(); c.translate(1228, 84); c.rotate(0.03);
      rr(c, 0, 0, 650, 226, 24); c.fillStyle = 'rgba(255,253,248,0.94)'; c.fill();
      c.fillStyle = 'rgba(244,166,183,0.85)'; c.fillRect(-18, -14, 140, 38);
      text(c, '《逃跑的天使》', 325, 98, 88, COL.ink);
      text(c, '原曲 伊野奏', 325, 182, 36, COL.ink2);
      c.restore();
    }
    comp.draw(renderer, L.upload(), out, { mode: 'replace' as any, opacity: 1 });
    const base = { bloom: 0.18, bloomThreshold: 1.0, halation: 0, ca: 0, grain: 0.03, vignette: 0.12, zoom: 1 + 0.005 * f.a.kick };
    const Pk = this.panels[k]!;
    if (!Pk.post) return base;
    const Lk = this.ctx.lyrics.lines;
    const dur = this.dur(k), lt = t - this.t0[k]!;
    return { ...base, ...Pk.post({ c, t, lt, p: clamp(lt / dur), dur, l: k >= 1 && k <= Lk.length ? Lk[k - 1]! : null, k: f.a.kick, beat: f.beat, bar: f.bar, f, i: k }) };
  }

  /** 手账页眉：左上角一条纸胶带写篇章名，右上角页码。 */
  private header(c: CanvasRenderingContext2D, k: number, dark: boolean) {
    const name = k <= 18 ? '上学篇' : k <= 38 ? '上班篇' : '逃跑篇';
    const tape = k <= 18 ? 'rgba(244,166,183,0.8)' : k <= 38 ? 'rgba(156,203,234,0.8)' : 'rgba(242,181,68,0.8)';
    c.save(); c.translate(110, 70); c.rotate(-0.04);
    rr(c, -16, -26, 170, 52, 6); c.fillStyle = tape; c.fill();
    text(c, name, 69, 1, 32, dark ? '#FFFDF8' : COL.ink);
    c.restore();
    text(c, `· ${k} ·`, W - 110, 72, 30, dark ? 'rgba(255,253,248,0.7)' : 'rgba(58,51,64,0.55)');
  }

  /** 贯穿线索：换页时一颗金色光点拖着尾巴划过（顺着镜头走的方向）。 */
  private spark(c: CanvasRenderingContext2D, kind: string, u: number) {
    const pos = (v: number): [number, number] => {
      if (kind === 'up') return [W * 0.5 + Math.sin(v * Math.PI) * 160, H * 1.05 - v * H * 1.1];
      if (kind === 'down') return [W * 0.5 - Math.sin(v * Math.PI) * 160, -H * 0.05 + v * H * 1.1];
      if (kind === 'zoom') { const a = v * TAU * 0.9 - 1.2, r = 60 + v * 900; return [W / 2 + Math.cos(a) * r, H / 2 + Math.sin(a) * r * 0.6]; }
      return [W * 1.05 - v * W * 1.1, H * 0.4 - Math.sin(v * Math.PI) * 120];
    };
    c.save();
    for (let i = 14; i >= 0; i--) {
      const v = clamp(u - i * 0.022);
      if (v <= 0) continue;
      const [x, y] = pos(v);
      if (i === 0) { c.shadowColor = 'rgba(255,214,110,0.95)'; c.shadowBlur = 24; }
      sparkle(c, x, y, i === 0 ? 30 : 22 - i * 1.3, i === 0 ? '#FFE08A' : `rgba(242,181,68,${0.9 - i * 0.055})`);
      c.shadowBlur = 0;
    }
    c.restore();
  }
}
