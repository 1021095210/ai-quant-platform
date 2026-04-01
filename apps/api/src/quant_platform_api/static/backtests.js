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
  selectedVersion: document.querySelector("#selected-version"),
  latestProvider: document.querySelector("#latest-provider"),
  history: document.querySelector("#backtest-history"),
  metrics: document.querySelector("#backtest-metrics"),
  sourcePills: document.querySelector("#backtest-source-pills"),
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
        initial_capital: 100000,
        fee_bps: 3,
        slippage_bps: 2,
        fill_price_rule: "next_bar_open",
        intrabar_match_policy: "no_intrabar_fill",
        calendar: "cn_a_share",
        timezone: "Asia/Shanghai",
        adjustment_mode: "qfq",
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
          <div class="muted-note">来源 ${item.data_source.provider || "未知"}</div>
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
  nodes.sourcePills.innerHTML = [
    `数据源：${data.data_source?.provider || "未知"}`,
    `缓存命中：${data.data_source?.served_from_cache ? "是" : "否"}`,
    `K线数量：${data.data_source?.bar_count || 0}`,
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
              <td>${item.side}</td>
              <td class="${item.pnl >= 0 ? "positive" : "negative"}">${item.pnl}</td>
              <td>${item.exit_reason}</td>
            </tr>
          `,
        )
        .join("")
    : '<tr><td colspan="5" class="empty-state">当前没有成交记录。</td></tr>';
}

nodes.projectSelect.addEventListener("change", applySelectedProjectDefaults);
document.querySelector("#run-backtest-btn").addEventListener("click", handle(runBacktest));
document
  .querySelector("#refresh-backtests-btn")
  .addEventListener("click", handle(refreshHistory));

Promise.all([loadProjects(), refreshHistory()]).catch((error) => setStatus(error.message));
