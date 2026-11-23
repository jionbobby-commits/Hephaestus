# 阶段 B2 验收报告：前端 DataPort 适配

日期：2026-11-23。分支：feat/v2-cross-platform。基线：main / 3e341a5；B2 起点 727f9c0。状态：代码与自动化验证完成，等待用户验收；未合并、未推送 main、未迁移真实库。

## 1. 范围与边界

按 2026-11-23 的 B2 授权，只做前端数据层适配：

- 前端统一 DataPort 入口，UI 不直接访问数据库或 API。
- 笔记、标签、收藏、回收站、设置的读写全部经过 Store/DataPort。
- 优先 /api/v2；未迁移、迁移待定、迁移失败时继续 /api/state。
- 数据模式检测、单写入源、失败回退、版本冲突、保存失败不丢内容。
- 自动化测试与真实 WebView2 窗口操作验证。

未做：真实库迁移、删除 frontend_state、修改旧笔记、双写、AI、附件上传、i18n、移动端壳、安装包、PR 合并、推 main、改写历史。

## 2. 验收清单

| 要求 | 实现 | 证据 |
|---|---|---|
| 统一前端 DataPort 入口 | static/dataport.js 是唯一网络层；Store 只调用它 | dataport.test.cjs 8 项；grep 前端无其它 fetch 数据请求 |
| 组件不直接调 DB/API | static/script.js 的数据操作全部走 Store | 代码审查；UI 操作测试 |
| 包装笔记/标签/收藏/回收站/设置 | V2 与 legacy 两套适配器方法齐全 | 方法表见 12-frontend-dataport.md |
| 使用 /api/v2 | v2_ready 时全部读写走 /api/v2 | 真实 v2 模式测试，revision 2→7 |
| 保留旧 /api/state 适配 | legacy / pending / failed 使用 /api/state | legacy 与两种迁移异常模式实测 |
| 检测数据版本并选择适配器 | GET /api/v2/status + 状态机 | test_v2_status.py 5 项 |
| 未迁移库绝不调用 V2 数据接口 | adapter=legacy 时 assertV2 抛错 | Node 测试；legacy 实测无 V2 数据请求 |
| 四种状态 legacy/pending/ready/failed | app/v2/status.py 固定优先级 | 5 项 API 测试 + 4 种真实 UI 模式 |
| 迁移失败自动回退旧版 | migration_failed → /api/state | 真实 UI failed 模式 |
| 不清空前端状态、不自动重复迁移、不删旧快照 | 前端只读写，不执行迁移；旧快照保留 | 真实库 hash 不变；临时库前后对比 |
| 单写入源、不双写 | v2 模式禁止 saveLegacy；状态未知时停止写入 | Node 双重写入测试；状态 503 停止写入测试 |
| 冲突明确提示 | 409 弹窗，显示服务器 revision，三种选择 | 真实 UI 冲突实测 |
| 保存失败/断网不丢内容 | localStorage 缓存 + journal；状态文案；初始化失败恢复日志 | 真实 UI 停服写入、恢复、刷新实测；状态 503 编辑恢复实测 |
| 刷新后状态一致 | 启动合并服务器快照与 journal | 真实 UI 刷新后 4 条唯一笔记、已保存 |
| 关闭/重开不丢内容 | 关窗前 pagehide + flush；重开合并 | 真实 UI reopen 实测 |
| 重复提交不重复创建 | reconcileRunning 去重 + journal | 连续两次 flush 后仍 4 条唯一笔记 |
| 旧 API 兼容 | /api/state 与 /api/v2/status 404 回退 | Node 404 回退测试；legacy 实测 |

## 3. 新增与修改文件

新增：

