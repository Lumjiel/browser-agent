#!/usr/bin/env python3
"""
browser_manager.py - 浏览器 Tab 管理 + 导航逻辑
"""
import subprocess
import threading
import time
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


# ========== Tab 管理 ==========

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
        now = time.time()
        for tid, info in browser_tabs.items():
            # 跳过超过 60 秒没有心跳的 tab（可能已关闭或脚本崩溃）
            updated_at = info.get("updated_at", 0)
            if now - updated_at > 60:
                continue
            if domain in info.get("url", "") and updated_at > best_time:
                best_tab = tid
                best_time = updated_at
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


# ========== 浏览器启动与导航 ==========

def launch_browser_via_adb(url):
    """通过 ADB 启动浏览器打开 URL"""
    if browser_launching.is_set():
        return False, "已有启动操作进行中"
    browser_launching.set()
    try:
        result = subprocess.run(
            ["rish", "-c",
             f"am start -n {BROWSER_PACKAGE}/{BROWSER_ACTIVITY} -a android.intent.action.VIEW -d '{url}'"],
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
        ok, msg = launch_browser_via_adb(url)
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
        waiter = result_waiters.get(data.get("id"))
        if waiter:
            result_cache[data.get("id")] = data
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
        for tid, info in browser_tabs.items():
            tabs[tid] = {
                "url": info.get("url", ""),
                "updated_at": info.get("updated_at", 0),
                "last_heartbeat": info.get("heartbeat", {}),
            }
        return tabs
