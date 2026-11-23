# DataPort 与 /api/v2（B1.3 / B1.4）

状态：Python 与 TypeScript DataPort 已实现；/api/v2 已注册；旧 /api/state 和 /notes 未修改。

## 1. 分层

~~~text
UI / API 路由
    -> DataPort（唯一数据访问入口）
        -> SQLAlchemy（桌面/Web）或 node:sqlite（移动端测试适配器）
            -> SQLite（v2_* 表 + 旧表）
~~~

禁止在 UI 组件或路由处理函数里直接执行 SQL。Python 端由 app/v2/dataport.py 提供 SqlAlchemyDataPort；移动端由 mobile/src/dataport.ts 提供 SqliteDataPort。两端共享同一份 JSON 契约和 fixture。

## 2. Python DataPort

构造：SqlAlchemyDataPort(session)

笔记：

- list_notes(query=None, tag_id=None, favorite=None, trashed=False, page=1, page_size=20, sort="updated")
- get_note(note_id)
- create_note(NoteCreate)
- update_note(note_id, NotePatch)
- set_favorite(note_id, favorite)
- trash_note(note_id)
- restore_note(note_id)
- delete_note(note_id, permanent=False)
- list_attachments(note_id)

标签：

- list_tags()
- create_tag(TagCreate)
- update_tag(tag_id, TagUpdate)
- delete_tag(tag_id)

设置与 AI 配置：

- get_settings() / update_settings(AppSettingsPatch)
- list_ai_providers() / create_ai_provider(AIProviderConfigCreate) / delete_ai_provider(id)

错误类型：

- NotFoundError -> HTTP 404
- ConflictError -> HTTP 409（revision 冲突、标签重名）
- InvalidReferenceError / ValueError -> HTTP 422（标签不存在、标题空白）
- OperationalError（缺 V2 表）-> HTTP 503，中文提示“V2 数据库尚未迁移；旧 /api/state 不受影响”

更新语义：

- update_note 是 PATCH 语义，只改 model_fields_set 中出现的字段。
- 若传 revision 且不等于当前值，抛 ConflictError，不覆盖他人修改。
- 每次成功更新（包括收藏、回收站、恢复）revision 加 1，updated_at 刷新。
- 收藏用 PATCH /notes/{id}/favorite；回收站用 DELETE 默认软删除；恢复用 POST /restore。

## 3. TypeScript DataPort

文件：mobile/src/dataport.ts。构造：new SqliteDataPort(client: SqliteClient)。

方法与 Python 对齐：listNotes、getNote、createNote、updateNote、setFavorite、trash、restore、deleteNote(permanent)、listTags、createTag、updateTag、deleteTag、getSettings、updateSettings、listAiProviders、createAiProvider、deleteAiProvider、listAttachments。

实现细节：

- 事务使用 BEGIN IMMEDIATE，失败 ROLLBACK。
- 布尔值在读写时转换 0/1。
- revision 冲突抛 ConflictError；不存在抛 NotFoundError；无效标签引用抛 InvalidReferenceError。
- createAiProvider 返回对象显式构造，不包含 key_ref，避免 spread 泄漏。
- 分页、排序、搜索、标签/收藏/回收站过滤语义与 Python 一致。
- 当前生产移动端使用 node:sqlite 适配器做契约测试；Capacitor 原生 SQLite 适配器在阶段 G 接入，接口不变。

## 4. /api/v2

前缀 /api/v2；OpenAPI 中可见。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /meta | contract_version、schema_version、server_time |
| GET | /notes | q、tag_id、favorite、trashed、page、page_size、sort |
| POST | /notes | 创建，201 |
| GET | /notes/{id} | 详情 |
| PATCH | /notes/{id} | 局部更新，可带 revision |
| DELETE | /notes/{id} | 默认软删除；permanent=true 永久删除，204 |
| PATCH | /notes/{id}/favorite | 收藏/取消收藏 |
| POST | /notes/{id}/restore | 从回收站恢复 |
| GET | /notes/{id}/attachments | 附件元数据列表 |
| GET/POST | /tags | 标签列表/创建 |
| PATCH/DELETE | /tags/{id} | 更新/删除标签 |
| GET/PATCH | /settings | 设置读取/局部更新 |
| GET/POST | /ai/providers | AI 配置列表/创建（不返回 key_ref） |
| DELETE | /ai/providers/{id} | 删除 AI 配置 |

兼容性：

- app/main.py 同时 include 旧 notes/state router 和新 v2 router；旧路径、旧响应不变。
- /api/state 继续读写 frontend_state，不经过 V2 表。
- 应用启动不会创建 v2_* 表；未迁移时 /api/v2 返回 503，旧接口仍可用。

## 5. 契约测试

- Python：tests/test_v2_dataport.py 6 项、test_v2_api.py 3 项、test_v2_contract_fixture.py 1 项。
- 移动端：mobile/tests/contract.test.ts 5 项；命令见 10-contract-tests.md。
- 共享 fixture：contracts/v2/contract_fixture.json；Python 和 TypeScript 都按它校验字段和精确 key 集合。

## 6. 未完成 / 后续

- 附件上传、下载、存储、引用计数属于阶段 E。
- Capacitor 原生 SQLite 适配器、真实 Android/iOS 壳属于阶段 G。
- AI 调用、流式响应、密钥托管属于阶段 C。
- /api/v2 尚未接入前端 UI；B1 只做数据层，前端继续使用 /api/state。
