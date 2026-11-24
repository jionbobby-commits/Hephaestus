# B3.3 迁移副本演练报告

演练时间：2026-11-24 12:13–12:16（Asia/Singapore）。
演练对象是 B3.2 新生成的真实库备份副本，不是用户正在使用的数据库。

## 1. 输入与输出

| 项目 | 值 |
|---|---|
| 输入备份 | `%LOCALAPPDATA%\Hephaestus\backups\pre-v2-b3-20261124-121305.db` |
| 输入 SHA256 | `28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762` |
| 输入完整性 | `ok` |
| 演练库 | `data/b3-drill/drill.db` |
| 演练库大小 | 90,112 bytes |
| 演练库 SHA256 | `e5e5f510b7b1b057e1afdebf753661711d5653c771b9450df8eb78714c399a1b` |
| 演练库完整性 | `ok` |

## 2. 迁移结果

| 项目 | 迁移前 | 迁移后 |
|---|---:|---:|
| 笔记 | 7 | 7 |
| 标签 | 4 | 4 |
| 笔记-标签关联 | 6 | 6 |
| 收藏 | 2 | 2 |
| 回收站 | 1 | 1 |
| 设置项 | 3 个 JSON 键 | 8 个 `v2_settings` 行 |
| 附件 | 0 | 0 |
| AI Provider | 0 | 0 |
| 迁移标记 | 无 | 1 |
| 导入元数据 | 无 | 4 |

设置项从 3 个 JSON 键展开为 8 个设置行，是统一 `AppSettings` 契约的结果；未知的额外 UI 键也会保留为行，已知键的非法值会让整次迁移失败。

## 3. 逐字段校验

`verify_against_snapshot(backup, drill.db)` 返回：

```json
{
  "ok": true,
  "checked_notes": 7,
  "checked_tags": 4,
  "checked_note_tags": 6,
  "checked_settings": 8,
  "frontend_state_preserved": true,
  "legacy_notes_count_preserved": true,
  "mismatches": []
}
```

校验覆盖：

- 每篇笔记的标题、HTML、创建/更新时间、分类、收藏/回收站标记
- 收藏时间与回收站时间：标记为真时等于原 updated，否则为 null
- 每篇笔记的未知字段 `extra_json` 与源 JSON 完全一致
- 每个标签的 ID、名称、颜色；缺失的时间使用迁移应用时间
- 笔记-标签关联的逐条对应
- 每个设置键的值；没有多余设置
- `frontend_state.payload` 字节级一致
- 旧 `notes` 表行数一致（0）

## 4. 幂等性

对已迁移的 `drill.db` 再次执行 `migrate_database`：

- `already_migrated: true`
- 笔记/标签/关联仍为 7/4/6
- SHA256 仍为 `e5e5f510...399a1b`
- 校验仍为 `ok`

第二次调用会在 `data/b3-drill/backups/` 生成一份迁移前副本，这是预期的安全行为，不会重复导入数据。

## 5. 失败与恢复

演练中用 `_insert_settings` 注入 `RuntimeError`，模拟迁移中途失败：

- 事务回滚后 `v2_notes=0`、`v2_tags=0`、`v2_schema_migrations=0`
- 用失败前副本恢复，SHA256 为 `28ceeff...29762`，与输入备份一致
- 完整性 `ok`，payload 仍为 `fe9c...`
- 恢复库中没有 `v2_*` 表

## 6. 回滚副本

把备份恢复到 `data/b3-drill/rollback.db`：

- 大小 16,384 bytes
- SHA256 `28ceeff...29762`
- 完整性 `ok`
- 表只有 `frontend_state`、`notes`
- payload `fe9c...`
- 没有 `v2_*` 表

结论：副本演练满足“数量一致、内容一致、关系一致、收藏/回收站一致、设置一致、时间不变、未知字段保留、旧快照保留、重复执行不重复导入、失败可恢复、完整性通过”。

原始机器可读结果：`data/b3-drill/drill_report.json`。
