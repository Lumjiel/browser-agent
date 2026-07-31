# 安装配置指南

## 前置条件

1. **Termux** 已安装
2. **Python 3.9+** 已安装
3. **Shizuku** 已安装并启动
4. **XBrowser** 已安装

## 快速安装

```bash
# 1. 克隆仓库
git clone https://github.com/Lumjiel/browser-agent.git
cd browser-agent

# 2. 启动服务端
make start
# 或: cd server && python3 shizuku_bridge.py

# 3. 验证
make health
```

## 油猴脚本安装

### 方式一：直接安装

1. 打开 XBrowser
2. 安装 Tampermonkey 扩展（或启用内置油猴支持）
3. 打开以下链接，点击安装：
   - `userscript/browser-agent.user.js` — 浏览器代理
   - `userscript/console.user.js` — ADB Shell 控制台
   - `userscript/ai_bridge.user.js` — AI 问答桥接

### 方式二：远程部署

```bash
# 配置环境变量
export VM_USER=youruser
export VM_HOST=yourserver.com
export VM_KEY=~/.ssh/your_key

# 运行部署脚本
bash deploy.sh
```

## 配置

### 服务端配置

复制 `config/config.example.json` 为 `config/config.json` 并修改：

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8123,
    "token": "你的密钥（随机字符串）"
  },
  "browser": {
    "package": "com.mmbox.xbrowser",
    "activity": ".BrowserActivity"
  }
}
```

### 油猴脚本配置

默认连接 `http://127.0.0.1:8123`。如需远程连接：

1. 打开浏览器控制台
2. 执行：
```js
localStorage.setItem("_browserAgentApi", "https://your-server.com/api/browser")
```

### CLI 配置

```bash
# 设置环境变量
export BRIDGE_URL="http://127.0.0.1:8123"
export BRIDGE_TAB="optional-default-tab-id"
```

## 验证安装

```bash
# 1. 健康检查
make health

# 2. 浏览器控制测试
./cli/browser_cli.sh tabs
./cli/browser_cli.sh state

# 3. AI 问答测试
python3 cli/ai_ask.py "你好" -a doubao

# 4. 运行测试套件
make test
```

## 开机自启

### 方式一：systemd（需要 root）

```bash
cp server/shizuku_bridge.service /etc/systemd/system/
systemctl enable shizuku_bridge
systemctl start shizuku_bridge
```

### 方式二：Termux boot

```bash
# ~/.termux/boot/start-bridge.sh
#!/data/data/com.termux/files/usr/bin/sh
cd /data/data/com.termux/files/home/projects/browser-agent/server
python3 shizuku_bridge.py &
```

## 常见问题

### 油猴脚本无法连接

- 确认服务端已启动：`make health`
- 确认端口 8123 未被占用：`netstat -tlnp | grep 8123`
- 检查 XBrowser 是否允许本地连接

### Shizuku 权限问题

- 确认 Shizuku 已启动：`rish -c "echo test"`
- 确认 rish 可执行权限

### 远程使用

如需从其他设备访问：

1. 修改 `shizuku_bridge.py` 中 `BIND_HOST` 为 `0.0.0.0`
2. 确保防火墙允许 8123 端口
3. 使用反向代理（nginx/caddy）添加 HTTPS

## 更新

```bash
git pull origin main
make stop
make start
```

## 卸载

```bash
make stop
rm -rf /data/data/com.termux/files/home/projects/browser-agent
```
