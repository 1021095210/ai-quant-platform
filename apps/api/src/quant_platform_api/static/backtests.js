import {
  activateNav,
  api,
  formatDateTime,
  getSelectedVersion,
  handle,
  pollTask,
  renderMetricCards,
  renderSparkline,
  setStatus,
} from "/assets/shared.js";

activateNav("/backtests");

const nodes = {
  projectSelect: document.querySelector("#project-version-select"),
  market: document.querySelector("#backtest-market"),
  assetType: document.querySelector("#backtest-asset-type"),
  from: document.querySelector("#backtest-from"),
  to: document.querySelector("#backtest-to"),
  capital: document.querySelector("#backtest-capital"),
  feeBps: document.querySelector("#backtest-fee-bps"),
  slippageBps: document.querySelector("#backtest-slippage-bps"),
  fillPriceRule: document.querySelector("#backtest-fill-price-rule"),
  intrabarPolicy: document.querySelector("#backtest-intrabar-policy"),
  calendar: document.querySelector("#backtest-calendar"),
  timezone: document.querySelector("#backtest-timezone"),
  adjustmentMode: document.querySelector("#backtest-adjustment-mode"),
  warmupBars: document.querySelector("#backtest-warmup-bars"),
  marketConstraint: document.querySelector("#backtest-market-constraint"),
  positionMode: document.querySelector("#backtest-position-mode"),
  positionValue: document.querySelector("#backtest-position-value"),
  maxPositionPct: document.querySelector("#backtest-max-position-pct"),
  minTradeUnit: document.querySelector("#backtest-min-trade-unit"),
  takeProfit: document.querySelector("#backtest-take-profit"),
  stopLoss: document.querySelector("#backtest-stop-loss"),
  maxDrawdown: document.querySelector("#backtest-max-drawdown"),
  maxHoldingBars: document.querySelector("#backtest-max-holding-bars"),
  selectedVersion: document.querySelector("#selected-version"),
  latestProvider: document.querySelector("#latest-provider"),
  history: document.querySelector("#backtest-history"),
  metrics: document.querySelector("#backtest-metrics"),
  sourcePills: document.querySelector("#backtest-source-pills"),
  configList: document.querySelector("#backtest-config-list"),
  snapshotList: document.querySelector("#backtest-snapshot-list"),
  assumptionList: document.querySelector("#backtest-assumption-list"),
  sparkline: document.querySelector("#equity-sparkline"),
  strategyPython: document.querySelector("#backtest-strategy-python"),
  tradeTableBody: document.querySelector("#trade-table-body"),
};

async function loadProjects() {
  const payload = await api("/api/v1/strategies/projects");
  const items = payload.data.items;
  nodes.projectSelect.innerHTML = items.length
    ? items
        .map(
          (item) =>
            `<option value="${item.version_id}" data-market="${item.strategy_dsl.market}" data-asset="${item.strategy_dsl.asset_type || "stock"}" data-timeframe="${item.strategy_dsl.timeframe || "1d"}" data-backtest-timeframe="${item.strategy_dsl.backtest_timeframe || "1d"}" data-analysis-mode="${item.strategy_dsl.analysis_mode || "single_timeframe"}" data-timeframes="${(item.strategy_dsl.timeframes || []).join(",")}">${item.title} · ${(item.strategy_dsl.timeframes || [item.strategy_dsl.timeframe || "1d"]).join("/")} · ${item.version_id}</option>`,
        )
        .join("")
    : '<option value="">请先去策略工坊保存策略</option>';

  const selected = getSelectedVersion().versionId;
  if (selected && items.some((item) => item.version_id === selected)) {
    nodes.projectSelect.value = selected;
  }
  applySelectedProjectDefaults();
}

