# Hephaestus V2.0 文档

本目录保存 V2.0 跨平台升级的阶段文档。阶段 A、B1、B2、B3、C1 与 C1.1 已完成并等待验收；当前等待 **真实库迁移的单独授权**。真实库尚未迁移；C1/C1.1 只完成后端 AI Provider 架构与安全复核，聊天 UI、人格、RAG、语音、附件送入模型、业务 UI 重构与安装包尚未开始。

| 文档 | 内容 |
|---|---|
| [01-current-state.md](01-current-state.md) | 仓库、测试、真实数据、架构、平台与工具链现状 |
| [02-architecture-decision.md](02-architecture-decision.md) | Capacitor/Tauri/Python 移动方案比较与推荐架构 |
| [03-development-plan.md](03-development-plan.md) | 阶段 B–H 的交付、验收、测试矩阵与回滚 |
| [04-risk-register.md](04-risk-register.md) | 风险、阻塞项、停止条件 |
| [05-phase-a-report.md](05-phase-a-report.md) | 阶段 A 结论与决策请求 |
| [06-data-contract.md](06-data-contract.md) | 统一数据契约、实体字段、删除/恢复规则、版本策略 |
| [07-schema-and-migration.md](07-schema-and-migration.md) | v2_* 表结构、迁移算法、真实数据演练与回滚 |
| [08-dataport-and-api.md](08-dataport-and-api.md) | Python/TypeScript DataPort 与 /api/v2 |
| [09-migration-drill.md](09-migration-drill.md) | 7 条真实笔记的独立副本迁移报告 |
| [10-contract-tests.md](10-contract-tests.md) | 桌面端/移动端契约测试与结果 |
| [11-phase-b1-report.md](11-phase-b1-report.md) | B1 验收清单、改动文件、测试与授权请求 |
| [12-frontend-dataport.md](12-frontend-dataport.md) | 前端 DataPort 架构、四态状态机、journal、错误与限制 |
| [13-phase-b2-report.md](13-phase-b2-report.md) | B2 验收清单、十项要求与恢复场景、真实窗口验证与授权请求 |
| [14-b3-real-data-inventory.md](14-b3-real-data-inventory.md) | B3 真实数据只读盘点 |
| [15-b3-copy-drill-report.md](15-b3-copy-drill-report.md) | B3 真实备份副本迁移、幂等与回滚演练 |
| [16-b3-data-integrity-report.md](16-b3-data-integrity-report.md) | B3 逐字段完整性校验 |
| [17-b3-rollback-report.md](17-b3-rollback-report.md) | B3 回滚与失败恢复验证 |
| [18-b3-migration-runbook.md](18-b3-migration-runbook.md) | B3 正式迁移预案（未执行） |
| [19-b3-ui-acceptance.md](19-b3-ui-acceptance.md) | B3 迁移副本真实 UI 验收 |
| [20-phase-b3-report.md](20-phase-b3-report.md) | B3 阶段总报告、测试结果、限制与下一步授权 |
| [21-ai-provider-architecture.md](21-ai-provider-architecture.md) | C1 AI Provider 分层、适配器、密钥、SSRF、API 与限制 |
| [22-phase-c1-report.md](22-phase-c1-report.md) | C1 阶段总报告、测试结果、改动文件与验收请求 |
| [23-ai-security-audit.md](23-ai-security-audit.md) | C1.1 AI Provider 安全复核、风险分级、修复与残余风险 |

## 当前状态

- 分支：`feat/v2-cross-platform`
- 基线：`main` / `3e341a5aeb486fb825fae2f71a0c9f7955ba040f`
- 现有测试：129 项；Windows 128 passed + 1 skipped（1 warning：Starlette httpx/TestClient 弃用提示），Linux CI 预计 122 passed + 7 skipped（待 GitHub Actions 验证）
- 其中 B1 新增 14 项 Python 测试；B2 新增 10 项 Python 测试；B3 新增 4 项迁移测试（8 项迁移测试总计）；C1 新增 16 项 AI 测试；C1.1 新增 25 项 AI 安全测试
- 前端 DataPort Node 测试：8 passed；移动端 5 项 Node 契约测试
- 真实用户数据：`frontend_state` 1 行（7 条笔记、4 个标签）；`notes` 表 0 行
- 真实库 SHA256 仍为 e16595...；未执行真实迁移、未修改用户数据、未构建任何新平台安装包
- B1 已在独立副本上完成迁移、完整性、幂等、备份恢复演练
- B2 已完成四种数据状态、单写入源、冲突与断网保存、刷新/重开、重复提交、初始化失败恢复的真实窗口验证
- B3 已完成真实数据只读盘点、独立备份、副本迁移、逐字段校验、幂等、失败恢复、回滚演练和迁移副本的真实 UI 验收
- C1 已完成统一 AI Provider 抽象、Ollama/OpenAI 兼容适配器、密钥托管、SSRF 防护、/api/v2/ai/* 与 16 项测试；未实现聊天 UI 与模型自动读取笔记
- C1.1 已完成 Host/Origin 边界、DNS pinning、CGNAT/IPv4-mapped SSRF 修复、422 密钥回显修复、跨进程密钥锁、请求体/并发限制与 25 项安全测试；未引入用户鉴权
- **真实库未迁移**；B3.4 迁移预案未执行，C1/C1.1 未修改真实库

## 待确认

1. 是否授权执行真实库迁移，并确定迁移窗口、操作人与备份位置。
2. 是否接受 B3 已知限制（无独立冲突中心、5MB 配额、多标签页、未做断电/磁盘写满测试）。
3. 是否提供 macOS/Xcode/Apple 签名、Linux、Android 构建环境（阶段 G）。