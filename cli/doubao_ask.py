#!/usr/bin/env python3
"""
doubao_ask.py - 多 AI 问答客户端（Pi 端直接控制）
用法:
  python3 doubao_ask.py "你的问题"           # 问豆包（默认）
  python3 doubao_ask.py "你的问题" -a deepseek  # 问 Deepseek
  python3 doubao_ask.py "你的问题" -m          # 多 AI 讨论模式
"""
import json
import time
import sys
import subprocess
import urllib.request

API = "http://127.0.0.1:8123/api/browser"

# AI 站点配置
AGENTS = {
    "doubao": {
        "name": "豆包",
        "url": "https://www.doubao.com/chat/",
        "input_selector": 'textarea[placeholder*="消息"]',
        "send_selector": None,  # 自动检测（找 textarea 最近的 SVG 按钮）
        "answer_selector": ".my-0.w-full.mx-auto",
        "min_answer_len": 20,
    },
    "deepseek": {
        "name": "Deepseek",
        "url": "https://chat.deepseek.com/",
        "input_selector": 'textarea[placeholder*="提问"]',
        "send_selector": None,
        "answer_selector": ".message-content",
        "min_answer_len": 20,
    },
    "qwen": {
        "name": "千问",
        "url": "https://chat.qwen.ai/",
        "input_selector": 'textarea[placeholder*="提问"]',
        "send_selector": None,
        "answer_selector": ".message-bubble",
        "min_answer_len": 20,
    },
}


