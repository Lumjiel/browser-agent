# Browser Agent — 浏览器远程控制桥接系统

> 基于 [claude-browser-agent](https://github.com/npezarro/claude-browser-agent) 本地化改造，适配 Android/Termux + XBrowser + Shizuku 环境。

## 架构

```
┌─────────────┐     HTTP      ┌──────────────────┐     rish/ADB     ┌─────────────┐
│  Pi / CLI   │ ◄──────────► │  Python Bridge    │ ◄──────────────► │  XBrowser   │
│  (doubao_ask)│              │  (shizuku_bridge) │                  │  (油猴脚本)  │
└─────────────┘              └──────────────────┘                  └─────────────┘
```

**与原项目的主要差异：**

| 原项目 | 本地化改造 |
|--------|-----------|
| Node.js 服务端 | **Python 3 纯标准库**（无依赖） |
| GM_xmlhttpRequest | **fetch()**（适配 XBrowser） |
| localhost 部署 | **Termux + Shizuku** 环境 |
| 仅浏览器控制 | **+ Shell 命令中继 + AI 问答** |

## 目录结构

```
browser-agent/
├── server/
│   ├── shizuku_bridge.py        # Python 桥接服务端（核心）
│   └── shizuku_bridge.service   # systemd 服务文件
├── userscript/
│   ├── browser-agent-xbrowser.user.js  # 通用浏览器代理（XBrowser 适配）
│   ├── shizuku_userscript.js           # Shizuku 控制台（shell 命令）
│   └── shizuku_doubao.js              # 豆包自动问答桥接
├── cli/
│   └── doubao_ask.py            # 多 AI 问答客户端
├── config/
│   └── config.example.json      # 配置示例
└── docs/
    └── setup.md                 # 安装配置指南
```

## 快速开始

### 1. 启动桥接服务端

```bash
cd server
python3 shizuku_bridge.py
# ✅ Shizuku Bridge 已启动: http://127.0.0.1:8123
```

### 2. 安装油猴脚本

1. 安装 [Tampermonkey](https://www.tampermonkey.net/)（或 XBrowser 内置油猴支持）
2. 安装 `userscript/browser-agent-xbrowser.user.js`
3. 脚本默认连接 `http://127.0.0.1:8123`

### 3. 使用 AI 问答客户端

```bash
# 向豆包提问
python3 cli/doubao_ask.py "什么是 AI Agent？"

# 向 Deepseek 提问
python3 cli/doubao_ask.py "什么是 AI Agent？" -a deepseek

# 多 AI 讨论模式
python3 cli/doubao_ask.py "什么是 AI Agent？" -m

# 打开指定 URL
python3 cli/doubao_ask.py "" -o https://www.doubao.com/chat/
```

## API 接口

### 浏览器代理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/browser/command` | 异步提交命令 |
| POST | `/api/browser/interactive` | 同步执行（阻塞等待结果） |
| POST | `/api/browser/navigate` | 导航到 URL 并等待加载 |
| POST | `/api/browser/ensure` | 确保有 tab 在目标页面（自动启动浏览器） |
| GET | `/api/browser/state` | 获取所有 tab 状态 |
| GET | `/api/browser/commands` | 油猴脚本轮询获取命令 |
| POST | `/api/browser/result` | 油猴脚本回传执行结果 |
| POST | `/api/browser/heartbeat` | 油猴脚本上报页面状态 |
| POST | `/api/browser/log` | 油猴脚本上报日志 |
| GET | `/api/browser/results` | 获取最近执行结果 |
| GET | `/api/browser/logs` | 获取最近日志 |

### Shell 命令 API（需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/shell` | 执行 shell 命令（需 Bearer Token + 白名单） |
| GET | `/api/health` | 健康检查 |

## 支持的命令

### 浏览器 DOM 操作

- `getState` — 获取页面状态（按钮、输入框、文本）
- `getBodyText` — 获取页面正文
- `querySelector` — DOM 查询
- `click` — 点击元素
- `type` — 输入文字
- `navigate` — 导航到 URL
- `eval` — 执行 JavaScript
- `getConsoleLog` — 获取控制台日志
- `screenshot` — 截图

### Shell 命令（白名单）

- `input tap/swipe/text/keyevent` — 模拟输入
- `uiautomator dump` — 获取 UI 树
- `screencap` — 截图
- `am start/force-stop/broadcast` — 应用管理
- `dumpsys` — 设备信息
- `cat/head/tail/ls` — 文件读取（只读）

## 配置

复制 `config/config.example.json` 为 `config/config.json` 并修改：

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

## License

MIT
