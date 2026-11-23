# Hephaestus V2.0 阶段 A：现状审查

> 状态：只读审查已完成。本文是事实记录，不代表 V2 功能已经实现。
> 审查日期：2026-11-23（Asia/Singapore）
> 仓库：Hephaestus 本地工作副本（路径按机器而异）

## 1. 结论摘要

当前 Hephaestus 是一个可运行的 Windows 本地笔记应用，但它不是“一个 FastAPI 后端 + 一套前端 + 多平台封装”的形态。真实情况是：

- 产品界面是一个 598 行的原生 JavaScript 单页应用，业务数据由浏览器 localStorage 和 `/api/state` 的整包 JSON 快照承担。
- `/notes` 系列 CRUD API 存在且有测试，但当前前端从不调用它们；真实用户笔记也不在 `notes` 表里。
- 桌面端是 Windows 专用的 pywebview + WebView2 + PyInstaller + Inno Setup 流程，不能直接复制到 macOS/Linux。
- 移动端没有工程、没有 Node/Android/iOS 工具链，也没有可在 iOS/Android 内运行的 Python 后端。

因此 V2.0 不是“增加打包目标”，而是一次数据层、前端架构和发布体系的升级。必须先做架构决策，再改代码。

## 2. 仓库与发布状态

| 项目 | 实测结果 |
|---|---|
| 当前分支 | `main` |
| HEAD | `3e341a5aeb486fb825fae2f71a0c9f7955ba040f` |
| 工作区 | 干净 |
| `origin/main` | 与本地 HEAD 一致 |
| 其他本地分支 | `feat/v1-api-completion`(1589200)、`feat/v1.3-release`(3e341a5)、`feat/windows-desktop-v1.1`(cba7b20)、`feat/windows-release-v1.2`(761f416) |
| 远端 | `https://github.com/jionbobby-commits/Hephaestus.git` |
| GitHub 仓库 | public，default_branch=main，main=3e341a5，0 open issues，1 star，license=null |
| 最近推送 | 2026-11-22T12:45:49Z |
| Release | v1.3.0 已发布，含 installer / portable / onefile 资产 |
| 特殊状态 | 存在一个 stash：`stash@{0} On feat/windows-release-v1.2: !!GitHub_Desktop<feat/windows-release-v1.2>`；本任务不读取、不修改、不丢弃 |

注意：仓库没有 LICENSE 文件。V2 对外发布前需要产品负责人决定许可证；本阶段不擅自选择。

## 3. 测试基线

```text
.venv/Scripts/python.exe -m pytest -q
60 passed, 1 warning in 44.68s
```

唯一 warning 是 Starlette 对 `httpx` + `TestClient` 的弃用提示（建议安装 httpx2），不影响本次结果。

测试分布：

| 文件 | 数量 | 覆盖范围 |
|---|---:|---|
| `tests/test_api.py` | 18 | FastAPI 笔记 CRUD、搜索、PATCH/PUT、收藏、状态接口 |
| `tests/test_desktop.py` | 25 | 桌面入口、健康检查、WebView2 检测、self-test、参数 |
| `tests/test_healthcheck.py` | 15 | 健康检查 URL、超时、连接失败、watchdog |
| `tests/test_installer.py` | 2 | Windows 安装/升级/卸载数据保留 |

覆盖缺口：没有前端浏览器测试、没有附件测试、没有 AI 测试、没有 i18n/RTL 测试、没有 macOS/Linux/Android/iOS 构建测试。现有 60 个测试全绿，只能证明它们覆盖的 Python 路径，不能证明产品界面使用了这些 API。

### 3.1 测试隔离问题

`tests/test_api.py:10-31` 用内存 SQLite 和 `dependency_overrides[get_db]`，但 `TestClient(app)` 的 lifespan 仍会执行 `app/main.py:18` 的 `create_db()`，而 `create_db()` 使用真实的 `DATABASE_URL`（`app/database.py:7`）。这会在仓库下创建 `data/hephaestus.db`。它不会删除用户数据（只有 `create_all`），但测试不是完全隔离的；V2 的迁移测试必须修复这一点。

## 4. 当前运行时架构

```text
+--------------------------- Windows desktop ---------------------------+
| pywebview 6.2.1 + WebView2                                            |
|   -> http://127.0.0.1:<random port>                                   |
|   -> FastAPI app.main:app                                             |
|   -> SQLite data/hephaestus.db (or %LOCALAPPDATA%/Hephaestus)          |
|   -> 静态文件 static/                                                  |
+-----------------------------------------------------------------------+

Web 模式：uvicorn app.main:app -> 同一套 static/ + 同一套 API
移动端：不存在
```

