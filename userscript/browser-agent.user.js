// ==UserScript==
// @name         Browser Agent (通用版)
// @namespace    https://github.com/Lumjiel/browser-agent
// @version      3.0.0
// @description  通用浏览器代理 - 轮询获取命令，执行 DOM 操作。兼容 Tampermonkey/Violentmonkey/XBrowser。
// @author       npezarro, Lumjiel (localized)
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // Skip iframes
  if (window.self !== window.top) return;

  // ── Configuration ──
  const API_BASE = "http://127.0.0.1:8123/api/browser";
  const VERSION = "3.0.0";
  const POLL_MS = 2000;

  // Per-tab session ID
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

  // ── Universal HTTP helpers ──
  // Priority: GM_xmlhttpRequest → fetch → XMLHttpRequest

  function apiPost(path, data) {
    const url = API_BASE + path;
    const body = JSON.stringify(data);

    // Try GM_xmlhttpRequest first (Tampermonkey/Violentmonkey)
    if (typeof GM_xmlhttpRequest !== "undefined") {
      try {
        GM_xmlhttpRequest({
          method: "POST",
          url: url,
          headers: { "Content-Type": "application/json" },
          data: body,
          onload: () => {},
          onerror: () => {},
          ontimeout: () => {},
        });
        return Promise.resolve();
      } catch (e) {
        // fall through to fetch
      }
    }

    // Try fetch
    if (typeof fetch !== "undefined") {
      return fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
      }).catch(() => {
        // Fallback to XMLHttpRequest
        return new Promise((resolve, reject) => {
          try {
            const xhr = new XMLHttpRequest();
            xhr.open("POST", url, true);
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.onload = () => resolve();
            xhr.onerror = () => reject();
            xhr.send(body);
          } catch (e) {
            reject(e);
          }
        });
      });
    }

    // Last resort: XMLHttpRequest
    return new Promise((resolve, reject) => {
      try {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", url, true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onload = () => resolve();
        xhr.onerror = () => reject();
        xhr.send(body);
      } catch (e) {
        reject(e);
      }
    });
  }

  function apiGet(url) {
    // Try fetch first for GET
    if (typeof fetch !== "undefined") {
      return fetch(url, {
        headers: { "Content-Type": "application/json" },
      }).then((resp) => {
        if (resp.status !== 200) return null;
        return resp.json();
      }).catch(() => null);
    }

    // Fallback to XMLHttpRequest
    return new Promise((resolve) => {
      try {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", url, true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onload = () => {
          try { resolve(JSON.parse(xhr.responseText)); } catch (e) { resolve(null); }
        };
        xhr.onerror = () => resolve(null);
        xhr.send();
      } catch (e) {
        resolve(null);
      }
    });
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

        case "getHtml": {
          const el = document.querySelector(cmd.selector);
          result = el ? { html: el.innerHTML.substring(0, cmd.maxLen || 5000) } : { error: "not found" };
          break;
        }

        case "querySelector": {
          const qEl = document.querySelector(cmd.selector);
          if (qEl) {
            result = {
              found: true,
              text: qEl.innerText?.trim().substring(0, 500),
              tag: qEl.tagName,
              id: qEl.id || null,
              classes: (qEl.className?.toString() || "").substring(0, 200),
            };
          } else {
            result = { found: false };
          }
          break;
        }

        case "querySelectorAll": {
          const els = Array.from(document.querySelectorAll(cmd.selector || "*"));
          const limit = cmd.limit || 20;
          result = { count: els.length, elements: els.slice(limit).map((e) => ({ tag: e.tagName, text: e.innerText?.trim().substring(0, 100) })) };
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

        case "clickAny": {
          const lc = cmd.text.toLowerCase();
          let found = null;
          let matchNum = 0;
          const targetNth = cmd.nth || 1;
          for (const el of document.querySelectorAll("*")) {
            const t = (el.innerText || el.value || "").trim().toLowerCase();
            if (t.includes(lc) && el.offsetParent !== null) {
              matchNum++;
              if (matchNum === targetNth) { found = el; break; }
            }
          }
          if (found) {
            found.scrollIntoView({ block: "center" });
            found.click();
            result = { clicked: true, text: (found.innerText || found.value || "").trim().substring(0, 80) };
          } else {
            result = { clicked: false, error: "No element found" };
          }
          break;
        }

        case "navigate":
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
              for (const char of cmd.text) {
                typeEl.dispatchEvent(new KeyboardEvent("keydown", { key: char, bubbles: true }));
                const typeProto = typeEl.tagName === "TEXTAREA"
                  ? window.HTMLTextAreaElement.prototype
                  : window.HTMLInputElement.prototype;
                const nSet = Object.getOwnPropertyDescriptor(typeProto, "value")?.set;
                if (nSet) {
                  nSet.call(typeEl, typeEl.value + char);
                } else {
                  typeEl.value += char;
                }
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

        case "fillForm": {
          const fields = cmd.fields || {};
          let filled = 0;
          for (const [selector, value] of Object.entries(fields)) {
            const el = document.querySelector(selector);
            if (el) {
              el.focus();
              const proto = el.tagName === "TEXTAREA"
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
              const nativeSet = Object.getOwnPropertyDescriptor(proto, "value")?.set;
              if (nativeSet) nativeSet.call(el, value);
              else el.value = value;
              el.dispatchEvent(new Event("input", { bubbles: true }));
              el.dispatchEvent(new Event("change", { bubbles: true }));
              filled++;
            }
          }
          result = { filled, total: Object.keys(fields).length };
          break;
        }

        case "selectOption": {
          const selEl = document.querySelector(cmd.selector);
          if (selEl) {
            selEl.value = cmd.value;
            selEl.dispatchEvent(new Event("change", { bubbles: true }));
            result = { selected: true, value: cmd.value };
          } else {
            result = { selected: false, error: "Select not found" };
          }
          break;
        }

        case "eval":
          try {
            const evalResult = eval(cmd.code);
            result = { ok: true, value: typeof evalResult === "object" ? JSON.stringify(evalResult) : String(evalResult) };
          } catch (evalErr) {
            result = { ok: false, error: evalErr.message };
          }
          break;

        case "scroll":
          if (cmd.selector) {
            const sEl = document.querySelector(cmd.selector);
            if (sEl) sEl.scrollIntoView({ block: "center" });
          } else if (cmd.y !== undefined) {
            window.scrollTo(0, cmd.y);
          }
          result = { scrolled: true, scrollY: window.scrollY };
          break;

        case "waitForSelector":
          result = { waited: true, found: !!document.querySelector(cmd.selector) };
          break;

        case "waitForText":
          result = { waited: true, found: (document.body?.innerText || "").includes(cmd.text) };
          break;

        case "waitForRender":
          result = { waited: true, bodyLen: (document.body?.innerText || "").length };
          break;

        case "wait":
          await new Promise((r) => setTimeout(r, cmd.ms || 1000));
          result = { waited: cmd.ms || 1000 };
          break;

        case "assertText":
          result = { ok: (document.body?.innerText || "").includes(cmd.text) };
          break;

        case "assertSelector":
          result = { ok: !!document.querySelector(cmd.selector) };
          break;

        case "ping":
          result = { pong: true, ts: Date.now() };
          break;

        default:
          result = { error: `Unknown action: ${action}` };
      }

      return result;
    } catch (err) {
      return { ok: false, error: err.message };
    }
  }

  // ── Polling loop ──

  let polling = false;

  async function poll() {
    if (polling) return;
    polling = true;

    try {
      const data = await apiGet(`${API_BASE}/commands?tabId=${tabId}&url=${encodeURIComponent(window.location.href)}`);
      if (!data || !data.commands || data.commands.length === 0) return;

      for (const cmd of data.commands) {
        try {
          const result = await execCommand(cmd);
          if (result) apiPost("/result", { tabId, id: cmd.id, ok: true, result });
        } catch (err) {
          apiPost("/result", { tabId, id: cmd.id, ok: false, error: err.message });
        }

        if (data.commands.length > 1) {
          await new Promise((r) => setTimeout(r, 300));
        }
      }
    } catch (e) {
      // silent fail
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
