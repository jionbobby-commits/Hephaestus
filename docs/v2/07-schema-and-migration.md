# V2 物理结构与迁移（B1.2）

状态：结构已实现；真实数据迁移演练已完成，**尚未迁移真实用户数据库**。

实现位置：

- app/v2/models.py：V2 SQLAlchemy 模型
- app/v2/db.py：独立 V2 engine/session、显式 create_v2_db
- app/v2/migrate.py：备份、快照读取、校验、迁移、回滚、完整性验证

## 1. 物理表

所有表使用 v2_ 前缀，与旧 notes/frontend_state 共存：

| 表 | 作用 | 关键约束 |
|---|---|---|
| v2_notes | 笔记主体 | id PK；title 120；content 最大 1,000,000；revision；extra_json |
| v2_tags | 标签 | id PK；name UNIQUE；color #RRGGBB |
| v2_note_tags | 笔记-标签多对多 | 复合 PK；双外键 CASCADE |
| v2_attachments | 附件元数据 | id PK；sha256；stored_name；mime；size |
| v2_note_attachments | 笔记-附件多对多 | 复合 PK；双外键 CASCADE |
| v2_settings | 设置键值 | key PK；value_json |
| v2_ai_providers | AI 配置 | id PK；key_ref 仅内部；extra_json |
| v2_schema_migrations | 迁移记录 | version PK；checksum；applied_at |
| v2_import_meta | 导入审计 | key PK；value |

旧表 notes 和 frontend_state 完全保留。V2 表不会在应用启动时自动创建；只有显式调用 create_v2_db() 或迁移命令才会创建。这样启动未迁移的真实库不会产生半套结构。

## 2. 迁移算法

migrate_database(source, target, backup_dir=None, allow_in_place=False) 的顺序：

1. 解析绝对路径；若 source==target 且未显式 allow_in_place，拒绝。
2. 以只读方式打开 source，读取 frontend_state id=1 的 payload。
3. 校验 payload：notes/tags 为数组；ID 唯一；时间戳为毫秒数；标签引用存在；统计收藏/回收站/data URL；未知字段记录到摘要。
4. 创建 target 父目录。
5. 若 target 不存在：用 SQLite online backup 复制 source 到 target，并对副本做 PRAGMA integrity_check。
6. 若 target 已存在：先备份 target 到 backup_dir，再迁移；绝不覆盖 source。
7. 创建 V2 表。
8. 在一个事务中插入标签、笔记、笔记-标签关联、设置、迁移记录和导入元数据。
9. 提交后运行 verify_migrated()，返回计数。
10. 任一步失败：事务回滚；target 可能留下空 V2 表，但不会留下半条笔记；source 不变。

迁移重复执行：若 v2_schema_migrations 已有 version=1，直接返回 already_migrated=true 和现有计数，不重复导入。

## 3. 回滚

restore_database(backup, target) 通过临时文件 + PRAGMA integrity_check + os.replace 恢复；备份文件本身不被修改。B1 演练中，备份恢复出的 restored.db 与备份 SHA256 完全一致。

回滚不依赖应用代码：即使 V2 代码不可用，也可以用备份文件直接替换数据库。真实迁移前必须先备份；B1 未对真实库执行 restore。

## 4. 真实数据演练

源库（真实用户数据库，只读）：

- 路径：%LOCALAPPDATA%\Hephaestus\hephaestus.db
- 大小：16,384 B
- SHA256：e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4
- 旧 notes 表 0 行；frontend_state 1 行；快照 7 条笔记、4 个标签、6 个笔记-标签关联、2 个收藏、1 个回收站、0 个 data URL。

迁移前备份：

- 路径：%LOCALAPPDATA%\Hephaestus\backups\pre-v2-b1-20261123-202137.db
- 大小：16,384 B
- SHA256：28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762
- PRAGMA integrity_check：ok

独立副本迁移：

- 目标：data/b1-drill/drill.db
- 大小：90,112 B
- SHA256：58f7f6fafaca6c298f40b867ff51c5d1ec29ea591cb7fa08db10f794599a8fee
- 计数：notes 7、tags 4、note_tags 6、favorites 2、trashed 1、settings 8、attachments 0、ai_providers 0
- verify_against_snapshot：ok=true，checked_notes=7，checked_tags=4，mismatches=[]
- 第二次 migrate_database：already_migrated=true，计数不变

回滚演练：

- 从上述备份恢复到 data/b1-drill/restored.db
- 大小：16,384 B；SHA256：28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762；integrity ok
- 恢复结果与备份逐字节一致

真实库在演练前后 SHA256 仍为 e16595...，且没有 v2_* 表。演练只读源库，没有清空 frontend_state，没有迁移 notes 表，没有删除任何用户数据。

## 5. 数据完整性验证

verify_against_snapshot 逐条比较：

- 每条笔记的 id、title、content_html、created_at、updated_at、is_favorite、is_trashed、category；
- 每条笔记的标签集合；
- 每个标签的 name、color；
- 笔记数、标签数。

全部匹配才返回 ok=true。未知字段不参与比较，但会保存在 v2_notes.extra_json 中；标签的未知字段目前只记录摘要，不落库（当前真实标签无未知字段）。

## 6. 风险与限制

- 迁移是单事务，但 SQLite 文件级备份/恢复不是数据库事务；必须依赖备份和 integrity_check，不能依赖“迁移失败自动恢复原文件”。
- 未做并发写入迁移；真实迁移应在应用停止写入时执行。
- 附件二进制、data:image 拆分、附件引用计数不在 B1；阶段 E 处理。
- 标签未知字段未落库；若未来出现，需要先扩展 TagV2 或 extra_json，再迁移。
- 真实迁移命令尚未执行；B1 只提供演练与验收证据，实际迁移需要单独授权。
