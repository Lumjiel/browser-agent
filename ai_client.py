#!/usr/bin/env python3
"""
ai_client.py - AI 问答客户端（通用引擎）
====================================
职责：读平台配置 + 调桥接服务 API。本文件不含任何平台特定逻辑。

平台配置在 agents/<key>/ 目录（一个平台一个目录，纯数据）：
  agents/<key>/config.yaml       # selector 等标量配置
  agents/<key>/system_role.txt   # 角色设定（可选）
  agents/<key>/prompt_hint.txt   # 回答风格提示（可选）
  agents/<key>/strategies/<task>.txt  # 按 task 类型的搜索策略（可选）

新增平台 = 新建一个目录，零代码改动。

用法：
  python3 ai_client.py "你的问题"                 # 问豆包（默认）
  python3 ai_client.py "你的问题" -a deepseek     # 问 DeepSeek
  python3 ai_client.py '{"task":"review","target":"..."}' -a doubao  # JSON 格式
  python3 ai_client.py open "https://..."         # 打开 URL
  python3 ai_client.py list                       # 列出平台
"""
import json
import os
import sys
import time
import urllib.request

# ========== 配置 ==========
API = "http://127.0.0.1:8123/api/browser"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(BASE_DIR, "agents")
AGENTS_FILE = os.path.join(BASE_DIR, "agents.yaml")  # 旧版单文件配置（兜底）

# ========== 加载平台配置 ==========

def load_agents():
    """加载平台配置

    优先扫描 agents/<key>/ 目录（每平台一个目录）；
    目录不存在时回退到旧版 agents.yaml 单文件。
    """
    if os.path.isdir(AGENTS_DIR):
        agents = {}
        for key in sorted(os.listdir(AGENTS_DIR)):
            pdir = os.path.join(AGENTS_DIR, key)
            cfg_path = os.path.join(pdir, "config.yaml")
            if not os.path.isfile(cfg_path):
                continue
            config = _parse_simple_yaml(cfg_path)
            # 提示词文本文件（可选）
            for field, fname in (("system_role", "system_role.txt"),
                                 ("prompt_hint", "prompt_hint.txt")):
                fpath = os.path.join(pdir, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "r") as f:
                        config[field] = f.read().strip()
            # 搜索策略 strategies/<task>.txt（可选）
            sdir = os.path.join(pdir, "strategies")
            if os.path.isdir(sdir):
                strategies = {}
                for fname in os.listdir(sdir):
                    if fname.endswith(".txt"):
                        with open(os.path.join(sdir, fname), "r") as f:
                            strategies[fname[:-4]] = f.read().strip()
                if strategies:
                    config["search_strategies"] = strategies
            agents[key] = config
        return agents
    # 兜底：旧版单文件配置
    try:
        import yaml
        with open(AGENTS_FILE, "r") as f:
            return yaml.safe_load(f)
    except ImportError:
        return _parse_simple_yaml(AGENTS_FILE)


def _parse_simple_yaml(path):
    """极简 YAML 解析器（零依赖）

    支持两种结构：
      1. 扁平: key: value                    （agents/<key>/config.yaml）
      2. 两级: section:\n  key: value        （旧版 agents.yaml）
    """
    def _clean(v):
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if v == "null":
            return None
        if v.isdigit():
            return int(v)
        return v

    agents = {}
    current_key = None
    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indented = line.startswith(" ") or line.startswith("\t")
            if not indented:
                if stripped.endswith(":"):
                    # 段落头（两级结构）
                    current_key = stripped[:-1]
                    agents[current_key] = {}
                elif ":" in stripped:
                    # 扁平 key: value
                    k, v = stripped.split(":", 1)
                    agents[_clean(k)] = _clean(v)
                    current_key = None
            elif current_key and ":" in stripped:
                k, v = stripped.split(":", 1)
                agents[current_key][_clean(k)] = _clean(v)
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


