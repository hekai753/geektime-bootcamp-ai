---
description: 查询数据库并把结果导出为 CSV/JSON 文件;未注册的库可自动添加连接,一键完成"查询+导出"。
argument-hint: "[库名] [SQL 或自然语言] [csv|json]"
---

# /export-query — 查询并导出

把「查询数据库 → 导出结果文件」自动化为一条命令,覆盖完整链路:
**新库自动注册连接 → 执行查询 → 主动确认格式 → 写出文件**。

过程中显式分解为三个子任务(呼应"Agent 任务分解"):
**①获取结果 → ②格式化数据 → ③创建文件**。

## 用户输入

```text
$ARGUMENTS
```

参数可能包含:数据库名 `DB`、查询 `Q`(SQL 或自然语言)、导出格式 `FMT`(csv|json)。
任一缺失时**主动询问用户**,不要臆测。

## 约定

- 后端地址 `http://localhost:8000`,API 前缀 `/api/v1`;健康检查 `GET /health`。
- 导出目录:`w2/db_query/exports/`(不存在则用 `mkdir -p` 创建)。
- 只读:只接受 SELECT(后端强制,你也只生成 SELECT)。
- 调 API 用 `curl -s`;注意 shell 转义。

## 执行步骤

### 1. 解析意图
从 `$ARGUMENTS` 提取 `DB`、`Q`、`FMT`。若 `Q` 是自然语言(中文描述,或非 `SELECT`/`WITH` 开头)则记 `IS_NL=true`。缺哪项就问哪项。

### 2. 后端在线检查
`curl -s http://localhost:8000/health`。失败 → 提示用户先在 `w2/db_query` 下跑 `make dev-backend`,然后停止。

### 3. 确认库已注册(命令行加连接能力)
`curl -s http://localhost:8000/api/v1/dbs` 列出已注册连接,检查 `DB` 是否出现在某条记录的 `name` 字段。

- **已注册** → 继续。
- **未注册** → 主动询问用户提供连接 URL,并提示格式:
  - MySQL:`mysql://user:pass@host:3306/dbname`
  - PostgreSQL:`postgresql://user:pass@host:5432/dbname`
  - ⚠️ 密码含 `@` 等特殊字符时**直接写原字符,不要 URL 编码**(本项目的 `urlparse` 不解码 password)。
  - 拿到 URL 后注册:
    ```
    curl -s -X PUT http://localhost:8000/api/v1/dbs/$DB \
      -H "Content-Type: application/json" \
      -d '{"url":"<URL>","description":"added via /export-query"}'
    ```
  - 若返回错误(连接测试失败)→ 如实转告 detail 并停止。

### 4. 获取结果(子任务 ①)
- 若 `IS_NL`:先
  ```
  curl -s -X POST http://localhost:8000/api/v1/dbs/$DB/query/natural \
    -H "Content-Type: application/json" -d '{"prompt":"<Q>"}'
  ```
  从响应 `sql` 字段取出 SQL,**展示给用户**(可编辑),再继续。
- 否则 SQL = `Q`。
- 执行查询:
  ```
  curl -s -X POST http://localhost:8000/api/v1/dbs/$DB/query \
    -H "Content-Type: application/json" -d '{"sql":"<SQL>"}'
  ```
  得到 `{columns, rows, rowCount, executionTimeMs, sql}`。出错(detail 字段)→ 转告并停止。

### 5. 展示摘要
打印:行数 `rowCount`、耗时 `executionTimeMs`、列名、前 3 行预览。

### 6. 主动询问格式(导出前的交互)
若 `FMT` 未指定 → 主动问:**"需要把这次查询结果导出吗?导出成 CSV 还是 JSON?"**,等用户回答。已指定则跳过。

### 7. 格式化并创建文件(子任务 ② + ③)
由你亲自完成,演示任务分解:
- **格式化**:
  - CSV:首行表头(列名,逗号分隔);值含逗号/引号/换行 → 用双引号包裹,内部引号双写(`"` → `""`);NULL → 空;换行用 `\n`。
  - JSON:`JSON.stringify(rows, null, 2)` —— 缩进 2 空格的行对象数组。
- **创建文件**:写到 `w2/db_query/exports/${DB}_<YYYYMMDDTHHMMSS>.${FMT}`,用 Write 工具落盘。
- **备选(可一并告知用户)**:若不想自己格式化或结果较大,可走服务端一键导出:
  ```
  curl -X POST "http://localhost:8000/api/v1/dbs/$DB/export?format=$FMT" \
    -H "Content-Type: application/json" -d '{"sql":"<SQL>"}' -o <文件路径>
  ```

### 8. 报告
打印:文件绝对路径、导出行数、文件字节数(`wc -c <文件>`)。

## 错误处理
- 连接测试失败 → 转告后端返回的 detail,建议检查 URL / 网络 / 凭据。
- SQL 非法或非 SELECT → 转告 `"Only SELECT statements are allowed"`,建议改为只读查询。
- 库不存在且用户拒绝提供 URL → 礼貌停止。
