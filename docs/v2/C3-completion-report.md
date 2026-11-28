# Hephaestus V2 C3 阶段完成报告

- 报告日期：2026-11-28
- 分支：`feat/v2-cross-platform`
- 实现提交：`e07fd69`
- 真实用户数据库：未迁移、未修改（SHA256 见第 12 节）

## 1. C3.1 / C3.2 / C3.3 完成情况

### C3.1 AI 聊天工作台

已完成，并在 Windows WebView2 真实界面中验收：

- 会话管理：新建、历史列表、选择、重命名、删除、刷新、刷新后恢复；归档通过现有 `archived` 字段接入，支持归档/取消归档，归档会话在列表中标记并禁止继续发送。
- 聊天交互：用户/助手气泡、Markdown 渲染、代码块高亮与复制、多行输入、Enter 发送、Shift+Enter 换行、流式输出、停止生成、重新生成、错误重试、生成中/已停止/失败状态。
- Provider/模型：读取 `GET /api/v2/ai/providers`，选择配置与模型；Ollama 与在线 API 在配置界面和状态提示中明确区分；没有可用配置时显示明确引导，不伪装连接成功。
- 可靠性：DataPort 逐块解析 SSE，处理跨 chunk 边界、网络中断、超时、停止和错误事件；防止重复提交；停止后保留已生成内容；刷新/重开从数据库恢复会话，不把完整聊天历史写入 localStorage。
- UI：在原有笔记界面上增加独立聊天工作台覆盖层，保留原有笔记、标签、收藏、回收站、主题和布局；支持窄屏侧栏切换。

### C3.2 赫淮斯托斯助手人格与设置

已完成：

- 默认名称为“赫淮斯托斯”，支持修改名称、专业严谨/简洁直接/友好自然/学术研究/创意探索/自定义风格、回答长度和自定义提示词。
- 设置通过现有 `AppSettings` / `AppSettingsPatch` 和 DataPort `PATCH /api/v2/settings` 持久化，使用 `assistant_name`、`assistant_style`、`response_length`、`assistant_custom_prompt` 字段，没有新增前端孤立存储。
- 支持恢复默认人格；界面提供实时预览、保存状态和关闭后的通知反馈。
- 人格在每次对话请求时注入：名称、风格、长度、自定义要求，最后追加不可覆盖的安全规则；对话自身的 `system_prompt` 作为附加要求，不能移除安全规则。
- 组合上限：人格文本最多 4000 字符，对话提示最多 6000 字符，最终 system prompt 最多 12000 字符；上下文仍受 24000 字符预算约束。
- 名称/自定义提示中的空值、NUL、疑似密钥或 Capability Token 会被拒绝；API Key 和 Token 不进入人格设置。

### C3.3 桌面端桥接与联调

Windows 已完成并通过真实 WebView2 自动化验收：

- `DesktopBridge.capability_token()` 为页面提供能力令牌；DataPort 只在内存保存，并只对 `/api/v2/ai/` 请求注入 `X-Hephaestus-Capability`；同时发送 `X-Hephaestus-Platform: desktop`。
- 桌面端 Ollama/在线 Provider 配置、模型选择、流式 SSE、停止、重新生成、刷新恢复均通过同一套前端和 DataPort 路径工作。
- 桥接不可用时，聊天界面显示明确错误，不伪造成功；普通浏览器无法安全取得令牌时保持 AI 不可用。
- 外部链接通过 `DesktopBridge.open_external()` 打开，仅允许 http/https 且拒绝凭据、javascript/file/data 等协议。
- 修复桌面页面 Referer 带 `?desktop=1` 被误判为跨站的问题；Origin 仍严格校验，未放宽 C1.1 的 Host/Origin/SSRF 边界。
- 修复跨请求 ChatService 实例无法取消流式生成的问题：共享取消状态后，停止接口能真正中止正在生成的流，而不是让完成状态覆盖“已停止”。

macOS/Linux/Android/iOS 未做真实 AI 联调，详见第 7 节。

## 2. 新增和修改文件清单

