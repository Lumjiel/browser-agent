#!/usr/bin/env python3
"""
ai_client.py - AI 问答客户端（薄层）
====================================
职责：读配置 + 调通用 API，不含任何平台特定逻辑。

新增平台：在 agents.yaml 加一段配置即可，无需改本文件。

用法：
  python3 ai_client.py "你的问题"                 # 问豆包
  python3 ai_client.py "你的问题" -a deepseek     # 问 DeepSeek
  python3 ai_client.py '{"task":"review","target":"..."}' -a doubao  # JSON 格式
  python3 ai_client.py --open "https://..."       # 打开 URL
  python3 ai_client.py --list                     # 列出平台
"""
import json
import os
import sys
import time
import urllib.request

# ========== 配置 ==========
API = "http://127.0.0.1:8123/api/browser"
AGENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "agents.yaml")

# ========== 加载平台配置 ==========

def load_agents():
    """从 agents.yaml 加载平台配置"""
    try:
        import yaml
        with open(AGENTS_FILE, "r") as f:
            return yaml.safe_load(f)
    except ImportError:
        return _parse_simple_yaml(AGENTS_FILE)


def _parse_simple_yaml(path):
    """极简 YAML 解析器"""
    agents = {}
    current_key = None
    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith(" ") and not line.startswith("\t"):
                current_key = stripped.rstrip(":")
                agents[current_key] = {}
            elif current_key and ":" in stripped:
                k, v = stripped.split(":", 1)
                v = v.strip().strip('"').strip("'")
                if v == "null":
                    v = None
                elif v.isdigit():
                    v = int(v)
                agents[current_key][k.strip()] = v
    return agents


# ========== HTTP 辅助 ==========

