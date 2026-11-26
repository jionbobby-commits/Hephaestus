# C2 阶段报告：AI 对话系统

状态：实现、测试与本地提交已完成，等待验收。按任务要求停在 C2，未进入 C3；未迁移真实库，未调用真实收费 API，未修改 main。

## 1. 结论

C2 已交付可复用的 AI 对话后端与统一契约：

- 本机 Capability Token 鉴权（C2.1）。
- Conversation / Message 数据模型，Python 与移动端 TypeScript DataPort 对齐（C2.2）。
- 多轮上下文、流式输出、停止、重新生成、超时、模型切换、错误归一化（C2.3）。
- `/api/v2/ai/conversations/*` API（C2.4）。
- 21 项 Python 对话测试、6 项移动端契约测试；完整 Python 测试 149 passed + 1 skipped。

本阶段没有聊天 UI，没有助手人格、RAG、附件送入模型、语音、安装包或真实库迁移；这些属于 C3 及后续，不能用“后端完成”冒充“用户界面可用”。

## 2. 架构分层

| 层 | 文件 | 职责 |
|---|---|---|
| 契约层 | `app/v2/contracts.py` | Conversation/Message/Send/Regenerate/Stop/ChatReply，角色、状态、长度和 revision 校验 |
| 数据层 | `app/v2/models.py`、`app/v2/dataport.py` | 两张增量表；会话/消息 CRUD、幂等、上下文查询、陈旧消息恢复 |
| 鉴权层 | `app/v2/ai/capability.py`、`app/v2/ai/middleware.py` | 进程内高熵 token、常量时间比较、Host/Origin 之后统一校验 |
| 对话引擎 | `app/v2/ai/chat.py` | 会话锁、轮次组装、上下文预算、SSE、停止、重新生成、错误落库 |
| 适配层 | `app/v2/ai/adapters.py`、`app/v2/ai/transport.py` | Provider 协议只在此层；DNS pinning、无重定向、字节上限、流式读取 |
| HTTP 层 | `app/v2/ai/api.py` | 对话 CRUD、消息、流式、停止、错误结构 |
| 桌面桥 | `desktop/main.py`、`static/dataport.js` | 启动时生成 token，经 pywebview `js_api` 交给受信任页面；只在 AI 请求加头 |
| 移动契约 | `mobile/src/contracts.ts`、`schema.ts`、`dataport.ts` | 同一会话/消息字段、状态、revision 和本地 SQLite 语义 |

旧 `/api/state`、`/notes`、`/api/v2` 与 C1 Provider 接口保留；C2 只新增路由和两张表，不改已有列。

## 3. C2.1 本机 Capability Token

### 机制

- 生成：`secrets.token_urlsafe(48)`，48 字节随机数，64 个 URL-safe 字符。
- 保存：仅当前进程内存；桌面启动方通过 `HEPHAESTUS_AI_TOKEN` 在同一进程树传递。
- 比较：`hmac.compare_digest`，避免普通字符串比较的时序差异。
- 请求头：`X-Hephaestus-Capability`；不放 URL、查询参数、Cookie、localStorage、SQLite、日志或 Git。
- 校验顺序：Host 合法 → Origin/Referer 同源 → 必须且只能一个 Capability 头 → 请求体/编码限制。
- 失败：缺失 401 `missing_capability`；错误或重复 401 `invalid_capability`；Host 403 `invalid_host`；跨站 403 `invalid_origin`。

### 分平台结论

| 平台 | 结论 |
|---|---|
| Windows 桌面（pywebview） | 已实现；原生桥 `DesktopBridge.capability_token()`，页面不落盘 token |
| macOS / Linux 桌面 | 设计上可复用；本机未实跑，需在对应平台验证 pywebview 桥和打包 |
| Web 浏览器 | **无法安全取得 token**；浏览器与任意本机进程同权限，没有带外通道。C2 不把 token 注入页面，因此 Web 端 AI 默认不可用 |
| Android / iOS | 预留 Capacitor 原生桥/安全存储方案；C2 未实现移动 HTTP 传输，只有本地 SQLite DataPort |
| 受信任本机脚本 | 必须显式设置环境变量/请求头；本机回环地址和平台头都不是身份 |

