# AI量化交易平台平台公共契约冻结稿

> 状态：冻结稿  
> 说明：本稿用于在下一阶段正式编码前冻结平台级公共契约，统一资源层级、API 语义、任务状态机、配置快照、追溯字段和治理底线，避免各业务模块在实施时各自定义。

## 1. 冻结目的与范围

### 1.1 冻结目的

本冻结稿的目标是为 AI 量化交易平台建立统一的平台基线，使策略生成、指标与规则、回测、交易复盘、数据库与数据资产等模块在后续细化和开发时，遵循同一套资源模型与执行语义。

重点冻结以下平台公共能力：

- 一级资源与归属关系
- API 请求/响应公共语义
- 错误码体系
- 异步任务统一状态机
- 配置版本与 `config_revision` 规则
- Trace / 审计字段
- 安全与治理底线
- 演进与兼容性规则

### 1.2 适用范围

本稿适用于以下所有模块：

- 模块 1：用户工作台与项目组织
- 模块 2：策略编排
- 模块 3：指标与规则知识
- 模块 4：回测执行与结果
- 模块 5：交易复盘与建议回灌
- 模块 6：平台底座与治理
- 模块 7：数据库与数据资产

### 1.3 暂不冻结的内容

以下内容不在本稿冻结范围内：

- 单个业务模块内部的算法实现细节
- 页面 UI 风格与文案细节
- 第三方供应商选型
- 某个策略、指标或复盘模型的具体 Prompt

---

## 2. 一级资源与归属模型

### 2.1 资源层级原则

平台资源层级冻结为：

`tenant -> workspace -> environment -> resource`

说明：

- `tenant`：租户层，当前版本可默认单租户，但模型必须预留
- `workspace`：用户实际操作空间，用于归属项目、策略、任务和结果
- `environment`：运行环境，如 `dev / staging / prod`
- `resource`：业务资源对象

### 2.2 一级资源清单

后续平台一级资源至少包含：

- `workspace`
- `strategy`
- `strategy_version`
- `indicator`
- `rule_term`
- `dataset`
- `dataset_snapshot`
- `task`
- `backtest_run`
- `optimization_run`
- `replay_run`
- `artifact`
- `audit_event`

### 2.3 资源归属规则

- 所有业务资源必须归属于某个 `workspace`
- 所有执行类结果必须关联具体 `environment`
- 所有结果资源必须可追溯到触发它的上游资源
- 任何资源都不得脱离 `workspace` / `environment` 单独存在

### 2.4 ID 与版本规则

- 所有资源使用全局不透明 ID
- 面向用户展示的名字、标题、代码可变，但资源 ID 不可变
- 版本化资源必须显式分为“资源本体”和“资源版本”
- 被引用结果绑定的是版本 ID，而不是可变的资源标题

### 2.5 删除与归档原则

- 已被执行结果引用的资源，默认不允许硬删除
- 允许逻辑删除、归档、停用，但必须保留追溯关系
- 结果类资源和审计类资源默认不可硬删除

---

## 3. API 公共契约

### 3.1 基础协议

- API 统一走 HTTPS + JSON
- 时间统一使用 UTC ISO 8601
- 高精度数值统一使用字符串传输
- 统一使用 `/api/v1` 前缀

### 3.2 成功响应格式

```json
{
  "success": true,
  "request_id": "req_xxx",
  "data": {},
  "meta": {
    "pagination": null
  },
  "error": null
}
```

### 3.3 失败响应格式

```json
{
  "success": false,
  "request_id": "req_xxx",
  "data": null,
  "meta": null,
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "invalid request",
    "details": {}
  }
}
```

### 3.4 公共请求头

- `X-Request-Id`
- `Idempotency-Key`
- `Authorization`
- `Content-Type`

### 3.5 `request_id` 规则

- 每个请求都必须返回 `request_id`
- 如果客户端传入 `X-Request-Id`，平台应透传或规范化后回传
- `request_id` 用于检索日志、任务和审计记录
- `request_id` 不能替代幂等键

### 3.6 `Idempotency-Key` 规则

以下接口必须支持 `Idempotency-Key`：

- 创建资源接口
- 启动异步任务接口
- 命令型接口（如取消、回灌、提交确认）

