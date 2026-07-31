# 安装配置指南

## 前置条件

1. **Termux** 已安装
2. **Python 3** 已安装
3. **Shizuku** 已安装并启动
4. **XBrowser** 已安装

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/Lumjiel/browser-agent.git
cd browser-agent
```

### 2. 配置

```bash
cp config/config.example.json config/config.json
# 编辑 config/config.json，设置你的 token
```

### 3. 启动服务端

```bash
cd server
python3 shizuku_bridge.py
```

### 4. 安装油猴脚本

1. 打开 XBrowser
2. 安装 Tampermonkey 扩展（或启用内置油猴支持）
3. 打开 `userscript/browser-agent-xbrowser.user.js`，点击安装
4. 脚本会自动连接 `http://127.0.0.1:8123`

### 5. 验证

```bash
# 健康检查
curl http://127.0.0.1:8123/api/health

# 查看 tab 状态
curl http://127.0.0.1:8123/api/browser/state
```

## 常见问题

### 油猴脚本无法连接

- 确认服务端已启动
- 确认端口 8123 未被占用
- 检查 XBrowser 是否允许本地连接

### Shizuku 权限问题

- 确认 Shizuku 已启动
- 确认 rish 可执行：`rish -c "echo test"`

### 远程使用

如需从其他设备访问，修改 `shizuku_bridge.py` 中的 `BIND_HOST` 为 `0.0.0.0`，并确保防火墙允许 8123 端口。
