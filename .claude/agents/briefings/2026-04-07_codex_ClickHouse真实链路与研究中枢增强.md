# 工作简报：ClickHouse真实链路与研究中枢增强

- **Agent**: codex
- **日期**: 2026-04-07 09:47
- **涉及模块**: 数据接入；回测中心；交易复盘；用户工作台；平台基础设施；接力文档

## 做了什么（What）

- 接入内部 ClickHouse 到平台真实数据链路。
  - 修改 [config.py](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/config.py)，新增 ClickHouse 连接配置。
  - 修改 [main.py](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/main.py)，在 `auto/clickhouse` 模式下优先启用内部 `ClickHouseMarketDataProvider`。
  - 修改 [market_data.py](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/market_data.py)，新增内部 DWD 日线提供器，支持 `raw/qfq/hfq`，并输出停牌、涨跌停、涨跌停价等执行约束字段。
- 补硬回测执行层。
  - 修改 [backtest_engine.py](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/backtest_engine.py)，把停牌、涨停、跌停、期末未平仓按保守规则进入执行结果，并新增 `execution_summary`。
  - 修改 [services.py](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/services.py)，回测结果与工作台摘要增加执行摘要、数据中心状态和研究优先项。
  - 修改 [backtests.js](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/static/backtests.js)，回测详情展示优先数据链路与执行约束回放。
- 推进工作台中枢化。
  - 修改 [workspace.html](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/static/workspace.html) 和 [workspace.js](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/static/workspace.js)，新增“当前研究优先项”和“平台数据中心状态”。
- 增强复盘自动化。
  - 修改 [services.py](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/services.py)，长文本智能识别补价记录会写入真实补价来源，便于回放和审计。
- 补充测试与文档。
  - 修改/新增 [test_market_data.py](/workspace/ai-quant-platform/tests/test_market_data.py)、[test_backtest_engine.py](/workspace/ai-quant-platform/tests/test_backtest_engine.py)、[test_quant_platform_api.py](/workspace/ai-quant-platform/tests/test_quant_platform_api.py)、[test_static_assets.py](/workspace/ai-quant-platform/tests/test_static_assets.py)。
  - 更新 [AI量化交易平台_新环境恢复与Agent接力说明.md](/workspace/ai-quant-platform/产品设计/AI量化交易平台_新环境恢复与Agent接力说明.md) 及相关模块文档，并同步到仓库外镜像。

## 为什么这样做（Why）

- 内部 ClickHouse 已经是当前最可信的 A 股主数据源，平台需要优先读取内部 `DWD/ADS`，避免真实回测仍主要依赖外部接口兜底。
- 回测可信度要落到执行层，不能只在前端解释规则；因此把停牌、涨跌停和期末未平仓处理写进引擎，并把结果显式展示给用户。
- 工作台需要从导航页升级成研究中枢，所以新增可执行的研究优先项和当前数据中心状态，而不是只列入口。
- 复盘自动补价必须保留来源，否则后续无法审计“价格从哪来”。
- ClickHouse 接入过程中，实际发现两处底层兼容问题：
  - 这台 ClickHouse 需要显式发送 `Authorization: Basic ...`，不能依赖 `HTTPBasicAuthHandler`。
  - ClickHouse 查询字符串字面量应使用单引号，原先的 `json.dumps()` 双引号写法会导致真实查询失败。
  这两点都已在实现中修正。

## 结果（Result）

- 测试结果：
  - `python -m unittest discover -s tests -p 'test_*.py'`：`146` 个测试通过。
  - `python -m unittest tests.test_market_data tests.test_backtest_engine tests.test_static_assets`：通过。
  - `python -m unittest tests.test_quant_platform_api.QuantPlatformApiTests.test_workspace_summary_returns_research_hub_data tests.test_quant_platform_api.QuantPlatformApiTests.test_manual_text_parse_endpoint_recognizes_symbols_and_rules tests.test_quant_platform_api.QuantPlatformApiTests.test_backtest_run_completes_and_returns_metrics`：通过。
  - `python tools/validate_product_design_docs.py`：通过。
- 真实链路验证：
  - 使用内部 ClickHouse 跑 `600519.SH` 的 A 股日线回测，结果 `data_source.provider` 和 `data_snapshot_summary.provider` 都已变为 `internal_clickhouse_dwd`。
  - 工作台 `data_hub_status` 能显示内部 DWD 已配置，最新交易日为 `2026-04-03`。
- 已知限制：
  - 当前内部数仓接入只落了 A 股日线真实链路，分钟级、多市场和 ADS 级特征消费还未完全接入。
  - 回测执行约束已补强，但尚未覆盖更细的成交撮合细节，如部分成交、集合竞价差异等。
- 后续建议：
  - 下一步优先把回测日线主链路进一步切到 `ADS/DWD` 联合读法，并补分钟级时间对齐审计。
  - 金融导师/金融助手后续应直接引用这条内部数据链路，而不是只用外部兜底数据。
