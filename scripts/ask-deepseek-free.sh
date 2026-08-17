#!/bin/bash
# ask-deepseek-free.sh — DeepSeek 自由讨论调度器 v3.1.1
# 调用链: 本脚本 → bridge API → 油猴脚本 → DeepSeek
#
# 用法:
#   bash ask-deepseek-free.sh "<问题>"
#   bash ask-deepseek-free.sh "<问题>" [goal_file] [timeout]
#   bash ask-deepseek-free.sh "<问题>" --file a --file b
#   bash ask-deepseek-free.sh --context "关键词" "<问题>"
#   bash ask-deepseek-free.sh --round 2 "<问题>"
#   bash ask-deepseek-free.sh --goal "新目标"
#   bash ask-deepseek-free.sh --dead "方向"
#   bash ask-deepseek-free.sh --free "<问题>"

set -euo pipefail

BRIDGE="http://127.0.0.1:8123"
MAX_AUTO_FILES=10
MAX_FILE_SIZE=$((1 * 1024 * 1024))
SCAN_DIRS=("$HOME/projects" "$HOME/tools" "$HOME/.agents/skills")

AGENT_DIR="$HOME/projects/active/browser-agent/agents/deepseek"
GOAL_FILE="$AGENT_DIR/goal.txt"
DEAD_FILE="$AGENT_DIR/dead_ends.txt"
FACTS_FILE="$AGENT_DIR/facts.txt"

CONTEXT_KEYWORD=""
AUTO_SCAN=false
QUESTION=""
TIMEOUT="120"
MANUAL_FILES=()
ROUND=1
FREE_MODE=false
NEW_GOAL=""
NEW_DEAD=""

_REMAINING_ARGS=()
while [[ $# -gt 0 ]]; do
    case "${1:-}" in
        --context) AUTO_SCAN=true; CONTEXT_KEYWORD="${2:-}"; shift 2 ;;
        --dir) SCAN_DIRS+=("${2:-}"); shift 2 ;;
        --file) MANUAL_FILES+=("${2:-}"); shift 2 ;;
        --round) ROUND="${2:-}"; shift 2 ;;
        --goal) NEW_GOAL="${2:-}"; shift 2 ;;
        --dead) NEW_DEAD="${2:-}"; shift 2 ;;
        --free) FREE_MODE=true; shift ;;
        *) _REMAINING_ARGS+=("${1:-}"); shift ;;
    esac
done

QUESTION="${_REMAINING_ARGS[0]:-}"
TIMEOUT="${_REMAINING_ARGS[1]:-$TIMEOUT}"

if [[ -n "$NEW_GOAL" ]]; then
    mkdir -p "$AGENT_DIR"
    cat > "$GOAL_FILE" << GOALEOF
# goal.txt — 只读目标区
goal: "$NEW_GOAL"
constraints:
  - "保持跨平台兼容"
GOALEOF
    echo "[✓] 目标已更新: $NEW_GOAL"
    [[ -z "$QUESTION" ]] && exit 0
fi

if [[ -n "$NEW_DEAD" ]]; then
    mkdir -p "$AGENT_DIR"
    echo "$(date +%Y-%m-%d): \"$NEW_DEAD\" — 被否决" >> "$DEAD_FILE"
    echo "[✓] 死路已注册: $NEW_DEAD"
    [[ -z "$QUESTION" ]] && exit 0
fi

if [[ -z "$QUESTION" ]]; then
    echo "用法: bash ask-deepseek-free.sh [--context <关键词>] [--file <path>] [--round N] [--goal <目标>] [--dead <方向>] [--free] \"问题\" [timeout]"
    exit 1
fi

AUTO_FILES=()
if [[ "$AUTO_SCAN" == true ]]; then
    echo "[*] 自动扫描模式，关键词: ${CONTEXT_KEYWORD:-无}"
    _candidates=()
    for dir in "${SCAN_DIRS[@]}"; do
        [[ -d "$dir" ]] || continue
        while IFS= read -r -d '' file; do
            _candidates+=("$file")
        done < <(find "$dir" -type f \( -name "README.md" -o -name "*.txt" -o -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.gradle" -o -name "*.properties" -o -name "*.md" \) ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/__pycache__/*" ! -name "*.so" ! -name "*.jar" ! -name "*.class" ! -name "*.png" ! -name "*.jpg" ! -name "*.pyc" 2>/dev/null | sort -u)
    done
    _filtered=()
    if [[ -n "$CONTEXT_KEYWORD" ]]; then
        _kw_lower="${CONTEXT_KEYWORD,,}"
        for f in "${_candidates[@]}"; do
            _fname=$(basename "$f")
            _fname_lower="${_fname,,}"
            [[ "$_fname_lower" == *"$_kw_lower"* || "${f,,}" == *"$_kw_lower"* ]] && _filtered+=("$f")
        done
    else
        _filtered=("${_candidates[@]}")
    fi
    _sorted=()
    for f in "${_filtered[@]}"; do [[ "$(basename "$f")" == "README.md" ]] && _sorted+=("$f"); done
    for f in "${_filtered[@]}"; do [[ "$(basename "$f")" != "README.md" ]] && _sorted+=("$f"); done
    _count=0
    for f in "${_sorted[@]}"; do
        [[ $_count -ge $MAX_AUTO_FILES ]] && break
        _size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)
        [[ "$_size" -gt 0 ]] && AUTO_FILES+=("$f") && ((_count++))
    done
    echo "[*] 找到 ${#AUTO_FILES[@]} 个相关文件"
