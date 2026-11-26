# C1 阶段报告：统一 AI Provider 架构

状态：实现、测试与本地提交已完成，等待验收。按任务要求在 C1 结束后暂停，未进入 C2。

> C1.1 安全复核已修复本文档第 6、11 节列出的 Host/Origin、DNS rebinding、CGNAT SSRF、脱敏和密钥并发问题；当前安全结论以 [23-ai-security-audit.md](23-ai-security-audit.md) 为准。

## 1. 结论

C1 已建立与 Provider 无关的后端抽象：统一配置、模型列表、连接测试、文本聊天、超时和错误结构；Ollama 与 OpenAI 兼容 API 各有独立适配器；密钥只存系统密钥库；/api/v2/ai/* 有本机访问限制、Base URL/SSRF 校验和统一错误；旧 /api/state、旧 /notes、B2 前端 DataPort 保持兼容。

本次没有执行真实数据库迁移，没有修改真实用户库，没有调用真实付费 API，没有改前端界面，没有合并或推送 main。

## 2. 架构

分层如下：

1. 契约层 app/v2/contracts.py：AIProviderConfigCreate/Update/Read、AIProviderParams、AIModelList、AIConnectionTest、AIChatRequest/Result、AIErrorResponse。
2. 配置数据层 app/v2/dataport.py：配置 CRUD、默认 Provider、设置同步；enabled/is_default/params 写入既有 extra_json，不新增列。
3. 服务层 app/v2/ai/service.py：校验、密钥生命周期、平台限制、默认切换、模型/测试/聊天编排。
4. 适配器层 app/v2/ai/adapters.py：Ollama 与 OpenAI Chat Completions；提供方路径、字段和错误映射只在此层。
5. 传输层 app/v2/ai/transport.py：只使用 urllib，禁用系统代理与重定向，限制响应字节数，统一超时。
6. 安全层 app/v2/ai/security.py 与 secrets.py：URL/SSRF、日志脱敏、DPAPI/Keychain/keyring/secret-tool/InMemory 密钥存储。
7. HTTP 层 app/v2/ai/api.py：/api/v2/ai/*；子路由挂到现有 /api/v2，公开前缀不变。

## 3. Provider 接口与适配器

统一能力：

- list_models(provider_id)：列模型。
- test_connection(provider_id)：连接测试，返回模型数量与耗时；不发送测试聊天。
- chat(provider_id, messages, system_prompt)：文本、多轮、系统提示、超时、统一错误。

Ollama：

- 默认 http://127.0.0.1:11434；GET /api/tags；POST /api/chat，stream=false。
- 调用前检查已安装模型；缺失时返回 model_not_found 和可用模型。
- Ollama 未启动返回 provider_unavailable，提示确认 Ollama 已启动。

OpenAI 兼容：

- 用户自定义 Base URL、API Key、模型名；GET /models、POST /chat/completions。
- 支持 openai、deepseek、qwen、custom 四种 kind，不硬编码单一厂商。
- 自动去掉误填的 /chat/completions 或 /models 后缀；解析 choices、finish_reason、usage。
- 不假设所有第三方服务完全兼容；上游错误按状态码映射，并在 details 中保留脱敏诊断。

anthropic、gemini 仍在公共枚举中，但 C1 明确返回 unsupported_provider，避免假装支持。

## 4. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v2/ai/providers | 配置列表，只返回 has_key |
| POST | /api/v2/ai/providers | 创建，201 |
| PATCH | /api/v2/ai/providers/{id} | 局部更新、密钥轮换/清除 |
| DELETE | /api/v2/ai/providers/{id} | 删除配置与密钥，204 |
| GET | /api/v2/ai/providers/{id}/models | 模型列表 |
| POST | /api/v2/ai/providers/{id}/test | 连接测试 |
| POST | /api/v2/ai/chat | 显式文本聊天 |

统一错误响应：

{"error": {"code": "timeout", "message": "...", "provider_id": "...", "retryable": true, "details": {}}}

AI 路由默认只允许 127.*、::1、localhost、testclient；远程部署必须显式设置 HEPHAESTUS_AI_ALLOW_REMOTE=1。X-Hephaestus-Platform 只接受 desktop、web、mobile；mobile 使用 Ollama 返回 403。

## 5. 配置与默认模型

AIProviderConfigCreate 字段：kind、label、base_url、model、api_key、enabled、is_default、params；key_ref 仅兼容旧客户端，服务端不接受调用方提供的密钥定位符。

AIProviderConfigUpdate 支持局部更新、api_key 轮换、clear_api_key、启用/禁用、默认切换、参数修改；api_key 与 clear_api_key 互斥。

参数：temperature 0..2、max_tokens 1..8192、top_p 0..1、timeout_seconds 1..120。

默认规则：

- 最多一个启用项为默认。
- 已有默认时不会被新配置抢占；只有显式 is_default=true 才切换。
- 删除或禁用当前默认后，自动选择第一个启用项。
- is_default 与 v2_settings.default_model 同步；禁用项不能设为默认。

## 6. 密钥与安全

- 数据库只存随机 key_ref（provider-<uuid>），不存明文 API Key。
- Windows：DPAPI 加密文件，默认 %LOCALAPPDATA%/Hephaestus/secrets/ai-secrets.json。
- macOS：Keychain；Linux：keyring 或 secret-tool；测试：InMemorySecretStore。
- 文件权限 0600，原子替换；文件损坏返回 secret_store_unavailable，不读取明文。
- API 读取只返回 has_key；错误、日志和响应中的 Authorization、x-api-key、api_key、sk- 前缀内容会脱敏。
- Base URL 只允许 http/https；拒绝 userinfo、query、fragment、控制字符、非法端口；拒绝 metadata/link-local/private 等地址（Ollama 例外）。在线 API 默认必须 https，回环地址例外。
- 传输层禁用代理和重定向；默认响应上限 2 MB。DNS rebinding 的检查-请求时间差是已知残余风险，已在文档记录。

## 7. 跨平台

- 桌面端：Ollama + 在线 API。
- Web：在线 API；Ollama 可用但只应指向本机/明确配置地址。
- 移动端：只允许在线 API；TypeScript DataPort 与后端双重拒绝 Ollama；不引入 Ollama 运行时依赖。
- 共享 JSON 契约已更新；Capacitor 原生 SQLite/HTTP 适配器属于阶段 G，本次未运行真实 Android/iOS 壳。

## 8. 改动文件

代码与契约：

- app/v2/contracts.py
- app/v2/dataport.py
- app/v2/api.py
- app/v2/ai/__init__.py、errors.py、security.py、transport.py、secrets.py、adapters.py、service.py、api.py
- contracts/v2/contract_fixture.json
- mobile/src/contracts.ts、mobile/src/dataport.ts

测试：

- tests/test_v2_ai.py（新增 16 项）
- tests/test_v2_dataport.py（兼容 C1 契约后的旧断言）
- mobile/tests/contract.test.ts（AI 配置新字段与移动端 Ollama 拒绝）

文档：

- docs/v2/21-ai-provider-architecture.md
- docs/v2/06-data-contract.md、08-dataport-and-api.md、10-contract-tests.md、README.md
- docs/v2/22-phase-c1-report.md（本文件）

## 9. 测试结果

完整 Python 测试：

- 命令：.venv/Scripts/python.exe -m pytest -q
- 结果：104 passed, 1 warning in 176.77s，EXIT 0
- 唯一 warning：StarletteDeprecationWarning，提示 httpx 与 starlette.testclient 弃用；既有问题，与本阶段无关。
- 组成：60 项旧测试 + 14 项 B1 + 10 项 B2 + 4 项 B3 + 16 项 C1。

C1 的 16 项覆盖：

1. Ollama 正常连接与模型列表（FakeTransport）。
2. Ollama 不可用提示。
3. OpenAI 兼容聊天、usage 与鉴权头。
4. 缺少 API Key。
5. 查询 API 不返回密钥。
6. 鉴权失败映射。
7. 请求超时。
8. 非法 Base URL/内网地址拒绝。
9. Ollama 模型不存在。
10. 多 Provider 密钥隔离。
11. 删除 Provider 后默认模型。
12. 移动端禁止 Ollama。
13. 日志与错误脱敏。
14. 旧 /api/state 兼容。
15. 配置重启恢复。
16. API Key 轮换与清除。

移动端：

- 契约/DataPort 测试：5 passed，EXIT 0（便携 Node 22.14.0，node:sqlite）。
- TypeScript：tsc --noEmit，EXIT 0。

补充检查：

- DPAPI FileSecretStore 在本机临时路径完成 set/get/delete 往返，无明文落库。
- git diff --check：EXIT 0；app/v2 compileall：EXIT 0；from app.main import app：EXIT 0。

## 10. 数据与兼容性

- 真实库：%LOCALAPPDATA%/Hephaestus/hephaestus.db，16384 bytes，SHA256 e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4，测试前后一致。
- 未执行迁移，未写 frontend_state，未创建/删除 v2_* 表。
- 旧 /api/state、旧 /notes、旧 PUT/q 参数未改。
- /api/v2/ai/providers 原 GET/POST/DELETE 路径保持；读取对象新增 enabled/is_default/params，旧客户端可忽略。
- 没有新增数据库列；部署到已有 v2 表时不需要迁移。

## 11. 限制与风险

1. C1 只有后端与契约，没有聊天 UI、助手人格、RAG、语音、附件送入模型；这些属于 C2 及后续。
2. 只有非流式文本；流式响应未实现。
3. anthropic、gemini 未实现适配器，明确报 unsupported_provider。
4. 真实 OpenAI/DeepSeek/Qwen/Ollama 网络调用未执行；测试全部使用 FakeTransport，避免付费和外部依赖。
5. macOS Keychain、Linux keyring/secret-tool 未在本机实测；Windows DPAPI 已实测。
6. 移动端只验证 TypeScript 契约与本地 SQLite DataPort，未在 Capacitor/真机运行。
7. DNS 校验与实际连接之间存在 rebinding 时间窗；重定向已禁用，但不能完全消除该风险。
8. /api/v2/ai/* 依赖本机来源限制，不是多用户鉴权系统；远程开放需要显式环境变量并应由反向代理补认证。
9. 未做速率限制、并发配额、成本统计；C1 不自动发起付费调用，但用户显式聊天没有预算上限。

## 12. Git

- 分支：feat/v2-cross-platform
- 代码与文档提交：430f9a5781d94da7b36558a318d218332fe639c3
- 父提交：5f3e114f980d061a5a311c5de94be777ddc2109c
- 提交信息：feat(v2): add unified AI provider architecture
- 本次提交：22 files changed, 2305 insertions(+), 68 deletions(-)
- 未推送、未合并、未改 main；main 仍为用户的 8204583。
- 本报告单独提交，提交后工作区应为干净状态。

## 13. 验收请求

请验收 C1 的统一 Provider 接口、两类适配器、配置/密钥/默认模型、/api/v2/ai/*、SSRF/本机限制与 104 项测试。验收通过后再授权 C2；C2 才会进入助手人格、对话 UI 与用户显式选择上下文的模型调用。
