#!/usr/bin/env bash
# browser_cli.sh — Browser Agent CLI (Python Server Edition)
#
# Control a remote browser via the Python shizuku_bridge server.
#
# Usage:
#   browser_cli.sh <command> [args...]
#
# Environment:
#   BRIDGE_URL   Server URL (default: http://127.0.0.1:8123)
#   BRIDGE_TAB   Default tab ID (auto-detected if omitted)

set -euo pipefail

API="${BRIDGE_URL:-http://127.0.0.1:8123}"
DEFAULT_TAB="${BRIDGE_TAB:-}"
TIMEOUT=30

# ── Helpers ──

# Synchronous command: POST to /api/browser/interactive, block for result
interactive() {
  local tab_id="${1:-}"
  local command_json="$2"
  local timeout="${3:-$TIMEOUT}"

  local body
  if [ -n "$tab_id" ]; then
    body=$(jq -nc --arg tid "$tab_id" --argjson cmd "$command_json" \
      '{tabId: $tid, action: ($cmd.action), ($cmd | del(.action)) | to_entries | reduce .[] as $item ({}; .[$item.key] = $item.value)}')
    # Simpler approach: merge tabId into command
    body=$(echo "$command_json" | jq --arg tid "$tab_id" '. + {tabId: $tid}')
  else
    body="$command_json"
  fi

  local resp
  resp=$(curl -s -m "$((timeout + 5))" -X POST "$API/api/browser/interactive" \
    -H "Content-Type: application/json" \
    -d "$body")

  local ok
  ok=$(echo "$resp" | jq -r '.ok // false')
  if [ "$ok" = "true" ]; then
    echo "$resp" | jq -r '.result // .'
  else
    local err
    err=$(echo "$resp" | jq -r '.error // "Unknown error"')
    echo "ERROR: $err" >&2
    echo "$resp" | jq '.' 2>/dev/null || echo "$resp"
    return 1
  fi
}

# ── Commands ──

cmd="${1:-help}"
shift || true

