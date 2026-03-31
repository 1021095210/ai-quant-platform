# AI 量化交易平台 API 详细设计

## 设计原则

- API 只接受和返回结构化数据，不传执行代码
- 所有 AI 输出都落为平台可校验的 JSON 结构
- 复盘分析结果同时返回结构化特征和可读总结
- 统一错误格式，方便前端识别和展示
- 回测、参数优化、复盘分析统一按异步任务资源设计
- 关键结果必须附带数据快照、模型版本或规则版本，保证可追溯

## 通用约定

### Base URL

```text
/api/v1
```

### 通用响应格式

成功：

```json
{
  "success": true,
  "data": {}
}
```

失败：

```json
{
  "success": false,
  "error": {
    "code": "INVALID_STRATEGY_DSL",
    "message": "strategy contains unsupported indicator",
    "details": {}
  }
}
```

### 长任务与异步约定

- `backtests`、`optimization-jobs`、`replays/analyses` 都采用“创建任务 + 轮询状态 + 读取结果”的模式
- 创建任务成功时只返回 `queued` 或 `running` 状态，不同步等待完整结果
- 长任务资源统一字段：
  - `id`
  - `status`: `queued` / `running` / `completed` / `failed` / `cancelled`
  - `progress_pct`
  - `status_url`
  - `result_url`
  - `error`
- 平台保留取消任务和失败重试的能力

## 1. 生成策略

### `POST /api/v1/strategies/generate`

将自然语言策略描述转为结构化策略 DSL。

请求体：

```json
{
  "prompt": "当5日均线上穿20日均线，RSI小于70，且当前成交量大于过去10根均量的1.2倍时做多；止盈8%，止损3%。",
  "market": "BTCUSDT",
  "timeframe": "1h",
  "preferences": {
    "side": "long",
    "style": "trend_following"
  }
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "strategy_dsl": {
      "market": "BTCUSDT",
      "timeframe": "1h",
      "entry": { "all": [] },
      "exit": { "any": [] },
      "position": {}
    },
    "human_summary": "5日均线上穿20日均线并放量时做多，RSI用于避免追高。",
    "ambiguities": []
  }
}
```

错误码：

- `INVALID_PROMPT`
- `UNSUPPORTED_MARKET`
- `DSL_GENERATION_FAILED`

## 2. 校验策略

### `POST /api/v1/strategies/validate`

请求体：

```json
{
  "strategy_dsl": {
    "market": "BTCUSDT",
    "timeframe": "1h"
  }
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "valid": false,
    "errors": [
      {
        "path": "entry.all[1]",
        "code": "UNSUPPORTED_INDICATOR",
        "message": "indicator foo_bar is not allowed"
      }
    ]
  }
}
```

## 3. 创建自定义指标

### `POST /api/v1/indicators/custom`

请求体：

```json
{
  "name": "volume_ratio_10",
  "expression": "volume / SMA(volume, 10)",
  "description": "当前成交量与10周期均量之比"
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "indicator_id": "ind_123",
    "name": "volume_ratio_10",
    "status": "active",
    "parsed_ast": {
      "type": "binary_expression"
    }
  }
}
```

错误码：

- `INVALID_EXPRESSION`
- `UNSUPPORTED_FUNCTION`
- `DUPLICATE_INDICATOR_NAME`

## 4. 查询指标列表

### `GET /api/v1/indicators`

查询参数：

- `type`: `builtin` / `custom`
- `keyword`

