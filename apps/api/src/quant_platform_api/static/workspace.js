import {
  activateNav,
  api,
  fetchCurrentUser,
  formatDateTime,
  logout,
  setStatus,
} from "/assets/shared.js";

activateNav("/workspace");

function renderProjects(items) {
  const node = document.querySelector("#recent-projects");
  document.querySelector("#project-count").textContent = `${items.length}`;
  if (!items.length) {
    node.textContent = "暂无策略项目。";
    return;
  }
  node.innerHTML = items
    .slice(0, 4)
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
  document.querySelector("#backtest-count").textContent = `${items.length}`;
  if (!items.length) {
    node.textContent = "暂无回测记录。";
    return;
  }
  node.innerHTML = items
    .slice(0, 4)
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.strategy_title || item.market}</strong>
          <div class="muted-note">${item.market} · ${formatDateTime(item.created_at)}</div>
          <div class="muted-note">收益 ${item.metrics.total_return_pct ?? 0}% / 交易 ${item.metrics.trade_count ?? 0} 次</div>
          <div class="muted-note">快照 ${item.dataset_snapshot_ref || "未标记"}</div>
        </div>
      `,
    )
    .join("");
}

async function loadWorkspace() {
  const user = await fetchCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/workspace";
    return;
  }

  document.querySelector("#workspace-title").textContent = `欢迎回来，${user.username}`;
  document.querySelector("#user-name").textContent = user.username;
  document.querySelector("#user-role").textContent = user.role;
  document.querySelector("#user-contact").textContent = user.contact;
  document.querySelector("#user-created-at").textContent = formatDateTime(user.created_at);
  document.querySelector("#user-role-badge").textContent = user.role;
  document
    .querySelector("#user-role-badge")
    .classList.toggle("admin", user.role === "admin");

  const [projectsPayload, backtestsPayload] = await Promise.all([
    api("/api/v1/strategies/projects"),
    api("/api/v1/backtests/runs"),
  ]);

  renderProjects(projectsPayload.data.items);
  renderBacktests(backtestsPayload.data.items);
  setStatus(`工作台已刷新，当前账户：${user.username}。`);
}

document.querySelector("#logout-btn").addEventListener("click", async () => {
  try {
    await logout();
    window.location.href = "/";
  } catch (error) {
    setStatus(error.message);
  }
});

loadWorkspace().catch((error) => setStatus(error.message));
