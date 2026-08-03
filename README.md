# Browser Agent — 浏览器远程控制桥接系统

> 基于 [claude-browser-agent](https://github.com/npezarro/claude-browser-agent) 本地化改造，适配 Android/Termux + XBrowser + Shizuku 环境。

[![CI](https://github.com/Lumjiel/browser-agent/workflows/CI/badge.svg)](https://github.com/Lumjiel/browser-agent/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 架构

```
┌──────────────────────────────────────────────┐
│  上层客户端（不属于本仓库）                     │
│  任何 HTTP 客户端：curl / Python / AI 问答工具  │
└──────────────────────────────────────────────┘
│      → 调 server API + 配置中的 selector        │
└──────────────────────────────────────────────┘
                    ↑
                    │ HTTP 调用
                    │
┌──────────────────────────────────────────────┐
│  shizuku_bridge.py（服务器端 · 通用）            │
│  ├── /api/browser/ensure   确保在目标页面       │
│  ├── /api/browser/navigate 导航+等待加载       │
│  ├── /api/browser/interactive  同步 DOM 操作   │
│  ├── /api/browser/command  异步 DOM 操作       │
│  ├── /api/browser/state    tab 状态            │
│  ├── /api/browser/commands 油猴脚本轮询命令     │
│  ├── /api/browser/result   油猴脚本回传结果     │
│  ├── /api/browser/heartbeat  油猴脚本心跳      │
│  └── /api/shell            ADB 命令中继        │
└──────────────────────────────────────────────┘
                    ↑
                    │ HTTP 轮询
                    │
┌──────────────────────────────────────────────┐
│  browser-agent-xbrowser.user.js（油猴脚本）     │
│  ├── 每 2 秒轮询获取命令                        │
│  ├── 执行 DOM 操作（type/click/eval/...）       │
│  ├── 回传执行结果                               │
│  └── 心跳上报页面状态                           │
└──────────────────────────────────────────────┘
```

**设计原则**：
- **本仓库只含通用桥接层**（导航、DOM 命令中继、tab 管理、Shell 中继），不含任何平台/业务逻辑
- AI 问答客户端（ai_client.py + 平台配置）属于个人业务需求，已迁出至 `~/tools/ai-ask/`

## 目录结构

```
browser-agent/
├── README.md                   ← 本文件
├── LICENSE                     ← MIT 许可证
├── CHANGELOG.md                ← 变更日志
├── Makefile                    ← 一键操作
├── .github/
│   └── workflows/ci.yml       ← CI 自动化
├── server/
│   ├── shizuku_bridge.py       ← 主入口（HTTP 路由）
│   ├── browser_manager.py      ← Tab 管理 + 导航逻辑
│   ├── shell_relay.py          ← Shell 命令中继 + 白名单
│   ├── config.py               ← 配置加载
│   ├── shizuku_bridge.service  ← systemd 服务文件
│   └── requirements.txt        ← 开发依赖
├── userscript/
│   ├── browser-agent-xbrowser.user.js  ← 通用浏览器代理（XBrowser 适配）
│   └── console.user.js                 ← ADB Shell 控制台
├── cli/
│   └── browser_cli.sh          ← 浏览器控制 CLI（20+ 命令）
├── config/
│   └── config.example.json     ← 服务端配置示例
├── docs/
│   ├── setup.md                ← 安装配置指南
│   ├── api.md                  ← API 文档
│   └── architecture.md         ← 架构说明
└── tests/
    ├── test_bridge.py          ← 服务端单元测试
    └── test_cli.sh             ← CLI 集成测试
```

## 快速开始

### 1. 启动桥接服务

```bash
# 方式一：Makefile
make start

# 方式二：启动脚本
bash ~/start-bridge.sh start

# 方式三：手动
cd server && python3 shizuku_bridge.py
```

验证：`curl -s http://127.0.0.1:8123/api/health`

### 2. 安装油猴脚本

1. XBrowser → 油猴管理 → 新建脚本
2. 粘贴 `userscript/browser-agent-xbrowser.user.js` 内容
3. 保存启用

### 3. AI 问答（已迁出本仓库）

AI 问答客户端属于个人业务需求，已迁至 `~/tools/ai-ask/`（通用引擎 + `agents/<平台>/` 配置目录），不在本仓库维护。

### 4. 浏览器控制 CLI

```bash
./cli/browser_cli.sh health
./cli/browser_cli.sh tabs
./cli/browser_cli.sh navigate "https://example.com"
./cli/browser_cli.sh click "Sign In"
./cli/browser_cli.sh text
```

## 功能特性

### 🌐 浏览器控制
- **20+ 命令**：导航、点击、输入、断言、等待、截图等
- **DOM 操作**：querySelector、eval、fillForm、selectOption
- **SPA 支持**：waitForRender、waitForSelector、waitForText
- **Console 捕获**：获取页面 console 日志

### 🤖 AI 问答（已迁出）
- 问答客户端与平台配置属于个人业务需求，已迁至 `~/tools/ai-ask/`
- 本仓库只提供通用桥接 API，任何客户端可对接

### 🔧 Shell 命令
- **白名单机制**：只允许安全的命令前缀
- **ADB 模拟输入**：tap、swipe、text、keyevent
- **设备信息**：dumpsys、uiautomator dump、screencap

## 平台配置（已迁出）

AI 平台配置（selector、角色、提示词）已迁至 `~/tools/ai-ask/agents/<平台>/`，与本仓库解耦。

## API 接口

详见 [docs/api.md](docs/api.md)。

### 浏览器代理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/browser/ensure` | 确保在目标页面（自动启动浏览器） |
| POST | `/api/browser/navigate` | 导航到 URL 并等待加载 |
| POST | `/api/browser/interactive` | 同步执行（阻塞等待结果） |
| POST | `/api/browser/command` | 异步提交命令 |
| GET | `/api/browser/state` | 获取所有 tab 状态 |
| POST | `/api/browser/heartbeat` | 油猴脚本上报页面状态 |
| GET | `/api/browser/results` | 获取最近执行结果 |
| GET | `/api/browser/logs` | 获取最近日志 |

### Shell 命令 API（需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/shell` | 执行 shell 命令（Bearer Token + 白名单） |
| GET | `/api/health` | 健康检查 |

## 安全说明

- Shell 命令使用**白名单机制**，只允许特定前缀的命令
- API Token 通过 `Authorization: Bearer` 头部传递
- 浏览器端接口无需鉴权（同域轮询）
- 建议仅在本地使用，不要暴露到公网

## 环境要求

- Android 设备（vivo PA2170 平板测试通过）
- Termux + Python 3
- Shizuku + rish（ADB shell 权限）
- XBrowser（或其他支持油猴的浏览器）

## 开发

```bash
# 安装开发依赖
make install

# 运行测试
make test

# 代码检查
make lint

# 一键操作
make help
```

## 已知问题

| 问题 | 原因 | 状态 |
|------|------|------|
| 千问输入失败 | 千问用 contenteditable div，`type` 命令不兼容 | 待修复 |
| `GM_xmlhttpRequest` 优先策略在 XBrowser 中不可用 | XBrowser 限制 | 已修复，使用 fetch 优先 |

## License

[MIT](LICENSE)
