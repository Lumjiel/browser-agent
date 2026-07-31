#!/usr/bin/env python3
"""
shell_relay.py - Shell 命令中继 + 白名单安全机制
"""
import subprocess

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


def is_command_allowed(cmd):
    """检查命令是否在白名单中"""
    return any(cmd.startswith(p) for p in ALLOWED_PREFIXES)


def execute_shell(cmd, timeout=15):
    """执行 shell 命令并返回结果"""
    try:
        result = subprocess.run(
            ["rish", "-c", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "cmd": cmd
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时（{timeout}s）", "cmd": cmd}
    except Exception as e:
        return {"error": str(e), "cmd": cmd}


def validate_and_execute(cmd, token, provided_auth):
    """验证并执行 shell 命令"""
    # 验证 Token
    if provided_auth != f"Bearer {token}":
        return {"error": "token无效"}, 403
    
    # 验证命令非空
    if not cmd:
        return {"error": "缺少cmd"}, 400
    
    # 验证白名单
    if not is_command_allowed(cmd):
        return {
            "error": f"命令不在白名单: {cmd}",
            "allowed_prefixes": list(ALLOWED_PREFIXES)
        }, 403
    
    # 执行
    result = execute_shell(cmd)
    return result, 200