case "$cmd" in

  tabs)
    curl -s "$API/api/browser/state" | jq '.tabs | to_entries | map({id: .key, url: .value.url, updated_at: .value.updated_at})'
    ;;

  state)
    interactive "${1:-$DEFAULT_TAB}" '{"action":"getState"}'
    ;;

  text)
    local_tab="${1:-$DEFAULT_TAB}"
    local_max="${2:-5000}"
    interactive "$local_tab" "$(jq -nc --argjson m "$local_max" '{action:"getBodyText", maxLen:$m}')"
    ;;

  click)
    local_target="${1:?text or selector required}"
    shift
    local_tab="$DEFAULT_TAB"
    local_nth=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --nth) local_nth="${2:?--nth requires a number}"; shift 2 ;;
        *) if [ -z "$local_tab" ] || [ "$local_tab" = "$DEFAULT_TAB" ]; then local_tab="$1"; fi; shift ;;
      esac
    done
    if [[ "$local_target" =~ ^[.#\[] ]]; then
      if [ -n "$local_nth" ]; then
        interactive "$local_tab" "$(jq -nc --arg s "$local_target" --argjson n "$local_nth" '{action:"click", selector:$s, nth:$n}')"
      else
        interactive "$local_tab" "$(jq -nc --arg s "$local_target" '{action:"click", selector:$s}')"
      fi
    else
      if [ -n "$local_nth" ]; then
        interactive "$local_tab" "$(jq -nc --arg t "$local_target" --argjson n "$local_nth" '{action:"click", text:$t, nth:$n}')"
      else
        interactive "$local_tab" "$(jq -nc --arg t "$local_target" '{action:"click", text:$t}')"
      fi
    fi
    ;;

  click-any|ca)
    local_text="${1:?text required}"
    shift
    local_tab="$DEFAULT_TAB"
    local_nth=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --nth) local_nth="${2:?--nth requires a number}"; shift 2 ;;
        *) if [ -z "$local_tab" ] || [ "$local_tab" = "$DEFAULT_TAB" ]; then local_tab="$1"; fi; shift ;;
      esac
    done
    if [ -n "$local_nth" ]; then
      interactive "$local_tab" "$(jq -nc --arg t "$local_text" --argjson n "$local_nth" '{action:"clickAny", text:$t, nth:$n}')"
    else
      interactive "$local_tab" "$(jq -nc --arg t "$local_text" '{action:"clickAny", text:$t}')"
    fi
    ;;

  navigate|nav|goto)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --arg u "${1:?url required}" '{action:"navigate", url:$u}')"
    ;;

  eval|js)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --arg c "${1:?code required}" '{action:"eval", code:$c}')"
    ;;

  query|qs)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" '{action:"querySelector", selector:$s}')"
    ;;

  read)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" '{action:"read", selector:$s}')"
    ;;

  set-input|input)
    interactive "${3:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" --arg v "${2:?value required}" '{action:"setInput", selector:$s, value:$v}')"
    ;;

  type)
    interactive "${3:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" --arg t "${2:?text required}" '{action:"type", selector:$s, text:$t}')"
    ;;

  fill)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --argjson f "${1:?json required}" '{action:"fillForm", fields:$f}')"
    ;;

  select)
    interactive "${3:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" --arg v "${2:?value required}" '{action:"selectOption", selector:$s, value:$v}')"
    ;;

  wait-for|wf)
    local_timeout="${2:-10000}"
    interactive "${3:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" --argjson t "$local_timeout" '{action:"waitForSelector", selector:$s, timeout:$t}')" "$(( (local_timeout / 1000) + 5 ))"
    ;;

  wait-text|wt)
    local_timeout2="${2:-10000}"
    interactive "${3:-$DEFAULT_TAB}" "$(jq -nc --arg t "${1:?text required}" --argjson to "$local_timeout2" '{action:"waitForText", text:$t, timeout:$to}')" "$(( (local_timeout2 / 1000) + 5 ))"
    ;;

  wait-render|wr)
    local_minlen="${1:-50}"
    local_timeout="${2:-15000}"
    local_tab="${3:-$DEFAULT_TAB}"
    interactive "$local_tab" "$(jq -nc --argjson m "$local_minlen" --argjson t "$local_timeout" '{action:"waitForRender", minLength:$m, timeout:$t}')" "$(( (local_timeout / 1000) + 5 ))"
    ;;

  assert-text|at)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --arg t "${1:?text required}" '{action:"assertText", text:$t}')"
    ;;

  assert)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --arg s "${1:?selector required}" '{action:"assertSelector", selector:$s}')"
    ;;

  console)
    interactive "${2:-$DEFAULT_TAB}" "$(jq -nc --argjson n "${1:-50}" '{action:"getConsoleLog", count:$n}')"
    ;;

  ping)
    interactive "${1:-$DEFAULT_TAB}" '{"action":"ping"}'
    ;;

  health|h)
    curl -s "$API/api/health" | jq '.'
    ;;

  results)
    curl -s "$API/api/browser/results" | jq '.'
    ;;

  logs)
    curl -s "$API/api/browser/logs" | jq '.'
    ;;

  help|--help|-h)
    cat <<'EOF'
Browser Agent CLI — Commands:
  tabs                          List active browser tabs
  state [tabId]                 Full page state (buttons, inputs, text)
  text [tabId] [maxLen]         Get body text
  click <"text"|selector> [tabId]  Click a button/link
  click-any <"text"> [tabId]    Click any element with matching text
  navigate <url> [tabId]        Navigate to URL
  eval <code> [tabId]           Execute JS in page
  query <selector> [tabId]      querySelector
  read <selector> [tabId]       Read element text
  set-input <selector> <value> [tabId]  Set input value
  type <selector> <text> [tabId]  Type text
  fill <json> [tabId]           Fill form: {"#id": "value", ...}
  select <selector> <value> [tabId]  Select dropdown option
  wait-for <selector> [timeout] [tabId]  Wait for element
  wait-text <text> [timeout] [tabId]  Wait for text
  wait-render [minLen] [timeout] [tabId]  Wait for SPA render
  assert-text <text> [tabId]    Assert text exists
  assert <selector> [tabId]     Assert element exists
  console [count] [tabId]       Get console logs
  ping [tabId]                  Ping browser agent
  health                        Server health check
  results                      Get recent execution results
  logs                          Get recent logs

Flags:
  --nth N                       Click the Nth match (for duplicate text)

Environment:
  BRIDGE_URL   Server URL (default: http://127.0.0.1:8123)
  BRIDGE_TAB   Default tab ID (auto-detected if omitted)
EOF
    ;;

  *)
    echo "Unknown command: $cmd. Run '$0 help' for usage." >&2
    exit 1
    ;;
esac
