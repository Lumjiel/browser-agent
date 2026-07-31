#!/usr/bin/env python3
"""
config.py - 配置加载模块
"""
import json
import os

# 配置文件路径（相对于本文件所在目录）
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CONFIG_DIR, "..", "config", "config.json")
CONFIG_EXAMPLE_FILE = os.path.join(CONFIG_DIR, "..", "config", "config.example.json")

# 默认配置
DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": 8123,
        "token": "MY_SECRET_123456"
    },
    "browser": {
        "package": "com.mmbox.xbrowser",
        "activity": ".BrowserActivity"
    },
    "features": {
        "shell_whitelist": True,
        "auto_launch_browser": True,
        "log_results": True,
        "max_results": 500,
        "max_logs": 200
    }
}


def load_config():
    """加载配置，优先从 config.json，否则用默认值"""
    config = DEFAULT_CONFIG.copy()
    
    # 尝试读取 config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # 深度合并
            for key, value in user_config.items():
                if key in config and isinstance(config[key], dict):
                    config[key].update(value)
                else:
                    config[key] = value
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 读取配置文件失败: {e}，使用默认配置")
    
    return config


def get_server_config():
    """获取服务端配置"""
    return load_config()["server"]


def get_browser_config():
    """获取浏览器配置"""
    return load_config()["browser"]


def get_feature_config():
    """获取功能配置"""
    return load_config()["features"]
