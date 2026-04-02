# 工作简报：回测详情顺序微调与 Tushare 试连

- **Agent**: codex
- **日期**: 2026-04-02 08:48
- **涉及模块**: `apps/api/src/quant_platform_api/static/backtests.html`, `tests/test_quant_platform_api.py`, `产品设计/AI量化交易平台_新环境恢复与Agent接力说明.md`, 仓库外接力镜像

## 做了什么（What）

- 调整 [backtests.html](/workspace/ai-quant-platform/apps/api/src/quant_platform_api/static/backtests.html) 中“当前回测详情”的阅读顺序：
  - 把“成交明细”从底部双栏区域移动到“回测曲线”正下方。
  - “策略 Python”改成独立区块，放到配置与快照摘要之后。
- 更新 [test_quant_platform_api.py](/workspace/ai-quant-platform/tests/test_quant_platform_api.py)：
  - 继续断言回测页包含“成交明细”。
  - 新增顺序断言，确保页面上 `回测曲线 -> 成交明细 -> 回测配置摘要` 的顺序不被后续改坏。
- 更新仓库内外两份接力文档，记录这次 UI 微调和当前外链验证方式。
- 额外验证了用户提供的 Tushare token：
  - 调用 `trade_cal` 接口返回 `40203`，说明当前 token 对该接口没有访问权限，暂未接入数据链路。

## 为什么这样做（Why）

- 当前回测详情里，成交明细比配置摘要和数据快照更容易被新手理解；把它放到曲线后面，能让用户先看净值变化，再立即看到对应交易。
- 这类调整很容易在后续页面重构中被“顺手挪回去”，所以我直接把顺序写进测试，而不是只依赖人工记忆。
- Tushare token 这次只做最小试连，不继续扩接入，是因为当前返回的是权限错误，不是网络错误；继续接入不会带来稳定结果。

## 结果（Result）

- 测试结果：
  - `python3 -m unittest tests.test_quant_platform_api.QuantPlatformApiTests.test_backtests_page_shows_config_and_snapshot_sections` 通过
  - `python3 -m unittest tests.test_static_assets` 通过，`9` 个测试 `OK`
- 运行验证：
  - 本地 `http://127.0.0.1:8023/healthz` 返回 `200`
  - 新临时外链已验证：
    - `/healthz` 返回 `200`
    - 登录后 `/backtests` 返回 `200`
- 已知限制：
  - 当前外链仍是临时 Pinggy 链接，不是正式长期部署
  - Tushare 当前 token 不能访问已测试接口，后续如要继续接入，需要更高权限或更合适的接口清单
- 建议后续 Agent 关注：
  - 如果继续优化回测结果阅读流，可以下一步给成交明细增加“买卖点映射到曲线”的联动高亮
