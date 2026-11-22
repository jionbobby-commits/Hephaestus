# 第三方依赖与许可证说明

Hephaestus 使用 Python、FastAPI、SQLite 和 pywebview 等开源项目构建。本文件列出 V1.3.0 构建与验证环境中实际使用的直接依赖、构建工具和运行时组件，以及它们的许可证。

本项目自身当前尚未声明开源许可证，详见 README 的「许可证」章节。本文件不改变任何第三方许可证的效力。

## 运行时直接依赖

| 组件 | 版本 | 许可证 | 用途 |
|---|---:|---|---|
| FastAPI | 0.163.2 | MIT | HTTP API |
| Starlette | 1.10.0 | BSD-3-Clause | ASGI 基础 |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI 服务器 |
| Pydantic | 2.14.3 | MIT | 数据校验 |
| pydantic-core | 2.50.4 | MIT | Pydantic 核心 |
| SQLAlchemy | 2.1.9 | MIT | ORM |
| pywebview | 6.2.1 | BSD-3-Clause | 桌面窗口 |
| pythonnet | 3.2.1 | MIT | .NET/WebView2 互操作 |
| clr-loader | 0.3.1 | MIT | .NET 运行时加载 |
| bottle | 0.13.4 | MIT | pywebview 内置 HTTP 服务 |
| cffi | 2.1.1 | MIT-0 | ctypes/ABI 支持 |
| pycparser | 3.12 | BSD-3-Clause | cffi 依赖 |
| anyio | 4.16.0 | MIT | 异步兼容层 |
| h11 | 0.16.0 | MIT | HTTP/1.1 协议 |
| httptools | 0.9.0 | MIT | HTTP 解析加速 |
| websockets | 17.4 | BSD-3-Clause | WebSocket 支持 |
| watchfiles | 1.3.0 | MIT | 文件监听 |
| python-dotenv | 1.2.4 | BSD-3-Clause | .env 支持 |
| PyYAML | 6.0.4 | MIT | 配置解析 |
| click | 8.5.1 | BSD-3-Clause | Uvicorn CLI |
| typing-extensions | 4.16.0 | PSF-2.0 | 类型标注兼容 |
| annotated-types | 0.8.0 | MIT | 类型标注 |
| idna | 3.20 | BSD-3-Clause | 国际化域名 |
| certifi | 2026.11.20 | MPL-2.0 | CA 证书包 |

## 测试与构建依赖

| 组件 | 版本 | 许可证 | 用途 |
|---|---:|---|---|
| httpx | 0.28.1 | BSD-3-Clause | API/桌面测试 |
| httpcore | 1.0.9 | BSD-3-Clause | httpx 依赖 |
| pytest | 8.4.2 | MIT | 测试框架 |
| PyInstaller | 6.22.3 | GPL-2.0-or-later，附 bootloader 例外 | 打包为 EXE |
| pyinstaller-hooks-contrib | 2026.10 | Apache-2.0 / GPL-2.0 | PyInstaller hooks |

PyInstaller 的许可证包含特殊例外，允许使用 PyInstaller 打包并分发非自由程序。Hephaestus 的构建不修改 PyInstaller 自身代码。

## 平台与运行时组件

| 组件 | 说明 | 许可证/分发方式 |
|---|---|---|
| Python | 3.15.2（本机构建环境；项目要求 3.10+） | Python Software Foundation License 2.0 |
| Microsoft Edge WebView2 Runtime | 桌面窗口运行时，由 Windows/Edge 安装，不随本项目仓库分发 | Microsoft 专有运行时；使用受 Microsoft 软件许可约束 |
| Inno Setup | 6.7.3，构建安装包的工具，不随源码仓库分发 | Inno Setup 免费许可；生成的安装程序包含其运行时代码 |
| ChineseSimplified.isl | 来自 Inno Setup 官方仓库的简体中文语言文件 | 随 Inno Setup 源码发布，按其许可证使用 |

## 许可证文本

以下目录保存了构建环境实际安装的 Python 依赖所附带的许可证文本：

- licenses/：按「包名-版本-LICENSE.txt」命名的许可证原文。

如果某个依赖没有单独的许可证文件，以其发行包元数据或上游项目页面为准。分发本项目的 Windows 构建产物时，请同时保留本文件和 licenses/ 目录。

## 素材说明

- 应用图标由项目内的 tools/make_icon.py 使用 Pillow 生成，没有复制第三方图标或素材。
- 前端使用系统字体和项目内联 SVG，没有引入第三方图标库、字体文件或图片素材。
- README 截图由本机真实运行的 Hephaestus 窗口截取，不包含个人笔记内容之外的用户数据（演示笔记为项目内置示例）。

## 参考链接

- FastAPI: https://github.com/fastapi/fastapi
- Starlette: https://github.com/encode/starlette
- Uvicorn: https://github.com/encode/uvicorn
- Pydantic: https://github.com/pydantic/pydantic
- SQLAlchemy: https://github.com/sqlalchemy/sqlalchemy
- pywebview: https://github.com/r0x0r/pywebview
- pythonnet: https://github.com/pythonnet/pythonnet
- PyInstaller: https://github.com/pyinstaller/pyinstaller
- Inno Setup: https://jrsoftware.org/isinfo.php
- WebView2: https://developer.microsoft.com/microsoft-edge/webview2/
- Python license: https://docs.python.org/3/license.html