### 新增

| 文件 | 作用 |
|---|---|
| `app/v2/ai/persona.py` | 人格组合、风格/长度指令、安全规则、密钥检测与长度上限 |
| `static/chat.css` | 聊天工作台、消息、Markdown、代码块、人格/Provider 弹窗样式 |
| `static/chat.js` | 聊天状态机、SSE 消费、Markdown 安全渲染、会话/人格/Provider UI |
| `tests/frontend/c3_chat_ui_verify.py` | 真实 Windows WebView2 + pywebview + mock Ollama 验收脚本 |
| `tests/frontend/chat.test.cjs` | SSE、Markdown 安全、状态 reducer、人格预览、DataPort AI 桥接 Node 测试 |

### 修改

下表包含实现提交 `e07fd69` 与文档索引提交 `ba16227` 的改动。

| 文件 | 作用 |
|---|---|
| `app/v2/ai/chat.py` | 共享会话锁/取消状态，人格注入，停止跨请求生效 |
| `app/v2/ai/middleware.py` | 修复带查询串的桌面 Referer 校验 |
| `app/v2/contracts.py` | 增加 `assistant_custom_prompt` 及人格字段校验 |
| `desktop/main.py` | 增加安全外部链接桥接 |
| `static/dataport.js` | AI Provider/会话/消息/设置方法、SSE stream、平台与 Capability 头 |
| `static/index.html` | 聊天工作台、人格设置、Provider 设置、归档按钮 |
| `static/script.js` | 暴露 `Store.port` 给聊天模块，不改笔记逻辑 |
| `tests/frontend/ui_verify.py` | 可见弹窗选择器修复，避免命中隐藏的人格弹窗 |
| `tests/test_desktop.py` | 外部链接白名单测试 |
| `tests/test_v2_ai_chat.py` | 人格持久化/注入/安全边界、跨实例停止回归测试 |
| `tests/test_v2_ai_security.py` | 桌面 Referer 查询串回归测试 |
| `tests/test_v2_migration.py` | settings 字段数随人格字段更新为 9 |
| `docs/v2/README.md` | C3 状态、测试数与报告索引 |
| `docs/v2/C3-completion-report.md` | 本报告 |

实现提交 `e07fd69` 的统计为 17 个文件、+3014/−20；C3 没有修改 `main`，没有修改旧版 `frontend_state` 数据。

## 3. 关键架构和接口

### 数据流

桌面窗口 → `static/chat.js` → `static/dataport.js`（内存令牌、SSE stream）→ `/api/v2/ai/*` → Capability/本机/Origin 中间件 → `ChatService` → Provider 适配器（Ollama 或 OpenAI 兼容）→ 本地 SQLite 会话/消息。

### 会话与消息

- `ConversationRead` 包含 id/title/provider_id/model/system_prompt/archived_at/revision/message_count/时间戳。
- `MessageRead` 包含 id/conversation_id/role/content/status/sequence/client_id/error_code/时间戳。
- 发送消息返回 `text/event-stream`，事件类型为 `start`、`delta`、`done`、`stopped`、`error`；每行格式 `data: <json>`，以空行分隔。
- 停止接口同时支持会话级和消息级路径；停止后消息状态为 `stopped`，已生成文本保留。
- 归档会话不能继续发送，API 返回 `conversation_archived`；前端禁用输入并提示取消归档。

### 人格

`compose_system_prompt(settings, conversation_prompt)` 的顺序为：助手名称 → 回答风格 → 回答长度 → 自定义人格 → 会话附加提示 → 固定安全规则。安全规则永远追加在最后，用户自定义内容不能覆盖。

### 密钥与权限

- Provider API Key 只通过写入接口传入，读取接口只返回 `has_key`；实际密钥保存在操作系统密钥存储（Windows 为 DPAPI），数据库只保存引用。
- Capability Token 只存在于桌面桥接和 DataPort 内存；不进入 localStorage、sessionStorage、URL 或日志。
- AI 路由仍要求本机客户端和 Capability Token；本次没有放宽 C1.1 的 SSRF、Host、Origin 或请求限制。