响应体：

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "ind_builtin_rsi",
        "name": "RSI",
        "type": "builtin",
        "params_schema": {
          "period": "number"
        }
      }
    ]
  }
}
```

## 5. 保存策略版本

### `POST /api/v1/strategies/projects`

请求体：

```json
{
  "title": "放量均线突破策略",
  "natural_language_prompt": "当5日均线上穿20日均线时做多...",
  "strategy_dsl": {}
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "project_id": "proj_123",
    "version_id": "ver_001"
  }
}
```

## 6. 运行回测

### `POST /api/v1/backtests/runs`

请求体：

```json
{
  "strategy_version_id": "ver_001",
  "dataset": {
    "market": "BTCUSDT",
    "timeframe": "1h",
    "from": "2024-01-01T00:00:00Z",
    "to": "2024-12-31T23:59:59Z"
  },
  "execution_contract": {
    "initial_capital": 100000,
    "fee_bps": 10,
    "slippage_bps": 5,
    "fill_price_rule": "next_bar_open",
    "intrabar_match_policy": "no_intrabar_fill",
    "calendar": "crypto_24_7",
    "timezone": "UTC",
    "adjustment_mode": "raw"
  },
  "data_snapshot": {
    "dataset_snapshot_ref": "md_btcusdt_1h_2024_v1"
  }
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "backtest_run_id": "bt_001",
    "status": "queued",
    "progress_pct": 0,
    "status_url": "/api/v1/backtests/runs/bt_001",
    "result_url": "/api/v1/backtests/runs/bt_001"
  }
}
```

错误码：

- `INVALID_DATE_RANGE`
- `MISSING_MARKET_DATA`
- `STRATEGY_VALIDATION_FAILED`

### `GET /api/v1/backtests/runs/{backtest_run_id}`

响应体：

```json
{
  "success": true,
  "data": {
    "backtest_run_id": "bt_001",
    "status": "completed",
    "progress_pct": 100,
    "dataset_snapshot_ref": "md_btcusdt_1h_2024_v1",
    "engine_version": "engine_v1",
    "metrics": {
      "total_return_pct": 18.4,
      "max_drawdown_pct": -7.1,
      "win_rate_pct": 54.2,
      "profit_factor": 1.68,
      "trade_count": 47
    },
    "equity_curve": [],
    "trades": []
  }
}
```

### `POST /api/v1/backtests/runs/{backtest_run_id}/cancel`

响应体：

```json
{
  "success": true,
  "data": {
    "backtest_run_id": "bt_001",
    "status": "cancelled"
  }
}
```

## 7. 参数优化

### `POST /api/v1/optimization-jobs`

请求体：

```json
{
  "strategy_version_id": "ver_001",
  "search_space": {
    "entry.all[0].params.fast": [3, 5, 8],
    "entry.all[0].params.slow": [15, 20, 30]
  },
  "objective": "profit_factor",
  "dataset": {
    "market": "BTCUSDT",
    "timeframe": "1h",
    "from": "2024-01-01T00:00:00Z",
    "to": "2024-12-31T23:59:59Z"
  }
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "job_id": "opt_001",
    "status": "queued",
    "progress_pct": 0,
    "status_url": "/api/v1/optimization-jobs/opt_001",
    "result_url": "/api/v1/optimization-jobs/opt_001"
  }
}
```

### `GET /api/v1/optimization-jobs/{job_id}`

响应体：

```json
{
  "success": true,
  "data": {
    "job_id": "opt_001",
    "status": "completed",
    "progress_pct": 100,
    "best_params": {
      "entry.all[0].params.fast": 5,
      "entry.all[0].params.slow": 20
    },
    "best_metrics": {
      "profit_factor": 1.82,
      "total_return_pct": 21.3
    },
    "trials": []
  }
}
```

### `POST /api/v1/optimization-jobs/{job_id}/cancel`

响应体：

```json
{
  "success": true,
  "data": {
    "job_id": "opt_001",
    "status": "cancelled"
  }
}
```

## 8. 上传交割单

### `POST /api/v1/trades/uploads`

`multipart/form-data`

字段：

- `file`
- `market_type`
- `timezone`

响应体：

```json
{
  "success": true,
  "data": {
    "upload_id": "upload_001",
    "status": "uploaded",
    "detected_columns": [
      "symbol",
      "side",
      "entry_time",
      "exit_time",
      "qty",
      "pnl"
    ]
  }
}
```

## 9. 确认字段映射并解析交割单

### `POST /api/v1/trades/uploads/{upload_id}/parse`

请求体：

```json
{
  "column_mapping": {
    "symbol": "标的",
    "side": "方向",
    "entry_time": "开仓时间",
    "exit_time": "平仓时间",
    "qty": "数量",
    "pnl": "盈亏"
  }
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "upload_id": "upload_001",
    "raw_row_count": 164,
    "fill_count": 164,
    "record_count": 126,
    "status": "parsed"
  }
}
```

## 10. 查询交易记录

### `GET /api/v1/trades/uploads/{upload_id}/records`

响应体：

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "trade_id": "trade_001",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_time": "2024-05-03T10:00:00Z",
        "exit_time": "2024-05-03T14:00:00Z",
        "pnl": -230.5
      }
    ]
  }
}
```

## 11. 执行复盘分析

### `POST /api/v1/replays/analyses`

请求体：

```json
{
  "upload_id": "upload_001",
  "focus_dimensions": [
    "volume_structure",
    "moving_average_structure"
  ],
  "custom_prompt": "重点分析量价关系和20日均线位置"
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "analysis_id": "replay_001",
    "status": "queued",
    "progress_pct": 0,
    "status_url": "/api/v1/replays/analyses/replay_001",
    "result_url": "/api/v1/replays/analyses/replay_001"
  }
}
```

### `GET /api/v1/replays/analyses/{analysis_id}`

响应体：

```json
{
  "success": true,
  "data": {
    "analysis_id": "replay_001",
    "status": "completed",
    "progress_pct": 100,
    "feature_snapshot_ref": "feature_snap_upload_001_v1",
    "analysis_rule_version": "replay_rule_v1",
    "summary": "亏损交易更常出现在价格位于20周期均线下方且量能不足时。",
    "winning_patterns": [],
    "losing_patterns": [],
    "suggestion_rules": [
      {
        "title": "避免弱势缩量入场",
        "dsl_patch": {
          "entry_filter": {
            "indicator": "volume_ratio",
            "operator": ">",
            "value": 1.0
          }
        }
      }
    ]
  }
}
```

### `POST /api/v1/replays/analyses/{analysis_id}/cancel`

响应体：

```json
{
  "success": true,
  "data": {
    "analysis_id": "replay_001",
    "status": "cancelled"
  }
}
```

## 12. 应用复盘建议为新策略版本

### `POST /api/v1/replays/analyses/{analysis_id}/promote-rule`

请求体：

```json
{
  "strategy_version_id": "ver_001",
  "rule_index": 0
}
```

响应体：

```json
{
  "success": true,
  "data": {
    "new_version_id": "ver_002",
    "applied_patch": {}
  }
}
```

## 13. 查询项目详情

### `GET /api/v1/strategies/projects/{project_id}`

响应体：

```json
{
  "success": true,
  "data": {
    "project_id": "proj_123",
    "title": "放量均线突破策略",
    "versions": [
      {
        "version_id": "ver_001",
        "created_at": "2026-03-30T06:00:00Z"
      }
    ]
  }
}
```

## 关键前后端联调顺序

建议按以下顺序联调：

1. `/strategies/generate`
2. `/strategies/validate`
3. `/indicators/custom`
4. `/backtests/runs`
5. `/backtests/runs/{id}`
6. `/optimization-jobs`
7. `/optimization-jobs/{id}`
8. `/trades/uploads`
9. `/trades/uploads/{id}/parse`
10. `/trades/uploads/{id}/records`
11. `/replays/analyses`
12. `/replays/analyses/{id}`
13. `/replays/analyses/{id}/promote-rule`

这样可以先打通 P0 主链路，再补异步任务轮询、优化与版本管理。
