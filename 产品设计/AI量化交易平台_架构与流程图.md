# AI 量化交易平台架构与流程图

## 1. 总体系统架构

```mermaid
flowchart LR
    U[用户] --> FE[前端工作台]
    FE --> API[FastAPI API层]
    API --> ORCH[策略编排服务]
    API --> BT[回测与优化服务]
    API --> RP[交割单解析与复盘服务]
    API --> JOB[任务编排与审计]
    API --> IND[指标引擎]
    JOB --> Q[(Redis 队列)]
    Q --> WK[后台 Worker]
    WK --> BT
    WK --> RP
    ORCH --> LLM[LLM API]
    BT --> MD[行情数据服务]
    RP --> MD
    RP --> LLM
    IND --> MD
    API --> DB[(PostgreSQL)]
    JOB --> DB
    RP --> FS[(文件存储)]
    MD --> FS
```

## 2. 自然语言生成策略流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant FE as 前端
    participant API as 后端API
    participant DB as PostgreSQL
    participant LLM as LLM API
    participant AUD as 审计字段

    User->>FE: 输入自然语言策略
    FE->>API: POST /strategies/generate
    API->>LLM: 提交提示词 + DSL schema
    LLM-->>API: 返回结构化策略 DSL
    API->>API: 校验指标/参数/运算符
    API->>AUD: 记录 model/prompt/schema 版本
    API->>DB: 保存策略版本
    API-->>FE: 返回 DSL + 解释摘要
    FE-->>User: 展示策略规则树
```

## 3. 回测流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant FE as 前端
    participant API as 后端API
    participant JOB as 任务编排
    participant Q as Redis队列
    participant WK as Worker
    participant MD as 行情服务
    participant IND as 指标引擎
    participant BT as 回测引擎
    participant DB as PostgreSQL

    User->>FE: 点击开始回测
    FE->>API: POST /backtests/runs
    API->>JOB: 创建回测任务
    JOB->>DB: 保存 queued 状态 + 数据快照 + 执行契约
    JOB->>Q: 投递任务
    Q->>WK: 分发回测任务
    WK->>MD: 读取指定版本历史OHLCV
    WK->>IND: 计算内置/自定义指标
    WK->>BT: 执行入场出场逻辑
    BT-->>WK: 返回收益指标与交易明细
    WK->>DB: 保存回测结果与执行状态
    FE->>API: GET /backtests/runs/{id}
    FE-->>User: 展示收益曲线/回撤/胜率
```

## 4. 交割单复盘流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant FE as 前端
    participant API as 后端API
    participant JOB as 任务编排
    participant Q as Redis队列
    participant WK as Worker
    participant FS as 文件存储
    participant MD as 行情服务
    participant IND as 指标引擎
    participant ANA as 分析器
    participant LLM as LLM API
    participant DB as PostgreSQL

    User->>FE: 上传交割单
    FE->>API: POST /trades/uploads
    API->>FS: 保存原始文件
    API-->>FE: 返回识别列
    User->>FE: 确认字段映射
    FE->>API: POST /trades/uploads/{id}/parse
    API->>DB: 保存原始行、fills 和聚合交易记录
    FE->>API: POST /replays/analyses
    API->>JOB: 创建复盘分析任务
    JOB->>Q: 投递任务
    Q->>WK: 分发复盘任务
    WK->>MD: 对齐历史行情
    WK->>IND: 提取入场/持仓/出场特征
    WK->>ANA: 计算盈利/亏损差异
    ANA-->>WK: 结构化分析结果
    WK->>LLM: 请求复盘总结
    LLM-->>WK: 返回可读分析和建议
    WK->>DB: 保存复盘结果与审计字段
    FE->>API: GET /replays/analyses/{id}
    API-->>FE: 返回复盘页面数据
```

## 5. 复盘建议回灌策略流程

```mermaid
flowchart TD
    A[用户选择一条复盘建议] --> B[前端提交建议规则]
    B --> C[后端生成 DSL patch]
    C --> D[创建新的策略版本]
    D --> E[重新运行回测]
    E --> F[展示新旧版本结果对比]
```

## 6. 业务流程图

```mermaid
flowchart TD
    A[打开平台] --> B{选择路径}
    B --> C[策略研究]
    B --> D[交易复盘]
    C --> E[输入自然语言策略]
    E --> F[生成结构化策略]
    F --> G[补充指标和参数]
    G --> H[执行回测]
    H --> I[查看结果]
    D --> J[上传交割单]
    J --> K[确认字段映射]
    K --> L[运行复盘分析]
    L --> M[查看成功/失败模式]
    M --> N[应用建议转规则]
    N --> H
```

## 7. 状态转换图

### 长任务状态

```mermaid
stateDiagram-v2
    [*] --> Queued
    Queued --> Running
    Running --> Completed
    Running --> Failed
    Queued --> Cancelled
    Running --> Cancelled
```

### 策略版本状态

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Validated
    Validated --> Backtested
    Backtested --> Optimized
    Backtested --> Archived
    Optimized --> Archived
```

### 交割单上传状态

```mermaid
stateDiagram-v2
    [*] --> Uploaded
    Uploaded --> MappingConfirmed
    MappingConfirmed --> Parsed
    Parsed --> Analyzed
    Uploaded --> Failed
    MappingConfirmed --> Failed
```

## 8. 如何在汇报时讲这些图

- 先讲总体系统架构，说明前端、后端、AI、回测、复盘的关系
- 再讲两条主流程：策略研究流程和交割单复盘流程
- 最后讲建议回灌策略，强调它形成了闭环
