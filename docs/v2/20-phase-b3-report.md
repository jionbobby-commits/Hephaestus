# 阶段 B3 报告：真实数据迁移预案、副本演练与 UI 验收

状态：**B3 已完成；真实库迁移未执行，等待单独授权。**

## 1. 范围与边界

B3 只做迁移前验证和预案，不做真实迁移。用户禁止的操作均未执行：

- 未修改真实数据库
- 未执行真实迁移
- 未删除旧 `frontend_state`
- 未覆盖任何既有备份
- 未清理用户文件
- 未开始 AI、附件上传、跨平台安装包
- 未合并 main、未 force-push、未改写历史

分支：`feat/v2-cross-platform`；实现与证据提交：`7fd4326ab3c061ab8337c616531915462d4dc288`。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| [14-b3-real-data-inventory.md](14-b3-real-data-inventory.md) | 真实数据只读盘点 |
| [15-b3-copy-drill-report.md](15-b3-copy-drill-report.md) | 副本迁移、幂等与失败恢复 |
| [16-b3-data-integrity-report.md](16-b3-data-integrity-report.md) | 逐字段完整性校验 |
| [17-b3-rollback-report.md](17-b3-rollback-report.md) | 回滚与恢复验证 |
| [18-b3-migration-runbook.md](18-b3-migration-runbook.md) | 正式迁移预案，未执行 |
| [19-b3-ui-acceptance.md](19-b3-ui-acceptance.md) | 迁移副本的真实 UI 验收 |
| `tests/frontend/b3_ui_verify.py` | 可重复执行的 UI 验收脚本 |
| `app/v2/migrate.py` | 更严格的迁移与校验 |
| `tests/test_v2_migration.py` | 迁移测试由 4 项增至 8 项 |

## 3. 真实数据盘点

只读确认：

- `frontend_state` 1 行，7 条笔记、4 个标签
- 6 条笔记-标签关联
- 2 条收藏，1 条回收站
- 3 个 UI 设置键
- 旧 `notes` 表 0 行
- 没有图片、附件或 AI Provider 数据
- 没有 schema 之外的未知笔记字段
- 时间字段和 payload 可正常解析

真实数据在 `frontend_state` 的 JSON 快照中，不在旧 `notes` 表；迁移不能只看 `notes` 行数。

## 4. 备份与副本演练

新设备份：

- `pre-v2-b3-20261124-121305.db`
- SHA256 `28ceeff23e9dc3af49f26078d3087e92a698261580c68959b251cf8cc5629762`
- 完整性 `ok`，可恢复到同等计数

副本演练：

- 输入：上述备份
- 输出：`data/b3-drill/drill.db`
- SHA256 `e5e5f510b7b1b057e1afdebf753661711d5653c771b9450df8eb78714c399a1b`
- 7 笔记、4 标签、6 关联、2 收藏、1 回收站、8 个设置行
- `verify_against_snapshot` 返回 `ok: true`，`mismatches: []`
- `frontend_state` 字节级保留；旧 `notes` 行数保留（0）
- 重复迁移返回 `already_migrated: true`，不重复导入
- 注入迁移失败后事务回滚，用备份恢复后哈希与输入一致

## 5. 真实 UI 验收

在迁移后的副本上，用真实前端 + WebView2 执行两个阶段：

- 第一阶段 32/32 检查通过：加载、编辑、收藏、标签、新建、回收站、恢复、永久删除、刷新
- 第二阶段 15/15 检查通过：关闭后重新启动，修改、标签、收藏和计数仍在
- 初始 6 条活动、1 条回收站、4 个标签；操作结束 7 条活动、1 条回收站、5 个标签
- 永久删除后服务器返回 404
- 临时副本最终 8 条 `v2_notes`（7 活动、1 回收站）、5 标签、7 关联、2 收藏
- 真实库 SHA256 `e16595...8ef4` 前后不变
- 演练库 SHA256 `e5e5f5...399a1b` 前后不变

## 6. 测试结果

执行：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

实际结果：

```text
88 passed, 1 warning in 181.47s (0:03:01)
EXIT:0
```

唯一 warning 是既有的 Starlette/httpx TestClient 弃用提示。没有删除、跳过或改写测试来制造通过。

测试组成：B2 的 84 项全部保留并继续通过；B3 将迁移测试从 4 项扩展到 8 项，新增 4 项。

## 7. 真实数据保护

- 真实库未被迁移，仍为旧 schema + `frontend_state`
- SHA256 仍为 `e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4`
- 大小仍为 16,384 bytes
- 新备份是独立文件，未覆盖旧备份
- 演练、UI 验收、失败恢复都在副本或临时目录

## 8. 限制

- 没有独立冲突中心；多设备/多标签页并发仍是已知限制
- 前端仍受 5MB localStorage 配额限制
- 未验证断电、磁盘写满、文件权限变化
- UI 验收由脚本驱动隐藏窗口，不是人工鼠标验收
- 迁移预案假设只有一个写入者；未做多进程并发迁移
- 没有 macOS、Linux、Android、iOS 构建环境
- 正式迁移命令未在真实库上执行

## 9. 合规核对

| 用户禁令 | 实际 |
|---|---|
| 不修改真实 DB | 未修改，哈希不变 |
| 不执行真实迁移 | 未执行 |
| 不删除旧快照 | `frontend_state` 保留，副本中字节级一致 |
| 不覆盖备份 | 只新增带时间戳备份 |
| 不清理用户文件 | 未清理 |
| 不开始 AI/附件/跨平台安装包 | 未开始 |
| 不合 main、不 force-push | 未执行 |

## 10. 下一步授权

B3 到此暂停。若要执行真实迁移，需要用户单独确认：

1. 迁移窗口和停机时间
2. 操作人
3. 备份目录与保留策略
4. 迁移后是否允许创建一条验收笔记
5. 失败时的回滚联系人与确认方式

在这些确认前，不应运行 `migrate_database` 指向真实库，也不应把本报告视为真实迁移授权。
