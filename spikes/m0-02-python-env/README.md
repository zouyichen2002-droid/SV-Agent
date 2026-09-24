# M0-02 探针：音频 worker 的独立 Python 环境

**探针 = 只为回答一个可行性问题而写的一次性代码，不进产品。**
这里的问题是：能不能建一个独立、可复现的 Python 环境，装得上、载得起、跑得通？（PRD §14）

| 文件 | 做什么 |
|---|---|
| `pyproject.toml` | 环境定义：Python 3.13.* + numpy 2.5.3。V1 的 worker 只需要这些 |
| `check_env.py` | 四项检查：隔离 · 版本 · 能跑 · 可复现。隔离和版本各带反向对照 |

建环境时**底座必须显式指定** —— 不指定的话，uv 默认会挑 miniconda 的 3.13.9，
环境就绑在了 conda 上：

```bash
cd /e/sv-bridge/spikes/m0-02-python-env
uv sync --python "C:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe"
uv run python check_env.py
```

`.venv/` 和 `out/` 不进仓库；`uv.lock` 进仓库（它记下了每个包的确切版本与哈希）。
