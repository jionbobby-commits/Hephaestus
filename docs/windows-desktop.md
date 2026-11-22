# Hephaestus V1.3.0 Windows 安装与桌面版

V1.3.0 在 V1.2.1 基础上固定了桌面窗口布局：顶栏和侧栏固定，只有笔记列表和编辑区内部滚动；
网页端新增 Windows 下载入口，发布页提供安装包、便携版、单文件版和 SHA256。
应用仍然是本地优先的：后端只监听 127.0.0.1，笔记保存在本机 SQLite 文件，不依赖浏览器、不联网、不上传数据。

## 系统要求

- Windows 10/11 x64
- Microsoft Edge WebView2 Runtime（Windows 10/11 通常已预装）
- 不需要安装 Python，也不需要浏览器

## 窗口布局与滚动

V1.3.0 使用真正的桌面应用布局：

- 整个应用外壳固定，窗口滚动条不会让页面整体上下移动；
- 顶部搜索栏、左侧导航和右侧编辑工具栏保持固定；
- 笔记列表在列表区域内独立滚动，鼠标在列表上滚动只移动列表；
- 长笔记只在正文区域内部滚动，不影响顶栏、列表和状态栏；
- 弹窗、菜单和侧边栏使用 overscroll-behavior: contain，避免滚动穿透；
- 窗口缩放后布局仍然固定，列表和正文继续各自滚动。

实现使用 CSS Grid/Flex、min-height: 0、overflow: hidden/auto 和 100dvh，
没有用固定像素高度硬撑，也没有改动现有深色主题、绿色主色、圆角和卡片样式。
Web 版与 pywebview 桌面版共用同一套样式，鼠标滚轮、触摸板和滚动条都适用。

## 安装版（推荐）

运行 **Hephaestus-Setup-1.3.0.exe**：

1. 安装程序先检测 WebView2 Runtime；缺失时给出中文提示，并可打开微软官方下载页。
2. 默认安装到 **%LOCALAPPDATA%\Programs\Hephaestus**，按用户安装，不需要管理员权限；
   也可以在选择目录页改成其他位置。
3. 自动创建开始菜单快捷方式；桌面快捷方式为可选项。
4. 安装完成后可直接启动 Hephaestus。

安装程序不允许把程序装进用户数据目录 **%LOCALAPPDATA%\Hephaestus**，
避免卸载时误删数据库。

静默安装（供脚本或批量部署）：

    Hephaestus-Setup-1.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="D:\Apps\Hephaestus" /TASKS=""

### 覆盖升级

直接运行新版本安装程序即可。安装程序使用固定 AppId，会识别已有安装并覆盖程序文件；
用户数据库在安装目录之外，升级不会覆盖、清空或迁移笔记。升级前建议关闭正在运行的
Hephaestus；安装程序也会尝试关闭占用文件的实例。

不需要先卸载旧版本。

### 卸载

通过“设置 → 应用 → 已安装的应用 → Hephaestus → 卸载”，或开始菜单中的卸载快捷方式。

卸载只删除安装目录内由安装程序写入的文件。以下用户数据默认保留：

    %LOCALAPPDATA%\Hephaestus\hephaestus.db
    %LOCALAPPDATA%\Hephaestus\logs\
    %LOCALAPPDATA%\Hephaestus\config\

如果确定不再需要数据，可在卸载后手动删除 **%LOCALAPPDATA%\Hephaestus**。
卸载程序不会主动删除该目录。

## 便携版

- **Hephaestus-Portable-1.3.0.zip**：解压后运行 **Hephaestus\Hephaestus.exe**，无需安装。
- **Hephaestus-1.3.0-onefile.exe**：单文件版本，双击即可运行。

便携版默认仍然把数据写到 **%LOCALAPPDATA%\Hephaestus**。如果希望数据跟着程序走：

    Hephaestus.exe --data-dir "%~dp0data"

或设置环境变量 **HEPHAESTUS_DATA_DIR**。移动程序目录不会自动移动数据目录。

