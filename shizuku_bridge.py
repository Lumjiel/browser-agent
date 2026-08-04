#!/usr/bin/env python3
"""
Shizuku HTTP Bridge - 纯标准库实现
==================================
职责（单一）：Shell 命令中继 + 浏览器 DOM 桥接

架构:
  油猴脚本 ←→ HTTP ←→ 本服务 ←→ rish ←→ Shizuku → adb shell
  Pi        ←→ HTTP ←→ 本服务

浏览器代理 API（通用）:
  POST /api/browser/adb        ADB 降级模式（点击/输入/截图/提取）
  POST /api/send              统一命令接口（排队→等待→返回）
  POST /api/browser/command    异步提交命令
  POST /api/browser/interactive 同步执行（阻塞等待结果）
  POST /api/browser/navigate   导航到 URL 并等待加载
  POST /api/browser/ensure     确保有 tab 在目标页面（自动启动浏览器）
  GET  /api/browser/state      获取所有 tab 状态
  GET  /api/browser/commands   油猴脚本轮询获取命令（支持 client_id 注册/复用）
  POST /api/browser/result     油猴脚本回传执行结果
  POST /api/browser/heartbeat  油猴脚本上报页面状态
  POST /api/browser/log        油猴脚本上报日志
  GET  /api/browser/results    获取最近执行结果
  GET  /api/browser/logs       获取最近日志
  GET  /api/clients            列出所有连接客户端（含 IP / url / 队列长度）

Shell API:
  POST /api/shell              执行 shell 命令（需鉴权 + 白名单）
  GET  /api/health             健康检查（油猴脚本自动发现时 ping 此端点）
"""
import json
import os
import random
import socket
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ========== 配置 ==========
API_TOKEN = "MY_SECRET_123456"
BIND_HOST = "0.0.0.0"   # 绑定所有网卡，支持局域网访问
BIND_PORT = 8123

# 命令白名单（安全！只允许这些前缀）
ALLOWED_PREFIXES = (
    # 输入模拟
    "input tap", "input swipe", "input text", "input keyevent",
    # UI 获取
    "uiautomator dump", "screencap",
    # 应用管理
    "am start", "am force-stop", "am broadcast",
    # 设备信息
    "dumpsys", "pm list", "pm path", "pm clear",
    "wm size", "wm density",
    "cmd package",
    "settings get", "settings put",
    "logcat",
    # 文件读取（只读，不写）
    "cat ", "head ", "tail ", "ls ", "stat ", "wc ",
    # 工具
    "echo ", "grep ", "pidof", "which",
)

# ========== 浏览器 DOM 桥接状态 ==========
browser_tabs = {}      # tabId -> {heartbeat, url, updated_at}
browser_commands = {}  # tabId -> [commands]  (队列)
browser_results = []   # 执行结果环形缓冲区
browser_logs = []      # 日志环形缓冲区
MAX_RESULTS = 500
MAX_LOGS = 200
cmd_id_counter = 0

# 服务端等待器（同步执行）
result_waiters = {}    # cmd_id -> threading.Event
result_cache = {}      # cmd_id -> result

# 浏览器启动锁（防止并发启动）
browser_launching = threading.Event()  # set = 正在启动中

import threading
browser_lock = threading.Lock()

# ========== ADB 降级模式（油猴脚本离线时兜底）==========

ADB_FALLBACK_COMMANDS = {"click", "type", "tap", "swipe", "text", "screenshot", "dump", "scroll"}

def _adb_check(script_path="/sdcard/browser.xml"):
    """ADB 执行 shell 命令的底层"""
    def run(cmd, timeout=15):
        try:
            r = subprocess.run(["rish", "-c", cmd], capture_output=True, text=True, timeout=timeout)
            return r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return "", "timeout", -1
        except Exception as e:
            return "", str(e), -1
    return run

def adb_uiautomator_dump(xml_path="/sdcard/browser.xml"):
    """通过 ADB 获取 UI 元素树"""
    run = _adb_check()
    stdout, stderr, rc = run(f"uiautomator dump {xml_path}")
    if rc != 0:
        return None, stderr
    stdout, stderr, rc = run(f"cat {xml_path}")
    if rc != 0:
        return None, stderr
    return stdout, None

