// ==UserScript==
// @name         豆包自动问答桥接 (fetch版)
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  自动从队列读取问题 → 输入豆包 → 获取回答 → 传回队列
// @match        *://*/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    const API = "http://127.0.0.1:8123";
    const TOKEN = "MY_SECRET_123456";
    const POLL_INTERVAL = 3000;

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    // 通用 API 请求（用 fetch）
    async function api(endpoint, method="GET", data=null) {
        const opt = { method, headers: {} };
        if (data) {
            opt.headers["Content-Type"] = "application/json";
            opt.body = JSON.stringify(data);
        }
        const resp = await fetch(API + endpoint, opt);
        return resp.json();
    }

    // 执行 shell 命令
    async function sh(cmd) {
        return api("/api/shell", "POST", { cmd });
    }

    // ========== 核心：向豆包提问并获取回答 ==========
    async function askDoubao(question, inputX, inputY) {
        console.log(`[豆包桥] 提问: ${question}`);

        // 1. 确保浏览器在前台
        await sh('am start -n com.mmbox.xbrowser/.BrowserActivity');
        await sleep(1000);

        // 2. 点击输入框
        await sh(`input tap ${inputX} ${inputY}`);
        await sleep(500);

        // 3. 输入问题
        const safeQ = question.replace(/ /g, '%s');
        await sh(`input text ${safeQ}`);
        await sleep(300);

        // 4. 按回车发送
        await sh('input keyevent 66');
        console.log('[豆包桥] 已发送，等待回答...');

        // 5. 等待豆包回答
        await sleep(3000);

        // 6. 轮询检测回答
        let lastText = '';
        for (let i = 0; i < 20; i++) {
            await sleep(3000);

            await sh('uiautomator dump /sdcard/doubao_answer.xml');
            const r = await sh('cat /sdcard/doubao_answer.xml');
            const xml = r.stdout || '';

            // 提取所有文本
            const texts = [];
            const re = /text="([^"]+)"/g;
            let m;
            while ((m = re.exec(xml)) !== null) {
                if (m[1].trim().length > 1) texts.push(m[1]);
            }

            const currentText = texts.join('|');
            if (currentText !== lastText && texts.length > 0) {
                const answer = texts.filter(t => t.length > 10).pop();
                if (answer && answer !== question) {
                    console.log(`[豆包桥] 获取回答: ${answer.substring(0, 80)}...`);
                    return answer;
                }
            }
            lastText = currentText;
        }

        return '[超时] 未获取到回答';
    }

    // ========== 主循环 ==========
    async function mainLoop() {
        console.log('[豆包桥] 自动问答已启动');

        while (true) {
            try {
                const qResp = await api("/api/question");
                if (qResp.status === "ok" && qResp.question) {
                    const qData = JSON.parse(qResp.question);
                    const question = qData.question;
                    const inputX = qData.input_x || 1920;
                    const inputY = qData.input_y || 950;

                    console.log(`[豆包桥] 新问题: ${question}`);
                    const answer = await askDoubao(question, inputX, inputY);
                    await api("/api/submit_answer", "POST", { answer });
                    console.log(`[豆包桥] 回答已提交`);
                }
            } catch(e) {
                console.log('[豆包桥] 错误: ' + e.message);
            }
            await sleep(POLL_INTERVAL);
        }
    }

    // ========== 手动接口 ==========
    window.doubaoAsk = async (question, x, y) => {
        await api("/api/ask", "POST", { question, input_x: x || 1920, input_y: y || 950 });
        console.log('[豆包桥] 问题已提交');
    };

    window.doubaoAnswer = async () => {
        return api("/api/answer");
    };

    // 启动
    mainLoop();
    console.log('✅ 豆包桥 v2.0 已加载 (fetch版)');
})();