function applySelectedProjectDefaults() {
  const option = nodes.projectSelect.selectedOptions[0];
  if (!option) {
    return;
  }
  nodes.selectedVersion.textContent = option.value || "未选择";
  nodes.market.value = option.dataset.market || nodes.market.value;
  nodes.assetType.value = option.dataset.asset || "stock";
  if (option.dataset.analysisMode === "multi_timeframe") {
    const executionTimeframe = option.dataset.backtestTimeframe || "1d";
    setStatus(
      `已加载混合周期策略，当前回测兼容层仍按 ${executionTimeframe} 执行，其他周期条件保留在策略规格中。`,
    );
  }
  const assetType = option.dataset.asset || "stock";
  nodes.minTradeUnit.value = assetType === "stock" || assetType === "etf" ? "100" : "1";
  const market = (option.dataset.market || "").toLowerCase();
  if (assetType === "stock" || assetType === "etf") {
    if (market.includes(".sh") || market.includes(".sz")) {
      nodes.calendar.value = "cn_a_share";
      nodes.timezone.value = "Asia/Shanghai";
      nodes.marketConstraint.value = "A股按 T+1 卖出，股票 / ETF 最小单位 100 股";
    } else {
      nodes.calendar.value = "us_equity";
      nodes.timezone.value = "America/New_York";
      nodes.marketConstraint.value = "美股默认按 T+0 语义处理，最小交易单位可按券商模型调整";
    }
  } else {
    nodes.calendar.value = assetType === "crypto" ? "crypto_24x7" : "london_gold";
    nodes.timezone.value = assetType === "crypto" ? "UTC" : "Europe/London";
    nodes.marketConstraint.value =
      assetType === "crypto"
        ? "加密货币默认按 7x24 连续交易处理"
        : "伦敦金按全球连续报价时段处理";
  }
}

async function runBacktest() {
  if (!nodes.projectSelect.value) {
    throw new Error("请先选择策略版本。");
  }
  setStatus("正在运行真实日线回测...");
  const created = await api("/api/v1/backtests/runs", {
    method: "POST",
    body: JSON.stringify({
      strategy_version_id: nodes.projectSelect.value,
      dataset: {
        market: nodes.market.value,
        timeframe:
          nodes.projectSelect.selectedOptions[0]?.dataset.backtestTimeframe || "1d",
        asset_type: nodes.assetType.value,
        from: `${nodes.from.value}T00:00:00Z`,
        to: `${nodes.to.value}T00:00:00Z`,
      },
      execution_contract: {
        initial_capital: Number(nodes.capital.value || 100000),
        fee_bps: Number(nodes.feeBps.value || 3),
        slippage_bps: Number(nodes.slippageBps.value || 2),
        fill_price_rule: nodes.fillPriceRule.value,
        intrabar_match_policy: nodes.intrabarPolicy.value,
        calendar: nodes.calendar.value,
        timezone: nodes.timezone.value,
        adjustment_mode: nodes.adjustmentMode.value,
        market_constraint_text: nodes.marketConstraint.value,
        warmup_bars: Number(nodes.warmupBars.value || 20),
        position_sizing: {
          mode: nodes.positionMode.value,
          value: Number(nodes.positionValue.value || 1),
          max_positions: 1,
          max_position_pct: Number(nodes.maxPositionPct.value || 1),
          min_trade_unit: Number(nodes.minTradeUnit.value || 100),
        },
        risk_controls: {
          take_profit_pct: Number(nodes.takeProfit.value || 0.08),
          stop_loss_pct: Number(nodes.stopLoss.value || -0.03),
          max_drawdown_pct: Number(nodes.maxDrawdown.value || -0.12),
          max_holding_bars: Number(nodes.maxHoldingBars.value || 40),
        },
      },
      data_snapshot: {
        dataset_snapshot_ref: `${nodes.market.value}_${nodes.projectSelect.selectedOptions[0]?.dataset.backtestTimeframe || "1d"}_${nodes.from.value}_${nodes.to.value}`,
      },
    }),
  });
  const result = await pollTask(created.data.status_url);
  renderBacktestDetail(result);
  await refreshHistory();
  setStatus("回测完成，结果已写入回测历史。");
}

