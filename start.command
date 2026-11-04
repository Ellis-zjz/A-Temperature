#!/bin/bash
# A-Temperature 一键启动脚本（双击即可）
cd "$(dirname "$0")"

PY="/Users/ellis/.workbuddy/binaries/python/envs/default/bin/python"

echo "============================================"
echo "  A-Temperature · A股情绪温度"
echo "  正在计算指标并生成页面…"
echo "============================================"

"$PY" compute.py && "$PY" render.py

echo ""
open index.html
