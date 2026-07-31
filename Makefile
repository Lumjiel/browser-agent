# Browser Agent — Makefile
# 一键操作：启动、测试、部署

.PHONY: help start stop test lint clean install

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
	@echo "  make docs       查看文档"

# 启动服务端
start:
	@echo "🚀 启动 Shizuku Bridge..."
	@cd server && python3 shizuku_bridge.py &

# 停止服务端
stop:
	@echo "🛑 停止 Shizuku Bridge..."
	@pkill -f "shizuku_bridge.py" 2>/dev/null || true

# 运行测试
test:
	@echo "🧪 运行测试..."
	@cd tests && python3 -m pytest -v

# 代码检查
lint:
	@echo "🔍 代码检查..."
	@cd server && python3 -m flake8 shizuku_bridge.py --max-line-length=120 || true

# 安装开发依赖
install:
	@echo "📦 安装开发依赖..."
	@pip3 install -r server/requirements.txt

# 清理
clean:
	@echo "🧹 清理临时文件..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true

# 健康检查
health:
	@echo "💓 健康检查..."
	@curl -s http://127.0.0.1:8123/api/health | python3 -m json.tool

# 查看状态
status:
	@echo "📊 服务端状态..."
	@curl -s http://127.0.0.1:8123/api/browser/state | python3 -m json.tool
