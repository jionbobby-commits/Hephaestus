# 干净 Windows 环境验证清单（V1.2）

## 状态说明

本清单**尚未在干净虚拟机中执行**。开发机是已安装 Python、Git、Inno Setup 和
WebView2 Runtime 的 Windows 11 家用版，无法代表最终用户环境；本机也未安装
Hyper-V 管理工具、VirtualBox、VMware 或 Windows Sandbox，因此没有伪造“通过”结果。

已完成的本机验证见 docs/release-notes-1.2.1.md：pytest 55 passed、安装包集成测试
2 passed、onedir/onefile 检查与自检通过。

## 目标环境

- Windows 10 22H2 x64 或 Windows 11 x64，全新安装，未装 Python、Git、Node.js、
  Visual Studio、Inno Setup。
- 建议断开网络或使用快照，避免系统自动更新改变 WebView2 状态。
- 至少 4 GB 内存、2 GB 可用磁盘。
- 分别准备“已含 WebView2”和“不含 WebView2”的系统快照：
  Windows 11 通常预装 WebView2；Windows 10 新装环境更可能缺失。

## 准备

1. 在宿主机核对发布文件 SHA256，与 dist/SHA256SUMS.txt 一致。
2. 把以下文件复制到虚拟机：
   - Hephaestus-Setup-1.2.1.exe
   - Hephaestus-Portable-1.2.1.zip
   - Hephaestus-1.2.1-onefile.exe
   - SHA256SUMS.txt
3. 在虚拟机中用 PowerShell 复核：

       Get-FileHash .\Hephaestus-Setup-1.2.1.exe -Algorithm SHA256

4. 确认系统没有 Python：

       Get-Command python, py -ErrorAction SilentlyContinue

   预期：没有任何输出。

5. 记录 WebView2 状态：

       Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue

## 测试用例

| 编号 | 场景 | 步骤 | 预期结果 | 实际结果 |
|---|---|---|---|---|
| VM-01 | 全新安装 | 双击安装包，使用默认目录完成安装 | 中文向导；无需管理员权限；安装成功 | 待执行 |
| VM-02 | 开始菜单 | 打开开始菜单 | 存在 Hephaestus 快捷方式，图标正确 | 待执行 |
| VM-03 | 首次启动 | 从开始菜单启动 | 独立窗口打开，标题 Hephaestus，界面中文正常 | 待执行 |
| VM-04 | 数据目录 | 查看 %LOCALAPPDATA%\Hephaestus | 生成 hephaestus.db 和 logs 目录 | 待执行 |
| VM-05 | 笔记 CRUD | 新建、编辑、收藏、搜索、删除笔记 | 操作正常，重启后结果保留 | 待执行 |
| VM-06 | 中文输入 | 用微软拼音输入中文标题和正文 | 显示、保存、再次读取均正常 | 待执行 |
| VM-07 | 关闭保存 | 编辑后立即关闭窗口 | 进程正常退出，重新打开后最后一次编辑仍在 | 待执行 |
| VM-08 | 重启应用 | 完全退出后重新启动 | 笔记、标签、主题、收藏状态保持 | 待执行 |
| VM-09 | 重启系统 | 重启 Windows 后启动应用 | 数据仍在，无需重新初始化 | 待执行 |
| VM-10 | 覆盖升级 | 保持数据库，运行同版本或更高版本安装包 | 程序文件更新，笔记不丢失 | 待执行 |
| VM-11 | 卸载保留数据 | 设置 → 应用 → 卸载 | 程序目录和快捷方式移除；%LOCALAPPDATA%\Hephaestus 保留 | 待执行 |
| VM-12 | 重装读取 | 再次安装并启动 | 直接看到卸载前的笔记 | 待执行 |
| VM-13 | 自定义目录 | 安装到 D:\Apps\Hephaestus | 安装成功，数据仍写入 %LOCALAPPDATA%\Hephaestus | 待执行 |
| VM-14 | 桌面快捷方式 | 安装时勾选“创建桌面快捷方式” | 桌面出现快捷方式并可启动 | 待执行 |
| VM-15 | 数据目录保护 | 安装时把目录改为 %LOCALAPPDATA%\Hephaestus | 安装程序拒绝并给出中文提示 | 待执行 |
| VM-16 | 便携版 | 解压 ZIP，运行 Hephaestus\Hephaestus.exe | 无需安装即可启动，数据写入默认数据目录 | 待执行 |
| VM-17 | 单文件版 | 运行 Hephaestus-1.2.1-onefile.exe | 启动成功；首次启动稍慢；数据持久化 | 待执行 |
| VM-18 | 移动程序 | 把便携版目录移到其他路径后启动 | 程序可启动，数据目录不变 | 待执行 |
| VM-19 | WebView2 存在 | 在含 WebView2 的系统启动 | 正常打开窗口，无错误提示 | 待执行 |
| VM-20 | WebView2 缺失 | 在无 WebView2 的系统启动 | 中文提示、官方下载链接、退出码 2，不崩溃 | 待执行 |
| VM-21 | 安装前 WebView2 检测 | 无 WebView2 时运行安装包 | 安装向导中文提示并可打开官方下载页 | 待执行 |
| VM-22 | 单实例 | 应用运行时再次双击 | 不产生第二个后端；提示已有实例 | 待执行 |
| VM-23 | 端口占用 | 占用默认/自动端口后启动 | 自动改用其他空闲端口，窗口正常 | 待执行 |
| VM-24 | 日志隐私 | 写入含敏感文字的笔记，查看日志 | 日志不含笔记正文 | 待执行 |
| VM-25 | 数据库损坏 | 用损坏文件替换数据库后启动 | 给出错误提示，不静默重建或删除原文件 | 待执行 |
| VM-26 | 无 Python 确认 | 全程不安装 Python | 所有功能正常 | 待执行 |

## 命令行辅助验证

在虚拟机中运行：

    & "$env:LOCALAPPDATA\Programs\Hephaestus\Hephaestus.exe" --version
    & "$env:LOCALAPPDATA\Programs\Hephaestus\Hephaestus.exe" --check-runtime runtime.json
    & "$env:LOCALAPPDATA\Programs\Hephaestus\Hephaestus.exe" --self-test selftest.json --data-dir "$env:TEMP\heph-vm-data"

预期：版本输出 Hephaestus 1.2.1；--check-runtime 输出 JSON 并在有 WebView2 时返回 0；
--self-test 报告 ok、health、frozen 为 true。把 JSON 文件和截图一并归档。

## 验收标准

- VM-01 至 VM-19、VM-22 至 VM-26 全部通过。
- VM-20、VM-21 在无 WebView2 快照中通过；若系统无法移除 WebView2，
  至少验证提示文案和 --check-runtime 返回码，并在报告中注明限制。
- 卸载后用户数据库仍存在，重装后能读取旧笔记。
- 全程未安装 Python 或开发工具。
- 任何失败项记录截图、日志路径和复现步骤，不修改测试结论。

## 结果记录

执行人：____________  日期：____________
虚拟机软件/版本：____________  系统版本：____________
WebView2 版本（如有）：____________
安装包 SHA256 是否一致：____________
通过项：____ / 26
失败项及说明：________________________________________________
