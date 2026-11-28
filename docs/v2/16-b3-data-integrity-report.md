# B3 数据完整性报告

## 1. 校验器

`app/v2/migrate.py` 的 `verify_against_snapshot(source_db, target_db)` 是本阶段的核心验收器。它不是只数行数，而是把源快照和迁移库逐项比较。

检查项：

- 迁移标记 `v2_schema_migrations.version=1` 存在
- 每篇笔记存在，标题、HTML、创建时间、更新时间、分类一致
- 收藏/回收站标记一致
- `favorited_at`、`trashed_at`：标记为真时等于源 `updated`，否则为 null
- 笔记未知字段 `extra_json` 与源对象完全一致
- 标签 ID、名称、颜色一致；标签时间缺失时使用迁移 `applied_at`
- 笔记-标签关联逐条一致
- 设置键逐项一致，且没有意外多出的键
- `frontend_state.payload` 字节级一致
- 旧 `notes` 表行数一致

返回 `mismatches` 列表；任何一项不一致都会使 `ok=false`。校验器本身只读打开目标库。

## 2. 本轮结果

| 检查 | 结果 |
|---|---|
| 迁移副本 `drill.db` 完整性 | `ok` |
| 笔记 | 7/7 |
| 标签 | 4/4 |
| 关联 | 6/6 |
| 收藏 | 2/2 |
| 回收站 | 1/1 |
| 设置 | 8/8 |
| `frontend_state` 保留 | true |
| 旧 `notes` 表行数 | 0（一致） |
| `mismatches` | `[]` |

## 3. 未知字段与非法设置

真实数据的未知字段为 0，因此本轮真实副本不能证明“未知字段保留”。为避免把未覆盖的能力说成已验证，新增合成测试：

- `test_unknown_note_fields_and_ui_extras_are_preserved`：注入未来版本的笔记字段与 `ui.density`，验证 `extra_json` 与设置行保留
- `test_unknown_tag_fields_fail_closed`：标签出现当前 schema 无法保留的字段时，迁移必须失败而不是静默丢弃
- `test_invalid_ui_value_rolls_back_and_backup_restores`：非法已知设置值使整次迁移回滚，备份可恢复
- `test_mid_transaction_failure_leaves_no_rows_and_restore_works`：事务中途失败不留半成品

## 4. 已知限制

- 真实数据没有附件、图片、AI Provider，因此这些表只验证了“0 行”而不是完整导入。
- 未知字段保留由合成测试证明，不是由真实数据证明。
- 校验器比较的是当前 schema 能表达的字段；未来新增字段必须继续扩展校验器，否则会漏检。
- 迁移不修改源库；真实迁移前的停写与备份仍是独立步骤。

结论：副本迁移的数据完整性通过；真实迁移前仍需按 B3.4 预案重新做一次只读盘点和独立备份。
