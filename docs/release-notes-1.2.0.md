# Hephaestus V1.2.0 发布说明

发布日期：2026-11-22
版本号：1.2.0
分支：feat/windows-release-v1.2

## 本次重点

V1.2 是 Windows 桌面端的正式发布准备版本。前端页面和 Web API 行为保持不变，
主要补充安装、分发和运行时检测能力。

- **Inno Setup 安装程序**：按用户安装，不需要管理员权限；支持自定义安装目录、
  开始菜单快捷方式、可选桌面快捷方式、覆盖升级和标准卸载。
- **WebView2 Runtime 检测**：应用启动前检查运行时；缺失时显示中文说明和微软官方
  下载地址，不会静默退出或直接崩溃。安装程序也会在安装前检查。
- **正式应用图标**：深绿色圆角底板 + 渐变 H 字母 + 琥珀色火花，提供 16–256px
  多尺寸 ICO，用于 EXE、安装程序、开始菜单、桌面和任务栏。
- **版本信息统一**：VERSION、desktop/__init__.py、build/version_info.txt、
  EXE 资源和安装程序版本均为 1.2.0。
- **安装/升级/卸载自动化测试**：真实运行安装程序，验证首次安装、启动、写入笔记、
  覆盖升级、卸载保留数据库、重装后读取旧数据。
- **文档更新**：安装、升级、卸载、便携版、备份恢复、WebView2 排障和发布流程。

## 发布文件

| 文件 | 大小（字节） | SHA256 |
|---|---|---|
| Hephaestus-Setup-1.2.0.exe | 22,427,384 | bd0b09d5682af1d7bf4dc238ba51cf6d6d514014d9ec4d45ddede214677943f6 |
| Hephaestus-Portable-1.2.0.zip | 24,195,877 | 48f84fb4c0650667f3f71a094241998b5ff551bac9334d04d0a9caa74eca093a |
| Hephaestus-1.2.0-onefile.exe | 24,303,102 | e3dd2df1d75cc184291a44e4a3c33b8d850d48d1a96cecccbc7ac496aa7faf32 |

安装包使用 onedir 产物构建，解压后的程序目录约 43.9 MB（99 个文件）；
便携版 ZIP 包含同一个 onedir 目录；单文件 EXE 首次启动会解压到临时目录，速度略慢。

## 安装与升级

默认安装目录：**%LOCALAPPDATA%\Programs\Hephaestus**。安装程序拒绝把程序装进
**%LOCALAPPDATA%\Hephaestus**，该目录专用于用户数据。

覆盖升级直接运行新版本安装程序即可，AppId 保持不变，程序文件被替换，数据库不动。
如果 Hephaestus 正在运行，安装程序会请求关闭占用文件的实例。

## 数据兼容

- 用户数据库位于 **%LOCALAPPDATA%\Hephaestus\hephaestus.db**，在安装目录之外。
- 卸载程序不删除数据库、日志和配置；卸载后重新安装可以继续读取原有笔记。
- 数据库只通过 SQLAlchemy create_all 补齐缺失的表，不会重建或清空已有数据。
- Web 模式继续使用 data/hephaestus.db 或 HEPHAESTUS_DATABASE_URL，与桌面版互不影响。
- 旧库导入仍会先校验、备份，再原子替换；失败不修改原数据库。

## 验证结果

- pytest：38 passed，1 warning（Starlette TestClient 的 httpx 弃用提示，不影响功能）。
- 安装包集成测试：2 passed，覆盖首次安装、启动、写入、升级、卸载保留数据、重装读取。
- onedir EXE：版本 1.2.0，--check-runtime 检测到 WebView2 152.0.4191.66，
  --self-test 健康检查通过。
- onefile EXE：版本 1.2.0，检查与自检通过。
- 测试期间真实用户数据库 %LOCALAPPDATA%\Hephaestus\hephaestus.db 的 SHA256 前后一致。

## 已知限制

- 安装包未做代码签名，Windows SmartScreen 可能提示“未知发布者”；
  请核对 SHA256 后再运行。正式公开分发建议购买代码签名证书。
- 没有可用的干净 Windows 虚拟机或 Windows Sandbox，因此“无 Python 的全新系统”
  验证尚未实际执行；发布前应按 docs/vm-verification-checklist.md 在干净环境补测。
- WebView2 缺失分支已通过单元测试和安装脚本逻辑验证，但开发机已安装 WebView2，
  没有在真实缺失运行时的系统上执行弹窗流程。
- 简体中文安装界面使用 Inno Setup 官方仓库的 ChineseSimplified.isl（6.5.0+），
  不是安装程序自带的官方语言列表。
- 安装包仅支持 Windows 10/11 x64。

## 升级与回退

升级前建议先退出应用并备份数据库。需要回退时，先备份当前数据库，再运行旧版本安装程序；
数据库结构向前兼容，但跨版本回退仍应先备份。

## 相关文档

- docs/windows-desktop.md：安装、升级、卸载、便携版、数据目录、备份和排障
- docs/vm-verification-checklist.md：干净 Windows 环境验证清单
- installer/README.md：安装脚本结构和构建说明
