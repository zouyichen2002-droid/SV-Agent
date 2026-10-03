#!/usr/bin/env bash
# 本地模型服务（10-03 起的默认）：llama.cpp b11259 CUDA 13.4 版 + Qwen3.6-35B-A3B（unsloth UD-IQ4_XS，17,730,509,792 字节；阿里 2026-04，Apache 2.0）
#   总共 35B 参数、每个字只用 3B（MoE）；放不进显存的专家放内存。10-03 下午照 DSH 全流程实测后创作者定成默认（sv-bridge/docs/v3/moe-trial.md）：
#   出字 62 token/秒（旧的 Qwen3.8-27B 6.5）、上下文 32k（旧的 16k）、常驻内存约 10 GB（旧的约 5–6 GB）
# 旧的 Qwen3.8-27B 留在 start-llama-27b.sh 备用。两个脚本用同一个端口 8081，同时只能开一个；换模型时 DSH 的默认模型也要一起换（cordis.patch.yml）
# 和旧脚本一样的：只听本机、要密钥、跨域只认本机、关 /slots、关思考、采样（温度 0.7 / top-p 0.8 / top-k 20 / min-p 0）+ DRY 防复读（为什么见 start-llama-27b.sh）
# --fit on 会自己把后一半层（20–40 层，外加 19 层的 down）的专家放内存、其余都在显卡上（llama-fit-params 看过）
# --load-mode none（10-03 13:40 加）：不用内存映射。映射的时候整个模型文件（16.5 GB）都留在进程里，系统可用内存一度只剩 0.34 GB；
#   而且 llama.cpp 自己提示「专家放 CPU 时映射会更慢」。不映射：只有放内存的专家常驻
set -euo pipefail
exec "E:/sv-agent-data/tools/llama.cpp-b11259-cuda/llama-server.exe" \
  -m "E:/sv-agent-data/models/llm/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf" --load-mode none \
  --host 127.0.0.1 --port 8081 -c 32768 --device CUDA0 --fit on -ctk q8_0 -ctv q8_0 -np 1 \
  --jinja --reasoning-format deepseek --chat-template-kwargs '{"enable_thinking":false}' --alias qwen3.6-35b-a3b \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0 --dry-multiplier 0.8 \
  --api-key-file "E:/sv-agent-data/dsh/llama.key" --cors-origins localhost --no-slots
