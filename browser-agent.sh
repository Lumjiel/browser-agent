#!/bin/bash
# browser-agent.sh - 浏览器代理快捷脚本
# 用法:
#   browser-agent.sh state          # 获取页面状态
#   browser-agent.sh click "文本"    # 点击按钮
#   browser-agent.sh input "选择器" "文本"  # 输入文字
#   browser-agent.sh text           # 获取页面文本
#   browser-agent.sh eval "JS代码"   # 执行 JS
#   browser-agent.sh wait "文本"     # 等待文本出现
#   browser-agent.sh results        # 获取执行结果
#   browser-agent.sh logs           # 获取日志
#
# 跨平台支持: Windows (Git Bash) / Linux / macOS

API="http://127.0.0.1:8123/api/browser"
TAB_ID="default"

# 检测可用的 python 命令
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "❌ 未找到 python 命令" >&2
    exit 1
fi

# JSON 格式化函数
json_format() {
    $PY -m json.tool 2>/dev/null || cat
}

case "$1" in
  state)
    curl -s "$API/state" | json_format
    ;;
  click)
    [ -z "$2" ] && { echo "用法: $0 click <文本>"; exit 1; }
    curl -s -X POST "$API/command" \
      -H "Content-Type: application/json" \
      -d "{\"action\":\"click\",\"text\":\"$2\",\"tabId\":\"$TAB_ID\"}"
    ;;
  input|setInput)
    [ -z "$2" ] || [ -z "$3" ] && { echo "用法: $0 input <选择器> <文本>"; exit 1; }
    curl -s -X POST "$API/command" \
      -H "Content-Type: application/json" \
      -d "{\"action\":\"setInput\",\"selector\":\"$2\",\"text\":\"$3\",\"tabId\":\"$TAB_ID\"}"
    ;;
  text)
    curl -s -X POST "$API/command" \
      -H "Content-Type: application/json" \
      -d "{\"action\":\"getBodyText\",\"tabId\":\"$TAB_ID\"}"
    ;;
  eval)
    [ -z "$2" ] && { echo "用法: $0 eval <JS代码>"; exit 1; }
    curl -s -X POST "$API/command" \
      -H "Content-Type: application/json" \
      -d "{\"action\":\"eval\",\"code\":\"$2\",\"tabId\":\"$TAB_ID\"}"
    ;;
  wait)
    [ -z "$2" ] && { echo "用法: $0 wait <文本>"; exit 1; }
    curl -s -X POST "$API/command" \
      -H "Content-Type: application/json" \
      -d "{\"action\":\"waitForText\",\"text\":\"$2\",\"tabId\":\"$TAB_ID\"}"
    ;;
  results)
    curl -s "$API/results" | json_format
    ;;
  logs)
    curl -s "$API/logs" | json_format
    ;;
  *)
    echo "用法: $0 {state|click|input|text|eval|wait|results|logs}"
    exit 1
    ;;
esac
echo ""
