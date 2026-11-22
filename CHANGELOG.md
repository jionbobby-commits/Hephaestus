# 更新记录

本项目遵循语义化版本号的主次修订思路；Windows 安装包、便携版和单文件版使用同一版本号。

## V1.3.0 — 2026-11-22

### 新增

- Web 页面右上角新增「Windows 版」下载入口，显示 Windows 图标、版本号和安装包大小，点击直达 GitHub Release 安装包。
- 新增 GET /api/release，集中返回版本、安装包文件名、大小、下载地址和 Release 页面地址。
- 新增 GET /download/windows，307 跳转到当前 Release 安装包。
- 新增版本配置 app/release.py，后续发版只需修改这一处版本信息。
- 新增 README 完整说明、CHANGELOG、CONTRIBUTING、THIRD-PARTY-NOTICES 和第三方许可证原文目录。

### 改进

- 桌面布局改为固定应用外壳：html/body 不滚动，顶栏和侧栏固定，笔记列表和编辑区各自内部滚动。
- 弹窗、菜单、侧边栏增加 overscroll-behavior: contain，避免滚动穿透。
- 窗口缩放时使用 Grid/Flex 和 min-height: 0 自适应，不再依赖固定像素高度。
- 桌面窗口加载 ?desktop=1，自动隐藏仅用于 Web 的下载入口。

### 修复

- 修复页面整体可被鼠标滚轮移动约 16px 的问题。
- 修复窗口缩放到较窄宽度时列表/编辑区高度计算不稳定的问题。
- 修复 PyInstaller 配置文档中的 PowerShell 环境变量示例笔误。

### 构建

- 版本号统一为 1.3.0：VERSION、desktop/__init__.py、build/version_info.txt、build/Hephaestus.spec、installer/Hephaestus.iss。
- 安装包、便携版、单文件版使用 V1.3.0 源码重新构建；SHA256 见 Release 页面和 docs/release-notes-1.3.0.md。

## V1.2.1 — 2026-11-22

- 修复桌面端启动后偶发「本地服务连续 3 次健康检查失败」误报：巡检改为请求 /health，并增加启动宽限期、确认次数、后端线程存活检查和停止事件。
- 新增 tests/test_healthcheck.py，覆盖健康检查地址、超时、连接失败、HTTP 状态、无效 JSON、慢启动、瞬时抖动和关停不误报。
- 安装包、便携版和单文件版更新为 1.2.1。

## V1.2.0 — 2026-11-22

- 新增正式应用图标（H 字母 + 火花，ICO/PNG）。
- 新增 WebView2 Runtime 检测、中文提示和 --check-runtime。
- 新增 EXE 版本资源、Inno Setup 安装包、开始菜单/可选桌面快捷方式、卸载保留用户数据。
- 新增便携版 ZIP 和单文件 EXE。
- 新增安装、升级、卸载、重装数据保留测试。

## V1.1.0 — 2026-11-22

- 新增 Windows 桌面封装：pywebview 独立窗口、本地 FastAPI 服务、自动端口、健康检查、单实例、优雅关停。
- 数据目录改为 %LOCALAPPDATA%\Hephaestus，支持 --data-dir、--import-db 和旧库备份导入。
- 新增 PyInstaller onedir/onefile 构建配置和桌面端测试。

## V1.0.0 及更早

- FastAPI + SQLite 笔记 API：创建、列表、详情、更新、删除、搜索、分类、收藏。
- 原生 HTML/CSS/JS 前端：富文本编辑、标签、收藏、回收站、导入导出、主题和布局。
- pytest 自动化测试和 GitHub Actions。
