# V2 数据契约（B1.1）

状态：B1.1 已实现，等待阶段 B1 验收。契约版本 **2.0**，物理结构版本 **1**。

本契约是桌面端 Python、移动端 TypeScript DataPort、Web 前端和未来导出/导入格式的唯一依据。实现位置：

- Python Pydantic：app/v2/contracts.py
- Python ORM：app/v2/models.py
- TypeScript 类型：mobile/src/contracts.ts
- 共享样例：contracts/v2/contract_fixture.json

## 1. 通用规则

- JSON 字段统一 **snake_case**；不使用 camelCase。
- ID 为字符串，1–64 字符，只允许 A-Z a-z 0-9 _ -；迁移时保留旧 ID，新对象使用 uuid4().hex。
- 时间统一为 UTC ISO-8601 文本，毫秒精度，必须形如 2026-11-23T12:34:56.789Z。
- 布尔值在 JSON 中为 true/false，在 SQLite 中为 0/1；跨端序列化必须转换。
- 正文以 HTML 为准，同时保存由 HTML 提取的纯文本用于搜索；不把 HTML 当纯文本存储。
- 未知字段：笔记和设置允许保留；API 的 NotePatch/TagPatch 使用 extra=forbid，防止拼写错误静默丢失。
- 不存明文 API Key；AI 配置只存 key_ref，读取时只返回 has_key。

## 2. 实体

### Note

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | 是 | 主键，旧 ID 保留 |
| title | string 1..120 | 是 | 标题；空白标题在 DataPort 层拒绝 |
| content_html | string <=1,000,000 | 是 | 正文 HTML，默认空串 |
| content_text | string <=1,000,000 | 是 | 纯文本投影，默认空串 |
| category | string <=30 或 null | 否 | 单分类，兼容 V1 |
| tags | Tag[] | 是 | 多标签，最多 100 个 |
| attachments | Attachment[] | 是 | 附件元数据 |
| is_favorite | bool | 是 | 收藏状态 |
| is_trashed | bool | 是 | 回收站状态 |
| favorited_at | ISO UTC 或 null | 否 | 收藏时间 |
| trashed_at | ISO UTC 或 null | 否 | 移入回收站时间 |
| created_at | ISO UTC | 是 | 创建时间 |
| updated_at | ISO UTC | 是 | 最后更新时间 |
| revision | int >=1 | 是 | 乐观锁版本，每次 PATCH 加 1 |

收藏不是独立表；它是 Note 上的 is_favorite + favorited_at。回收站同理。这样删除/恢复不会复制正文，也不会产生两套笔记 ID。

### Tag

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 主键 |
| name | string 1..32 | 唯一，去除首尾空白后不能为空 |
| color | #RRGGBB | 标签色 |
| created_at / updated_at | ISO UTC | 时间 |

笔记与标签为多对多：v2_note_tags(note_id, tag_id)，两端外键 ondelete CASCADE。删除标签只删除关联，不删除笔记。

### Attachment

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 主键 |
| original_name | string <=512 | 原始文件名，仅用于显示 |
| mime | string <=255 | MIME |
| size | int >=0 | 字节数 |
| sha256 | 64 hex | 内容校验 |
| kind | image/audio/document/other | 展示分类 |
| created_at | ISO UTC | 上传时间 |

笔记与附件为多对多：v2_note_attachments(note_id, attachment_id)。附件元数据独立存在，同一附件可被多篇笔记引用；删除一篇笔记只删除关联，不删除附件。附件二进制不在本契约中，B1 只定义元数据、关联和级联；上传/存储实现属于阶段 E。

### AppSettings

| 字段 | 类型 | 默认 |
|---|---|---|
| locale | 10 个 locale 之一 | zh-CN |
| theme | light/dark/system | system |
| layout | list/grid | list |
| sort | updated/created/title | updated |
| assistant_name | string 1..32 | 赫淮斯托斯 |
| assistant_style | professional/concise/friendly/academic/creative/custom | friendly |
| response_length | short/medium/long | medium |
| default_model | string 或 null | null |

locale 允许：zh-CN、en、ja、es、fr、ru、ar、fa、he、tr。ar/fa/he 为 RTL，前端必须设置 dir=rtl；数据层只保存值，不推断布局。

