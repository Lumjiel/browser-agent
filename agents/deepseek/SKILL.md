---
name: ask-deepseek
description: DeepSeek 自由讨论调度器。多轮对话、目标驱动、死路注册、事实注入、幻觉警惕。当用户说「问 DeepSeek」「讨论方案」「架构讨论」「技术选型」时触发。
version: 3.1.1
type: browser-automation
trigger: 问 DeepSeek, 讨论方案, 架构讨论, 技术方案, DeepSeek 分析, 方案评审, brainstorm
---

# DeepSeek 自由讨论调度器

你是 DeepSeek 自由讨论的调度器。核心模式：**一轮一轮对话**，不是一次性输出。

## 唯一入口

```bash
# 纯提问
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh "<问题>" [goal_file] [timeout]

# 带文件上传（支持多文件）
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh "<问题>" [goal_file] [timeout] [--file a] [--file b]

# 自动扫描本地文件（--context 模式）
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh --context "关键词" "<问题>"

# 多轮追问
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh --round 2 "<追问内容>"

# 切换目标
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh --goal "新目标"

# 注册死路
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh --dead "被否决的方向"

# 自由讨论（忽略目标）
bash ~/projects/active/browser-agent/scripts/ask-deepseek-free.sh --free "<问题>"
```

| 参数 | 说明 | 默认值 |
|:---|:---|:---|
| `--context <关键词>` | 自动扫描本地相关文件上传 | 无 |
| `--dir <目录>` | 额外扫描目录（可多次指定） | ~/projects, ~/tools, ~/.agents/skills |
| `--file` | 上传文件路径（可选，可多次，最大 1MB） | — |
| `--round N` | 多轮追问（第 N 轮，影响事实注入策略） | 1 |
| `--goal <目标>` | 切换讨论目标（覆盖 goal.txt） | — |
| `--dead <方向>` | 注册死路（追加到 dead_ends.txt） | — |
| `--free` | 自由讨论模式（忽略 goal.txt） | false |
| 问题 | 要讨论的内容（必填） | — |
| goal_file | 目标文件路径 | `~/projects/active/browser-agent/agents/deepseek/goal.txt` |
| timeout | 等待秒数 | `120` |

## 脚本行为（一体化）

1. 检查桥接服务 + 浏览器客户端连接
2. 读取 goal.txt 作为 `## 当前讨论目标` 上下文前缀
3. 读取 dead_ends.txt 作为 `## 已排除方向` 约束
4. 第 1 轮注入 facts.txt 减少幻觉
5. 复用已有 DeepSeek tab（不 navigate，保持多轮对话上下文）
6. 如有 --file 参数：base64 编码 → DataTransfer 注入 → 等 3 秒
7. 输入问题 + 点击发送 + 轮询等待回答（字数稳定 = 完成）
8. 输出回答文本

## 文件上传

### 路径格式

**Windows (Git Bash/WSL)**：
```bash
# 使用 /mnt/ 前缀访问 Windows 分区
bash ask-deepseek-free.sh "分析这个文件" --file /mnt/e/test-upload.txt
bash ask-deepseek-free.sh "对比文件" --file /mnt/c/Users/name/file.txt --file /mnt/d/other.txt
```

**Linux/macOS**：
```bash
bash ask-deepseek-free.sh "分析这个文件" --file ~/projects/myfile.txt
```

### 自动扫描 (--context)

按关键词自动扫描本地目录，上传相关文件：
```bash
# 扫描默认目录中文件名包含 "config" 的文件
bash ask-deepseek-free.sh --context "config" "分析配置"

# 扫描额外目录
bash ask-deepseek-free.sh --context "sherpa" --dir ~/my-project "集成方案"
```

**匹配逻辑**：文件名包含关键词（不区分大小写）→ README 优先 → 最多 10 个 → 超 1MB 自动截断

### 技术细节

- 文件通过 base64 编码 → DataTransfer API 注入到 `input[type=file]`
- 支持多文件同时上传
- 超 1MB 自动截断并标记 `[截断]`

## goal.txt 管理

- 存在 → 作为上下文前缀发给 DeepSeek
- 不存在 → 纯自由讨论
- 用户说"换个目标" → `--goal` 覆盖写入新内容
- 用户说"自由讨论/随便聊聊" → `--free` 忽略目标

路径: `~/projects/active/browser-agent/agents/deepseek/goal.txt`

## dead_ends.txt 管理

- 用户确认某个方向不可行时 → `--dead` 注册
- 每轮自动注入 prompt 作为排除约束
- 避免重复建议已否决方向

路径: `~/projects/active/browser-agent/agents/deepseek/dead_ends.txt`

## facts.txt 管理

- 本地环境事实注册表，减少 DeepSeek 幻觉
- 仅第 1 轮注入（后续轮次已有上下文）
- 环境变更后手动更新

路径: `~/projects/active/browser-agent/agents/deepseek/facts.txt`

## 多轮对话

```
第N轮:
  1. 决定追问方向（基于目标 + 上轮回答）
  2. 脚本发送（带 goal.txt + dead_ends.txt + facts.txt 上下文）
  3. 收到回答
  4. 快速判断:
     - 偏题 → 追问纠正
     - 可疑点 → 标记但不验证
     - 完备 → 结束或换角度
```

## 幻觉处理（不验证，只标记）

DeepSeek 会有幻觉。代码片段、版本号、配置示例可能与你的环境不匹配。

| 信号 | 处理 |
|:---|:---|
| 具体数字无来源 | 内心标记，不验证 |
| 给了链接 | 默认不信任，不打开 |
| API/库名不确定 | 记住，影响决策时再追问 |
| 代码片段 | 能用就用，不能用让它改，不查文档 |
| 承认编造 | 接受，继续下一轮 |
| 偏题/自相矛盾 | 追问纠正 |

**核心**: 保持警惕是为了不被骗，不验证是为了省时间。讨论目的是探索方案，不是事实核查。

## 兜底

- 桥接未运行 → 自动启动
- 浏览器客户端未连接 → 报错（需 Chrome + 油猴脚本打开 DeepSeek）
- 回答超时 → 返回已有内容（如有）

## 踩坑（精简版）

| # | 要点 |
|:--|:-----|
| 1 | 操作一键化：加载目标+发问题+等回答 一个脚本搞定 |
| 2 | 幻觉审查≠验证：知道可能有坑但不花时间查 |
| 3 | goal.txt 必须发给 DeepSeek，不是光本地读 |
| 4 | 复用已有 tab 保持多轮对话上下文，不 navigate 开新对话 |
| 5 | 页面首次加载 sleep 8s，确保 textarea 可交互 |
| 6 | 文件上传：base64 + DataTransfer 注入，全自动，最大 1MB/文件 |
| 7 | 死路注册：用户否决的方向记录在案，不再重复建议 |
| 8 | 事实注入：第 1 轮注入本地环境事实，减少幻觉 |
| 9 | Windows 路径用 `/mnt/` 前缀（如 `/mnt/e/file.txt`），不要用 `/e/` |

### 策略系统

`agents/deepseek/strategies/` 目录下存放策略模板，可在 goal.txt 的 constraints 中引用：

- `adversarial_review.txt` — 对抗式审查
- `project_research.txt` — 项目调研
- `recommend.txt` — 推荐方案
- `search_and_review.txt` — 搜索审查