规则冻结如下：

- 相同 `Idempotency-Key` + 相同请求体应返回同一结果
- 相同 `Idempotency-Key` + 不同请求体应返回冲突错误
- 普通任务幂等键默认保留 24 小时
- 高风险命令幂等键保留期可提升到 7 天

### 3.7 错误码体系

平台统一错误码如下：

- `INVALID_ARGUMENT`
- `UNAUTHORIZED`
- `FORBIDDEN`
- `NOT_FOUND`
- `RATE_LIMITED`
- `STATE_CONFLICT`
- `TASK_CONFLICT`
- `IDEMPOTENCY_CONFLICT`
- `REVISION_CONFLICT`
- `CONCURRENT_MODIFICATION`
- `UPSTREAM_TIMEOUT`
- `POLICY_VIOLATION`
- `APPROVAL_REQUIRED`
- `INTERNAL_ERROR`

### 3.8 HTTP 状态映射

- `200`：读取成功、同步命令成功
- `201`：创建成功
- `202`：异步任务已受理
- `400`：参数错误
- `401`：未认证
- `403`：无权限
- `404`：资源不存在
- `409`：状态冲突 / 幂等冲突 / 版本冲突
- `422`：语义合法但无法执行
- `429`：限流
- `500`：内部错误
- `502/503/504`：上游或依赖服务故障

---

## 4. 统一任务模型

### 4.1 统一抽象

平台内所有异步执行单元统一抽象为 `task`。包括但不限于：

- 回测运行
- 参数优化
- OCR 识别
- 交割单结构化
- 交易复盘分析
- 建议规则回灌
- 数据同步

### 4.2 最小任务字段

每个 `task` 至少包含：

- `id`
- `task_type`
- `state`
- `workspace_id`
- `environment`
- `resource_refs`
- `input`
- `output`
- `config_revision`
- `created_by`
- `request_id`
- `trace_id`
- `idempotency_key`
- `priority`
- `retry_count`
- `error_code`
- `error_message`
- `created_at`
- `started_at`
- `ended_at`

### 4.3 统一状态机

正式状态集合冻结为：

- `pending`
- `queued`
- `running`
- `succeeded`
- `failed`
- `canceling`
- `canceled`

可选扩展状态：

- `pausing`
- `paused`

### 4.4 允许状态迁移

- `pending -> queued`
- `queued -> running`
- `running -> succeeded`
- `running -> failed`
- `queued -> canceling -> canceled`
- `running -> canceling -> canceled`
- `running -> pausing -> paused -> queued`

禁止静默跳跃式状态变更。

### 4.5 任务事件

标准任务事件冻结为：

- `created`
- `queued`
- `started`
- `progressed`
- `succeeded`
- `failed`
- `cancel_requested`
- `canceled`

### 4.6 父子任务原则

允许存在父任务和子任务，但对外仍统一表现为 `task` 抽象，不允许每个模块自定义另一套“任务模型”。

---

## 5. 配置与版本快照

### 5.1 配置治理原则

所有会影响执行结果的配置都必须进入平台治理，包括但不限于：

- 回测执行参数
- 市场规则参数
- 数据快照引用
- AI 模型与提示模板版本
- OCR 模板版本
- 风险与校验开关

### 5.2 `config_revision`

`config_revision` 冻结为：

- 不可变执行配置快照
- 每次正式执行必须绑定一个 `config_revision`
- 任何配置修改都必须生成新版本，不得覆盖旧版本

### 5.3 生命周期

配置版本生命周期冻结为：

- `draft`
- `validated`
- `approved`
- `released`
- `deprecated`

### 5.4 结果绑定规则

以下结果必须绑定 `config_revision`：

- 回测结果
- 参数优化结果
- OCR / 结构化结果
- 复盘结果
- 建议规则回灌结果

---

## 6. 追溯与审计契约

### 6.1 最小追溯字段

所有关键结果资源至少记录以下追溯字段：

- `request_id`
- `trace_id`
- `span_id`
- `parent_span_id`
- `correlation_id`
- `causation_id`
- `actor_id`
- `actor_type`
- `workspace_id`
- `environment`
- `config_revision`
- `strategy_version_id`
- `dataset_snapshot_id`
- `source_system`
- `created_at`