平台头 `X-Hephaestus-Platform` 只用于“移动端禁用 Ollama”的业务策略，不是鉴权。C2 不把可伪造头包装成权限。

## 4. C2.2 数据模型与迁移

### v2_conversations

`id`、`title`、`provider_id`、`model`、`created_at`、`updated_at`、`archived_at`、`revision`、`extra_json`（当前存 system_prompt）。

### v2_messages

`id`、`conversation_id`（FK，ON DELETE CASCADE，索引）、`role`、`content`、`status`、`sequence`、`client_id`（幂等键）、`error_code`、`created_at`、`updated_at`、`revision`。

状态：`pending / streaming / complete / stopped / error`。角色：`user / assistant / system`。

保证：

- 多会话、多轮、历史恢复、重命名、归档、删除。
- `client_message_id` 重复提交返回同一条助手回复，不重复调用模型。
- 同一会话进程内单写锁；第二个并发生成返回 409 `conversation_busy`。
- 会话 revision 乐观锁；旧 revision 返回 409。
- 读取历史时，超过 120 秒仍为 pending/streaming 的消息标记为 `error/generation_interrupted`，保留已生成内容。
- 删除会话级联删除消息；不触碰笔记、标签、收藏、回收站或旧 `frontend_state`。

### 迁移方案

C2 **没有执行真实迁移**。两张表是纯增量：

1. 显式迁移/测试建库时，`create_v2_db()` 的 `create_all` 补建两张新表。
2. 不需要 `ALTER TABLE`、不重写旧表、不删除 `frontend_state`。
3. 真实库迁移仍需单独授权；迁移前必须备份、在副本演练、验证回滚。
4. `/api/v2/status` 新增只读 `chat_schema_ready`；不改变 legacy/pending/ready/failed 的优先级。
5. 真实用户库仍是 legacy，未创建任何 v2 对话表。

## 5. C2.3 对话引擎与流式协议

### 上下文

- 只取当前会话、当前 assistant 消息之前的历史。
- 只包含 `user/assistant` 且状态为 `complete/stopped`、内容非空的消息。
- 最多 30 条、24,000 字符（含 system prompt 预算）。
- system prompt 过长时，最新一条用户消息截断到剩余预算；绝不把完整历史无限发给模型。
- 不自动读取或上传笔记、附件、标签、设置。

### 流式

`stream=true` 返回 `text/event-stream`：

~~~text
data: {"type":"start","conversation_id":"...","user_message":{...},"assistant_message":{...}}
data: {"type":"delta","message_id":"...","text":"..."}
data: {"type":"done","reply":{...}}
data: {"type":"stopped","message":{...}}
data: {"type":"error","error":{...},"message":{...},"retryable":true}
~~~

- Provider 协议只在 `adapters.py` 实现；引擎只消费统一 `StreamDelta`。
- 传输层保持 DNS pinning、禁代理/重定向、响应字节上限和超时；流式读取同样受上限约束。
- 用户停止：设置取消事件，停止读取并落库 `stopped`；适配器关闭上游连接。
- 重新生成：复用同一条 assistant 消息，清空内容并重新生成，不新增重复消息。
- 断网/Provider 异常：已生成内容保留，消息置 `error`，HTTP/SSE 返回统一错误。
- 模型切换：会话级 `model` 在下一轮生效；Provider 默认模型仍由 C1 管理。
- 并发：全进程最多 4 个 Provider 调用槽，超出 429。

## 6. C2.4 API

