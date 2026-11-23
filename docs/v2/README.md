# Hephaestus V2.0 文档

本目录保存 V2.0 跨平台升级的阶段文档。当前处于**阶段 A：审查与架构决策**，业务代码未修改。

| 文档 | 内容 |
|---|---|
| [01-current-state.md](01-current-state.md) | 仓库、测试、真实数据、架构、平台与工具链现状 |
| [02-architecture-decision.md](02-architecture-decision.md) | Capacitor/Tauri/Python 移动方案比较与推荐架构 |
| [03-development-plan.md](03-development-plan.md) | 阶段 B–H 的交付、验收、测试矩阵与回滚 |
| [04-risk-register.md](04-risk-register.md) | 风险、阻塞项、停止条件 |
| [05-phase-a-report.md](05-phase-a-report.md) | 阶段 A 结论与决策请求 |

## 当前状态

- 分支：`feat/v2-cross-platform`
- 基线：`main` / `3e341a5aeb486fb825fae2f71a0c9f7955ba040f`
- 现有测试：60 passed（1 warning）
- 真实用户数据：`frontend_state` 1 行（7 条笔记、4 个标签）；`notes` 表 0 行
- 未执行数据库迁移、未修改用户数据、未构建任何新平台安装包

## 待确认

1. 是否批准“Python 桌面/Web + Capacitor 移动 + 原生 SQLite”的方案 A。
2. 移动端首版功能子集是否可接受。
3. 是否提供 macOS/Xcode/Apple 签名、Linux、Android 构建环境。