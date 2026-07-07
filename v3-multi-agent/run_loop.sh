#!/bin/bash
# AI 知识库 — 本地定时采集循环
# 用法: bash run_loop.sh [间隔分钟数，默认5]

INTERVAL=${1:-5}
echo "=== 知识库自动采集启动 ==="
echo "间隔: ${INTERVAL} 分钟 | Ctrl+C 停止"
echo ""

while true; do
    echo ">>> $(date '+%H:%M:%S') 开始采集..."
    python3 pipeline/pipeline.py --sources github --limit 5
    python3 hooks/validate_json.py knowledge/articles/*.json 2>/dev/null
    python3 hooks/check_quality.py knowledge/articles/*.json 2>/dev/null
    echo ""
    echo "--- 下次采集: $(date -d "+${INTERVAL} min" '+%H:%M:%S' 2>/dev/null || date -v+${INTERVAL}M '+%H:%M:%S') ---"
    echo ""
    sleep $((INTERVAL * 60))
done