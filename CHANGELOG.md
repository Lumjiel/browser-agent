# Browser Agent — Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 新增 `cli/browser_cli.sh` — 浏览器控制 CLI 工具（20+ 命令）
- 新增 `cli/ai_client.py` — 多 AI 问答客户端（支持豆包/DeepSeek/千问）
- 新增 `userscript/console.user.js` — ADB Shell 控制台
- 新增 `config/config.example.json` — 配置示例
- 新增 `docs/setup.md` — 安装配置指南
- 新增 `docs/api.md` — 完整 API 文档
- 新增 `docs/architecture.md` — 架构说明文档
- 新增 `server/requirements.txt` — 开发依赖声明
- 新增 `Makefile` — 一键操作
- 新增 `.github/workflows/ci.yml` — CI 自动化
- 新增 `tests/` — 单元测试和集成测试框架
- 新增 `server/config.py` — 配置加载模块
- 新增 `server/browser_manager.py` — Tab 管理 + 导航逻辑
- 新增 `server/shell_relay.py` — Shell 命令中继 + 白名单

### Changed
- 项目结构重组：按 server/userscript/cli/config/docs 分类
- 重命名脚本为通用名称（doubao_ask.py → ai_ask.py）
- 更新 README.md 反映本地化架构
- 更新 .gitignore 忽略原始参考文件
- 服务端从单文件拆分为 4 个模块（config/browser_manager/shell_relay/shizuku_bridge）
- 配置加载改为读取 config.json，不再硬编码
- 油猴脚本 HTTP 策略改为 fetch 优先（GM_xmlhttpRequest 在 XBrowser 中不可用）

### Removed
- 移除对 Node.js 服务端依赖（纯 Python 实现）
- 删除 7 个原始参考文件（agent-server.js, browser-agent.user.js, browser-cli.sh, deploy.sh, ecosystem.config.js, install.html, package.json）
- 删除有问题的 v3.0 油猴脚本（GM_xmlhttpRequest 优先策略不兼容 XBrowser）

### Fixed
- 修复 `find_tab_on_domain` 跳过超过 60 秒无心跳的 tab
- 修复 `cmd_id_counter` 在模块化后的引用问题
- 修复 `ai_client.py` 中 agents.yaml 路径问题

## [1.0.0] - 2024-07-28

### Added
- 初始版本：基于 claude-browser-agent 本地化改造
- Python 桥接服务端（shizuku_bridge.py）
- XBrowser 适配油猴脚本
- Shizuku 控制台脚本
