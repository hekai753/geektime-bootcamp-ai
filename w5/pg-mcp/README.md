# pg-mcp — 自然语言数据库查询服务

**用自然语言查询 PostgreSQL 和 MySQL 数据库。** 提供两种使用方式：

- **Web UI**（`:8000`）：聊天式查询界面 + 可视化设置页，所有配置在网页上完成
- **MCP 服务器**（stdio）：接入 Claude Desktop / Claude Code 等 MCP 客户端

架构上两条入口共享同一套编排组件（`QueryOrchestrator`），配置统一读取
`pg-mcp.config.json`（Web 设置页可视化编辑），环境变量仍可覆盖一切。

---

## 功能特性

| 能力 | 说明 |
|---|---|
| 自然语言 → SQL | LLM 生成 SQL，安全校验后执行，AI 复核结果并给出 0-100 置信度 |
| 多数据库 | 同时配置多个 PostgreSQL / MySQL 库，按请求中的 `database` 字段路由 |
| 安全控制 | 只读强制、危险函数黑名单、表/列黑名单、EXPLAIN 策略，全部可配置 |
| 弹性 | 查询/LLM 并发限流、验证失败指数退避重试、熔断器 |
| 可观测 | Prometheus 指标（查询计数/耗时/LLM 调用/token/拒绝数）、请求级 tracing |
| LLM 可插拔 | `LLM_PROVIDER=openai` 或 `anthropic`（Claude API），一行配置切换 |

## 快速开始

### 前置条件