### 4.1 后端文件与真实职责

| 文件 | 行数 | 真实职责 |
|---|---:|---|
| `app/main.py` | 50 | FastAPI 实例、lifespan `create_db()`、静态目录、路由注册、`/health`、`/api/release`、`/download/windows` |
| `app/database.py` | 35 | 读取 `HEPHAESTUS_DATABASE_URL`，默认 `sqlite:///./data/hephaestus.db`；`create_db()` 仅 `Base.metadata.create_all` |
| `app/models.py` | 31 | `Note` 和 `FrontendState` 两张表 |
| `app/schemas.py` | 82 | `NoteCreate`/`NoteUpdate`/`NoteRead`/`NoteList`/`FrontendStatePayload` |
| `app/routers/notes.py` | 60 | `/notes` CRUD、PATCH、旧 PUT、收藏、筛选 |
| `app/routers/state.py` | 32 | `/api/state` 整包读取/保存 |
| `app/services/notes.py` | 58 | 搜索、筛选、排序、分页 |

当前模型：

```text
Note: id INTEGER PK, title VARCHAR(100), content TEXT, category VARCHAR(30),
      is_favorite BOOL, created_at DATETIME, updated_at DATETIME
FrontendState: id INTEGER PK, payload JSON, updated_at DATETIME
```

没有附件、标签关联、设置、AI 会话、回收站、迁移版本、版本号/并发控制字段。

### 4.2 API 现状

已存在：

- `GET /health`
- `GET /api/release`、`GET /download/windows`（Windows 发布元数据/下载）
- `GET/POST /notes`、`GET/PATCH/PUT/DELETE /notes/{id}`
- `GET /notes/favorites`、`PATCH /notes/{id}/favorite`
- `GET/PUT /api/state`

`NoteCreate.title` 最大 100（`app/schemas.py:8`），但前端标题输入框 `maxlength=120`（`static/index.html:105`）。如果 V2 让前端改走 `/notes`，现有 101-120 字的标题会得到 422。

`/api/state` 的 payload 校验很宽：`FrontendStatePayload` 允许额外字段，只检查 notes 数量不超过 10000、tags 不超过 1000（`app/routers/state.py:23`）；没有逐条笔记校验，也没有请求体总大小限制。

### 4.3 前端现状

`static/index.html` 119 行、`static/style.css` 245 行、`static/script.js` 598 行。没有构建步骤，没有 npm，没有模块化，没有框架。

关键事实：

- `static/index.html:2`：`<html lang="zh-CN">`，没有 locale/RTL 机制。
- `static/script.js:58`：`const KEY = 'hephaestus.v1', QUOTA = 5 * 1024 * 1024;`。localStorage 只有 5MB 配额。
- `static/script.js:78-82`：加载 localStorage，缺省用 7 条演示笔记；`ui` 默认 `theme: "light"`，不是跟随系统。
- `static/script.js:84-99`：每次保存先写 localStorage，再 350ms 防抖 `PUT /api/state`。
- `static/script.js:101-122`：启动时 `GET /api/state`，若后端未初始化则把本地整包推上去。
- `static/script.js:546`：主题按钮只在 dark/light 之间切换，没有 system。
- `static/script.js:581`：唯一另一个 API 调用是 `GET /api/release`。
- 全文没有 `fetch("/notes")`，因此 `/notes` CRUD 在产品 UI 中是死路径。
- 所有界面文字硬编码在 HTML/JS 中；`localeCompare(..., "zh")` 固定中文排序（`static/script.js:285`）。
- 原生 `<select id="headingSel">`；没有统一的自定义下拉/菜单/日期组件体系。
- 图片插入：`FileReader` 读入，canvas 压缩到最大 1200px，`toDataURL("image/jpeg", .82)` 后直接写进笔记 HTML（`static/script.js:447-453`）。图片以 base64 存在整包 JSON 和 localStorage 里，是 5MB 配额的主要消耗者。
- 粘贴图片同样走 data URL（`static/script.js:500-503`）。
- 没有附件模型、拖放上传、附件预览、音频播放、存储管理页面。
- `trashed`、`tags` 是前端 JSON 字段；后端没有标签表，也没有软删除/恢复 API（`DELETE /notes/{id}` 是硬删除）。

### 4.4 真实数据在哪里

对用户数据库 `%LOCALAPPDATA%/Hephaestus/hephaestus.db` 做了只读检查（不写入）：