## WebView2 检测

应用启动时会在导入窗口组件之前检查 WebView2 Runtime：

- 已安装：正常打开窗口。
- 未安装：弹出中文提示，说明需要 WebView2、给出微软官方下载地址，并提示不需要安装 Python；
  点击“是”会打开官方下载页，应用以退出码 2 结束，不会静默崩溃。

命令行检查（适合排障和部署前验证）：

    Hephaestus.exe --check-runtime
    Hephaestus.exe --check-runtime runtime.json

输出 JSON：ok、version、frozen、webview2、download_url。
检测到 WebView2 返回 0，未检测到返回 3。安装程序也会在安装前做同样的注册表检测。

官方下载页：https://developer.microsoft.com/microsoft-edge/webview2/

## Web 页面下载入口

Web 版右上角、搜索框右侧显示「Windows 版」入口，包含 Windows 图标、版本号和安装包大小。
入口读取 GET /api/release，并跳转到 GitHub Release 中的真实安装包；桌面窗口通过 ?desktop=1
自动隐藏该入口，避免桌面用户重复下载。版本号、文件名、大小和下载地址集中在 app/release.py，
发版时只需修改这一处配置并重新构建。

## 数据目录与备份

    %LOCALAPPDATA%\Hephaestus\
      hephaestus.db                     # SQLite 数据库（笔记与前端状态）
      logs\hephaestus-desktop.log       # 运行日志（自动轮转，不记录笔记正文）
      config\                           # 预留配置目录
      backups\legacy-hephaestus-*.db    # 旧数据库导入前的备份

- 数据库不会写入 EXE 所在目录、PyInstaller 临时目录或只读目录；移动或重装程序不会丢失笔记。
- Web 模式（uvicorn app.main:app）继续使用原来的 data/hephaestus.db 或 HEPHAESTUS_DATABASE_URL，
  两种模式互不影响。
- 数据库只通过 SQLAlchemy create_all 补齐缺失的表，不会删除或重建已有数据。

备份（先完全退出 Hephaestus）：

    Copy-Item "$env:LOCALAPPDATA\Hephaestus\hephaestus.db" "D:\Backup\hephaestus-$(Get-Date -Format yyyyMMdd).db"

如果同目录存在 hephaestus.db-wal / hephaestus.db-shm，请一起复制。

恢复：退出应用后，把备份文件复制回 **%LOCALAPPDATA%\Hephaestus\hephaestus.db** 覆盖原文件。

### 导入旧数据

1. 自动导入：首次启动且目标数据库不存在时，会检查程序目录旁的 data/hephaestus.db，
   其中存在笔记才导入；
2. 手动导入：Hephaestus.exe --import-db "D:\旧路径\hephaestus.db"。

导入流程先做 SQLite 文件头、PRAGMA integrity_check 和 notes 表校验，再把原文件备份到
backups\，最后原子替换目标数据库。任何一步失败都不会修改或删除原数据库。

## 从源码运行

    .venv\Scripts\python.exe -m desktop.main

命令行参数：

| 参数 | 说明 |
|---|---|
| --data-dir PATH | 指定数据目录（默认 %LOCALAPPDATA%\Hephaestus） |
| --port PORT | 指定本地服务端口（默认自动选择空闲端口） |
| --import-db PATH | 从旧的 Hephaestus SQLite 数据库导入数据 |
| --startup-timeout SEC | 本地服务启动超时时间 |
| --headless | 只启动后端不打开窗口，输出 JSON 信息，供脚本或排障使用 |
| --self-test REPORT | 启动后端做自检并写入 JSON 报告，成功返回 0 |
| --check-runtime [REPORT] | 检测 WebView2，输出 JSON，可选写入报告文件 |
| --version | 输出版本号 |

## 关闭与保存

