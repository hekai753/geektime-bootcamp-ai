# 数据导出功能 — 设计文档(作业提交物)

## 1. 功能概述

为「智能数据库查询工具」新增数据导出能力,支持将查询结果导出为 **CSV** 与 **JSON** 两种格式。提供三条**互补**的使用路径:

| 路径 | 入口 | 特点 |
|------|------|------|
| Web 界面按钮 | `Home.tsx` 的 EXPORT CSV / EXPORT JSON | 纯前端下载(已有,第二周完成) |
| 后端导出端点 | `POST /api/v1/dbs/{name}/export?format=csv\|json` | 服务端生成文件,脚本/大数据友好(本次新增) |
| 命令行自动化 | Claude Code command `/export-query` | 一条命令完成「查询+导出」,新库可自动注册连接(本次新增) |

## 2. 设计动机

导出代码在前端其实已经存在(`Home.tsx` 的 `handleExportCSV/handleExportJSON`,见 `PHASE3_IMPLEMENTATION.md`)。但仅有"鼠标点按钮"一种方式,存在四个缺口:

1. **命令行无法导出** —— 运维/脚本场景必须开浏览器。
2. **新库要先开 web 注册连接** —— 命令行自动化链路在第一步就断了。
3. **大数据集撑爆浏览器** —— 纯前端把全量结果载入内存拼字符串,几万行就卡顿/崩溃。
4. **没有 AI 交互** —— 不会主动询问"要不要导出"。

因此本次**不在前端重复造轮子**,而是「后端补端点 + Claude Code 补自动化」,把导出从"手工点击"提升为"一键 / 一句话触发"。这正是作业要求的:从代码实现 → **功能规划与自动化流程设计**。

## 3. 架构

```
┌─ Web 浏览器 ─────────────────────────────────────────┐
│ Home.tsx: EXPORT CSV / EXPORT JSON (纯前端 Blob 下载) │  ← 已有
└──────────────────────────────────────────────────────┘

┌─ 命令行(Claude Code)─────────────────────────────────┐
│ /export-query                                         │  ← 新增
│   解析 → 加连接(若新库) → /query → 格式化 → 写文件   │
│                                  (子任务分解,见 §4)    │
│        │ 也可改走 ↓                                    │
│        └─► POST /api/v1/dbs/{name}/export              │  ← 新增(服务端导出)
└──────────────────────────────────────────────────────┘
                 │ 复用 execute_query_with_service
                 ▼
        PostgreSQL / MySQL adapter(SQLModel + sqlglot 只读校验)
```

**关键复用**:export 端点直接调用 `execute_query_with_service`(`app/services/query_wrapper.py`),自动继承 **SELECT-only 校验、查询历史记录、自动 LIMIT 1000**,无需在导出逻辑里重复实现。格式化逻辑独立为 `app/services/exporter.py`(`to_csv` / `to_json`),可单独测试。

## 4. 自动化流程设计(command 的任务分解)

`/export-query`(`.claude/commands/export-query.md`)把"导出数据"这个复杂任务显式分解为三个子任务,由 Claude 编排:

1. **获取结果** — 判断库是否已注册(否则询问 URL 并 `PUT` 注册)→ 执行 SQL(自然语言则先调 `/query/natural` 转 SQL 并展示)→ 拿到 `QueryResult`。
2. **格式化数据** — CSV(RFC 4180:逗号/引号/换行转义、NULL→空)/ JSON(缩进 2 空格的行对象数组)。
3. **创建文件** — 写到 `exports/{db}_{时间戳}.{格式}`。

这种分解让每一步**可观察、可中断、可替换** —— 例如第 2/3 步可整体替换为一次 `curl POST /export -o file`(服务端导出),体现"获取/格式化/创建"的解耦。

## 5. 用户交互设计

- **参数缺失主动问**:库名 / 查询 / 格式任一缺失,command 主动询问而非臆测。
- **新库主动问 URL**:检测到库未注册 → 主动问连接串,并给出格式提示(含本项目特有的坑:密码含 `@` 等**直接写原字符,不要 URL 编码**,因为 `urlparse` 不解码 password)。
- **导出前确认格式**:查询结果展示后,主动问"需要导出吗?CSV 还是 JSON?"。
- **自然语言入口**:用户可输入中文(如"查询最近 10 条订单"),command 先转 SQL 并展示给用户确认。

## 6. 工具链整合

| 工具 | 擅长 | 在本项目的职责 |
|------|------|---------------|
| **Cursor** | 快速写/改代码 | 后端 export 端点、`exporter.py`、`QuerySource.EXPORT`、前端导出按钮(前期) |
| **Claude Code** | 多步骤自动化、Agent 编排 | `/export-query` command、子任务分解、主动交互式询问 |

二者互补:Cursor 产出"可调用的能力(端点)",Claude Code 把这些能力编排成"一条命令的自动化流程"。

## 7. 使用示例

```bash
# 1) 已注册库,直接导出
/export-query mysql "SELECT * FROM users LIMIT 100" csv

# 2) 自然语言查询并导出
/export-query mysql 查询最近10条订单 json

# 3) 新库(command 会主动询问连接 URL,注册后再导出)
/export-query newshop "SELECT 1" csv

# 4) 纯后端一键导出(脚本/cron 友好,不依赖 Claude)
curl -X POST "http://localhost:8000/api/v1/dbs/mysql/export?format=csv" \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT * FROM users LIMIT 10"}' -o users.csv
```

后端响应头会带:`Content-Disposition: attachment; filename="mysql_20260805T155215.csv"`。

## 8. 局限与未来

- **真流式导出**:当前 `execute_query` 一次性 `fetchall`,超大结果集仍占内存;未来可用 MySQL `SSCursor` / PostgreSQL server-side cursor 逐行 `yield`(配合 `StreamingResponse`)。
- **更多格式**:Excel `.xlsx`(需 `openpyxl`)、SQL `INSERT` 语句、Markdown 表格。
- **定时 / 批量导出**:结合 cron 或 `/export-query` 编排多库批量任务。
- **权限与审计**:导出敏感库时增加二次确认或列级脱敏。

## 附:本次改动清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/services/exporter.py` | 新增 | `to_csv` / `to_json` 格式化 |
| `backend/app/api/v1/exports.py` | 新增 | `POST /{name}/export` 端点 |
| `backend/app/models/query.py` | 修改 | `QuerySource` 新增 `EXPORT` |
| `backend/app/main.py` | 修改 | 注册 exports router |
| `.claude/commands/export-query.md` | 新增 | 命令行自动化 command |
| `exports/.gitignore` | 新增 | 忽略导出产物 |
| `fixtures/test.rest` | 修改 | 追加 export 端点测试范例 |
