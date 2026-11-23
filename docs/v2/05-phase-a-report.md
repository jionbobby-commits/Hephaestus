# Hephaestus V2.0 阶段 A 报告

> 日期：2026-11-23
> 分支：`feat/v2-cross-platform`（从 `main` 的 `3e341a5` 创建）
> 状态：阶段 A 完成；实现未开始，等待架构决策确认。

## 1. 本阶段做了什么

1. 检查本地 Git：分支、HEAD、工作区、remote、已有分支、stash。
2. 通过 GitHub API 核对远端仓库、默认分支、最新提交、Release、issue、license。
3. 运行现有完整测试：60 passed，1 warning，44.68s。
4. 阅读后端、前端、桌面、打包、安装器、CI 的实际代码。
5. 只读检查用户数据库和仓库数据库的表/行数/JSON 快照。
6. 识别跨平台、数据迁移、AI、i18n、附件、存储、测试和发布风险。
7. 形成架构决策、开发计划、风险登记。

## 2. 关键发现（按严重度）

### 2.1 真实数据不在 notes 表

用户数据库 `%LOCALAPPDATA%/Hephaestus/hephaestus.db`：

- `frontend_state`：1 行，payload 含 **7 条笔记、4 个标签**，theme=dark；
- `notes`：**0 行**。

当前前端只调用 `/api/state`，不调用 `/notes`。因此 V2 迁移必须以 `frontend_state` 为源，不能只迁移 `notes` 表。

### 2.2 前端是产品主体，但不是可移植架构

- `static/script.js` 598 行、`static/index.html` 119 行、`static/style.css` 245 行；无构建、无框架、无模块。
- 数据保存：localStorage 整包 + 350ms 防抖 `PUT /api/state`（`script.js:84-99`）。
- 启动：`GET /api/state`（`script.js:101-122`），未初始化时把本地整包推上去。
- localStorage 配额硬编码 5MB（`script.js:58`）；图片以 base64 写入笔记 HTML（`script.js:447-453`），是主要容量风险。
- 全部界面中文、`lang=zh-CN`；主题仅 light/dark（`script.js:546`）；原生 select；无附件/拖放/i18n/RTL。

### 2.3 移动端不能直接复用 Python 后端

- FastAPI + SQLite + pywebview 是桌面形态；iOS 不能这样启动 Python HTTP 服务，Android 也不适合。
- pywebview 无 iOS/Android 支持；Capacitor 只包 WebView，不提供 Python。
- 因此移动端必须有独立的本地 SQLite/文件存储实现；这是阶段 B 的前置决策。

### 2.4 Windows 专用代码遍布桌面/打包层

- `desktop/main.py`、`desktop/runtime.py`、`desktop/dialogs.py`、`desktop/paths.py`、`desktop/single_instance.py`。
- `build/Hephaestus.spec` 是 Windows PyInstaller；`installer/Hephaestus.iss` 是 Inno Setup。
- `app/release.py` 只描述 Windows 下载。
- 需要平台适配层，不能把 Windows 路径/注册表/WebView2 写进公共代码。

### 2.5 测试全绿但覆盖不等于产品

- 60 个测试覆盖 Python API/桌面/健康检查/Windows 安装；
- 没有前端浏览器测试、附件测试、AI 测试、i18n/RTL 测试、移动端测试；
- `tests/test_api.py` 的 lifespan 仍会对真实 `DATABASE_URL` 执行 `create_db()`，测试隔离有缺陷。

### 2.6 环境缺工具链

- 无 Node/npm、JDK、Android SDK、Xcode、WSL；
- 本机只能完成 Windows/Web 的代码、测试和 Windows 打包；
- 不能在本机真实构建/验证 macOS DMG、Linux DEB、Android APK、iOS IPA。

## 3. 架构建议

推荐 **方案 A**：

- 桌面/Web 保留 Python FastAPI + SQLite；
- 移动端用 Capacitor 壳 + 原生 SQLite + TypeScript 数据层；
- 共享 `static/` UI、i18n、设计 token 和 JSON 契约；
- 用 `DataPort` 隔离 WebBackend 与 MobileNative；
- 不做云同步。

理由：最大化复用现有前端/Windows 桌面；避免把 Python 强行塞进 iOS/Android；不重写整个产品。

代价：移动端有第二套数据/AI 实现，需要契约测试防止漂移。

详细比较见 `02-architecture-decision.md`。

## 4. 本阶段产出

| 文件 | 内容 |
|---|---|
| `docs/v2/01-current-state.md` | 仓库、测试、运行架构、真实数据、平台/工具链事实 |
| `docs/v2/02-architecture-decision.md` | 四种方案比较、推荐 A、组件/数据/密钥设计、决策请求 |
| `docs/v2/03-development-plan.md` | 阶段 B–H 的范围、交付、验收、测试矩阵、回滚 |
| `docs/v2/04-risk-register.md` | 20 项风险、阻塞项、停止条件 |
| `docs/v2/README.md` | 文档索引 |
| `docs/v2/05-phase-a-report.md` | 本文件 |

## 5. 本阶段没有做的事

- 没有修改业务代码、前端、桌面、打包脚本。
- 没有执行数据库迁移，没有写入/删除用户数据库或附件。
- 没有合并 PR，没有推送 main，没有重写 Git 历史。
- 没有安装 Node/Android SDK/Xcode，没有伪造跨平台构建。
- 没有调用第三方 AI，没有上传任何笔记。

## 6. 需要确认的决策

1. 是否批准方案 A（Python 桌面/Web + Capacitor 移动 + 原生 SQLite + 双数据适配器）？
2. 是否接受移动端首版功能子集（笔记/标签/收藏/回收站/附件/在线 AI/10 语言/RTL，不含 Ollama/云同步/协作）？
3. 是否提供 macOS/Xcode/Apple 签名、Linux/WSL/Docker、Android SDK/JDK 构建环境？

没有这三项确认，进入阶段 B 会产生架构返工或无法交付的安装包。

## 7. 下一步（确认后）

1. 阶段 B1：数据契约 + 迁移框架，在用户数据库副本上演练。
2. 阶段 B2：`/api/v2` + 旧 API 兼容层。
3. 阶段 B3：前端 `DataPort`，保留现有 Windows UI 外观。
4. 阶段 B4/B5：桌面平台适配 + Capacitor 工程骨架。
5. 每个阶段结束跑测试、检查 diff、提交阶段报告。

## 8. 证据边界

本报告的事实来自实际 Git/GitHub 查询、pytest 运行、源码阅读和 SQLite 只读查询。没有进行真机移动端运行、macOS/Linux 构建、AI 服务调用；相关结论标记为“待构建/待真机验证”。