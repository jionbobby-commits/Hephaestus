# Hephaestus V1.3.0 发布说明

发布日期：2026-11-22

版本号：1.3.0

## 本次发布重点

- **桌面滚动体验修复**：固定整个应用外壳，顶栏和侧栏保持不动，笔记列表与编辑区分别内部滚动；页面不再随鼠标滚轮整体移动。
- **Web 下载入口**：网页右上角新增「Windows 版」按钮，显示版本号和安装包大小，点击直接下载 GitHub Release 中的安装包。
- **发布配置集中化**：版本、安装包文件名、大小和下载地址集中在 app/release.py；新增 GET /api/release 和 GET /download/windows。
- **项目文档补全**：README 重写为完整的使用、安装、数据、开发、测试和 FAQ 文档；新增 CHANGELOG、CONTRIBUTING、THIRD-PARTY-NOTICES 和第三方许可证原文目录。
- **Windows 产物更新**：安装包、便携版 ZIP 和单文件 EXE 全部使用 V1.3.0 源码重新构建。

## 滚动修复说明

V1.3.0 之前，应用外壳虽然设置了 overflow: hidden，但 Grid 的隐式行按内容最大高度撑开，主区域和侧栏比外壳高约 38px，加上底部外边距后页面仍可被滚轮移动约 16px。

修复方式：

- html、body 固定为 100% 高度并隐藏溢出；
- .app 显式使用 grid-template-rows: minmax(0, 1fr)，限制最大高度为 100dvh 减外边距；
- .main、.body、.list-pane、.editor-pane 增加 min-height: 0 和 overflow: hidden；
- .note-list 与 .doc 保留 overflow: auto，作为唯一的内部滚动容器；
- 弹窗、菜单、侧边栏和正文增加 overscroll-behavior: contain，避免滚动穿透；
- 移动端布局继续使用 100dvh，保持原有侧边栏抽屉和编辑页切换。

真实 pywebview 窗口验证（1266x783 CSS 像素，DPR 1.5）：

| 检查 | 结果 |
|---|---|
| 页面 scrollHeight / clientHeight | 783 / 783，页面不可整体滚动 |
| 页面 scrollY（滚轮/scrollTo 后） | 0 |
| 笔记列表滚轮 | scrollTop 500 → 1900，页面仍为 0 |
| 长笔记正文滚轮 | scrollTop 0 → 600，页面仍为 0 |
| 顶栏滚轮 | 页面 0，列表和正文位置不变 |
| 窗口缩放到 986x563 | 页面仍不可整体滚动，列表 400px 高并可内部滚动 |
| 弹窗内滚动 | .m-body scrollTop 0 → 800；页面 scrollY 仍为 0，弹窗未关闭 |

## 下载与校验

| 文件 | 大小 | SHA256 |
|---|---:|---|
| Hephaestus-Setup-1.3.0.exe | 22,441,960 字节 | 675FC8F8BD935BB9CF4C0C94D4A1B1057A44C1328F2165518CCE7631CD0B2D59 |
| Hephaestus-Portable-1.3.0.zip | 24,206,470 字节 | B3D5E5AF32B8D07BA6CB99B01C0FA712ABD0454669C0F7CA6555287708A1CB82 |
| Hephaestus-1.3.0-onefile.exe | 24,314,848 字节 | 5EB6B93DCC090511CBD9C3341095FA7A6DFAFB50C8B0B4072AE38C0A20DBA8F3 |

发布页面：https://github.com/jionbobby-commits/Hephaestus/releases/tag/v1.3.0

安装包直链：https://github.com/jionbobby-commits/Hephaestus/releases/download/v1.3.0/Hephaestus-Setup-1.3.0.exe

## 系统要求

- Windows 10/11 x64
- Microsoft Edge WebView2 Runtime（Windows 11 通常已内置）
- 不需要安装 Python，不需要浏览器
- 安装程序按当前用户安装，默认目录 %LOCALAPPDATA%\Programs\Hephaestus

## 安装、升级与卸载

- 安装：双击 Hephaestus-Setup-1.3.0.exe，按向导完成；可选择是否创建桌面快捷方式。
- 升级：直接运行新版本安装包覆盖安装。固定 AppId，程序文件被替换，%LOCALAPPDATA%\Hephaestus 中的数据库保留。
- 卸载：从「设置 → 应用」卸载。默认保留数据库、日志和备份；如需彻底清理，请先备份再手动删除数据目录。
- 数据目录：%LOCALAPPDATA%\Hephaestus\hephaestus.db；Web 版使用 data/hephaestus.db。

## 验证结果

### 自动化测试

命令：.venv\Scripts\python.exe -m pytest -q

结果：59 passed, 1 warning in 41.87s（warning 为 Starlette TestClient 的 httpx 弃用提示，不影响结果）。

覆盖：API 测试、桌面端路径/WebView2/旧库导入/健康检查、安装包首次安装与覆盖升级/卸载保留数据。安装包测试需要真实构建产物，本次已实际执行，未跳过。

### 构建与运行

- onedir：dist/Hephaestus/Hephaestus.exe，--version 输出 Hephaestus 1.3.0，--check-runtime 检测到 WebView2 152.0.4191.66。
- onefile：dist/Hephaestus-1.3.0-onefile.exe，--version 与 --check-runtime 通过。
- 安装包集成测试：首次安装、开始菜单快捷方式、启动、写入笔记、覆盖升级、卸载保留数据库、重装读取旧笔记。
- 真实用户数据库 %LOCALAPPDATA%\Hephaestus\hephaestus.db 在测试前后 SHA256 不变。

### 实际接口

- GET /health 返回 {"status":"ok"}。
- GET /api/release 返回 V1.3.0 的版本、安装包名、大小、下载地址和 Release 页面。
- GET /download/windows 返回 307，Location 指向安装包直链。
- GET /docs 正常加载 Swagger UI。
- 笔记 CRUD、PATCH、旧 PUT、keyword/q 搜索、分类/收藏筛选、/api/state 保存读取均通过既有 API 测试。

### 未执行或未完成

- **干净 Windows 虚拟机验证未执行**：本机没有可用的 Hyper-V/VirtualBox/VMware/Windows Sandbox 测试环境，未伪造该结果。发布说明只报告本机实际执行过的测试。
- **代码签名未完成**：安装包未做 Authenticode 签名，Windows SmartScreen 可能提示“未知发布者”。
- **WebView2 缺失场景未在真实缺 Runtime 的机器上执行**：已通过单元测试模拟和 --check-runtime 验证检测逻辑。
- **项目许可证尚未确定**：未擅自选择开源许可证；README 和 THIRD-PARTY-NOTICES 已说明当前状态，第三方许可证原文已整理到 licenses/。

## 升级兼容性

- 数据库结构未变化；V1.2.x 创建的数据库可直接被 V1.3.0 读取。
- 旧版 PUT /notes/{id} 和 q 搜索参数继续保留，现有前端和旧客户端不受影响。
- 桌面数据目录、安装目录和卸载保留策略与 V1.2.1 一致。