async function refreshHistory() {
  const payload = await api("/api/v1/backtests/runs");
  const items = payload.data.items;
  if (!items.length) {
    nodes.history.textContent = "暂无回测记录。";
    return;
  }
  nodes.history.innerHTML = items
    .map(
      (item) => `
        <button class="list-item" data-backtest-id="${item.backtest_run_id}" style="text-align:left">
          <strong>${item.strategy_title || item.market}</strong>
          <div class="muted-note">${item.market} · ${formatDateTime(item.created_at)}</div>
          <div class="muted-note">收益 ${item.metrics.total_return_pct ?? 0}% · 交易 ${item.metrics.trade_count ?? 0} 次</div>
          <div class="muted-note">快照 ${item.data_snapshot_summary?.dataset_snapshot_ref || "未标记"} · 来源 ${item.data_source.provider || "未知"}</div>
        </button>
      `,
    )
    .join("");
  nodes.history.querySelectorAll("[data-backtest-id]").forEach((node) => {
    node.addEventListener(
      "click",
      handle(async () => {
        const payloadDetail = await api(`/api/v1/backtests/runs/${node.dataset.backtestId}`);
        renderBacktestDetail(payloadDetail.data);
      }),
    );
  });
}

function renderBacktestDetail(data) {
  renderMetricCards(nodes.metrics, data.metrics || {});
  renderSparkline(nodes.sparkline, data.equity_curve || []);
  nodes.latestProvider.textContent = data.data_source?.provider || "未知";
  renderConfigList(data.backtest_config || {});
  renderSnapshotList(data.data_snapshot_summary || {});
  renderAssumptionList(data.backtest_config || {}, data.data_snapshot_summary || {});
  nodes.sourcePills.innerHTML = [
    `数据源：${data.data_source?.provider || "未知"}`,
    `缓存命中：${data.data_source?.served_from_cache ? "是" : "否"}`,
    `K线数量：${data.data_source?.bar_count || 0}`,
    `快照：${data.dataset_snapshot_ref || "未标记"}`,
  ]
    .map((item) => `<span class="pill">${item}</span>`)
    .join("");
  nodes.strategyPython.textContent = data.strategy_python || "# 当前回测未包含 Python 策略代码";
  const trades = data.trades || [];
  nodes.tradeTableBody.innerHTML = trades.length
    ? trades
        .map(
          (item) => `
            <tr>
              <td>${item.entry_time}</td>
              <td>${item.exit_time}</td>
              <td>${item.side} / ${item.quantity ?? "-"}</td>
              <td class="${item.pnl >= 0 ? "positive" : "negative"}">${item.pnl}</td>
              <td>${item.exit_reason} / ${item.holding_bars ?? "-"} bars</td>
            </tr>
          `,
        )
        .join("")
    : '<tr><td colspan="5" class="empty-state">当前没有成交记录。</td></tr>';
}

