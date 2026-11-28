# B1.2 真实数据迁移演练报告

执行日期：2026-11-23。执行范围：只读真实库 + 独立副本迁移 + 备份恢复；**未迁移真实库**。

## 1. 输入

| 项 | 值 |
|---|---|
| 真实库 | %LOCALAPPDATA%\Hephaestus\hephaestus.db |
| 大小 | 16,384 B |
| SHA256 | e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4 |
| 旧 notes 行数 | 0 |
| frontend_state 行数 | 1 |
| 快照笔记 | 7 |
| 快照标签 | 4 |
| 笔记-标签关联 | 6 |
| 收藏 | 2 |
| 回收站 | 1 |
| data:image 引用 | 0 |

真实数据只在 frontend_state 的 JSON 中，notes 表为空；因此本次只迁移 JSON 快照，不迁移空的 notes 表。

## 2. 备份

迁移前用 SQLite online backup 生成：

- %LOCALAPPDATA%\Hephaestus\backups\pre-v2-b1-20261123-202137.db
- 16,384 B；SHA256 28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762
- PRAGMA integrity_check = ok

备份位于真实库同级 backups 目录，不在仓库内，不进入 Git。

## 3. 副本迁移

命令等价于：

~~~powershell
.venv\Scripts\python.exe -c "from app.v2.migrate import migrate_database; print(migrate_database(r'%LOCALAPPDATA%\Hephaestus\hephaestus.db', r'data/b1-drill/drill.db'))"
~~~

结果：

- 目标：data/b1-drill/drill.db
- 大小：90,112 B
- SHA256：58f7f6fafaca6c298f40b867ff51c5d1ec29ea591cb7fa08db10f794599a8fee
- ok=true，already_migrated=false
- 计数：notes 7、tags 4、note_tags 6、favorites 2、trashed 1、settings 8
- 旧 notes 0、frontend_state 1 保留在副本中
- v2_attachments 0、v2_ai_providers 0

## 4. 完整性验证

verify_against_snapshot 输出：

~~~json
{"ok": true, "checked_notes": 7, "checked_tags": 4, "mismatches": []}
~~~

逐项比较了：

- 7 条笔记的 id、title、content_html、created_at、updated_at、is_favorite、is_trashed、category；
- 每条笔记的标签集合；
- 4 个标签的 name、color；
- 笔记数和标签数。

另验证：

- 所有 created_at/updated_at 符合 ISO UTC 毫秒格式；
- 所有迁移的标签时间符合 ISO UTC；
- 旧 frontend_state 仍在，未被清空；
- 旧 notes 表仍在（0 行）。

## 5. 幂等性

对同一个已迁移的 drill.db 再执行 migrate_database：

- already_migrated=true
- notes 7、tags 4、note_tags 6 不变
- 没有重复笔记或重复关联

实现依据：v2_schema_migrations 中 version=1 的存在性检查；整个导入在一个事务中提交。

## 6. 回滚

从备份恢复到独立文件：

- 目标：data/b1-drill/restored.db
- 大小：16,384 B
- SHA256：28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762
- 与备份 SHA256 逐字节一致
- PRAGMA integrity_check = ok

说明：B1 没有对真实库执行恢复；只演示了从备份恢复独立副本。真实迁移若失败，操作者应停止应用，用备份替换真实库，再校验 hash 和 integrity_check。

## 7. 真实库未变化证据

演练前后：

- 真实库 SHA256 仍为 e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4
- 表仍只有 frontend_state、notes
- 没有 v2_* 表
- frontend_state 仍为 1 行
- 没有任何用户笔记被改写或删除

## 8. 验收结论

- 独立副本迁移：通过。
- 7 条笔记 / 4 个标签完整性：通过。
- 重复执行不重复导入：通过。
- 备份恢复：通过。
- 真实库保护：通过（未迁移、未清空、未删除）。
- 未完成：真实库正式迁移（需要单独授权）；附件/data URL 拆分；并发写入场景。
