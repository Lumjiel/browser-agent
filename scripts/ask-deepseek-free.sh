#!/bin/bash
# ask-deepseek-free.sh — DeepSeek 自由讨论（支持 --context 自动扫描本地文档）
# 用法:
#   bash ask-deepseek-free.sh "问题"
#   bash ask-deepseek-free.sh "问题" [goal_file] [timeout] [--file a] [--file b]
#   bash ask-deepseek-free.sh --context "关键词" "问题" [--dir ~/projects] [--file c]

set -euo pipefail

BRIDGE="http://127.0.0.1:8123"
MAX_AUTO_FILES=10
MAX_FILE_SIZE=$((1 * 1024 * 1024))  # 1MB
SCAN_DIRS=("$HOME/projects" "$HOME/tools" "$HOME/.pi/agent/skills")

# === 解析参数 ===
CONTEXT_KEYWORD=""
AUTO_SCAN=false
QUESTION=""
GOAL_FILE="$HOME/projects/active/browser-agent/agents/deepseek/goal.txt"
TIMEOUT="120"
MANUAL_FILES=()

# 先提取 --context 和 --dir
_REMAINING_ARGS=()
while [[ $# -gt 0 ]]; do
    case "${1:-}" in
        --context)
            AUTO_SCAN=true
            CONTEXT_KEYWORD="${2:-}"
            shift 2
            ;;
        --dir)
            SCAN_DIRS+=("${2:-}")
            shift 2
            ;;
        --file)
            MANUAL_FILES+=("${2:-}")
            shift 2
            ;;
        *)
            _REMAINING_ARGS+=("${1:-}")
            shift
            ;;
    esac
done

# 剩余参数: question [goal_file] [timeout]
QUESTION="${_REMAINING_ARGS[0]:-}"
GOAL_FILE="${_REMAINING_ARGS[1]:-$GOAL_FILE}"
TIMEOUT="${_REMAINING_ARGS[2]:-$TIMEOUT}"

if [[ -z "$QUESTION" ]]; then
    echo "用法: bash ask-deepseek-free.sh [--context <关键词>] [--file <path>] [--dir <path>] \"问题\" [goal_file] [timeout]"
    exit 1
fi

# === 自动扫描本地文件 ===
AUTO_FILES=()

if [[ "$AUTO_SCAN" == true ]]; then
    echo "[*] 自动扫描模式，关键词: ${CONTEXT_KEYWORD:-无}"
    
    _candidates=()
    for dir in "${SCAN_DIRS[@]}"; do
        [[ -d "$dir" ]] || continue
        while IFS= read -r -d '' file; do
            _candidates+=("$file")
        done < <(find "$dir" -type f \
            \( -name "README.md" -o -name "*.txt" -o -name "*.json" \
            -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" \
            -o -name "*.gradle" -o -name "*.properties" -o -name "*.md" \) \
            ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/__pycache__/*" \
            ! -name "*.so" ! -name "*.jar" ! -name "*.class" ! -name "*.png" ! -name "*.jpg" \
            ! -name "*.pyc" 2>/dev/null | sort -u)
    done
    
    _filtered=()
    if [[ -n "$CONTEXT_KEYWORD" ]]; then
        _kw_lower="${CONTEXT_KEYWORD,,}"
        for f in "${_candidates[@]}"; do
            _fname=$(basename "$f")
            _fname_lower="${_fname,,}"
            if [[ "$_fname_lower" == *"$_kw_lower"* ]] || [[ "${f,,}" == *"$_kw_lower"* ]]; then
                _filtered+=("$f")
            fi
        done
    else
        _filtered=("${_candidates[@]}")
    fi
    
    # 排序: README 优先
    _sorted=()
    for f in "${_filtered[@]}"; do
        [[ "$(basename "$f")" == "README.md" ]] && _sorted+=("$f")
    done
    for f in "${_filtered[@]}"; do
        [[ "$(basename "$f")" != "README.md" ]] && _sorted+=("$f")
    done
    
    _count=0
    for f in "${_sorted[@]}"; do
        [[ $_count -ge $MAX_AUTO_FILES ]] && break
        _size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)
        if [[ "$_size" -gt 0 ]]; then
            AUTO_FILES+=("$f")
            ((_count++))
        fi
    done
    
    echo "[*] 找到 ${#AUTO_FILES[@]} 个相关文件"
    for f in "${AUTO_FILES[@]}"; do
        _size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)
        echo "    - $(basename "$f") ($_size B) [$f]"
    done