全部前缀 `/api/v2/ai`，全部要求 Capability Token：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/conversations` | 列表，`page`、`page_size`、`include_archived` |
| POST | `/conversations` | 创建，201 |
| GET | `/conversations/{id}` | 详情 + 分页消息 |
| PATCH | `/conversations/{id}` | 重命名、换 Provider/模型、system prompt、归档；支持 revision |
| DELETE | `/conversations/{id}` | 删除会话及消息，204 |
| GET | `/conversations/{id}/messages` | 消息历史 |
| POST | `/conversations/{id}/messages` | 发送；`stream=true` 返回 SSE |
| POST | `/conversations/{id}/messages/{message_id}/regenerate` | 重新生成指定 assistant 消息 |
| POST | `/conversations/{id}/stop` | 停止当前生成（可带 message_id） |
| POST | `/conversations/{id}/messages/{message_id}/stop` | 停止指定消息 |
| POST | `/chat` | C1 无状态单次聊天，保留兼容 |

统一错误：

~~~json
{"error":{"code":"conversation_busy","message":"...","provider_id":null,"retryable":true,"details":{}}}
~~~

常见状态：401 鉴权、403 Host/跨站、404 不存在、409 归档/忙/revision、422 参数、429 并发槽、502 上游异常、503 不可用/未迁移、504 超时。

## 7. 安全与兼容性

- 不自动向外部模型发送笔记、附件、标签或设置；只有显式发送的对话消息进入上下文。
- API Key 继续只存系统密钥库；对话记录、响应、日志不含 Key 或 Capability Token。
- C1 的 SSRF、DNS pinning、错误脱敏、请求体上限继续生效。
- 旧 `/api/state`、`/notes`、`/api/v2`、C1 Provider 路由未删除；新鉴权只作用于 `/api/v2/ai`。
- 移动端契约只含 `has_key`，不含 `key_ref`/API Key；Ollama 在移动平台被拒绝。
- 未修改真实数据库、未删除笔记/附件、未执行真实迁移、未推送 main、未合并 PR。

## 8. 测试报告

完整 Python：

- 命令：`.venv/Scripts/python.exe -m pytest -q`
- 结果：**149 passed, 1 skipped, 1 warning in 192.73s**，EXIT 0
- warning：StarletteDeprecationWarning（httpx 与 starlette.testclient 弃用），既有问题。
- 组成：旧 60 + B1 14 + B2 10 + B3 4 + C1 16 + C1.1 25 + C2 21 = 150 项。
- 日志：`C:/Users/Bobby-Zhang/AppData/Local/Temp/heph_c2_pytest_final.txt`

C2 对话专项 21 项，覆盖 18 项要求及补充边界：

| 要求 | 测试 |
|---|---|
| Token 正常授权 | 所有带 token 的会话/消息测试；创建返回 201 |
| 无 Token 拒绝 | `test_missing_and_wrong_capability_are_rejected` |
| 错误 Token 拒绝 | 同上 |
| 跨站请求拒绝 | `test_cross_site_request_is_rejected_even_with_token` |
| 会话创建/读取/重命名/删除 | `test_conversation_create_list_rename_archive_delete` |
| 消息持久化 | `test_message_persistence_and_multi_turn_context`、`test_restart_recovery_loads_conversation_and_messages` |
| 多轮上下文组装 | `test_message_persistence_and_multi_turn_context` |
| 流式输出 | `test_streaming_sse_events` |
| 中止生成 | `test_stop_generation_marks_message_stopped` |
| 重新生成 | `test_regenerate_replaces_the_same_assistant_message` |
| 网络中断 | `test_network_interruption_marks_message_error` |
| Provider 不可用 | `test_provider_unavailable_returns_unified_error` |
| 模型切换 | `test_model_switch_is_used_on_next_turn` |
| 超长上下文限制 | `test_context_is_bounded_by_messages_and_characters`、`test_long_system_prompt_still_hard_caps_context` |
| 并发写入冲突 | `test_concurrent_send_is_rejected` |
| 重启恢复 | `test_restart_recovery_loads_conversation_and_messages` |
| Key/Token 不出现在响应与日志 | `test_token_and_api_key_never_leak` |
| 移动端契约兼容 | `mobile/tests/contract.test.ts` 6 项通过；`test_mobile_platform_is_rejected_for_ollama` |

补充覆盖：`client_message_id` 幂等、重复流式请求复用已完成回复、陈旧 streaming 恢复、未知会话 404、旧路由仍可用、长 system prompt 截断。

其他检查：

- 移动端：`node --experimental-strip-types --experimental-sqlite --test tests/contract.test.ts` → 6 passed，0 failed。
- TypeScript：`tsc --noEmit` → EXIT 0。
- `compileall app/v2` 与 `import app.main` → EXIT 0。
- `git diff --check` → EXIT 0。

## 9. 数据验证

- 真实库：`%LOCALAPPDATA%/Hephaestus/hephaestus.db`
- 大小/哈希：16,384 bytes，SHA256 `e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4`
- C2 测试前后一致；未执行迁移、未写真实 `frontend_state`、未创建/删除任何真实 v2 表。
- 测试使用临时内存 SQLite 与显式副本，不触碰真实用户数据。

## 10. 改动文件

后端：`app/main.py`、`app/v2/models.py`、`app/v2/contracts.py`、`app/v2/dataport.py`、`app/v2/status.py`、`app/v2/ai/{capability,chat,middleware,transport,adapters,service,api}.py`。

桌面与前端：`desktop/main.py`、`static/dataport.js`。

移动端：`mobile/src/{contracts,schema,dataport}.ts`、`mobile/tests/contract.test.ts`。

测试：`tests/test_v2_ai_chat.py`（新增 21 项）、`tests/test_v2_ai.py`、`tests/test_v2_ai_security.py`。

文档：`docs/v2/24-c2-chat-architecture.md`，以及 `06-data-contract.md`、`08-dataport-and-api.md`、`10-contract-tests.md`、`README.md` 更新。

## 11. 已知限制与风险

1. **没有聊天 UI**：C2 是后端、契约和流式 API；用户还无法在现有界面直接聊天。聊天界面、人格、RAG、语音属于 C3/后续。
2. **Web 端 AI 不可用**：浏览器无法安全取得本机 token；C2 不把 token 注入 Web 页面。桌面端可用，Web 需要未来单独的受信任机制。
3. macOS/Linux 桌面桥未实跑；移动端只有本地 SQLite DataPort，没有 HTTP 传输或 Capacitor 原生桥。
4. 会话锁是进程内锁；多后端进程/多实例同时写同一 SQLite 文件没有跨进程会话锁。当前桌面是单进程。
5. 客户端断开依赖生成器收到 `GeneratorExit`；Provider 不支持及时取消时，停止可能要等下一次读取/超时；服务进程崩溃由 120 秒陈旧恢复兜底。
6. 测试全部使用 Mock/FakeTransport，没有调用真实 Ollama、OpenAI、DeepSeek、Qwen 或任何收费 API；真实网络行为仍需在验收环境单独验证。
7. HTTP 流式上限、并发 4 槽、上下文 30 条/24k 字符是当前硬限制；超长对话会被截断，界面必须说明。
8. 同一 OS 用户下具备进程内存读取/调试权限的恶意程序仍可能提取 token；这超出 HTTP 鉴权边界。
9. 没有多用户账户体系、速率/成本配额、审计中心或密钥轮换策略 UI。
10. 未做真实库迁移；真实库仍是 legacy，v2 对话表在真实库尚不存在。

## 12. Git

- 分支：`feat/v2-cross-platform`
- 实现提交：`eb5a819cdffe91a16f239d3a51ddcbac544cd716`
- 父提交：`d0897338cf3bb72911a4a59de56905c7ae49241b`
- 提交信息：`feat(v2): add C2 chat system with capability auth and streaming`
- 规模：26 files changed，3,217 insertions(+)，33 deletions(-)
- 未推送、未合并、未改 main；main 仍为 `82045834f4ff2d864a2ead14d5f423d734fe9b4d`。
- 本报告单独提交；提交后工作区应为干净状态。

## 13. 验收请求

请验收 C2 的 Capability Token、会话/消息契约、流式/停止/重新生成引擎、`/api/v2/ai/conversations/*` API、移动端 DataPort 对齐和 150 项测试。验收通过后再授权 C3；C3 才进入聊天界面、助手人格与用户可见交互。