### 6.2 平台追溯目标

平台必须保证：从任意一个结果对象出发，都可以追溯到：

- 谁触发了它
- 什么时候触发
- 用了哪个请求
- 绑定了哪些资源版本
- 经过了哪些任务
- 最终产生了哪些结果或副作用

### 6.3 审计不可变原则

- 审计记录默认追加写
- 不允许静默改写审计事实
- 删除、取消、失败、重试都必须形成审计事件

---

## 7. 安全与治理底线

### 7.1 统一鉴权

- 所有资源访问必须经过统一鉴权层
- 不允许业务模块自行绕过鉴权直连底层数据

### 7.2 敏感信息保护

- 密钥、凭证、隐私数据必须加密或脱敏
- 密钥和连接信息只能走环境变量或受控密钥服务

### 7.3 高风险操作控制

以下高风险操作必须具备额外保护：

- 生产交易相关命令
- 大规模数据修正
- 批量回灌规则
- 跨环境配置变更

保护手段至少包括审批、双确认或 MFA。

### 7.4 平台治理要求

- 全局限流
- 外部依赖超时
- 熔断与降级
- 全局 kill switch
- 时钟同步
- 审计日志可检索

---

## 8. 数据库演进与兼容性规则

### 8.1 兼容性原则

平台默认只允许向后兼容的增量变更：

- 新增字段
- 新增资源
- 新增可选错误码
- 新增可选状态

### 8.2 非兼容变更规则

以下变更视为非兼容变更：

- 删除字段
- 修改字段语义
- 修改状态机含义
- 修改错误码语义
- 修改响应 envelope 结构

非兼容变更只能通过新主版本或正式废弃流程进行。

### 8.3 废弃流程

- 明确标记 `deprecated`
- 给出迁移期
- 给出替代方案
- 完成监控与切流后再移除

### 8.4 迁移要求

任何迁移都必须保证：

- 资源 ID 不丢失
- `request_id` / `trace_id` / `config_revision` 保持可追溯
- 历史结果语义不被隐式改写

---

## 9. 必须冻结的决策清单

1. 资源层级固定为 `tenant -> workspace -> environment -> resource`。  
2. 资源 ID 为不透明全局 ID，不使用业务语义主键替代。  
3. 平台统一响应 envelope，不允许各模块返回不同风格 JSON。  
4. 所有创建和命令型接口必须支持 `Idempotency-Key`。  
5. 所有请求必须回传 `request_id`。  
6. 平台统一错误码体系，不允许模块自定义平行体系。  
7. 所有异步执行统一抽象为 `task`。  
8. 统一任务状态机至少包含 `pending`、`queued`、`running`、`succeeded`、`failed`、`canceling`、`canceled`。  
9. 所有正式执行结果必须绑定 `config_revision`。  
10. 所有关键结果必须可追溯到资源版本、请求和任务。  
11. 审计记录默认不可变。  
12. 已被结果引用的资源不得硬删除。  
13. 高风险操作必须有额外治理机制。  
14. 平台默认只允许向后兼容变更。  
15. 非兼容变更必须走正式版本升级或废弃流程。  

---

## 10. 推荐实施顺序

### 阶段一：冻结公共契约骨架

- 固化资源层级
- 固化响应 envelope
- 固化错误码体系
- 固化统一任务状态机

### 阶段二：补齐配置与追溯闭环

- 落地 `config_revision`
- 落地 `request_id` / `trace_id` / 关联字段
- 统一结果绑定逻辑

### 阶段三：补齐安全治理底线

- 接入统一鉴权
- 补齐审计日志
- 为高风险命令加审批与限流

### 阶段四：约束演进与迁移

- 建立废弃流程
- 建立兼容性检查
- 为关键结构变更增加灰度与双写策略

---

## 11. 冻结完成判定标准

满足以下条件，才视为平台公共契约冻结完成：

- 所有模块都引用同一套资源层级与任务模型
- 所有接口返回统一 envelope
- 所有正式执行都绑定 `config_revision`
- 关键结果都可追溯到请求、任务和版本资源
- 关键平台变更已具备兼容性与废弃规则

