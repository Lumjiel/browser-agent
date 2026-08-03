#!/bin/bash
# start-bridge.sh — 启动 Browser Agent 桥接服务
# 用法: bash ~/start-bridge.sh [start|stop|status]

PROJECT_DIR="$HOME/projects/browser-agent/server"
LOG_FILE="$PREFIX/tmp/bridge.log"
PID_FILE="$PREFIX/tmp/bridge.pid"

case "${1:-start}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "✅ 桥接服务已在运行 (PID: $(cat "$PID_FILE"))"
      exit 0
    fi
    cd "$PROJECT_DIR" || exit 1
    python3 shizuku_bridge.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "✅ 桥接服务已启动 (PID: $(cat "$PID_FILE"))"
      echo "   API: http://127.0.0.1:8123"
      echo "   日志: $LOG_FILE"
    else
      echo "❌ 启动失败，查看日志: $LOG_FILE"
      cat "$LOG_FILE"
      exit 1
    fi
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null
      rm -f "$PID_FILE"
      echo "🛑 桥接服务已停止"
    else
      echo "⚠️ 没有运行中的服务"
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "✅ 桥接服务运行中 (PID: $(cat "$PID_FILE"))"
      curl -s http://127.0.0.1:8123/api/health | python3 -m json.tool 2>/dev/null
    else
      echo "❌ 桥接服务未运行"
    fi
    ;;
  *)
    echo "用法: $0 [start|stop|status]"
    exit 1
    ;;
esac
