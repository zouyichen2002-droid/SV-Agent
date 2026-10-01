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
