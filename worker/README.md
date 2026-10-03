# worker · Cover Skill 的 Python Worker（v3 阶段 3）

`cover_run.py`：一首歌 → SynthV 工程。把 M1 的 9 步（`docs/m1/station-end.md` §1）串成**一条命令**，产物都写进项目文件夹。
平时由 DSH 里的 `sv-cover` 插件在后台调（不进沙箱，原因见 `docs/v3/s3-cover.md` §5.1；只往这首歌的文件夹里写）；也可以自己直接跑：

```
python cover_run.py <项目文件夹> --round rNN --source <链接 | 本地音频 | 已有> [--lyrics <歌词原文.txt> | --lyrics none] [--voice 星尘] [--language auto|zh|en|ja] [--octave-pick on|off]
```

| 步 | 用什么 | 写到哪 | 大约 |
|---|---|---|---|
| 原曲 | yt-dlp（不登录、只下音频）/ 本地文件 → ffmpeg 转 44.1 kHz 16 位 | `素材\原曲整首.wav`、`source.json` | 几秒 |
| 歌词 | 认语言（`--language auto`：有假名 → 日语，只有字母 → 英文，否则中文）→ 中文：数字换汉字（`４` → `四`）+ `clean_lyrics`；英文 / 日语：去整行标签和标点 | `素材\歌词_要唱的字.txt` | 瞬间 |
| 分离 | audio-separator：人声 / 伴奏 → 主唱 / 叠唱（**显卡**，创作者 10-01 定） | `分离\` | 约 75 秒 |
| 补段 | 主唱分轨整段没声、整条人声又和平时主唱一样响的地方，用整条人声补 | `分离\主唱_缺的段用整条人声补.wav` | 几秒 |
| 找拍子 | librosa 粗估 → `tempo_map.py`（单线程，**和下面三步并行**） | `拍子\` | 10–18 分钟 |
| 扒谱 | Vocal2Midi（GAME + Qwen3-ASR，DirectML 显卡）；中文只听写，英文 / 日语把歌词交给它对齐 | `扒谱\` | 约 40 秒 |
| 多声部 | basic-pitch（挑八度的第二个裁判） | `扒谱\basic_pitch_raw_主唱补段.json` | 约 10 秒 |
| 模板 | `make_template.py`：声库从 `cover_config.json` 里的 base 抄（默认星尘） | `模板\` | 几秒 |
| 生成工程 | `song_round.py`：中文修歌词只改字、挑八度、你定的规矩、吸格线；英文 / 日语挑八度、吸格线、声库设成 SV 跨语种。`--octave-pick off` = 不挑八度（创作者 10-01 定：加开关、默认开） | `rNN\` + `说明.md` | 约 5 秒 |

- **做完的步跳过**：中途断了，再跑一遍接着走（`rNN` 那一步除外：每一版都写新文件）
- 每一步的输出在 `日志\<步>.log`；进度一行一个 JSON 在 `日志\进度.jsonl`（插件读它）；总结在 `日志\翻唱_rNN.json`
- **不用管道接子程序的输出**（写日志文件）：DSH 的 Windows 沙箱里，管道接别的程序的输出会 EPERM
- 一开始把自己调成「低于正常」，起的子程序都跟着低；numba 的缓存放到临时目录（沙箱里 site-packages 写不了）
- 本机的程序和模型路径都在 `cover_config.json`，换机器只改它
- 日语读音：Vocal2Midi 要 pyopenjtalk，Windows 没有现成的包 → `spikes/m1-01-voice-to-midi/ja_g2p_fugashi.py` 借本机 `tts-indextts2` 环境里的 fugashi + unidic-lite（环境变量 `SV_JA_G2P_SITE` 可以改路径）

## 测过的

见 `docs/v3/s3-cover.md` §3：整首重跑《逃跑的天使》对 M1 r02；10-01 下午在 DSH 里翻你给的六首（4 中文、1 英文、1 日语）。

## 歌词视频（v3 视频，10-01）

`video_run.py`：翻唱出来的工程 + 你给的图 + 你混好的成品音频 → 1080p 成片（mp4）+ 剪映草稿。平时由 DSH 里的 `sv-video` 插件在后台调（不进沙箱：剪映的草稿文件夹在工作区外面）：

```
python video_run.py <项目文件夹> --version vNN --audio <成品音频> --image <图或视频> [--image …] [--svp <工程>] [--title …] [--credit …] [--fx 可爱|凌厉|平铺|弹跳|发光|浮现|逐字出现|竖排古风] [--side auto|left|right] [--drafts <剪映草稿文件夹>]
```

| 步 | 用什么 | 写到哪 | 大约 |
|---|---|---|---|
| 检查、素材 | 音频、图、工程、歌词都在；图和成品音频拷一份（剪映草稿指着这份） | `视频\vNN\素材\` | 1 秒 |
| 逐字时间 | `lyric_timing.py`（vocal2midi 环境）：工程里每个音 → 对回歌词原文的字 | `视频\vNN\逐字时间.json` | 1 秒 |
| 对齐 | `audio_offset.py`（numpy）：成品音频比工程晚几秒（伴奏两边共有，起音包络互相关 + 分段核对）→ 字幕平移 | 同上（平移前的另存 `_工程时间.json`） | 1 秒 |
| 成片 | `lyric_video.py`（ffmpeg）：图（推近）或视频底片（循环铺满）+ 字幕 + 成品音频；字幕默认「可爱」，`--fx` 换别的（每个字单独动，排版自己算，`python lyric_fx.py --calibrate` 核对）；`--side` 指定字放哪边 | `视频\vNN\<歌名>_歌词视频_vNN.mp4` | 一首 3–4 分钟的歌约 1–2.5 分钟（libx264） |
| 剪映草稿 | `jianying_draft.py`（video 环境，pyJianYingDraft）：整份草稿在内存里做完再写盘 | `<剪映草稿文件夹>\SV-Agent_<歌名>_vNN\` | 1 秒 |
| 说明 | 用了哪个工程、对齐结果、要看一下的 | `视频\vNN\说明.md`（最后写：有它 = 这一版做完了） | — |

- 进度一行一个 JSON 在 `日志\视频进度.jsonl`；总结在 `日志\视频_vNN.json`；每步的输出在 `日志\视频_vNN_<步>.log`
- 自检：`python audio_offset.py --selftest`、`python lyric_fx.py --calibrate`（特效字幕每个字的位置）；用真歌测过的数字见 `docs/v3/s10-video.md` §3–5
- 「可爱」（默认）用站酷快乐体，「凌厉」用马善政毛笔楷书（大字、竖排小字都是；日语用佑字肅；都在 `cover_config.json` 的 `fonts_dir`，不装进系统；每一版拷一份到 `视频\vNN\_fonts\`）；「凌厉」出片前把底图调一次（压暗、降饱和、暗角、颗粒，存 `视频\vNN\_底图\`）；拆行（`lyric_rows.py`）和字放哪边（`image_side.py`）成片和剪映草稿共用
- 字只放在 `image_side.text_area` 里（判断哪边空时量的那 45%：左 60–860、右 1060–1860 像素），按整块外框居中（10-02《怪物》雨夜底片压到人物的手以后改的，见 `docs/v3/s10-video.md` §5.6）

## 八度和声（10-02）

`add_octave_harmony.py`：主轨在给定几段里的音复制一份、移一个八度，放成新轨（下八度、上八度各一条，一条开一条静音，比主轨低几分贝）；原来的轨不动，新文件已经存在就不写。

```
python add_octave_harmony.py <工程.svp> <新工程.svp> --lines 14-18,44-48 [--readme] [--on below|above] [--gain -6] [--track 主轨名]
python add_octave_harmony.py <工程.svp> <新工程.svp> --section 40.0-55.8 [--section …] …
```

- `--lines`（第几句到第几句）：用做字幕那套代码对出每句唱的起止，取第一句第一个字到最后一句最后一个字 —— 不会多带上一句的音；歌词默认 `<项目>\素材\歌词_要唱的字.txt`
- `--section`（秒）：音的开头落在 [开始, 结束) 里才复制。输出里「两头」列出每段复制的第一个、最后一个音和紧挨着没复制的音，对着看
- `--readme`：在新工程旁边写 `说明.md`
- 创作者 10-03 定：和声不进 DSH、不做成通用技能 —— 他说哪几句要加，手动跑这个
- 《怪物》r03 就是这样做的，见 `docs/v3/s3-cover.md` §3.6（r02 因为边界多带了一个音弃用）
