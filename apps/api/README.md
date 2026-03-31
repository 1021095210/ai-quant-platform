# AI 量化交易平台 Web 应用

当前应用已经按中国股票 / ETF 研究场景重构为多页面网页端：

- `总览`：最近策略项目和最近回测历史
- `策略工坊`：自然语言生成 Python 策略代码和结构化规则规格
- `回测中心`：按股票 / ETF 日线运行回测，并查看每一次回测历史和详情
- `交易复盘`：上传交割单并运行 AI 复盘

后端除了业务库之外，还新增了一套独立的行情缓存库：

- 业务库：策略项目、任务、交割单解析、复盘结果
- 行情库：股票 / ETF 历史日线缓存，避免每次回测都重新请求外部数据

## 本地启动

```bash
export DATABASE_URL=sqlite+pysqlite:///./quant_platform.db
export MARKET_DATA_DATABASE_PATH=./market_data.db
export MARKET_DATA_PROVIDER=auto
export TUSHARE_TOKEN=your_token
/workspace/.venv/bin/uvicorn quant_platform_api.main:create_app --factory --app-dir /workspace/apps/api/src --host 0.0.0.0 --port 8000 --reload
```

启动后直接打开：

```text
http://127.0.0.1:8000/
```

如果你在远程容器或云开发环境里，需要把它临时公开给外部试用，可以在保持服务运行的同时另开一个终端执行：

```bash
npx localtunnel --port 8000
```

命令会返回一个 `https://*.loca.lt` 的临时公网地址，外部用户可直接访问。这个地址是临时的，服务进程或隧道进程结束后会失效。

## 试用路径

建议按这个顺序试用一遍：

1. 进入 `策略工坊`
2. 生成 Python 策略并保存项目
3. 进入 `回测中心`
4. 运行回测并查看历史列表
5. 点击某一条历史记录查看详情
6. 进入 `交易复盘`
7. 上传并解析交割单，再运行 AI 复盘

页面默认已经带了策略描述和样例交割单，不需要你先准备文件。

## 当前已实现

### 网页端

- `GET /`
- `GET /strategy`
- `GET /backtests`
- `GET /replay`
- `GET /assets/theme.css`
- `GET /assets/*.js`

### 策略与项目

- `POST /api/v1/strategies/generate`
- `POST /api/v1/strategies/projects`
- `GET /api/v1/strategies/projects`
- `GET /api/v1/strategies/projects/{version_id}`

### 回测与优化

- `POST /api/v1/backtests/runs`
- `GET /api/v1/backtests/runs`
- `GET /api/v1/backtests/runs/{id}`
- `POST /api/v1/backtests/runs/{id}/cancel`
- `POST /api/v1/optimization-jobs`
- `GET /api/v1/optimization-jobs/{id}`
- `POST /api/v1/optimization-jobs/{id}/cancel`

### 交割单与复盘

- `POST /api/v1/trades/uploads`
- `POST /api/v1/trades/uploads/{upload_id}/parse`
- `GET /api/v1/trades/uploads/{upload_id}/records`
- `POST /api/v1/replays/analyses`
- `GET /api/v1/replays/analyses/{id}`
- `POST /api/v1/replays/analyses/{id}/cancel`

### 健康检查

- `GET /healthz`

## 当前仍是 Demo 版的部分

- 自然语言策略生成仍是规则模板生成，不是真实 LLM 调用
- 回测已改成真实股票 / ETF 日线数据驱动，但策略语义和回测模型仍是 MVP 级别
- 复盘分析已经读取上传的交割单统计，但还没接入更完整的特征工程
- 任务执行仍在应用进程内线程池完成，还没有拆成独立 Worker + Redis 队列
- 当前数据源优先尝试 Tushare；如果 token 无权限，会自动回退到腾讯历史行情
- 股票 / ETF 的历史日线会写入独立的 `market_data.db`，同一标的和时间范围的二次回测会直接命中缓存

## 数据持久化

当前应用默认通过 `DATABASE_URL` 使用 SQLAlchemy 持久化：

- 本地开发可用 SQLite
- Docker / 演示环境可用 PostgreSQL

默认建议：

```bash
export DATABASE_URL=sqlite+pysqlite:///./quant_platform.db
export MARKET_DATA_DATABASE_PATH=./market_data.db
```