def adb_parse_elements(xml_text):
    """解析 uiautomator dump XML 为结构化元素列表"""
    import re
    elements = []
    for node in re.findall(r'<node[^>]*>', xml_text):
        text = re.search(r'text="([^"]*)"', node)
        desc = re.search(r'content-desc="([^"]*)"', node)
        rid = re.search(r'resource-id="([^"]*)"', node)
        cls = re.search(r'class="([^"]*)"', node)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if bounds:
            x1, y1, x2, y2 = int(bounds.group(1)), int(bounds.group(2)), int(bounds.group(3)), int(bounds.group(4))
            elements.append({
                "text": text.group(1) if text else "",
                "content-desc": desc.group(1) if desc else "",
                "resource-id": rid.group(1) if rid else "",
                "class": cls.group(1).split(".")[-1] if cls else "",
                "bounds": [x1, y1, x2, y2],
                "center": [(x1+x2)//2, (y1+y2)//2],
            })
    return elements

def adb_find_element(elements, text=None, desc=None, rid=None):
    """从元素列表中查找目标"""
    for el in elements:
        if text and text.lower() in el["text"].lower():
            return el
        if desc and desc.lower() in el["content-desc"].lower():
            return el
        if rid and rid in el["resource-id"]:
            return el
    return None

def adb_fallback_click(x, y):
    """ADB 模拟点击"""
    run = _adb_check()
    _, stderr, rc = run(f"input tap {x} {y}")
    return rc == 0, stderr

def adb_fallback_type(text):
    """ADB 模拟输入（需先点击输入框）"""
    # 转义特殊字符
    safe = text.replace(" ", "%s").replace("'", "\'").replace('"', '\"')
    run = _adb_check()
    _, stderr, rc = run(f"input text '{safe}'")
    return rc == 0, stderr

def adb_fallback_swipe(x1, y1, x2, y2, duration=300):
    """ADB 模拟滑动"""
    run = _adb_check()
    _, stderr, rc = run(f"input swipe {x1} {y1} {x2} {y2} {duration}")
    return rc == 0, stderr

def adb_fallback_screenshot(path="/sdcard/browser_screenshot.png"):
    """ADB 截图"""
    run = _adb_check()
    _, stderr, rc = run(f"screencap -p {path}")
    return rc == 0, stderr

def is_tamonkey_alive(tab_id=None, max_age=10):
    """检查油猴脚本是否在线（最近 max_age 秒内有心跳）"""
    with browser_lock:
        if tab_id:
            tab = browser_tabs.get(tab_id, {})
            last = tab.get("updated_at", 0)
            return (time.time() - last) < max_age
        # 检查任意 tab
            for tid, info in browser_tabs.items():
                if (time.time() - info.get("updated_at", 0)) < max_age:
                    return True
    return False

# ========== 客户端管理（借鉴 hermes-browser-bridge）==========
# clients: client_id -> {ip, last_seen, url, queue, connected}
clients = {}
blank_cid_ips = {}          # ip -> 上次为该 IP 新建客户端的时间戳
NEW_CLIENT_THROTTLE_SEC = 5 # 每 IP 5 秒内最多新建一个客户端
CLIENT_STALE_SEC = 60       # 超过 60 秒未活跃视为离线


def new_client_id():
    """生成唯一客户端 ID"""
    return "c" + str(int(time.time() * 1000000)) + str(random.randint(0, 9999))


def register_client(cid, ip, url=""):
    """注册或复用客户端，返回生效的 client_id；被节流时返回 None。

    复用规则（与 hermes 一致）:
      1. 已有 client_id 直接复用
      2. 空白 client_id → 尝试同 IP 复用（页面刷新后身份丢失）
      3. 未知 client_id（旧身份失效）→ 尝试同 IP 复用
      4. 均不匹配 → 新建（每 IP 5 秒节流，防止重复注册）
    """
    global blank_cid_ips
    now = time.time()
    with browser_lock:
        found_existing = bool(cid) and cid in clients

        # 空白 client_id → 同 IP 复用
        if not found_existing and not cid:
            for c in reversed(list(clients.keys())):
                if clients[c].get("ip") == ip:
                    cid, found_existing = c, True
                    break

        # 未知 client_id（如服务重启后旧身份失效）→ 同 IP 复用
        if not found_existing and cid:
            for c in reversed(list(clients.keys())):
                if clients[c].get("ip") == ip:
                    cid, found_existing = c, True
                    break

        if not found_existing:
            last = blank_cid_ips.get(ip, 0)
            if now - last < NEW_CLIENT_THROTTLE_SEC:
                return None  # 节流：不新建
            cid = cid or new_client_id()
            blank_cid_ips[ip] = now
            clients[cid] = {
                "ip": ip, "last_seen": now, "url": url,
                "queue": [], "connected": True,
            }
        else:
            clients[cid]["connected"] = True

        clients[cid]["last_seen"] = now
        if url:
            clients[cid]["url"] = url
        return cid


def cleanup_client_loop():
    """后台清理线程：移除超过 CLIENT_STALE_SEC 未活跃的客户端"""
    while True:
        time.sleep(30)
        now = time.time()
        with browser_lock:
            stale = [k for k, v in clients.items()
                     if now - v.get("last_seen", 0) > CLIENT_STALE_SEC]
            for k in stale:
                del clients[k]


def get_lan_ips():
    """获取本机局域网 IP（纯 Python，不执行 shell 命令）"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))  # 仅用于路由选择，不实际发包
        ip = s.getsockname()[0]
        if not ip.startswith("127."):
            ips.append(ip)
        s.close()
    except Exception:
        pass
    return list(dict.fromkeys(ips))


# ========== 通用服务器端辅助函数 ==========

def send_cmd(tab_id, cmd_data):
    """发送命令到指定 tab，返回 cmd_id"""
    global cmd_id_counter
    with browser_lock:
        cmd_id_counter += 1
        cmd_id = cmd_id_counter
        cmd = {"id": cmd_id, "tabId": tab_id, **cmd_data}
        if tab_id not in browser_commands:
            browser_commands[tab_id] = []
        browser_commands[tab_id].append(cmd)
        return cmd_id


def wait_for_cmd_result(cmd_id, timeout=30):
    """等待指定 cmd_id 的命令执行结果"""
    start = time.time()
    while time.time() - start < timeout:
        with browser_lock:
            for r in browser_results:
                if r.get("id") == cmd_id:
                    browser_results.remove(r)
                    return r
        time.sleep(0.3)
    return None


def find_tab_on_domain(domain):
    """找到目标域名上最近活跃的 tab，返回 tab_id 或 None"""
    with browser_lock:
        best_tab = None
        best_time = 0
        for tid, info in browser_tabs.items():
            if domain in info.get("url", "") and info.get("updated_at", 0) > best_time:
                best_tab = tid
                best_time = info["updated_at"]
        return best_tab


def find_most_recent_tab():
    """找到最近活跃的 tab，返回 tab_id 或 None"""
    with browser_lock:
        if not browser_tabs:
            return None
        return max(browser_tabs, key=lambda tid: browser_tabs[tid].get("updated_at", 0))


def ping_tab(tab_id, timeout=5):
    """Ping 指定 tab，返回是否响应"""
    cmd_id = send_cmd(tab_id, {"action": "ping"})
    result = wait_for_cmd_result(cmd_id, timeout=timeout)
    return result is not None and result.get("ok", False)


def launch_browser_via_adb(url):
    """通过 ADB 启动浏览器打开 URL"""
    if browser_launching.is_set():
        return False, "已有启动操作进行中"
    browser_launching.set()
    try:
        result = subprocess.run(
            ["rish", "-c",
             f"am start -a android.intent.action.VIEW -d '{url}'"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return False, result.stderr[:200] if result.stderr else "am start 失败"
        return True, "ok"
    except subprocess.TimeoutExpired:
        return False, "am start 超时"
    except Exception as e:
        return False, str(e)
    finally:
        # 给浏览器留出启动时间，再释放锁
        threading.Timer(5.0, browser_launching.clear).start()


# ========== HTTP Handler ==========

class ShizukuHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # ── GET ──

    def do_GET(self):
        parsed_path = urlparse(self.path).path

        if parsed_path == "/api/browser/commands":
            # 浏览器轮询获取命令（支持 client_id 注册/复用，兼容旧 tabId 参数）
            params = parse_qs(urlparse(self.path).query)
            tab_id = params.get("tabId", ["default"])[0]
            client_id = params.get("client_id", [tab_id])[0]
            url = params.get("url", [""])[0]
            ip = self.client_address[0]
            cid = register_client(client_id, ip, url)
            with browser_lock:
                if tab_id not in browser_tabs:
                    browser_tabs[tab_id] = {}
                browser_tabs[tab_id]["url"] = url
                browser_tabs[tab_id]["updated_at"] = time.time()
                cmds = browser_commands.get(tab_id, [])
                browser_commands[tab_id] = []
                if cid and cid in clients:
                    client_cmds = clients[cid]["queue"]
                    clients[cid]["queue"] = []
                    cmds = cmds + client_cmds
            self._send_json({"commands": cmds, "client_id": cid})
            return

        if parsed_path == "/api/browser/state":
            with browser_lock:
                tabs = {}
                for tid, info in browser_tabs.items():
                    tabs[tid] = {
                        "url": info.get("url", ""),
                        "updated_at": info.get("updated_at", 0),
                        "last_heartbeat": info.get("heartbeat", {}),
                    }
            self._send_json({"tabs": tabs, "results_count": len(browser_logs)})
            return

        if parsed_path == "/api/browser/results":
            with browser_lock:
                results = browser_results[-50:]
            self._send_json({"results": results})
            return

        if parsed_path == "/api/browser/logs":
            with browser_lock:
                logs = browser_logs[-100:]
            self._send_json({"logs": logs})
            return

        if parsed_path == "/api/clients":
            # 列出所有连接客户端
            now = time.time()
            with browser_lock:
                out = []
                for cid, meta in clients.items():
                    out.append({
                        "id": cid,
                        "url": meta.get("url", ""),
                        "last_seen": round(now - meta.get("last_seen", now), 1),
                        "ip": meta.get("ip", ""),
                        "connected": meta.get("connected", False),
                        "queue": len(meta.get("queue", [])),
                    })
            self._send_json({"clients": out, "count": len(out), "timestamp": now})
            return

        if parsed_path == "/api/health":
            self._send_json({"status": "ok", "service": "shizuku-bridge"})
            return

        self._send_json({"error": "not found"}, 404)

    # ── POST ──

    def do_POST(self):
        parsed_path = urlparse(self.path).path
        global cmd_id_counter

        # ========== 浏览器代理接口（无需鉴权）==========

        if parsed_path == "/api/browser/log":
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            with browser_lock:
                browser_logs.append(data)
                if len(browser_logs) > MAX_LOGS:
                    browser_logs.pop(0)
            self._send_json({"ok": True})
            return

        if parsed_path == "/api/browser/heartbeat":
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            tab_id = data.get("tabId", "default")
            register_client(tab_id, self.client_address[0], data.get("url", ""))
            with browser_lock:
                if tab_id not in browser_tabs:
                    browser_tabs[tab_id] = {}
                browser_tabs[tab_id]["heartbeat"] = data
                browser_tabs[tab_id]["url"] = data.get("url", "")
                browser_tabs[tab_id]["updated_at"] = time.time()
            self._send_json({"ok": True})
            return

        if parsed_path == "/api/browser/result":
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            cmd_id = data.get("id")
            with browser_lock:
                browser_results.append(data)
                if len(browser_results) > MAX_RESULTS:
                    browser_results.pop(0)
                waiter = result_waiters.get(cmd_id)
                if waiter:
                    result_cache[cmd_id] = data
                    waiter.set()
            self._send_json({"ok": True})
            return

        if parsed_path == "/api/browser/interactive":
            # 同步执行：发送命令并等待结果（支持 ADB 降级）
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            action = data.get("action", "").strip()
            if not action:
                return self._send_json({"error": "缺少action"}, 400)

            # ADB 降级模式：油猴离线时走 ADB
            tab_id = data.get("tabId", "default")
            use_adb = data.get("adb", False)
            if not use_adb and not is_tamonkey_alive(tab_id):
                if action in ADB_FALLBACK_COMMANDS:
                    use_adb = True
            tab_id = data.get("tabId", "default")
            timeout = data.get("timeout", 30)
            with browser_lock:
                cmd_id_counter += 1
                cmd_id = cmd_id_counter
                cmd = {"id": cmd_id, "action": action, "tabId": tab_id}
                for k, v in data.items():
                    if k not in ("action", "tabId"):
                        cmd[k] = v
                if tab_id not in browser_commands:
                    browser_commands[tab_id] = []
                browser_commands[tab_id].append(cmd)
                event = threading.Event()
                result_waiters[cmd_id] = event

            # ADB 降级执行
            if use_adb:
                result = None
                if action == "dump":
                    xml, err = adb_uiautomator_dump()
                    if xml:
                        elements = adb_parse_elements(xml)
                        result = {"ok": True, "elements": elements, "count": len(elements), "mode": "adb"}
                    else:
                        result = {"ok": False, "error": err, "mode": "adb"}
                elif action == "screenshot":
                    ok, err = adb_fallback_screenshot(data.get("path", "/sdcard/browser_screenshot.png"))
                    result = {"ok": ok, "path": "/sdcard/browser_screenshot.png", "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "click":
                    x, y = data.get("x"), data.get("y")
                    if x is None or y is None:
                        # 通过文本查找坐标
                        xml, err = adb_uiautomator_dump()
                        if xml:
                            elements = adb_parse_elements(xml)
                            el = adb_find_element(elements, text=data.get("text"), desc=data.get("desc"), rid=data.get("rid"))
                            if el:
                                x, y = el["center"]
                            else:
                                result = {"ok": False, "error": "element not found", "mode": "adb"}
                        else:
                            result = {"ok": False, "error": err, "mode": "adb"}
                    if x is not None and y is not None:
                        ok, err = adb_fallback_click(x, y)
                        result = {"ok": True, "x": x, "y": y, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "type":
                    text = data.get("text", "")
                    if text:
                        ok, err = adb_fallback_type(text)
                        result = {"ok": True, "text": text, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "tap":
                    x, y = data.get("x"), data.get("y")
                    ok, err = adb_fallback_click(x, y)
                    result = {"ok": True, "x": x, "y": y, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "swipe":
                    x1, y1 = data.get("x1", 500), data.get("y1", 1500)
                    x2, y2 = data.get("x2", 500), data.get("y2", 500)
                    dur = data.get("duration", 300)
                    ok, err = adb_fallback_swipe(x1, y1, x2, y2, dur)
                    result = {"ok": True, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "scroll":
                    direction = data.get("direction", "up")
                    if direction == "up":
                        ok, err = adb_fallback_swipe(500, 1500, 500, 500)
                    else:
                        ok, err = adb_fallback_swipe(500, 500, 500, 1500)
                    result = {"ok": True, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                else:
                    result = {"ok": False, "error": f"ADB mode不支持 {action}", "mode": "adb"}

                if result:
                    result["fallback"] = True
                    result["reason"] = "油猴脚本离线，已降级到 ADB 模式"
                self._send_json(result or {"error": "ADB 执行失败", "mode": "adb"})
                return

            if event.wait(timeout=timeout):
                result = result_cache.pop(cmd_id, None)
                self._send_json(result or {"error": "result lost"})
            else:
                self._send_json({"error": "timeout", "cmdId": cmd_id}, 408)
            result_waiters.pop(cmd_id, None)
            result_cache.pop(cmd_id, None)
            return

        if parsed_path == "/api/browser/command":
            # 异步提交命令
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            action = data.get("action", "").strip()
            if not action:
                return self._send_json({"error": "缺少action"}, 400)
            tab_id = data.get("tabId", "default")
            with browser_lock:
                cmd_id_counter += 1
                cmd = {"id": cmd_id_counter, "action": action, "tabId": tab_id}
                for k, v in data.items():
                    if k not in ("action", "tabId"):
                        cmd[k] = v
                if tab_id not in browser_commands:
                    browser_commands[tab_id] = []
                browser_commands[tab_id].append(cmd)
            self._send_json({"ok": True, "cmdId": cmd_id_counter, "action": action})
            return

        if parsed_path == "/api/send":
            # 统一命令接口（借鉴 hermes）：排队 → 等待 → 返回
            # Body: {"action": "...", "client_id": "可选", "tabId": "兼容旧参数",
            #        "timeout": 30, ...其余参数透传给油猴脚本}
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            action = data.get("action", "").strip()
            if not action:
                return self._send_json({"error": "缺少action"}, 400)
            client_id = data.get("client_id", None)
            tab_id = data.get("tabId", None)
            timeout = data.get("timeout", 30)

            with browser_lock:
                cmd_id_counter += 1
                cmd_id = cmd_id_counter
                cmd = {"id": cmd_id, "action": action,
                       "tabId": tab_id or client_id or "default"}
                for k, v in data.items():
                    # timeout 透传给油猴脚本（浏览器端执行时限），action/client_id 不传
                    if k not in ("action", "client_id"):
                        cmd[k] = v

                # 目标选择：client_id > tabId > 最近活跃客户端
                target = client_id or tab_id
                sent = False
                if target:
                    if target in clients:
                        clients[target]["queue"].append(cmd)
                        sent = True
                    elif target in browser_tabs or target in browser_commands:
                        browser_commands.setdefault(target, []).append(cmd)
                        sent = True
                else:
                    if clients:
                        target = max(clients, key=lambda c: clients[c].get("last_seen", 0))
                        clients[target]["queue"].append(cmd)
                        sent = True
                    elif browser_tabs:
                        target = max(browser_tabs, key=lambda t: browser_tabs[t].get("updated_at", 0))
                        browser_commands.setdefault(target, []).append(cmd)
                        sent = True

                if not sent:
                    return self._send_json(
                        {"error": "no browser connected", "code": "NO_CLIENTS"}, 503)
                event = threading.Event()
                result_waiters[cmd_id] = event

            # ADB 降级执行
            if use_adb:
                result = None
                if action == "dump":
                    xml, err = adb_uiautomator_dump()
                    if xml:
                        elements = adb_parse_elements(xml)
                        result = {"ok": True, "elements": elements, "count": len(elements), "mode": "adb"}
                    else:
                        result = {"ok": False, "error": err, "mode": "adb"}
                elif action == "screenshot":
                    ok, err = adb_fallback_screenshot(data.get("path", "/sdcard/browser_screenshot.png"))
                    result = {"ok": ok, "path": "/sdcard/browser_screenshot.png", "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "click":
                    x, y = data.get("x"), data.get("y")
                    if x is None or y is None:
                        # 通过文本查找坐标
                        xml, err = adb_uiautomator_dump()
                        if xml:
                            elements = adb_parse_elements(xml)
                            el = adb_find_element(elements, text=data.get("text"), desc=data.get("desc"), rid=data.get("rid"))
                            if el:
                                x, y = el["center"]
                            else:
                                result = {"ok": False, "error": "element not found", "mode": "adb"}
                        else:
                            result = {"ok": False, "error": err, "mode": "adb"}
                    if x is not None and y is not None:
                        ok, err = adb_fallback_click(x, y)
                        result = {"ok": True, "x": x, "y": y, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "type":
                    text = data.get("text", "")
                    if text:
                        ok, err = adb_fallback_type(text)
                        result = {"ok": True, "text": text, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "tap":
                    x, y = data.get("x"), data.get("y")
                    ok, err = adb_fallback_click(x, y)
                    result = {"ok": True, "x": x, "y": y, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "swipe":
                    x1, y1 = data.get("x1", 500), data.get("y1", 1500)
                    x2, y2 = data.get("x2", 500), data.get("y2", 500)
                    dur = data.get("duration", 300)
                    ok, err = adb_fallback_swipe(x1, y1, x2, y2, dur)
                    result = {"ok": True, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                elif action == "scroll":
                    direction = data.get("direction", "up")
                    if direction == "up":
                        ok, err = adb_fallback_swipe(500, 1500, 500, 500)
                    else:
                        ok, err = adb_fallback_swipe(500, 500, 500, 1500)
                    result = {"ok": True, "mode": "adb"} if ok else {"ok": False, "error": err, "mode": "adb"}
                else:
                    result = {"ok": False, "error": f"ADB mode不支持 {action}", "mode": "adb"}

                if result:
                    result["fallback"] = True
                    result["reason"] = "油猴脚本离线，已降级到 ADB 模式"
                self._send_json(result or {"error": "ADB 执行失败", "mode": "adb"})
                return

            if event.wait(timeout=timeout):
                result = result_cache.pop(cmd_id, None)
                self._send_json(result or {"error": "result lost"})
            else:
                self._send_json({"error": "timeout", "cmdId": cmd_id}, 408)
            result_waiters.pop(cmd_id, None)
            result_cache.pop(cmd_id, None)
            return

        if parsed_path == "/api/browser/navigate":
            # 导航到 URL 并等待加载完成
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            url = data.get("url", "").strip()
            if not url:
                return self._send_json({"error": "缺少url"}, 400)
            tab_id = data.get("tabId", None)
            timeout = data.get("timeout", 30)
            from urllib.parse import urlparse as up
            target_domain = up(url).netloc

            # 确定发送命令的 tab
            if tab_id is None:
                tab_id = find_most_recent_tab()
            if tab_id is None:
                return self._send_json({"error": "no tab available"}, 503)

            # 发送导航命令
            send_cmd(tab_id, {"action": "navigate", "url": url})

            # 等待任意 tab 出现在目标页面（不锁定原始 tabId）
            start = time.time()
            while time.time() - start < timeout:
                time.sleep(1)
                # 找任意在目标域名上的 tab
                found_tab = find_tab_on_domain(target_domain)
                if found_tab:
                    with browser_lock:
                        tab = browser_tabs.get(found_tab, {})
                        tab_url = tab.get("url", "")
                        hb = tab.get("heartbeat", {})
                        ready = hb.get("readyState", "")
                    if ready in ("interactive", "complete"):
                        if ping_tab(found_tab, timeout=5):
                            elapsed = time.time() - start
                            return self._send_json({
                                "ok": True, "tabId": found_tab, "url": tab_url,
                                "elapsed": round(elapsed, 1), "readyState": ready
                            })
            return self._send_json({"error": "timeout", "url": url}, 408)

        if parsed_path == "/api/browser/ensure":
            # 确保有 tab 在目标页面（自动启动浏览器 + 导航）
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            url = data.get("url", "").strip()
            if not url:
                return self._send_json({"error": "缺少url"}, 400)
            timeout = data.get("timeout", 30)
            from urllib.parse import urlparse as up
            target_domain = up(url).netloc

            # 1. 检查是否已有活跃 tab 在目标页面
            existing = find_tab_on_domain(target_domain)
            if existing and ping_tab(existing, timeout=5):
                with browser_lock:
                    tab_url = browser_tabs[existing].get("url", "")
                return self._send_json({
                    "ok": True, "tabId": existing, "url": tab_url,
                    "elapsed": 0, "readyState": "already_there",
                    "mode": "full" if is_tamonkey_alive(existing) else "adb"
                })

            # 2. 没有 tab → 启动浏览器
            with browser_lock:
                has_tabs = bool(browser_tabs)
            if not has_tabs:
                ok, msg = launch_browser_via_adb(url)
                if not ok:
                    return self._send_json({"error": f"启动浏览器失败: {msg}"}, 500)
                # 等待 tab 注册
                start = time.time()
                while time.time() - start < timeout:
                    time.sleep(1)
                    with browser_lock:
                        if browser_tabs:
                            break
                # 重新找 tab
                existing = find_tab_on_domain(target_domain)
                if existing and ping_tab(existing, timeout=5):
                    with browser_lock:
                        tab_url = browser_tabs[existing].get("url", "")
                    elapsed = time.time() - start
                    return self._send_json({
                        "ok": True, "tabId": existing, "url": tab_url,
                        "elapsed": round(elapsed, 1), "readyState": "launched"
                    })

            # 3. 有 tab 但不在目标页面 → 导航
            tab_id = find_most_recent_tab()
            if tab_id:
                send_cmd(tab_id, {"action": "navigate", "url": url})
                start = time.time()
                while time.time() - start < timeout:
                    time.sleep(1)
                    # 不锁定原始 tabId，找任意在目标域名上的 tab
                    found_tab = find_tab_on_domain(target_domain)
                    if found_tab:
                        with browser_lock:
                            tab = browser_tabs.get(found_tab, {})
                            tab_url = tab.get("url", "")
                            hb = tab.get("heartbeat", {})
                            ready = hb.get("readyState", "")
                        if ready in ("interactive", "complete"):
                            if ping_tab(found_tab, timeout=5):
                                elapsed = time.time() - start
                                return self._send_json({
                                    "ok": True, "tabId": found_tab, "url": tab_url,
                                    "elapsed": round(elapsed, 1), "readyState": ready
                                })

            return self._send_json({"error": "ensure failed", "url": url}, 503)

        # ========== ADB 直控接口（降级模式）==========

        if parsed_path == "/api/browser/adb":
            # ADB 降级模式：直接执行 ADB 操作，不走油猴脚本
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            action = data.get("action", "").strip()
            if not action:
                return self._send_json({"error": "缺少action"}, 400)

            if action == "dump":
                xml, err = adb_uiautomator_dump()
                if xml:
                    elements = adb_parse_elements(xml)
                    return self._send_json({"ok": True, "elements": elements, "count": len(elements), "mode": "adb"})
                return self._send_json({"ok": False, "error": err}, 500)

            if action == "click":
                x, y = data.get("x"), data.get("y")
                if x is None:
                    xml, _ = adb_uiautomator_dump()
                    if xml:
                        elements = adb_parse_elements(xml)
                        el = adb_find_element(elements, text=data.get("text"), desc=data.get("desc"))
                        if el:
                            x, y = el["center"]
                        else:
                            return self._send_json({"ok": False, "error": "element not found"})
                ok, err = adb_fallback_click(x, y)
                return self._send_json({"ok": ok, "x": x, "y": y, "mode": "adb"} if ok else {"ok": False, "error": err})

            if action == "type":
                ok, err = adb_fallback_type(data.get("text", ""))
                return self._send_json({"ok": ok, "mode": "adb"} if ok else {"ok": False, "error": err})

            if action == "screenshot":
                ok, err = adb_fallback_screenshot(data.get("path", "/sdcard/browser_screenshot.png"))
                return self._send_json({"ok": ok, "path": "/sdcard/browser_screenshot.png", "mode": "adb"} if ok else {"ok": False, "error": err})

            if action == "swipe":
                ok, err = adb_fallback_swipe(
                    data.get("x1", 500), data.get("y1", 1500),
                    data.get("x2", 500), data.get("y2", 500),
                    data.get("duration", 300))
                return self._send_json({"ok": ok, "mode": "adb"} if ok else {"ok": False, "error": err})

            if action == "extract":
                xml, err = adb_uiautomator_dump()
                if xml:
                    elements = adb_parse_elements(xml)
                    texts = [el["text"] for el in elements if el["text"].strip()]
                    return self._send_json({"ok": True, "texts": texts, "count": len(texts), "mode": "adb"})
                return self._send_json({"ok": False, "error": err})

            return self._send_json({"error": f"ADB 不支持 {action}", "supported": ["dump", "click", "type", "screenshot", "swipe", "extract"]}, 400)

        # ========== Shell 命令接口（需鉴权）==========

        if parsed_path == "/api/shell":
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {API_TOKEN}":
                return self._send_json({"error": "token无效"}, 403)
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            cmd = data.get("cmd", "").strip()
            if not cmd:
                return self._send_json({"error": "缺少cmd"}, 400)
            if not any(cmd.startswith(p) for p in ALLOWED_PREFIXES):
                return self._send_json({
                    "error": f"命令不在白名单: {cmd}",
                    "allowed_prefixes": list(ALLOWED_PREFIXES)
                }, 403)
            try:
                result = subprocess.run(
                    ["rish", "-c", cmd],
                    capture_output=True, text=True, timeout=15
                )
                self._send_json({
                    "stdout": result.stdout, "stderr": result.stderr,
                    "returncode": result.returncode, "cmd": cmd
                })
            except subprocess.TimeoutExpired:
                self._send_json({"error": "命令超时（15s）"}, 500)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        self._send_json({"error": "not found"}, 404)


# ========== 启动 ==========

if __name__ == "__main__":
    from http.server import ThreadingHTTPServer

    # 后台客户端清理线程
    threading.Thread(target=cleanup_client_loop, daemon=True).start()

    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), ShizukuHandler)
    print(f"✅ Shizuku Bridge 已启动: http://{BIND_HOST}:{BIND_PORT}")
    for ip in get_lan_ips():
        print(f"   局域网地址: http://{ip}:{BIND_PORT}")
    print(f"   白名单命令数: {len(ALLOWED_PREFIXES)}")
    print(f"   TOKEN: {API_TOKEN}")
    print(f"   按 Ctrl+C 停止")
    server.serve_forever()
