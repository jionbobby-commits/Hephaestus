# Hephaestus V2.0 开发计划

> 前提：阶段 A 文档已提交，方案 A 尚待产品负责人确认。未确认前不进入实现。
> 本文按用户定义的阶段 B–H 组织；每个阶段都有退出条件和回滚点。

## 0. 总体原则

1. 先数据层，后 UI；先兼容，后替换。
2. Windows V1.3 功能、Web 入口、现有用户数据必须保留。
3. 每个数据库变更前自动备份；迁移必须可回滚；不删除旧表/旧字段。
4. 不把 API Key、笔记正文、附件、数据库提交到 Git。
5. 不用一个平台的测试结果代表其他平台。
6. 每个阶段单独提交，保留可回滚 commit；阶段结束提交报告和测试记录。

## 阶段 B：统一跨平台架构与本地数据层

### B1. 数据契约与迁移框架

交付：

- `docs/v2/contract/`：Note/Tag/Attachment/Settings/AIProvider 的 JSON Schema。
- `app/models/`：`notes`（TEXT id）、`tags`、`note_tags`、`attachments`、`settings`、`ai_providers`、`ai_conversations`、`ai_messages`、`schema_migrations`。
- 迁移器：读取 `schema_version`，逐步执行 SQL/事务；启动前备份数据库到 `backups/pre-v2-<timestamp>/`。
- 旧数据导入：从 `frontend_state.payload` 导入 7 条真实笔记、4 个标签、`ui` 设置；保留未知字段到 `extra_json`，不丢数据。
- 旧内联图片：把 `<img src="data:image/...">` 提取为附件（可选开关），替换为 `attachment://<id>`；失败时保留原 data URL 并记录。
- 回滚脚本：停止应用、恢复备份、保留新表供诊断，不强删。

验收：

- 在真实用户数据库的**副本**上迁移成功；原库字节不变。
- 迁移前后笔记数、标签数、收藏数、回收站数一致；正文/图片可读。
- 迁移中断（模拟异常）后能恢复备份，应用可启动。
- 重复执行迁移幂等。

### B2. `/api/v2` 领域 API

交付：

- 笔记：列表（分页、搜索、标签、分类、收藏、回收站）、详情、创建、PATCH、软删除、恢复、永久删除。
- 标签：列表、创建、重命名、改色、删除（先解除关联）。
- 设置：locale/theme/assistant 配置；不含密钥。
- 并发：`revision` 字段；PATCH 带 `If-Match`/`revision`，冲突返回 409。
- 兼容：保留现有 `/notes` 旧路由和 `/api/state`；可另行增加 `/api/v1` 版本化别名。`/api/state` 进入“旧版只读/迁移提示”模式，避免与 v2 双写冲突。
- 错误码：400/401/403/404/409/413/422/429/500 的稳定 JSON 结构。

验收：

- OpenAPI 文档与实际响应一致。
- 现有 18 个 API 测试改为显式使用 v1；新增 v2 测试覆盖全部分支。
- 迁移后 v1 只读仍能取到旧快照；写入返回明确 409/410 和升级提示。

### B3. 前端数据端口与渐进迁移

交付：

- `DataPort` 接口：`listNotes/getNote/createNote/updateNote/trash/restore/delete/listTags/...`。
- `WebBackendPort`：调用 `/api/v2`。
- `MobileSqlitePort`：Capacitor 插件实现（阶段 G 接入原生工程）。
- 首版保留现有 UI 外观，但把“整包保存”改成“笔记级保存”，350ms 防抖改为 600ms + 关闭前 flush + 失败重试/提示。
- 旧的 localStorage 仅作为离线草稿缓存，不再作为唯一数据源；捕获 QuotaExceededError 并提示。

验收：

- 同一份契约 fixture 在浏览器和移动端 adapter 上返回同 shape。
- 刷新、断网、重启后数据不丢；编辑中切换主题不丢内容。
- 两窗口并发编辑同一笔记时，后写者收到 409 并可选择覆盖/放弃。

### B4. 桌面平台适配层

交付：

- `desktop/platforms/`：Windows/macOS/Linux 的路径、单实例、对话框、打开文件、安全存储适配。
- 数据目录：Windows `%LOCALAPPDATA%/Hephaestus`，macOS `~/Library/Application Support/Hephaestus`，Linux `$XDG_DATA_HOME/Hephaestus`（默认 `~/.local/share/Hephaestus`）。
- Windows 保留 WebView2 检测；macOS/Linux 不导入 `winreg`/`MessageBoxW`。
- 把现有 `desktop/main.py` 的 Windows 逻辑拆到 `platforms/win.py`，启动器只依赖接口。

