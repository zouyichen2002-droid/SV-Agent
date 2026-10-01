#!/usr/bin/env bash
# SV-Agent 用的 DSH 网页界面启动脚本（10-01）。
# - DSH 0.2.0-rc.2 装在 E:/sv-agent-data/dsh（锁版本；开发者预览，升级前先读升级说明）
# - 数据（配置档、会话、凭据）放 E:/sv-agent-data/dsh-home，不进用户目录
# - 从专用工作目录 E:/sv-agent-workspace 启动：DSH 默认只在这里读写；权限预设默认 workspace-write（沙箱只许写工作区 + 要审批的先问）
# - 遥测关掉（DSH_TELEMETRY_DISABLED 非空就退出；默认会在用户点反馈时把会话片段发到 DeepSeek 的收集服务器）—— 创作者要全部本地
# - 只开在本机 127.0.0.1:3080，不自动开浏览器；访问令牌在日志里
# 本地模型：另起 llama.cpp（CUDA 版）在 127.0.0.1:8081，见 start-llama.sh
set -euo pipefail
export DSH_HOME="E:/sv-agent-data/dsh-home"
export DSH_TELEMETRY_DISABLED=1
export DSH_PERMISSION_MODE=workspace-write
LOCAL_LLAMA_KEY="$(grep -v '^#' "E:/sv-agent-data/dsh/llama.key" | head -n 1)"   # 本地模型服务的密钥（10-01 起要密钥，见 start-llama.sh）
export LOCAL_LLAMA_KEY
cd "E:/sv-agent-workspace"
exec "E:/sv-agent-data/dsh/node_modules/.bin/dsh" web --no-open
