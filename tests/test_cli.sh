#!/usr/bin/env bash
# test_cli.sh — CLI 集成测试
#
# 测试 browser_cli.sh 的基本功能
# 需要先启动服务端: cd server && python3 shizuku_bridge.sh

set -euo pipefail

CLI="../cli/browser_cli.sh"
API="${BRIDGE_URL:-http://127.0.0.1:8123}"
PASS=0
FAIL=0

# ── 测试框架 ──

assert_ok() {
  local desc="$1"
  if eval "$2" > /dev/null 2>&1; then
    echo "  ✅ $desc"
    ((PASS++))
  else
    echo "  ❌ $desc"
    ((FAIL++))
  fi
}

assert_contains() {
  local desc="$1"
  local cmd="$2"
  local expected="$3"
  if eval "$cmd" 2>/dev/null | grep -q "$expected"; then
    echo "  ✅ $desc"
    ((PASS++))
  else
    echo "  ❌ $desc (expected: $expected)"
    ((FAIL++))
  fi
}

# ── 测试用例 ──

echo "🧪 CLI 集成测试"
echo ""

echo "📋 基础命令:"
assert_ok "health 命令" "$CLI health"
assert_ok "help 命令" "$CLI help"
assert_ok "tabs 命令" "$CLI tabs"
assert_ok "results 命令" "$CLI results"
assert_ok "logs 命令" "$CLI logs"

echo ""
echo "📋 健康检查:"
assert_contains "health 返回 status" "$CLI health" "ok"

echo ""
echo "📋 浏览器控制 (需要油猴脚本运行):"
# 以下测试需要浏览器连接，仅在可选模式下运行
if curl -s "$API/api/browser/state" | jq -e '.tabs | length > 0' > /dev/null 2>&1; then
  assert_ok "state 命令" "$CLI state"
  assert_ok "text 命令" "$CLI text"
  assert_ok "ping 命令" "$CLI ping"
else
  echo "  ⚠️ 无浏览器 tab 连接，跳过浏览器控制测试"
fi

# ── 结果 ──

echo ""
echo "========================"
echo "结果: $PASS 通过, $FAIL 失败"
echo "========================"

if [ $FAIL -gt 0 ]; then
  exit 1
fi