function renderConfigList(config) {
  const execution = config || {};
  const position = execution.position_sizing || {};
  const risk = execution.risk_controls || {};
  const items = [
    ["成交方式", execution.fill_price_rule || "未知"],
    ["盘中撮合", execution.intrabar_match_policy || "未知"],
    ["结算规则", execution.settlement_policy || "未知"],
    ["复权模式", execution.adjustment_mode || "未知"],
    ["日历 / 时区", `${execution.calendar || "未知"} / ${execution.timezone || "未知"}`],
    ["费用 / 滑点", `${execution.fee_bps ?? 0}bps / ${execution.slippage_bps ?? 0}bps`],
    ["市场约束", execution.market_constraint_text || "未记录"],
    ["仓位模式", `${position.mode || "未知"} / ${position.value ?? "-"}`],
    ["单笔上限", `${position.max_position_pct ?? "-"} / 最小单位 ${position.min_trade_unit ?? "-"}`],
    ["风控", `止盈 ${risk.take_profit_pct ?? "-"} / 止损 ${risk.stop_loss_pct ?? "-"} / 回撤 ${risk.max_drawdown_pct ?? "-"}`],
    ["预热 / 持有上限", `${execution.warmup_bars ?? "-"} bars / ${risk.max_holding_bars ?? "-"} bars`],
  ];
  nodes.configList.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="list-item compact-item">
          <strong>${label}</strong>
          <div class="muted-note">${value}</div>
        </div>
      `,
    )
    .join("");
}

function renderSnapshotList(summary) {
  const items = [
    ["快照引用", summary.dataset_snapshot_ref || "未标记"],
    ["数据来源", summary.provider || "未知"],
    ["覆盖率 / 缺失率", `${summary.coverage_pct ?? "-"}% / ${summary.missing_rate_pct ?? "-"}%`],
    ["时区 / 日历", `${summary.timezone || "未知"} / ${summary.calendar || "未知"}`],
    ["Bar 数 / 预热", `${summary.bar_count ?? 0} / ${summary.warmup_bars ?? "-"}`],
    ["最近同步", summary.last_synced_at || "未知"],
  ];
  nodes.snapshotList.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="list-item compact-item">
          <strong>${label}</strong>
          <div class="muted-note">${value}</div>
        </div>
      `,
    )
    .join("");
}

function renderAssumptionList(config, summary) {
  const execution = config || {};
  const assumptions = [
    [
      "成交假设",
      execution.fill_price_rule === "same_bar_close"
        ? "当前按当前K线收盘价成交解释信号，不再等到下一根K线。"
        : "当前按下一根K线开盘成交解释信号，避免把信号形成后的价格提前成交。",
    ],
    [
      "盘中撮合边界",
      execution.intrabar_match_policy === "intrabar_touch_fill"
        ? "允许盘中触价即成交，这会提高成交率，但也会让结果更依赖盘中路径假设。"
        : "当前不做盘中撮合，只在离散 K 线节点成交，结果更保守但可能漏掉盘中触发机会。",
    ],
    [
      "结算与可卖规则",
      execution.same_day_exit_allowed
        ? `当前按 ${execution.settlement_policy || "t_plus_zero"} 语义处理，同日买入后的后续同日时段允许退出。`
        : `当前按 ${execution.settlement_policy || "t_plus_one"} 语义处理，同日买入后的后续同日时段不允许退出。`,
    ],
    [
      "价格序列口径",
      execution.adjustment_mode === "raw"
        ? "当前使用不复权价格序列，回测结果对分红送配更敏感。"
        : `当前使用 ${execution.adjustment_mode} 价格口径，需与策略研究口径保持一致。`,
    ],
    [
      "数据边界",
      `当前快照 ${summary.dataset_snapshot_ref || "未标记"} 来自 ${summary.provider || "未知来源"}，覆盖率 ${summary.coverage_pct ?? "-"}%，缺失率 ${summary.missing_rate_pct ?? "-"}%。`,
    ],
    [
      "市场约束提醒",
      execution.market_constraint_text || "请结合市场制度、最小交易单位和可卖规则理解本次结果。",
    ],
  ];
  nodes.assumptionList.innerHTML = assumptions
    .map(
      ([label, value]) => `
        <div class="list-item compact-item">
          <strong>${label}</strong>
          <div class="muted-note">${value}</div>
        </div>
      `,
    )
    .join("");
}

nodes.projectSelect.addEventListener("change", applySelectedProjectDefaults);
document.querySelector("#run-backtest-btn").addEventListener("click", handle(runBacktest));
document
  .querySelector("#refresh-backtests-btn")
  .addEventListener("click", handle(refreshHistory));

Promise.all([loadProjects(), refreshHistory()]).catch((error) => setStatus(error.message));