- Python 3.14+ 与 [uv](https://docs.astral.sh/uv/)
- 可访问的 PostgreSQL 和/或 MySQL 数据库
- 一个 LLM API Key（Anthropic 或 OpenAI）

### 安装与启动

```bash
cd pg-mcp
uv sync --all-extras

# 方式一：直接启动 Web UI（默认 http://localhost:8000）
uv run python -m pg_mcp.webapp

# 方式二：在设置页里完成以下配置（也可写 .env / pg-mcp.config.json）
#   1. 数据库连接（PostgreSQL / MySQL）
#   2. LLM Provider 与 API Key
# 保存后组件自动热重载，立即可用
```

### Web UI

打开 `http://localhost:8000`：

- **聊天页**：选择目标库 → 输入自然语言问题 → 展示生成的 SQL、查询结果表格、
  执行耗时与置信度；`return_type=sql` 模式只生成 SQL 不执行
- **设置页**（右上角 ⚙）：数据库连接（类型/主机/端口/库名/账号）、附加数据库、
  LLM Provider 与密钥、表/列黑名单、EXPLAIN 开关、并发限流参数。
  保存即写入 `pg-mcp.config.json` 并热生效

### 接入 Claude Desktop / Claude Code（零 env 配置）

因为配置都在 `pg-mcp.config.json` 里，MCP 配置文件**不再需要 env 块**：

```json
{
  "mcpServers": {
    "postgres": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/pg-mcp",
        "run", "python", "main.py"
      ]
    }
  }
}
```

MCP 入口在进程启动时读取配置；设置页改动后重启 Claude Desktop 即生效。

## 配置

优先级：**环境变量 > `pg-mcp.config.json` > 默认值**

| 配置方式 | 适用场景 |
|---|---|
| Web 设置页 | 日常使用、演示（推荐） |
| `pg-mcp.config.json` | 随项目保存的非敏感配置（已 gitignore） |
| 环境变量 / `.env` | 容器、CI、覆盖特定项 |

主要配置项（环境变量名）：

```bash
# 主数据库（DATABASE_*，别名为主库名）
DATABASE_DB_TYPE=postgres        # 或 mysql
DATABASE_HOST=10.128.8.20
DATABASE_PORT=5432
DATABASE_NAME=blog_small
DATABASE_USER=he3db
DATABASE_PASSWORD=...

# 附加数据库（JSON map，别名 -> 连接配置）
DATABASES={"mysql_blog": {"db_type": "mysql", "host": "...", "port": 3306, "name": "blog_small", "user": "root", "password": "..."}}

# LLM
LLM_PROVIDER=anthropic           # openai | anthropic
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_API_KEY=...            # 或网关变量
ANTHROPIC_BASE_URL=...           # Anthropic 兼容网关（可选）
ANTHROPIC_AUTH_TOKEN=...         # Bearer token 方式（可选）
ANTHROPIC_MODEL=claude-haiku-4-5

# 安全
SECURITY_BLOCKED_TABLES=secrets, audit_log
SECURITY_BLOCKED_COLUMNS=password_hash
SECURITY_ALLOW_EXPLAIN=false
SECURITY_MAX_ROWS=10000
SECURITY_MAX_EXECUTION_TIME=30

# 弹性（已实际生效于请求路径）
RESILIENCE_QUERY_RATE_LIMIT=10   # 最大并发查询
RESILIENCE_LLM_RATE_LIMIT=5      # 最大并发 LLM 调用
RESILIENCE_MAX_RETRIES=3
RESILIENCE_RETRY_DELAY=1.0
RESILIENCE_BACKOFF_FACTOR=2.0
RESILIENCE_CIRCUIT_BREAKER_THRESHOLD=5
```

完整模板见 `.env.example`。

## 架构

```
Claude Desktop ──stdio──┐
                        ▼
                  server.py (MCP)          webapp (FastAPI :8000)
                        └────────┬─────────────┘
                                 ▼  共享组件（同一装配、同一配置）
                        QueryOrchestrator
        ┌───────────┬───────────┼────────────┬──────────────┐
        ▼           ▼           ▼            ▼              ▼
   SQLGenerator  SQLValidator  SQLExecutor  ResultValidator  Metrics/Tracing
   (openai|      (sqlglot      (PG|MySQL    (openai|         (限流/熔断/
    anthropic)    方言感知)      驱动适配)     anthropic)       重试已接入)
        └───────────┴───────────┴──────┬─────┴──────────────┘
                                       ▼
                        PostgreSQL (asyncpg) | MySQL (aiomysql)
```

查询流水线：解析库路由 → Schema 缓存 → LLM 生成 SQL → 安全校验（黑名单/只读/
方言解析）→ 只读事务执行（行数限制/超时）→ LLM 结果验证（置信度）→ 结构化响应。

## 测试

```bash
uv run pytest --cov=src --cov-report=term   # 全量（unit 无外部依赖；integration/e2e 需真实 PG）
uv run pytest tests/unit -q                 # 仅单元测试（mock，无需数据库）
uv run ruff check . && uv run mypy src      # Lint 与类型检查
```

- 集成 / E2E 测试需要真实 PostgreSQL（加载 `fixtures/01_small_db.sql`）
- MySQL 支持的测试库脚本：`fixtures/04_mysql_blog.sql`
- 安全模块（sql_validator 等）覆盖率 ≥95%，总体 ≥80%

## 效果截图

| 文件 | 内容 |
|---|---|
| `screenshots/ui-chat.png` | Web UI：同一次会话中路由 PostgreSQL 与 MySQL 两个库，展示生成的 SQL、结果表格与置信度 |
| `screenshots/mcp-tool.png` | MCP stdio 入口：`tools/list` 与 `tools/call query` 的真实协议交互结果 |

## 测试数据

`fixtures/` 提供三套规模的测试库：

| 脚本 | 引擎 | 规模 |
|---|---|---|
| `01_small_db.sql` | PostgreSQL | blog_small，7 表 + 3 视图 |
| `02_medium_db.sql` | PostgreSQL | 电商，25 表 |
| `03_large_db.sql` | PostgreSQL | CRM，55+ 表 |
| `04_mysql_blog.sql` | MySQL | blog_small 的 MySQL 版 |

无本地 psql 客户端时可用 `scripts/load_fixture.py` 加载 PG fixture。

## Docker 部署

`docker-compose.yml` 同时提供 PostgreSQL、MySQL（自动灌入测试库）与 pg-mcp 服务：

```bash
docker-compose up -d
docker-compose logs -f pg-mcp
```

## 安全说明

- 默认只读：仅允许单条 SELECT；PG 端在只读事务中执行，并设置安全 `search_path`
- 表/列黑名单、危险函数黑名单（`pg_sleep`、文件 I/O 等）在 SQL 解析层强制
- MySQL 只读性依赖 SQL 校验层 + 只读账号（建议），不依赖事务特性
- API Key/密码在本机配置文件中为明文（已 gitignore），`GET /api/settings` 永不
  回传完整密钥；生产环境请使用只读账号与秘密管理服务

## 故障排查

| 现象 | 处理 |
|---|---|
| `llm_unavailable` / 认证失败 | 检查 Provider 对应的 API Key；网关需同时配 `ANTHROPIC_BASE_URL` |
| 启动时连不上库 | 确认 `.env` / 设置页中的连接信息；`DATABASE_*` 环境变量会覆盖配置文件 |
| 请求被限流 | 调大 `RESILIENCE_QUERY_RATE_LIMIT` / `RESILIENCE_LLM_RATE_LIMIT` |
| 改了配置 MCP 未生效 | stdio 进程启动时读配置，重启 Claude Desktop |

## 许可证

仅供课程作业演示使用。
