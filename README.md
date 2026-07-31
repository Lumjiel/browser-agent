# Browser Agent — 浏览器远程控制桥接系统

> 基于 [claude-browser-agent](https://github.com/npezarro/claude-browser-agent) 本地化改造，适配 Android/Termux + XBrowser + Shizuku 环境。

[![CI](https://github.com/Lumjiel/browser-agent/workflows/CI/badge.svg)](https://github.com/Lumjiel/browser-agent/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 架构

```
┌─────────────┐     HTTP      ┌──────────────────┐     rish/ADB     ┌─────────────┐
│  Pi / CLI   │ ◄──────────► │  Python Bridge    │ ◄──────────────► │  XBrowser   │
│  (ai_ask)   │              │  (shizuku_bridge) │                  │  (油猴脚本)  │
└─────────────┘              └──────────────────┘                  └─────────────┘
```

**与原项目的主要差异：**

| 原项目 | 本地化改造 |
|--------|-----------|
| Node.js 服务端 | **Python 3 纯标准库**（零依赖） |
| GM_xmlhttpRequest | **fetch()**（适配 XBrowser） |
| localhost 部署 | **Termux + Shizuku** 环境 |
| 仅浏览器控制 | **+ Shell 命令中继 + AI 问答** |

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
│   ├── shizuku_bridge.py       ← Python 桥接服务端（核心）
│   ├── shizuku_bridge.service  ← systemd 服务文件
│   └── requirements.txt        ← 开发依赖
├── userscript/
│   ├── browser-agent.user.js   ← 通用浏览器代理（XBrowser 适配）
│   ├── console.user.js         ← ADB Shell 控制台
│   └── ai_bridge.user.js       ← AI 通用问答桥接
├── cli/
│   ├── browser_cli.sh          ← 浏览器控制 CLI（20+ 命令）
│   └── ai_ask.py               ← 多 AI 问答客户端
├── config/
│   └── config.example.json     ← 配置示例
├── docs/
│   ├── setup.md                ← 安装配置指南
│   ├── api.md                  ← API 文档
│   └── architecture.md         ← 架构说明
└── tests/
    ├── test_bridge.py          ← 服务端单元测试
    └── test_cli.sh             ← CLI 集成测试
```

## 快速开始

### 1. 克隆并启动

```bash
git clone https://github.com/Lumjiel/browser-agent.git
cd browser-agent

# 启动桥接服务端
make start
# 或手动: cd server && python3 shizuku_bridge.py
```

### 2. 安装油猴脚本

1. 安装 [Tampermonkey](https://www.tampermonkey.net/)（或 XBrowser 内置油猴支持）
2. 安装 `userscript/browser-agent.user.js`
3. 脚本默认连接 `http://127.0.0.1:8123`

### 3. 使用 CLI

```bash
# 浏览器控制
./cli/browser_cli.sh health
./cli/browser_cli.sh tabs
./cli/browser_cli.sh navigate "https://example.com"
./cli/browser_cli.sh click "Sign In"
./cli/browser_cli.sh text

# AI 问答
python3 cli/ai_ask.py "什么是 AI Agent？"
python3 cli/ai_ask.py "什么是 AI Agent？" -a deepseek
python3 cli/ai_ask.py "什么是 AI Agent？" -m
```

## 功能特性

### 🌐 浏览器控制
- **20+ 命令**：导航、点击、输入、断言、等待、截图等
- **DOM 操作**：querySelector、eval、fillForm、selectOption
- **SPA 支持**：waitForRender、waitForSelector、waitForText
- **Console 捕获**：获取页面 console 日志

### 🤖 AI 问答
- **多平台支持**：豆包、Deepseek、千问等
- **多 AI 讨论模式**：一个问题同时问多个 AI
- **自动页面管理**：自动启动浏览器、导航、等待加载

### 🔧 Shell 命令
- **白名单机制**：只允许安全的命令前缀
- **ADB 模拟输入**：tap、swipe、text、keyevent
- **设备信息**：dumpsys、uiautomator dump、screencap

## API 接口

详见 [docs/api.md](docs/api.md)。

### 浏览器代理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/browser/command` | 异步提交命令 |
| POST | `/api/browser/interactive` | 同步执行（阻塞等待结果） |
| POST | `/api/browser/navigate` | 导航到 URL 并等待加载 |
| POST | `/api/browser/ensure` | 确保有 tab 在目标页面 |
| GET | `/api/browser/state` | 获取所有 tab 状态 |
| POST | `/api/browser/heartbeat` | 油猴脚本上报页面状态 |
| GET | `/api/browser/results` | 获取最近执行结果 |
| GET | `/api/browser/logs` | 获取最近日志 |

### Shell 命令 API（需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/shell` | 执行 shell 命令（Bearer Token + 白名单） |
| GET | `/api/health` | 健康检查 |

## 配置

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8123,
    "token": "你的密钥"
  },
  "browser": {
    "package": "com.mmbox.xbrowser",
    "activity": ".BrowserActivity"
  }
}
```

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

## License

[MIT](LICENSE)
