# B3.4 正式迁移操作预案

状态：**预案，未执行**。真实用户数据库迁移需要单独授权；B3 只在副本上演练。

## 1. 方案选择

推荐“影子库 + 原子替换”，不直接在正在使用的库上执行迁移：

1. 停写后复制真实库到影子文件。
2. 在影子上创建 V2 表并导入快照。
3. 用源库与影子库做逐字段校验。
4. 校验通过后，先把真实库改名为迁移前文件，再把影子库原子替换为真实库。
5. 启动应用，确认 `v2_ready`；失败则原子回滚。

优点：迁移失败不会让真实库出现半成品；写入窗口只有一次文件替换。缺点：需要额外磁盘空间和一个影子文件。`migrate_database(..., allow_in_place=True)` 仅作为受控备选，不作为首选。

## 2. 迁移前检查表

逐项勾选，任何一项不满足就停止：

- [ ] 用户已单独授权真实迁移，并确认迁移窗口。
- [ ] 已记录当前 Git 分支与提交，工作区干净；使用与验收一致的代码。
- [ ] 已确认没有任何 Hephaestus / uvicorn / python 进程占用数据库。
- [ ] 已确认数据库路径为 `%LOCALAPPDATA%\Hephaestus\hephaestus.db`，不是仓库里的 `data/hephaestus.db`。
- [ ] 磁盘剩余空间至少是数据库大小的 3 倍。
- [ ] 已重新执行只读盘点，记录当前笔记、标签、收藏、回收站、时间字段数量；不得沿用旧报告的数字。
- [ ] 已计算真实库 SHA256 和 `PRAGMA integrity_check`，两者均正常。
- [ ] 已确认 `frontend_state` 仍存在且 payload 可解析；这是回滚和旧前端兼容的依据。
- [ ] 已确认备份目录可写，现有备份不会被覆盖。
- [ ] 已通知用户停机时间，并确认迁移后需要重新打开应用。
- [ ] 已准备回滚文件路径和回滚操作人。

## 3. 停写

1. 让用户关闭 Hephaestus 窗口；等待进程退出。
2. 检查没有残留进程：

```powershell
Get-Process Hephaestus, python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like '*Hephaestus*' }
```

不要仅凭窗口消失判断；必须确认进程已退出。

3. 检查数据库旁是否有 `-wal` / `-shm`。如果有残留，先确认应用已停止，再用 Python 对数据库执行一次 `PRAGMA wal_checkpoint(TRUNCATE)`；不要在应用运行时操作。
4. 从这一步开始停止所有写入：不打开旧前端、不运行会写库的测试、不启动第二个实例。

## 4. 备份

