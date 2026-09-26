# M0-04 探针：SynthV 认不认我们写的 `.svp`

**探针 = 只为回答一个可行性问题而写的一次性代码，不进产品。**
结论见 [`docs/m0/04-synthv.md`](../../docs/m0/04-synthv.md)。

SynthV 的官方脚本接口**不能打开、保存、导出工程**，但能读当前打开的工程。
所以「SynthV 认不认」只能这样验：你打开我们写的文件，运行一个只读脚本，把 SynthV 眼里的内容导出来比。

| 文件 | 做什么 |
|---|---|
| `make_test_svp.py` | 生成测试工程 `out/m0_04.svp`、`out/m0_05.svp` 和标准答案 `out/spec.json` |
| `SVAgentDump.lua` | 装进 SynthV 的**只读**脚本：把当前工程的速度、拍号、音符写成 `<工程>.dump.json` |
| `compare.py` | 标准答案 vs SynthV 的输出，全部精确相等才算绿；自带三处注入缺陷的自检 |
| `verify_recovery.py` | **裁判 3**：读 SynthV 自己写的恢复文件（它眼里的工程），读全部音符组，交给 compare.py 比 |
| `watch_session.py` | 实测时在后台等导出脚本的输出和导出的 WAV，出现就自动核对 |

```bash
cd /e/sv-bridge/spikes/m0-04-svp
python make_test_svp.py
python compare.py out/m0_04.svp.dump.json
python verify_recovery.py m0_04
```

`out/` 不进仓库。模板取自 git 历史（`v1-archive` 里 SynthV 亲手存的空工程），声库引用取自你本机的 SynthV 恢复文件。
