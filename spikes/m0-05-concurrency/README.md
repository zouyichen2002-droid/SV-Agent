# M0-05 探针：文件并发编辑

**探针 = 只为回答一个可行性问题而写的一次性代码，不进产品。**
结论见 [`docs/m0/05-concurrency.md`](../../docs/m0/05-concurrency.md)。

三个问题：软件开着时我在外面改文件，它会不会发现？你一保存，我的改动还在不在？
FL 开着时用命令行导出另一个工程，会不会打扰你？

| 文件 | 做什么 |
|---|---|
| `make_files.py` | 生成测试文件：`m0_05.svp`（复用 M0-04 验证过的生成器）、两份 FL 空模板拷贝 |
| `watch_svp.py` | SynthV 一轮的监视程序：你运行导出脚本 → 它在磁盘上改文件 → 等你保存 → 看谁的改动留下了 |
| `watch_flp.py` | FL 一轮的监视程序：你按 Ctrl+S 当信号 → 它改速度 → 等你保存 → 看速度；再在 FL 开着时命令行导出 |
| `probe_cli_while_open.py` | **全自动**：打开 FL，先确认看得见它，再命令行导出另一个工程，全程记录进程和窗口标题 |

```bash
cd /e/sv-bridge/spikes/m0-05-concurrency
python make_files.py
python watch_svp.py 240           # 参数：最多等几分钟
python watch_flp.py 240
python probe_cli_while_open.py    # 会弹出 FL 窗口约半分钟，别碰它
```

`out/` 不进仓库。
