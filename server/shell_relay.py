#!/usr/bin/env python3
"""
shell_relay.py - Shell 命令中继 + 白名单安全机制（跨平台）
"""
import os
import subprocess
import shutil
import sys

# 命令白名单（安全！只允许这些前缀）
ALLOWED_PREFIXES = (
    # 输入模拟（Android）
    "input tap", "input swipe", "input text", "input keyevent",
    # UI 获取（Android）
    "uiautomator dump", "screencap",
    # 应用管理（Android）
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

# 桌面端额外允许的命令（只读/安全命令）
DESKTOP_ALLOWED_PREFIXES = (
    "echo ", "ls ", "cat ", "head ", "tail ", "pwd", "whoami", "date",
    "uname", "which ", "env", "printenv", "id", "hostname",
    "dir ", "type ", "find ", "more ", "tree ",
)


def _is_android():
    """检测是否为 Android/Termux 环境"""
    if sys.platform != "linux":
        return False
    return shutil.which("rish") is not None


def is_command_allowed(cmd):
    """检查命令是否在白名单中"""
    # 检查 Android 白名单
    if any(cmd.startswith(p) for p in ALLOWED_PREFIXES):
        return True
    # 桌面端额外白名单
    if any(cmd.startswith(p) for p in DESKTOP_ALLOWED_PREFIXES):
        return True
    return False


def execute_shell(cmd, timeout=15):
    """执行 shell 命令并返回结果（跨平台）"""
    try:
        if _is_android():
            # Android: 通过 rish/Shizuku 执行
            result = subprocess.run(
                ["rish", "-c", cmd],
                capture_output=True, text=True, timeout=timeout
            )
        else:
            # 桌面端：直接执行（shell=True 以支持管道/重定向）
            result = subprocess.run(
                cmd, shell=True,
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PATH": os.environ.get("PATH", "")}
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
            "allowed_prefixes": list(ALLOWED_PREFIXES) + list(DESKTOP_ALLOWED_PREFIXES)
        }, 403
    
    # 执行
    result = execute_shell(cmd)
    return result, 200
