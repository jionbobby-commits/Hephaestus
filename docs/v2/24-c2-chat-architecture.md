# C2 AI 对话系统：架构、鉴权、数据与流式协议

状态：C2 后端与契约实现完成，等待验收。未迁移真实库，未开发聊天 UI（C3 范围），未调用真实收费 API。

## 1. 范围与边界

C2 交付的是可复用的对话能力：

- 本机 Capability Token 鉴权（C2.1）。
- Conversation / Message 统一数据模型与 Python、TypeScript DataPort（C2.2）。
- 多轮上下文、流式输出、停止、重新生成、超时、模型切换与错误归一化（C2.3）。
- `/api/v2/ai/conversations/*` HTTP API（C2.4）。
- 21 项 Python 对话测试、移动端契约测试与 tsc 检查。

不在 C2：聊天 UI、AI 人格、RAG、附件送入模型、语音、真实迁移、安装包、C3 的任何工作。

## 2. C2.1 本机 Capability Token

### 2.1 威胁模型

本机回环地址不是身份。任意同用户进程都可以访问 `127.0.0.1`，因此不能用“来源 IP 是本机”或可伪造的 `X-Hephaestus-Platform` 请求头作为鉴权。C2 引入每次启动生成的高熵 bearer token，只在本机进程内存与受信任的原生桥之间传递。

### 2.2 生成与保存

- 生成：`secrets.token_urlsafe(48)`，48 字节随机数，64 个 URL-safe 字符。
- 环境变量：`HEPHAESTUS_AI_TOKEN`，仅用于同一进程树内传递；过短（<32 字符）会被拒绝或重新生成。
- 生命周期：桌面端在导入后端前生成；后端 `lifespan` 调用 `ensure_capability_token()`，已有值不覆盖。
- 存储：仅进程内存；不写 SQLite、不写 localStorage、不写 URL、不写普通日志、不写 Git。
- 比较：`hmac.compare_digest`，避免时序侧信道。

请求头：

```
X-Hephaestus-Capability: <token>
```

### 2.3 校验位置

`AISecurityMiddleware` 对 `/api/v2/ai` 前缀统一执行：

