// 一格画面的接口（SV-Agent 10-03）：一句歌词一格，外加开场、结尾。
import type { Line } from '../../engine/lyrics';
import type { Frame } from '../../engine/scene';
import type { C2, LyricStyle } from './kit';

export interface PD {
  c: C2;
  /** 歌曲时间、这一格开始以后的时间、这一格的进度（0..1）和长度 */
  t: number; lt: number; p: number; dur: number;
  /** 这一格的歌词（开场 / 结尾没有） */
  l: Line | null;
  /** 底鼓脉冲（0..1，一响就是 1 再衰减）、拍子、小节 */
  k: number; beat: number; bar: number;
  f: Frame;
  /** 格号：0 开场，1..50 对应第 0..49 句，51 结尾 */
  i: number;
}

export interface Panel {
  bg?: 'paper' | 'night' | 'gray' | 'sky' | 'pink';
  draw: (d: PD) => void;
  /** 歌词怎么摆；null = 这一格自己画字（黑板、屏幕……） */
  text?: LyricStyle | null;
  /** 进这一格的转场 */
  tr?: 'pan' | 'up' | 'down' | 'zoom' | 'cut';
  /** 这一格的后期（闪白、推镜头……），和默认的合并 */
  post?: (d: PD) => Record<string, number>;
}
