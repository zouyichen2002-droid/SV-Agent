# M0-03 探针：FL Studio 工程读写、速度、命令行导出

**探针 = 只为回答一个可行性问题而写的一次性代码，不进产品。**
结论和全部数字见 [`docs/m0/03-fl-project.md`](../../docs/m0/03-fl-project.md)。

核心办法：**让 FL 自己当裁判** —— 用它的命令行导出 MIDI / WAV，读出它认定的速度和长度，
拿来核对我们对 `.flp` 的读和写。

| 文件 | 做什么 |
|---|---|
| `flp.py` | 最小的 `.flp` 读取器：只认结构不认含义；自带「恰好读完」的结构检查；能改一个定长事件的值 |
| `fl_cli.py` | 调 FL 命令行导出 MIDI / WAV；**只认产物，不认退出码**（`/M<文件夹>` 退出码 0 却零产出） |
| `find_tempo.py` | 不预设答案地找速度事件：FL 报速度 → 在所有事件里找值对得上的 |
| `write_check.py` | 写入新速度，用 FL 导出的 MIDI 和 WAV 时长双重核对；先注入「忘了乘 1000」证明检查会响 |

```bash
cd /e/sv-bridge/spikes/m0-03-flp
python find_tempo.py     # 第一次会启动 FL 13 次；结果缓存在 out/oracle.json
python write_check.py    # 会启动 FL 5 次
```

运行前**确认 FL 没开着**。样本都是 FL 自带工程的拷贝，放在 `out/`，不进仓库（第三方内容）。
需要 `mido`（miniconda 里有）。
