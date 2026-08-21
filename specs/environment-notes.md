# 环境实测记录

> 交接文件 §2 记的环境事实，接手会话逐条复核。**有三条已经过期或不准确**，
> 以本文件为准。复核日期 2026-08-20。

## 1. 已复核一致

| 项 | 值 |
|---|---|
| Python | 3.13.9（Anaconda，`G:\miniconda`） |
| librosa / numpy / scipy / soundfile | 1.0.0 / 2.3.4 / 1.16.3 / 0.14.0 |
| torch | 2.13.0+cpu |
| transformers | 5.15.1 |
| 上游桥仓库 | `E:\SV_MCP`，commit `5c51bd9`，工作区干净 |
| CTC 模型 | `E:\SynthV-models\zh-ctc\`，`pytorch_model.bin` 1,276,296,151 字节，在位 |
| 已装技能 | `synthv-agent` / `synthv-tuning` / `lyric-writing` / `composition-arrangement` |
| MCP 注册 | `E:\潮声回响\.mcp.json` → `node E:/SV_MCP/dist/src/cli.js` |

## 2. 已过期 / 需修正的三条

### 2.1 「不要装 torchaudio」这条约束不成立

交接文件 §2：「**未装且不要装** torchaudio —— pypi 最高 2.11.0，会把 torch 2.13.0
降级弄坏。」

实测：`pip install torchcrepe` 会把 `torchaudio 2.11.0` 作为依赖装进来，
**但 pip 没有降级 torch**，torch 仍是 2.13.0+cpu，两者共存正常：

| 测试 | 结果 |
|---|---|
| `torch` 基本算子（matmul / Conv1d） | 正常 |
| `import torchaudio` | 正常，2.11.0+cpu |
| `torchaudio.functional.resample` / `spectrogram`（C++ 扩展） | 正常 |
| **`torchaudio.functional.forced_align`** | **可用** |
| `torchaudio.load` | 失败，需要 `torchcodec`（不影响，直接喂 tensor 即可） |

**后果**：`forced_align` 现在可用，ADR-0001 里「Viterbi 自己实现」不再是必须的。
自实现版本已验证有效（33/33 行、300/315 字），没有非换不可的理由，
但如果要重构，可以少一段自写代码。

### 2.2 HuggingFace 现在很快

交接文件 §2：「HuggingFace 通但**慢**（440–560 KB/s 最好情况，会衰减到 23 KB/s）」，
§7.1：「这 1.28GB 下了六次才成功」。

实测 2026-08-20：`rmvpe.pt` 181,184,272 字节，**3.04 秒下完，平均 56.8 MB/s**，
单进程 curl 一次成功。

**后果**：所有「下模型太贵所以不做」的判断都要重新算成本。

### 2.3 numpy 的 LAPACK 路径与 torch 的 OpenMP 冲突 —— 会直接 abort

交接文件没有这条。**这是本机最容易反复踩的坑。**

```
OMP: Error #15: Initializing libomp.dll, but found libiomp5md.dll already initialized.
```

- 触发条件：进程里已 `import torch`（它加载 conda 的 `libiomp5md.dll`），
  之后调用 **numpy 的 LAPACK 后端**（`np.polyfit` / `np.linalg.lstsq` / `svd` 等），
  它去加载 `G:\miniconda\Library\bin\libomp.dll` → 直接 abort，**不是异常，是进程死掉**。
- 与 `torch.stft`、`librosa`、`torchcrepe`、`parselmouth` 都**无关**（都验过了）。
- 定位过程走了不少弯路，记在这里省下次的时间：
  单次 `torch.stft`、单次模型前向、连续 14 次前向都正常；
  用逐步打印才定位到是循环末尾的 `np.polyfit`。

**规避方式**：小规模线性拟合自己写闭式解（见 `scripts/calibrate_rmvpe.py:lsq`）。

**不要用 `KMP_DUPLICATE_LIB_OK=TRUE`。** 官方提示自己写着它
"may cause crashes or silently produce incorrect results" —— 本项目的整条方法论
就是防静默错误，不能在地基上开这个口子。`OMP_NUM_THREADS=1` 也不管用（实测无效）。

## 3. 本次新装的包

| 包 | 版本 | 用途 |
|---|---|---|
| `torchcrepe` | 0.0.24 | CREPE，神经族 f0 |
| `praat-parselmouth` | 0.4.7 | Praat 自相关 f0，用作跨族对照 |
| `pypinyin` | 0.55.0 | OOV 字的同音回退（阶段 3 用，尚未接入） |
| `torchaudio` | 2.11.0 | torchcrepe 的依赖，被动装上，见 §2.1 |
| `resampy` | 0.4.3 | torchcrepe 的依赖 |

`audio-separator` **未装** —— 阶段 0 才需要，见 ADR-0002。

## 4. 模型清单

| 模型 | 路径 | 大小 | sha256 |
|---|---|---|---|
| 中文 CTC | `E:\SynthV-models\zh-ctc\pytorch_model.bin` | 1,276,296,151 | `de031fd4b29e0c0667e5346450fadfe1326c89936b888b59c4ede608db763ee4` |
| RMVPE | `E:\SynthV-models\rmvpe\rmvpe.pt` | 181,184,272 | `6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193` |
| CREPE full | torchcrepe 包内 | ~85MB | 随包分发 |

RMVPE 来源：`https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt`

## 5. 性能实测（CPU，16 线程）

| 操作 | 全曲 229.46s 的耗时 |
|---|---|
| torchcrepe `full` @10ms hop | 84.5s |
| praat-ac @10ms | 0.4s |
| RMVPE @10ms | 5.2s（约 50× 实时） |

RMVPE 比 torchcrepe 快 16 倍且质量更好（见 ADR-0004）。
