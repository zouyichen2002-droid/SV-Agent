#!/usr/bin/env bash
# 旧的本地模型（10-01 到 10-03 用的；10-03 起默认换成 Qwen3.6-35B-A3B，见 start-llama.sh）—— 留着备用：要用就停掉那个、开这个，DSH 的默认模型改回 qwen3.8-27b
# 本地模型服务（10-01）：llama.cpp b11259 CUDA 13.4 版（09-29 下的那份）+ Qwen3.8-27B（UD-IQ4_XS，14.3 GB）
# 只监听 127.0.0.1:8081；上下文 16k、KV 缓存 8 位；放不进显存的层自动放 CPU（--fit on）；服务端关掉思考（这台机器上开思考答不完）
# --jinja：按模型自带的模板出工具调用（DSH 要用）；起来以后用 PowerShell 把进程调成低优先级
# 安全（10-01）：默认没密钥、任何网页都能跨域调用（浏览器里开的网站能在后台用模型、读 /slots 里正在处理的对话）→
#   要密钥（llama.key，# 开头的行是注释；DSH 那边从同一个文件读）、跨域只认本机来源、关掉 /slots
# （关思考的 --chat-template-kwargs 写法新版标了过时，新写法是 --reasoning off；现在还能用，先不动）
# 采样（10-03）：DSH 不传采样参数，用这里的默认值。原来是 llama.cpp 默认（温度 0.8、top-k 40、top-p 0.95、不防复读）→
#   工具调用的参数里两次陷进复读、写满 4096 输出上限（项目名「怪物DSH测试」写成「怪物盘中测试盘中盘中…」）。
#   改成 Qwen3 非思考模式官方推荐的 温度 0.7 / top-p 0.8 / top-k 20 / min-p 0，再开 DRY 防复读
#   （只罚重复出现的一整段；换行、冒号、引号、星号是断点、不罚 —— JSON 的引号不受影响）
set -euo pipefail
exec "E:/sv-agent-data/tools/llama.cpp-b11259-cuda/llama-server.exe" \
  -m "E:/sv-agent-data/models/llm/Qwen3.8-27B-UD-IQ4_XS.gguf" \
  --host 127.0.0.1 --port 8081 -c 16384 --device CUDA0 --fit on -ctk q8_0 -ctv q8_0 -np 1 \
  --jinja --reasoning-format deepseek --chat-template-kwargs '{"enable_thinking":false}' --alias qwen3.8-27b \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0 --dry-multiplier 0.8 \
  --api-key-file "E:/sv-agent-data/dsh/llama.key" --cors-origins localhost --no-slots
