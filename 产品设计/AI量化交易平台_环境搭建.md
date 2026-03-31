# AI 量化交易平台环境搭建说明

## 目标

这份环境搭建说明用于支撑第一周开发和演示，目标是：

- 开发环境能快速启动
- 演示环境稳定可访问
- 不引入超出一周项目的运维复杂度

## 技术栈选择

### 前端

- React
- Next.js
- TypeScript
- pnpm

### 后端

- Python 3.11
- FastAPI
- Uvicorn

### 数据与分析

- PostgreSQL 15
- Redis 7
- pandas / polars
- pandas-ta

### AI 组件

- OpenAI 兼容 LLM API
- 结构化输出模式

### 部署方式

- Docker Compose

## 服务组成

开发和演示环境包含 5 个核心服务：

1. `web`
   - 提供策略实验室和复盘页面
2. `api`
   - 提供策略生成、回测、复盘相关接口
3. `postgres`
   - 存储元数据和结果
4. `redis`
   - 作为最小异步任务队列和状态缓存
5. `worker`
   - 执行回测、参数优化和复盘分析

本周默认不单独拆：

- 对象存储服务
- Nginx
- 多 worker 集群

如果后续时间充足，再补这些基础设施。

## 推荐目录结构

```text
repo/
├── apps/
│   ├── web/
│   └── api/
├── infra/
│   └── docker-compose.yml
├── storage/
│   ├── uploads/
│   └── market-data/
├── docs/
└── .env.example
```

## 环境变量

```env
# app
APP_ENV=development

# postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=quant_ai
POSTGRES_USER=quant_user
POSTGRES_PASSWORD=quant_pass

# llm
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_key
LLM_MODEL_STRATEGY=gpt-4.1
LLM_MODEL_SUMMARY=gpt-4.1-mini
STRATEGY_PROMPT_VERSION=v1
REPLAY_PROMPT_VERSION=v1

# storage
STORAGE_ROOT=/app/storage
UPLOAD_DIR=/app/storage/uploads
MARKET_DATA_DIR=/app/storage/market-data

# async jobs
REDIS_URL=redis://redis:6379/0
BACKTEST_ENGINE_VERSION=engine_v1
JOB_POLL_INTERVAL_MS=1000

# governance
DATA_RETENTION_DAYS=30
ALLOWED_LLM_EXPORT_FIELDS=symbol,side,entry_time,exit_time,pnl,feature_snapshot
```

## 本地开发步骤

### 1. 准备基础依赖

- 安装 Docker 和 Docker Compose
- 安装 Node.js 20
- 安装 Python 3.11
- 安装 pnpm

### 2. 创建项目结构

- 初始化 `apps/web`
- 初始化 `apps/api`
- 创建 `storage/uploads`
- 创建 `storage/market-data`

### 3. 启动 PostgreSQL

使用 Docker Compose 启动数据库，确保本地和演示环境一致。

### 4. 启动后端

- 创建虚拟环境
- 安装依赖
- 配置 `.env`
- 启动 FastAPI 服务

### 4.5 启动 worker

- 连接 Redis
- 以后台 worker 模式启动
- 验证能消费回测 / 复盘任务

### 5. 启动前端

- 安装依赖
- 配置前端环境变量
- 启动 Next.js 开发服务器

### 6. 导入样例数据

- 放入一份历史行情样例
- 放入一份交割单样例
- 验证页面可用

## Docker Compose 设计

建议包含以下服务：

### web

- 构建前端
- 暴露端口 `3000`

### api

- 构建 FastAPI 服务
- 暴露端口 `8000`
- 挂载 `storage/`

### redis

- 使用 Redis 官方镜像
- 作为最小任务队列

### worker

- 复用 API 代码仓，但以 worker 模式启动
- 处理回测、优化、复盘三个长任务

### postgres

- 使用 PostgreSQL 官方镜像
- 暴露端口 `5432`
- 持久化数据库目录

## 为什么选这个方案

- 比本地手工装数据库稳定
- 比拆云服务更简单
- 比只做同步接口更接近真实平台
- 能保证开发和演示环境尽可能一致

## 样例数据准备

环境搭建完成后，至少准备两类样例：

### 行情样例

- 单市场
- 单周期
- 时间范围固定
- 用于回测演示

### 交割单样例

- 至少包含 30 到 100 条交易记录
- 字段包含：
  - 标的
  - 开仓时间
  - 平仓时间
  - 方向
  - 数量
  - 盈亏

## 本周环境范围边界

本周只要求做到：

- 开发环境可运行
- 演示环境可访问
- 数据和文件可用
- 长任务可以异步排队和轮询状态

本周不要求做到：

- 生产级高可用
- 自动扩缩容
- 真实行情服务接入
- 实盘安全隔离

## 数据治理与安全边界

- 样例交割单必须先脱敏，再进入演示环境
- 原始上传文件、原始行数据、标准化 fills、聚合 trade records 分层保存
- 对外部 LLM 只发送结构化特征和白名单字段，不发送原始文件
- 上传文件要有保留期限和清理状态
- 所有密钥只通过环境变量提供，不写入代码和镜像

## 环境搭建验收标准

- 前端可访问
- 后端接口可访问
- 数据库连接正常
- Redis 和 worker 可用
- 样例行情可读
- 样例交割单可上传
- LLM API 配置可用
- 能跑通最短演示链路
