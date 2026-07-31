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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from config import get_server_config
from browser_manager import (
    browser_tabs, browser_commands, browser_results, browser_logs,
    send_cmd, wait_for_cmd_result, find_tab_on_domain, find_most_recent_tab,
    ping_tab, launch_browser_via_adb, navigate_and_wait, ensure_on_page,
    add_result, add_log, get_results, get_logs, get_tabs_state,
    result_waiters, result_cache, cmd_id_counter, browser_lock,
    MAX_RESULTS, MAX_LOGS
)
from shell_relay import validate_and_execute, ALLOWED_PREFIXES

# ========== 配置 ==========
_server_cfg = get_server_config()
API_TOKEN = _server_cfg["token"]
BIND_HOST = _server_cfg["host"]
BIND_PORT = _server_cfg["port"]


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
            tabs = get_tabs_state()
            self._send_json({"tabs": tabs, "results_count": len(browser_logs)})
            return

        if parsed_path == "/api/browser/results":
            self._send_json({"results": get_results(50)})
            return

        if parsed_path == "/api/browser/logs":
            self._send_json({"logs": get_logs(100)})
            return

        if parsed_path == "/api/health":
            self._send_json({"status": "ok", "service": "shizuku-bridge"})
            return

        self._send_json({"error": "not found"}, 404)

    # ── POST ──

    def do_POST(self):
        parsed_path = urlparse(self.path).path

        # ========== 浏览器代理接口（无需鉴权）==========

        if parsed_path == "/api/browser/log":
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            add_log(data)
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
            add_result(data)
            self._send_json({"ok": True})
            return

        if parsed_path == "/api/browser/interactive":
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
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            url = data.get("url", "").strip()
            if not url:
                return self._send_json({"error": "缺少url"}, 400)
            tab_id = data.get("tabId", None)
            timeout = data.get("timeout", 30)
            result, code = navigate_and_wait(url, tab_id, timeout)
            self._send_json(result, code)
            return

        if parsed_path == "/api/browser/ensure":
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            url = data.get("url", "").strip()
            if not url:
                return self._send_json({"error": "缺少url"}, 400)
            timeout = data.get("timeout", 30)
            result, code = ensure_on_page(url, timeout)
            self._send_json(result, code)
            return

        # ========== Shell 命令接口（需鉴权）==========

        if parsed_path == "/api/shell":
            data = self._read_json_body()
            if data is None:
                return self._send_json({"error": "invalid json"}, 400)
            cmd = data.get("cmd", "").strip()
            auth = self.headers.get("Authorization", "")
            result, code = validate_and_execute(cmd, API_TOKEN, auth)
            self._send_json(result, code)
            return

        self._send_json({"error": "not found"}, 404)


# ========== 启动 ==========

if __name__ == "__main__":
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), ShizukuHandler)
    print(f"✅ Shizuku Bridge 已启动: http://{BIND_HOST}:{BIND_PORT}")
    print(f"   白名单命令数: {len(ALLOWED_PREFIXES)}")
    print(f"   TOKEN: {API_TOKEN}")
    print(f"   按 Ctrl+C 停止")
    server.serve_forever()
