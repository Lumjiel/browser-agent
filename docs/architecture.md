# 架构说明

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         控制端 (Pi / CLI)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ browser_cli  │  │  ai_ask.py   │  │   future clients     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
└─────────┼─────────────────┼─────────────────────┼──────────────┘
          │                 │                     │
          ▼                 ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Python Bridge (shizuku_bridge.py)             │
│                    http://127.0.0.1:8123                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  HTTP Server (ThreadingHTTPServer)                       │    │
│  │  ├── /api/browser/*   ← 浏览器代理接口                   │    │
│  │  ├── /api/shell       ← Shell 命令接口（需鉴权）         │    │
│  │  └── /api/health      ← 健康检查                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  状态管理                                               │    │
│  │  ├── browser_tabs      ← tab 状态字典                   │    │
│  │  ├── browser_commands  ← 命令队列（per tab）             │    │
│  │  ├── browser_results   ← 结果环形缓冲区                  │    │
│  │  ├── browser_logs      ← 日志环形缓冲区                  │    │
│  │  └── result_waiters    ← 同步等待器                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
          │                                           │
          ▼                                           ▼
┌─────────────────────────┐           ┌─────────────────────────┐
│    油猴脚本（浏览器端）    │           │    Shizuku / ADB       │
│  ┌───────────────────┐  │           │  ┌───────────────────┐  │
│  │ browser-agent     │  │           │  │ rish (ADB shell)  │  │
│  │ (轮询执行 DOM 操作)│  │           │  │  ├── input tap    │  │
│  └───────────────────┘  │           │  │  ├── input swipe  │  │
│  ┌───────────────────┐  │           │  │  ├── input text   │  │
│  │ ai_bridge         │  │           │  │  ├── screencap    │  │
│  │ (AI 问答桥接)      │  │           │  │  └── uiautomator  │  │
│  └───────────────────┘  │           │  └───────────────────┘  │
│  ┌───────────────────┐  │           └─────────────────────────┘
│  │ console           │  │
│  │ (ADB Shell 控制台) │  │
│  └───────────────────┘  │
└─────────────────────────┘
```

## 核心组件

### 1. shizuku_bridge.py（服务端）

**职责：**
- HTTP 请求路由和处理
- 浏览器 tab 状态管理
- 命令队列分发
- Shell 命令安全中继

**关键设计：**
- **纯标准库**：无外部依赖，适合 Termux 环境
- **线程安全**：使用 `threading.Lock` 保护共享状态
- **同步等待**：`result_waiters` 字典 + `threading.Event` 实现同步执行
- **环形缓冲区**：`browser_results` 和 `browser_logs` 自动清理旧数据

### 2. 油猴脚本（浏览器端）

**browser-agent.user.js：**
- 每 2 秒轮询 `/api/browser/commands`
- 执行 DOM 操作（click、type、eval 等）
- 上报状态到 `/api/browser/heartbeat` 和 `/api/browser/result`

**ai_bridge.user.js：**
- AI 平台页面专用桥接
- 自动输入问题、获取回答

**console.user.js：**
- 提供浏览器内 ADB Shell 控制台
- 通过 HTTP 调用服务端 Shell API

### 3. CLI 工具

**browser_cli.sh：**
- 20+ 浏览器控制命令
- 同步执行，阻塞等待结果

**ai_ask.py：**
- 多 AI 平台问答客户端
- 支持单问、多问、多 AI 讨论模式

## 数据流

### 浏览器控制流程

```
1. CLI 发送 POST /api/browser/interactive
2. Bridge 生成 cmd_id，将命令加入 browser_commands[tab_id]
3. Bridge 创建 Event，存入 result_waiters[cmd_id]
4. 油猴脚本轮询 GET /api/browser/commands?tabId=xxx
5. 油猴脚本执行命令
6. 油猴脚本 POST /api/browser/result 回传结果
7. Bridge 找到对应 Event，set() 唤醒
8. CLI 收到响应
```

### AI 问答流程

```
1. ai_ask.py 调用 /api/browser/ensure 确保页面
2. ai_ask.py 发送 type 命令输入问题
3. ai_ask.py 发送 eval 命令点击发送
4. 等待 AI 回答渲染
5. ai_ask.py 发送 eval 命令提取回答文本
```

## 安全机制

### Shell 命令白名单

```python
ALLOWED_PREFIXES = (
    "input tap", "input swipe", "input text", "input keyevent",
    "uiautomator dump", "screencap",
    "am start", "am force-stop", "am broadcast",
    "dumpsys", "pm list", "pm path", "pm clear",
    "wm size", "wm density",
    "cmd package",
    "settings get", "settings put",
    "logcat",
    "cat ", "head ", "tail ", "ls ", "stat ", "wc ",
    "echo ", "grep ", "pidof", "which",
)
```

- 只允许特定前缀的命令
- 只读文件操作（cat/head/tail），不写
- 每次命令 15 秒超时

### API 鉴权

- 浏览器代理接口：无需认证（同域轮询）
- Shell 命令接口：需要 Bearer Token

## 扩展指南

### 添加新的浏览器命令

1. 在 `browser-agent.user.js` 的 `execCommand` 函数中添加新的 `case`
2. 在 `browser_cli.sh` 中添加对应的 CLI 命令
3. 在 `docs/api.md` 中记录

### 添加新的 AI 平台

1. 在 `ai_ask.py` 的 `AGENTS` 字典中添加配置
2. 配置包括：URL、输入框选择器、回答选择器等

### 添加新的 Shell 白名单

1. 在 `shizuku_bridge.py` 的 `ALLOWED_PREFIXES` 中添加前缀
