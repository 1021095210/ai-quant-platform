# AI 量化交易平台 API 与网页端

当前仓库里的网页端由 FastAPI 直接托管，不存在独立的 React/Vue 前端工程。页面位于 `apps/api/src/quant_platform_api/static/`，后端接口和页面一起由一个 FastAPI 进程提供。

## 当前页面结构

- 首页：平台入口
- 登录 / 注册：认证入口
- 用户工作台：登录后的研究中枢
- 管理后台：管理员查看用户、任务、平台运行态和角色管理
- 策略工坊：自然语言转策略 DSL / Python 样例
- 回测中心：创建回测并查看配置摘要、快照摘要和结果
- 交易复盘：上传交割单并生成复盘结论
- 指标设置：内置指标与自定义指标
- 规则模块：默认研究规则与术语库

## 技术栈

- 前端：HTML + Vanilla JavaScript + CSS
- 后端：Python 3.11 + FastAPI + Uvicorn
- ORM：SQLAlchemy
- 默认业务存储：SQLite
- 推荐共享环境存储：PostgreSQL
- 对象存储与缓存部署基线：MinIO、Redis

## 本地开发启动

```bash
cd /workspace/ai-quant-platform
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e apps/api
uvicorn quant_platform_api.main:create_app --factory --app-dir apps/api/src --host 0.0.0.0 --port 8000 --reload
```

默认打开：

```text
http://127.0.0.1:8000/
```

## Docker 启动

构建镜像：

```bash
cd /workspace/ai-quant-platform
docker build -f apps/api/Dockerfile -t ai-quant-platform-api .
```

直接运行单容器：

```bash
docker run --rm -p 8000:8000 \
  -e APP_ENV=container \
  -e DATABASE_URL=sqlite+pysqlite:////app/data/quant_platform.db \
  -e MARKET_DATA_DATABASE_PATH=/app/data/market_data.db \
  -v "$(pwd)/storage:/app/data" \
  ai-quant-platform-api
```

## Compose 部署入口

- 本地一体化依赖：`infra/docker-compose.yml`
- 外部托管依赖：`infra/docker-compose.external.yml`
- HTTPS 反向代理模板：`infra/Caddyfile.example`
- 环境模板：`infra/deploy.env.example`

## 环境差异处理

- 本地开发默认可用 SQLite，降低启动门槛
- 演示/共享环境建议把 `DATABASE_URL` 切到 PostgreSQL
- `MARKET_DATA_DATABASE_PATH` 单独放在持久卷，避免市场缓存和业务库混在一起
- Redis 和 MinIO 目前主要作为部署基线和下一阶段扩展预留，不强制阻塞当前主链路
- 正式生产环境建议：
  - `ENABLE_DEFAULT_ACCOUNTS=false`
  - 配置 `INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_CONTACT / INITIAL_ADMIN_PASSWORD`
  - 配置 `SESSION_COOKIE_SECURE=true`
  - 在 HTTPS 域名下运行

## 联调与验证

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
```

依赖校验：

```bash
.venv/bin/python tools/verify_infra_stack.py \
  --database-url "$DATABASE_URL" \
  --redis-url "$REDIS_URL" \
  --minio-endpoint "$MINIO_ENDPOINT" \
  --app-url "$APP_PUBLIC_URL"
```

测试：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```