def api_post(path, data=None):
    body = json.dumps(data).encode() if data else b""
    req = urllib.request.Request(
        API + path, data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def api_get(path):
    try:
        with urllib.request.urlopen(API + path, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


# ========== 通用浏览器操作 ==========

def ensure_on_page(url, timeout=30):
    """确保有 tab 在目标页面"""
    result = api_post("/ensure", {"url": url, "timeout": timeout})
    if result.get("ok"):
        return result.get("tabId")
    return None


def interactive_cmd(action, tab_id=None, timeout=30, **kw):
    """同步执行命令并等待结果"""
    data = {"action": action, "timeout": timeout, **kw}
    if tab_id:
        data["tabId"] = tab_id
    return api_post("/interactive", data)


def async_cmd(action, tab_id=None, **kw):
    """异步提交命令"""
    data = {"action": action, **kw}
    if tab_id:
        data["tabId"] = tab_id
    return api_post("/command", data)


# ========== 问答流程 ==========

def ask(question, agent_key="doubao"):
    """向指定 AI 提问并获取回答

    question 可以是：
      - str: 普通文本问题
      - dict: 结构化问题（JSON 格式发送）
    """
    agents = load_agents()
    if agent_key not in agents:
        return {"error": f"未知平台: {agent_key}，可用: {list(agents.keys())}"}

    config = agents[agent_key]
    name = config.get("name", agent_key)
    url = config["url"]
    input_sel = config["input_selector"]
    send_sel = config.get("send_selector")
    answer_sel = config["answer_selector"]
    answer_text_path = config.get("answer_text_path", "self")
    min_len = config.get("min_answer_len", 20)
    system_role = config.get("system_role", "")
    prompt_hint = config.get("prompt_hint", "")
    question_format = config.get("question_format", "text")

    # 构造完整提示词
    full_prompt = _build_prompt(question, system_role, prompt_hint, question_format)

    print(f"🎯 目标: {name}")
    if isinstance(question, dict):
        print(f"📝 任务: {question.get('task', '问答')}")
        print(f"📝 目标: {str(question.get('target', ''))[:60]}")
    else:
        q = str(question)[:60] + "..." if len(str(question)) > 60 else question
        print(f"📝 问题: {q}")

    # 1. 确保在目标页面
    print(f"   切换到 {name}...")
    tab_id = ensure_on_page(url, timeout=30)
    if not tab_id:
        return {"error": f"无法切换到 {name}"}
    print(f"   ✅ 已在 {name} (tab: {tab_id[:12]}...)")

    # 2. 获取当前最后回答（用于后续对比）
    old_answer = _get_latest_answer(tab_id, answer_sel, answer_text_path, min_len)

    # 3. 输入问题
    result = interactive_cmd("type", tab_id=tab_id, selector=input_sel, text=full_prompt, timeout=15)
    if not result.get("ok"):
        return {"error": f"输入失败: {result.get('error', 'unknown')}"}

    time.sleep(0.5)

    # 4. 点击发送
    if send_sel:
        send_code = f"""(function() {{
            var btn = document.querySelector('{send_sel}');
            if (btn) {{ btn.click(); return 'clicked'; }}
            return 'not_found';
        }})()"""
    else:
        send_code = """(function() {
            var ta = document.querySelector('textarea[placeholder*="发消息"]');
            if (!ta) return 'no textarea';
            var container = ta;
            for (var i = 0; i < 10; i++) {
                container = container.parentElement;
                if (!container) break;
                if (container.querySelectorAll('button').length > 1) break;
            }
            var btns = Array.from(container.querySelectorAll('button')).filter(function(b) {
                var r = b.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && b.querySelector('svg') && (b.innerText || '').trim() === '';
            });
            if (btns.length === 0) return 'no_svg_btns';
            btns.sort(function(a, b) { return b.getBoundingClientRect().x - a.getBoundingClientRect().x; });
            btns[0].click();
            return 'clicked';
        })()"""
    result = interactive_cmd("eval", tab_id=tab_id, code=send_code, timeout=15)
    if not result.get("ok"):
        return {"error": f"发送失败: {result.get('error', 'unknown')}"}

    # 5. 等待回答完成
    print("   等待回答...")
    answer = _wait_for_answer(tab_id, answer_sel, answer_text_path, min_len, timeout=120)
    if not answer:
        return {"error": "提取回答失败"}

    return {"ok": True, "question": question, "answer": answer, "agent": agent_key}


def _build_prompt(question, system_role, prompt_hint, question_format):
    """构造完整提示词"""
    parts = []
    if system_role:
        parts.append(system_role.strip())
    if prompt_hint:
        parts.append(prompt_hint.strip())
    if isinstance(question, dict) and question_format == "json":
        parts.append("\n请回答以下问题：")
        parts.append(json.dumps(question, ensure_ascii=False, indent=2))
    else:
        parts.append(f"\n## 我的问题\n{question}")
    return "\n\n".join(parts)


def _wait_for_answer(tab_id, answer_selector, answer_text_path, min_len, timeout=120):
    """轮询等待回答完成"""
    prev_len = 0
    stable_count = 0
    start = time.time()
    last_report = 0

    while time.time() - start < timeout:
        time.sleep(3)
        current = _get_latest_answer(tab_id, answer_selector, answer_text_path, 0)
        current_len = len(current) if current else 0

        if current_len > 0 and current_len == prev_len:
            stable_count += 1
            if stable_count >= 2:
                elapsed = time.time() - start
                print(f"   ✅ 回答完成 ({elapsed:.0f}s, {current_len} 字)")
                return current
        else:
            stable_count = 0

        prev_len = current_len

        elapsed = time.time() - start
        if elapsed - last_report >= 10:
            last_report = elapsed
            print(f"   ⏳ 生成中 ({elapsed:.0f}s, {current_len} 字)")

    current = _get_latest_answer(tab_id, answer_selector, answer_text_path, 0)
    if current:
        print(f"   ⚠️ 超时但返回已有内容 ({len(current)} 字)")
        return current
    return None


def _get_latest_answer(tab_id, answer_selector, answer_text_path, min_len):
    """提取最新回答"""
    if answer_text_path == "first_grid_child":
        code = f"""(function() {{
            var els = document.querySelectorAll('{answer_selector}');
            var candidates = Array.from(els).filter(e => {{
                var grid = e.querySelector('.relative.grid.w-full');
                return grid && grid.innerText.trim().length > {min_len};
            }});
            if (candidates.length > 0) {{
                var last = candidates[candidates.length - 1];
                var grid = last.querySelector('.relative.grid.w-full');
                return grid ? grid.innerText.trim() : '';
            }}
            return '';
        }})()"""
    else:
        code = f"""(function() {{
            var els = document.querySelectorAll('{answer_selector}');
            var candidates = Array.from(els).filter(e => e.innerText.trim().length > {min_len});
            if (candidates.length > 0) return candidates[candidates.length - 1].innerText.trim();
            return '';
        }})()"""
    result = interactive_cmd("eval", tab_id=tab_id, code=code, timeout=10)
    if result.get("ok"):
        return result.get("result", {}).get("value", "")
    return ""


def _format_answer(result):
    """格式化输出回答"""
    return result.get("answer", "")


# ========== CLI ==========

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="AI 问答客户端（通用）",
        epilog="新增平台只需在 agents.yaml 加配置，无需改代码"
    )
    parser.add_argument("question", nargs="?", help="要提问的问题（或 JSON 字符串）")
    parser.add_argument("--agent", "-a", default="doubao",
                        help="目标 AI（在 agents.yaml 中定义）")
    parser.add_argument("--multi", "-m", action="store_true",
                        help="多 AI 讨论模式")
    parser.add_argument("--open", "-o", metavar="URL",
                        help="打开指定 URL（全自动）")
    parser.add_argument("--list", "-l", action="store_true",
                        help="列出所有可用平台")
    args = parser.parse_args()

    agents = load_agents()

    if args.list:
        print("可用平台：")
        for key, config in agents.items():
            print(f"  {key:12} → {config.get('name', key)} ({config.get('url', '?')[:50]})")
        sys.exit(0)

    if args.open:
        tab_id = ensure_on_page(args.open, timeout=30)
        if tab_id:
            print(f"✅ 已打开, tab_id: {tab_id}")
        else:
            print("❌ 打开失败")
        sys.exit(0 if tab_id else 1)

    if not args.question:
        parser.print_help()
        sys.exit(1)

    # 尝试解析 JSON 问题
    try:
        question = json.loads(args.question)
    except (json.JSONDecodeError, ValueError):
        question = args.question

    if args.multi:
        results = []
        for key in agents:
            print(f"\n{'='*50}")
            result = ask(question, key)
            results.append(result)
            if result.get("ok"):
                name = agents[key].get("name", key)
                print(f"\n✅ {name} 回答:")
                print(_format_answer(result))
            else:
                print(f"\n❌ {agents[key].get('name', key)} 失败: {result.get('error')}")
        print(f"\n{'='*50}")
        print(f"📊 讨论完成，共 {len([r for r in results if r.get('ok')])} 个 AI 回答")
    else:
        result = ask(question, args.agent)
        print()
        if result.get("ok"):
            name = agents.get(args.agent, {}).get("name", args.agent)
            print(f"✅ {name} 回答:")
            print(_format_answer(result))
        else:
            print(f"❌ 错误:", result.get("error"))