fi

ALL_FILES=("${MANUAL_FILES[@]}" "${AUTO_FILES[@]}")

CONTEXT=""
if [[ "$FREE_MODE" == false ]] && [[ -f "$GOAL_FILE" ]]; then
    GOAL_CONTENT=$(cat "$GOAL_FILE")
    CONTEXT="## 当前讨论目标（只读参考）\n${GOAL_CONTENT}\n\n---\n\n"
fi

if [[ -f "$DEAD_FILE" ]]; then
    DEAD_LINES=$(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}:' "$DEAD_FILE" | tail -10)
    if [[ -n "$DEAD_LINES" ]]; then
        CONTEXT="${CONTEXT}## 已排除方向（不要再建议）\n"
        while IFS= read -r line; do CONTEXT="${CONTEXT}${line}\n"; done <<< "$DEAD_LINES"
        CONTEXT="${CONTEXT}\n---\n\n"
    fi
fi

if [[ "$ROUND" -eq 1 ]] && [[ -f "$FACTS_FILE" ]]; then
    FACTS_CONTENT=$(cat "$FACTS_FILE")
    CONTEXT="${CONTEXT}## 本地环境事实（减少幻觉）\n${FACTS_CONTENT}\n\n---\n\n"
fi

MESSAGE="${CONTEXT}${QUESTION}"

echo "========== DeepSeek 自由讨论 =========="
echo "轮次: $ROUND | 超时: ${TIMEOUT}s | 文件: ${#ALL_FILES[@]}"
echo "=========================================="

export DS_TIMEOUT="$TIMEOUT"
export DS_MESSAGE="$MESSAGE"
export DS_BRIDGE="$BRIDGE"
export DS_HOME="$HOME"
export DS_MAX_FILE_SIZE="$MAX_FILE_SIZE"

