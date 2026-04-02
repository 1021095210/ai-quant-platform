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
  runPanel: document.querySelector("#run-backtest-panel"),
  historyPanel: document.querySelector("#backtest-history-panel"),
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
  compareStatus: document.querySelector("#backtest-compare-status"),
  compareHighlights: document.querySelector("#backtest-compare-highlights"),
  compareHead: document.querySelector("#backtest-compare-head"),
  compareBody: document.querySelector("#backtest-compare-body"),
  compareConfigList: document.querySelector("#backtest-compare-config-list"),
  compareSnapshotList: document.querySelector("#backtest-compare-snapshot-list"),
  metrics: document.querySelector("#backtest-metrics"),
  sourcePills: document.querySelector("#backtest-source-pills"),
  configList: document.querySelector("#backtest-config-list"),
  snapshotList: document.querySelector("#backtest-snapshot-list"),
  assumptionList: document.querySelector("#backtest-assumption-list"),
  sparkline: document.querySelector("#equity-sparkline"),
  strategyPython: document.querySelector("#backtest-strategy-python"),
  tradeTableBody: document.querySelector("#trade-table-body"),
};

const compareSelection = new Set();
let currentBacktestRunId = "";

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
    nodes.history.classList.add("empty-state");
    syncHistoryViewportHeight();
    renderEmptyComparison();
    return;
  }
  nodes.history.classList.remove("empty-state");
  nodes.history.innerHTML = items
    .map(
      (item) => `
        <div class="list-item history-card">
          <button class="history-primary" data-backtest-id="${item.backtest_run_id}" type="button">
            <div class="history-head">
              <div>
                <strong class="history-title">${item.strategy_title || item.market}</strong>
                <div class="muted-note">${formatHistoryMarketLabel(item)} · ${formatDateTime(item.created_at)}</div>
              </div>
              <div class="history-return ${Number(item.metrics.total_return_pct ?? 0) >= 0 ? "positive" : "negative"}">
                ${formatHistoryReturn(item.metrics.total_return_pct)}
              </div>
            </div>
            <div class="history-meta-grid">
              <div class="history-meta-card">
                <span class="mini-label">交易概况</span>
                <strong>${item.metrics.trade_count ?? 0} 笔</strong>
                <div class="muted-note">胜率 ${formatPercentText(item.metrics.win_rate_pct)}</div>
              </div>
              <div class="history-meta-card">
                <span class="mini-label">结算与卖出</span>
                <strong>${formatSettlementPolicyLabel(item.backtest_config?.settlement_policy)}</strong>
                <div class="muted-note">${formatSameDayExitLabel(item.backtest_config)}</div>
              </div>
              <div class="history-meta-card">
                <span class="mini-label">价格口径</span>
                <strong>${formatAdjustmentModeLabel(item.backtest_config?.adjustment_mode)}</strong>
                <div class="muted-note">${formatFillPriceRuleLabel(item.backtest_config?.fill_price_rule)}</div>
              </div>
              <div class="history-meta-card">
                <span class="mini-label">数据快照</span>
                <strong>${item.data_snapshot_summary?.dataset_snapshot_ref || "未标记"}</strong>
                <div class="muted-note">${item.data_source?.provider || "未知来源"}</div>
              </div>
            </div>
            <div class="history-footnotes">
              <span class="history-badge">${formatCalendarLabel(item.backtest_config?.calendar)}</span>
              <span class="history-badge">${formatTimezoneLabel(item.backtest_config?.timezone)}</span>
              <span class="history-badge">${item.config_revision || "未记录版本"}</span>
            </div>
          </button>
          <div class="history-actions">
            <button
              class="btn ${compareSelection.has(item.backtest_run_id) ? "secondary" : "ghost"} history-compare-toggle"
              data-compare-id="${item.backtest_run_id}"
              type="button"
            >
              ${compareSelection.has(item.backtest_run_id) ? "已加入对比" : "加入对比"}
            </button>
            <button
              class="btn ghost danger history-delete-btn"
              data-delete-id="${item.backtest_run_id}"
              type="button"
            >
              删除记录
            </button>
          </div>
        </div>
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
  nodes.history.querySelectorAll("[data-compare-id]").forEach((node) => {
    node.addEventListener("click", () => toggleCompareSelection(node.dataset.compareId));
  });
  nodes.history.querySelectorAll("[data-delete-id]").forEach((node) => {
    node.addEventListener(
      "click",
      handle(async () => {
        await deleteBacktestRun(node.dataset.deleteId);
      }),
    );
  });
  syncCompareStatus();
  syncHistoryViewportHeight();
}

function renderBacktestDetail(data) {
  currentBacktestRunId = data.backtest_run_id || "";
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

function renderEmptyBacktestDetail() {
  currentBacktestRunId = "";
  renderMetricCards(nodes.metrics, {});
  renderSparkline(nodes.sparkline, []);
  nodes.latestProvider.textContent = "未知";
  nodes.sourcePills.innerHTML = '<span class="pill">等待选择回测记录。</span>';
  nodes.strategyPython.textContent = "# 等待选择回测记录";
  nodes.tradeTableBody.innerHTML =
    '<tr><td colspan="5" class="empty-state">等待选择回测记录。</td></tr>';
  nodes.configList.textContent = "等待回测。";
  nodes.snapshotList.textContent = "等待回测。";
  nodes.assumptionList.textContent = "等待回测。";
}

function renderConfigList(config) {
  const execution = config || {};
  const position = execution.position_sizing || {};
  const risk = execution.risk_controls || {};
  const items = [
    ["成交方式", formatFillPriceRuleLabel(execution.fill_price_rule)],
    ["盘中撮合", formatIntrabarPolicyLabel(execution.intrabar_match_policy)],
    ["结算规则", formatSettlementPolicyLabel(execution.settlement_policy)],
    ["复权模式", formatAdjustmentModeLabel(execution.adjustment_mode)],
    ["日历 / 时区", `${formatCalendarLabel(execution.calendar)} / ${formatTimezoneLabel(execution.timezone)}`],
    ["费用 / 滑点", `${execution.fee_bps ?? 0}bps / ${execution.slippage_bps ?? 0}bps`],
    ["市场约束", execution.market_constraint_text || "未记录"],
    ["仓位模式", `${formatPositionModeLabel(position.mode)} / ${position.value ?? "-"}`],
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
        ? `${formatSettlementPolicyLabel(execution.settlement_policy)}。同日买入后的后续同日时段允许退出。`
        : `${formatSettlementPolicyLabel(execution.settlement_policy)}。同日买入后的后续同日时段不允许退出。`,
    ],
    [
      "价格序列口径",
      normalizeDisplayToken(execution.adjustment_mode) === "raw"
        ? "当前使用不复权价格序列，回测结果对分红送配更敏感。"
        : `当前使用${formatAdjustmentModeLabel(execution.adjustment_mode)}价格序列，需与策略研究口径保持一致。`,
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

function toggleCompareSelection(runId) {
  if (!runId) {
    return;
  }
  if (compareSelection.has(runId)) {
    compareSelection.delete(runId);
    refreshHistory().catch((error) => setStatus(error.message));
    return;
  }
  if (compareSelection.size >= 4) {
    setStatus("一次最多对比 4 条回测记录。");
    return;
  }
  compareSelection.add(runId);
  refreshHistory().catch((error) => setStatus(error.message));
}

function syncCompareStatus() {
  const count = compareSelection.size;
  if (count < 2) {
    nodes.compareStatus.textContent = `已选择 ${count} 条记录。请至少选择 2 条回测后再生成对比。`;
    return;
  }
  nodes.compareStatus.textContent = `已选择 ${count} 条记录，可以生成实验 / 回测对比。基线将按当前选择顺序的第一条记录处理。`;
}

async function runComparison() {
  if (compareSelection.size < 2) {
    throw new Error("请先选择至少 2 条回测记录。");
  }
  const search = new URLSearchParams();
  [...compareSelection].forEach((runId) => search.append("run_ids", runId));
  const payload = await api(`/api/v1/backtests/compare?${search.toString()}`);
  renderComparison(payload.data);
  setStatus("回测对比已生成，可以继续调整执行规则后重复比较。");
}

function clearComparisonSelection() {
  compareSelection.clear();
  renderEmptyComparison();
  refreshHistory().catch((error) => setStatus(error.message));
}

async function deleteBacktestRun(runId) {
  if (!runId) {
    return;
  }
  if (typeof window !== "undefined" && typeof window.confirm === "function") {
    const confirmed = window.confirm("删除后这条回测历史将不再出现在列表和对比中，确认继续吗？");
    if (!confirmed) {
      return;
    }
  }
  await api(`/api/v1/backtests/runs/${runId}`, { method: "DELETE" });
  compareSelection.delete(runId);
  if (currentBacktestRunId === runId) {
    renderEmptyBacktestDetail();
  }
  if (compareSelection.size < 2) {
    renderEmptyComparison();
  }
  await refreshHistory();
  setStatus("回测历史已删除。");
}

function renderComparison(data) {
  renderCompareHighlights(data.highlights || []);
  renderCompareTable(data.items || [], data.metric_rows || []);
  renderCompareDiffList(nodes.compareConfigList, data.config_diffs || []);
  renderCompareDiffList(nodes.compareSnapshotList, data.snapshot_diffs || []);
}

function renderCompareHighlights(highlights) {
  nodes.compareHighlights.innerHTML = highlights.length
    ? highlights.map((item) => `<span class="pill">${item}</span>`).join("")
    : '<span class="pill">当前对比中没有可提炼的高亮结论。</span>';
}

function renderCompareTable(items, rows) {
  if (!items.length || !rows.length) {
    renderEmptyComparison();
    return;
  }
  nodes.compareHead.innerHTML = `
    <tr>
      <th>指标</th>
      ${items
        .map(
          (item, index) =>
            `<th>${index === 0 ? "基线" : "对比项"}<div class="muted-note">${item.display_title}<br />${formatDateTime(item.created_at)}</div></th>`,
        )
        .join("")}
    </tr>
  `;
  nodes.compareBody.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td><strong>${row.label}</strong></td>
          ${row.values
            .map(
              (item, index) => `
                <td>
                  <div>${formatCompareValue(item.value)}</div>
                  ${
                    index === 0 || item.delta_vs_baseline === null
                      ? '<div class="muted-note">基线</div>'
                      : `<div class="muted-note ${item.delta_vs_baseline >= 0 ? "positive" : "negative"}">Δ ${formatCompareDelta(item.delta_vs_baseline)}</div>`
                  }
                </td>
              `,
            )
            .join("")}
        </tr>
      `,
    )
    .join("");
}

