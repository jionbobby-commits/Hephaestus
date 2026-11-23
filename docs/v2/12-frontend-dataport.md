# 前端 DataPort 与兼容层（B2）

状态：B2 已实现，等待验收。分支 feat/v2-cross-platform。基线 main / 3e341a5；B2 起点 727f9c0。

## 1. 目标与边界

B2 只做前端数据访问适配：

- 现有 UI 不直接调用 fetch、SQL 或数据库。
- 未迁移的库继续使用旧 /api/state，旧版前端行为不变。
- 迁移完成后使用 /api/v2，新前端不再写旧快照。
- 同一份数据同一时间只有一个写入源，禁止双写。
- 保存失败、刷新、关闭窗口、版本冲突时不丢内容。
- 不迁移真实用户库，不删除 frontend_state，不重写历史，不合入 main。

本阶段不做 AI、附件上传、i18n、主题扩展、移动端壳和安装包。

## 2. 分层

~~~text
static/index.html / script.js（UI、Store）
        |
        v
static/dataport.js（唯一的网络层）
        |
        +-- /api/v2/status   数据模式检测（只读）
        +-- /api/v2/*        迁移完成后的读写
        +-- /api/state       旧版快照读写（仅 legacy / pending / failed）
~~~

static/index.html 先加载 dataport.js，再加载 script.js。Store 是页面内唯一的数据协调者；界面事件只改 Store.data，然后调用 Store.save / Store.flush。

## 3. 数据模式状态机

GET /api/v2/status 由 app/v2/status.py 只读检测，app/v2/api.py 暴露。返回 data_mode：

| data_mode | 条件 | 前端适配器 | 写入目标 |
|---|---|---|---|
| legacy | 没有 v2_* 表 | legacy | /api/state |
| migration_pending | v2 表不完整，或缺迁移标记 | legacy | /api/state |
| migration_failed | v2_import_meta 中 migration_status=failed/failed 状态 | legacy | /api/state |
| v2_ready | 完整 v2 表 + v2_schema_migrations version=1 | v2 | /api/v2 |

判定顺序在 app/v2/status.py 的 detect_data_mode 中固定：显式 failed -> 显式 pending -> 无表 -> 表不完整 -> 缺迁移标记 -> V2 读取错误 -> v2_ready。

前端在 Store 中保留 mode / modeLabel，界面的存储空间卡片显示当前状态（旧版快照、迁移待定 · 旧版兼容、迁移失败 · 旧版兼容、V2 数据、V2 · 服务未连接）。

### 3.1 状态接口失败时停止写入

- 只有 HTTP 404/405 表示“旧服务端没有 /api/v2/status”，此时才回退 /api/state。
- 网络错误、超时、5xx、未知响应都抛 DataPortError(status_unavailable)，Store 不初始化写入路径；本地缓存仍可浏览，编辑会写入恢复日志，服务恢复后刷新页面或重试时自动合并。
- 这样避免迁移后的库因一次状态接口故障被旧快照再次写入，形成两个写入源。

### 3.2 初始化失败恢复

如果页面能打开但 `/api/v2/status` 暂时不可用，Store 进入 `unknown` 模式（界面显示“服务未连接 · 本地缓存”），并：

1. 只把相对页面初始快照发生变化的笔记写入 journal，`reason` 标记为 `init_failed`，`base` 为空。
2. 不调用 `/api/state`，也不调用任何 `/api/v2` 写接口。
3. 下一次成功启动时，v2_ready 走正常 journal 合并；旧版快照模式按“同 id 本地优先、其余服务器优先”合并，然后写回 `/api/state`。
4. 旧版合并是最后写入者优先，状态接口长时间不可用且同一笔记在多处修改时可能覆盖一次服务器改动；这是旧快照协议本身的限制，v2 模式仍有 revision 冲突保护。

## 4. 数据操作映射

| 界面动作 | V2 方法 | 旧版方法 |
|---|---|---|
| 读取全部数据 | GET /api/v2/tags + /settings + 分页 /notes?trashed=false/true | GET /api/state |
| 新建 | POST /api/v2/notes | PUT /api/state |
| 修改 | PATCH /api/v2/notes/{id}，带 revision | PUT /api/state |
| 收藏 | PATCH /api/v2/notes/{id}/favorite | PUT /api/state |
| 删除/回收站 | DELETE /api/v2/notes/{id}（软删除） | PUT /api/state |
| 恢复 | POST /api/v2/notes/{id}/restore | PUT /api/state |
| 永久删除 | DELETE /api/v2/notes/{id}?permanent=true | PUT /api/state |
| 标签增删改 | /api/v2/tags | PUT /api/state |
| 设置 | PATCH /api/v2/settings | PUT /api/state |

V2 请求统一 12 秒超时，credentials: same-origin，409 映射为 ConflictError。旧版适配器仍使用原有字段与 350ms 防抖，保持旧服务端兼容。

标签映射按名称对齐：本地标签 ID 与服务器 ID 不同时，先用名称查找，找不到再创建，随后把笔记标签替换成服务器 ID，避免重复标签。

## 5. 待同步日志（journal）

localStorage 键：hephaestus.v2.pending，版本 1。

~~~json
{
  "version": 1,
  "savedAt": 1710000000000,
  "notes": [],
  "tags": [],
  "ui": {},
  "base": { "note-id": { "serial": "...", "revision": 3, "fav": false, "trashed": false } },
  "baseTags": { "tag-id": { "name": "工作", "color": "#7c83e6" } }
}
~~~

规则：

1. V2 模式下每次 save/flush，在发起网络请求前写入 journal；base 记录当时服务器基线。
2. 只有一次完整 reconcile 成功后才清除 journal；任何失败都保留。
3. 页面重新加载时先读取服务器快照，再合并 journal：
   - 服务器与本地相同：采用服务器版本。
   - 本地有基线且服务器未变：保留本地修改，随后 PATCH。
   - 双方都改：保留本地并标记版本冲突。
   - 本地删除、服务器未变：保持删除，随后 DELETE。
   - 服务器删除、本地修改：保留本地并标记冲突。
   - 本地新建（服务器没有该 id）：保留并创建。
   - 同 id 但无基线（例如 V2 读取失败期间的编辑）：保留本地并标记冲突，不静默覆盖服务器。
4. V2 服务未连接（blocked）时仍写 journal，避免刷新丢内容；但不会发起写入。
5. 标签合并只删除 journal.baseTags 中记录、且本地确实删除的标签，不误删服务器新增标签。
6. 启动阶段状态接口失败时写 `reason: "init_failed"` 的恢复日志，只包含相对页面初始快照变化的笔记；下次启动按目标模式合并后清除。旧版快照模式无法表达 revision，同 id 笔记按本地优先合并。

媒体图片仍以 data:image 形式存在笔记 HTML 中；journal 会复制这部分数据，接近 5MB 配额时可能写入失败，界面会显示存储空间不足。附件拆分属于阶段 E。

## 6. 保存状态与冲突

保存状态文案：

- 已保存
- 保存中…
- 等待保存…
- 保存失败，内容已保存在本地
- 服务未连接，修改已保存在本地
- 版本冲突，请选择保留内容

PATCH 返回 409 时弹出“检测到编辑冲突”对话框，显示服务器 revision，提供：

- 保留我的修改：使用服务器 revision 重新提交本地内容。
- 重新加载服务器：放弃本地这篇笔记的修改。
- 稍后处理：保留冲突标记，不覆盖服务器。

保存失败时不清空正文、不退出编辑、不删除本地缓存；恢复连接后 Store.retry 重新打开适配器并合并 journal。

## 7. 代码位置

- static/dataport.js：UMD 包装，浏览器挂 window.HephaestusDataPort，Node 可直接 require；唯一网络层。
- static/script.js：Store 状态、journal、reconcile、冲突处理；UI 只调用 Store。
- static/index.html：脚本加载顺序。
- app/v2/status.py：只读模式检测。
- app/v2/api.py：GET /api/v2/status。
- tests/frontend/dataport.test.cjs：Node 内置测试，无 npm 依赖。
- tests/frontend/ui_verify.py、ui_fixtures.py：真实 WebView2 操作验证。
- tests/frontend/recovery_verify.py：状态接口 503 时编辑、恢复、二次刷新的真实窗口验证。
- tests/frontend/status_fail_app.py：只让 `/api/v2/status` 返回 503 的测试 ASGI 包装。
- tests/test_v2_status.py：模式判定 API 测试。
- tests/test_v2_ui.py：真实窗口 pytest 包装（含初始化失败恢复）。

## 8. 已知限制

- 尚未迁移真实库；所有 v2_ready 验证都在独立临时库。
- journal 合并发现冲突时目前显示冲突状态，但没有单独的“选择保留哪一份”弹窗；下一次保存或重新加载时按 409 流程处理。专门的冲突列表属于后续 B3。
- 旧标签同步以名称对齐，重名标签的极端情况未覆盖。
- 本地缓存与 journal 各存一份数据，大图片笔记可能先触发 5MB localStorage 配额。
- 未做多标签页同时编辑同一笔记的协调；最后写入者仍受 revision 保护。
- 移动端 DataPort 未接入本前端 Store；阶段 G 接入 Capacitor。
