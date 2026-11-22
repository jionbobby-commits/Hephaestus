# Hephaestus V1.1 Windows 桌面版

V1.1 在保留原有 Web 前端与 FastAPI 后端的前提下，用 pywebview + WebView2 提供一个独立的 Windows 桌面窗口。
应用完全本地运行：后端只监听 127.0.0.1，笔记数据保存在本机 SQLite 文件，不依赖浏览器、不联网、不上传数据。

## 运行

源码模式（需要项目虚拟环境）：

```powershell
.venv\Scripts\python.exe -m desktop.main
```

打包后（Windows 10/11，需已安装 Microsoft Edge WebView2 Runtime）：

```text
dist\Hephaestus\Hephaestus.exe     # onedir 版本，整个 Hephaestus 文件夹一起分发
dist\Hephaestus.exe                 # onefile 单文件版本
```

双击 EXE 即可打开窗口，窗口标题为 Hephaestus。再次双击不会启动第二个实例，而是提示应用已在运行。

命令行参数：

| 参数 | 说明 |
|---|---|
| `--data-dir PATH` | 指定数据目录（默认 %LOCALAPPDATA%\Hephaestus） |
| `--port PORT` | 指定本地服务端口（默认自动选择空闲端口） |
| `--import-db PATH` | 从旧的 Hephaestus SQLite 数据库导入数据 |
| `--startup-timeout SEC` | 本地服务启动超时时间 |
| `--headless` | 只启动后端不打开窗口，输出 JSON 信息，供脚本或排障使用 |
| `--self-test REPORT` | 启动后端做自检并写入 JSON 报告，成功返回 0 |
| `--version` | 输出版本号 |

## 数据目录

桌面版把用户数据放在：

```text
%LOCALAPPDATA%\Hephaestus\
  hephaestus.db                     # SQLite 数据库
  logs\hephaestus-desktop.log       # 运行日志（自动轮转，不记录笔记正文）
  config\                           # 预留配置目录
  backups\legacy-hephaestus-*.db    # 旧数据库导入前的备份
```

- 数据库不会写入 EXE 所在目录、PyInstaller 临时目录或只读目录；移动或重装 EXE 不会丢失笔记。
- 用环境变量 `HEPHAESTUS_DATA_DIR` 可以整体替换数据目录，便于便携使用或测试。
- Web 模式（`uvicorn app.main:app`）仍然使用原来的 `data/hephaestus.db` 或 `HEPHAESTUS_DATABASE_URL`，两种模式互不影响。
- 数据库只通过 SQLAlchemy `create_all` 补齐缺失的表，不会删除或重建已有数据。

### 导入旧数据

如果本机已有旧版 Hephaestus 数据库，可以：

1. 自动导入：首次启动且目标数据库不存在时，会检查程序目录旁的 `data/hephaestus.db`，其中存在笔记才导入；
2. 手动导入：`Hephaestus.exe --import-db "D:\旧路径\hephaestus.db"`。

导入流程先做 SQLite 文件头、`PRAGMA integrity_check` 和 notes 表校验，再把原文件备份到 `backups\`，最后原子替换目标数据库。任何一步失败都不会修改或删除原数据库。

## 关闭与保存

关闭窗口时，桌面端会先触发前端 `pagehide` 并等待约 0.9 秒（前端保存有 350ms 防抖），让最后一次编辑写入后端，然后停止本地服务并退出进程。
如果后端在运行中异常退出，窗口会弹出提示并给出日志路径。

## 打包

```powershell
# onedir（默认，启动更快，便于排查）
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean build\Hephaestus.spec

# onefile（单文件分发）
$env:HEPHAESTUS_ONEFILE = "1"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean build\Hephaestus.spec
```

- 打包配置：`build/Hephaestus.spec`，入口 `desktop_launcher.py`，静态资源 `static/` 会一起打包。
- 不包含用户数据库，不包含测试依赖。
- 目标机器不需要安装 Python，但需要 WebView2 Runtime（Windows 10/11 通常已预装；缺失时窗口会提示安装）。

## 故障排查

| 现象 | 处理 |
|---|---|
| 提示缺少 WebView2 | 安装 Microsoft Edge WebView2 Runtime 后重试 |
| 提示“Hephaestus 已在运行” | 已有实例占用单实例锁，切换到已打开的窗口 |
| 启动失败并提示端口/服务错误 | 查看 `logs\hephaestus-desktop.log`，或用 `--port` 指定端口 |
| 数据看起来是旧的 | 确认数据目录：默认 `%LOCALAPPDATA%\Hephaestus`，可用 `--data-dir` 或 `HEPHAESTUS_DATA_DIR` 覆盖 |
| 数据库被占用或写入失败 | 关闭其他正在使用该数据库的进程，检查数据目录写权限；应用不会强杀或重建数据库 |
| 需要脚本化验证 | `Hephaestus.exe --self-test report.json --data-dir 临时目录` |

日志默认位于 `%LOCALAPPDATA%\Hephaestus\logs\hephaestus-desktop.log`，最多保留 3 个 1MB 轮转文件。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest -q
```

`tests/test_api.py` 覆盖 Web API，`tests/test_desktop.py` 覆盖桌面端路径、单实例、旧库导入、后端启动、持久化和自检。
