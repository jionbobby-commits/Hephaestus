# B1 契约测试报告

## 1. 共享 fixture

contracts/v2/contract_fixture.json

包含：

- contract_version=2.0
- 一个完整标签
- 一条完整笔记（收藏、revision=3、空附件）
- 设置对象
- AI 配置对象（只有 has_key，没有 key_ref）
- 空列表页

Python 和 TypeScript 测试都读取同一个文件；任一端字段漂移都会失败。

## 2. Python 测试

命令：

~~~powershell
.venv\Scripts\python.exe -m pytest -q tests/test_v2_dataport.py tests/test_v2_migration.py tests/test_v2_api.py tests/test_v2_contract_fixture.py
~~~

结果：14 passed，1 warning（Starlette 的 httpx/TestClient 弃用警告，与 B1 无关）。

完整仓库测试：74 passed，1 warning，42.39s（旧 60 项 + B1 14 项，无失败）。

覆盖：

- test_v2_dataport.py（6）：创建/读取/局部更新/revision 冲突/收藏/回收站/恢复/永久删除；标签 CRUD 与重名冲突；设置；AI key_ref 不泄漏；附件列表；分页与排序。
- test_v2_migration.py（4）：JSON 快照解析与校验；独立副本迁移计数；幂等；备份恢复与完整性；真实样例的 7 条笔记字段比对（使用测试夹具，不写真实库）。
- test_v2_api.py（3）：/api/v2/meta；笔记与标签端点；错误映射（404/409/422）；旧 /api/state 仍可用；缺失 V2 表返回 503。
- test_v2_contract_fixture.py（1）：Pydantic 模型接受 fixture，且 NoteRead 的精确 key 集合符合契约。

## 3. 移动端测试

环境：Windows + 便携 Node 22.14.0（不要求目标机安装 Node；这是开发测试环境）。

命令：

~~~powershell
cd mobile
node --experimental-strip-types --experimental-sqlite --test tests/contract.test.ts
~~~

结果：5 passed，0 failed；有两条 ExperimentalWarning（类型剥离、SQLite），属于 Node 22 的实验特性提示。

覆盖：

1. 共享 JSON fixture 与移动端契约一致。
2. 笔记创建、读取、更新、收藏、回收站、恢复、永久删除。
3. 标题/标签校验与事务回滚边界。
4. 设置与 AI 配置不暴露 key_ref。
5. 分页与附件列表稳定性。

类型检查：

~~~powershell
npm install
npm run typecheck
~~~

结果：tsc --noEmit 退出码 0。依赖只包含 typescript 与 @types/node；node_modules 已加入 .gitignore。

## 4. 两端一致性

| 契约点 | Python | TypeScript | 结果 |
|---|---|---|---|
| 精确字段集合 | fixture 测试 | fixture 测试 | 一致 |
| 时间格式 | IsoUtc 正则 | ISO_UTC 正则 | 一致 |
| 布尔存储 | SQLAlchemy Boolean | 0/1 转换 | 一致 |
| revision 冲突 | ConflictError | ConflictError | 一致 |
| 标签引用不存在 | InvalidReferenceError | InvalidReferenceError | 一致 |
| key_ref 不暴露 | _provider_public | 显式对象 | 一致 |
| 分页默认/上限 | 20 / 100 | 20 / 100 | 一致 |
| 回收站默认过滤 | trashed=false | trashed=false | 一致 |

## 5. 未覆盖

- Capacitor 原生 SQLite 适配器（阶段 G）。
- 多进程/多设备并发写同一 SQLite 文件。
- 附件二进制上传与引用计数。
- 10 种语言/RTL 的 UI 快照测试。
- 真实 Android/iOS 设备上的契约测试。

## 6. 结论

B1 的桌面端与移动端数据访问层已经用同一份契约和同一组语义测试验证；两端都能独立完成笔记、标签、收藏、回收站、设置与 AI 配置的基础操作。测试未触碰真实用户数据库。
