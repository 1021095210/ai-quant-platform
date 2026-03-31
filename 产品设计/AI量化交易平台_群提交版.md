# 选题 + 设计文档 + 环境搭建

## 项目名称

AI 量化交易研究与复盘平台

## 一句话定义

我要做一个 `AI 量化交易研究与复盘平台`，它能帮助 `有交易经验但不会写量化代码、也缺少系统复盘能力的交易者` 解决 `策略难以快速验证、交割单复盘依赖主观经验、无法系统提升胜率` 的问题。

## 为什么做这个题

- 真实痛点强：很多交易者有交易经验，但很难把经验快速转成可验证规则。
- AI 参与度高：自然语言生成策略、复盘总结、建议规则生成都适合 AI 深度参与。
- 闭环完整：需求、设计、实现、测试、部署、演示都能覆盖。
- 一周可控：做“研究与复盘平台”，不做实盘自动交易和券商接入。

## 目标用户

- 有一定交易经验的个人交易者
- 想快速验证交易想法的研究型用户
- 有历史交割单，希望通过数据改进交易模式的用户

## 核心功能与优先级

| 功能 | 说明 | 优先级 |
| --- | --- | --- |
| 自然语言生成策略 | 用户输入自然语言，平台生成结构化量化策略 DSL | P0 |
| 内置指标与自定义指标 | 支持 MA、EMA、RSI、MACD 等内置指标，也支持受限表达式自定义指标 | P0 |
| 策略回测与结果展示 | 基于历史行情运行回测，展示收益、回撤、胜率、交易记录 | P0 |
| 交割单上传与解析 | 用户上传历史交割单，系统标准化交易记录 | P0 |
| AI 复盘分析 | 分析盈利/亏损交易共同特征，给出优化建议 | P0 |
| 参数优化 | 对策略参数做网格搜索，输出最优组合 | P1 |
| 建议回灌策略 | 将复盘建议转成新规则并重新回测 | P1 |
| 策略版本对比 | 比较不同策略版本表现 | P2 |

### P0 最小可演示闭环

1. 输入自然语言策略
2. 平台生成结构化策略
3. 选择内置指标或创建自定义指标
4. 运行回测并查看结果
5. 上传交割单
6. 平台输出复盘建议
7. 应用一条建议重新回测

## 技术选型与理由

### 前端

- `React + Next.js + TypeScript`
- 原因：
  - 适合做数据工作台
  - 图表、表格、复杂状态管理生态成熟
  - 便于实现策略实验室和复盘工作台

### 后端

- `Python + FastAPI`
- 原因：
  - 更适合指标计算、回测逻辑、数据分析和 LLM 编排
  - 对 pandas / polars / 技术分析库支持自然
  - API 结构清晰，适合前后端分离

### 数据存储

- `PostgreSQL + 文件存储`
- PostgreSQL 存：
  - 用户项目
  - 策略版本
  - 回测结果摘要
  - 参数优化结果
  - 交割单解析记录
  - 复盘结果
- 文件存储存：
  - 原始交割单
  - 样例行情文件
  - 大体量缓存结果

### AI 组件

- `LLM API + 结构化输出`
- 作用：
  - 自然语言转策略 DSL
  - 策略解释与歧义提示
  - 复盘分析结果的人类可读总结
- 约束：
  - AI 不直接生成可执行交易代码
  - AI 不负责回测计算
  - AI 输出必须经过结构化校验

### 部署方式

- `Docker Compose + 单机演示环境`
- 原因：
  - 一周内最稳妥
  - 能统一前端、后端、数据库环境
  - 适合本地或演示机部署

## 数据流转（重点）

### 1. 自然语言策略生成

用户输入自然语言策略描述  
→ 前端提交给后端  
→ 后端构造提示词和 DSL schema  
→ 调用 LLM API  
→ 返回结构化策略 DSL  
→ 后端校验指标、参数、运算符是否合法  
→ 保存策略版本到 PostgreSQL  
→ 前端展示规则树和解释摘要

### 2. 回测流程

用户点击“开始回测”  
→ 前端提交策略版本 ID、市场、周期、时间范围  
→ 后端读取策略 DSL  
→ 行情服务加载历史 OHLCV  
→ 指标引擎计算内置指标和自定义指标  
→ 回测引擎执行入场、出场和收益逻辑  
→ 生成收益指标、净值曲线、交易明细  
→ 保存回测结果  
→ 前端展示结果页

