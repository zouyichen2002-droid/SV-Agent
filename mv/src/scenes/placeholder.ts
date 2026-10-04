// 占位场景（SV-Agent 10-03）：验证底子能不能跑通 —— 不是给哪首歌的设计，正式场景照设计手册另写。
//   背景按段落换色调、底鼓一响亮一下；当前这句歌词按 SV 工程的逐字时间一个字一个字亮；
//   底下一排拍子点（强拍大一点）；左下角段落名、第几小节第几拍、时间。
import type * as THREE from 'three';
import { Scene, type Frame } from '../engine/scene';
import { FSPass, Layer2D, W, H } from '../engine/gl';
import { Lyrics, type Line } from '../engine/lyrics';
import { rgba } from '../engine/palette';
import { F, font, layout, fitSize } from '../engine/type';
import { clamp, smoothstep } from '../engine/util';

const TINTS = [0.0, 0.35, 0.7, 1.0, 0.5, 0.15]; // 每个段落一个色调（0 = 墨黑偏冷，1 = 偏橙）

export default class Placeholder extends Scene {
  bg = new FSPass(/* glsl */ `
    uniform float t, kick, tint;
    void main() {
      vec2 p = (vUv - 0.5) * vec2(${(W / H).toFixed(4)}, 1.0);
      float n = 0.5 + 0.5 * fbm(vec3(p * 2.2, t * 0.07), 4);
      vec3 warm = mix(C_INK2, C_BLOOD * 0.35, tint);
      vec3 base = mix(C_INK, warm, n);
      float vig = smoothstep(1.15, 0.15, length(p));
      vec3 col = base * vig + C_SIGNAL * kick * 0.10 * vig;
      fragColor = vec4(col, 1.0);
    }`, { t: { value: 0 }, kick: { value: 0 }, tint: { value: 0 } });
  text = new Layer2D();

  render(f: Frame, out: THREE.WebGLRenderTarget) {
    const { renderer, comp, lyrics, params } = this.ctx;
    this.bg.u.t!.value = f.t;
    this.bg.u.kick!.value = f.a.kick;
    this.bg.u.tint!.value = TINTS[(params.index ?? 0) % TINTS.length]!;
    this.bg.render(renderer, out);

    const L = this.text, c = L.ctx;
    L.clear();
    // 正在唱的那句；句子之间的空当显示刚唱完的那句（淡一点）
    const cur = lyrics.lineAt(f.t);
    const line = cur ?? lyrics.lastLine(f.t);
    if (line) this.drawLine(c, line, f.t, cur ? 1 : 0.35);
    this.drawBeat(c, f);
    comp.draw(renderer, L.upload(), out);
    return { bloom: 0.5 + 0.4 * f.a.rms, grain: 0.06 };
  }

  private drawLine(c: CanvasRenderingContext2D, line: Line, t: number, alpha: number) {
    const fam = F.kuaile();
    const size = Math.min(96, fitSize(line.text, fam, W - 240, 96));
    const lay = layout(line.text, fam, size);
    const x0 = (W - lay.width) / 2, y = H / 2 + size * 0.35;
    const sung = Lyrics.lineCharProgress(line, t);
    c.save();
    c.textBaseline = 'alphabetic';
    c.font = font(fam, size);
    lay.glyphs.forEach((g, i) => {
      const k = clamp(sung - i, 0, 1); // 这个字唱到哪了：0 没唱、1 唱完
      const pop = k > 0 && k < 1 ? 1 + 0.08 * Math.sin(Math.PI * k) : 1;
      c.save();
      c.translate(x0 + g.x + g.w / 2, y);
      c.scale(pop, pop);
      c.fillStyle = k > 0 ? rgba('bone', alpha * (0.55 + 0.45 * k)) : rgba('graphite', alpha * 0.9);
      c.fillText(g.ch, -g.w / 2, 0);
      c.restore();
    });
    c.restore();
  }

  private drawBeat(c: CanvasRenderingContext2D, f: Frame) {
    const beatInBar = Math.floor((f.bar - Math.floor(f.bar)) * 4 + 1e-6) % 4; // 4/4：小节里第几拍（0 = 强拍）
    for (let i = 0; i < 4; i++) {
      const on = i === beatInBar;
      const r = (i === 0 ? 9 : 6) * (on ? 1 + 0.6 * (1 - smoothstep(0, 0.25, f.beatPhase)) : 1);
      c.beginPath();
      c.arc(W / 2 - 60 + i * 40, H - 120, r, 0, Math.PI * 2);
      c.fillStyle = on ? rgba('signal', 0.95) : rgba('graphite', 0.7);
      c.fill();
    }
    c.font = font(F.kuaile(), 24);
    c.fillStyle = rgba('ash', 0.8);
    c.textBaseline = 'alphabetic';
    const bar = Math.floor(f.bar) + 1;
    c.fillText(`${this.ctx.params.section ?? ''}  ·  第 ${bar} 小节 第 ${beatInBar + 1} 拍  ·  ${f.t.toFixed(2)} 秒`, 64, H - 56);
  }
}