def upload_file(file_path, tab_id=None, file_input_selector=None, timeout=15):
    """上传文件到浏览器页面（通过 base64 + DataTransfer 注入）

    原理：读取本地文件 → base64 编码 → 在浏览器中构造 File 对象 →
          DataTransfer 注入到 <input[type=file]> → 触发 change 事件

    Args:
        file_path: 本地文件路径（Termux 中的路径）
        tab_id: 浏览器 tab ID（None = 使用最近活跃 tab）
        file_input_selector: 文件输入框 CSS 选择器
                            （None = 自动查找 input[type=file]）
        timeout: 超时秒数

    Returns:
        dict: {"ok": bool, "fileName": str, "size": int} 或 {"error": str}
    """
    import base64
    import os

    # 1. 读取文件
    if not os.path.isfile(file_path):
        return {"error": f"文件不存在: {file_path}"}

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    if file_size > 50 * 1024 * 1024:  # 50MB 限制
        return {"error": f"文件过大: {file_size} bytes (最大 50MB)"}

    try:
        with open(file_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        return {"error": f"读取文件失败: {e}"}

    # 2. 构造注入 JS（使用字符串拼接避免转义冲突）
    js_parts = [
        "(function(){",
        "  try {",
        "    var b64 = \"" + b64_data + "\";",
        "    var binary = atob(b64);",
        "    var bytes = new Uint8Array(binary.length);",
        "    for (var i = 0; i < binary.length; i++) {",
        "      bytes[i] = binary.charCodeAt(i);",
        "    }",
        "    var blob = new Blob([bytes]);",
        "    var file = new File([blob], \"" + file_name + "\");",
        "    var input = document.querySelector('" + (file_input_selector or "input[type=file]") + "');",
        "    if (!input) return JSON.stringify({ok:false, error:\"file input not found\"});",
        "    var dt = new DataTransfer();",
        "    dt.items.add(file);",
        "    input.files = dt.files;",
        "    input.dispatchEvent(new Event('change', {bubbles: true}));",
        "    input.dispatchEvent(new Event('input', {bubbles: true}));",
        "    return JSON.stringify({ok:true, fileName:file.name, size:file.size});",
        "  } catch(e) {",
        "    return JSON.stringify({ok:false, error:e.message});",
        "  }",
        "})()"
    ]
    inject_js = "\n".join(js_parts)

    # 3. 执行注入（使用异步命令 + 轮询结果，避免 interactive 超时）
    cmd_result = api_post("/command", {
        "action": "eval",
        "tabId": tab_id,
        "code": inject_js
    })

    if not cmd_result.get("ok"):
        return {"error": f"提交命令失败: {cmd_result.get('error', 'unknown')}"}

    cmd_id = cmd_result.get("cmdId")

    # 4. 轮询等待结果（最多 timeout 秒）
    import time
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(1)
        results_resp = api_get("/results")
        for r in results_resp.get("results", []):
            if r.get("id") == cmd_id:
                if r.get("ok"):
                    try:
                        value = r.get("result", {}).get("value", "")
                        return json.loads(value)
                    except (json.JSONDecodeError, TypeError) as e:
                        return {"error": f"解析结果失败: {e}", "raw": str(r)[:200]}
                else:
                    return {"error": f"执行失败: {r.get('error', 'unknown')}"}

    return {"error": f"轮询超时 ({timeout}s)"}


def async_cmd(action, tab_id=None, **kw):
    """异步提交命令"""
    data = {"action": action, **kw}
    if tab_id:
        data["tabId"] = tab_id
    return api_post("/command", data)


# ========== 问答流程 ==========

def ask(question, agent_key="doubao", first_round=True, file_path=None):
    """向指定 AI 提问并获取回答

    question 可以是：
      - str: 普通文本问题
      - dict: 结构化问题（JSON 格式发送）
    first_round: True=首轮（注入完整提示词），False=后续轮次（只发问题）
    file_path: 可选，上传文件路径（上传后再发消息）
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

    # 构造提示词：首轮注入完整提示词，后续轮次只发问题
    full_prompt = _build_prompt(question, system_role, prompt_hint, question_format, agent_key, first_round)

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

    # 1.5 上传文件（如果指定）
    if file_path:
        file_input_sel = config.get("file_input_selector")
        print(f"   📎 上传文件: {file_path}")
        upload_result = upload_file(file_path, tab_id=tab_id, file_input_selector=file_input_sel)
        if not upload_result.get("ok"):
            return {"error": f"文件上传失败: {upload_result.get('error', 'unknown')}"}
        print(f"   ✅ 文件已上传: {upload_result.get('fileName', '?')} ({upload_result.get('size', '?')} bytes)")
        time.sleep(1)  # 等待文件处理

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
        # structure_detect: 表单容器内最右边的 SVG 无文字按钮（不依赖类名/坐标）
        send_code = f"""(function() {{
            var ta = document.querySelector('{input_sel}');
            if (!ta) return 'no input';
            var container = ta;
            for (var i = 0; i < 10; i++) {{
                container = container.parentElement;
                if (!container) break;
                if (container.querySelectorAll('button').length > 1) break;
            }}
            var btns = Array.from(container.querySelectorAll('button')).filter(function(b) {{
                var r = b.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && b.querySelector('svg') && (b.innerText || '').trim() === '';
            }});
            if (btns.length === 0) return 'no_svg_btns';
            btns.sort(function(a, b) {{ return b.getBoundingClientRect().x - a.getBoundingClientRect().x; }});
            btns[0].click();
            return 'clicked';
        }})()"""
    result = interactive_cmd("eval", tab_id=tab_id, code=send_code, timeout=15)
    if not result.get("ok"):
        return {"error": f"发送失败: {result.get('error', 'unknown')}"}

    # 5. 等待回答完成
    print("   等待回答...")
    answer = _wait_for_answer(tab_id, answer_sel, answer_text_path, min_len, timeout=120)
    if not answer:
        return {"error": "提取回答失败"}

    return {"ok": True, "question": question, "answer": answer, "agent": agent_key}


def _build_prompt(question, system_role, prompt_hint, question_format, agent_key, first_round=True):
    """构造完整提示词

    first_round=True: 注入 system_role + 搜索策略 + prompt_hint（首轮对话）
    first_round=False: 只发用户问题（后续轮次，AI 已记住上下文）
    """
    # 后续轮次：只发问题，不注入任何提示词
    if not first_round:
        if isinstance(question, dict):
            return json.dumps(question, ensure_ascii=False, indent=2)
        return str(question)

    # 首轮：注入完整提示词
    parts = []
    if system_role:
        parts.append(system_role.strip())

    # 搜索策略注入（按 task 类型 + 平台）
    search_instr = _get_search_instruction(question, agent_key)
    if search_instr:
        parts.append(search_instr)

    if prompt_hint:
        parts.append(prompt_hint.strip())
    if isinstance(question, dict) and question_format == "json":
        parts.append("\n请回答以下问题：")
        parts.append(json.dumps(question, ensure_ascii=False, indent=2))
    else:
        parts.append(f"\n## 我的问题\n{question}")
    return "\n\n".join(parts)


def _get_search_instruction(question, agent_key):
    """根据任务类型和平台生成搜索指令（策略来自平台配置 search_strategies）"""
    if not isinstance(question, dict):
        return None
    task = question.get("task", "")
    if not task:
        return None
    config = load_agents().get(agent_key, {})
    return config.get("search_strategies", {}).get(task)



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


# ========== 五阶段讨论（所有平台统一）==========

DISCUSSION_STAGES = {
    1: {
        "name": "发散",
        "template": "请给出 2-3 个候选方案，每个方案说明：核心思路、优劣势、适用场景。不要写代码。"
    },
    2: {
        "name": "风险与验证",
        "template": "【风险与验证】对每个方案做压力测试：1）最大风险点是什么？触发条件？2）在 {project_env} 环境下是否可行？3）失败怎么回滚？输出格式：【方案X】风险=高/中/低，触发条件=...，回滚=..."
    },
    3: {
        "name": "信息缺口",
        "template": "【信息缺口】为了给出最终推荐，还缺哪些关键信息？列出 ≤ 3 个需要确认的问题（如具体版本号、性能指标、用户量等）。"
    },
    4: {
        "name": "MVP",
        "template": "【MVP】综合以上，给出最小可行方案：第一步做什么（1小时内验证方向）、第二步做什么（核心跑通）、第三步做什么（完善）。每个步骤给出完成标准。"
    },
    5: {
        "name": "评估",
        "template": "【评估】对照 MVP，评估当前完成度：已完成、缺失、最大风险、下一步优先级。"
    }
}

# 检查点标记（AI 输出这些标记时触发暂停）
CHECKPOINT_MARKERS = ["【风险与验证】完成", "【MVP】完成"]

# 快速模式跳过阶段（用于简单查询）
FAST_SKIP_STAGES = [2, 3]  # 跳过风险验证和信息缺口


def discuss(question, agent_key="doubao", stages=None, project_env="Android Termux", interactive=False, max_len=0, fast=False):
    """统一讨论入口：所有平台都走五阶段流程
    
    question: 初始问题
    agent_key: 目标 AI
    stages: 要执行的阶段列表，默认 [1,2,3,4,5]
    project_env: 项目环境描述（嵌入到提示词中）
    interactive: 交互模式（检查点暂停）
    max_len: 输出最大字符数（0=不限制）
    fast: 快速模式（跳过阶段 2 和 3）
    """
    if stages is None:
        stages = [1, 2, 3, 4, 5]
    
    # 快速模式：跳过风险验证和信息缺口
    if fast:
        stages = [s for s in stages if s not in FAST_SKIP_STAGES]
        print(f"⚡ 快速模式：跳过阶段 {FAST_SKIP_STAGES}")
    
    if stages is None:
        stages = [1, 2, 3, 4, 5]
    
    # 快速模式：跳过风险验证和信息缺口
    if fast:
        stages = [s for s in stages if s not in FAST_SKIP_STAGES]
        print(f"⚡ 快速模式：跳过阶段 {FAST_SKIP_STAGES}")
    
    results = []
    previous_answer = None
    
    for stage_num in stages:
        stage = DISCUSSION_STAGES[stage_num]
        print(f"\n{'='*50}")
        print(f"📌 阶段 {stage_num}/5: {stage['name']}")
        print(f"{'='*50}")
        
        if stage_num == 1:
            # 首轮：注入完整提示词（平台 system_role + 搜索策略）
            full_question = _build_discuss_prompt(question, agent_key, stage, project_env, previous_answer)
            result = ask(full_question, agent_key, first_round=True)
        else:
            # 后续轮次：只发阶段提示 + 上轮结论引用（不注入 system_role）
            stage_prompt = stage['template'].format(project_env=project_env)
            if previous_answer:
                # 只提取结论段（不是截断全文），帮助 AI 回忆方向
                conclusion = _extract_conclusion(previous_answer, max_len=150)
                stage_prompt = f"上轮结论：{conclusion}\n\n{stage_prompt}"
            result = ask(stage_prompt, agent_key, first_round=False)
        
        if result.get("ok"):
            answer = result.get("answer", "")
            print(f"\n✅ {agent_key} 回答:")
            if max_len > 0:
                print(answer[:max_len] + ("..." if len(answer) > max_len else ""))
            else:
                print(answer)
            previous_answer = answer
            results.append({"stage": stage_num, "name": stage["name"], "answer": previous_answer})
            
            # 交互模式：在检查点暂停（阶段 2 和 4 后）
            if interactive and stage_num in [2, 4] and stage_num != stages[-1]:
                user_input = input(f"\n⏸️ 检查点：按 Enter 继续，输入自定义问题，或 q 退出: ").strip()
                if user_input.lower() == 'q':
                    print("⏹️ 用户终止讨论")
                    break
                elif user_input:
                    # 用户输入了自定义问题，回答后重试当前阶段
                    custom_result = ask(user_input, agent_key, first_round=False)
                    if custom_result.get("ok"):
                        print(f"\n✅ 追问回答:")
                        print(custom_result.get("answer", ""))
                        previous_answer = custom_result.get("answer", "")
        else:
            print(f"\n❌ 阶段 {stage_num} 失败: {result.get('error')}")
            break
    
    return {"ok": True, "stages_completed": len(results), "results": results}


def _build_discuss_prompt(question, agent_key, stage, project_env, previous_answer):
    """构造首轮讨论提示词"""
    agents = load_agents()
    config = agents[agent_key]
    system_role = config.get("system_role", "")
    prompt_hint = config.get("prompt_hint", "")
    
    parts = []
    if system_role:
        parts.append(system_role.strip())
    
    # 搜索策略
    search_instr = _get_search_instruction(question, agent_key)
    if search_instr:
        parts.append(search_instr)
    
    if prompt_hint:
        parts.append(prompt_hint.strip())
    
    # 阶段提示
    stage_prompt = stage['template'].format(project_env=project_env)
    parts.append(f"\n## 当前阶段：{stage['name']}\n{stage_prompt}")
    
    # 用户问题
    if isinstance(question, dict):
        parts.append("\n## 用户问题")
        parts.append(json.dumps(question, ensure_ascii=False, indent=2))
    else:
        parts.append(f"\n## 用户问题\n{question}")
    
    return "\n\n".join(parts)


def _extract_conclusion(answer, max_len=200):
    """提取回答的结论段（通常是最后一段或包含'结论'/'推荐'的部分）"""
    # 尝试找结论标记
    markers = ["结论", "推荐", "最终", "总结", "综上", "因此"]
    for marker in markers:
        idx = answer.rfind(marker)
        if idx != -1 and idx > len(answer) * 0.3:
            # 找到结论标记，取该位置之后的内容
            conclusion = answer[idx:idx+max_len].strip()
            if len(conclusion) > 50:
                return conclusion
    # 没找到结论标记，取最后一段
    paragraphs = answer.split("\n\n")
    if paragraphs:
        last = paragraphs[-1].strip()
        if len(last) <= max_len:
            return last
        return last[:max_len] + "..."
    return answer[:max_len] + "..." if len(answer) > max_len else answer


# ========== 文件上传 ==========

def send_file(file_path, question="请分析这个文件", agent_key="doubao", first_round=True):
    """上传文件 + 发一条消息（便捷函数）

    Args:
        file_path: 本地文件路径
        question: 伴随消息（默认"请分析这个文件"）
        agent_key: 目标 AI
        first_round: 是否首轮对话

    Returns:
        dict: ask() 的返回结果
    """
    return ask(question, agent_key, first_round=first_round, file_path=file_path)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="AI 问答客户端（通用引擎）",
        epilog="新增平台只需在 agents/<key>/ 加配置目录，无需改代码"
    )
    subparsers = parser.add_subparsers(dest="command")
    
    # === ask 子命令（单轮问答，默认）===
    ask_parser = subparsers.add_parser("ask", help="单轮问答")
    ask_parser.add_argument("question", nargs="?", help="要提问的问题（或 JSON 字符串）")
    ask_parser.add_argument("--agent", "-a", default="doubao", help="目标 AI")
    ask_parser.add_argument("--multi", "-m", action="store_true", help="多 AI 模式")
    ask_parser.add_argument("--continue", "-c", action="store_true", dest="continue_round", help="后续轮次")
    ask_parser.add_argument("--file", "-f", help="上传文件路径（上传后自动发消息）")

    # === send-file 子命令 ===
    send_file_parser = subparsers.add_parser("send-file", help="上传文件到 AI")
    send_file_parser.add_argument("file", help="要上传的文件路径")
    send_file_parser.add_argument("--question", "-q", default="请分析这个文件", help="伴随消息")
    send_file_parser.add_argument("--agent", "-a", default="doubao", help="目标 AI")
    send_file_parser.add_argument("--continue", "-c", action="store_true", dest="continue_round", help="后续轮次")
    
    # === discuss 子命令（五阶段讨论，所有平台统一）===
    discuss_parser = subparsers.add_parser("discuss", help="五阶段深入讨论（所有平台统一）")
    discuss_parser.add_argument("question", nargs="?", help="要讨论的问题")
    discuss_parser.add_argument("--agent", "-a", default="doubao", help="目标 AI")
    discuss_parser.add_argument("--stages", "-s", type=int, nargs="+", default=[1,2,3,4,5], help="要执行的阶段")
    discuss_parser.add_argument("--env", "-e", default="Android Termux XBrowser", help="项目环境描述")
    discuss_parser.add_argument("--interactive", "-i", action="store_true", help="交互模式：检查点暂停")
    discuss_parser.add_argument("--fast", "-f", action="store_true", help="快速模式：跳过风险验证和信息缺口")
    discuss_parser.add_argument("--max-len", type=int, default=0, help="输出最大字符数（0=不限制）")
    
    # === 其他 ===
    open_parser = subparsers.add_parser("open", help="打开 URL")
    open_parser.add_argument("url", help="要打开的 URL")
    subparsers.add_parser("list", help="列出所有平台")
    
    args = parser.parse_args()
    agents = load_agents()
    
    # === 路由 ===
    if args.command == "list":
        print("可用平台：")
        for key, config in agents.items():
            print(f"  {key:12} → {config.get('name', key)} ({config.get('url', '?')[:50]})")
        sys.exit(0)
    
    if args.command == "open":
        tab_id = ensure_on_page(args.url, timeout=30)
        print(f"{'✅' if tab_id else '❌'} {'已打开' if tab_id else '打开失败'}")
        sys.exit(0 if tab_id else 1)
    
    if args.command == "discuss":
        # 五阶段讨论模式（所有平台统一）
        try:
            question = json.loads(args.question)
        except (json.JSONDecodeError, ValueError, TypeError):
            question = args.question
        result = discuss(question, args.agent, args.stages, args.env, args.interactive, args.max_len, args.fast)
        print(f"\n{'='*50}")
        print(f"📊 讨论完成，共完成 {result.get('stages_completed', 0)} 个阶段")
        sys.exit(0)
    
    # === 默认：单轮 ask ===
    question = getattr(args, 'question', None)
    file_path = getattr(args, 'file', None)

    # === send-file 子命令路由 ===
    if args.command == "send-file":
        result = send_file(
            args.file,
            question=args.question,
            agent_key=args.agent,
            first_round=not getattr(args, 'continue_round', False)
        )
        print()
        if result.get("ok"):
            name = agents.get(args.agent, {}).get("name", args.agent)
            print(f"✅ {name} 回答:")
            print(_format_answer(result))
        else:
            print(f"❌ 错误:", result.get("error"))
        sys.exit(0)

    if not question and not file_path:
        parser.print_help()
        sys.exit(1)

    first_round = not getattr(args, 'continue_round', False)
    try:
        question = json.loads(question)
    except (json.JSONDecodeError, ValueError):
        pass

    if getattr(args, 'multi', False):
        results = []
        for key in agents:
            print(f"\n{'='*50}")
            result = ask(question, key, first_round=first_round, file_path=file_path)
            results.append(result)
            if result.get("ok"):
                print(f"\n✅ {agents[key].get('name', key)} 回答:")
                print(_format_answer(result))
            else:
                print(f"\n❌ {agents[key].get('name', key)} 失败: {result.get('error')}")
        print(f"\n{'='*50}")
        print(f"📊 讨论完成，共 {len([r for r in results if r.get('ok')])} 个 AI 回答")
    else:
        result = ask(question, args.agent, first_round=first_round, file_path=file_path)
        print()
        if result.get("ok"):
            name = agents.get(args.agent, {}).get("name", args.agent)
            print(f"✅ {name} 回答:")
            print(_format_answer(result))
        else:
            print(f"❌ 错误:", result.get("error"))
