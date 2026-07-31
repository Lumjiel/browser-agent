// ==UserScript==
// @name         Browser Console (ADB Shell)
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  通过 rish + Shizuku 在浏览器中执行 adb shell 命令（模拟输入/截图/UI dump）
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function() {
    'use strict';

    const TOKEN = "MY_SECRET_123456";
    const API_URL = "http://127.0.0.1:8123/api/shell";

    // 封装：执行 shell 命令
    async function sh(cmd) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: "POST",
                url: API_URL,
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${TOKEN}`
                },
                data: JSON.stringify({cmd: cmd}),
                onload: (resp) => {
                    try {
                        resolve(JSON.parse(resp.responseText));
                    } catch(e) { reject(e); }
                },
                onerror: reject
            });
        });
    }

    // 封装：确保浏览器在前台并获得输入焦点
    window.focusBrowser = async () => {
        await sh('am start -n com.mmbox.xbrowser/.BrowserActivity');
        await sleep(1000);
    }

    // 封装：在浏览器中输入（先聚焦浏览器 → 点击输入框 → 输入）
    window.typeInBrowser = async (text, inputX, inputY) => {
        await sh('am start -n com.mmbox.xbrowser/.BrowserActivity');
        await sleep(800);
        await sh(`input tap ${inputX || 1920} ${inputY || 950}`);  // 点击输入框
        await sleep(500);
        await sh(`input text ${text.replace(/ /g, '%s')}`);
    };

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    // 封装：点击坐标
    window.tap = async (x, y) => sh(`input tap ${x} ${y}`);
    // 封装：滑动
    window.swipe = async (x1, y1, x2, y2, ms=300) => sh(`input swipe ${x1} ${y1} ${x2} ${y2} ${ms}`);
    // 封装：输入文字
    window.type = async (text) => sh(`input text ${text.replace(/ /g, '%s')}`);
    // 封装：按键
    window.key = async (code) => sh(`input keyevent ${code}`);
    // 封装：截图
    window.screenshot = async () => sh(`screencap -p /sdcard/screenshot.png`);
    // 封装：获取 UI 树
    window.uidump = async () => {
        await sh(`uiautomator dump /sdcard/uidump.xml`);
        // 读取 XML 内容
        const r = await sh(`cat /sdcard/uidump.xml`);
        return r.stdout;
    };
    // 封装：获取当前应用
    window.currentApp = async () => sh(`dumpsys window windows | grep mCurrentFocus`);

    // 创建悬浮控制台
    const panel = document.createElement('div');
    panel.id = 'shizuku-console';
    panel.innerHTML = `
        <div style="position:fixed;top:10px;right:10px;z-index:99999;background:#1a1a2e;color:#eee;padding:12px;border-radius:8px;font-family:monospace;font-size:13px;min-width:280px;box-shadow:0 4px 20px rgba(0,0,0,0.4);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="color:#0f0;font-weight:bold;">⚡ Shizuku Bridge</span>
                <button id="shizuku-toggle" style="background:#333;color:#eee;border:none;padding:2px 8px;border-radius:3px;cursor:pointer;">−</button>
            </div>
            <div id="shizuku-body">
                <input id="shizuku-input" placeholder="输入命令..." style="width:100%;background:#000;color:#0f0;border:1px solid #333;padding:6px;border-radius:4px;box-sizing:border-box;outline:none;">
                <div id="shizuku-output" style="margin-top:6px;max-height:200px;overflow-y:auto;color:#aaa;font-size:12px;white-space:pre-wrap;"></div>
                <div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">
                    <button data-cmd="input tap 500 800" style="background:#333;color:#eee;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;">点击</button>
                    <button data-cmd="uiautomator dump /sdcard/uidump.xml" style="background:#333;color:#eee;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;">UI树</button>
                    <button data-cmd="screencap -p /sdcard/screenshot.png" style="background:#333;color:#eee;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;">截图</button>
                    <button data-cmd="dumpsys window windows | grep mCurrentFocus" style="background:#333;color:#eee;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;">前台</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(panel);

    const input = document.getElementById('shizuku-input');
    const output = document.getElementById('shizuku-output');
    const toggle = document.getElementById('shizuku-toggle');
    const body = document.getElementById('shizuku-body');

    // 折叠/展开
    toggle.onclick = () => {
        const visible = body.style.display !== 'none';
        body.style.display = visible ? 'none' : 'block';
        toggle.textContent = visible ? '+' : '−';
    };

    // 执行命令并显示结果
    async function execCmd(cmd) {
        output.textContent = `> ${cmd}\n执行中...`;
        try {
            const r = await sh(cmd);
            const text = r.stdout || r.stderr || r.error || '(无输出)';
            output.textContent = `> ${cmd}\n${text}`;
        } catch(e) {
            output.textContent = `> ${cmd}\n错误: ${e.message || e}`;
        }
    }

    // 回车执行
    input.onkeydown = (e) => {
        if (e.key === 'Enter' && input.value.trim()) {
            execCmd(input.value.trim());
            input.value = '';
        }
    };

    // 快捷按钮
    panel.querySelectorAll('button[data-cmd]').forEach(btn => {
        btn.onclick = () => execCmd(btn.dataset.cmd);
    });

    console.log('✅ Shizuku Bridge 已加载。输入 tap(500,800) / type("hello") / swipe(500,1500,500,500) 测试');
})();