使用 SQLite backup API，而不是在运行中直接复制：

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$db = "$env:LOCALAPPDATA\Hephaestus\hephaestus.db"
$backup = "$env:LOCALAPPDATA\Hephaestus\backups\pre-v2-real-$stamp.db"
.venv\Scripts\python.exe -c "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1].replace('\\','/')+'?mode=ro',uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $db $backup
Get-FileHash $backup -Algorithm SHA256
```

随后验证：

```powershell
.venv\Scripts\python.exe -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print('frontend_state',c.execute('select count(*) from frontend_state').fetchone()[0]); print('notes',c.execute('select count(*) from notes').fetchone()[0])" $backup
```

要求：完整性 `ok`，`frontend_state` 行数与真实库一致，`notes` 行数与真实库一致。

再把备份复制到临时目录做一次恢复演练，确认可打开、可读出同样计数。不得覆盖任何既有备份。

## 5. 构建影子库

```powershell
.venv\Scripts\python.exe -c "from app.v2.migrate import migrate_database; import json; print(json.dumps(migrate_database(r'C:\Users\<用户>\AppData\Local\Hephaestus\hephaestus.db', r'C:\Users\<用户>\AppData\Local\Hephaestus\hephaestus.v2-build.db', backup_dir=r'C:\Users\<用户>\AppData\Local\Hephaestus\backups'), ensure_ascii=False, indent=2))"
```

若影子文件已存在，换一个新的时间戳文件名；不要删除旧影子文件。

预期输出：

- `ok: true`
- `already_migrated: false`
- `summary.note_count` / `tag_count` 与盘点一致
- 影子文件大小大于旧库
- 影子库 `integrity_check=ok`

## 6. 校验

```powershell
.venv\Scripts\python.exe -c "from app.v2.migrate import verify_against_snapshot, verify_migrated; import json; print('snapshot',json.dumps(verify_against_snapshot(r'C:\...\hephaestus.db', r'C:\...\hephaestus.v2-build.db'), ensure_ascii=False)); print('migrated',json.dumps(verify_migrated(r'C:\...\hephaestus.v2-build.db'), ensure_ascii=False))"
```

必须满足：

- `ok: true`
- `mismatches: []`
- `frontend_state_preserved: true`
- `legacy_notes_count_preserved: true`
- 笔记、标签、关联、设置计数与盘点一致
- 收藏数和回收站数与盘点一致

任何一项失败：不替换真实库，保留影子文件和日志，按“失败处理”退出。

## 7. 原子替换

确认应用已停止、影子库校验通过后执行：

```powershell
$db = "$env:LOCALAPPDATA\Hephaestus\hephaestus.db"
$shadow = "$env:LOCALAPPDATA\Hephaestus\hephaestus.v2-build.db"
$pre = "$env:LOCALAPPDATA\Hephaestus\hephaestus.pre-v2-$(Get-Date -Format 'yyyyMMdd-HHmmss').db"
.venv\Scripts\python.exe -c "import os,sys; db,shadow,pre=sys.argv[1:4]; os.replace(db,pre); print('original moved to',pre); os.replace(shadow,db); print('shadow installed')" $db $shadow $pre
```

如果第二次替换失败，立即把 `$pre` 换回 `$db`，不要启动应用。

## 8. 启动与验收

1. 启动应用，等待窗口出现。
2. 确认界面显示 7 条笔记、4 个标签、2 个收藏、1 个回收站项（以最新盘点为准）。
3. 打开一篇笔记，确认标题、正文、标签、收藏状态正常。
4. 关闭并重新打开，确认数据仍在。
5. 如果能访问本地 API，确认 `GET /api/v2/status` 返回 `data_mode=v2_ready`；不能访问时以真实 UI 为准。
6. 不在真实库上做破坏性测试；如需创建验收笔记，必须先得到用户同意，并在验收后明确处理。

## 9. 回滚

出现以下任一情况立即回滚：启动失败、笔记/标签缺失、内容错乱、界面无法保存、数据状态不是 `v2_ready`、用户要求停止。

1. 关闭应用，确认进程退出。
2. 把当前库改名为 `hephaestus.failed-<stamp>.db`，保留证据。
3. 把迁移前的 `hephaestus.pre-v2-<stamp>.db` 原子替换回 `hephaestus.db`。
4. 校验完整性、`frontend_state`、`notes` 行数。
5. 启动应用，确认回到迁移前状态。
6. 保留失败库、影子库、备份和日志，等待用户确认后再清理。

## 10. 失败处理

| 阶段 | 失败表现 | 处理 |
|---|---|---|
| 停写 | 进程仍占用 | 停止操作，等待进程退出；不要强杀后直接迁移 |
| 备份 | 完整性失败 / 无法打开 | 停止，不迁移；先修复备份介质 |
| 建影子 | 迁移异常 / 计数不符 | 保留影子与异常，真实库未动；修复后重试 |
| 校验 | `mismatches` 非空 | 不替换；按字段修复或回滚到未迁移状态 |
| 替换 | 文件锁 / 替换失败 | 用迁移前文件原子换回；不要启动半成品 |
| 启动 | 笔记缺失 / 保存失败 | 立即回滚到迁移前文件 |
| 回滚 | 回滚文件损坏 | 使用第二份独立备份；不要删除任何现场文件 |

## 11. 停机时间与风险

预计停机 5–15 分钟：其中迁移本身通常小于 1 秒，备份、校验、替换和启动验收占主要时间。数据量增长后按实际盘点调整。

| 风险 | 影响 | 缓解 |
|---|---|---|
| 应用仍在写库 | 备份/迁移不一致 | 停写并确认进程退出 |
| 备份被覆盖 | 无法回滚 | 时间戳命名、只新增、不覆盖 |
| 迁移到错误路径 | 真实库未变或误改 | 迁移前打印并核对绝对路径 |
| 影子校验漏字段 | 数据静默丢失 | 使用 `verify_against_snapshot`，不通过不替换 |
| 替换中断 | 数据库缺失 | 先改名保留原库，再原子替换；失败立即换回 |
| 回滚覆盖新数据 | 迁移后新笔记丢失 | 回滚前确认没有需保留的新内容 |
| 旧前端缓存 | 显示旧数据 | 迁移后只使用 V2 就绪的前端；保留 `frontend_state` |

## 12. 退出条件

只有以下全部满足才算真实迁移完成：

- 影子迁移 `ok`
- 逐字段校验 `ok`，`mismatches=[]`
- 真实库已备份且备份可恢复
- 原子替换成功
- 启动后数据计数、内容、标签、收藏、回收站正确
- 关闭重开数据仍在
- 用户确认验收

否则必须回滚并报告，不得把“迁移命令返回 0”当作迁移成功。
