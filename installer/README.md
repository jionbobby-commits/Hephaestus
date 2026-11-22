# 安装程序（Inno Setup）

installer/Hephaestus.iss 使用 Inno Setup 6 构建 Windows 安装包。
简体中文界面来自 ChineseSimplified.isl，文件取自 Inno Setup 官方仓库：

    https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseSimplified.isl

该翻译文件头部标注适用 Inno Setup 6.5.0+。升级 Inno Setup 后如界面出现缺项，
重新从官方仓库获取同名文件即可。

## 构建前提

1. 已构建 onedir 产物 dist\Hephaestus\Hephaestus.exe。
2. 已安装 Inno Setup 6.5 或更高版本，默认路径：
   %LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe。
3. VERSION、desktop/__init__.py、build/version_info.txt 和 Hephaestus.iss 中的
   版本号一致（当前 1.2.1）。

## 构建命令

    & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\Hephaestus.iss

输出：dist\installer\Hephaestus-Setup-1.2.1.exe

## 设计要点

- **AppId 固定**：{{7C4E2B1A-9F3D-4A6E-8B52-1D9C0E7A3F64}}，升级时识别同一产品。
  修改 AppId 会被系统视为另一个产品，不要随意改动。
- **按用户安装**：PrivilegesRequired=lowest，默认目录
  %LOCALAPPDATA%\Programs\Hephaestus，不触发 UAC。
- **数据目录隔离**：安装目录不能等于 %LOCALAPPDATA%\Hephaestus，避免卸载误删数据库。
- **不删除用户数据**：脚本没有 [UninstallDelete] 段，卸载只移除安装目录内的程序文件。
- **WebView2 检测**：ReadWebView2Version 读取 HKLM/HKCU 的 32/64 位注册表；
  缺失时显示中文提示并可打开微软官方下载页，安装继续进行。
- **关闭运行中的实例**：CloseApplications=yes，RestartApplications=no。
- **快捷方式**：开始菜单必选；桌面快捷方式为可选任务，默认不勾选。
- **静默安装**：支持 /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=... /TASKS=。

## 自动化测试

tests/test_installer.py 会真实执行安装、启动、写入、升级、卸载和重装，
使用临时安装目录和临时数据目录，并在测试前后校验真实用户数据库的 SHA256。

    .venv\Scripts\python.exe -m pytest tests\test_installer.py -q

缺少 dist\Hephaestus 或安装包时，该测试模块整体跳过。
