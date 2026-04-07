# 工作简报：ClickHouse 资源登记

- **Agent**: codex
- **日期**: 2026-04-07 09:00
- **涉及模块**: 实战落地参考文档、开发文档测试

## 做了什么（What）

- 实际探测了用户提供的 ClickHouse 资源：
  - 地址：`192.168.0.203:31054`
  - 已确认 HTTP 可连接
  - 版本：`24.8.1.2227`
- 已确认存在量化数据仓库分层：
  - `quant_ods`
  - `quant_dwd`
  - `quant_ads`
- 已确认存在 A股相关数据表，例如：
  - `quant_dwd.dwd_mkt_kline_daily`
  - `quant_dwd.dwd_mkt_kline_1min`
  - `quant_dwd.dwd_mkt_kline_1min_qfq`
  - `quant_ads.ads_idx_stock_daily`
  - `quant_ods.ods_cal_trade`
- 已确认大致数据范围：
  - 日线到 `2026-04-03`
  - 1 分钟到 `2026-01-30`
  - 交易日历到 `2026-12-31`
- 已把这份资源登记到：
  - [AI量化交易平台_实战落地资源清单与验收标准.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_实战落地资源清单与验收标准.md)
  - [AI量化交易平台_资源源选型建议_2026-04-07.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_资源源选型建议_2026-04-07.md)
  - [AI量化交易平台_资源部门单页说明.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_资源部门单页说明.md)
  - [AI量化交易平台_数据中心与增量同步设计.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_数据中心与增量同步设计.md)
- 更新 [test_process_reference_docs.py](/workspace/ai-quant-platform/tests/test_process_reference_docs.py)，确保 ClickHouse 资源登记与内部数据仓库原则不会丢失

## 为什么这样做（Why）

- 用户提供的不是普通接口，而是内部数据仓库资源；这对平台最重要的价值不是“再加一个数据源”，而是让平台优先读取内部数据中心，减少直接访问第三方接口。
- 因此这轮重点是确认它是否可连、是否真有 A股数据、是否适合作为平台内部主数据层候选，并把这个结论固定到文档中。

## 结果（Result）

- 现在文档里已经明确：如果内部 ClickHouse 数据仓库长期稳定可维护，平台优先读内部 ClickHouse，外部接口只做补数、校验和回填
- 测试通过：
  - `python -m unittest tests.test_process_reference_docs`
- 已知情况：
  - 目前只是连通性与只读探测，不代表已经完成正式接入代码
  - 1 分钟数据当前只到 `2026-01-30`，后续接入前仍需确认增量更新策略
  - 本地运行态数据库 `quant_platform.db` 仍未入库
