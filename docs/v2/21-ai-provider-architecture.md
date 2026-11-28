# C1 统一 AI Provider 架构

状态：C1 已实现并等待验收；未进入 C2，未实现聊天 UI、人格、RAG、语音或附件送入模型。

## 1. 目标与边界

C1 只解决“统一 Provider 抽象、配置、密钥与 API 边界”。它不改变旧 /api/state、旧 /notes 和现有前端 DataPort，也不修改真实用户数据库。

- 桌面端：支持本机 Ollama 与任意 OpenAI 兼容在线 API。
- Web：与桌面端相同的在线 API；Ollama 可用，但只应连接本机或用户明确配置的地址。
- 移动端：只允许在线 API。请求头 X-Hephaestus-Platform: mobile 时，Ollama 的创建和使用都会被拒绝。
- 所有模型调用必须由用户显式发起；C1 不会自动把笔记、标签、附件或任何私人内容发给外部模型。

## 2. 分层

1. 契约层 app/v2/contracts.py：Provider 配置、模型、连接测试、聊天、统一错误。
2. 数据层 app/v2/dataport.py：只保存配置与 key_ref，不保存明文密钥；enabled、is_default、params 存入既有 extra_json，不需要改表。
3. 服务层 app/v2/ai/service.py：创建/更新/删除配置、默认模型、密钥生命周期、平台限制、调用编排。
4. 适配器层 app/v2/ai/adapters.py：把统一请求翻译成 Ollama 或 OpenAI Chat Completions，并把所有上游错误翻译为统一错误。
5. 传输层 app/v2/ai/transport.py：urllib、禁用代理与重定向、超时、响应大小上限。
6. 安全层 app/v2/ai/security.py 与 app/v2/ai/secrets.py：Base URL/SSRF 校验、日志脱敏、系统密钥存储。
7. HTTP 层 app/v2/ai/api.py：/api/v2/ai/*，只允许本机访问。

provider-specific 的路径、字段和错误文本不出现在业务层或路由层。

## 3. Provider 接口

服务层对上层提供：

- list_models(provider_id)：可用模型列表。
- test_connection(provider_id)：连接测试，返回模型数量和耗时。
- chat(provider_id, messages, system_prompt)：文本聊天，支持系统提示、多轮消息、超时和统一错误。

适配器必须实现 list_models 与 chat。连接测试复用模型列表接口，不发送测试聊天内容，避免产生不必要的模型调用。

### Ollama

- 默认 Base URL：http://127.0.0.1:11434。
- GET /api/tags 列出已安装模型；POST /api/chat 使用 stream=false。
- 调用前先检查模型是否已安装；未安装返回 model_not_found，并附带可用模型。
- 连接失败时返回 provider_unavailable，提示“请确认 Ollama 已启动”。

### OpenAI 兼容

- 用户可配置 Base URL、API Key、模型名；不硬编码任何厂商。
- GET {root}/models；POST {root}/chat/completions。
- 支持标准 Authorization: Bearer；请求体使用 messages、temperature、max_tokens、top_p、stream=false。
- 自动去掉用户误填的 /chat/completions 或 /models 后缀。
- 解析 choices[0].message.content、finish_reason 和 usage；不假设所有厂商字段完全一致。

当前支持 kind：ollama、openai、deepseek、qwen、custom。anthropic、gemini 保留在公共枚举中，但 C1 明确返回 unsupported_provider，避免伪装成完全兼容。

## 4. 配置模型

AIProviderConfigCreate：kind、label、base_url、model、api_key、enabled、is_default、params；key_ref 仅为旧 F2 客户端兼容字段，服务端忽略。

AIProviderConfigUpdate：所有字段可选；支持 api_key 轮换、clear_api_key、启用/禁用、设为默认、修改参数。api_key 与 clear_api_key 不能同时出现。

AIProviderParams：temperature 0..2、max_tokens 1..8192、top_p 0..1、timeout_seconds 1..120。

读取契约只返回 has_key，不返回 key_ref、api_key 或任何密钥文本。

默认模型规则：

- 任意时刻最多一个 enabled 的默认 Provider。
- 创建时如果已有默认，保留原默认；没有默认且新配置 enabled，则新配置成为默认。
- 删除或禁用当前默认后，自动选择第一个 enabled 的 Provider。
- is_default 与 v2_settings.default_model 同步；禁用配置不能设为默认。

## 5. 密钥存储

数据库只保存随机 key_ref（provider-<uuid>）。密钥按平台放入：

- Windows：DPAPI 加密的 ai-secrets.json，默认在 %LOCALAPPDATA%/Hephaestus/secrets/。
- macOS：Keychain。
- Linux：keyring，或 secret-tool（密钥只经 stdin）。
- 测试：InMemorySecretStore，仅进程内。

文件密钥存储使用跨进程锁（同目录 .lock）、fsync 和原子替换，权限 0600，只保存 DPAPI 密文；密钥存储损坏时返回 secret_store_unavailable，不读取或回退明文。跨进程锁防止两个进程各自读改写同一 JSON 时丢失 Key。

以下位置不会出现明文密钥：SQLite、API 读取响应、异常日志、测试报告、Git 文件、FastAPI 422 校验错误。错误详情中的上游响应会先经过 redact_secret；422 处理器会把请求体中的 api_key/key_ref 等字段替换为 [REDACTED]。

## 6. 网络安全

validate_base_url 在创建和每次使用前执行：

- 只允许 http/https；拒绝空值、超长、控制字符、userinfo、query、fragment、非法端口。
- 解析 DNS，拒绝 unspecified、multicast、link-local、reserved、CGNAT 100.64.0.0/10，以及默认情况下的 private 地址；先归一化 IPv4-mapped IPv6。
- Ollama 允许本机/私有地址；在线 API 默认只允许 https，回环地址例外。
- 需要连接内网在线 API 时，必须显式设置 HEPHAESTUS_AI_ALLOW_PRIVATE_URLS=1，属于管理员级选择。
- resolve_base_url 返回解析后的精确 IP；传输层只连接这些固定地址，禁用系统代理与重定向，限制响应体大小，默认超时取自 Provider 参数。
- AI 请求体上限 2 MB；聊天最多 50 条、每条 20,000 字符；单进程最多 4 个 Provider 调用；超时 1..120 秒。

AI 路由通过 require_local_client 限制为 127.*、::1、localhost 或 testclient；同时 AISecurityMiddleware 校验 Host，并在存在时校验 Origin/Referer，阻止浏览器 DNS rebinding 和跨站请求。远程部署必须显式设置 HEPHAESTUS_AI_ALLOW_REMOTE=1，且不应把该接口直接暴露到公网。

## 7. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v2/ai/providers | 配置列表，只返回 has_key |
| POST | /api/v2/ai/providers | 创建配置，201 |
| PATCH | /api/v2/ai/providers/{id} | 局部更新、轮换/清除密钥 |
| DELETE | /api/v2/ai/providers/{id} | 删除配置和对应密钥，204 |
| GET | /api/v2/ai/providers/{id}/models | 模型列表 |
| POST | /api/v2/ai/providers/{id}/test | 连接测试 |
| POST | /api/v2/ai/chat | 显式文本聊天 |

统一错误结构：

{"error": {"code": "...", "message": "...", "provider_id": "...", "retryable": false, "details": {}}}

主要错误码：provider_not_found、provider_disabled、unsupported_provider、mobile_ollama_forbidden、invalid_base_url、missing_api_key、secret_store_unavailable、auth_failed、model_not_found、rate_limited、timeout、provider_unavailable、invalid_provider_response、response_too_large。

## 8. 兼容性

- 旧 /api/state、旧 /notes、旧 PUT/q 参数和 B2 前端 DataPort 不变。
- 原 /api/v2/ai/providers 的 GET/POST/DELETE 由新子路由承接，路径不变；读取对象新增 enabled/is_default/params，旧客户端可忽略。
- 配置存于既有 v2_ai_providers.extra_json，不新增列、不要求数据库迁移。
- 未迁移的旧库仍走 /api/state；调用 AI 接口时如果没有 V2 表，返回 503，并明确提示先显式迁移。

## 9. 测试与限制

- tests/test_v2_ai.py 共 16 项，覆盖 Ollama 正常/不可用、OpenAI 兼容聊天、缺少密钥、密钥不回传、鉴权失败、超时、非法 Base URL、模型不存在、多 Provider 隔离、删除后的默认模型、移动端禁止 Ollama、日志脱敏、旧 API 兼容、重启恢复、密钥轮换/清除。
- tests/test_v2_ai_security.py 共 25 项，覆盖 Host/Origin/DNS rebinding、CGNAT/IPv4-mapped SSRF、DNS pinning、无重定向、响应上限、跨进程密钥锁、422 密钥回显、key_ref 注入、并发上限、请求体上限，以及非 Windows 无 DPAPI 时失败关闭。文件锁/原子写测试在非 Windows 使用注入的测试保护器，不改变生产 DPAPI 默认。
- 测试全部使用 FakeTransport，不调用真实付费 API。
- 移动端 TypeScript 契约与 DataPort 已加入 enabled/is_default/params，并禁止在移动端创建 Ollama；不引入 Ollama 运行时依赖。
- C1 未实现流式响应、聊天 UI、人格、RAG、语音、附件送入模型。
- 未在真实移动端 Capacitor 壳中运行；接口与 JSON 契约已为 G 阶段预留。
- 未在无 keyring/secret-tool 的 Linux 桌面实测；默认会回退到 DPAPI/Keychain/keyring/secret-tool 中可用的实现，否则明确报错。

## 10. 下一步

C1 验收通过后再进入 C2。C2 才处理助手人格、对话 UI、上下文组织与用户显式选择内容的模型调用。