### AIProviderConfig

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 主键 |
| kind | ollama/openai/anthropic/gemini/deepseek/qwen/custom | 提供方类型 |
| label | string 1..64 | 用户可见名称 |
| base_url | string 1..2048 | 服务地址 |
| model | string 1..200 | 模型名 |
| key_ref | string 或 null | 仅内部存储；**读取契约不包含此字段** |
| has_key | bool | 读取时表示是否已配置密钥 |
| created_at / updated_at | ISO UTC | 时间 |

移动端首版不包含 Ollama；ollama 仍保留在契约中，供桌面端后续阶段使用。

## 3. 删除、恢复与级联

- DELETE /api/v2/notes/{id} 默认软删除：is_trashed=true，trashed_at=now，正文保留。
- POST /api/v2/notes/{id}/restore：is_trashed=false，trashed_at=null。
- DELETE /api/v2/notes/{id}?permanent=true：删除笔记行和 v2_note_tags/v2_note_attachments 关联；附件元数据保留，避免误删共享附件。
- 删除标签：删除 v2_tags 行和关联；笔记保留。
- 附件二进制清理必须由阶段 E 的引用计数任务处理，不能在删除笔记时直接删文件。

## 4. JSON 序列化样例

~~~json
{
  "id": "fwp72mwsh2u",
  "title": "欢迎使用赫淮斯托斯",
  "content_html": "<h1>开始记录</h1>",
  "content_text": "开始记录",
  "category": null,
  "tags": [{"id": "ggrdajzsh2u", "name": "学习", "color": "#f5a524", "created_at": "2026-11-23T12:00:00.000Z", "updated_at": "2026-11-23T12:00:00.000Z"}],
  "attachments": [],
  "is_favorite": true,
  "is_trashed": false,
  "favorited_at": "2026-11-22T08:00:12.822Z",
  "trashed_at": null,
  "created_at": "2026-11-22T08:00:12.822Z",
  "updated_at": "2026-11-22T08:00:12.822Z",
  "revision": 1
}
~~~

列表响应：

~~~json
{"items": [], "total": 0, "page": 1, "page_size": 20}
~~~

## 5. 版本与迁移策略

- 契约版本在 /api/v2/meta 返回 contract_version=2.0、schema_version=1。
- 物理迁移由 v2_schema_migrations 记录 version、applied_at、checksum；当前 version=1。
- 迁移只新增 v2_* 表和导入元数据，不修改、不删除旧 notes/frontend_state。
- 旧 /api/state 和 /notes 继续注册，字段和响应保持不变。
- 未来破坏性变更必须提升 contract_version，并提供只读适配层；不得静默改变字段含义。
- 迁移必须可重复执行：已存在 version=1 记录时直接返回 already_migrated=true，不重复插入。

## 6. 与旧数据的对应

| 旧字段 | 新字段 | 规则 |
|---|---|---|
| notes[].id | Note.id | 原样保留 |
| notes[].title | Note.title | 截断到 120 |
| notes[].html | Note.content_html | 原样保留；content_text 由 HTML 提取 |
| notes[].tags[] | Note.tags | 按旧 tag id 关联 |
| notes[].fav | is_favorite / favorited_at | true 时 favorited_at=updated |
| notes[].trashed | is_trashed / trashed_at | true 时 trashed_at=updated |
| notes[].created/updated | created_at/updated_at | 毫秒时间戳转 ISO UTC |
| notes[].category | category | 截断到 30 |
| tags[].id/name/color | Tag | 原样；缺失时间用迁移时间 |
| ui.theme/layout/sort | AppSettings | 原样；非法值由 Pydantic 拒绝 |

旧笔记中的 data:image 仍保留在 content_html 中；B1 的 data_url_count 会统计，但不会自动拆成 Attachment。附件拆分属于阶段 E。

## 7. 兼容性约束

- 不得把 frontend_state 清空或改写成 V2 格式。
- 不得让 /api/state 的 payload 结构变化。
- 不得在 UI 组件里直接执行 SQL；桌面端必须走 Python DataPort，移动端必须走 TypeScript DataPort。
- 两端契约测试使用同一份 contracts/v2/contract_fixture.json。
