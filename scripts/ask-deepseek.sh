#!/bin/bash
# ask-deepseek.sh — DeepSeek 问答脚本（桌面版）
# 用法: bash scripts/ask-deepseek.sh "<问题>" [timeout_seconds]
#
# 流程：输入问题 → 点击发送 → 等待回答完成（连续2次字数不变=结束）→ 输出
# 跨平台支持: Windows (Git Bash/WSL) / Linux / macOS

set -euo pipefail

API="http://127.0.0.1:8123/api/browser"
QUESTION="${1:?用法: ask-deepseek.sh \"<问题>\" [timeout]}"
TIMEOUT="${2:-120}"

# 检测 python 命令
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "❌ 未找到 python 命令" >&2
    exit 1
fi

# ── 辅助函数：用 eval 提取最后一个有内容的回答 ──
extract_text() {
    local selector="${1:-.ds-assistant-message-main-content}"
    local min_len="${2:-20}"
    local tab_id="${3:-}"
    
    local code="(function(){
        var els = document.querySelectorAll('${selector}');
        var candidates = Array.from(els).filter(e => e.innerText.trim().length > ${min_len});
        if (candidates.length > 0) return candidates[candidates.length - 1].innerText.trim();
        return '';
    })()"
    
    local payload
    if [ -n "$tab_id" ]; then
        payload=$("$PY" -c "import json; print(json.dumps({'tabId':'$tab_id','action':'eval','timeout':10,'code':'''$code'''}))" 2>/dev/null)
    else
        payload=$("$PY" -c "import json; print(json.dumps({'action':'eval','timeout':10,'code':'''$code'''}))" 2>/dev/null)
    fi
    
    curl -s -X POST "$API/interactive" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        | "$PY" -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('value',''))" 2>/dev/null
}

# ── 1. 获取 Tab ID ──
TAB=$(curl -s "$API/state" | "$PY" -c "
import sys,json
data=json.load(sys.stdin)
for tid,t in data.get('tabs',{}).items():
    if 'deepseek' in t.get('url','').lower():
        print(tid); break
" 2>/dev/null || true)

if [ -z "$TAB" ]; then
    echo "DeepSeek tab 未找到，正在打开..." >&2
    curl -s -X POST "$API/interactive" -H "Content-Type: application/json" \
        -d '{"action":"navigate","url":"https://chat.deepseek.com"}' > /dev/null
    sleep 5
    TAB=$(curl -s "$API/state" | "$PY" -c "
import sys,json
data=json.load(sys.stdin)
for tid,t in data.get('tabs',{}).items():
    if 'deepseek' in t.get('url','').lower():
        print(tid); break
" 2>/dev/null)
fi

if [ -z "$TAB" ]; then
    echo "❌ 无法找到或打开 DeepSeek tab" >&2
    exit 1
fi

# ── 2. 确保是新对话 ──
curl -s -X POST "$API/interactive" -H "Content-Type: application/json" \
    -d "{\"tabId\":\"$TAB\",\"action\":\"navigate\",\"url\":\"https://chat.deepseek.com\"}" > /dev/null
sleep 5

# 等待 textarea 可交互
for i in $(seq 1 6); do
    READY=$(curl -s -X POST "$API/interactive" -H "Content-Type: application/json" \
        -d "{\"tabId\":\"$TAB\",\"action\":\"eval\",\"timeout\":5,\"code\":\"document.querySelector('textarea[placeholder*=\\\"给 DeepSeek 发送消息\\\"]') ? '1' : '0'\"}" \
        | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('result',{}).get('value',''))" 2>/dev/null)
    if [ "$READY" = "1" ]; then break; fi
    sleep 2
done

# ── 3. 输入问题 ──
curl -s -X POST "$API/interactive" -H "Content-Type: application/json" \
    -d "{\"tabId\":\"$TAB\",\"action\":\"type\",\"selector\":\"textarea[placeholder*=\\\"给 DeepSeek 发送消息\\\"]\",\"text\":\"$QUESTION\"}" > /dev/null

# ── 4. 点击发送 ──
curl -s -X POST "$API/interactive" -H "Content-Type: application/json" \
    -d "{\"tabId\":\"$TAB\",\"action\":\"eval\",\"code\":\"(function(){var btns=document.querySelectorAll('div.ds-button--primary.ds-button--filled.ds-button--circle');if(btns.length>0){btns[btns.length-1].click();return 'ok'}return 'not found'})()\"}" > /dev/null

echo "已发送，等待回答..." >&2

# ── 5. 等待回答完成 ──
PREV_LEN=0
STABLE_COUNT=0
ELAPSED=0
POLL_INTERVAL=3

while [ $ELAPSED -lt $TIMEOUT ]; do
    sleep $POLL_INTERVAL
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
    
    TEXT=$(extract_text ".ds-assistant-message-main-content" 20 "$TAB")
    CUR_LEN=${#TEXT}
    
    if [ "$CUR_LEN" -gt 50 ] && [ "$CUR_LEN" -eq "$PREV_LEN" ]; then
        STABLE_COUNT=$((STABLE_COUNT + 1))
        if [ $STABLE_COUNT -ge 2 ]; then
            echo "回答完成（${CUR_LEN} 字, ${ELAPSED}s）" >&2
            echo "$TEXT"
            exit 0
        fi
    else
        STABLE_COUNT=0
    fi
    PREV_LEN=$CUR_LEN
    
    if [ $((ELAPSED % 10)) -eq 0 ]; then
        echo "⏳ 生成中 (${ELAPSED}s, ${CUR_LEN} 字)" >&2
    fi
done

# 超时但返回已有内容
TEXT=$(extract_text ".ds-assistant-message-main-content" 20 "$TAB")
echo "⚠️ 超时但返回已有内容 (${#TEXT} 字)" >&2
echo "$TEXT"
