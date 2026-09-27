# M0-07 第 2 步：交给 Codex 做的 GUI 核对

第 1 步（公开的官方资料）见 [`docs/m0/07-publish-entry.md`](../../docs/m0/07-publish-entry.md)。
第 2 步要登录后看上传页面，创作者决定交给能做 GUI 操作的 Codex。

| 文件 | 做什么 |
|---|---|
| `CODEX_TASK.md` | **给 Codex 的任务说明**：11 个核对项、7 条硬规则（绝不提交、不传真作品、不写个人信息……） |
| `codex_results.md` | 结果模板，Codex 填 |
| `make_test_assets.py` | 生成测试素材（上传页要先选文件时用），并按 B站官方规格用 ffprobe 逐项核对 |

测试素材在 `out/`（不进仓库）：

| 文件 | 规格 |
|---|---|
| `test_cover.png` | 3000×3000 纯色静态图 |
| `test_audio.wav` | M0-04 的 7.5 秒测试人声，单声道 16-bit 44.1 kHz |
| `test_video.mp4` | 封面静帧 + 测试音频：H.264 · yuv420p · 8bit · 关键帧每 2 秒 · AAC 48 kHz 立体声 · **B站规格 9 项全部达标** |

截图也存在 `out/screenshots/`（里面可能有个人信息，所以不进仓库）。

```bash
cd /e/sv-bridge/spikes/m0-07-publish && python make_test_assets.py
```