## 4. 安全检查结果

| 检查 | 结果 |
|---|---|
| Token 是否出现在 WebView2 DOM | 否（真实验收检查通过） |
| Token 是否出现在 localStorage/sessionStorage | 否（真实验收检查通过） |
| 聊天历史是否写入 localStorage | 否；只从数据库恢复 |
| Markdown 原始 HTML | 全部转义；测试覆盖 `<img onerror>` 与 `<script>` |
| 危险链接 | 仅允许 http/https/mailto/#；`javascript:` 被移除 |
| 外部链接打开 | 经桌面桥接，仅 http/https，拒绝凭据和危险协议 |
| API Key 回显 | 读取接口不返回密钥，只返回 `has_key` |
| 人格中的密钥/Token | 契约校验拒绝；组合层再次检测 |
| 自定义人格覆盖安全规则 | 测试确认安全规则始终在最后且不可移除 |
| Origin/Referer | 桌面 Referer 查询串回归修复；Origin 带查询串仍被拒绝 |
| 真实收费 API | 未调用；验收使用本地 mock Ollama |

残余风险：桌面页面必须能通过 `pywebview.api.capability_token()` 读取令牌，因此若页面出现 XSS，令牌仍可能被同源脚本读取；当前以严格 Markdown 转义、外链白名单和 CSP 缺失风险记录在第 8 节。

## 5. 完整测试结果及测试数量

### 后端 / 全量 pytest

命令：`.venv/Scripts/python.exe -m pytest -q --tb=short`

- 结果：**158 passed, 1 skipped, 1 warning in 189.75s**
- 收集总数：159 项
- 跳过项：`tests/test_v2_ai_security.py:486`，Windows 上 DPAPI 可用，跳过的是平台条件回退测试
- 警告：StarletteDeprecationWarning，提示 `httpx` 与 `starlette.testclient` 的弃用组合
- 全量测试包含 C2 鉴权、会话持久化、SSE、停止/重生成、人格、安全、迁移、桌面、安装器和 UI 集成测试

### 前端 Node

命令：`node --test tests/frontend/chat.test.cjs`

- 结果：**5 passed, 0 failed**
- 覆盖 SSE 分块/畸形事件、Markdown XSS、`javascript:` 链接、停止状态保留、人格预览、DataPort Capability/Platform 头和原始 SSE Response

### 移动端契约

- `node --experimental-strip-types --experimental-sqlite --test tests/contract.test.ts`：**6 passed**
- `tsc --noEmit`：退出码 0
- 仅验证契约兼容；移动端原生 AI 桥接未实现，见第 7 节

### Windows WebView2 验收

- 主流程：22 项检查全部通过
- 重开流程：8 项检查全部通过
- 无失败检查；真实用户数据库与验收源库哈希前后一致

## 6. Windows 实际 UI 验收情况

验收使用 `tests/frontend/c3_chat_ui_verify.py`：复制 `data/b3-drill/drill.db` 到临时目录，启动真实 uvicorn、本地 mock Ollama 和 pywebview WebView2 窗口（自动化隐藏窗口），通过 DOM 事件驱动真实界面。

主流程检查全部通过：

- Token 不在 DOM、不在浏览器存储
- 聊天工作台打开、Provider 保存、模型选择
- 人格预览、保存、弹窗关闭
- 会话创建、重命名
- 归档后列表标记、输入禁用；取消归档后输入恢复
- 流式回答出现、Markdown 粗体渲染、代码块渲染、无 `<script>`
- 完成后状态正常
- 停止后保留 48 字符部分内容，完整末尾未出现
- 重新生成完成
- 刷新后用户消息、助手消息、人格头部恢复

重开流程检查全部通过：会话、用户消息、助手消息、人格名称、风格、自定义提示均从数据库恢复。

会话数据库最终为 1 个会话、4 条消息、9 项设置；临时库 integrity_check 为 `ok`。

## 7. macOS/Linux/Android/iOS 尚未完成的事项