- static/dataport.js：前端唯一网络层，UMD，浏览器 window.HephaestusDataPort，Node 可 require。
- app/v2/status.py：只读数据模式检测。
- tests/frontend/dataport.test.cjs：8 项 Node 内置测试，无 npm 依赖。
- tests/frontend/ui_fixtures.py：独立临时 SQLite 夹具（legacy/v2/pending/failed）。
- tests/frontend/ui_verify.py：真实 pywebview/WebView2 操作脚本，输出 JSON。
- tests/frontend/recovery_verify.py：状态接口 503 时编辑、恢复、二次刷新的真实窗口脚本。
- tests/frontend/status_fail_app.py：只让 /api/v2/status 返回 503 的测试 ASGI 包装。
- tests/test_v2_status.py：5 项模式检测与 API 测试。
- tests/test_v2_ui.py：5 项真实窗口 pytest 包装（含初始化失败恢复），校验真实用户库 hash 不变。
- docs/v2/12-frontend-dataport.md：B2 架构与状态机说明。
- docs/v2/13-phase-b2-report.md：本报告。

修改：

- static/script.js：Store 重写为 DataPort 协调层；journal、reconcile、冲突、保存状态、模式显示。
- static/index.html：先加载 dataport.js，再加载 script.js。
- app/v2/api.py：新增 GET /api/v2/status。
- docs/v2/README.md：状态与索引更新。

未修改：app/v2/dataport.py、app/v2/models.py、app/v2/migrate.py、app/v2/db.py、旧 notes/state 路由、数据库结构、真实用户库。

## 4. 四种数据状态与单写入源

| 状态 | 前端写入 | 说明 |
|---|---|---|
| legacy | PUT /api/state | 没有 v2_* 表，旧版继续工作 |
| migration_pending | PUT /api/state | v2 表不完整或缺迁移标记 |
| migration_failed | PUT /api/state | 显式失败标记，回退旧版 |
| v2_ready | /api/v2 | 完整 v2 表 + version=1 迁移标记 |

只有 404/405 表示旧服务端没有状态接口，才回退 /api/state。网络错误、超时、5xx 或未知响应一律停止写入，避免迁移后的库被旧快照再次写入。该行为已用 Node 测试锁定。

## 5. 数据保护

- 真实用户库：%LOCALAPPDATA%\Hephaestus\hephaestus.db，SHA256 e16595ccf1da0739d40a840ecb71557918d9d416f6a9b470fc9d36bf27aa8ef4。B2 全程未写入、未迁移、未删除。
- test_v2_ui.py 每个用例运行前后计算真实库 SHA256 并断言一致。
- 所有 UI 测试库位于临时目录，使用 ui_fixtures.py 生成，测试结束清理。
- 未执行 migrate_database 对真实库；未调用 /api/v2 写真实库。
- 旧 frontend_state 快照保留；前端不删除、不清空。

## 6. 测试结果

### 6.1 Python

~~~text
84 passed, 1 warning in 214.62s
~~~

其中 B2 新增：

- tests/test_v2_status.py：5 passed
- tests/test_v2_ui.py：5 passed（真实 WebView2）

唯一 warning 仍是 Starlette 的 httpx/TestClient 弃用提示，与 B2 无关。

### 6.2 Node DataPort

~~~text
tests 8, pass 8, fail 0
~~~

覆盖：legacy 快照规范化、无状态接口回退、状态 503 停止写入、pending/failed 不写 V2、v2 分页读写、409 冲突、V2 读取失败不写旧快照、本地标签按名称映射。

### 6.3 真实窗口（WebView2）

5 个 pytest 用例全部通过：

- legacy：读取旧快照，创建、编辑、收藏、加标签、删除、恢复、刷新、重开。
- v2_ready：创建、编辑、收藏、加标签、删除、恢复；revision 2→7；409 冲突弹窗，选择保留我的修改；停服保存失败后恢复；同端口重试；刷新；重开。
- migration_pending：只读旧版，标签“迁移待定 · 旧版兼容”，无 V2 写入。
- migration_failed：只读旧版，标签“迁移失败 · 旧版兼容”，无 V2 写入。
- 初始化失败恢复：/api/v2/status 返回 503 时进入“服务未连接 · 本地缓存”，编辑只写恢复日志；服务恢复并刷新后内容写入 V2，二次刷新仍在。