### 3. 参数优化流程

用户选择参数范围  
→ 前端提交搜索空间  
→ 后端生成优化任务  
→ 优化执行器批量运行回测  
→ 聚合结果  
→ 返回最优参数和热图数据

### 4. 交割单复盘流程

用户上传交割单 CSV/XLSX  
→ 后端接收并校验格式  
→ 自动识别列名并等待用户确认映射  
→ 标准化为统一交易记录  
→ 根据成交时间对齐历史行情  
→ 提取量价、均线、波动率、持仓时长等特征  
→ 比较盈利交易和亏损交易差异  
→ 结构化结果传给 LLM 做总结  
→ 返回“成功原因、失败原因、建议规则”

### 5. 建议回灌策略流程

用户选择一条复盘建议  
→ 后端将建议转成 DSL patch  
→ 生成新的策略版本  
→ 重新运行回测  
→ 对比新旧结果

## 业务流转（重点）

### 首次使用

1. 用户打开平台首页
2. 进入策略实验室
3. 输入自然语言策略
4. 平台生成结构化策略
5. 用户补充指标和参数
6. 用户运行回测
7. 用户查看结果

### 日常研究使用

1. 打开已有策略项目
2. 调整规则或参数
3. 重新回测
4. 查看结果变化
5. 保存为新策略版本

### 交易复盘使用

1. 打开交易复盘页
2. 上传交割单
3. 确认字段映射
4. 选择分析维度
5. 查看盈利 / 亏损交易差异
6. 查看优化建议
7. 应用建议并重新回测

## 系统模块划分

### 1. 前端工作台

- 职责：策略输入、图表展示、复盘可视化

### 2. API 层

- 职责：路由、参数校验、统一错误格式

### 3. 策略编排模块

- 职责：自然语言转 DSL、DSL 校验、策略解释、版本保存

### 4. 指标引擎模块

- 职责：内置指标计算、自定义指标表达式解析

### 5. 回测与优化模块

- 职责：回测执行、收益统计、参数搜索

### 6. 交割单解析与复盘模块

- 职责：交割单解析、交易特征提取、复盘建议生成

### 7. 行情数据模块

- 职责：读取历史行情，统一提供 OHLCV 数据

### 8. 存储模块

- 职责：PostgreSQL 元数据持久化 + 文件存储

### 模块关系

前端工作台  
→ API 层  
→ 策略编排 / 回测与优化 / 交割单解析与复盘  
→ 指标引擎 + 行情数据模块  
→ PostgreSQL / 文件存储

## 数据模型设计

### 核心实体

1. `users`
2. `strategy_projects`
3. `strategy_versions`
4. `indicators`
5. `backtest_runs`
6. `optimization_jobs`
7. `optimization_trials`
8. `trade_uploads`
9. `trade_records`
10. `replay_analyses`

### 关键表字段

#### users

- id
- name
- email
- created_at

#### strategy_projects

- id
- user_id
- title
- description
- created_at

#### strategy_versions

- id
- project_id
- natural_language_prompt
- strategy_dsl
- explanation
- source_type
- parent_version_id
- created_at

#### indicators

- id
- user_id
- name
- type: `builtin / custom`
- expression
- description
- meta

#### backtest_runs

- id
- strategy_version_id
- market
- timeframe
- date_from
- date_to
- execution_config
- metrics
- equity_curve
- trade_points

#### trade_uploads

- id
- user_id
- source_file_name
- storage_path
- parse_status
- detected_columns
- column_mapping

#### trade_records

- id
- upload_id
- symbol
- side
- entry_time
- exit_time
- quantity
- entry_price
- exit_price
- pnl
- fees

#### replay_analyses

- id
- upload_id
- focus_dimensions
- custom_prompt
- summary
- winning_patterns
- losing_patterns
- suggestion_rules

### 实体关系

- 一个 user 有多个 strategy_projects
- 一个 strategy_project 有多个 strategy_versions
- 一个 strategy_version 有多个 backtest_runs 和 optimization_jobs
- 一个 user 有多个 trade_uploads
- 一个 trade_uploads 有多条 trade_records
- 一个 trade_uploads 可生成多次 replay_analyses

