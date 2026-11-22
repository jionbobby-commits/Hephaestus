# Hephaestus

一个基于 Python、FastAPI 和 SQLite 的本地优先笔记管理系统。

## 功能

- 富文本笔记前端、标签、收藏、回收站、搜索与排序
- Markdown / TXT 导入与导出
- 深色与浅色主题、列表与网格视图
- FastAPI 笔记 REST API：创建、详情、分页、关键词搜索、分类筛选、收藏筛选、局部更新和删除
- SQLite + SQLAlchemy 持久化
- 前端完整状态（笔记、标签和界面设置）持久化
- Pydantic 参数验证、pytest 自动化测试与 GitHub Actions
- Windows 桌面版（V1.2.1）：pywebview + WebView2 独立窗口，无需浏览器，数据保存在本机；含安装程序、WebView2 检测和正式图标

## 环境与启动

要求 Python 3.10+。

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 ，Swagger 接口文档位于 http://127.0.0.1:8000/docs。

首次启动自动创建 `data/hephaestus.db`。可通过环境变量 `HEPHAESTUS_DATABASE_URL` 修改数据库连接地址。

## Windows 桌面版（V1.2.1）

桌面版把原有前端和 FastAPI 后端封装成一个独立窗口，完全本地运行，不依赖浏览器：

```powershell
.venv\Scripts\python.exe -m desktop.main
```

V1.2.1 提供 Inno Setup 安装程序（按用户安装、开始菜单快捷方式、可选桌面快捷方式、覆盖升级、卸载保留用户数据）、便携版 ZIP 和单文件 EXE。启动前会检测 WebView2 Runtime，缺失时显示中文提示和微软官方下载地址。

打包使用 `build/Hephaestus.spec`（onedir 或 onefile），安装包脚本为 `installer/Hephaestus.iss`。用户数据默认保存在 `%LOCALAPPDATA%\Hephaestus`，可用 `--data-dir` 或 `HEPHAESTUS_DATA_DIR` 覆盖。安装、升级、卸载、备份和故障排查见 [docs/windows-desktop.md](docs/windows-desktop.md)，版本变更见 [docs/release-notes-1.2.1.md](docs/release-notes-1.2.1.md)。

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 健康检查 |
| POST | /notes | 创建笔记，成功返回 201 |
| GET | /notes | 分页列表；支持 keyword、category、favorite |
| GET | /notes/favorites | 收藏笔记列表 |
| GET | /notes/{id} | 笔记详情，不存在返回 404 |
| PATCH | /notes/{id} | 局部更新一个或多个字段 |
| PATCH | /notes/{id}/favorite | 设置收藏状态，JSON: is_favorite |
| DELETE | /notes/{id} | 删除笔记，成功返回 204 |
| GET | /api/state | 获取前端完整状态 |
| PUT | /api/state | 保存前端完整状态 |

搜索参数 `q` 与旧版前端兼容；新调用建议使用 `keyword`。旧版 PUT /notes/{id} 暂时保留兼容，推荐新客户端使用 PATCH。

## 测试

```bash
python -m pytest -q
```

安装包测试会静默安装到临时目录，需要先构建 `dist/Hephaestus` 和 `dist/installer/Hephaestus-Setup-1.2.1.exe`；缺少产物时自动跳过。GitHub Actions 会在推送和 Pull Request 时自动运行测试。

## 项目结构

```text
app/
  database.py       # 数据库连接与 Session
  models.py         # SQLAlchemy 数据模型
  schemas.py        # Pydantic 请求/响应模型
  routers/          # HTTP 路由层
  services/         # 业务逻辑层
  main.py           # 应用入口与生命周期
desktop/
  main.py           # 桌面端入口：启动后端、打开窗口、关闭时保存
  server.py         # 本地 FastAPI 服务生命周期与健康检查
  paths.py          # 用户数据目录与数据库路径
  runtime.py        # WebView2 Runtime 检测与中文提示
  legacy.py         # 旧数据库校验、备份与导入
  single_instance.py# 单实例互斥量
  dialogs.py        # 原生错误提示框
  assets/           # 正式应用图标（ICO/PNG）
build/
  Hephaestus.spec   # PyInstaller 打包配置（onedir / onefile）
  version_info.txt  # EXE 版本信息
installer/
  Hephaestus.iss    # Inno Setup 安装脚本
  ChineseSimplified.isl # 简体中文安装界面
tools/
  make_icon.py      # 生成应用图标
docs/
  windows-desktop.md# 桌面版安装、数据目录与故障排查
  release-notes-1.2.1.md # V1.2.1 发布说明
tests/
  test_api.py       # API 自动化测试
  test_desktop.py   # 桌面端自动化测试
  test_healthcheck.py# 健康检查与后端生命周期回归
  test_installer.py # 安装、升级、卸载集成测试
```

## 数据与安全

当前前端状态 API 是单一共享工作区，适合个人本机使用。公开部署或多人使用前，必须先实现用户认证、用户数据隔离、访问控制和 HTTPS。当前版本不应直接作为多用户云笔记服务。