| 表 | 行数 | 说明 |
|---|---:|---|
| `frontend_state` | 1 | payload 含 7 条笔记、4 个标签，`ui={theme:dark, layout:list, sort:updated}` |
| `notes` | 0 | 规范化笔记表是空的 |

仓库内 `data/hephaestus.db` 也是同样两张表，两表均 0 行。

这推翻了“后端 notes 表是主数据源”的假设：真实用户内容目前只存在 `frontend_state.payload` 的 JSON 里。V2 迁移必须先导入这个快照，再写规范化表；不能只迁移 `notes` 表。

## 5. 桌面/打包现状

- `desktop/main.py:1` 明确写着 Windows 桌面端；`:115` 默认 `%LOCALAPPDATA%\Hephaestus`；`:222` 缺 WebView2 时退出；`:252` 使用 `webview.create_window`；`:314` 使用 `webview.start`。
- `desktop/runtime.py` 用 `winreg` 读 WebView2 版本，用 `MessageBoxW` 提示。
- `desktop/single_instance.py:27` 在 Windows 用命名互斥量，其他平台退化为端口检测。
- `desktop/dialogs.py:13` 非 Windows 分支只是 stderr fallback。
- `desktop/paths.py:31` 只从 `LOCALAPPDATA` 推导数据目录。
- `build/Hephaestus.spec` 是 Windows PyInstaller 配置，包含 WebView2 WinForms/Win32 二进制；`installer/Hephaestus.iss` 是 Inno Setup 6.5+ 的 Windows 安装脚本。
- `app/release.py` 只描述 Windows 下载；没有 macOS/Linux/Android/iOS 发布元数据。

现有 V1.3 桌面安装包、便携 ZIP、onefile 均已发布；V2 必须保留 Windows 现有功能和升级数据。

## 6. 环境与工具链

| 工具 | 状态 | 对 V2 的影响 |
|---|---|---|
| Python | `.venv` 3.15.2 | 可开发/测试 Python 后端 |
| pytest | 已安装 | 可跑现有 60 项 |
| Node/npm | 未安装 | 不能构建 Capacitor/现代前端 |
| Java/JDK | 未安装 | 不能构建 Android |
| Android SDK/adb/gradle | 未安装 | 不能生成 APK |
| Xcode/xcodebuild | 不存在 | 不能构建 macOS/iOS |
| WSL/Linux | 未安装 | 不能本机构建 DEB |
| Docker | 未确认可用 | 不能假定可做 Linux 构建 |

因此本机可以完成：Windows/Web 的 Python 后端、前端、Windows 打包、自动化测试。

本机不能完成：macOS DMG、Android APK、iOS IPA、Linux DEB 的真实构建与运行验证。没有 Apple 签名和 provisioning profile 时，更不能声称 IPA 可安装。

## 7. 关键矛盾与必须纠正的假设

1. **“现有 FastAPI + SQLite 可以直接搬上手机”不成立。** iOS 不允许以这种形态启动 Python HTTP 服务；Android 也不适合把桌面 uvicorn 进程当应用内后端。pywebview 没有 iOS/Android 支持。
2. **“前端已经在使用 notes API”不成立。** 当前 UI 只读写 `/api/state`，`/notes` 是测试覆盖但产品未使用的路径。
3. **“notes 表就是用户数据”不成立。** 真实数据在 `frontend_state.payload`，notes 表为空。
4. **“加一个 Capacitor 壳就能跨平台”不成立。** Capacitor 能包 Web UI，但不会把 Python 后端和 SQLite 带进 iOS/Android；移动端需要独立的本地存储实现。
5. **“现有测试全绿就能保证 V2”不成立。** 没有前端、附件、AI、i18n、RTL、移动端测试；桌面/安装测试只在 Windows。
6. **“直接把 V1 前端改成调用 /notes 即可”不成立。** 标签、回收站、图片 data URL、整包状态、离线 hydrate 等行为都需要迁移设计；否则会丢数据或破坏现有体验。

## 8. 本阶段没有做的事

- 没有修改任何业务代码。
- 没有改数据库，没有迁移，没有删除任何用户数据。
- 没有合并 PR，没有推送 main，没有重写历史。
- 没有安装 Node/Android SDK/Xcode，也没有伪造任何跨平台构建结果。

## 9. 证据边界

本文结论来自：Git 命令、GitHub API、现有 pytest 运行、源码逐文件阅读、对用户数据库的只读 SQLite 查询。没有进行真机移动端运行、没有 macOS/Linux 构建、没有第三方 AI 服务调用。未验证的部分在后续文档中明确标为“待构建/待真机验证”。