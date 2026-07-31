# API 文档

## 认证

### Shell 命令接口
需要 Bearer Token：
```
Authorization: Bearer YOUR_TOKEN
```

### 浏览器代理接口
无需认证（同域轮询机制）。

---

## 浏览器代理 API

### POST /api/browser/interactive

同步执行命令，阻塞等待结果。

**请求体：**
```json
{
  "action": "click",
  "selector": "#submit-btn",
  "tabId": "tab123",
  "timeout": 30
}
```

**响应：**
```json
{
  "ok": true,
  "result": "clicked"
}
```

**支持的 action：**

| Action | 参数 | 说明 |
|--------|------|------|
| `getState` | - | 获取页面完整状态 |
| `getBodyText` | `maxLen` | 获取页面正文 |
| `click` | `selector`/`text`, `nth` | 点击元素 |
| `clickAny` | `text`, `nth` | 点击任意匹配元素 |
| `navigate` | `url` | 导航到 URL |
| `eval` | `code` | 执行 JavaScript |
| `querySelector` | `selector` | DOM 查询 |
| `read` | `selector` | 读取元素文本 |
| `setInput` | `selector`, `value` | 设置输入值 |
| `type` | `selector`, `text` | 模拟输入 |
| `fillForm` | `fields` | 批量填充表单 |
| `selectOption` | `selector`, `value` | 选择下拉选项 |
| `waitForSelector` | `selector`, `timeout` | 等待元素出现 |
| `waitForText` | `text`, `timeout` | 等待文本出现 |
| `waitForRender` | `minLength`, `timeout` | 等待 SPA 渲染 |
| `assertText` | `text` | 断言文本存在 |
| `assertSelector` | `selector` | 断言元素存在 |
| `getConsoleLog` | `count` | 获取控制台日志 |
| `ping` | - | 心跳检测 |

### POST /api/browser/command

异步提交命令，不等待结果。

**请求体：**
```json
{
  "action": "click",
  "selector": "#btn",
  "tabId": "tab123"
}
```

**响应：**
```json
{
  "ok": true,
  "cmdId": 42,
  "action": "click"
}
```

### POST /api/browser/navigate

导航到 URL 并等待加载完成。

**请求体：**
```json
{
  "url": "https://example.com",
  "timeout": 30
}
```

**响应：**
```json
{
  "ok": true,
  "tabId": "tab123",
  "url": "https://example.com",
  "elapsed": 2.3,
  "readyState": "complete"
}
```

### POST /api/browser/ensure

确保有 tab 在目标页面，自动启动浏览器。

**请求体：**
```json
{
  "url": "https://example.com",
  "timeout": 30
}
```

**响应：**
```json
{
  "ok": true,
  "tabId": "tab123",
  "url": "https://example.com",
  "elapsed": 3.1,
  "readyState": "launched"
}
```

### GET /api/browser/state

获取所有 tab 状态。

**响应：**
```json
{
  "tabs": {
    "tab123": {
      "url": "https://example.com",
      "updated_at": 1700000000.0,
      "last_heartbeat": {
        "readyState": "complete"
      }
    }
  },
  "results_count": 0
}
```

### POST /api/browser/heartbeat

油猴脚本上报页面状态。

**请求体：**
```json
{
  "tabId": "tab123",
  "url": "https://example.com",
  "readyState": "complete",
  "title": "Example Domain"
}
```

### POST /api/browser/result

油猴脚本回传执行结果。

**请求体：**
```json
{
  "id": 42,
  "ok": true,
  "result": "clicked"
}
```

### POST /api/browser/log

油猴脚本上报日志。

**请求体：**
```json
{
  "tabId": "tab123",
  "msg": "Command executed",
  "ts": 1700000000000
}
```

### GET /api/browser/results

获取最近执行结果（最多 50 条）。

### GET /api/browser/logs

获取最近日志（最多 100 条）。

---

## Shell 命令 API

### POST /api/shell

执行 shell 命令（需鉴权 + 白名单）。

**请求体：**
```json
{
  "cmd": "input tap 100 200"
}
```

**响应：**
```json
{
  "stdout": "",
  "stderr": "",
  "returncode": 0,
  "cmd": "input tap 100 200"
}
```

**白名单前缀：**
- `input tap/swipe/text/keyevent` — 模拟输入
- `uiautomator dump` — UI 树导出
- `screencap` — 截图
- `am start/force-stop/broadcast` — 应用管理
- `dumpsys` — 设备信息
- `pm list/path/clear` — 包管理
- `wm size/density` — 显示设置
- `settings get/put` — 系统设置
- `logcat` — 日志
- `cat/head/tail/ls/stat/wc` — 文件读取（只读）
- `echo/grep/pidof/which` — 工具

### GET /api/health

健康检查。

**响应：**
```json
{
  "status": "ok",
  "service": "shizuku-bridge"
}
```

---

## 错误响应

所有 API 在出错时返回：
```json
{
  "error": "错误描述"
}
```

常见 HTTP 状态码：
- `400` — 请求格式错误
- `403` — Token 无效或命令不在白名单
- `404` — 接口不存在
- `408` — 执行超时
- `500` — 服务器内部错误
- `503` — 无可用浏览器 tab
