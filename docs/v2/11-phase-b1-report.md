# 阶段 B1 验收报告

日期：2026-11-23。分支：feat/v2-cross-platform。基线：main / 3e341a5。

## 1. 范围

按 2026-11-23 的 B1 授权，只完成数据架构：

- B1.1 统一数据契约
- B1.2 真实数据保护、独立副本迁移演练、完整性、回滚、幂等
- B1.3 Python + TypeScript DataPort
- B1.4 /api/v2 与旧接口兼容

未做：AI 调用、UI 改造、i18n 页面、附件上传、移动端 Capacitor 壳、安装包、真实库迁移、PR、合并、推送 main。

## 2. 验收清单

| 验收项 | 交付 | 结果 |
|---|---|---|
| 1. 统一数据契约文档 | docs/v2/06-data-contract.md | 完成 |
| 2. 数据库结构设计 | app/v2/models.py、docs/v2/07-schema-and-migration.md | 完成 |
| 3. DataPort 接口设计 | app/v2/dataport.py、mobile/src/dataport.ts、docs/v2/08-dataport-and-api.md | 完成 |
| 4. JSON 快照迁移方案 | app/v2/migrate.py、docs/v2/07 | 完成 |
| 5. 独立副本迁移演练报告 | docs/v2/09-migration-drill.md、data/b1-drill/drill.db | 完成 |
| 6. 数据完整性验证报告 | 09 报告；verify_against_snapshot ok=true，7 条笔记/4 标签 | 完成 |
| 7. 回滚测试结果 | 09 报告；restored.db 与备份 SHA256 一致 | 完成 |
| 8. 桌面端/移动端契约测试 | 14 Python + 5 Node；同一 fixture | 完成 |

## 3. 新增与修改文件

新增：

- app/v2/__init__.py
- app/v2/contracts.py
- app/v2/models.py
- app/v2/db.py
- app/v2/dataport.py
- app/v2/migrate.py
- app/v2/api.py
- contracts/v2/contract_fixture.json
- tests/test_v2_dataport.py
- tests/test_v2_migration.py
- tests/test_v2_api.py
- tests/test_v2_contract_fixture.py
- mobile/README.md
- mobile/package.json
- mobile/package-lock.json
- mobile/tsconfig.json
- mobile/src/contracts.ts
- mobile/src/schema.ts
- mobile/src/sqlite.ts
- mobile/src/node-sqlite.ts
- mobile/src/dataport.ts
- mobile/tests/contract.test.ts
- docs/v2/06-data-contract.md
- docs/v2/07-schema-and-migration.md
- docs/v2/08-dataport-and-api.md
- docs/v2/09-migration-drill.md
- docs/v2/10-contract-tests.md
- docs/v2/11-phase-b1-report.md

修改：

- app/main.py：注册 /api/v2 router；旧 router 不变
- .gitignore：忽略 mobile/node_modules、构建产物
- docs/v2/README.md：更新状态与索引

未修改：static/ 前端、app/routers/notes.py、app/routers/state.py、app/services/notes.py、旧 notes/frontend_state 表结构。

## 4. 数据契约

契约版本 2.0，schema_version 1。JSON snake_case、ID 字符串、时间 ISO UTC 毫秒、布尔 0/1 跨端转换。核心实体：

- Note：标题 1..120，正文 HTML <=1,000,000，category <=30，tags <=100，revision 乐观锁，is_favorite/is_trashed 及时间。
- Tag：name 1..32 唯一，color #RRGGBB。
- Attachment：元数据（original_name、mime、size、sha256、kind、created_at）；笔记-附件多对多；附件二进制阶段 E。
- AppSettings：10 locale、light/dark/system、list/grid、updated/created/title、助手名称/风格/长度/默认模型。
- AIProviderConfig：kind/label/base_url/model/key_ref；读取只返回 has_key，不返回 key_ref。

删除规则：默认软删除进回收站；restore 恢复；permanent=true 删除笔记和关联，共享附件元数据保留；删除标签只删关联。

## 5. 迁移与真实数据保护

