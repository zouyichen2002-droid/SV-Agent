# 环境实测记录

> 交接文件 §2 记的环境事实，接手会话逐条复核，并追加本会话新踩到的坑。
> 以本文件为准。首次复核 2026-08-20，最近更新 2026-08-22。

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

## 2. 已过期 / 需修正 / 新增的坑

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

### 2.4 audio-separator 0.44.5 与 librosa 1.0.0 不兼容

`audio_separator/separator/common_separator.py:292` 调用
`librosa.get_duration(filename=...)`。librosa 0.10 把该参数改名为 `path`，
1.0.0 里 `filename` 已不存在。

**失败位置很坑**：它在**推理全部跑完之后**的写文件那一步才炸，
所以会白跑一遍完整推理（本机 RoFormer + MDX 两个模型合计 40s，长曲目会更痛）。

三个选项与取舍：

| 做法 | 为什么不选 / 选 |
|---|---|
| 降 librosa | 不行。RMVPE 前端、activity、音符构建全依赖 1.0.0 |
| 改 site-packages 里的第三方文件 | 能修，但重装就没了，且不留痕迹 |
| **在自己进程里包一层 shim** | **选这个**。只影响本进程、可见、可撤、不动别人的文件 |

实现见 `scripts/separate_voices.py:patch_librosa_get_duration()`。

### 2.5 basic-pitch 在 Python 3.13 上装不上

构建链用了 3.12 已移除的 `pkgutil.ImpImporter`：

```
AttributeError: module 'pkgutil' has no attribute 'ImpImporter'
```

`--only-binary :all:` 也解不开依赖（ResolutionImpossible）。0.4.0 及以下全部如此。
替代方案见 ADR-0005（回代检验）。若一定要用，可仿 ADR-0003 对 RMVPE 的做法：
拿它的 ONNX 权重自己写推理。

## 3. 本次新装的包

| 包 | 版本 | 用途 |
|---|---|---|
| `torchcrepe` | 0.0.24 | CREPE，神经族 f0 |
| `praat-parselmouth` | 0.4.7 | Praat 自相关 f0，用作跨族对照 |
| `pypinyin` | 0.55.0 | OOV 字的同音回退（阶段 3 用，尚未接入） |
| `torchaudio` | 2.11.0 | torchcrepe 的依赖，被动装上，见 §2.1 |
| `resampy` | 0.4.3 | torchcrepe 的依赖 |
| `audio-separator` | 0.44.5 | 主唱/和声分离（ADR-0005），需 §2.4 的 shim |
| `audioread` | — | audio-separator 的隐式依赖，不装它 import 就失败 |
| `onnxruntime` | 1.29.0 | audio-separator 跑 ONNX 模型 |
| `torchvision` | 0.28.0 | audio-separator → onnx2torch 的依赖，被动装上 |

装 `audio-separator[cpu]` **没有降级 torch**（2.13.0 保留）。

## 4. 模型清单

| 模型 | 路径 | 大小 | sha256 |
|---|---|---|---|
| 中文 CTC | `E:\SynthV-models\zh-ctc\pytorch_model.bin` | 1,276,296,151 | `de031fd4b29e0c0667e5346450fadfe1326c89936b888b59c4ede608db763ee4` |
| RMVPE | `E:\SynthV-models\rmvpe\rmvpe.pt` | 181,184,272 | `6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193` |
| CREPE full | torchcrepe 包内 | ~85MB | 随包分发 |
| karaoke 分离 · RoFormer | `separator/mel_band_roformer_karaoke_gabox.ckpt` | 913,026,650 | 由 audio-separator 下载并校验 |
| karaoke 分离 · MDX-Net | `separator/UVR_MDXNET_KARA_2.onnx` | — | 同上 |

RMVPE 来源：`https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt`

## 5. 性能实测（CPU，16 线程）

| 操作 | 全曲 229.46s 的耗时 |
|---|---|
| torchcrepe `full` @10ms hop | 84.5s |
| praat-ac @10ms | 0.4s |
| RMVPE @10ms | 5.2s（约 50× 实时） |

RMVPE 比 torchcrepe 快 16 倍且质量更好（见 ADR-0004）。
