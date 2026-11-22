# Hephaestus

一个基于 Python、FastAPI 和 SQLite 的本地优先笔记管理系统。

## 当前功能

- 富文本笔记编辑、标签、收藏、回收站、搜索和排序
- Markdown / TXT 导入与导出
- 深色与浅色主题、列表与网格视图
- FastAPI 笔记 REST API：创建、读取、更新、删除、分页和搜索
- SQLite + SQLAlchemy 持久化
- 前端完整状态（笔记、标签和界面设置）持久化到 SQLite
- Pydantic 请求验证与 pytest API 测试

## 环境要求

- Python 3.10+
- pip

## 本地运行

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

浏览器访问 http://127.0.0.1:8000 ，接口文档访问 http://127.0.0.1:8000/docs。

首次启动会自动创建 `data/hephaestus.db`。数据库文件不会提交到 Git。

## 数据库位置

默认使用项目目录下的 `data/hephaestus.db`。可通过环境变量 `HEPHAESTUS_DATABASE_URL` 修改，例如：

```bash
# Linux / macOS
export HEPHAESTUS_DATABASE_URL="sqlite:///./data/custom.db"
# Windows PowerShell
$env:HEPHAESTUS_DATABASE_URL = "sqlite:///./data/custom.db"
```

## 运行测试

```bash
python -m pytest -q
```

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 健康检查 |
| POST | /notes | 创建笔记 |
| GET | /notes | 分页、关键词、分类和收藏筛选 |
| GET | /notes/{id} | 获取笔记 |
| PUT | /notes/{id} | 更新笔记 |
| DELETE | /notes/{id} | 删除笔记 |
| GET | /api/state | 获取前端完整状态 |
| PUT | /api/state | 保存前端完整状态 |

## 数据与安全说明

当前前端状态接口保存的是单一共享工作区，适合个人本机使用。若将服务公开部署给多人使用，必须先实现用户认证、用户隔离、访问控制和 HTTPS，不能直接把当前版本当作多用户云笔记服务。
