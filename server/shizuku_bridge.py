#!/usr/bin/env python3
"""
Shizuku HTTP Bridge - 纯标准库实现
==================================
职责（单一）：Shell 命令中继 + 浏览器 DOM 桥接

架构:
  油猴脚本 ←→ HTTP ←→ 本服务 ←→ rish ←→ Shizuku → adb shell
  Pi        ←→ HTTP ←→ 本服务

浏览器代理 API（通用）:
  POST /api/browser/command    异步提交命令
  POST /api/browser/interactive 同步执行（阻塞等待结果）
  POST /api/browser/navigate   导航到 URL 并等待加载
  POST /api/browser/ensure     确保有 tab 在目标页面（自动启动浏览器）
  GET  /api/browser/state      获取所有 tab 状态
  GET  /api/browser/commands   油猴脚本轮询获取命令
  POST /api/browser/result     油猴脚本回传执行结果
  POST /api/browser/heartbeat  油猴脚本上报页面状态
  POST /api/browser/log        油猴脚本上报日志
  GET  /api/browser/results    获取最近执行结果
  GET  /api/browser/logs       获取最近日志

Shell API:
  POST /api/shell              执行 shell 命令（需鉴权 + 白名单）
  GET  /api/health             健康检查
"""
import json
import os
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ========== 配置 ==========
API_TOKEN = "MY_SECRET_123456"
BIND_HOST = "127.0.0.1"
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
            # 浏览器轮询获取命令
            params = parse_qs(urlparse(self.path).query)
            tab_id = params.get("tabId", ["default"])[0]
            url = params.get("url", [""])[0]
            with browser_lock:
                if tab_id not in browser_tabs:
                    browser_tabs[tab_id] = {}
                browser_tabs[tab_id]["url"] = url
                browser_tabs[tab_id]["updated_at"] = time.time()
                cmds = browser_commands.get(tab_id, [])
                browser_commands[tab_id] = []
            self._send_json({"commands": cmds})
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
            # 同步执行：发送命令并等待结果
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            action = data.get("action", "").strip()
            if not action:
                return self._send_json({"error": "缺少action"}, 400)
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
                    "elapsed": 0, "readyState": "already_there"
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
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), ShizukuHandler)
    print(f"✅ Shizuku Bridge 已启动: http://{BIND_HOST}:{BIND_PORT}")
    print(f"   白名单命令数: {len(ALLOWED_PREFIXES)}")
    print(f"   TOKEN: {API_TOKEN}")
    print(f"   按 Ctrl+C 停止")
    server.serve_forever()