def api_post(path, data=None):
    body = json.dumps(data).encode() if data else b""
    req = urllib.request.Request(
        API + path, data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def api_get(path):
    try:
        with urllib.request.urlopen(API + path, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def get_all_tabs():
    """获取所有 tab 信息"""
    data = api_get("/state")
    return data.get("tabs", {})


def find_tab_by_url(domain):
    """根据域名查找 tab"""
    tabs = get_all_tabs()
    for tid, info in tabs.items():
        if domain in info.get("url", ""):
            return tid
    return None


def send_cmd(action, tab_id=None, **kw):
    data = {"action": action}
    if tab_id:
        data["tabId"] = tab_id
    data.update(kw)
    return api_post("/command", data)


def get_results():
    return api_get("/results")


def get_result_by_id(cmd_id, timeout=30):
    """根据 cmd_id 获取结果"""
    start = time.time()
    while time.time() - start < timeout:
        results = get_results().get("results", [])
        for r in results:
            if r.get("id") == cmd_id:
                return r
        time.sleep(0.5)
    return None


def wait_for_result(cmd_id, timeout=30):
    """等待指定 cmd_id 的结果（带重试）"""
    result = get_result_by_id(cmd_id, timeout)
    if result and result.get("ok"):
        return result
    return result  # 返回 None 或失败结果


def get_current_url(tab_id):
    r = send_cmd("eval", tab_id=tab_id, code="window.location.href")
    result = get_result_by_id(r.get("cmdId"), timeout=10)
    if result and result.get("ok"):
        return result.get("result", {}).get("value", "")
    return ""


def navigate_to(url, timeout=10):
    """导航到新页面（会打开新 tab）"""
    print(f"   导航到: {url}")
    # 用 eval 在当前页面导航
    tabs = get_all_tabs()
    if tabs:
        tab_id = list(tabs.keys())[0]
        send_cmd("eval", tab_id=tab_id, code=f"window.location.href = '{url}'")
        time.sleep(timeout)
    return True


def navigate_and_wait(url, timeout=30):
    """导航到 URL 并等待页面加载完成。

    1. 发送 navigate 命令到浏览器
    2. 轮询 /api/browser.state 直到目标 URL 出现且 readyState=complete
    3. 返回 tab_id

    Args:
        url: 目标 URL
        timeout: 最大等待秒数

    Returns:
        tab_id 或 None（超时）
    """
    from urllib.parse import urlparse
    target_domain = urlparse(url).netloc
    print(f"   导航到: {url} (timeout={timeout}s)")

    # 先检查是否已有 tab 在目标页面且能响应
    tabs = get_all_tabs()
    for tid, info in tabs.items():
        if target_domain in info.get("url", ""):
            # ping 测试是否活跃
            r = send_cmd("ping", tab_id=tid)
            ping_result = wait_for_result(r.get("cmdId"), timeout=5)
            if ping_result and ping_result.get("ok"):
                print(f"   ✅ 已有活跃 tab 在目标页面: {info['url'][:60]}")
                return tid

    # 没有活跃 tab，找最近活跃的 tab 来导航（避免挑到后台节流 tab）
    tab_id = None
    for tid, info in tabs.items():
        if target_domain in info.get("url", ""):
            tab_id = tid
            break
    if not tab_id and tabs:
        # 挑 updated_at 最新的 tab（前台活跃 tab）
        tab_id = max(tabs, key=lambda tid: tabs[tid].get("updated_at", 0))

    if not tab_id:
        print("   ⚠️ 没有可用 tab")
        return None

    # 发送 navigate 命令
    send_cmd("navigate", tab_id=tab_id, url=url)

    # 轮询等待加载完成
    start = time.time()
    last_report = 0
    while time.time() - start < timeout:
        time.sleep(1)
        tabs = get_all_tabs()
        for tid, info in tabs.items():
            tab_url = info.get("url", "")
            hb = info.get("last_heartbeat", {})
            ready = hb.get("readyState", "")
            # 检查 URL 匹配且页面加载完成
            # SPA（如豆包）可能一直停留在 interactive，也视为可用
            if target_domain in tab_url and ready in ("interactive", "complete"):
                # 验证油猴脚本是否活跃（ping 测试）
                r = send_cmd("ping", tab_id=tid)
                ping_result = wait_for_result(r.get("cmdId"), timeout=5)
                if ping_result and ping_result.get("ok"):
                    elapsed = time.time() - start
                    print(f"   ✅ 加载完成 ({elapsed:.1f}s, {ready}): {tab_url[:80]}")
                    return tid
                # ping 失败，继续等待
        # 每 5 秒报告一次进度
        elapsed = time.time() - start
        if elapsed - last_report >= 5:
            last_report = elapsed
            tabs = get_all_tabs()
            status = []
            for tid, info in tabs.items():
                hb = info.get("last_heartbeat", {})
                status.append(f"{tid[:8]}... -> {info.get('url', '?')[:50]} [{hb.get('readyState', '?')}]")
            print(f"   ⏳ 等待中 ({elapsed:.0f}s): {'; '.join(status)}")

    print(f"   ❌ 导航超时 ({timeout}s)")
    return None


def open_url(url, timeout=30):
    """全自动打开一个 URL：从启动浏览器到确认页面加载完成。

    流程：
    1. 检查是否有活跃 tab 已在目标页面 → 直接返回
    2. 有 tab 但不活跃 → 用 navigate_and_wait 导航
    3. 没有任何 tab → ADB 启动 XBrowser 打开网址，等待注册

    Args:
        url: 目标 URL
        timeout: 最大等待秒数

    Returns:
        tab_id 或 None（超时）
    """
    from urllib.parse import urlparse
    target_domain = urlparse(url).netloc
    print(f"🔗 open_url: {url}")

    # 1. 检查是否已有活跃 tab 在目标页面
    tabs = get_all_tabs()
    for tid, info in tabs.items():
        if target_domain in info.get("url", ""):
            r = send_cmd("ping", tab_id=tid)
            ping_result = wait_for_result(r.get("cmdId"), timeout=5)
            if ping_result and ping_result.get("ok"):
                print(f"   ✅ 已有活跃 tab: {info['url'][:60]}")
                return tid

    # 2. 有 tab 但不活跃，尝试导航
    if tabs:
        print(f"   有 {len(tabs)} 个 tab，尝试导航...")
        return navigate_and_wait(url, timeout=timeout)

    # 3. 没有任何 tab，用 ADB 启动浏览器
    print(f"   没有 tab，启动浏览器...")
    try:
        result = subprocess.run(
            ["rish", "-c",
             f"am start -a android.intent.action.VIEW -d '{url}'"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"   ⚠️ am start 失败: {result.stderr[:200]}")
            return None
        print(f"   浏览器已启动，等待页面注册...")
    except subprocess.TimeoutExpired:
        print(f"   ⚠️ am start 超时")
        return None
    except Exception as e:
        print(f"   ⚠️ am start 异常: {e}")
        return None

    # 4. 等待 tab 注册 + 页面加载完成
    start = time.time()
    last_report = 0
    while time.time() - start < timeout:
        time.sleep(1)
        tabs = get_all_tabs()
        for tid, info in tabs.items():
            tab_url = info.get("url", "")
            hb = info.get("last_heartbeat", {})
            ready = hb.get("readyState", "")
            if target_domain in tab_url and ready in ("interactive", "complete"):
                r = send_cmd("ping", tab_id=tid)
                ping_result = wait_for_result(r.get("cmdId"), timeout=5)
                if ping_result and ping_result.get("ok"):
                    elapsed = time.time() - start
                    print(f"   ✅ 加载完成 ({elapsed:.1f}s): {tab_url[:80]}")
                    return tid
        elapsed = time.time() - start
        if elapsed - last_report >= 5:
            last_report = elapsed
            if tabs:
                status = [f"{tid[:8]}... -> {info.get('url','?')[:50]}"
                          for tid, info in tabs.items()]
                print(f"   ⏳ 等待中 ({elapsed:.0f}s): {'; '.join(status)}")
            else:
                print(f"   ⏳ 等待 tab 注册 ({elapsed:.0f}s)...")

    print(f"   ❌ open_url 超时 ({timeout}s)")
    return None


def ensure_on_page(agent_key):
    """确保当前页面是目标 AI，不是则导航过去"""
    agent = AGENTS[agent_key]
    target_domain = agent["url"].split("/")[2]

    # 检查是否有 tab 已经在目标页面且能响应
    tab_id = find_working_tab(target_domain)
    if tab_id:
        print(f"   找到 {agent['name']} tab: {tab_id[:15]}...")
        return tab_id

    # 没有则打开页面（全自动：有 tab 导航，没 tab 启动浏览器）
    print(f"   当前不在 {agent['name']}，正在切换...")
    tab_id = open_url(agent["url"], timeout=30)
    if tab_id:
        print(f"   切换到 {agent['name']} tab: {tab_id[:15]}...")
        return tab_id

    print(f"   ⚠️ 未能找到 {agent['name']} tab")
    return None


def find_working_tab(domain, timeout=5):
    """找到能响应 ping 的 tab"""
    tabs = get_all_tabs()
    for tid, info in tabs.items():
        if domain in info.get("url", ""):
            # 测试是否能响应
            r = send_cmd("ping", tab_id=tid)
            result = wait_for_result(r.get("cmdId"), timeout=timeout)
            if result and result.get("ok"):
                return tid
    return None


def click_latest_conversation(tab_id):
    """点击最新对话"""
    click_code = """(function() {
        var items = document.querySelectorAll('.flex.flex-col.gap-2 > div a');
        if (items.length > 0) { items[0].click(); return 'clicked'; }
        return 'not_found';
    })()"""
    r = send_cmd("eval", tab_id=tab_id, code=click_code)
    return wait_for_result(r.get("cmdId"), timeout=10)


def get_latest_answer(tab_id, agent_key):
    """获取最新回答"""
    agent = AGENTS[agent_key]
    selector = agent["answer_selector"]
    min_len = agent["min_answer_len"]

    code = f"""(function() {{
        var els = document.querySelectorAll('{selector}');
        var candidates = Array.from(els).filter(e => e.innerText.trim().length > {min_len});
        if (candidates.length > 0) return candidates[candidates.length - 1].innerText.trim();
        return '';
    }})()"""
    r = send_cmd("eval", tab_id=tab_id, code=code)
    result = wait_for_result(r.get("cmdId"), timeout=10)
    if result and result.get("ok"):
        return result.get("result", {}).get("value", "")
    return ""


def ask_ai(question, agent_key="doubao"):
    """向指定 AI 提问并获取回答"""
    agent = AGENTS[agent_key]
    print(f"🎯 目标: {agent['name']}")
    print(f"📝 问题: {question}")

    # 1. 确保在正确的页面，获取 tab_id
    tab_id = ensure_on_page(agent_key)
    if not tab_id:
        return {"error": f"无法找到 {agent['name']} 页面"}

    # 2. 记录发送前的最后一个回答
    old_answer = get_latest_answer(tab_id, agent_key)

    # 3. 输入问题（异步 + 轮询）
    r = send_cmd("type", tab_id=tab_id, selector=agent["input_selector"], text=question)
    result = wait_for_result(r.get("cmdId"), timeout=15)
    if not result or not result.get("ok"):
        return {"error": "输入失败"}

    time.sleep(0.5)

    # 4. 点击发送按钮
    if agent.get("send_selector"):
        click_code = f"""(function() {{
            var btn = document.querySelector('{agent["send_selector"]}');
            if (btn) {{ btn.click(); return 'clicked'; }}
            return 'not_found';
        }})()"""
    else:
        click_code = """(function() {
            var ta = document.querySelector('textarea');
            if (!ta) return 'no textarea';
            var taRect = ta.getBoundingClientRect();
            var btns = Array.from(document.querySelectorAll('button')).filter(function(b) {
                return b.querySelector('svg') && b.innerText.trim() === '';
            });
            if (btns.length === 0) return 'no_svg_btns';
            var nearest = btns[0];
            var nearestDist = Infinity;
            for (var i = 0; i < btns.length; i++) {
                var r = btns[i].getBoundingClientRect();
                var dist = Math.abs(r.y - taRect.y) + Math.abs(r.x - taRect.x);
                if (dist < nearestDist) { nearestDist = dist; nearest = btns[i]; }
            }
            nearest.click();
            return 'clicked';
        })()"""
    r = send_cmd("eval", tab_id=tab_id, code=click_code)
    result = wait_for_result(r.get("cmdId"), timeout=15)
    if not result or not result.get("ok"):
        return {"error": "点击发送失败"}

    # 5. 等待回答
    print("   等待回答...")
    time.sleep(15)  # 固定等待 15 秒

    # 6. 点击最新对话
    click_latest_conversation(tab_id)
    time.sleep(3)

    # 7. 提取最新回答
    answer = get_latest_answer(tab_id, agent_key)
    if not answer:
        return {"error": "提取回答失败"}

    return {"ok": True, "question": question, "answer": answer, "agent": agent_key}


def multi_ai_discussion(question, agents=None):
    """多 AI 讨论：依次向多个 AI 提问"""
    if agents is None:
        agents = ["doubao", "deepseek", "qwen"]

    results = []
    for agent_key in agents:
        if agent_key not in AGENTS:
            continue
        print(f"\n{'='*50}")
        result = ask_ai(question, agent_key)
        results.append(result)
        if result.get("ok"):
            print(f"\n✅ {AGENTS[agent_key]['name']} 回答:")
            print(result["answer"][:300])
        else:
            print(f"\n❌ {AGENTS[agent_key]['name']} 失败: {result.get('error')}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="多 AI 问答客户端")
    parser.add_argument("question", nargs="?", help="要提问的问题")
    parser.add_argument("--agent", "-a", default="doubao",
                        choices=list(AGENTS.keys()),
                        help="目标 AI")
    parser.add_argument("--multi", "-m", action="store_true",
                        help="多 AI 讨论模式")
    parser.add_argument("--open", "-o", metavar="URL",
                        help="打开指定 URL（全自动：启动浏览器→确认加载）")
    args = parser.parse_args()

    # 优先处理 --open
    if args.open:
        tab_id = open_url(args.open, timeout=30)
        if tab_id:
            print(f"\n✅ 已打开, tab_id: {tab_id}")
        else:
            print(f"\n❌ 打开失败")
        sys.exit(0 if tab_id else 1)

    if not args.question:
        parser.print_help()
        sys.exit(1)

    if args.multi:
        results = multi_ai_discussion(args.question)
        print(f"\n{'='*50}")
        print(f"📊 讨论完成，共 {len([r for r in results if r.get('ok')])} 个 AI 回答")
    else:
        result = ask_ai(args.question, args.agent)
        print()
        if result.get("ok"):
            print(f"✅ {AGENTS[args.agent]['name']} 回答:")
            print(result["answer"])
        else:
            print(f"❌ 错误:", result.get("error"))
