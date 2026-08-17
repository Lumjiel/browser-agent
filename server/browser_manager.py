#!/usr/bin/env python3
"""
browser_manager.py - 浏览器 Tab 管理 + 导航逻辑（跨平台）
"""
import os
import subprocess
import sys
import shutil
import threading
import time
import webbrowser
from urllib.parse import urlparse

from config import get_browser_config, get_feature_config

# ========== 浏览器 DOM 桥接状态 ==========
browser_tabs = {}      # tabId -> {heartbeat, url, updated_at}
browser_commands = {}  # tabId -> [commands]  (队列)
browser_results = []   # 执行结果环形缓冲区
browser_logs = []      # 日志环形缓冲区
cmd_id_counter = 0

# 服务端等待器（同步执行）
result_waiters = {}    # cmd_id -> threading.Event
result_cache = {}      # cmd_id -> result

# 浏览器启动锁（防止并发启动）
browser_launching = threading.Event()

browser_lock = threading.Lock()

# 浏览器配置
_browser_cfg = get_browser_config()
BROWSER_PACKAGE = _browser_cfg["package"]
BROWSER_ACTIVITY = _browser_cfg["activity"]

_feature_cfg = get_feature_config()
MAX_RESULTS = _feature_cfg["max_results"]
MAX_LOGS = _feature_cfg["max_logs"]


# ========== 平台检测 ==========

def _is_android():
    """检测是否为 Android/Termux 环境"""
    if sys.platform != "linux":
        return False
    # Android 特征：存在 rish 或 /system/bin/adb
    return shutil.which("rish") is not None or os.path.exists("/system/bin/adb")


def _desktop_browser_cmd():
    """返回桌面端浏览器启动命令，或 None 使用 webbrowser 回退"""
    if sys.platform == "win32":
        # Windows: 尝试 Chrome
        for path in [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]:
            if os.path.isfile(path):
                return path
        return None
    elif sys.platform == "darwin":
        # macOS: Chrome
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.isfile(chrome):
            return chrome
        return None
    else:
        # Linux: 尝试常见浏览器
        for name in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
            path = shutil.which(name)
            if path:
                return path
        return None


# ========== Tab 管理 ==========

def send_cmd(tab_id, cmd_data):
    """发送命令到指定 tab，返回 cmd_id"""
    global cmd_id_counter
    with browser_lock:
        cmd_id_counter += 1
        cmd_id = cmd_id_counter
        cmd = {"id": cmd_id, **cmd_data}
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
        for tab_id, tab in browser_tabs.items():
            # 子域名兼容：doubao.com 匹配 www.doubao.com
            if domain in tab.get("url", "") and tab.get("updated_at", 0) > best_time:
                best_tab = tab_id
                best_time = tab["updated_at"]
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
    result = wait_for_cmd_result(cmd_id, timeout)
    return result is not None and result.get("ok", False)


# ========== 浏览器启动与导航 ==========

def launch_browser(url):
    """启动浏览器打开 URL（跨平台）"""
    if browser_launching.is_set():
        return False, "已有启动操作进行中"
    browser_launching.set()
    try:
        if _is_android():
            # Android: 通过 rish/Shizuku 启动 XBrowser
            result = subprocess.run(
                ["rish", "-c",
                 f"am start -n {BROWSER_PACKAGE}/{BROWSER_ACTIVITY} -a android.intent.action.VIEW -d '{url}'"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return False, result.stderr[:200] if result.stderr else "am start 失败"
            return True, "ok"

        # 桌面端：尝试启动指定浏览器，否则回退系统默认
        browser_cmd = _desktop_browser_cmd()
        if browser_cmd:
            subprocess.Popen([browser_cmd, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"launched {os.path.basename(browser_cmd)}"
        # 回退：系统默认浏览器
        webbrowser.open(url)
        return True, "opened with default browser"
    except subprocess.TimeoutExpired:
        return False, "启动超时"
    except Exception as e:
        return False, str(e)
    finally:
        threading.Timer(5.0, browser_launching.clear).start()


def navigate_and_wait(url, tab_id=None, timeout=30):
    """导航到 URL 并等待加载完成"""
    target_domain = urlparse(url).netloc

    # 确定发送命令的 tab
    if tab_id is None:
        tab_id = find_most_recent_tab()
    if tab_id is None:
        return {"error": "no tab available"}, 503

    # 发送导航命令
    send_cmd(tab_id, {"action": "navigate", "url": url})

    # 等待任意 tab 出现在目标页面
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(1)
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
                    return {
                        "ok": True, "tabId": found_tab, "url": tab_url,
                        "elapsed": round(elapsed, 1), "readyState": ready
                    }, 200
    return {"error": "timeout", "url": url}, 408


def ensure_on_page(url, timeout=30):
    """确保有 tab 在目标页面（自动启动浏览器 + 导航）"""
    target_domain = urlparse(url).netloc

    # 1. 检查是否已有活跃 tab 在目标页面
    existing = find_tab_on_domain(target_domain)
    if existing and ping_tab(existing, timeout=5):
        with browser_lock:
            tab_url = browser_tabs[existing].get("url", "")
        return {
            "ok": True, "tabId": existing, "url": tab_url,
            "elapsed": 0, "readyState": "already_there"
        }, 200

    # 2. 没有 tab → 启动浏览器
    with browser_lock:
        has_tabs = bool(browser_tabs)
    if not has_tabs:
        ok, msg = launch_browser(url)
        if not ok:
            return {"error": f"启动浏览器失败: {msg}"}, 500

        # 等待 tab 注册
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(1)
            with browser_lock:
                if browser_tabs:
                    break
        existing = find_tab_on_domain(target_domain)
        if existing and ping_tab(existing, timeout=5):
            with browser_lock:
                tab_url = browser_tabs[existing].get("url", "")
            elapsed = time.time() - start
            return {
                "ok": True, "tabId": existing, "url": tab_url,
                "elapsed": round(elapsed, 1), "readyState": "launched"
            }, 200

    # 3. 有 tab 但不在目标页面 → 导航
    tab_id = find_most_recent_tab()
    if tab_id:
        result, code = navigate_and_wait(url, tab_id, timeout)
        if code == 200:
            return result, code

    return {"error": "ensure failed", "url": url}, 503


# ========== 结果/日志管理 ==========

def add_result(data):
    """添加执行结果"""
    with browser_lock:
        browser_results.append(data)
        if len(browser_results) > MAX_RESULTS:
            browser_results.pop(0)
        cmd_id = data.get("id")
        waiter = result_waiters.get(cmd_id)
        if waiter:
            result_cache[cmd_id] = data
            waiter.set()


def add_log(data):
    """添加日志"""
    with browser_lock:
        browser_logs.append(data)
        if len(browser_logs) > MAX_LOGS:
            browser_logs.pop(0)


def get_results(count=50):
    """获取最近执行结果"""
    with browser_lock:
        return browser_results[-count:]


def get_logs(count=100):
    """获取最近日志"""
    with browser_lock:
        return browser_logs[-count:]


def get_tabs_state():
    """获取所有 tab 状态"""
    with browser_lock:
        tabs = {}
        for tab_id, tab in browser_tabs.items():
            tabs[tab_id] = {
                "url": tab.get("url", ""),
                "updated_at": tab.get("updated_at", 0),
                "heartbeat": tab.get("heartbeat", {})
            }
        return tabs
