#!/bin/bash
# test_health.sh — ask-deepseek 健康检查
# 本文件位于 agents/deepseek/test_health.sh
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "🔍 检查: ask-deepseek"

# 检查核心文件 (与本文件同级)
for f in SKILL.md meta.json goal.txt facts.txt dead_ends.txt; do
  [ -f "$SKILL_DIR/$f" ] || { echo "❌ 缺少 $f"; exit 1; }
done

# 检查脚本 (位于项目 scripts/ 目录)
SCRIPT_DIR="$SKILL_DIR/../../scripts"
[ -f "$SCRIPT_DIR/ask-deepseek-free.sh" ] || { echo "❌ 缺少 scripts/ask-deepseek-free.sh"; exit 1; }

# 检查桥接服务 (带超时)
if curl -s --max-time 3 http://127.0.0.1:8123/api/health > /dev/null 2>&1; then
  echo "✅ 桥接服务正常"
else
  echo "⚠️  桥接服务未运行（使用时需启动）"
fi

echo "✅ 通过"
