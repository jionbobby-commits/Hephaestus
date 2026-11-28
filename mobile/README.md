# Hephaestus Mobile（B1）

这是 V2.0 移动端数据层的第一个骨架，不是可安装的 APK/IPA。当前只包含：

- JSON 数据契约（TypeScript 类型）
- V2 SQLite schema
- 可替换的 SqliteClient 接口
- Node 22 SQLite 适配器（仅用于开发/契约测试）
- TypeScript DataPort
- 共享 fixture 契约测试

Capacitor 壳、原生 SQLite 插件、UI、i18n、附件上传在后续阶段接入；本目录不声称已经有可运行 App。

## 环境

- Node.js 22（开发测试使用 22.14.0）
- npm（仅安装 typescript 与 @types/node）
- 不要求最终用户安装 Node

## 命令

~~~powershell
cd mobile
npm install
npm run typecheck
npm run test
~~~

npm run test 等价于：

~~~powershell
node --experimental-strip-types --experimental-sqlite --test tests/contract.test.ts
~~~

Node 22 会打印 Type Stripping / SQLite 的实验特性警告；测试仍应 5 passed。

## 与桌面端共享

- 契约样例：../contracts/v2/contract_fixture.json
- Python 实现：../app/v2
- 字段、时间格式、布尔转换、revision 冲突、key_ref 不暴露规则必须与 Python DataPort 一致。

## 安全

- 不写入真实用户数据库；测试使用内存 SQLite。
- AI 配置只保存 key_ref，读取不返回密钥。
- node_modules 不进 Git。