function renderCompareDiffList(target, rows) {
  if (!rows.length) {
    target.textContent = "当前没有差异。";
    return;
  }
  target.innerHTML = rows
    .map(
      (row) => `
        <div class="list-item compact-item">
          <strong>${row.label}</strong>
          ${row.values
            .map(
              (item, index) => `
                <div class="muted-note compare-note">
                  ${index === 0 ? "基线" : "对比项"} · ${item.display_title}：${formatCompareValue(item.value)}
                </div>
              `,
            )
            .join("")}
        </div>
      `,
    )
    .join("");
}

function renderEmptyComparison() {
  nodes.compareHighlights.innerHTML =
    '<span class="pill">等待选择至少 2 条回测记录后生成对比。</span>';
  nodes.compareHead.innerHTML = `
    <tr>
      <th>指标</th>
      <th>等待对比</th>
    </tr>
  `;
  nodes.compareBody.innerHTML = `
    <tr>
      <td colspan="2" class="empty-state">从回测历史中加入记录后再生成对比。</td>
    </tr>
  `;
  nodes.compareConfigList.textContent = "等待对比。";
  nodes.compareSnapshotList.textContent = "等待对比。";
}

function formatCompareValue(value) {
  if (value === null || value === undefined || value === "" || value === "undefined" || value === "null") {
    return "未记录";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? `${value}` : value.toFixed(2);
  }
  return `${value}`;
}

