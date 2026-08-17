# Browser Agent — 浏览器远程控制桥接

**HTTP → 油猴脚本 → 浏览器 DOM**，零外部依赖，纯标准库实现。

*跨平台：Android/Termux + Windows · AI Agent 的浏览器手和眼*

[![CI](https://github.com/Lumjiel/browser-agent/workflows/CI/badge.svg)](https://github.com/Lumjiel/browser-agent/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[快速开始](#-quick-start) · [API 接口](#-api-接口) · [CLI 命令](#-cli-命令) · [DeepSeek 讨论](#-deepseek-讨论) · [架构](#-架构) · [配置](#-配置)

---

## 😤 问题

你的 AI Agent 需要操作浏览器：查资料、填表单、抓数据。

| 方案 | 问题 |
|------|------|
| Selenium/Playwright | Android Termux 装不了，需要 Chrome + 驱动 |
| js_shooters（纯 fetch） | 只能抓静态页面，无法操作 DOM |
| 手动复制粘贴 | 慢、脆、不能自动化 |

**你需要一个轻量桥接层，让任何 HTTP 客户端都能控制浏览器。**

---

## ✅ 方案

Browser Agent 启动一个 HTTP 服务，通过油猴脚本桥接到浏览器 DOM：

```
你的脚本/curl/AI 工具
        │
        ▼ HTTP POST
┌─────────────────────┐
│  shizuku_bridge.py  │  ← Python，纯标准库，端口 8123
│  (127.0.0.1:8123)   │
└─────────────────────┘
        │
        ▼ HTTP 轮询（每 2s）
┌─────────────────────┐
│  油猴脚本           │  ← XBrowser/Chrome 中运行
│  (浏览器内)         │
└─────────────────────┘
        │
        ▼ DOM 操作
   目标网页
```

**特点**：
- 服务端零依赖（纯 Python 标准库）
- 跨平台：Android/Termux + Windows
- 油猴脚本 fetch 优先（兼容 XBrowser/Chrome）
- Shell 命令白名单 + Token 鉴权 + 注入检测

---

## 🚀 Quick Start

### Windows

```bash
# 1. 克隆
git clone https://github.com/Lumjiel/browser-agent
cd browser-agent

# 2. 启动服务
bash start-bridge.sh start
# ✅ 桥接服务已启动: http://127.0.0.1:8123

# 3. 安装油猴脚本
# Chrome → Tampermonkey → 新建 → 粘贴 userscript/browser-agent-xbrowser.user.js

# 4. 控制浏览器
curl -s -X POST http://127.0.0.1:8123/api/browser/interactive \
  -H "Content-Type: application/json" \
  -d '{"action":"navigate","url":"https://example.com"}'
```

### Android/Termux

```bash
# 1. 克隆
git clone https://github.com/Lumjiel/browser-agent
cd browser-agent

# 2. 启动服务
python3 server/shizuku_bridge.py

# 3. 安装油猴脚本
# XBrowser → 油猴管理 → 新建 → 粘贴 userscript/browser-agent-xbrowser.user.js

# 4. 控制浏览器
curl -s -X POST http://127.0.0.1:8123/api/browser/interactive \
  -H "Content-Type: application/json" \
  -d '{"action":"navigate","url":"https://example.com"}'
```

---

## 📊 API 接口

### 浏览器代理（无需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/browser/ensure` | 确保有 tab 在目标页面（自动开浏览器） |
| POST | `/api/browser/navigate` | 导航到 URL 并等待加载 |
| POST | `/api/browser/interactive` | **同步执行**（阻塞等待结果） |
| POST | `/api/browser/command` | **异步提交**（立即返回 cmdId） |
| GET  | `/api/browser/state` | 获取所有 tab 状态 |
| GET  | `/api/browser/commands` | 油猴脚本轮询获取命令 |
| POST | `/api/browser/result` | 油猴脚本回传执行结果 |
| POST | `/api/browser/heartbeat` | 油猴脚本上报页面状态 |
| POST | `/api/browser/log` | 油猴脚本上报日志 |
| GET  | `/api/browser/results` | 获取最近执行结果 |
| GET  | `/api/browser/logs` | 获取最近日志 |

### Shell 命令（需 Bearer Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/shell` | 执行 Shell 命令（白名单 + Token + 注入检测） |
| GET  | `/api/health` | 健康检查 |

### 同步 vs 异步

| 模式 | 端点 | 适用场景 |
|------|------|----------|
| 同步 | `/api/browser/interactive` | 需要立即拿到结果，≤ 30s |
| 异步 | `/api/browser/command` | 长时间操作，通过 `/result` 回传 |

---

## 💻 CLI 命令

### browser_cli.sh

```bash
# 基础
./cli/browser_cli.sh health              # 健康检查
./cli/browser_cli.sh tabs                # 列出所有 tab
./cli/browser_cli.sh state               # 查看 tab 详情

# 导航
./cli/browser_cli.sh navigate "https://example.com"

# DOM 操作
./cli/browser_cli.sh click "Sign In"
./cli/browser_cli.sh type "#email" "user@example.com"
./cli/browser_cli.sh text                 # 获取页面文本
./cli/browser_cli.sh eval "document.title" # 执行 JS

# 其他
./cli/browser_cli.sh screenshot           # 截图
```

环境变量：`BRIDGE_URL`（默认 `http://127.0.0.1:8123`）、`BRIDGE_TAB`（指定 tab）。

### browser-agent.sh

```bash
bash browser-agent.sh state                # 获取页面状态
bash browser-agent.sh click "文本"          # 点击按钮
bash browser-agent.sh input "选择器" "文本"  # 输入文字
bash browser-agent.sh text                 # 获取页面文本
bash browser-agent.sh eval "JS代码"        # 执行 JS
bash browser-agent.sh wait "文本"          # 等待文本出现
```

---

## 🤖 DeepSeek 讨论

内置 DeepSeek 自由讨论调度器，支持多轮对话、目标驱动、文件上传。

```bash
# 纯提问
bash scripts/ask-deepseek-free.sh "问题"

# 带文件上传（支持多文件）
bash scripts/ask-deepseek-free.sh "分析这个文件" --file /mnt/e/test.txt

# 自动扫描本地文件
bash scripts/ask-deepseek-free.sh --context "关键词" "问题"

# 多轮追问
bash scripts/ask-deepseek-free.sh --round 2 "追问内容"

# 切换目标
bash scripts/ask-deepseek-free.sh --goal "新目标"

# 注册死路
bash scripts/ask-deepseek-free.sh --dead "被否决的方向"

# 自由讨论（忽略目标）
bash scripts/ask-deepseek-free.sh --free "问题"
```

**特性**：
- 自动注入 `goal.txt` 作为讨论目标
- 自动注入 `dead_ends.txt` 排除已否决方向
- 第 1 轮注入 `facts.txt` 减少幻觉
- 文件上传：base64 + DataTransfer 注入，支持多文件，自动截断
- 复用已有 tab 保持多轮对话上下文

详见 [`agents/deepseek/SKILL.md`](agents/deepseek/SKILL.md)

---

## 🔧 Shell 命令中继

通过 Shizuku/桌面 Shell 执行命令，**白名单 + Token + 注入检测** 三重安全：

```bash
curl -s -X POST http://127.0.0.1:8123/api/shell \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer MY_SECRET_123456" \
  -d '{"cmd": "input tap 500 800"}'
```

**白名单前缀**：

| 类型 | 允许的命令前缀 |
|------|---------------|
| 输入模拟 | `input tap`、`input swipe`、`input text`、`input keyevent` |
| UI 获取 | `uiautomator dump`、`screencap` |
| 应用管理 | `am start`、`am force-stop`、`am broadcast` |
| 设备信息 | `dumpsys`、`pm list`、`cmd package` |
| 文件读取 | `cat `、`head `、`tail `、`ls `、`stat `、`wc ` |
| 工具 | `echo `、`grep `、`pidof`、`which` |

**注入检测**：自动拒绝包含 `;`、`&&`、`||`、`\|`、`` ` ``、`$()`、换行 的命令。

---

## 🏗 架构

```
┌─────────────────────────────────────────────────┐
│  客户端（任何 HTTP 工具）                          │
│  curl / Python / ai_client / browser_cli.sh      │
└─────────────────────────────────────────────────┘
                      │ HTTP
                      ▼
┌─────────────────────────────────────────────────┐
│  shizuku_bridge.py (HTTP Server · 纯标准库)       │
│  ├── 浏览器 API：ensure / navigate / interactive  │
│  ├── 命令队列：command → commands → result        │
│  ├── Tab 管理：state / heartbeat                  │
│  └── Shell API：白名单 + Token + 注入检测        │
└─────────────────────────────────────────────────┘
                      │ HTTP 轮询（每 2s）
                      ▼
┌─────────────────────────────────────────────────┐
│  browser-agent-xbrowser.user.js（油猴脚本）       │
│  ├── 轮询 /api/browser/commands                   │
│  ├── 执行 DOM 操作（type / click / eval / ...）   │
│  └── 回传 /api/browser/result + heartbeat        │
└─────────────────────────────────────────────────┘
```

**模块拆分**：

| 文件 | 职责 |
|------|------|
| `server/shizuku_bridge.py` | HTTP 路由 + 入口 |
| `server/browser_manager.py` | Tab 管理 + 导航 + 命令队列（跨平台） |
| `server/shell_relay.py` | Shell 白名单校验 + 执行（跨平台） |
| `server/config.py` | 配置加载 |

---

## ⚙️ 配置

`config/config.example.json` → 复制为 `config.json`：

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8123,
    "token": "MY_SECRET_123456"
  },
  "browser": {
    "package": "",
    "activity": ""
  },
  "features": {
    "shell_whitelist": true,
    "auto_launch_browser": true,
    "log_results": true,
    "max_results": 500,
    "max_logs": 200
  }
}
```

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `server.host` | `127.0.0.1` | 监听地址（不建议暴露公网） |
| `server.port` | `8123` | 监听端口 |
| `server.token` | — | Shell API 的 Bearer Token |
| `browser.package` | — | Android 浏览器包名（留空则桌面端） |
| `features.shell_whitelist` | `true` | Shell 白名单开关 |

---

## 📁 项目结构

```
browser-agent/
├── agents/
│   └── deepseek/
│       ├── SKILL.md                  # DeepSeek 讨论调度器文档 (v3.1.1)
│       ├── meta.json               # Skill 元数据
│       ├── goal.txt                # 只读目标区（自动注入 prompt）
│       ├── facts.txt               # 本地环境事实（减少幻觉）
│       ├── dead_ends.txt          # 死路注册表（排除约束）
│       ├── test_health.sh          # 健康检查脚本
│       └── strategies/             # 策略模板（adversarial_review 等）
├── scripts/
│   ├── ask-deepseek-free.sh      # DeepSeek 免费版脚本（v3.1.1 · 主脚本）
│   └── ask-deepseek.sh           # DeepSeek 问答脚本（旧版）
├── cli/
│   └── browser_cli.sh            # 浏览器 CLI（20+ 命令）
├── server/
│   ├── shizuku_bridge.py         # HTTP 主入口（纯标准库）
│   ├── browser_manager.py        # Tab 管理（跨平台：Android + Windows）
│   ├── shell_relay.py            # Shell 命令中继（白名单 + Token）
│   ├── config.py                 # 配置加载
│   └── requirements.txt          # 开发依赖
├── userscript/
│   ├── browser-agent-xbrowser.user.js  # XBrowser/Chrome 油猴脚本
│   └── console.user.js                 # ADB Shell 控制台
├── config/
│   └── config.example.json       # 配置示例
├── docs/
│   ├── api.md                    # 完整 API 文档
│   ├── setup.md                  # 安装配置指南
│   └── architecture.md           # 架构详解
├── tests/
│   ├── test_bridge.py            # 服务端单元测试
│   └── test_cli.sh               # CLI 集成测试
├── Makefile                      # make start / stop / test / lint
├── CHANGELOG.md                  # 变更日志
└── LICENSE                       # MIT
```

---

## 🧪 开发

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

**测试覆盖**：服务端单元测试（pytest）+ CLI 集成测试（bash）。

---

## 📜 License

[MIT](LICENSE)