| 平台 | 状态 | 未完成事项 |
|---|---|---|
| Windows | 已完成本机 WebView2 自动化验收 | 真实 Ollama、真实在线 API、真实用户库迁移未做 |
| macOS | 未实测 | pywebview/WebView2 替代运行时、签名、通知、真实 AI 桥接未验证 |
| Linux | 未实测 | WebKitGTK 运行时、密钥存储、桌面桥接、真实 AI 未验证；仅保留单元/契约级兼容 |
| Android | 未实现 AI | 只有既有数据契约测试；Capability Token 原生桥接、SSE、会话 UI 未实现 |
| iOS | 未实现 AI | 同上；未声明可用 |

本报告不把 macOS/Linux/Android/iOS 的 AI 能力标记为完成。

## 8. 已知问题与技术债务

1. `_SHARED_LOCKS` 为每个会话保留一个 `threading.Lock`，当前没有在会话删除后清理，长期运行会缓慢增长。
2. 前端尚未设置 Content-Security-Policy；Markdown 已严格转义，但 CSP 仍是纵深防御缺口。
3. 桌面桥接必须把 Capability Token 暴露给页面脚本；同源 XSS 仍是残余风险。
4. 验收使用 mock Ollama；真实 Ollama、真实在线 API 和收费 API 未测试，未产生费用。
5. 归档会话在同一个列表中展示并标记，没有单独的“归档箱”页面；功能可用但信息架构较简单。
6. 普通浏览器模式无法安全取得 Capability Token，AI 在纯 Web 页面默认不可用；这是既有安全设计，不是 C3 回归。
7. 真实用户数据库未迁移；C3 只在副本上验收，未执行 B3.4 迁移预案。
8. 未制作 V2 正式安装包，符合本阶段“不制作正式安装包”的限制。
9. WebView2 验收为自动化 DOM/事件驱动，不是人工逐项点击；真实窗口的视觉细节仍建议人工复核。

## 9. Git 提交记录

| 提交 | 说明 |
|---|---|
| `e07fd69` | `feat(v2): complete C3 AI chat workspace, persona and desktop bridge`（17 文件，+3014/−20） |
| `ba16227` | `11-27`（C3 文档状态与索引更新） |
| 本次报告提交 | `docs(v2): add C3 completion report`（本文件与最终文档状态） |

C3 代码提交位于 `feat/v2-cross-platform`，没有修改 `main`，没有 force push。

## 10. GitHub 推送结果和远程 HEAD

- 远程仓库：`https://github.com/jionbobby-commits/Hephaestus`
- 远程分支：`origin/feat/v2-cross-platform`
- 报告编写前远程 HEAD：`ba162278484beb0b85cee61d6e1f383e7e19616f`
- C3 实现提交 `e07fd69` 已包含在远程历史中
- 报告提交推送后，最终远程 HEAD 以交付回复中的 `git rev-parse origin/feat/v2-cross-platform` 为准
- 未推送 `main`，未合并 PR，未执行强制推送

## 11. 工作区最终状态

- 分支：`feat/v2-cross-platform`
- 本地与远程在报告提交前同步（0 ahead / 0 behind）
- 工作区在报告提交前只有本报告未跟踪；提交并推送后应为干净状态
- `main` 仍为 `82045834f4ff2d864a2ead14d5f423d734fe9b4d`，未被修改
- 无真实 API Key、Token、密码或用户笔记进入 Git

## 12. 确认真实用户数据库未发生变化

- 真实库路径：`C:/Users/Bobby-Zhang/AppData/Local/Hephaestus/hephaestus.db`
- 验收前 SHA256：`e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4`
- 验收后 SHA256：`e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4`
- 文件大小：16,384 字节
- 未执行迁移、未删除、未清空、未覆盖；未修改旧版 `frontend_state`
- WebView2 验收使用 `data/b3-drill/drill.db` 的临时副本，副本源哈希前后一致：`e5e5f510b7b1b057e1afdebf753661711d5653c771b9450df8eb78714c399a1b`
