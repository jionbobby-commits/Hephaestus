# Hephaestus V2.0 阶段 A：跨平台架构决策

> 状态：提案。需要在进入阶段 B 前由产品负责人确认。
> 本文不宣称任何平台构建已完成。

## 1. 问题定义

V2.0 同时要求：

- Windows、macOS、Linux 桌面端；
- Android、iOS 移动端；
- 保留 Web 入口；
- 本地优先，离线可编辑；
- 统一笔记/附件/设置模型；
- AI（桌面含 Ollama，移动端仅在线）；
- 10 种语言、RTL、主题、附件、存储管理；
- 各平台安装包。

现有实现把 Python FastAPI、SQLite、pywebview 和 Windows 打包绑在一起。核心约束是：

1. iOS 不能以桌面方式运行 Python HTTP 服务；Android 也不适合把 uvicorn 作为应用内后端。
2. pywebview 没有 iOS/Android 运行时；Capacitor 只提供 WebView 壳和原生插件，不提供 Python 运行时。
3. 现有前端是 598 行 IIFE 单文件，数据层是整包 JSON；直接把它搬进移动端会同时遇到 5MB localStorage 配额和 WebView 生命周期问题。
4. 当前 `notes` 表没有真实数据；真实数据在 `frontend_state` JSON。

因此必须先决定：**移动端的本地数据层由谁实现，以及桌面端是否继续保留 Python。**

## 2. 候选方案

### 方案 A：共享 Web UI + Python 桌面/Web 后端 + Capacitor 移动壳 + 移动原生 SQLite

```text
                 +-----------------------------+
                 | static/ (shared UI)         |
                 | i18n, theme, components     |
                 +--------------+--------------+
                                |
                +---------------+----------------+
                |                                |
     DataPort: WebBackend                 DataPort: MobileNative
     (fetch /api/v2)                      (Capacitor plugin)
                |                                |
     FastAPI + SQLite                    Native SQLite
     Windows/macOS/Linux/Web             Android/iOS
     Python service                      Kotlin/Swift + TS adapter
```

- 桌面/Web：继续使用 Python FastAPI + SQLite，新增 `/api/v2`，保留 `/api/state` 兼容层。
- 移动：Capacitor 壳加载同一套 `static/` UI；用 `@capacitor-community/sqlite`（或等价原生 SQLite 插件）保存笔记/标签/附件元数据；文件用原生文件系统插件保存。
- 共享层：同一套 HTML/CSS/JS、i18n 资源、设计 token、JSON 数据契约；通过 `DataPort` 接口按平台注入实现。
- AI：桌面端 Python provider 适配器；移动端 TypeScript provider 适配器；两者遵守同一请求/事件契约。
- 不在任何平台实现云同步。

**结论：Capacitor 适合做移动端 UI 壳，但不适合“原样运行现有 Python 后端”。推荐采用 A，前提是接受移动端存在独立的 TypeScript 数据层。**

### 方案 B：Tauri v2 全平台

- Rust 核心 + SQLite，Web UI 共享；桌面和移动都由 Tauri 打包。
- 优点：单一原生壳、体积较小、安全存储/文件系统插件成熟。
- 缺点：现有 Python 业务逻辑、FastAPI Web 入口、60 个 Python 测试、PyInstaller/Inno 流程都要重写或废弃；需要 Rust 工具链和每个平台的构建机；对“保留现有 Windows 版”风险最高。
- 结论：不作为 V2.0 主方案；可作为 V3 的重构选项。

### 方案 C：Python 移动端（BeeWare / Chaquopy / Kivy）

- 在 Android/iOS 内嵌 Python，尝试复用 FastAPI/model。
- 缺点：UI 无法复用现有 HTML/CSS/JS；iOS 对动态代码/进程限制严格；包体大；后台服务模型不符合移动系统；维护成本高。
- 结论：不推荐。

### 方案 D：Capacitor + 内嵌 Python 服务

- Android 用 Chaquopy，iOS 用 Python-Apple-support，启动本地 HTTP 服务。
- 缺点：iOS App Store 审核和进程/网络限制风险高；启动慢、包体大；pywebview 不可用；仍要写原生插件。
- 结论：不推荐。

## 3. 推荐架构（A）

### 3.1 仓库分层

```text
app/                    Python FastAPI：v1 兼容 + v2 领域/API
  api/v1/              现有 /notes、/api/state（冻结兼容）
  api/v2/              新规范化 API
  models/              SQLAlchemy 模型
  services/            笔记、标签、附件、设置、AI、备份
  ai/                  provider 适配器、密钥引用、流式桥接
  migrations/          版本化迁移 + 备份
static/                共享前端（渐进模块化，不引入框架）
  locales/             10 语言资源
  js/                  数据端口、组件、页面
desktop/               平台适配：窗口、路径、单实例、安全存储
  platforms/win.py, mac.py, linux.py
mobile/                Capacitor 工程 + TS 本地数据层
  src/data/            SQLite/文件系统适配器
  android/ ios/        原生工程（需对应工具链）
packaging/             PyInstaller/Inno/DMG/DEB/CI 脚本
docs/v2/               本阶段文档
tests/                 Python + 契约 + 前端 + 平台测试
```

保留 `static/` 路径可以降低 Windows 打包风险；不立即重命名。新前端代码可以逐步拆到 `static/js/`，但首版不引入 React/Vue，避免重写全部 UI。

### 3.2 统一数据契约

所有平台使用同一份 JSON Schema/TypeScript 类型（由 Python Pydantic 生成或手工维护并以契约测试锁定）：

