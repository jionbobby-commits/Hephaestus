# 参与贡献

感谢你关注 Hephaestus。这个项目是个人发起的本地优先笔记应用，欢迎通过 Issue 和 Pull Request 提交问题、建议和修复。

## 提交 Issue

请尽量包含：

- 操作系统版本（例如 Windows 11 23H2 x64）；
- Hephaestus 版本（安装包文件名或 --version 输出）；
- 复现步骤、实际结果和期望结果；
- 相关日志（%LOCALAPPDATA%\Hephaestus\logs\hephaestus-desktop.log），但不要附带真实笔记内容、数据库文件或密钥；
- 如果涉及界面，附截图时请先遮挡个人信息。

## 提交 Pull Request

1. 从 main 创建独立功能分支，不要直接修改 main。
2. 保持改动聚焦，避免顺手重构无关代码。
3. 不提交数据库、日志、个人笔记、.env、密钥、构建产物或本地 IDE 配置。
4. 新增或修改行为时补充测试；不要删除或跳过现有测试来制造通过结果。
5. 提交前运行：

       .venv\Scripts\python.exe -m pytest -q

6. 如果修改桌面端或安装包，请说明是否重新构建了 dist/Hephaestus、onefile 和安装包，以及实际执行的验证。
7. 在 PR 描述中说明改动目的、兼容性影响和测试结果。

## 开发环境

    python -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    python -m uvicorn app.main:app --reload

桌面端源码运行：

    .venv\Scripts\python.exe -m desktop.main

安装包测试需要先构建 dist/Hephaestus 和 dist/installer/Hephaestus-Setup-<版本>.exe；缺少产物时测试会自动跳过。

## 许可证与贡献

本项目当前尚未声明开源许可证。在项目所有者确认许可证之前，提交贡献不代表自动授予再分发许可；如果你希望以特定许可证贡献代码，请在 PR 中说明并与项目所有者确认。

## 行为准则

请保持尊重、具体和建设性。技术讨论对事不对人；不要提交他人的私人数据、密钥或未经授权的素材。
