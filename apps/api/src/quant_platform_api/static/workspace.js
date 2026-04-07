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
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          <div class="muted-note">${item.version_label || item.version_id}</div>
          <div class="muted-note">${item.market} / ${(item.timeframes || []).join(" / ")}</div>
          <div class="muted-note">${item.analysis_mode === "multi_timeframe" ? "混合周期策略" : "单周期策略"} · ${formatDateTime(item.created_at)}</div>
        </div>
      `,
    )
    .join("");
}

function renderFocusCards(items) {
  const node = document.querySelector("#workspace-focus-cards");
  if (!items.length) {
    node.textContent = "当前还没有形成明确的下一步建议。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <a class="list-item" href="${item.path}">
          <strong>${item.title}</strong>
          <div class="muted-note">${item.summary}</div>
          <div class="muted-note">${item.action_label}</div>
        </a>
      `,
    )
    .join("");
}

function renderDataHubStatus(status) {
  const node = document.querySelector("#workspace-data-hub");
  if (!status || !Object.keys(status).length) {
    node.textContent = "当前没有可展示的数据中心状态。";
    return;
  }
  const primaryFeed = status.primary_feed || {};
  node.innerHTML = `
    <div class="list-item">
      <strong>优先数据来源</strong>
      <div class="muted-note">${status.preferred_provider || "未知"} / 回退 ${status.fallback_provider || "未知"}</div>
    </div>
    <div class="list-item">
      <strong>内部数据仓库状态</strong>
      <div class="muted-note">${primaryFeed.configured ? "已配置" : "未配置"}${primaryFeed.latest_trade_date ? ` · 最新交易日 ${primaryFeed.latest_trade_date}` : ""}</div>
    </div>
    <div class="list-item">
      <strong>默认读取层</strong>
      <div class="muted-note">${primaryFeed.preferred_layer ? `${String(primaryFeed.preferred_layer).toUpperCase()} 优先` : "内部数仓未启用"}${primaryFeed.configured ? " · 用户侧默认优先读取 DWD/ADS" : ""}</div>
    </div>
  `;
}

function renderBacktests(items) {
  const node = document.querySelector("#recent-backtests");
  document.querySelector("#backtest-count").textContent = `${items.length}`;
  if (!items.length) {
    node.textContent = "暂无回测记录。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title || item.task_id}</strong>
          <div class="muted-note">${formatDateTime(item.created_at)} · ${item.status}</div>
          <div class="muted-note">收益 ${item.metrics.total_return_pct ?? 0}% / 交易 ${item.metrics.trade_count ?? 0} 次 / 期末净值 ${item.metrics.final_equity ?? 0}</div>
          <div class="muted-note">快照 ${item.dataset_snapshot_ref || "未标记"} · 配置 ${item.config_revision}</div>
        </div>
      `,
    )
    .join("");
}

function renderReplays(items) {
  const node = document.querySelector("#recent-replays");
  document.querySelector("#replay-count").textContent = `${items.length}`;
  if (!items.length) {
    node.textContent = "暂无复盘记录。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title || item.task_id}</strong>
          <div class="muted-note">${formatDateTime(item.created_at)} · ${item.status}</div>
          <div class="muted-note">快照 ${item.dataset_snapshot_ref || "未标记"} / 配置 ${item.config_revision}</div>
        </div>
      `,
    )
    .join("");
}

function renderFailures(items) {
  const node = document.querySelector("#recent-failures");
  document.querySelector("#failed-task-count").textContent = `${items.length}`;
  if (!items.length) {
    node.textContent = "暂无失败任务。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.kind} / ${item.task_id}</strong>
          <div class="muted-note">${formatDateTime(item.created_at)} · ${item.status}</div>
          <div class="muted-note">配置 ${item.config_revision} · 快照 ${item.dataset_snapshot_ref || "未标记"}</div>
        </div>
      `,
    )
    .join("");
}

function renderSnapshots(items) {
  const node = document.querySelector("#snapshot-states");
  if (!items.length) {
    node.textContent = "暂无数据快照摘要。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.dataset_snapshot_ref}</strong>
          <div class="muted-note">${item.market || "未知市场"} / ${item.timeframe || "未知周期"} / ${item.provider || "未知来源"}</div>
          <div class="muted-note">覆盖率 ${item.coverage_pct ?? "-"}% · 缺失率 ${item.missing_rate_pct ?? "-"}% · 状态 ${item.coverage_status || "unknown"}</div>
          <div class="muted-note">${item.timezone || "未知时区"} / ${item.calendar || "未知日历"} / 预热 ${item.warmup_bars ?? "-"}</div>
        </div>
      `,
    )
    .join("");
}

function chooseNextStep(summary) {
  if (!summary.recent_projects.length) {
    return "如果你还不确定该从哪里开始，先去金融导师理清概念，或去金融助手按研究任务拆框架，再在策略工坊创建第一个策略项目。";
  }
  if (!summary.recent_backtests.length) {
    return "你已经有策略项目，下一步建议运行一轮带明确成交假设和风险参数的回测。";
  }
  if (summary.recent_failures.length) {
    return "最近有失败或取消任务，建议优先检查对应配置、快照引用和数据范围，再继续扩实验。";
  }
  if (!summary.recent_replays.length) {
    return "最近回测已有沉淀，下一步建议导入交割单或进入交易复盘，把经验回灌到策略。";
  }
  return "当前研究链路比较完整，建议对同一策略做多组回测配置对比，再进入下一轮迭代。";
}

function revealAdminEntry() {
  document.querySelector("#admin-nav-link").hidden = false;
  document.querySelector("#admin-entry-btn").hidden = false;
  document.querySelector("#admin-quick-card").hidden = false;
  document.querySelector("#admin-context-item").hidden = false;
  document.querySelector("#workspace-subtitle").textContent =
    "这里集中查看个人研究进展；你同时拥有管理员入口，可进一步查看平台用户、任务与运行态。";
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
  if (user.role === "admin") {
    revealAdminEntry();
  }

  const summary = (await api("/api/v1/workspace/summary")).data;
  renderProjects(summary.recent_projects || []);
  renderFocusCards(summary.focus_cards || []);
  renderBacktests(summary.recent_backtests || []);
  renderReplays(summary.recent_replays || []);
  renderFailures(summary.recent_failures || []);
  renderSnapshots(summary.snapshot_states || []);
  renderDataHubStatus(summary.data_hub_status || {});
  document.querySelector("#workspace-next-step").textContent = chooseNextStep(summary);
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