- 只读真实库，迁移独立副本，真实库 hash 前后一致 e16595...。
- 迁移前备份：pre-v2-b1-20261123-202137.db，SHA256 28ceef...。
- 副本：7 notes、4 tags、6 note_tags、2 favorites、1 trashed、8 settings；verify ok，mismatches=[]。
- 幂等：第二次 already_migrated=true，计数不变。
- 回滚：restored.db 与备份 SHA256 一致，integrity ok。
- 旧 notes 表 0 行、frontend_state 1 行保留；没有清空、没有改写。

## 6. API 与兼容性

- /api/v2 提供 meta、notes CRUD/PATCH/favorite/restore/delete、attachments 列表、tags、settings、ai/providers。
- 缺 V2 表返回 503 中文提示；404/409/422 映射明确。
- 旧 /api/state 和 /notes 仍注册，响应不变。
- 应用启动不创建 v2_* 表；避免未迁移库出现半套结构。

## 7. 测试结果

完整 pytest：

~~~text
74 passed, 1 warning in 42.39s
~~~

其中旧测试 60 项全部通过，B1 新增 14 项通过。唯一 warning 是 Starlette 的 httpx/TestClient 弃用提示，与 B1 无关。

移动端：

~~~text
5 passed, 0 failed
tsc --noEmit exit 0
~~~

移动端测试使用便携 Node 22.14.0 和 node:sqlite，仅用于开发验证；不要求最终用户安装 Node。

### 7.1 实际接口验证

在独立副本（不是真实库）上启动 uvicorn（127.0.0.1:8011，HEPHAESTUS_DATABASE_URL 指向临时副本），用 httpx 发真实请求：

- GET /health -> 200 {"status":"ok"}
- GET /api/v2/meta -> contract_version=2.0，schema_version=1
- GET /api/v2/notes -> 默认排除回收站，total=6，items=6
- GET /api/v2/notes?favorite=true -> total=2
- GET /api/v2/notes?trashed=true -> total=1
- PATCH /api/v2/notes/{id} 带 revision -> 200，revision 从 1 变 2
- PATCH /api/v2/notes/{id}/favorite -> 200
- POST /api/v2/notes/{id}/restore -> 200，is_trashed=false
- POST /api/v2/notes -> 201；DELETE ?permanent=true -> 204
- GET /api/state -> 200，initialized=true，state 仍有 7 条笔记（旧快照未变）
- GET /notes（旧接口）-> 200，total=0（旧 notes 表仍为空）
- GET /api/v2/notes/nope -> 404；PATCH 空对象 -> 422
- 未迁移的 Web 默认库（仓库 data/，不是真实用户库）：GET /api/v2/notes -> 503 中文提示；GET /api/state -> 200；GET /health -> 200；没有创建 v2_* 表

## 8. 已知限制

- 尚未迁移真实用户数据库；需要单独授权和执行窗口。
- Capacitor 原生 SQLite 适配器尚未接入；当前移动端以 Node SQLite 适配器完成契约测试。
- 附件上传/下载/引用计数、data:image 拆分属于阶段 E。
- /api/v2 尚未接入 UI；前端仍使用 /api/state。
- 标签未知字段未落库；当前真实标签无未知字段。
- 未做多进程并发写同一 SQLite 文件的压力测试。
- 未添加 LICENSE；按授权继续内部开发。
- 未构建 Android/iOS/macOS/Linux 安装包；阶段 G。

## 9. 风险与回滚

- 风险：真实迁移时应用未停止写入；必须停写并在维护窗口执行。
- 风险：SQLite 文件级恢复不是事务；必须依赖备份 + integrity_check。
- 回滚：停止应用，使用迁移前备份替换真实库，核对 SHA256 和 PRAGMA integrity_check；旧 frontend_state 未动，旧 Web 前端可继续工作。
- 本阶段所有演练均在副本上完成，未触碰真实数据。

## 10. 请求授权

B1 已完成，按约定暂停。请验收以下内容，并决定是否授权：

1. 进入 B2：前端适配 /api/v2 或双写策略；
2. 真实库迁移的执行窗口与操作人；
3. 附件、Capacitor、AI、i18n 的后续阶段顺序。

未收到授权前，不合并 PR、不推送 main、不迁移真实库、不开始 AI/UI/安装包开发。
