#!/usr/bin/env bash
# 本地模型服务（10-01）：llama.cpp b11259 CUDA 13.4 版（09-29 下的那份）+ Qwen3.8-27B（UD-IQ4_XS，14.3 GB）
# 只监听 127.0.0.1:8081；上下文 16k、KV 缓存 8 位；放不进显存的层自动放 CPU（--fit on）；服务端关掉思考（这台机器上开思考答不完）
# --jinja：按模型自带的模板出工具调用（DSH 要用）；起来以后用 PowerShell 把进程调成低优先级
# 安全（10-01）：默认没密钥、任何网页都能跨域调用（浏览器里开的网站能在后台用模型、读 /slots 里正在处理的对话）→
#   要密钥（llama.key，# 开头的行是注释；DSH 那边从同一个文件读）、跨域只认本机来源、关掉 /slots
# （关思考的 --chat-template-kwargs 写法新版标了过时，新写法是 --reasoning off；现在还能用，先不动）
set -euo pipefail
exec "E:/sv-agent-data/tools/llama.cpp-b11259-cuda/llama-server.exe" \
  -m "E:/sv-agent-data/models/llm/Qwen3.8-27B-UD-IQ4_XS.gguf" \
  --host 127.0.0.1 --port 8081 -c 16384 --device CUDA0 --fit on -ctk q8_0 -ctv q8_0 -np 1 \
  --jinja --reasoning-format deepseek --chat-template-kwargs '{"enable_thinking":false}' --alias qwen3.8-27b \
  --api-key-file "E:/sv-agent-data/dsh/llama.key" --cors-origins localhost --no-slots
