# Hephaestus V1.2.1 发布说明

发布日期：2026-11-22
版本号：1.2.1
分支：feat/windows-release-v1.2

## 本次重点

V1.2.1 修复了 V1.2 桌面版启动后偶发弹出的“本地服务连续 3 次健康检查失败”误报。
前端页面、Web API 和数据库结构保持不变。

## 根本原因

桌面窗口的健康巡检线程收到的是服务根地址 http://127.0.0.1:端口，而不是健康检查地址。
根路径返回的是前端 index.html（HTTP 200），旧实现直接对响应做 json.loads，
抛出 JSONDecodeError 后把检查判为失败；连续 3 次失败便弹出告警。
服务本身一直正常，因此日志里没有任何后端异常。

旧实现还有两个问题：check_health 用 except Exception 吞掉了异常和状态码，
无法从日志判断失败类型；巡检线程在窗口初始化阶段就开始计时，没有启动宽限。

## 修复内容

- 健康检查地址统一归一化：根地址自动补 /health，完整 /health 地址保持不变。
- 健康探测返回结构化结果，记录 URL、HTTP 状态码、耗时、异常类型、异常信息和堆栈。
- 健康检查显式绕过系统代理直连 127.0.0.1，避免代理软件干扰本机回环请求。
- 巡检失败时记录完整原因，并区分超时、连接失败、HTTP 状态异常、响应格式异常。
- 增加启动宽限期、失败确认探测、后端线程存活检查和停止事件：
  瞬时抖动不会提示用户；后端线程确实退出或持续不可用才告警。
- 关闭窗口时先停止巡检线程，避免退出过程中误报。
- 根因回归测试和 12 类启动/健康检查场景测试全部加入自动化测试。

## 发布文件

| 文件 | 大小（字节） | SHA256 |
|---|---|---|
| Hephaestus-Setup-1.2.1.exe | 22,440,810 | 3d8bb1fc4522a7132bf001b07bcce584c2d20373287306ab17e73edb32b394cd |
| Hephaestus-Portable-1.2.1.zip | 24,204,193 | 728fbeabd517c3cf9415a98b902065a3a3abaae5ffaf1d9b0779be3e22daf69c |
| Hephaestus-1.2.1-onefile.exe | 24,312,022 | 8626eae53519d491cf82852450549bb91dafecf3f55a48af48b1c15a0350525a |

安装包使用 onedir 产物构建，解压后的程序目录约 43.96 MB（99 个文件）；
便携版 ZIP 包含同一个 onedir 目录；单文件 EXE 首次启动会解压到临时目录，速度略慢。

## 安装与升级

默认安装目录：%LOCALAPPDATA%\Programs\Hephaestus。安装程序拒绝把程序装进
%LOCALAPPDATA%\Hephaestus，该目录专用于用户数据。

从 1.2.0 覆盖升级直接运行 1.2.1 安装程序即可，AppId 保持不变，程序文件被替换，
数据库不动。如果 Hephaestus 正在运行，安装程序会请求关闭占用文件的实例。

## 数据兼容

- 用户数据库位于 %LOCALAPPDATA%\Hephaestus\hephaestus.db，在安装目录之外。
- 卸载程序不删除数据库、日志和配置；卸载后重新安装可以继续读取原有笔记。
- 数据库只通过 SQLAlchemy create_all 补齐缺失的表，不会重建或清空已有数据。
- 覆盖升级和卸载后重装均已验证旧笔记仍可读取。
- Web 模式继续使用 data/hephaestus.db 或 HEPHAESTUS_DATABASE_URL，与桌面版互不影响。
- 测试使用临时数据目录；真实用户数据库 SHA256 在测试前后一致。

## 验证结果

- pytest：55 passed，1 warning（Starlette TestClient 的 httpx 弃用提示，不影响功能）。
- 健康检查专项：15 passed，覆盖根地址回归、慢启动、超时、连接失败、HTTP 异常、
  响应格式异常、瞬时抖动、确认故障、停止事件、启动宽限和后端线程退出。
- 桌面测试：24 passed，新增连续启动关闭和健康巡检接线测试。
- 安装包集成测试：2 passed，覆盖首次安装、启动、写入、覆盖升级、卸载保留数据、重装读取。
- onedir 实际桌面窗口：启动后 25 秒内 48 次健康检查全部成功，无告警，正常关闭，退出码 0。
- onefile 实际桌面窗口：启动后 25 秒内 48 次健康检查全部成功，无告警，正常关闭，退出码 0。
- 两个 EXE 的 --check-runtime 均输出 1.2.1，检测到 WebView2 152.0.4191.66。

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