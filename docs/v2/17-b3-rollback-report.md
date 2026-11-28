# B3 回滚验证报告

## 1. 回滚对象

回滚目标是 B3.2 的独立备份：

```
%LOCALAPPDATA%\Hephaestus\backups\pre-v2-b3-20261124-121305.db
SHA256 28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762
```

该备份与两份既有 B1 备份字节一致，均为 16,384 bytes、完整性 `ok`、`frontend_state` 1 行、`notes` 0 行。

## 2. 三种验证

### 2.1 既有备份可恢复

把两份 B1 备份分别复制到临时目录：

- 复制件 SHA256 与备份一致
- `PRAGMA integrity_check=ok`
- `frontend_state` 1 行、payload 仍为 `fe9c...`

### 2.2 迁移失败后恢复

在副本迁移中注入 `RuntimeError`：

- 事务回滚，`v2_notes=0`、`v2_tags=0`、`v2_schema_migrations=0`
- 从失败前副本恢复
- 恢复件 SHA256 `28ceeff...29762`，与输入备份完全一致
- 完整性 `ok`
- payload `fe9c...`
- 没有 `v2_*` 表

### 2.3 迁移成功后回滚

把备份恢复到 `rollback.db`：

- 16,384 bytes
- SHA256 `28ceeff...29762`
- 完整性 `ok`
- 表只有 `frontend_state`、`notes`
- 没有 `v2_*` 表
- payload `fe9c...`

## 3. 正式回滚步骤

1. 关闭 Hephaestus 桌面窗口，确认没有 uvicorn/Hephaestus 进程占用数据库。
2. 把当前数据库另存为 `hephaestus.failed-<时间>.db`，不要删除。
3. 把选定备份复制为同目录临时文件 `hephaestus.db.restore.tmp`。
4. 对临时文件执行 `PRAGMA integrity_check`，必须为 `ok`。
5. 在应用停止状态下用同卷原子替换为 `hephaestus.db`。
6. 重新启动应用，验证 `/api/v2/status` 返回 `legacy` 或迁移前状态，7 条笔记、4 个标签、2 个收藏、1 个回收站项可见。
7. 保留失败库和备份，直到用户确认。

## 4. 回滚风险

- 回滚会丢弃迁移后新写入的笔记；执行前必须确认没有需要保留的新内容。
- 如果应用未停止，Windows 文件锁或 SQLite WAL 可能让替换失败；必须先停写。
- 不能用“复制覆盖”代替完整性检查；损坏的备份会把可恢复状态变成不可恢复。
- 回滚后旧前端快照仍是权威数据；不要删除 `frontend_state`。

结论：备份可恢复、失败可回滚、回滚后仍是可用的旧版数据库；本轮没有对真实库执行回滚。