```text
Note: id, title, content_html, content_text, category, tags[], is_favorite,
      is_trashed, created_at, updated_at, revision, attachments[]
Tag: id, name, color, created_at
Attachment: id, note_id, original_name, mime, size, sha256, kind, created_at
Settings: locale, theme, assistant_name, assistant_style, response_length,
          default_model, editor_prefs
AIProvider: id, kind, label, base_url, model, has_key (never key itself)
```

移动端和桌面端字段必须一致；`revision` 用于并发冲突检测。时间统一 ISO-8601 UTC，UI 按 locale 显示。

### 3.3 数据存储

- 桌面/Web：SQLite，新增 `schema_version`、`notes`(TEXT id)、`tags`、`note_tags`、`attachments`、`settings`、`ai_*`、`migrations`。
- 移动：原生 SQLite，同样表结构；附件文件放在应用私有目录（Android `filesDir` / iOS Application Support）。
- 图片：V2 新插入图片作为附件保存，正文只存 `attachment://<id>` 引用；迁移时把旧 data URL 提取为附件（可选但推荐）。
- 缓存：缩略图在 `cache/thumbnails`，可清；原始附件不可被缓存清理删除。
- 备份：数据库快照 + 附件目录 + manifest 校验和，打包为 zip；恢复先写 staging，校验后原子替换。

### 3.4 桌面端

- 继续使用 pywebview（Windows WebView2、macOS WKWebView、Linux WebKitGTK），保留 FastAPI 本地服务。
- 平台适配层隔离：数据目录（`%LOCALAPPDATA%` / `~/Library/Application Support` / `$XDG_DATA_HOME`）、单实例、窗口、日志、文件选择器、系统安全存储、打开文件。
- Windows 继续 PyInstaller + Inno；macOS 用 PyInstaller `.app` + `hdiutil` DMG；Linux 用 PyInstaller + `.deb`（需在 Linux 构建）。
- macOS/Linux 的代码可以先写，但没有对应机器时只能标记“未构建/未验证”。

### 3.5 移动端

- Capacitor 壳 + 本地静态资源；不使用远程 URL 作为主界面。
- 本地 SQLite：Android/iOS 原生插件；若插件不能满足事务/迁移，写最小原生桥接。
- 附件：Android SAF/文件选择器，iOS UIDocumentPicker；文件复制到应用私有目录后记录元数据。
- 安全存储：Android Keystore / iOS Keychain 插件；API Key 不进入 WebView localStorage/SQLite。
- 移动端首版只做在线 AI；离线时笔记完整可用，AI 入口显示不可用原因。
- 响应式：桌面三栏，移动单栏 + 底部导航；适配安全区、状态栏、系统返回键/手势。

### 3.6 AI 与密钥

- 桌面 provider 适配器在 Python 中实现；移动在 TypeScript 中实现；请求格式按 provider 分开，禁止共用 OpenAI 格式硬套 Anthropic/Gemini。
- 桌面密钥：`keyring`，Windows Credential Manager / macOS Keychain / Linux Secret Service。若 Linux 无 Secret Service，明确报错，不回退明文。
- 移动密钥：Capacitor 安全存储插件（Keychain/Keystore）；不写日志、不回传前端完整值。
- Ollama 仅桌面：`/api/tags` 列模型，`/api/chat` 流式；不自动 pull，不默认加载大模型。
- 在线 provider：OpenAI-compatible、Anthropic、Gemini、DeepSeek、Qwen；自定义 base URL/model；连接测试；超时/重试/错误映射。
- 任何会把笔记正文发给第三方的操作，必须由用户显式触发，并在发送前展示“将发送哪些内容、发往哪个服务”。

## 4. 为什么不是“只加一个 Capacitor 壳”

Capacitor 的职责是：

- 提供 WebView 容器；
- 提供原生插件桥（文件、SQLite、安全存储、分享）；
- 生成 Android/iOS 工程。

它不提供：

- Python 解释器/uvicorn 服务；
- 现有 SQLite 文件的自动跨平台读写；
- 桌面 pywebview 的窗口/单实例/文件对话框行为；
- 自动的数据模型迁移。

因此移动端必须新增一个 TypeScript 本地数据层。接受这一点，Capacitor 才是合适方案。

## 5. 双数据层的一致性策略

这是方案 A 的最大成本，必须显式管理：

1. 以 `docs/v2/contract/` 的 JSON Schema 作为唯一字段定义。
2. 同一组契约 fixture 同时跑 Python 和 TypeScript 测试：创建、PATCH、软删除、恢复、标签、附件、冲突、分页、RTL 无关。
3. API 响应与移动端 repository 返回同一 shape；字段重命名必须同时改两端。
4. 迁移脚本有版本号；两端 `schema_version` 必须匹配；不匹配时拒绝启动写入并提示升级。
5. 不考虑自动云同步；跨设备迁移用显式导出/导入（后续版本再设计同步）。

## 6. 决策请求

进入阶段 B 前，需要确认以下三项：

1. **是否批准方案 A**（Python 桌面/Web + Capacitor 移动 + 移动原生 SQLite + 两套数据适配器）？
2. **是否接受“移动端首版功能子集”**：笔记/标签/收藏/回收站/附件/在线 AI/10 语言/RTL；不包含 Ollama、云同步、协作？
3. **构建资源**：是否提供 macOS（Xcode + Apple Developer 签名）、Linux（或 WSL/Docker）、Android SDK/JDK 的构建环境？没有这些环境时，只能交付可构建工程/未签名产物，不能交付可安装的 DMG/IPA/APK/DEB。

如果否决方案 A，备选是 B（Tauri v2 全平台重写）或“先只做 Windows/Web V2，移动端另立项目”。这两条都会改变工作量和风险，不能在不确认的情况下开工。

## 7. 决策记录

| 日期 | 决策 | 状态 |
|---|---|---|
| 2026-11-23 | 阶段 A 完成，推荐方案 A | 待产品负责人确认 |