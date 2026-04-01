# AI 量化交易平台环境搭建说明

## 目标

这份文档服务于当前真实可运行版本，而不是早期草案。目标是：

- 新环境能快速恢复
- 本地开发、演示部署、外部托管依赖三种场景能切换
- 新 Agent 接手时能快速判断当前真实技术栈和部署方式

## 技术栈选择

### 前端

- 多页面 HTML
- Vanilla JavaScript
- CSS
- 由 FastAPI 统一托管

### 后端

- Python 3.11
- FastAPI
- Uvicorn
- SQLAlchemy

### 数据与分析

- SQLite
- PostgreSQL
- Redis
- MinIO
- pandas

### AI 组件

- OpenAI 兼容 LLM API 配置预留
- 当前主链路仍以规则模板和结构化逻辑为主

### 部署方式

- Docker
- Docker Compose
- 本地直跑 FastAPI

## 服务组成

当前真实运行链路以一个 API 容器为中心：

1. `api`
   - 提供页面和业务接口
2. `postgres`
   - 共享环境的业务数据库
3. `redis`
   - 异步队列和状态缓存预留
4. `minio`
   - 对象存储预留

当前没有独立 `web` 服务，也没有独立 `worker` 服务；这些是后续演进方向，不是本版真实架构。

## 推荐目录结构

```text
repo/
├── apps/
│   └── api/
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.external.yml
│   └── deploy.env.example
├── tools/
│   └── verify_infra_stack.py
├── storage/
└── 产品设计/
```

## 环境变量

```env
APP_ENV=development
APP_NAME=AI Quant Platform API
APP_PUBLIC_URL=http://127.0.0.1:8000
API_PREFIX=/api/v1

DATABASE_URL=sqlite+pysqlite:///./quant_platform.db
MARKET_DATA_DATABASE_PATH=./market_data.db
MARKET_DATA_PROVIDER=auto
TUSHARE_TOKEN=

REDIS_URL=

MINIO_ENDPOINT=
MINIO_CONSOLE=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=quant-platform

LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL_STRATEGY=
LLM_MODEL_SUMMARY=
ALLOWED_LLM_EXPORT_FIELDS=symbol,side,entry_time,exit_time,pnl,feature_snapshot

BACKTEST_ENGINE_VERSION=engine_v1
STRATEGY_PROMPT_VERSION=v1
REPLAY_PROMPT_VERSION=v1
JOB_EXECUTION_MODE=background
JOB_SIMULATION_LATENCY_MS=100
```

## 本地开发步骤

### 1. 准备 Python 环境

- 创建 `.venv`
- 安装 `apps/api`
- 复制 `.env.example` 为 `.env`

### 2. 启动应用

```bash
uvicorn quant_platform_api.main:create_app --factory --app-dir apps/api/src --host 0.0.0.0 --port 8000 --reload
```

### 3. 访问页面

- 首页：`/`
- 登录：`/login`
- 工作台：`/workspace`

### 4. 跑测试

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## Docker Compose 设计

### 本地一体化

使用 `infra/docker-compose.yml` 启动：

- API
- PostgreSQL
- Redis
- MinIO

### 外部托管依赖

使用 `infra/docker-compose.external.yml` 只启动 API，并把环境变量指向外部 PostgreSQL / Redis / MinIO。

## 为什么选这个方案

- 比旧版“前后端分离 + 独立 worker”的草案更符合当前代码现实
- 比完全手工搭环境更容易接力
- 比只保留 SQLite 更接近真实部署
- 能处理开发、演示、托管依赖三种环境差异

## 样例数据准备

当前版本不要求额外导入大型预置样例才能启动，但建议准备：

### 行情样例

- 至少一个股票或 ETF 标的
- 一个完整回测时间段

### 交割单样例

- 至少一份可解析的交易记录文件
- 用于验证上传和复盘链路

## 本周环境范围边界

本阶段要求做到：

- 本地开发可运行
- Docker 镜像可构建
- 可选择本地依赖或外部依赖部署
- 业务链路可测试和验证

本阶段暂不要求：

- 生产级高可用
- 自动扩缩容
- 多 worker 集群
- 实盘交易安全隔离

## 数据治理与安全边界

- 不把密钥写入仓库
- 对外部 LLM 只暴露白名单字段
- 原始交易文件、解析记录和复盘结论需要分层保存
- 市场缓存数据库与业务数据库分离
- 运行态数据库文件不进入 Git 仓库

## 环境搭建验收标准

- 页面可访问
- 后端接口可访问
- 自动化测试通过
- `/healthz` 返回正常
- PostgreSQL / Redis / MinIO 可按环境变量切换
- `tools/verify_infra_stack.py` 能验证依赖状态
- 能跑通登录 -> 策略 -> 回测 -> 查看结果的最短链路
