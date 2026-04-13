# AI量化交易平台埋点方案 v1.0

## 1. 埋点目标

埋点不是为了“收集更多数据”，而是为了验证：

1. 用户是否真的对平台有兴趣
2. 用户是否会持续回来使用
3. 用户更喜欢哪个模块
4. 平台是否真的帮助用户形成研究闭环

## 2. 当前主指标

- 用户 7 日留存

## 3. 当前辅助指标

- 完成一次研究闭环的用户数
- 交易复盘使用次数
- 金融导师使用人数
- 金融助手使用人数
- 用户主观反馈“是否真的有帮助”

## 4. 核心埋点事件

### A. 用户进入与登录

- `home_view`
- `login_submit`
- `register_submit`
- `workspace_view`

### B. 金融导师

- `mentor_view`
- `mentor_topic_click`
- `mentor_question_submit`
- `mentor_followup_submit`

### C. 策略工坊

- `strategy_view`
- `strategy_generate_submit`
- `strategy_save_submit`
- `strategy_go_backtest_click`

### D. 回测中心

- `backtest_view`
- `backtest_create_submit`
- `backtest_result_view`
- `backtest_compare_submit`

### E. 交易复盘

- `replay_view`
- `replay_csv_submit`
- `replay_screenshot_submit`
- `replay_manual_submit`
- `replay_ai_analysis_submit`

### F. 金融助手

- `assistant_view`
- `assistant_query_submit`

## 5. 埋点使用原则

- 埋点先围绕产品验证，不追求一次性埋很多
- 每个事件至少保留：
  - 用户 ID
  - 时间
  - 模块
  - 事件名
- 高风险内容不直接记录原始敏感文本

## 6. 当前最重要的分析问题

1. 哪个模块最能吸引用户第一次进入
2. 哪个模块最能带来 7 日留存
3. 用户是否会从导师走到策略工坊 / 回测中心
4. 用户是否会从复盘回到策略优化
