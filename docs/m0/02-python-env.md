# M0-02 · 音频 worker 的独立 Python 环境

| | |
|---|---|
| 对应 | PRD §14「Python 与音频依赖」· §11.5「版本组合在 V0 实测后锁定，不根据旧描述直接限定」 |
| 日期 | 2026-09-24 |
| 结论 | **V1 的环境：绿。** Python 3.13.7 + numpy 2.5.3，独立、锁定、跑得通，输出和 M0-01 逐字节相同。「≤ 3.11」的旧描述**成立，但只因为 basic-pitch 一个包** |
| 代码 | `spikes/m0-02-python-env/`（探针，不进产品） |

---

## 1. 结论先说

```
  worker 用 Python 3.13
    │
    ├─ V1 只要 numpy ──────────── 绿   本次装好、锁定，四项检查全过
    │
    ├─ V2 要 CUDA 版 torch ─────── 灰   强证据：同机 ComfyUI 已经跑通
    │                                   Python 3.13 + torch 2.13.0+cu130 + sm_120
    │                                   我们自己的环境里还没装（几个 GB，到 V2 再装、装前先问你）
    │
    └─ V2 如果要 basic-pitch ───── 红   原样装不上（见第 2 节）
                                        两条退路到 V2 再验，现在不做
```

**灰 ≠ 绿**（PRD §8.3）：CUDA 那一行证据很强，但证据来自别的环境，不是我们的。

---

## 2. 「pi-audio 要 Python ≤ 3.11」—— 成立，但原因比原话窄得多

```
  TensorFlow 2.15.0 的安装包只有 cp39 · cp310 · cp311          ← 没有 3.12、3.13
          ▲
  basic-pitch 0.4.0 的依赖：Windows 上 Python ≥ 3.11 时
  必须装 tensorflow < 2.15.1（Python < 3.11 时改用 onnxruntime）
          ▲
  上游 pi-audio 用 basic-pitch 做音符转写           →   所以「≤ 3.11」
```

证据（2026-09-24 直接读 PyPI 的包信息）：

| 读了什么 | 原文 |
|---|---|
| basic-pitch 最新版 | `0.4.0`（2024-08-16 之后没有新版），自身 `requires_python` 为空 —— **它本身不限版本** |
| basic-pitch 的一条依赖 | `tensorflow<2.15.1,>=2.4.1; platform_system != "Darwin" and python_version >= "3.11"` |
| 另一条 | `onnxruntime; platform_system == "Windows" and python_version < "3.11"` |
| TensorFlow 2.15.0 的全部安装包 | 只有 `cp39` `cp310` `cp311` 三种（任何平台都没有更高的） |

**所以：限制来自 basic-pitch 这一个包的一条依赖，不是整个音频生态。**
不用 basic-pitch，就不受这个限制。V1 完全用不到它；V2 的转写用不用它还没定。

如果 V2 真要用，两条退路（**都没验证过，到时候再验**）：

1. 跳过它的依赖安装（`--no-deps`），自己装 onnxruntime —— basic-pitch 0.4.0 自带 ONNX 模型
2. 单开一个 Python 3.11 的小进程只跑它

---

## 3. 为什么是 3.13

| 证据 | 来源 |
|---|---|
| 这块显卡（RTX 5070 Ti Laptop，算力 12.0 / sm_120，Blackwell）上，**Python 3.13.14 + torch 2.13.0+cu130 已经跑通**：`cuda.is_available()` 为真、架构列表含 `sm_120`、GPU 矩阵乘法通过 | 同机 ComfyUI 自带的 Python，2026-09-24 实测 |
| numpy 最新版 2.5.3 要求 Python ≥ 3.12 | PyPI |
| numba 最新版 0.67.0（librosa 依赖它）要求 Python ≥ 3.10 | PyPI |
| 唯一的反例是 basic-pitch | 第 2 节 |

---

## 4. 环境本身

```bash
cd /e/sv-bridge/spikes/m0-02-python-env
uv sync --python "C:/Users/admin/AppData/Local/Programs/Python/Python313/python.exe"
```

| 项 | 值 |
|---|---|
| 工具 | uv 0.12.5 |
| 底座 | python.org 的 **3.13.7**（`C:\Users\admin\AppData\Local\Programs\Python\Python313`） |
| 装了什么 | **只有** numpy 2.5.3（下载 12.0 MiB，来自 PyPI） |
| 耗时 | **3.96 秒**（含下载 1.22 秒）—— 环境坏了、换机器，一条命令、几秒钟就能重建 |
| 锁定 | `uv.lock` 进仓库：记下每个包的确切版本、来源和哈希 |
| `pyvenv.cfg` | `include-system-site-packages = false` |

