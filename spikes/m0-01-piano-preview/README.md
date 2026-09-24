# M0-01 探针：钢琴预览

**探针 = 只为回答一个可行性问题而写的一次性代码，不进产品。**
这里的问题是：钢琴预览能不能做到 ≤ 30 秒（PRD §8.1 ①）。

结论和全部数字见 [`docs/m0/01-piano-preview.md`](../../docs/m0/01-piano-preview.md)。

| 文件 | 做什么 |
|---|---|
| `sample.py` | 标准样本：16 小节 · 76 BPM · 163 个音。也能写成 `.mid` |
| `renderers.py` | 两个渲染器：读 gm.dls 的采样钢琴、纯代码合成的钢琴 |
| `measure.py` | 测速：冷启动 × 5、热启动 × 20、失败计数、响度、确定性 |
| `pitch_check.py` | 测音准：两级检查 + 三个注入缺陷，证明检查会响 |

```bash
cd /e/sv-bridge/spikes/m0-01-piano-preview
python measure.py        # 测速，产物在 out/
python pitch_check.py    # 测音准
```

`out/` 不进仓库。