function formatCompareDelta(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatCompareValue(value)}`;
}

function normalizeDisplayToken(value) {
  if (value === null || value === undefined || value === "" || value === "undefined" || value === "null") {
    return "";
  }
  return `${value}`;
}

function formatSettlementPolicyLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (normalized === "t_plus_one") {
    return "T+1，当日买入后需次日才能卖出";
  }
  if (normalized === "t_plus_zero") {
    return "T+0，当日买入后同日可卖出";
  }
  return "未设置结算规则";
}

function formatSameDayExitLabel(config) {
  if (!config) {
    return "未记录当日可卖规则";
  }
  return config.same_day_exit_allowed ? "当日后续时段可卖出" : "当日后续时段不可卖出";
}

function formatAdjustmentModeLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (normalized === "qfq") {
    return "前复权";
  }
  if (normalized === "hfq") {
    return "后复权";
  }
  if (normalized === "raw") {
    return "不复权";
  }
  return "未设置价格口径";
}

function formatFillPriceRuleLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (normalized === "next_bar_open") {
    return "下一根K线开盘成交";
  }
  if (normalized === "same_bar_close") {
    return "当前K线收盘成交";
  }
  return "未设置成交方式";
}

function formatIntrabarPolicyLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (normalized === "intrabar_touch_fill") {
    return "盘中触价即成交";
  }
  if (normalized === "no_intrabar_fill") {
    return "不做盘中撮合";
  }
  return "未设置盘中撮合";
}

function formatCalendarLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (normalized === "cn_a_share") {
    return "A股交易日历";
  }
  if (normalized === "us_equity") {
    return "美股交易日历";
  }
  if (normalized === "crypto_24x7") {
    return "加密货币 7x24";
  }
  if (normalized === "london_gold") {
    return "伦敦金连续时段";
  }
  return "未设置交易日历";
}

function formatTimezoneLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (!normalized) {
    return "未设置时区";
  }
  const labels = {
    "Asia/Shanghai": "亚洲/上海",
    "America/New_York": "美东",
    UTC: "UTC",
    "Europe/London": "欧洲/伦敦",
  };
  return labels[normalized] || normalized;
}

function formatPositionModeLabel(value) {
  const normalized = normalizeDisplayToken(value);
  if (normalized === "fixed_fraction") {
    return "资金比例";
  }
  if (normalized === "fixed_quantity") {
    return "固定数量";
  }
  return "未设置仓位模式";
}

function formatHistoryMarketLabel(item) {
  const market = normalizeDisplayToken(item.market) || "未标记标的";
  const timeframe = normalizeDisplayToken(item.timeframe) || "未标记周期";
  return `${market} · ${timeframe}`;
}

function formatHistoryReturn(value) {
  const numeric = Number(value ?? 0);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function formatPercentText(value) {
  if (value === null || value === undefined || value === "") {
    return "未记录";
  }
  return `${Number(value).toFixed(2)}%`;
}

function syncHistoryViewportHeight() {
  if (
    !nodes.runPanel ||
    !nodes.historyPanel ||
    !nodes.history ||
    typeof window === "undefined" ||
    window.matchMedia("(max-width: 1100px)").matches
  ) {
    if (nodes.history) {
      nodes.history.style.maxHeight = "";
    }
    return;
  }
  const panelHeight = nodes.runPanel.getBoundingClientRect().height;
  const historyPanelStyles = window.getComputedStyle(nodes.historyPanel);
  const header = nodes.historyPanel.querySelector(".panel-header");
  const compareStatus = nodes.compareStatus;
  const occupiedHeight =
    (header?.getBoundingClientRect().height || 0) +
    parseFloat(window.getComputedStyle(header || nodes.historyPanel).marginBottom || "0") +
    (compareStatus?.getBoundingClientRect().height || 0) +
    parseFloat(window.getComputedStyle(compareStatus || nodes.historyPanel).marginBottom || "0");
  const paddingHeight =
    parseFloat(historyPanelStyles.paddingTop || "0") +
    parseFloat(historyPanelStyles.paddingBottom || "0");
  const maxHeight = Math.max(panelHeight - occupiedHeight - paddingHeight, 220);
  nodes.history.style.maxHeight = `${maxHeight}px`;
}

nodes.projectSelect.addEventListener("change", applySelectedProjectDefaults);
document.querySelector("#run-backtest-btn").addEventListener("click", handle(runBacktest));
document
  .querySelector("#refresh-backtests-btn")
  .addEventListener("click", handle(refreshHistory));
document
  .querySelector("#run-backtest-compare-btn")
  .addEventListener("click", handle(runComparison));
document
  .querySelector("#clear-backtest-compare-btn")
  .addEventListener("click", handle(async () => clearComparisonSelection()));

if (typeof window !== "undefined") {
  window.addEventListener("resize", syncHistoryViewportHeight);
  if (typeof ResizeObserver !== "undefined" && nodes.runPanel) {
    const resizeObserver = new ResizeObserver(() => syncHistoryViewportHeight());
    resizeObserver.observe(nodes.runPanel);
  }
}

Promise.all([loadProjects(), refreshHistory()]).catch((error) => setStatus(error.message));
