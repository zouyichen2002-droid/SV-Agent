// 时间轴：哪一段放哪个场景。
// SV-Agent（10-03）：pdoom 那份是它那首歌的剪辑表。这里先放一个通用的占位时间轴 —— 按音频分析里的段落
//   （audio.json 的 sections）每段一个条目，都用占位场景；段落边界本来就落在强拍上。
//   正式做一首歌时，照那首歌的设计手册另写（按第几句歌词找时间点，代码里不写歌词原文：仓库是公开的）。
import type { TimelineEntry } from './engine/engine';
import type { SceneClass } from './engine/scene';
import type { Lyrics } from './engine/lyrics';
import type { AudioData } from './engine/audio';

// Scene modules are discovered lazily so a missing/broken scene never breaks the build.
const modules = import.meta.glob<{ default: SceneClass }>('./scenes/*.ts');
const scene = (name: string) => () => {
  const m = modules[`./scenes/${name}.ts`];
  return m ? m() : Promise.reject(new Error(`scene module not found: scenes/${name}.ts`));
};

export function makeTimeline(_ly: Lyrics, au: AudioData): TimelineEntry[] {
  // 一首歌一个整首场景，用环境变量 VITE_MV_SCENE 选（不设 = journal）：
  //   journal  10-03《逃跑的天使》：手账，一句一格、自己换格
  //   theater  10-04《由》：人偶剧场
  if (import.meta.env.VITE_MV_PLACEHOLDER !== '1') {
    const name = import.meta.env.VITE_MV_SCENE || 'journal';
    return [{ id: name, load: scene(name), start: 0, end: au.duration }];
  }
  const secs = au.sections.length ? au.sections : [{ name: 'all', start: 0, end: au.duration }];
  return secs.map((s, i) => ({
    id: `${String(i + 1).padStart(2, '0')}-${s.name}`,
    load: scene('placeholder'),
    start: i === 0 ? 0 : s.start,
    end: i === secs.length - 1 ? au.duration : secs[i + 1]!.start,
    params: { section: s.name, index: i },
  }));
}
