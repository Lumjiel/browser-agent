# Browser Agent — Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.1] - 2026-08-17

### Added
- 新增 `agents/deepseek/` 目录：完整的 DeepSeek 讨论调度器 skill
- 新增 `scripts/ask-deepseek-free.sh` v3.1.1：多轮对话、目标驱动、死路注册、事实注入
- 新增文件上传功能：base64 + DataTransfer 注入，支持多文件，自动截断
- 新增 `--context` 模式：自动扫描本地文件上传
- 新增 `--goal`/`--dead`/`--round`/`--free` 参数
- 新增策略系统：`agents/deepseek/strategies/` 目录

### Changed
- `server/browser_manager.py`：跨平台支持（Android + Windows）
- `server/shell_relay.py`：跨平台支持，桌面端直接执行
- `server/shizuku_bridge.py`：修复 interactive 自动解析 tabId
- 发送按钮选择器修复：改为动态查找最后一个 primary circle 按钮

### Fixed
- 修复 `interactive` 不传 tabId 超时问题
- 修复文件上传路径：Windows 使用 `/mnt/` 前缀
- 修复客户端检测：使用 `/api/browser/state` 替代 `/api/clients`

 ## [Unreleased]
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
