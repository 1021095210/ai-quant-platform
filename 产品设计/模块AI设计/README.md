# 模块 AI 设计索引

> 用途：把“全平台哪些模块要接 AI、AI 具体负责什么、哪些必须由平台硬约束、怎样避免幻觉和编造”拆成模块级设计记录，作为后续开发基线。

## 使用方式

1. 先读主接力文档  
   [AI量化交易平台_新环境恢复与Agent接力说明.md](/workspace/ai-quant-platform/产品设计/AI量化交易平台_新环境恢复与Agent接力说明.md)
2. 再按当前模块阅读本目录对应文件  
3. 涉及数据真实性、资源和验收标准时，同时阅读  
   [AI量化交易平台_实战落地资源清单与验收标准.md](/workspace/ai-quant-platform/产品设计/实战落地参考/AI量化交易平台_实战落地资源清单与验收标准.md)

## 模块文件

- [首页模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/首页模块_AI设计.md)
- [认证与账户模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/认证与账户模块_AI设计.md)
- [用户工作台模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/用户工作台模块_AI设计.md)
- [管理员工作台模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/管理员工作台模块_AI设计.md)
- [策略工坊模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/策略工坊模块_AI设计.md)
- [策略工坊模块_详细查缺补漏.md](/workspace/ai-quant-platform/产品设计/模块AI设计/策略工坊模块_详细查缺补漏.md)
- [指标设置模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/指标设置模块_AI设计.md)
- [规则模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/规则模块_AI设计.md)
- [回测中心模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/回测中心模块_AI设计.md)
- [交易复盘模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/交易复盘模块_AI设计.md)
- [金融导师模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/金融导师模块_AI设计.md)
- [金融助手模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/金融助手模块_AI设计.md)
- [平台基础设施与部署模块_AI设计.md](/workspace/ai-quant-platform/产品设计/模块AI设计/平台基础设施与部署模块_AI设计.md)

## 共通原则

- AI 负责理解、整理、生成候选结果，不负责定义真值。
- 真值层必须来自平台结构化规格、平台数据中心、平台规则引擎和可审计日志。
- 所有高风险结论都必须支持：
  - 引用来源
  - 不确定项
  - 冲突提示
  - 人工确认或拒答
- 平台必须允许系统明确回答：
  - 当前不支持
  - 当前数据不足
  - 当前无法确认
