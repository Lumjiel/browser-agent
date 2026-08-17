#!/bin/bash
# start-bridge.sh — 启动 Browser Bridge 桥接服务
# 用法: bash start-bridge.sh [start|stop|status|restart]
#
# 跨平台支持: Windows (Git Bash) / WSL / Linux / macOS

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
BRIDGE_SCRIPT="server/shizuku_bridge.py"
LOG_FILE="$PROJECT_DIR/bridge.log"
PID_FILE="$PROJECT_DIR/bridge.pid"

# Python 检测（简化版，按优先级）
# 环境变量 > uv run python > python3 > python > py
detect_python() {
    if [[ -n "${PYTHON_CMD:-}" ]]; then
        echo "$PYTHON_CMD"
        return
    fi
    # 有 uv 就用 uv run python（Windows 最可靠）
    if command -v uv &>/dev/null; then
        echo "uv run python"
        return
    fi
    # 标准 python3
    if command -v python3 &>/dev/null; then
        # 检查是否是 Microsoft Store 空壳（Windows）
        local py_path
        py_path=$(command -v python3)
        if [[ "$py_path" == *"WindowsApps"* ]]; then
            : # 跳过空壳
        else
            echo "python3"
            return
        fi
    fi
    if command -v python &>/dev/null; then
        echo "python"
        return
    fi
    if command -v py &>/dev/null; then
        echo "py"
        return
    fi
    echo ""
}

PYTHON_CMD="$(detect_python)"

if [[ -z "$PYTHON_CMD" ]]; then
    echo "❌ 未找到 Python 解释器" >&2
    echo "   请安装 Python 或设置 PYTHON_CMD 环境变量" >&2
    echo "   推荐: uv run python" >&2
    exit 1
fi

is_running() {
    curl -s --max-time 2 http://127.0.0.1:8123/api/health > /dev/null 2>&1
}

stop_bridge() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null || true
        sleep 1
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        echo "🛑 桥接服务已停止 (PID: $PID)"
    else
        if is_running; then
            echo "⚠️ 端口 8123 有服务但无 PID 文件"
            pkill -9 -f "shizuku_bridge.py" 2>/dev/null || true
            echo "🛑 已尝试停止"
        else
            echo "⚠️ 没有运行中的服务"
        fi
    fi
}

case "${1:-start}" in
    start)
        if is_running; then
            echo "✅ 桥接服务已在运行"
            echo "   API: http://127.0.0.1:8123"
            [ -f "$PID_FILE" ] && echo "   PID: $(cat "$PID_FILE")"
            exit 0
        fi
        
        cd "$PROJECT_DIR" || exit 1
        echo "🚀 启动桥接服务 (使用: $PYTHON_CMD)..."
        
        $PYTHON_CMD "$BRIDGE_SCRIPT" > "$LOG_FILE" 2>&1 &
        NEW_PID=$!
        echo "$NEW_PID" > "$PID_FILE"
        
        sleep 2
        
        if is_running; then
            echo "✅ 桥接服务已启动 (PID: $NEW_PID)"
            echo "   API: http://127.0.0.1:8123"
            echo "   日志: $LOG_FILE"
        else
            echo "❌ 启动失败，查看日志: $LOG_FILE"
            cat "$LOG_FILE" 2>/dev/null | tail -20
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;
        
    stop)
        stop_bridge
        ;;
        
    status)
        if is_running; then
            echo "✅ 桥接服务运行中"
            echo "   API: http://127.0.0.1:8123"
            [ -f "$PID_FILE" ] && echo "   PID: $(cat "$PID_FILE")"
        else
            echo "❌ 桥接服务未运行"
        fi
        ;;
        
    restart)
        stop_bridge
        sleep 1
        $0 start
        ;;
        
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
