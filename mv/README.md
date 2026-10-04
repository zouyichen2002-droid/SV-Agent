# 代码画的 MV（`mv/`）

照 [mexicat/pdoom-video](https://github.com/mexicat/pdoom-video) 的做法：每一帧都是「歌曲时间」的函数，用 three.js / WebGL 画，后台 Chrome 一帧一帧画、ffmpeg 编码。
它的**引擎部分**拿过来了（MIT，许可声明见 `LICENSE-pdoom-video.txt`，取自它 `a048746` 那一版），它的歌、场景、插图、字体都没拿。为什么做、怎么排期见 `docs/v3/mv-plan.md`。

## 和 pdoom 不一样的地方（10-03）

- 用本机的 Node 24 跑（它用 bun）：`scripts/render.ts` 改写了起服务器、写文件、收帧那几处，收帧用 `ws`
- Windows：Chrome 走 D3D11，加了用独立显卡的开关（实测用的是 RTX 5070 Ti）；渲染时把自己、ffmpeg、这次开的 Chrome 调成「低于正常」
- 字体换成中文（`src/engine/type.ts`：快乐体、马善政），从仓库外的字体文件夹读
- 歌词按字：中文一个字一个单位、中间没空格（`lyrics.ts` 的逐字进度、按内容找句子跟着改）
- 顶层叠加（`hud.ts`）去掉了它那首歌专用的 P(doom) 读数和裁切线，只留字幕；没拿它的单线英文字体（`stroke.ts`）
- 数据不在仓库里：`/song/*` 指到那首歌的 MV 文件夹（`MV_SONG_DIR`），`/fonts/*` 指到 `E:\sv-agent-data\fonts`（`vite.config.ts`）

## 文件

| 位置 | 是什么 |
|---|---|
| `src/engine/` | 引擎：时间轴调度、运动模糊（子帧平均，自适应 4–324 个）、后期（泛光、光晕、色差、颗粒、暗角）、字体排版、GPU 线条 |
| `src/scenes/` | 场景：`journal.ts`（《逃跑的天使》手账 MV：一句一格、换格转场、页眉、贯穿的金色光点）+ `angel/`（`kit.ts` 画画工具和小天使、`panels-a/b/c.ts` 52 格画面）；`placeholder.ts`（验证用的占位场景） |
| `src/timeline.ts` | 时间轴：现在整首放 `journal`；`VITE_MV_PLACEHOLDER=1` 时换回占位（每个段落一个占位场景） |
| `scripts/render.ts` | 出图出片：`gpu` / `stills` / `sheet` / `perf` / `video` |
| `analysis/prepare_song.py` | 准备一首歌的数据（见下） |
| `docs/ENGINE-pdoom.md` | 原作的引擎说明（英文），写场景时照它：场景接口、确定性规则、后期参数、4K |

## 一首歌的数据（仓库外：`<项目>\MV\`）

`analysis/prepare_song.py` 生成（miniconda 的 Python，要 librosa；自己调低优先级）：

- `audio.wav`：创作者从 SV 导出的成品混音（拷一份）
- `逐字时间.json` → `lyrics.json`：从和混音对应的那份 SV 工程算每个字什么时候唱（`worker/lyric_timing.py`，和歌词视频同一套）
- `audio.json`：拍子、强拍（找拍子的结果）；各频段、各声部响度（混音 + 分离出来的主唱 / 伴奏）；底鼓、军鼓、镲、人声的起音；粗分的段落
- `准备.json`：用了哪些文件、混音和伴奏的对齐结果、各项统计（不写歌词原文）
- `out\`：单帧、联系表、短片段、成片

## 怎么跑

```
cd E:\sv-bridge\mv
npm install                                   # 第一次（three、opentype.js、vite、playwright-core、ws，约 74 MB）
G:\miniconda\python.exe analysis\prepare_song.py --project <项目> --svp <和混音对应的工程> --mix <成品混音.wav>
node scripts/render.ts gpu    --song <项目>\MV                      # 看 Chrome 用哪块显卡
node scripts/render.ts stills --song <项目>\MV --t 10.5,30.2         # 单帧 → out\stills\
node scripts/render.ts sheet  --song <项目>\MV --from 3 --to 215 --n 16 --cols 4   # 联系表 → out\sheets\
node scripts/render.ts video  --song <项目>\MV --from 14 --to 22 --samples auto --preset veryfast --out <文件.mp4>
```

拖着看、带声音的预览：`MV_SONG_DIR=<项目>\MV` 下 `npx vite`，浏览器开 http://localhost:5173 （空格播放 / 暂停，←→ 跳 1 秒）。

## 实测（10-03，《逃跑的天使》+ 占位场景）

- Chrome 用的是 RTX 5070 Ti（D3D11）
- 不带运动模糊：一帧约 29 ms（含读像素）→ 整首 1080p60 约 7 分钟
- 带运动模糊（`--samples auto`）：每秒约 1.5 帧（大多数帧 36 个子帧）→ 整首约 2.5 小时，正式出片放夜里低优先级跑

## 规矩

- 代码里不写歌词原文（仓库是公开的）：找时间点按第几句（`lyrics.lines[12]`），不按内容找
- 歌、歌词、字体文件不进仓库；画面不抄原 MV、不画已有的角色
- 渲染是重活：低优先级跑，创作者要用电脑就停
