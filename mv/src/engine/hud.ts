// 顶层叠加（SV-Agent 10-03 重写）：原来是 pdoom 那首歌专用的 P(doom) 读数和裁切线，去掉了。
// 现在只画时间轴条目给的字幕（右下角，例如开头的歌名、署名）；没有字幕时是透明的，也不重新上传。
import { Layer2D, W, H } from './gl';
import { rgba } from './palette';
import { F, font } from './type';
import { smoothstep } from './util';

export interface Caption { start: number; end: number; fig: string; text: string }

export interface HudOptions {
  /** HUD opacity multiplier (post.hud). */
  opacity?: number;
  /** 0..1: the frame is light — captions switch to ink. */
  paper?: number;
}

export class Hud {
  private layer = new Layer2D();
  private blank = false;

  constructor(private captions: Caption[] = []) {}

  draw(t: number, o: HudOptions = {}) {
    const op = o.opacity ?? 1;
    const on = op > 0 ? this.captions.filter((c) => t >= c.start && t < c.end) : [];
    if (on.length === 0) {
      if (!this.blank) { this.layer.clear(); this.layer.upload(); this.blank = true; }
      return this.layer.texture;
    }
    this.blank = false;
    const L = this.layer, c = L.ctx;
    L.clear();
    const ink = (o.paper ?? 0) > 0.5 ? 'ink' : 'bone';
    for (const cap of on) {
      const a = op * smoothstep(cap.start, cap.start + 0.4, t) * (1 - smoothstep(cap.end - 0.6, cap.end, t));
      if (a <= 0) continue;
      c.save();
      c.textAlign = 'right';
      c.textBaseline = 'alphabetic';
      c.font = font(F.kuaile(), 22);
      c.fillStyle = rgba(ink, 0.55 * a);
      c.fillText(cap.fig, W - 64, H - 92);
      c.font = font(F.kuaile(), 34);
      c.fillStyle = rgba(ink, 0.9 * a);
      c.fillText(cap.text, W - 64, H - 52);
      c.restore();
    }
    return L.upload();
  }
}