### 一个坑：uv 默认会挑 miniconda 当底座

不写 `--python` 的话，uv 挑的是 `G:\miniconda\python.exe`（3.13.9）。
那样环境就绑在了你的 conda 上 —— conda 一升级 Python，环境就可能坏。
**所以建环境时底座必须显式指定。**

还有一条无害的警告：uv 缓存在 C 盘、项目在 E 盘，跨盘不能硬链接，只能复制。
慢一点，结果一样。

---

## 5. 四项检查

| 检查 | 结果 | 怎么判 |
|---|---|---|
| **隔离** | 绿 | 是虚拟环境；搜索路径里没有环境以外的第三方包目录；**scipy 和 librosa 都导入失败** |
| **版本** | 绿 | Python 3.13.7；numpy 2.5.3 |
| **能跑** | 绿 | 用 M0-01 的 gm.dls 渲染器渲染标准样本 × 5：中位 0.305 · 最慢 0.372 秒；峰值 −2.8 / RMS −20.0 dBFS；削波 0 |
| **可复现** | 绿 | 和 M0-01 的 WAV **逐字节相同**（SHA-256 `5b6e97259441ea88…`） |

**「可复现」的分量**：M0-01 是在 miniconda（Python 3.13.9 · numpy 2.3.4）里渲染的，
这次是新环境（Python 3.13.7 · numpy 2.5.3）。换了解释器、换了 numpy 版本，
出来的文件**一个字节都没变**。核对过不是拿同一个文件自己比自己：
两个文件路径不同、写出时间差了一个多小时，而代码合成钢琴的 WAV 哈希不同（`0b279026…`）。

### 反向对照：先证明检查会响

scipy 装在底座（python.org 3.13 里是 1.16.2）和 miniconda 里，librosa 装在 miniconda 里 ——
在隔离的环境里导入它们必须失败。并且**在建环境之前**，先用两个不隔离的解释器直接跑检查：

| 故意用不隔离的解释器 | 隔离 | 版本 | 为什么红 |
|---|---|---|---|
| python.org 3.13.7 本身 | **红** | **红** | 不是虚拟环境；scipy 能导入；numpy 是 2.2.6 |
| miniconda 3.13.9 本身 | **红** | **红** | 不是虚拟环境；scipy 和 librosa 都能导入；numpy 是 2.3.4 |

检查会响，这次的绿才算数（PRD §12 纪律一）。

---

## 6. 速度：比 miniconda 慢一些，原因没查

| | 这个环境 | M0-01（miniconda） |
|---|---|---|
| 热启动渲染（中位） | 0.305 秒（× 5） | 0.233 秒（× 20） |
| 冷启动（新进程，中位） | 671 ms（× 5，658–692） | 470 ms（× 5） |

慢 30–40%。**原因没查** —— 对 30 秒的目标还有约 100 倍余量，查它不会让出歌更快（铁律）。
以后如果预览速度真的成了问题，这里是个起点。

冷启动是直接用 `.venv\Scripts\python.exe` 起的进程，不经过 `uv run` —— M2 里 worker 就会这样启动。

---

## 7. 这次没测到的

| 没测到 | 什么时候测 |
|---|---|
| CUDA 版 torch 装进**我们的**环境 | V2 选定源分离 / 音高模型时（几个 GB，装前先问你） |
| basic-pitch 的两条退路 | V2 决定要不要用它时 |
| 源分离、逐字对齐等其他 V2 依赖 | 同上 —— 方法还没选，现在装是本末倒置 |
| 主进程 ↔ worker 的通信 | M2 |
| 用 uv 自己管理的 Python 当底座（比 python.org 的更独立） | 需要时再换；那也是一次下载 |

---

## 8. 能力矩阵条目

| 能力 | 状态 | 最近的验证证据 | 限制 | 替代路径 |
|---|---|---|---|---|
| 音频 worker 环境（V1） | **绿** | 本文 · 2026-09-24 | 只装了 numpy；底座绑在 python.org 3.13.7 上（卸了它，环境要重建） | `uv sync` 一条命令、约 4 秒重建 |
| CUDA 版 torch（V2） | **灰**（强证据） | 同机 ComfyUI 实测 · 2026-09-24 | 我们的环境里还没装 | CPU 版 torch（慢） |
| basic-pitch（V2 可选） | **红**（原样装不上） | PyPI 包信息 · 2026-09-24 | TensorFlow 2.15 只到 cp311 | 跳过依赖改用 onnxruntime；或单开 3.11 小进程 |