1. Host 必须是单值且为本机允许值（防 DNS rebinding）。
2. Origin / Referer 必须同源（防 CSRF）。
3. 必须且只能有一个 Capability 头，值通过时序安全比较。
4. 拒绝压缩请求体，限制请求体 2,000,000 字节。
5. 添加 `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。

失败结构：

| 情况 | HTTP | code |
|---|---|---|
| 缺少 token | 401 | `missing_capability` |
| token 错误或重复 | 401 | `invalid_capability` |
| Host 不合法 | 403 | `invalid_host` |
| 跨站 Origin/Referer | 403 | `invalid_origin` |

平台头 `X-Hephaestus-Platform` 只作为“移动端禁用 Ollama”的 UI 提示，不是权限依据。

### 2.4 分平台结论

| 平台 | 状态 | 说明 |
|---|---|---|
| Windows 桌面（pywebview） | 已实现 | 启动时生成 token，通过 `js_api=DesktopBridge` 暴露 `capability_token()`；前端 DataPort 只在 `/api/v2/ai` 请求加头。原页面不落盘 token。 |
| macOS 桌面 | 设计可用，未实跑 | 同一 Python/pywebview 架构；需在 macOS 上验证原生桥与代码签名。 |
| Linux 桌面 | 设计可用，未实跑 | 同上；依赖 WebKitGTK/pywebview 行为。 |
| Web 浏览器 | **无法安全取得 token** | 浏览器页面与任意本机进程同权限，没有可信的本机带外通道。C2 不把 token 注入页面、不写 cookie、不放 URL；因此 Web 端 AI 默认不可用。若要启用，只能由运维显式提供 token，但这会把 token 暴露给浏览器环境，C2 不推荐也不自动化。 |
| Android / iOS | 待原生壳接入 | 规划由 Capacitor 原生桥从安全存储/启动参数取得 token，再传给统一 DataPort；C2 未实现移动 HTTP 传输，移动端只有本地 SQLite DataPort。 |
| 纯 HTTP API 客户端 | 需显式提供 token | 仅适合本机受信任脚本；token 由启动方通过环境变量传递。 |

这个限制是诚实结论：如果某个平台无法可靠建立带外通道，就不能用可伪造的 HTTP 头伪装成鉴权。

### 2.5 残余风险

- 同一操作系统用户下的恶意程序若具备进程内存读取/调试权限，仍可能提取 token；这不属于 HTTP 伪造，但属于本机威胁模型的剩余部分。
- 管理接口没有多用户账户体系，仍假设“一个本机用户”。
- 桌面桥 token 只在已加载页面可调用；若页面被替换为不受信任内容，token 可能被读取。当前页面来自本机打包静态资源，未开放任意导航。
- Web 端未实现安全 token 交付，因此不声称 Web 端 AI 可用。

## 3. C2.2 数据模型

新增两张**纯增量**表，不修改任何已有列：

### v2_conversations

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | String(64) PK | 随机 hex |
| `title` | String(200) | 默认“新对话”，可重命名 |
| `provider_id` | String(64) nullable | 绑定的 Provider |
| `model` | String(200) | 会话级模型覆盖；空串表示用 Provider 默认 |
| `created_at` / `updated_at` | String(40) | ISO UTC 毫秒 Z |
| `archived_at` | String(40) nullable | 归档时间；列表默认过滤 |
| `revision` | Integer | 乐观并发版本 |
| `extra_json` | Text | 当前存 `system_prompt`，保留扩展空间 |

### v2_messages

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | String(64) PK | 随机 hex |
| `conversation_id` | String(64) FK | `ON DELETE CASCADE`，有索引 |
| `role` | String(16) | user / assistant / system |
| `content` | Text | 流式过程中持续更新 |
| `status` | String(16) | pending / streaming / complete / stopped / error |
| `sequence` | Integer | 会话内递增顺序 |
| `client_id` | String(64) nullable | 客户端幂等键 |
| `error_code` | String(64) nullable | 失败原因 |
| `created_at` / `updated_at` | String(40) | ISO UTC 毫秒 Z |
| `revision` | Integer | 消息版本 |

并发与一致性：

- 每个会话一个进程内 `threading.Lock`，同一会话同时只允许一个生成；第二个请求返回 409 `conversation_busy`。
- 消息追加使用 `MAX(sequence)+1`，单进程锁下不重复。
- `client_message_id` 幂等：同一会话重复提交同一 ID 不会重复调用模型，也不会重复插入消息。
- 崩溃恢复：读取历史时，超过 120 秒仍是 pending/streaming 的消息标记为 `error` / `generation_interrupted`，避免永远“生成中”。
- 删除会话同时删除消息；不触碰笔记、标签、收藏、回收站。
- 现有 V2 表与旧 `frontend_state` / `notes` 完全不变。

### 迁移方案

C2 **没有执行真实迁移**。表是 additive：

1. `create_v2_db()` 的 `Base.metadata.create_all` 会为已迁移的 V2 库补建两张新表。
2. 不需要 `ALTER TABLE`、不需要重写旧表、不需要删除 `frontend_state`。
3. 真实库迁移仍需单独授权；迁移前必须备份、在副本演练、验证回滚。
4. `/api/v2/status` 新增只读 `chat_schema_ready` 字段；旧库仍显示 `legacy`，不改变既有四态优先级。

## 4. C2.4 API

统一前缀 `/api/v2/ai`，全部要求 Capability Token。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/conversations?page=&page_size=&include_archived=` | 会话列表，按 updated_at 倒序 |
| POST | `/conversations` | 创建会话，201 |
| GET | `/conversations/{id}?page=&page_size=` | 会话详情 + 分页消息 |
| PATCH | `/conversations/{id}` | 重命名、换模型、换 Provider、改 system prompt、归档；支持 revision |
| DELETE | `/conversations/{id}` | 删除会话及消息，204 |
| GET | `/conversations/{id}/messages` | 消息历史，分页 |
| POST | `/conversations/{id}/messages` | 发送消息；`stream=true` 返回 SSE |
| POST | `/conversations/{id}/messages/{message_id}/regenerate` | 重新生成指定 assistant 消息 |
| POST | `/conversations/{id}/stop` | 停止当前生成，可带 message_id |
| POST | `/conversations/{id}/messages/{message_id}/stop` | 停止指定消息 |
| POST | `/chat`（C1） | 无状态单次对话，保留兼容 |