## 7. 场景矩阵（十项要求 + 初始化失败补充）

| 场景 | 验证方式 | 结果 |
|---|---|---|
| 旧版模式 | 真实 UI legacy + Node | 通过；/api/state 写入 |
| V2 模式 | 真实 UI v2_ready | 通过；/api/v2 写入 |
| 未迁移库 | 真实 UI legacy（无 V2 表） | 通过；不调用 V2 数据接口 |
| 迁移失败 | 真实 UI migration_failed | 通过；回退旧版 |
| 版本冲突 | 真实 UI 409 + 弹窗选择 | 通过；revision 递增，不静默覆盖 |
| 保存失败 | 真实 UI 停服写入 | 通过；内容与标题保留，状态明确 |
| 页面刷新 | 真实 UI load_url 刷新 | 通过；4 条唯一笔记，状态已保存 |
| 关闭/重开 | 真实 UI reopen 阶段 | 通过；数据仍在 |
| 重复提交 | 连续两次 Store.flush | 通过；无重复笔记 |
| 旧 API 回退 | Node 404 + legacy 真实 UI | 通过；使用 /api/state |
| 初始化失败恢复（补充） | 真实 UI：状态 503 → 编辑 → 恢复 | 通过；journal 记录 1 条，恢复后写入且二次刷新仍在 |

## 8. 实际前端验证摘要

平台：Windows 11，pywebview 6.2.1，WebView2 Runtime 152.0.4191.66，真实窗口隐藏驱动，真实 FastAPI/uvicorn 子进程，临时 SQLite。

- v2 初始 3 条旧快照迁移笔记；创建“B2 v2 新建”后编辑为“B2 v2 已编辑”，revision 2→3；收藏→4；标签→5；删除→6；恢复→7。
- 服务器修改到 revision 3 后，界面提交冲突内容，弹出“检测到编辑冲突”，选择“保留我的修改”，最终 revision 4，服务端与界面一致。
- 停止服务后编辑“B2 断网本地保留”，状态显示“保存失败，内容已保存在本地”；同端口重启并重试，内容写入成功。
- 刷新后 4 条笔记、ID 唯一、状态“已保存”。
- 关闭窗口后重新打开，4 条笔记仍在。
- pending / failed 模式全程没有 V2 数据写入。
- 状态接口 503 时，界面进入“服务未连接 · 本地缓存”，编辑后 journal 记录 1 条；恢复并刷新后该笔记写入 V2，库内 live 笔记从 2 条变为 3 条，二次刷新仍在。

## 9. 已知限制

- 仍未迁移真实用户库；需要单独授权与停写窗口。
- 状态接口失败时的旧版恢复合并是最后写入者优先，没有 revision 保护；v2_ready 路径仍有 409 冲突保护。
- journal 合并发现冲突时显示冲突状态，但没有独立冲突列表弹窗；下一次保存走 409 流程。完整冲突中心可在 B3 做。
- localStorage 同时存缓存与 journal，大图片笔记接近 5MB 配额时可能失败；界面会提示，不会清空正文。
- 多标签页同时编辑未做跨页协调；revision 仍能防止静默覆盖。
- 旧标签同步按名称对齐，重名标签的极端情况未覆盖。
- 未测试真实浏览器（Chrome/Edge）路径；真实窗口使用 WebView2。DataPort 是标准 fetch，Node 已覆盖协议层。
- 测试依赖本机 WebView2；无 WebView2 的机器会跳过 UI 用例，并明确显示 skip。

## 10. 请求授权

B2 已完成并按约定暂停。请验收：

1. 是否接受 B2 当前实现与已知限制；
2. 是否授权 B3（迁移执行方案/真实库迁移窗口，或冲突中心与旧数据收尾）；
3. 真实库迁移的时间、操作人和备份位置。

未收到授权前：不合并 PR、不推送 main、不迁移真实库、不开始 AI/UI/安装包开发。