fi

# 合并手动指定 + 自动扫描的文件
ALL_FILES=("${MANUAL_FILES[@]}" "${AUTO_FILES[@]}")

# === 读取目标上下文 ===
CONTEXT=""
if [[ -f "$GOAL_FILE" ]]; then
    CONTEXT="## 当前讨论目标(只读参考)\n$(cat "$GOAL_FILE")\n\n---\n\n"
fi
MESSAGE="${CONTEXT}${QUESTION}"

# ============ 主流程（单 Python 块完成） ============
echo "========== DeepSeek 自由讨论 =========="

export DS_TIMEOUT="$TIMEOUT"
export DS_MESSAGE="$MESSAGE"
export DS_BRIDGE="$BRIDGE"
export DS_HOME="$HOME"
export DS_MAX_FILE_SIZE="$MAX_FILE_SIZE"

if [[ ${#ALL_FILES[@]} -gt 0 ]]; then
    export DS_UPLOADS="$(printf '%s\n' "${ALL_FILES[@]}")"
else
    export DS_UPLOADS=""
fi

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

# === 1. 检查桥接 + 连接 ===
if req("/api/health", method="GET").get("status") != "ok":
    print("[*] 桥接未运行，启动中...", file=sys.stderr)
    subprocess.run(["bash", f"{HOME}/projects/active/browser-agent/start-bridge.sh",
                   "start"], capture_output=True)
    time.sleep(3)
    if req("/api/health", method="GET").get("status") != "ok":
        print("[!] 桥接启动失败", file=sys.stderr)
        exit(1)

clients = req("/api/clients", method="GET").get("count", 0)
if clients == 0:
    print("[!] 无浏览器客户端连接", file=sys.stderr)
    exit(1)
print(f"[✓] 桥接正常，{clients} 个客户端", file=sys.stderr)

# === 2. 获取 tab，复用同一会话 ===
tid = tab_id()
if not tid:
    post("/api/browser/ensure", {"url": "https://chat.deepseek.com", "timeout": 15})
    time.sleep(8)
    tid = tab_id()
    if not tid:
        print("[!] 无法打开 DeepSeek", file=sys.stderr)
        exit(1)

# === 3. 文件上传（支持多文件 + 大文件截断） ===
if UPLOAD_FILES:
    files_data = []
    for fpath in UPLOAD_FILES:
        if not os.path.isfile(fpath):
            print(f"[!] 文件不存在: {fpath}", file=sys.stderr)
            continue
        size = os.path.getsize(fpath)
        if size > MAX_FILE_SIZE:
            print(f"[!] 截断超大文件: {fpath} ({size}B > {MAX_FILE_SIZE}B)", file=sys.stderr)
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

# === 4. 发送 + 等待回答 ===
print(f"[*] 发送问题 (timeout: {TIMEOUT}s)...", file=sys.stderr)
print("==========================================")

post("/api/browser/interactive", {"tabId": tid, "action": "type",
    "selector": 'textarea[placeholder*="给 DeepSeek 发送消息"]', "text": MESSAGE})
post("/api/browser/interactive", {"tabId": tid, "action": "click",
    "selector": "div.ds-button--primary.ds-button--filled.ds-button--circle"})

# 发送前：记录当前消息数量（验证新回答已渲染）
COUNT_JS = """(function(){
    var c=document.querySelector('.ds-virtual-list-visible-items');
    return c?c.children.length:0;
})()"""
r = post("/api/browser/interactive", {"tabId": tid, "action": "eval", "code": COUNT_JS})
old_count = r.get("result", {}).get("value", 0) if "result" in r else 0
print(f"[*] 当前消息数: {old_count}", file=sys.stderr)

# 提取器：取最后一条消息的完整内容（思考+回答）
ANS_JS = """(function(){
    var c=document.querySelector('.ds-virtual-list-visible-items');
    if(!c)return '';
    var last=c.lastElementChild;
    // 确保是 AI 回答（含思考或最终回答），不是用户消息
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

# 超时
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
