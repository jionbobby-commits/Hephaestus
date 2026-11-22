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

GitHub Actions 会在推送和 Pull Request 时自动运行测试。

## 项目结构

```text
app/
  database.py       # 数据库连接与 Session
  models.py         # SQLAlchemy 数据模型
  schemas.py        # Pydantic 请求/响应模型
  routers/          # HTTP 路由层
  services/         # 业务逻辑层
  main.py           # 应用入口与生命周期
tests/
  test_api.py       # API 自动化测试
```

## 数据与安全

当前前端状态 API 是单一共享工作区，适合个人本机使用。公开部署或多人使用前，必须先实现用户认证、用户数据隔离、访问控制和 HTTPS。当前版本不应直接作为多用户云笔记服务。