### 存储分层

- PostgreSQL：元数据和分析结果
- 文件存储：原始交割单和行情文件
- 内存：临时指标序列和回测中间状态

## 页面 / 界面草图

### 页面 1：首页

- 新建策略研究
- 上传交割单复盘
- 最近策略
- 最近回测
- 最近复盘建议

### 页面 2：策略实验室

- 左侧：自然语言输入框
- 中间：策略规则树 / DSL
- 右侧：指标和参数配置
- 底部：保存版本 / 开始回测

### 页面 3：回测结果页

- 顶部：策略版本信息
- 中部：收益曲线、回撤曲线、指标卡片
- 下方：交易明细、参数优化结果

### 页面 4：交易复盘页

- 左侧：上传交割单 + 维度设置
- 中间：交易解析表和统计结果
- 右侧：AI 复盘总结 + 建议规则

## 环境搭建

### 开发环境

- 前端：Node.js 20 + pnpm + Next.js
- 后端：Python 3.11 + FastAPI
- 数据库：PostgreSQL 15
- 文件存储：本地 `storage/`
- 部署：Docker Compose

### 推荐目录结构

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
└── .env.example
```

### 环境变量

```env
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=quant_ai
POSTGRES_USER=quant_user
POSTGRES_PASSWORD=quant_pass
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_key
LLM_MODEL_STRATEGY=gpt-4.1
LLM_MODEL_SUMMARY=gpt-4.1-mini
STORAGE_ROOT=/app/storage
```

### 环境搭建步骤

1. 准备 Docker、Node.js 20、Python 3.11、pnpm
2. 初始化 `apps/web` 和 `apps/api`
3. 启动 PostgreSQL
4. 启动 FastAPI
5. 启动 Next.js
6. 准备样例行情和交割单
7. 验证最短演示链路

## AI 协作设计过程

### 第一轮

让 AI 帮我梳理：

- 核心功能
- 用户场景
- MVP 范围

### 第二轮

我继续追问：

- 有没有更简单的方式？
- 哪些功能最容易超范围？
- 为什么要做成一个平台而不是两个工具？

### 第三轮

让 AI 深挖：

- 数据流转
- 业务流转
- 系统模块划分
- 数据模型

### 第四轮

让 AI 反向挑战设计：

- 哪些地方有时间风险？
- 哪些地方有技术风险？
- 哪些地方可能出现 AI 幻觉和安全问题？

### 第五轮

让 AI 生成可视化材料：

- 架构图
- 流程图
- 页面布局
- 五日开发计划

## 关键风险与应对

### 时间风险

- 风险：功能多，容易做不完
- 应对：优先保证 P0，不做实盘、不做实时行情

### 技术风险

- 风险：自定义指标如果允许任意代码执行会有安全问题
- 应对：只允许白名单表达式

### 数据风险

- 风险：交割单格式不统一
- 应对：增加字段映射确认步骤

### AI 风险

- 风险：AI 生成错误策略或错误复盘结论
- 应对：结构化输出 + DSL 校验 + 基于结构化事实的复盘

## 五日开发计划

### 周一

- 选题确认
- 完成设计文档
- 明确 DSL、数据模型、页面结构

### 周二

- 搭前后端骨架
- 打通自然语言生成策略和指标管理

### 周三

- 完成回测链路和结果展示

### 周四

- 完成交割单上传、解析、复盘分析

### 周五

- 完成参数优化与建议回灌
- 整理文档与演示

## 本周明确不做

- 实盘自动交易
- 券商 / 交易所 API 接入
- 实时行情服务
- 多用户团队协作权限体系
- 生产级风控和高可用部署

## 选题自问清单

- [x] 这个项目是我真正想做的吗？
- [x] 一周后我能演示出一个最小可用版本吗？
- [x] 这个项目能让我走完 `需求 → 设计 → 实现 → 测试 → 部署 → 复盘` 吗？
- [x] 我能用一句话说清楚它解决什么问题吗？
- [x] 我有没有过于贪心、想在一周内做太多？
- [x] 密钥和敏感数据我知道怎么处理吗？

结论：这个选题范围可控、闭环完整、可演示，也符合安全边界要求。
