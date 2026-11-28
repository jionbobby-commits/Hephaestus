# C1.1 AI Provider 安全复核报告

状态：安全复核、修复、测试与文档已完成，等待验收。按任务要求在 C1.1 结束后暂停，未进入 C2。

审计对象：feat/v2-cross-platform 上的 C1 AI Provider 实现，重点是 app/v2/ai/*、app/v2/contracts.py、app/v2/dataport.py、app/main.py 与相关测试。

安全边界：本报告只使用 Mock/本地隔离服务；没有使用真实 API Key，没有调用收费接口，没有访问真实外部服务，没有修改真实用户数据库，没有执行数据迁移，没有修改 main，没有强推或重写历史。

## 1. 结论

没有发现 Critical 级问题。确认并修复 5 个 High 级问题、3 个 Medium 级问题；保留 2 个 Medium 级残余风险和 6 个 Low 级风险或测试缺口。

最重要的修复是三条边界：

1. AI API 不再只凭 socket peer 判断本机来源，而是同时校验 Host、Origin/Referer；浏览器 DNS rebinding 页面不能再直接读取配置或发起聊天。
2. Base URL 校验返回解析后的精确 IP，传输层连接这些固定地址，禁用代理和重定向；校验与实际连接之间不再重新解析 DNS。
3. API Key 不再通过 FastAPI 422 错误体、上游错误详情或日志回显；密钥文件增加跨进程锁、fsync 和原子替换。

旧 /api/state、旧 /notes、B2 前端 DataPort 和 C1 的 Provider 接口路径保持不变；没有新增数据库列或迁移步骤。

## 2. 风险总表

| ID | 级别 | 问题 | 状态 | 主要位置 |
|---|---|---|---|---|
| H-1 | High | Host/Origin 未校验，浏览器 DNS rebinding 可访问 AI API | 已修复 | app/v2/ai/middleware.py:206 |
| H-2 | High | SSRF 允许 CGNAT 100.64.0.0/10，IPv4-mapped IPv6 未归一化 | 已修复 | app/v2/ai/security.py:57 |
| H-3 | High | 校验与请求之间重新解析 DNS，存在 rebinding 时间窗 | 已修复 | app/v2/ai/security.py:109、transport.py:124 |
| H-4 | High | redact_secret 捕获组错误，独立 sk- Key 原样保留；JSON/Basic/query 形状漏检 | 已修复 | app/v2/ai/security.py:35 |
| H-5 | High | FastAPI 422 响应回显整个请求体，包含 api_key | 已修复 | app/v2/ai/validation.py:53、app/main.py:28 |
| M-1 | Medium | FileSecretStore 仅进程内锁，多进程并发读改写会丢 Key | 已修复 | app/v2/ai/secrets.py:125、189 |
| M-2 | Medium | 调用方可通过 key_ref 绑定任意密钥定位符 | 已修复 | app/v2/ai/service.py:67 |
| M-3 | Medium | 聊天请求缺少统一请求体/并发上限 | 已缓解/修复 | app/v2/ai/middleware.py:206、service.py:269 |
| M-4 | Medium | AI 配置接口没有用户鉴权，只有本机来源限制 | 残余风险 | app/v2/ai/api.py:52 |
| M-5 | Medium | macOS Keychain 通过 argv 传递密钥，可能被进程列表看到 | 残余风险 | app/v2/ai/secrets.py 的 MacKeychainStore |
| L-1 | Low | X-Hephaestus-Platform 由客户端控制，可伪造 desktop 绕过 Ollama 功能限制 | 残余风险 | app/v2/ai/api.py |
| L-2 | Low | Ollama Base URL 可指向本机其他端口，存在受限的 confused-deputy 风险 | 残余风险 | app/v2/ai/security.py、adapters.py |
| L-3 | Low | Windows 密钥文件沿用 LocalAppData 继承 ACL，没有显式收紧 ACL | 可接受 | app/v2/ai/secrets.py |
| L-4 | Low | Origin 比较 host/port，不比较 scheme | 可接受 | app/v2/ai/middleware.py:135 |
| L-5 | Low | 请求体读取没有应用层超时，慢速本机客户端可占用连接 | 残余风险 | app/v2/ai/middleware.py:178 |
| L-6 | Low | 未对 pinned HTTPS 做真实 TLS 集成测试 | 测试缺口 | tests/test_v2_ai_security.py |

## 3. 重点问题与证据

### H-1 Host/Origin 与 DNS rebinding

旧边界只看 request.client.host。浏览器把 evil.example 解析到 127.0.0.1 后，脚本仍以 evil.example 为同源，可以读取响应；socket peer 却是 127.0.0.1。仅检查 peer 不能阻止这种攻击。

修复在 AISecurityMiddleware.__call__：

- Host 必须恰好一个，解析后只允许 127.0.0.1、localhost、::1；额外主机只能通过 HEPHAESTUS_AI_ALLOWED_HOSTS 显式配置。
- testserver 只在 TestClient 的 testclient peer 下允许。
- Origin 必须与请求 host/port 一致；Origin: null、跨源、带 userinfo/query/fragment 的值拒绝。
- 没有 Origin 时才检查 Referer，允许路径但要求同源。
- 拒绝 Content-Encoding 不是 identity 的请求；响应加 Cache-Control: no-store 和 X-Content-Type-Options: nosniff。

测试：test_host_header_rebinding_is_rejected、test_x_forwarded_host_does_not_override_host、test_cross_origin_and_null_origin_are_rejected、test_same_origin_and_referer_are_allowed、test_allowed_hosts_env_matches_optional_port。

### H-2 SSRF 地址分类

旧 _ip_allowed 只用 is_private。Python 对 100.64.0.0/10（CGNAT）的 is_private 为 False、is_reserved 也为 False，因此被放行；IPv4-mapped IPv6 也需要先归一化，否则 ::ffff:169.254.169.254 可能绕过 IPv4 分类。

修复后先取 ipv4_mapped，再拒绝 unspecified、multicast、link_local、reserved；is_global 放行；其余只按 allow_private 决定。在线 API 默认不允许私网/CGNAT；Ollama 允许本机/私网，但仍拒绝 link-local 和 metadata。

测试：test_cgnat_and_ipv4_mapped_metadata_are_rejected、test_resolver_private_answer_is_rejected。

### H-3 DNS pinning

旧实现只校验 URL，urllib 在发送时重新解析域名。攻击者控制的 DNS 可以在校验后把域名改到私网地址，形成 TOCTOU。

修复后 resolve_base_url(kind, value, platform, resolver) 返回规范化 URL 和解析后的精确 IP 列表；AIProviderService._resolve_for_use 把它放进 ResolvedProvider.resolved_ips；PinnedHttpTransport 用 socket.create_connection 连接该 IP，HTTPS 仍用原始 host 做 SNI 和证书校验；禁用代理和重定向；连接失败只在尚未发送请求时尝试下一个 IP。

测试：test_resolve_base_url_returns_exact_pinned_addresses、test_transport_connects_to_pinned_ip_and_keeps_original_host、test_transport_does_not_follow_redirects、test_transport_response_cap、test_transport_timeout、test_transport_rejects_empty_validated_addresses。

### H-4 脱敏规则

旧 redact_secret 的独立 sk- 正则含捕获组，lambda 把 group(1) 拼回结果，导致 Key 本身保留；同时缺少 JSON 字段、Basic auth、URL query 等形状。

修复后覆盖 Authorization Bearer/Basic/Token、x-api-key/x-goog-api-key/api-key、JSON/form 的 api_key/access_token/refresh_token/token/secret、URL query key/token/access_token、独立 sk-；独立 sk- 使用无捕获组正则，整个匹配替换为 [REDACTED]。上游错误详情在 adapters.py:121 和 adapters.py:135 进入响应前再次脱敏。

测试：test_secret_redaction_covers_common_shapes、test_api_key_never_returned_and_echoed_key_is_redacted。

### H-5 422 校验错误回显密钥

复现：创建一个 Provider 后发送

PATCH /api/v2/ai/providers/{id}
{"api_key":"sk-SUPERSECRET123456789","clear_api_key":true}

模型级校验器拒绝 api_key 与 clear_api_key 同时使用，FastAPI 默认 422 的 input 字段是完整请求体，于是 Key 出现在错误响应中。这是确认的 API Key 泄露，不是理论风险。

修复：新增 app/v2/ai/validation.py，递归把已知密钥字段替换为 [REDACTED]；loc、msg、type 保留，ctx 也清理；app/main.py:28 注册 RequestValidationError 处理器。普通校验错误仍返回 422 和可用定位信息。

测试：test_validation_errors_do_not_echo_api_key（断言 422、响应不含 Key、包含 [REDACTED]）。

### M-1 密钥文件多进程并发

旧 FileSecretStore 只有每个实例的 threading.Lock。两个进程可以同时读取同一 JSON，各自加入自己的 Key，后写者覆盖前者。

修复：每个路径对应一个 .lock 文件；Windows 用 msvcrt.locking(LK_NBLCK)，POSIX 用 fcntl.flock(LOCK_EX|LOCK_NB)，带默认 10 秒超时；实例线程锁与进程锁同时持有；写入临时文件后 fsync、chmod 0600、os.replace；POSIX 再 fsync 父目录；replace 失败保留旧文件并删除临时文件。

测试：test_secret_store_separate_instances_do_not_lose_keys（4 实例、24 线程）、test_secret_store_separate_processes_do_not_lose_keys（3 进程）、test_atomic_replace_failure_keeps_previous_secret、test_secret_file_is_ciphertext_and_restricted。

### M-2 key_ref 注入

旧 create_provider 接受调用方传入的 key_ref，DataPort 在 key_ref 为空时还会使用 legacy_ref。调用方可以把 Provider 绑定到任意密钥定位符，虽然不能直接读 Key，但能改变服务端使用哪个密钥。

修复：service.create_provider 先 model_copy 把 key_ref 置空，再生成新的随机 key_ref；旧客户端字段仍可解析，但不会被信任。

测试：test_client_supplied_key_ref_cannot_bind_arbitrary_secret。

### M-3 请求资源限制

现有边界：

- 请求体最大 2,000,000 字节；Content-Length 预检，分块读取也累计限制；压缩请求体拒绝。
- 聊天 messages 1..50，每条 content 1..20,000 字符，system_prompt 最多 20,000 字符。
- 单进程同时最多 4 个 Provider 调用；超限返回 429 too_many_requests。
- Provider 超时 1..120 秒；上游响应最多 2 MB，错误详情最多保留 20,000 字符。

测试：test_body_limit_and_content_encoding、test_ai_call_slot_limit。

## 4. 未修复的残余风险

### M-4 没有用户鉴权

/api/v2/ai/* 的边界是“本机 + Host/Origin”，不是用户鉴权。同用户的本机进程本来就能读 DPAPI；多用户机器上的其他用户可能访问 loopback 端口，使用已配置的 Provider 发起付费调用，但不能读出 Key。浏览器跨站路径已被 Host/Origin 阻断。

建议 C2 引入每次启动生成的本地 capability token（只注入桌面 WebView/受信前端），或 mTLS/命名管道；不要在没有 UI 配合时临时加半套鉴权。

### M-5 macOS Keychain argv

MacKeychainStore 使用 security add-generic-password ... -w <secret>，同机进程列表可能看到参数。当前没有 macOS 主机，未修改；建议改用 stdin、security 的交互输入或 keyring 后端。

### 低风险

- X-Hephaestus-Platform 只是功能开关，不是安全边界；移动端可伪造 desktop，但 Ollama 仍需本机可达地址。
- Ollama 可指向本机其他端口；适配器只会请求 /api/tags 和 /api/chat，link-local/metadata 已拒绝，但仍可能触达本机无鉴权服务。调用必须由用户显式配置和显式聊天触发。
- Windows 密钥文件 ACL 继承自 %LOCALAPPDATA%/Hephaestus，实测只有 SYSTEM、Administrators、当前用户；文件内容是 DPAPI 密文。没有额外 ACL，管理员/SYSTEM 仍可读密文。
- Origin 比较不校验 scheme；正常直连 HTTP 下不可利用，文档记录。
- 请求体读取没有应用层超时；本机慢速客户端可占用连接。未加是因为 uvicorn 没有统一的体读取超时，单加应用层超时不能覆盖慢 header，且会增加 ASGI 取消复杂度。
- 未做 pinned HTTPS 的真实 TLS 集成测试；逻辑使用原始 host 作为 server_hostname，但没有本地 TLS 服务测试。

## 5. 8 项审计范围对照

| 审计项 | 结论 | 证据 |
|---|---|---|
| SSRF 与 DNS Rebinding | H-2/H-3 已修复 | 地址分类、pinning、无重定向、无代理测试 |
| Host/Origin/Referer/本机限制 | H-1 已修复 | 403 回归测试、Allowed Hosts 测试 |
| Key 加密/权限/原子写/异常恢复 | M-1 已修复；DPAPI 正常 | 密文、0600、replace 失败、进程并发测试 |
| 多进程密钥文件并发 | M-1 已修复 | 3 进程测试 |
| 请求大小/消息数/并发/超时 | M-3 已修复/缓解 | 413、429、50x20k、1..120s、2MB 响应 |
| Ollama 与本机敏感服务 | L-2 残余 | link-local/metadata 拒绝；本机其他端口仍可能 |
| 日志/异常/响应 Key 泄露 | H-4/H-5 已修复 | 脱敏测试、422 回归、日志只记录 id/kind/model |
| 配置接口未授权访问 | M-4 残余 | Host/Origin 阻断浏览器；无用户鉴权 |

## 6. 测试结果

安全测试模块：

- 命令：.venv/Scripts/python.exe -m pytest -q tests/test_v2_ai_security.py
- Windows 结果：24 passed, 1 skipped, 1 warning in 4.44s，EXIT 0；跳过项是 Windows 上不运行的“无 DPAPI 时必须失败关闭”测试。
- Linux CI（待 GitHub Actions 验证）：同一模块 25 项均可执行；安全文件测试在非 Windows 上使用注入的测试保护器验证锁/原子写，生产默认保护器仍为 DPAPI 且无 DPAPI 时失败关闭。
- warning 为既有 StarletteDeprecationWarning：httpx 与 starlette.testclient 弃用。

全量 Python 测试：

- 命令：.venv/Scripts/python.exe -m pytest -q
- Windows 结果：128 passed, 1 skipped, 1 warning in 186.68s，EXIT 0。
- 组成：原有 60 项 + B1 14 + B2 10 + B3 4 + C1 16 + C1.1 25；Windows 跳过 1 项，Linux CI 预计 122 passed + 7 skipped（待验证），此前 4 项安全文件测试因 DPAPI 失败的问题已修复。
- 日志：C:/Users/Bobby-Zhang/AppData/Local/Temp/heph_c11_pytest_portable.txt

移动端：

- 命令：bundled Node 24.21.0 --experimental-strip-types --experimental-sqlite --test tests/contract.test.ts
- 结果：5 passed, 0 failed，EXIT 0。
- TypeScript：node node_modules/typescript/lib/tsc.js --noEmit，EXIT 0。

补充检查：

- .venv/Scripts/python.exe -m compileall -q app/v2 app/main.py：EXIT 0。
- .venv/Scripts/python.exe -c "import app.main"：IMPORT_OK。
- git diff --check：EXIT 0。
- 真实库 SHA256 在复核前后保持一致；没有写真实库。

## 7. 改动文件

安全实现：

- app/main.py：注册 RequestValidationError 脱敏处理器，注册 AISecurityMiddleware。
- app/v2/ai/middleware.py：新增 Host/Origin/Referer、请求体上限、编码拒绝、安全响应头。
- app/v2/ai/security.py：地址分类、IPv4-mapped 归一化、resolve_base_url、脱敏规则。
- app/v2/ai/transport.py：PinnedHttpTransport，连接固定 IP，禁用代理/重定向，响应上限。
- app/v2/ai/secrets.py：FileSecretStore 跨进程锁、fsync、原子替换、目录权限。
- app/v2/ai/service.py：剥离调用方 key_ref、并发信号量、使用 pinned 地址。
- app/v2/ai/adapters.py：ResolvedProvider.resolved_ips，错误详情脱敏。
- app/v2/ai/validation.py：新增 422 错误脱敏。
- tests/test_v2_ai.py：FakeTransport 接受 resolved_ips。
- tests/test_v2_ai_security.py：新增 25 项安全回归测试，其中非 Windows 使用测试保护器验证文件锁与原子写，并验证无 DPAPI 时失败关闭。

文档：

- docs/v2/23-ai-security-audit.md（本文件）。
- docs/v2/21-ai-provider-architecture.md、docs/v2/README.md 更新。
- docs/v2/22-phase-c1-report.md 保留为 C1 历史报告；C1.1 的安全结论以本文件为准。

## 8. 兼容性与数据

- 真实库：C:/Users/Bobby-Zhang/AppData/Local/Hephaestus/hephaestus.db，16384 bytes，SHA256 e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4，测试前后一致。
- 未执行迁移、未写 frontend_state、未创建/删除 v2_* 表。
- 旧 /api/state、/notes、PUT/q 参数和 B2 DataPort 未改。
- Provider 配置仍存于 v2_ai_providers.extra_json，不新增列，不需要迁移。
- 旧客户端可继续使用 GET/POST/DELETE /api/v2/ai/providers；新增 PATCH、models、test、chat 不改变旧路径。

## 9. Git

- 分支：feat/v2-cross-platform
- C1.1 实现提交：2ae48c7bc0d3169e2f4c8a01764842dbfa4560c3（用户已提交并推送）
- 父提交：24ffd23c11dce6b3909923662430ddf6a588e724
- 可移植性修复提交：32431dda3d3d5c22d6a56edf92518e8a3700d9a0（父提交 be0d429c7e0fb76037652cc13fd11f7bf680a1bf）；仅调整密钥存储测试的可注入保护器并新增失败关闭测试，生产 DPAPI 默认未改。
- 本报告与 422 修复提交在本文档完成后创建；不推送、不合并 main。
