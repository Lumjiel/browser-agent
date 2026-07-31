// ==UserScript==
// @name         Browser Agent (XBrowser 适配版)
// @namespace    https://github.com/npezarro/claude-browser-agent
// @version      2.0.0
// @description  通用浏览器代理 - 轮询获取命令，执行 DOM 操作。适配 XBrowser（用 fetch 替代 GM_xmlhttpRequest）
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
  const API_BASE = "http://127.0.0.1:8123/api/browser";
  const VERSION = "2.0.0";
  const POLL_MS = 2000;

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

  // ── HTTP helpers (fetch 替代 GM_xmlhttpRequest) ──

  async function apiPost(path, data) {
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

  async function apiGet(url) {
    try {
      const resp = await fetch(url, {
        headers: { "Content-Type": "application/json" },
      });
      if (resp.status !== 200) return null;
      return await resp.json();
    } catch (e) {
      return null;
    }
  }

  function log(msg) {
    origLog(`[BrowserAgent] ${msg}`);
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

  // ── Poll loop ──

  let polling = false;

  async function poll() {
    if (polling) return;
    polling = true;

    const data = await apiGet(`${API_BASE}/commands?tabId=${tabId}&url=${encodeURIComponent(window.location.href)}`);

    if (data && data.commands && data.commands.length > 0) {
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

    polling = false;
  }

  // ── Init ──

  log(`v${VERSION} loaded on ${window.location.hostname}`);
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
  setTimeout(poll, 800);
})();
