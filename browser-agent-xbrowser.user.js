// ==UserScript==
// @name         Browser Agent (XBrowser 适配版)
// @namespace    https://github.com/npezarro/claude-browser-agent
// @version      2.1.0
// @description  通用浏览器代理 - 轮询获取命令，执行 DOM 操作。适配 XBrowser（用 fetch 替代 GM_xmlhttpRequest）。v2.1: 自动发现桥接服务 + 交互元素编号 @eN + 错误恢复 + 可视化面板
// @author       npezarro (adapted for XBrowser)
// @match        *://*/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // Skip iframes
  if (window.self !== window.top) return;

  // ── Configuration ──
  // API_BASE 不再固定：启动时通过候选列表自动发现（localStorage 记录 → localhost → 127.0.0.1 → RTC 局域网 IP → 手动输入）
  let API_BASE = null;             // 生效地址: http://host:8123/api/browser
  let apiRoot = null;              // http://host:8123
  const BRIDGE_PORT = 8123;
  const API_DISCOVER_KEY = "_browserAgentApiBase";
  const VERSION = "2.1.0";
  const POLL_MS = 2000;
  const DISCOVER_TIMEOUT_MS = 2500;
  const MAX_CONSECUTIVE_ERRORS = 5;
  const RECONNECT_MS = 3000;

  // Per-tab session ID（localStorage 保证页面跳转后 tabId 不变）
  const STORAGE_KEY = "_browserAgentTabId";
  const stored = localStorage.getItem(STORAGE_KEY);
  const tabId = stored || `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  if (!stored) localStorage.setItem(STORAGE_KEY, tabId);

  // ── Console log capture ──
  const MAX_CONSOLE = 100;
  const consoleLogs = new Array(MAX_CONSOLE);
  let consoleHead = 0;
  let consoleCount = 0;
  const origLog = console.log;
  const origWarn = console.warn;
  const origError = console.error;

  function captureConsole(level, args) {
    const msg = args.map((a) => typeof a === "object" ? JSON.stringify(a).substring(0, 300) : String(a)).join(" ");
    consoleLogs[consoleHead] = { level, msg, ts: Date.now() };
    consoleHead = (consoleHead + 1) % MAX_CONSOLE;
    if (consoleCount < MAX_CONSOLE) consoleCount++;
  }

  function getConsoleLogs(count) {
    count = Math.min(count || 50, consoleCount);
    const result = [];
    let idx = (consoleHead - count + MAX_CONSOLE) % MAX_CONSOLE;
    for (let i = 0; i < count; i++) {
      result.push(consoleLogs[idx]);
      idx = (idx + 1) % MAX_CONSOLE;
    }
    return result;
  }

  console.log = function (...args) { origLog.apply(console, args); captureConsole("log", args); };
  console.warn = function (...args) { origWarn.apply(console, args); captureConsole("warn", args); };
  console.error = function (...args) { origError.apply(console, args); captureConsole("error", args); };

  window.addEventListener("error", (e) => {
    captureConsole("error", [`${e.message} at ${e.filename}:${e.lineno}`]);
  });

  // ── 可视化面板 + 自动发现（借鉴 hermes-browser-bridge）──

  let panel = null;
  let consecutiveErrors = 0;

  function dbg(msg) {
    const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
    origLog(`[BrowserAgent] ${msg}`);
    if (!panel) return;
    const pre = panel.querySelector("pre");
    if (!pre) return;
    let lines = pre.textContent ? pre.textContent.split("\n") : [];
    lines.push(line);
    if (lines.length > 50) lines = lines.slice(-50);
    pre.textContent = lines.join("\n");
    pre.scrollTop = pre.scrollHeight;
  }

  function createPanel() {
    if (document.getElementById("browser-agent-panel")) return;
    const d = document.createElement("div");
    d.id = "browser-agent-panel";
    d.style.cssText = "position:fixed;bottom:8px;right:8px;z-index:2147483647;width:320px;max-height:220px;background:#111;border:1px solid #333;border-radius:6px;color:#eee;font-family:monospace;font-size:11px;overflow:hidden;display:flex;flex-direction:column;";
    d.innerHTML =
      '<div id="ba-header" style="padding:4px 8px;background:#222;display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none;">' +
      `  <span>BrowserAgent v${VERSION}</span>` +
      '  <span id="ba-status" style="color:#fa0;">init...</span>' +
      "</div>" +
      '<pre id="ba-log" style="margin:0;padding:4px 8px;overflow-y:auto;flex:1;white-space:pre-wrap;word-break:break-word;font-size:10px;color:#aaa;"></pre>';
    (document.body || document.documentElement).appendChild(d);
    panel = d;
    // 点击标题栏折叠/展开日志
    d.querySelector("#ba-header").addEventListener("click", function () {
      const pre = d.querySelector("#ba-log");
      pre.style.display = pre.style.display === "none" ? "block" : "none";
    });
  }

  function setStatus(txt, color) {
    const s = document.getElementById("ba-status");
    if (s) { s.textContent = txt; s.style.color = color || "#888"; }
  }

  function showManualInput(attempted) {
    createPanel();
    if (document.getElementById("ba-manual-input")) return;
    const div = document.createElement("div");
    div.id = "ba-manual-input";
    div.style.cssText = "padding:6px 8px;border-top:1px solid #333;";
    div.innerHTML =
      `<div style="color:#f44;margin-bottom:4px;">无法连接桥接服务，已尝试: ${attempted.slice(0, 3).join(", ")}${attempted.length > 3 ? "..." : ""}</div>` +
      '<div style="display:flex;gap:4px;">' +
      '<input id="ba-ip" placeholder="http://IP:8123" style="flex:1;padding:4px;border-radius:3px;border:1px solid #555;background:#222;color:#0f0;font-family:monospace;">' +
      '<button id="ba-set" style="padding:4px 8px;background:#0a0;color:#fff;border:none;border-radius:3px;cursor:pointer;">连接</button>' +
      "</div>";
    panel.appendChild(div);
    document.getElementById("ba-set").addEventListener("click", function () {
      const val = (document.getElementById("ba-ip").value || "").trim().replace(/\/+$/, "");
      if (!val) return;
      localStorage.setItem(API_DISCOVER_KEY, val);
      dbg("已设置 API: " + val);
      location.reload();
    });
  }

  function isVirtualIP(ip) {
    // VirtualBox host-only / libvirt / VMware NAT / Android tether
    if (/^192\.168\.56\./.test(ip)) return true;
    if (/^192\.168\.122\./.test(ip)) return true;
    if (/^192\.168\.254\./.test(ip)) return true;
    if (/^192\.168\.42\./.test(ip)) return true;
    return false;
  }

  function ipScore(ip) {
    // 越小越优先：0=真实局域网，2=虚拟网段，3=localhost
    if (ip === "127.0.0.1" || ip === "localhost") return 3;
    if (isVirtualIP(ip)) return 2;
    return 0;
  }

  function discoverLocalIPs() {
    // WebRTC 发现本机局域网 IP
    return new Promise(function (resolve) {
      const ips = [];
      try {
        const pc = new RTCPeerConnection({ iceServers: [] });
        if (pc.createDataChannel) pc.createDataChannel("");
        pc.onicecandidate = function (ice) {
          if (!ice || !ice.candidate || !ice.candidate.candidate) { resolve(ips); return; }
          const m = /([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/.exec(ice.candidate.candidate);
          if (m) {
            const ip = m[1];
            if (ip !== "127.0.0.1" && !ip.startsWith("0.0.0.0") && ips.indexOf(ip) === -1) ips.push(ip);
          }
        };
        pc.createOffer().then(function (o) {
          pc.setLocalDescription(o, function () {}, function () {});
        }).catch(function () {});
        setTimeout(function () { resolve(ips); }, 1500);
      } catch (e) { resolve(ips); }
    });
  }

  function buildCandidates() {
    return discoverLocalIPs().then(function (rtcIps) {
      const candidates = [];
      // 1. 上次成功地址（先验证再使用）
      const saved = localStorage.getItem(API_DISCOVER_KEY);
      if (saved) candidates.push(saved);
      // 2. localhost → 127.0.0.1
      candidates.push("http://localhost:" + BRIDGE_PORT);
      candidates.push("http://127.0.0.1:" + BRIDGE_PORT);
      // 3. RTC 局域网 IP（真实局域网优先）
      rtcIps.sort(function (a, b) { return ipScore(a) - ipScore(b); });
      rtcIps.forEach(function (ip) { candidates.push("http://" + ip + ":" + BRIDGE_PORT); });
      // 去重（保持顺序）
      const seen = new Set();
      return candidates.filter(function (c) {
        if (seen.has(c)) return false;
        seen.add(c);
        return true;
      });
    });
  }

  function discoverAPI(callback) {
    buildCandidates().then(function (candidates) {
      if (!candidates.length) { showManualInput([]); callback(null); return; }
      let idx = 0;
      const attempted = [];
      function next() {
        if (idx >= candidates.length) {
          dbg("No API reachable after " + attempted.length + " tries");
          showManualInput(attempted);
          callback(null);
          return;
        }
        const root = candidates[idx++];
        attempted.push(root);
        setStatus("try " + root.replace(/^https?:\/\//, ""), "#fa0");
        // ping 桥接服务健康检查端点验证连通性
        fetchWithTimeout(root + "/api/health", { headers: { "Content-Type": "application/json" } }, DISCOVER_TIMEOUT_MS)
          .then(function (resp) {
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            return resp.json();
          })
          .then(function (d) {
            if (d && d.status === "ok") {
              apiRoot = root;
              API_BASE = root + "/api/browser";
              consecutiveErrors = 0;
              localStorage.setItem(API_DISCOVER_KEY, root);
              setStatus("connected", "#0f0");
              dbg("API OK: " + root);
              callback(API_BASE);
              return;
            }
            next();
          })
          .catch(function () { next(); });
      }
      next();
    });
  }

  function rediscover() {
    API_BASE = null;
    apiRoot = null;
    setTimeout(function () {
      discoverAPI(function (base) {
        if (base) {
          consecutiveErrors = 0;
          log("重连成功: " + base);
        } else {
          setStatus("no API", "#f44");
        }
      });
    }, RECONNECT_MS);
  }

  // ── HTTP helpers (fetch 替代 GM_xmlhttpRequest) ──

  async function apiPost(path, data) {
    if (!API_BASE) return;
    try {
      await fetch(API_BASE + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    } catch (e) {
      // silent fail for logging
    }
  }

  function fetchWithTimeout(url, opts, timeoutMs) {
    // fetch 带超时：网络错误 / 超时 / 非 200 均 reject（供轮询与发现使用）
    return new Promise((resolve, reject) => {
      const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
      let settled = false;
      const timer = setTimeout(() => {
        if (ctrl) ctrl.abort();
        if (!settled) { settled = true; reject(new Error("timeout")); }
      }, timeoutMs || 3000);
      fetch(url, ctrl ? Object.assign({}, opts, { signal: ctrl.signal }) : opts)
        .then((resp) => { if (!settled) { settled = true; clearTimeout(timer); resolve(resp); } })
        .catch((err) => { if (!settled) { settled = true; clearTimeout(timer); reject(err); } });
    });
  }

  async function apiGetRaw(url) {
    const resp = await fetchWithTimeout(url, { headers: { "Content-Type": "application/json" } }, 10000);
    if (resp.status !== 200) throw new Error("HTTP " + resp.status);
    return await resp.json();
  }

  function log(msg) {
    dbg(msg);
    apiPost("/log", { tabId, msg, ts: Date.now() });
  }

  // ── Page introspection ──

  let cachedPageState = null;
  let cachedPageStateAt = 0;
  const PAGE_STATE_TTL = 2000;

  function getPageStateCached() {
    const now = Date.now();
    if (cachedPageState && now - cachedPageStateAt < PAGE_STATE_TTL) return cachedPageState;
    cachedPageState = getPageState();
    cachedPageStateAt = now;
    return cachedPageState;
  }

  function getPageState() {
    const buttons = [];
    const textCount = {};
    for (const el of document.querySelectorAll("button, a[class*='button'], a[class*='btn'], a[role='button'], [role='button'], input[type='submit'], input[type='button']")) {
      const text = (el.innerText || el.value || "").trim().replace(/\s+/g, " ");
      if (!text || text.length > 100) continue;
      textCount[text] = (textCount[text] || 0) + 1;
      buttons.push({
        text,
        nth: textCount[text],
        tag: el.tagName,
        disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
        visible: el.offsetParent !== null,
        classes: (el.className?.toString() || "").substring(0, 120),
        href: el.href || null,
        id: el.id || null,
      });
      if (buttons.length >= 80) break;
    }

    const inputs = [];
    for (const el of document.querySelectorAll("input:not([type='hidden']), select, textarea")) {
      inputs.push({
        tag: el.tagName, type: el.type || "", name: el.name || "",
        value: el.type === "password" ? "***" : (el.value || "").substring(0, 120),
        id: el.id || "", placeholder: el.placeholder || "",
        label: el.labels?.[0]?.innerText?.trim().substring(0, 80) || "",
      });
      if (inputs.length >= 30) break;
    }

    const dialogs = [];
    for (const el of document.querySelectorAll("[role='dialog'], [role='alertdialog'], dialog, [class*='modal']:not([class*='modal-'])")) {
      if (el.offsetParent === null && !el.open) continue;
      dialogs.push({ text: el.innerText?.trim().substring(0, 500).replace(/\s+/g, " ") });
      if (dialogs.length >= 5) break;
    }

    return {
      tabId, url: window.location.href, title: document.title,
      version: VERSION, ts: Date.now(),
      buttons, inputs, dialogs,
      bodyText: (document.body?.innerText || "").substring(0, 3000),
      scrollY: window.scrollY,
      docHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      readyState: document.readyState,
    };
  }

  // ── 交互元素编号（借鉴 hermes: @e1/@e2...）──

  let interactiveMap = new Map();

  function buildInteractiveMap() {
    interactiveMap.clear();
    const sel = 'a, button, input:not([type="hidden"]), textarea, select, [role="button"], [role="link"], [role="tab"], summary, label';
    const els = Array.from(document.querySelectorAll(sel));
    let idx = 1;
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue; // 跳过不可见元素
      interactiveMap.set("@e" + idx++, el);
    }
    return interactiveMap;
  }

  function summarizeElement(el) {
    const r = el.getBoundingClientRect();
    const txt = (el.innerText || el.textContent || el.value || el.placeholder || el.title || el.getAttribute("aria-label") || "").trim();
    return {
      tag: el.tagName,
      type: el.type || null,
      text: txt.slice(0, 300),
      href: el.href || null,
      visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    };
  }

  // ── Command executor ──

  async function execCommand(cmd) {
    const { action, id } = cmd;
    try {
      let result;

      switch (action) {
        case "getState":
          result = getPageState();
          break;

        case "getConsoleLog":
          result = { logs: getConsoleLogs(cmd.count || 50) };
          break;

        case "getBodyText":
          result = { text: (document.body?.innerText || "").substring(0, cmd.maxLen || 5000) };
          break;

        case "querySelector": {
          const el = document.querySelector(cmd.selector);
          result = el ? {
            found: true, tag: el.tagName, text: el.innerText?.trim().substring(0, 300),
            classes: el.className?.toString().substring(0, 120),
            href: el.href || null, value: el.value || null,
            id: el.id || null, visible: el.offsetParent !== null,
          } : { found: false };
          break;
        }

        case "click": {
          let el;
          if (cmd.selector) {
            el = document.querySelector(cmd.selector);
          } else if (cmd.text) {
            const scope = "button, a, input[type='submit'], input[type='button'], [role='button']";
            const lc = cmd.text.toLowerCase();
            let matchNum = 0;
            const targetNth = cmd.nth || 1;
            for (const candidate of document.querySelectorAll(scope)) {
              const t = (candidate.innerText || candidate.value || "").trim().toLowerCase();
              if (t.includes(lc)) {
                matchNum++;
                if (matchNum === targetNth) { el = candidate; break; }
              }
            }
          }
          if (el) {
            el.scrollIntoView({ block: "center" });
            el.click();
            result = { clicked: true, text: (el.innerText || el.value || "").trim().substring(0, 80) };
          } else {
            result = { clicked: false, error: "Element not found" };
          }
          break;
        }

        case "getInteractiveElements": {
          // 扫描 a/button/input/textarea/select/[role=button]...，编号 @e1/@e2...
          buildInteractiveMap();
          const out = [];
          interactiveMap.forEach((el, ref) => {
            const s = summarizeElement(el);
            s.ref = ref;
            out.push(s);
          });
          result = { elements: out, count: out.length };
          break;
        }

        case "clickByRef": {
          // 按编号点击（编号来自 getInteractiveElements 返回的 ref）
          let refEl = interactiveMap.get(cmd.ref);
          if (!refEl) { buildInteractiveMap(); refEl = interactiveMap.get(cmd.ref); }
          if (refEl) {
            refEl.scrollIntoView({ block: "center" });
            refEl.click();
            result = {
              clicked: true, ref: cmd.ref,
              text: (refEl.innerText || refEl.value || refEl.getAttribute("aria-label") || "").trim().substring(0, 80),
            };
          } else {
            result = { clicked: false, error: "ref not found: " + cmd.ref };
          }
          break;
        }

        case "navigate":
          // 先确保结果发送完成，再导航（避免页面跳转丢失结果）
          return apiPost("/result", { tabId, id, ok: true, result: { navigating: true, url: cmd.url } })
            .then(function() { window.location.href = cmd.url; })
            .then(function() { return null; });

        case "setInput": {
          const inputEl = document.querySelector(cmd.selector);
          if (inputEl) {
            inputEl.focus();
            const proto = inputEl.tagName === "TEXTAREA"
              ? window.HTMLTextAreaElement.prototype
              : window.HTMLInputElement.prototype;
            const nativeSet = Object.getOwnPropertyDescriptor(proto, "value")?.set;
            if (nativeSet) nativeSet.call(inputEl, cmd.value);
            else inputEl.value = cmd.value;
            inputEl.dispatchEvent(new Event("input", { bubbles: true }));
            inputEl.dispatchEvent(new Event("change", { bubbles: true }));
            result = { set: true };
          } else {
            result = { set: false, error: "Input not found" };
          }
          break;
        }

        case "type": {
          const typeEl = cmd.selector ? document.querySelector(cmd.selector) : document.activeElement;
          if (typeEl) {
            typeEl.focus();
            const isContentEditable = typeEl.getAttribute("contenteditable") === "true" || typeEl.isContentEditable;
            if (isContentEditable) {
              // contenteditable div handling (千问等)
              typeEl.innerText = "";
              typeEl.dispatchEvent(new Event("input", { bubbles: true }));
              for (const char of cmd.text) {
                typeEl.dispatchEvent(new KeyboardEvent("keydown", { key: char, bubbles: true }));
                typeEl.innerText += char;
                typeEl.dispatchEvent(new Event("input", { bubbles: true }));
                typeEl.dispatchEvent(new KeyboardEvent("keyup", { key: char, bubbles: true }));
                if (cmd.delay) await new Promise((r) => setTimeout(r, cmd.delay));
              }
              typeEl.dispatchEvent(new Event("change", { bubbles: true }));
              result = { typed: true, length: cmd.text.length };
            } else {
              // standard input/textarea handling
              for (const char of cmd.text) {
                typeEl.dispatchEvent(new KeyboardEvent("keydown", { key: char, bubbles: true }));
                const typeProto = typeEl.tagName === "TEXTAREA"
                  ? window.HTMLTextAreaElement.prototype
                  : window.HTMLInputElement.prototype;
                const nSet = Object.getOwnPropertyDescriptor(typeProto, "value")?.set;
                if (nSet) nSet.call(typeEl, typeEl.value + char);
                else typeEl.value += char;
                typeEl.dispatchEvent(new Event("input", { bubbles: true }));
                typeEl.dispatchEvent(new KeyboardEvent("keyup", { key: char, bubbles: true }));
                if (cmd.delay) await new Promise((r) => setTimeout(r, cmd.delay));
              }
              typeEl.dispatchEvent(new Event("change", { bubbles: true }));
              result = { typed: true, length: cmd.text.length };
            }
          } else {
            result = { typed: false, error: "Element not found" };
          }
          break;
        }

        case "scroll":
          if (cmd.selector) {
            const scrollEl = document.querySelector(cmd.selector);
            if (scrollEl) scrollEl.scrollIntoView({ block: cmd.block || "center" });
          } else {
            window.scrollBy(0, cmd.y || 500);
          }
          result = { scrolled: true, scrollY: window.scrollY };
          break;

        case "waitForSelector": {
          const timeout = cmd.timeout || 10000;
          const start = Date.now();
          let found = null;
          while (Date.now() - start < timeout) {
            found = document.querySelector(cmd.selector);
            if (found) break;
            await new Promise((r) => setTimeout(r, 250));
          }
          result = found
            ? { found: true, text: found.innerText?.trim().substring(0, 200), elapsed: Date.now() - start }
            : { found: false, elapsed: Date.now() - start };
          break;
        }

        case "waitForText": {
          const tTimeout = cmd.timeout || 10000;
          const tStart = Date.now();
          const searchText = cmd.text.toLowerCase();
          let textFound = false;
          while (Date.now() - tStart < tTimeout) {
            if ((document.body?.innerText || "").toLowerCase().includes(searchText)) {
              textFound = true;
              break;
            }
            await new Promise((r) => setTimeout(r, 250));
          }
          result = { found: textFound, elapsed: Date.now() - tStart };
          break;
        }

        case "eval": {
          const fn = new Function("document", "window", "return (" + cmd.code + ")");
          const evalResult = await fn(document, window);
          result = { value: String(evalResult).substring(0, cmd.maxLen || 5000) };
          break;
        }

        case "wait":
          await new Promise((r) => setTimeout(r, cmd.ms || 1000));
          result = { waited: cmd.ms || 1000 };
          break;

        case "ping":
          result = { pong: true, url: window.location.href, version: VERSION, tabId };
          break;

        // ── 扩展命令 ──

        case "getHtml": {
          const htmlEl = cmd.selector ? document.querySelector(cmd.selector) : document.body;
          result = { html: (htmlEl?.innerHTML || "").substring(0, cmd.maxLen || 10000) };
          break;
        }

        case "read": {
          const readEl = document.querySelector(cmd.selector);
          result = readEl ? {
            found: true, text: readEl.innerText?.trim().substring(0, cmd.maxLen || 1000),
            value: readEl.value || null,
          } : { found: false };
          break;
        }

        case "readAttr": {
          const attrEl = document.querySelector(cmd.selector);
          result = attrEl ? {
            found: true, value: attrEl.getAttribute(cmd.attr),
          } : { found: false };
          break;
        }

        case "fillForm": {
          const formResults = {};
          for (const [sel, val] of Object.entries(cmd.fields || {})) {
            const field = document.querySelector(sel);
            if (field) {
              field.focus();
              const proto = field.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype
                : field.tagName === "SELECT" ? window.HTMLSelectElement.prototype
                : window.HTMLInputElement.prototype;
              const ns = Object.getOwnPropertyDescriptor(proto, "value")?.set;
              if (ns) ns.call(field, val); else field.value = val;
              field.dispatchEvent(new Event("input", { bubbles: true }));
              field.dispatchEvent(new Event("change", { bubbles: true }));
              formResults[sel] = "set";
            } else {
              formResults[sel] = "not found";
            }
          }
          result = { fields: formResults };
          break;
        }

        case "selectOption": {
          const selectEl = document.querySelector(cmd.selector);
          if (selectEl && selectEl.tagName === "SELECT") {
            selectEl.value = cmd.value;
            selectEl.dispatchEvent(new Event("change", { bubbles: true }));
            result = { selected: true, value: selectEl.value };
          } else {
            result = { selected: false, error: selectEl ? "Not a select" : "Not found" };
          }
          break;
        }

        case "getNetworkErrors":
          result = { errors: getConsoleLogs(consoleCount).filter((l) => l.level === "error").slice(-20) };
          break;

        case "assertText": {
          const bodyText = (document.body?.innerText || "").toLowerCase();
          const searchFor = cmd.text.toLowerCase();
          const found = bodyText.includes(searchFor);
          result = { pass: cmd.negate ? !found : found, text: cmd.text, negate: !!cmd.negate };
          break;
        }

        case "assertSelector": {
          const assertEl = document.querySelector(cmd.selector);
          const exists = !!assertEl;
          result = { pass: cmd.negate ? !exists : exists, selector: cmd.selector, negate: !!cmd.negate };
          break;
        }

        default:
          result = { error: `Unknown action: ${action}` };
      }

      return { id, ok: true, result };
    } catch (err) {
      return { id, ok: false, error: err.message, stack: err.stack?.substring(0, 300) };
    }
  }

  // ── Poll loop（带错误恢复：连续失败 ≥5 次自动重新发现）──

  let polling = false;

  async function poll() {
    if (polling || !API_BASE) return;
    polling = true;

    try {
      const data = await apiGetRaw(
        `${API_BASE}/commands?tabId=${encodeURIComponent(tabId)}&client_id=${encodeURIComponent(tabId)}&url=${encodeURIComponent(window.location.href)}`
      );

      consecutiveErrors = 0;
      setStatus("connected", "#0f0");
      if (data.client_id && data.client_id !== tabId) {
        log("server client_id: " + data.client_id);
      }

      if (data.commands && data.commands.length > 0) {
        for (const cmd of data.commands) {
          log(`Exec: ${cmd.action}${cmd.selector ? ` ${cmd.selector}` : ""}${cmd.text ? ` "${cmd.text}"` : ""}`);
          const cmdTimeout = cmd.timeout || 20000;
          let result;
          try {
            result = await Promise.race([
              execCommand(cmd),
              new Promise((_, reject) =>
                setTimeout(() => reject(new Error("Command timeout")), cmdTimeout)
              ),
            ]);
          } catch (err) {
            result = { id: cmd.id, ok: false, error: err.message };
          }
          if (result) apiPost("/result", { tabId, ...result });

          if (data.commands.length > 1) {
            await new Promise((r) => setTimeout(r, 300));
          }
        }
      }
    } catch (err) {
      consecutiveErrors++;
      setStatus("err " + consecutiveErrors, "#f44");
      if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        log(`连续失败 ${consecutiveErrors} 次，重新发现服务...`);
        rediscover();
      }
    } finally {
      polling = false;
    }
  }

  // ── Init：发现桥接服务 → 注册 → 开始轮询 ──

  function boot() {
    createPanel();
    setStatus("discovering...", "#fa0");
    dbg("v" + VERSION + " loaded on " + window.location.hostname);

    discoverAPI(function (base) {
      if (!base) {
        setStatus("no API", "#f44");
        return;
      }
      log("connected: " + base);
      apiPost("/heartbeat", getPageState());

      let lastUrl = window.location.href;
      function tick() {
        if (window.location.href !== lastUrl) {
          lastUrl = window.location.href;
          log(`Navigate: ${lastUrl.substring(0, 120)}`);
          apiPost("/heartbeat", getPageStateCached());
        }
        poll();
      }

      setInterval(tick, POLL_MS);
      setTimeout(poll, 500);
    });
  }

  boot();
})();
