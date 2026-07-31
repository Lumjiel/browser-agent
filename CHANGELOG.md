# Browser Agent — Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 新增 `cli/browser_cli.sh` — 浏览器控制 CLI 工具（20+ 命令）
- 新增 `cli/ai_ask.py` — 多 AI 问答客户端（支持豆包/Deepseek/千问）
- 新增 `userscript/ai_bridge.user.js` — AI 通用问答桥接脚本
- 新增 `userscript/console.user.js` — ADB Shell 控制台
- 新增 `config/config.example.json` — 配置示例
- 新增 `docs/setup.md` — 安装配置指南
- 新增 `server/requirements.txt` — 开发依赖声明
- 新增 `Makefile` — 一键操作
- 新增 `.github/workflows/ci.yml` — CI 自动化
- 新增 `tests/` — 测试框架

### Changed
- 项目结构重组：按 server/userscript/cli/config/docs 分类
- 重命名脚本为通用名称（doubao_ask.py → ai_ask.py 等）
- 更新 README.md 反映本地化架构
- 更新 .gitignore 忽略原始参考文件

### Removed
- 移除对 Node.js 服务端依赖（纯 Python 实现）

## [1.0.0] - 2024-07-28

### Added
- 初始版本：基于 claude-browser-agent 本地化改造
- Python 桥接服务端（shizuku_bridge.py）
- XBrowser 适配油猴脚本
- Shizuku 控制台脚本