错误结构统一为：

```json
{"error":{"code":"conversation_busy","message":"...","provider_id":null,"retryable":true,"details":{}}}
```

常见错误：401 鉴权、403 跨站/Host、404 会话/消息不存在、409 归档/忙/版本冲突、422 参数、429 并发槽满、502 上游响应异常、503 Provider 不可用/未迁移、504 超时。

## 5. C2.3 对话引擎与流式

### 上下文

- 只取当前会话、当前 assistant 消息之前的历史。
- 只包含 user/assistant 且状态 complete/stopped、内容非空的消息。
- 上限 30 条、24,000 字符（含 system prompt 预算）。
- 若 system prompt 很长，最新一条消息会截断到剩余预算，绝不超出硬上限。
- 不自动读取或上传任何笔记、附件、标签或设置。

### 流式协议

`stream=true` 返回 `text/event-stream`，每行 `data: {json}`：

```
{"type":"start","conversation_id":"...","user_message":{...},"assistant_message":{...}}
{"type":"delta","message_id":"...","text":"..."}
{"type":"done","reply":{...}}
{"type":"stopped","message":{...}}
{"type":"error","error":{...},"message":{...},"retryable":true}
```

- Provider 协议只在 `app/v2/ai/adapters.py` 中实现；对话引擎只消费统一 `StreamDelta`。
- 传输层保持 DNS pinning、禁止重定向、响应字节上限、超时。
- 用户停止：设置取消事件，引擎停止读取并把消息置为 stopped；Provider 的连接由适配器关闭。
- 重新生成：复用同一条 assistant 消息，清空内容、置 pending，重新调用；不新增重复消息。
- 断网/Provider 异常：消息置 `error` 并保存已生成的部分内容，客户端可重试/重新生成。
- 模型切换：会话级 `model` 在下一轮生效；Provider 级默认模型仍由 C1 管理。
- 生成槽位：全进程最多 4 个并发 Provider 调用，超出返回 429。

### 已知限制

- 进程内锁只能覆盖单后端进程；多进程/多实例同时写同一 SQLite 文件没有跨进程会话锁。当前桌面/自带后端是单进程。
- 客户端中止（关闭 SSE 连接）依赖生成器收到 `GeneratorExit`；服务进程崩溃时由 120 秒陈旧恢复兜底。
- Provider 不支持原生取消时，停止可能等到下一次读取或超时；不会把后续内容写入消息。
- 未实现 Web 端安全 token 交付（见 2.4），聊天 UI 未在 C2 实现。
- 未对真实收费 API 做集成测试；全部测试使用 MockTransport。

## 6. 安全与数据保护

- 不修改真实用户数据库；不删除笔记/附件；不执行真实迁移。
- 不把 API Key、Capability Token 写入聊天记录、日志、响应、URL、Git。
- C1 的密钥托管、SSRF、DNS pinning、错误脱敏继续生效；C2 不复制 Provider 协议。
- 请求体上限、并发上限、上下文长度上限、响应长度上限均保留。
- 旧 `/api/state`、`/notes`、`/api/v2`、C1 Provider 接口未删除；新增鉴权只作用于 `/api/v2/ai`。
- 移动端契约不包含 `key_ref` / API Key；只有 `has_key` 布尔值。

## 7. 测试与验证

- Python 全量：见 `docs/v2/25-phase-c2-report.md`。
- 对话专项：21 项，覆盖 18 项要求 + 幂等流 + 长 system prompt + 崩溃恢复。
- 移动端：`contract.test.ts` 6 项通过；`tsc --noEmit` 通过。
- 真实库 SHA256 在 C2 实现前后保持一致。