验收：

- Windows V1.3 全部桌面测试通过；实际窗口可开、数据目录不变。
- macOS/Linux 代码可在无 GUI 下 import/单元测试；真实窗口标记“待对应平台验证”。

### B5. 移动端工程骨架

交付：

- `mobile/`：Capacitor 配置、Android/iOS 工程、SQLite/文件系统/安全存储插件接入。
- 共享 `static/` 复制到移动 Web 目录；不复制用户数据。
- 移动数据层：迁移、CRUD、附件、设置；不依赖网络。
- 首版功能子集：笔记、标签、收藏、回收站、附件、在线 AI、10 语言/RTL。

验收：

- 无网络启动、创建、编辑、重启后数据仍在。
- 关闭 AI/无 API Key 时笔记功能不受影响。
- 需在真实 Android/iOS 设备或模拟器验证；本机无工具链时只能交付工程，不能声称已运行。

## 阶段 C：AI Provider 与赫淮斯托斯助手

### C1. Provider 抽象

- `AIProvider` 接口：`list_models`、`test_connection`、`stream_chat`、`cancel`。
- 适配器：Ollama、OpenAI-compatible、Anthropic、Gemini、DeepSeek、Qwen。
- 每种 provider 独立请求/响应解析；禁止把 Anthropic 消息硬套 OpenAI JSON。
- 超时、重试（仅未产生 token 前）、429/401/404 错误映射；流式取消。

### C2. 密钥与配置

- 桌面 `keyring`；Windows Credential Manager、macOS Keychain、Linux Secret Service。
- 移动 Keychain/Keystore 插件。
- 配置表只存 `key_ref`、provider、base_url、model、label；不存明文 key。
- 日志统一 redact：Authorization、x-api-key、query key、请求体中的笔记内容。

### C3. 助手功能

- 独立对话界面、设置界面、模型选择、连接状态。
- 功能：问答、总结笔记、整理、生成待办、提取重点、生成标题/摘要、搜索笔记、按指令创建草稿。
- 所有写操作先生成“变更提案”，展示目标笔记和 diff，用户确认后才调用写 API。
- 删除/覆盖必须二次确认；默认不自动发送任何笔记。
- 风格预设：专业严谨、简洁直接、友好自然、学术研究、创意写作、自定义 system prompt；名称/语气/回答长度/默认模型可配。

验收：

- 无 key、断网、模型不存在、429、超时、流中断均有明确提示。
- 不自动下载 Ollama 模型；不默认加载；不把 key 写日志/localStorage。
- 移动端不出现 Ollama 入口。

## 阶段 D：国际化、主题与 UI/UX

### D1. 国际化

- 10 种语言：zh-CN、en、ja、es、fr、ru、ar、fa、he、tr。
- 资源文件按 namespace 拆分；启动时按设置加载；缺失 key 回退 en 并记录，不显示 key 名。
- `Intl.DateTimeFormat`/`NumberFormat`/`RelativeTimeFormat`；货币格式化工具（当前核心界面没有货币字段，不伪造货币数据）。
- RTL：`dir=rtl`、CSS 逻辑属性、图标镜像、焦点顺序、混合文本 bidi 隔离；ar/fa/he 专项截图测试。
- 字体栈覆盖阿拉伯/希伯来/波斯字符；不允许乱码/截断/混语言。

翻译状态必须标注：`complete` / `beta` / `partial`；未翻译页面不能标成已支持。

### D2. 主题与组件

- 主题：light/dark/system；持久化；跟随系统变化；切换不刷新、不丢编辑内容。
- 设计 token：颜色、圆角、阴影、间距、字号、动效时长。
- 自定义组件：Select、Dropdown/Menu、Dialog、DatePicker、ContextMenu、Toast、Tooltip；统一键盘/ARIA/焦点陷阱。
- 替换原生 `<select id="headingSel">`；消除浏览器默认控件风格。
- 动效 120–220ms；`prefers-reduced-motion` 关闭/缩短。
- 视觉层级：导航/侧栏/列表/编辑器/工具栏统一；响应式三栏/单栏。
- 数据可视化：真实笔记数、标签分布、最近活动、存储占用；无数据时显示空状态，不造假数据。

验收：

- 10 语言切换后重启保持；RTL 三种语言逐页检查。
- 主题切换时正在编辑的标题/正文/光标不丢。
- 组件视觉/键盘/屏幕阅读器一致；无原生下拉框残留。

## 阶段 E：附件、拖放与存储管理

### E1. 附件

