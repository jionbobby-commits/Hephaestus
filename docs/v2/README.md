# Hephaestus V2.0 文档

本目录保存 V2.0 跨平台升级的阶段文档。阶段 A 已完成；当前处于**阶段 B1：数据架构与迁移演练**，业务 UI、AI、安装包尚未开始。

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

## 当前状态

- 分支：`feat/v2-cross-platform`
- 基线：`main` / `3e341a5aeb486fb825fae2f71a0c9f7955ba040f`
- 现有测试：74 passed（1 warning：Starlette httpx/TestClient 弃用提示）
- 其中 B1 新增 14 项 Python 测试；移动端 5 项 Node 契约测试
- 真实用户数据：`frontend_state` 1 行（7 条笔记、4 个标签）；`notes` 表 0 行
- 真实库 SHA256 仍为 e16595...；未执行真实迁移、未修改用户数据、未构建任何新平台安装包
- B1 已在独立副本上完成迁移、完整性、幂等、备份恢复演练

## 待确认

1. B1 验收是否通过，是否授权进入 B2（前端 API 适配/双写策略/迁移执行方案）。
2. 真实库迁移的窗口与操作人；B1 不自行迁移。
3. 是否提供 macOS/Xcode/Apple 签名、Linux、Android 构建环境（阶段 G）。