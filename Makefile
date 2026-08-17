# Browser Agent — Makefile
# 一键操作：启动、测试、部署
# 跨平台支持: Windows (Git Bash/WSL) / Linux / macOS

.PHONY: help start stop test lint clean install health status

# 检测操作系统
ifeq ($(OS),Windows_NT)
    DETECTED_OS := Windows
    RM_CMD := del /f /q
    FIND_CMD := dir /s /b
    PYTHON := python
else
    DETECTED_OS := $(shell uname -s)
    RM_CMD := rm -rf
    FIND_CMD := find
    PYTHON := python3
endif

# 默认目标
help:
	@echo "Browser Agent — 可用命令:"
	@echo ""
	@echo "  make start      启动桥接服务端"
	@echo "  make stop       停止桥接服务端"
	@echo "  make test       运行测试"
	@echo "  make lint       代码检查"
	@echo "  make install    安装开发依赖"
	@echo "  make clean      清理临时文件"
	@echo "  make health     健康检查"
	@echo "  make status     查看状态"
	@echo ""
	@echo "  检测到的 OS: $(DETECTED_OS)"

# 启动服务端
start:
	@echo "🚀 启动 Shizuku Bridge..."
ifeq ($(OS),Windows_NT)
	@cd server && start /B python shizuku_bridge.py
else
	@cd server && python3 shizuku_bridge.py &
endif

# 停止服务端
stop:
	@echo "🛑 停止 Shizuku Bridge..."
ifeq ($(OS),Windows_NT)
	@taskkill /f /im python.exe /fi "WINDOWTITLE eq shizuku_bridge*" 2>nul || echo "未找到运行中的服务"
else
	@pkill -f "shizuku_bridge.py" 2>/dev/null || true
endif

# 运行测试
test:
	@echo "🧪 运行测试..."
	@cd tests && python -m pytest -v

# 代码检查
lint:
	@echo "🔍 代码检查..."
	@cd server && python -m flake8 shizuku_bridge.py browser_manager.py shell_relay.py config.py --max-line-length=120 || true

# 安装开发依赖
install:
	@echo "📦 安装开发依赖..."
	@pip install -r server/requirements.txt

# 清理
clean:
	@echo "🧹 清理临时文件..."
ifeq ($(OS),Windows_NT)
	@cd server && $(RM_CMD) __pycache__ 2>nul || true
	@cd tests && $(RM_CMD) __pycache__ 2>nul || true
	@$(RM_CMD) .pytest_cache 2>nul || true
else
	@find . -type d -name "__pycache__" -exec $(RM_CMD) {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@$(RM_CMD) .pytest_cache 2>/dev/null || true
endif

# 健康检查
health:
	@echo "💓 健康检查..."
	@curl -s http://127.0.0.1:8123/api/health | python -m json.tool

# 查看状态
status:
	@echo "📊 服务端状态..."
	@curl -s http://127.0.0.1:8123/api/browser/state | python -m json.tool
