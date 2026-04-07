# 工作简报：ClickHouse 分层读取基线

- **Agent**: codex
- **日期**: 2026-04-07 09:09
- **涉及模块**: 实战落地参考文档、平台基础设施与部署模块、主接力文档、开发文档测试

## 做了什么（What）

- 更新 [AI量化交易平台_实战落地资源清单与验收标准.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_实战落地资源清单与验收标准.md)：
  - 在已登记的内部 ClickHouse A股数据仓库条目下补充“默认优先读取 `quant_ads / quant_dwd`，`quant_ods` 只做原始回查、补数、审计和问题排查”的硬规则。
- 更新 [AI量化交易平台_资源源选型建议_2026-04-07.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_资源源选型建议_2026-04-07.md)：
  - 明确如果内部仓库已经按 `ODS / DWD / ADS` 分层，平台默认读 `ADS / DWD`，不把 `ODS` 当作用户侧默认查询层。
- 更新 [AI量化交易平台_数据中心与增量同步设计.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_数据中心与增量同步设计.md)：
  - 在“标准化数据层”和“当前设计结论”里补充分层读取原则。
- 更新 [AI量化交易平台_资源部门单页说明.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_资源部门单页说明.md)：
  - 用非金融视角补一句话规则，方便资源部门理解为什么平台不是直接查 `ODS`。
- 更新 [AI量化交易平台_新环境恢复与Agent接力说明.md](/workspace/ai-quant-platform/产品设计/AI量化交易平台_新环境恢复与Agent接力说明.md) 和 [平台基础设施与部署模块.md](/workspace/ai-quant-platform/产品设计/接力模块/平台基础设施与部署模块.md)：
  - 让后续 agent 在只读接力文件时也能看到这条数据层基线。
- 更新 [test_process_reference_docs.py](/workspace/ai-quant-platform/tests/test_process_reference_docs.py)：
  - 增加 `ADS / DWD / ODS` 相关断言，防止后续文档回退时丢掉这条规则。
- 同步镜像到 `/workspace/ai量化平台设计/接力文档记录/`。

## 为什么这样做（Why）

- 用户补充的数据字典已经明确说明：`ADS / DWD` 是消费层和加工层，`ODS` 更偏原始层。这个信息如果不写成硬规则，后续 agent 很容易为了“字段更全”直接误用 `ODS`，反而把原始脏数据和未标准化字段暴露到回测、复盘、导师或助手。
- 这条规则不仅影响技术实现，也影响资源部门理解数据如何被平台消费，所以我同时更新了：
  - 技术设计文档
  - 资源部门单页说明
  - 主接力文档
  - 平台基础设施模块文档
- 选择把校验写进测试，而不是只写进文档，是为了让这条基线后续不会被无意删掉。

## 结果（Result）

- 平台关于内部 ClickHouse 的默认读取策略已经清晰固定：
  - 用户侧和业务侧默认优先读取 `ADS / DWD`
  - `ODS` 只做原始回查、补数、审计和重算输入
- 测试通过：
  - `python -m unittest tests.test_process_reference_docs`
  - `python tools/validate_product_design_docs.py`
- 已知情况：
  - 本地运行态数据库 `quant_platform.db` 未入库
  - 这轮没有改任何业务代码，只更新了文档和文档测试
- 建议后续 agent：
  - 如果开始真正接内部 ClickHouse，请先基于 `DWD / ADS` 建平台读模型，再按需回查 `ODS`
  - 如果后续资源部门再补充字段级字典，继续优先把“平台默认消费哪一层”写进实战落地参考文档，而不是只堆表名