关闭窗口时，桌面端会先触发前端 pagehide 并等待约 0.9 秒（前端保存有 350ms 防抖），
让最后一次编辑写入后端，然后停止本地服务并退出进程。如果后端在运行中异常退出，
窗口会弹出提示并给出日志路径。

## 打包与发布

前置：项目虚拟环境、Pillow（生成图标）、Inno Setup 6.5+。

    # 1. 生成正式图标（Pillow）
    .venv\Scripts\python.exe tools\make_icon.py

    # 2. onedir（安装包使用这个产物）
    .venv\Scripts\pyinstaller.exe --noconfirm --clean build\Hephaestus.spec

    # 3. onefile
    $env:HEPHAESTUS_ONEFILE = "1"
    .venv\Scripts\pyinstaller.exe --noconfirm --clean build\Hephaestus.spec
    Remove-Item Env:HEPHAESTUS_ONEFILE

    # 4. 编译安装包（需要 Inno Setup 6 的 ISCC.exe）
    & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\Hephaestus.iss

    # 5. 便携版与校验和
    Compress-Archive -Path dist\Hephaestus -DestinationPath dist\Hephaestus-Portable-1.3.0.zip -Force
    Get-FileHash dist\installer\Hephaestus-Setup-1.3.0.exe, dist\Hephaestus-Portable-1.3.0.zip, dist\Hephaestus-1.3.0-onefile.exe -Algorithm SHA256

- 打包配置：build/Hephaestus.spec，入口 desktop_launcher.py，静态资源 static/ 会一起打包。
- 版本信息：VERSION、desktop/__init__.py、build/version_info.txt 和安装脚本中的版本号需要一致。
- 不包含用户数据库，不包含测试依赖。
- 安装包使用 installer/ChineseSimplified.isl（来自 Inno Setup 官方仓库的简体中文翻译）。
- 目标机器不需要安装 Python，但需要 WebView2 Runtime。

## 故障排查

| 现象 | 处理 |
|---|---|
| 提示缺少 WebView2 | 按提示打开微软官方下载页安装 Runtime，然后重试；可用 --check-runtime 验证 |
| 安装时提示不能装到用户数据目录 | 换一个安装目录；%LOCALAPPDATA%\Hephaestus 专用于保存笔记数据库 |
| SmartScreen 提示“未知发布者” | 当前安装包未做代码签名，确认文件 SHA256 与发布说明一致后再运行 |
| 提示“Hephaestus 已在运行” | 已有实例占用单实例锁，切换到已打开的窗口 |
| 启动失败并提示端口/服务错误 | 查看 logs\hephaestus-desktop.log，或用 --port 指定端口 |
| 数据看起来是旧的 | 确认数据目录：默认 %LOCALAPPDATA%\Hephaestus，可用 --data-dir 或 HEPHAESTUS_DATA_DIR 覆盖 |
| 数据库被占用或写入失败 | 关闭其他正在使用该数据库的进程，检查数据目录写权限；应用不会强杀或重建数据库 |
| 升级后想回到旧版本 | 先备份数据库，再运行旧版安装程序；数据库结构向前兼容，但降级前务必备份 |
| 需要脚本化验证 | Hephaestus.exe --self-test report.json --data-dir 临时目录 |

日志默认位于 **%LOCALAPPDATA%\Hephaestus\logs\hephaestus-desktop.log**，最多保留 3 个 1MB 轮转文件。

## 测试

    .venv\Scripts\python.exe -m pytest -q

- tests/test_api.py：Web API
- tests/test_desktop.py：桌面端路径、WebView2 检测、单实例、旧库导入、后端启动、持久化和自检
- tests/test_healthcheck.py：健康检查地址规范化、失败分类、慢启动、宽限期、瞬时抖动、线程退出和关停不误报
- tests/test_installer.py：静默安装、启动、写入笔记、覆盖升级、卸载保留数据、重装读取旧数据

安装包测试需要先构建 dist/Hephaestus 和 dist/installer/Hephaestus-Setup-1.3.0.exe；
缺少产物时会整体跳过，其余测试不受影响。