- 模型/存储：附件 ID、note_id、原文件名、MIME、大小、sha256、kind、创建时间；文件在应用数据目录，不存临时路径。
- 允许类型：pdf、doc/docx、xls/xlsx、ppt/pptx、txt/md、png/jpg/jpeg/webp、mp3/wav/m4a/flac/aac/ogg。
- 拒绝可执行/脚本/HTML/SVG 等危险类型；不执行用户文件。
- 上传：分块流式写临时文件，边写边算 sha256，校验 MIME/大小/磁盘空间，原子 rename，再写 DB。
- 限制：单文件默认 200MB、总空间阈值可配；超限明确报错。
- 删除：笔记软删除保留附件；永久删除需确认；附件按 note_id 单归属，未来共享用 link 表，避免误删。
- 预览：图片缩略图/原图；音频 `<audio>` + Range；文档显示名称/类型/大小/打开；PDF 可后续用 PDF.js。
- 拖放/选择器/多文件/进度/错误；粘贴图片转为附件。

### E2. 存储管理

- `/api/v2/storage/stats`：数据库大小、附件/图片/音频占用、缓存可清理量、附件数量、备份大小、磁盘剩余。
- 全部读真实文件/SQL，禁止假数据。
- 清理缓存只删 `cache/`；不动原始附件。
- 备份/恢复入口；备份含 DB 快照 + 附件 + manifest；恢复 staging 校验后替换。

验收：

- 大文件上传内存不随文件大小线性增长；断点/中断不留下半个 DB 记录。
- 删除笔记不误删其他笔记附件；备份恢复后附件可打开。
- 存储页面数字与磁盘实际一致。

## 阶段 F：Bug 修复与回归

先建立 bug 清单（问题、复现、原因、修复、回归测试），再修。至少覆盖：

- `/api/state` 与 `/notes` 双数据源；迁移后旧客户端写入；
- 标题 120/100 契约；标签/分类长度；
- 并发保存/最后写入覆盖；
- 测试 lifespan 使用真实 DB；
- 断网/磁盘满/DB 损坏/重复导入/删除引用；
- 窗口尺寸/多平台路径；
- 主题切换丢内容；RTL 布局；
- 附件 MIME/大小/路径/权限；
- AI key 泄漏/超时/流中断；
- 大笔记/大附件/长列表内存。

每个 bug 必须有回归测试；不允许用 UI 隐藏问题。

## 阶段 G：Windows、Linux、Android、macOS 构建

按平台分别记录，不互相代替：

| 平台 | 产物 | 前置条件 |
|---|---|---|
| Windows | EXE、安装程序、便携 ZIP | 本机可做；保留 V1 数据 |
| Linux | DEB | Linux/WSL/Docker + 依赖；本机当前不具备 |
| Android | APK | JDK、Android SDK、Gradle、签名；本机当前不具备 |
| macOS | DMG | macOS + Xcode/命令行工具；本机当前不具备 |
| iOS | IPA（见阶段 H） | macOS + Xcode + Apple Developer 签名/provisioning；本机当前不具备 |

每个安装包必须有真实构建日志、大小、SHA256；升级/卸载保留用户数据；未构建就写“未构建”。

## 阶段 H：iOS 工程与 IPA

- 先交付可构建 Xcode 工程和未签名构建（如条件允许）。
- 没有 Apple 开发者账号、证书、provisioning profile 时，不生成/不宣称可安装 IPA。
- 如后续具备条件：配置 Keychain、文件导入、安全区、后台限制、隐私清单；在真机测试安装/升级/数据保留。

## 测试矩阵（每阶段更新）

| 类型 | Windows | Web | macOS | Linux | Android | iOS |
|---|---|---|---|---|---|---|
| 单元/契约 | 必须 | 必须 | 代码级 | 代码级 | TS 单测 | TS 单测 |
| API/DB | 必须 | 必须 | 待构建 | 待构建 | 原生 SQLite | 原生 SQLite |
| UI/E2E | 必须 | 必须 | 待构建 | 待构建 | 真机/模拟器 | 真机/模拟器 |
| 附件/大文件 | 必须 | 部分 | 待构建 | 待构建 | 真机 | 真机 |
| AI/Ollama | 必须 | 在线 | 待构建 | 待构建 | 在线 | 在线 |
| 安装/升级/卸载 | 必须 | N/A | 待构建 | 待构建 | APK | IPA 条件满足 |

## 提交与回滚

- 每阶段一个或多个小 commit，提交信息带阶段号。
- 迁移前备份；迁移脚本有 down 方案或“恢复备份”脚本。
- 每阶段结束：pytest、前端测试、构建检查、`git diff --stat`、阶段报告。
- 不 force push、不重写历史、不直接改 main。