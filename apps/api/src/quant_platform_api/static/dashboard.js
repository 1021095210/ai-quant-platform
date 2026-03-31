import {
  activateNav,
  api,
  formatDateTime,
  getSelectedVersion,
  setStatus,
} from "/assets/shared.js";

activateNav("/");

async function loadDashboard() {
  const { versionId } = getSelectedVersion();
  document.querySelector("#current-version").textContent = versionId || "未选择";

  const [projectsPayload, backtestsPayload] = await Promise.all([
    api("/api/v1/strategies/projects"),
    api("/api/v1/backtests/runs"),
  ]);

  renderProjects(projectsPayload.data.items.slice(0, 4));
  renderBacktests(backtestsPayload.data.items.slice(0, 4));

  if (backtestsPayload.data.items.length) {
    document.querySelector("#latest-backtest-status").textContent =
      backtestsPayload.data.items[0].status;
  }
  setStatus("总览已刷新。");
}

function renderProjects(items) {
  const node = document.querySelector("#recent-projects");
  if (!items.length) {
    node.textContent = "暂无策略项目。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          <div class="muted-note">${item.version_id}</div>
          <div class="muted-note">${item.strategy_dsl.market} / ${item.strategy_dsl.timeframe}</div>
        </div>
      `,
    )
    .join("");
}

function renderBacktests(items) {
  const node = document.querySelector("#recent-backtests");
  if (!items.length) {
    node.textContent = "暂无回测记录。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.strategy_title || item.market}</strong>
          <div class="muted-note">${item.market} · ${formatDateTime(item.created_at)}</div>
          <div class="muted-note">收益 ${item.metrics.total_return_pct ?? 0}% / 交易 ${item.metrics.trade_count ?? 0} 次</div>
          <div class="muted-note">数据源：${item.data_source.provider || "未知"}</div>
        </div>
      `,
    )
    .join("");
}

loadDashboard().catch((error) => setStatus(error.message));