[[ ${#ALL_FILES[@]} -gt 0 ]] && export DS_UPLOADS="$(printf '%s\n' "${ALL_FILES[@]}")" || export DS_UPLOADS=""

python3 << 'PYEOF'
import json, time, urllib.request, base64, os, sys, subprocess

BRIDGE = os.environ["DS_BRIDGE"]
TIMEOUT = int(os.environ.get("DS_TIMEOUT", "120"))
MESSAGE = os.environ.get("DS_MESSAGE", "")
UPLOAD_FILES = [f for f in os.environ.get("DS_UPLOADS", "").split("\n") if f.strip()]
HOME = os.environ.get("DS_HOME", os.path.expanduser("~"))
MAX_FILE_SIZE = int(os.environ.get("DS_MAX_FILE_SIZE", str(1024*1024)))

def req(path, payload=None, method="POST", timeout=10):
    if method == "GET":
        req = urllib.request.Request(f"{BRIDGE}{path}")
    else:
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(f"{BRIDGE}{path}", data=data,
                                    headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception:
        return {}

def post(path, payload=None, timeout=10):
    return req(path, payload, "POST", timeout)

def tab_id():
    for tid, info in req("/api/browser/state", method="GET").get("tabs", {}).items():
        if "deepseek" in info.get("url", "").lower():
            return tid
    return None

# === 1. 检查桥接 + 启动 ===
if req("/api/health", method="GET").get("status") != "ok":
    print("[*] 桥接未运行，启动中...", file=sys.stderr)
    bridge_dir = os.path.join(HOME, "projects", "active", "browser-agent")
    if not os.path.isdir(bridge_dir):
        bridge_dir = os.path.dirname(os.path.abspath(__file__))
    bridge_script = os.path.join(bridge_dir, "server", "shizuku_bridge.py")
    if os.path.isfile(bridge_script):
        subprocess.Popen(
            [sys.executable, bridge_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=bridge_dir
        )
        time.sleep(3)
    if req("/api/health", method="GET").get("status") != "ok":
        print("[!] 桥接启动失败", file=sys.stderr)
        exit(1)

tabs = req("/api/browser/state", method="GET").get("tabs", {})
if len(tabs) == 0:
    print("[!] 无浏览器客户端连接（需要 Chrome + 油猴脚本打开网页）", file=sys.stderr)
    exit(1)
print(f"[✓] 桥接正常，{len(tabs)} 个浏览器 tab", file=sys.stderr)

# === 2. 获取 tab ===
tid = tab_id()
if not tid:
    post("/api/browser/ensure", {"url": "https://chat.deepseek.com", "timeout": 15})
    time.sleep(8)
    tid = tab_id()
    if not tid:
        print("[!] 无法打开 DeepSeek", file=sys.stderr)
        exit(1)

# === 3. 文件上传 ===
if UPLOAD_FILES:
    files_data = []
    for fpath in UPLOAD_FILES:
        if not os.path.isfile(fpath):
            print(f"[!] 文件不存在: {fpath}", file=sys.stderr)
            continue
        size = os.path.getsize(fpath)
        if size > MAX_FILE_SIZE:
            with open(fpath, "rb") as f:
                content = f.read(MAX_FILE_SIZE)
            b64 = base64.b64encode(content).decode()
            name = os.path.basename(fpath) + " [截断]"
        else:
            b64 = base64.b64encode(open(fpath, "rb").read()).decode()
            name = os.path.basename(fpath)
        files_data.append({"name": name, "b64": b64})
        print(f"[*] 上传: {name}", file=sys.stderr)
    if files_data:
        files_json = json.dumps(files_data)
        js = f"""(function(){{
            var files = {files_json};
            var dt = new DataTransfer();
            for (var i = 0; i < files.length; i++) {{
                var b = atob(files[i].b64);
                var u = new Uint8Array(b.length);
                for (var j = 0; j < b.length; j++) u[j] = b.charCodeAt(j);
                dt.items.add(new File([u], files[i].name));
            }}
            var x = document.querySelector('div.bf38813a > input[type=file]');
            if (!x) return 'no';
            x.files = dt.files;
            x.dispatchEvent(new Event('change', {{bubbles: true}}));
            x.dispatchEvent(new Event('input', {{bubbles: true}}));
            return 'ok';
        }})()"""
        post("/api/browser/command", {"action": "eval", "tabId": tid, "code": js})
        time.sleep(3)

# === 4. 输入问题 + 点击发送 ===
print(f"[*] 发送问题 (timeout: {TIMEOUT}s)...", file=sys.stderr)
print("==========================================")

# 输入框
INPUT_JS = '''document.querySelector('textarea[placeholder*="给 DeepSeek 发送消息"]')'''
post("/api/browser/interactive", {"tabId": tid, "action": "eval",
    "code": f"var el={INPUT_JS}; if(el){{el.focus(); el.value=''; el.dispatchEvent(new Event('input',{{bubbles:true}})); 'ok'}} else {{'no'}}"})

# 输入文字
post("/api/browser/interactive", {"tabId": tid, "action": "type",
    "selector": 'textarea[placeholder*="给 DeepSeek 发送消息"]', "text": MESSAGE})

# 点击发送（最后一个 primary circle 按钮）
post("/api/browser/interactive", {"tabId": tid, "action": "eval",
    "code": """(function(){
        var btns = document.querySelectorAll('div.ds-button--primary.ds-button--filled.ds-button--circle');
        if (btns.length > 0) {
            btns[btns.length - 1].click();
            return 'clicked send button';
        }
        return 'send button not found';
    })()"""})

# === 5. 等待回答完成 ===
ANS_JS = """(function(){
    var c=document.querySelector('.ds-virtual-list-visible-items');
    if(!c)return '';
    var last=c.lastElementChild;
    if(!last.querySelector('.ds-think-content') && !last.querySelector('.ds-assistant-message-main-content'))
        return '';
    var msg=last.querySelector('.ds-message');
    return msg?msg.innerText.trim():last.innerText.trim();
})()"""
prev, stable, elapsed = 0, 0, 0
while elapsed < TIMEOUT:
    time.sleep(3)
    elapsed += 3
    r = post("/api/browser/interactive", {"tabId": tid, "action": "eval", "code": ANS_JS})
    text = r.get("result", {}).get("value", "") if "result" in r else ""
    cur = len(text)
    if cur > 0 and cur == prev:
        stable += 1
        if stable >= 2:
            print(f"回答完成（{cur}字, {elapsed}s）", file=sys.stderr)
            print(text)
            exit(0)
    else:
        stable = 0
    prev = cur
    if elapsed % 15 == 0:
        print(f"⏳ 生成中 ({elapsed}s, {cur}字)", file=sys.stderr)

if prev > 0:
    r = post("/api/browser/interactive", {"tabId": tid, "action": "eval", "code": ANS_JS})
    text = r.get("result", {}).get("value", "") if "result" in r else ""
    print(f"⚠️ 超时但有内容 ({len(text)}字)", file=sys.stderr)
    print(text)
else:
    print("⚠️ 超时无内容", file=sys.stderr)
    exit(1)

print("==========================================")
print("[✓] 完成。")
PYEOF
