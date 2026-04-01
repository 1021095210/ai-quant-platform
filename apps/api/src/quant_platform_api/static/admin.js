import {
  activateNav,
  api,
  fetchCurrentUser,
  formatDateTime,
  logout,
  setStatus,
} from "/assets/shared.js";

activateNav("/admin");

function renderDistributionPanels(summary) {
  const sections = [
    ["角色分布", summary.role_distribution || []],
    ["任务状态", summary.task_status_distribution || []],
    ["任务类型", summary.task_kind_distribution || []],
  ];
  document.querySelector("#distribution-panels").innerHTML = sections
    .map(
      ([title, items]) => `
        <div class="card muted">
          <span class="mini-label">${title}</span>
          <div class="distribution-list">
            ${
              items.length
                ? items
                    .map(
                      (item) => `
                        <div class="distribution-item">
                          <strong>${item.label}</strong>
                          <span class="badge">${item.count}</span>
                        </div>
                      `,
                    )
                    .join("")
                : '<div class="empty-state">暂无数据。</div>'
            }
          </div>
        </div>
      `,
    )
    .join("");
}

function renderGovernanceNotes(items) {
  const node = document.querySelector("#governance-notes");
  if (!items.length) {
    node.textContent = "暂无治理建议。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>治理提示</strong>
          <div class="muted-note">${item}</div>
        </div>
      `,
    )
    .join("");
}

function renderUsers(items, currentUserId) {
  const node = document.querySelector("#admin-users-table");
  if (!items.length) {
    node.innerHTML = '<tr><td colspan="6" class="empty-state">暂无用户数据。</td></tr>';
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>
            <strong>${item.username}</strong>
            <div class="muted-note">${item.contact}</div>
            <div class="muted-note">${item.workspace_id}</div>
          </td>
          <td>
            <span class="badge ${item.role === "admin" ? "admin" : ""}">${item.role}</span>
            <div class="muted-note">${formatDateTime(item.created_at)} 创建</div>
          </td>
          <td>
            <div class="muted-note">项目 ${item.project_count} / 回测 ${item.backtest_count} / 复盘 ${item.replay_count}</div>
            <div class="muted-note">优化 ${item.optimization_count} / 运行中 ${item.running_task_count}</div>
          </td>
          <td>
            <div class="muted-note">活跃会话 ${item.active_sessions}</div>
            <div class="muted-note">失败任务 ${item.failed_task_count}</div>
          </td>
          <td>${formatDateTime(item.last_activity_at)}</td>
          <td>
            <div class="role-editor">
              <select class="role-select" data-role-select="${item.user_id}">
                <option value="user" ${item.role === "user" ? "selected" : ""}>普通用户</option>
                <option value="admin" ${item.role === "admin" ? "selected" : ""}>管理员</option>
              </select>
              <button
                class="btn secondary role-save-btn"
                type="button"
                data-role-save="${item.user_id}"
                ${item.user_id === currentUserId ? "disabled" : ""}
              >
                保存
              </button>
            </div>
            ${item.user_id === currentUserId ? '<div class="muted-note">当前登录管理员不可在此页修改自己的角色。</div>' : ""}
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderRecentTasks(items) {
  const node = document.querySelector("#recent-tasks");
  if (!items.length) {
    node.textContent = "暂无任务记录。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.username} · ${item.kind}</strong>
          <div class="muted-note">${item.title}</div>
          <div class="muted-note">${formatDateTime(item.created_at)} · ${item.status} · ${item.config_revision || "无配置版本"}</div>
          <div class="muted-note">快照 ${item.dataset_snapshot_ref || "未标记"} / ${item.workspace_id}</div>
        </div>
      `,
    )
    .join("");
}

function renderSnapshots(items) {
  const node = document.querySelector("#admin-snapshots");
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
          <div class="muted-note">覆盖率 ${item.coverage_pct ?? "-"}% · 缺失率 ${item.missing_rate_pct ?? "-"}% · ${item.coverage_status || "unknown"}</div>
          <div class="muted-note">${item.timezone || "未知时区"} / ${item.calendar || "未知日历"} / 预热 ${item.warmup_bars ?? "-"}</div>
        </div>
      `,
    )
    .join("");
}

function bindRoleActions(loadUsers) {
  document.querySelectorAll("[data-role-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const userId = button.getAttribute("data-role-save");
      const select = document.querySelector(`[data-role-select="${userId}"]`);
      try {
        await api(`/api/v1/admin/users/${userId}/role`, {
          method: "PUT",
          body: JSON.stringify({ role: select.value }),
        });
        setStatus("用户角色已更新。");
        await loadUsers();
      } catch (error) {
        setStatus(error.message);
      }
    });
  });
}

async function loadAdminConsole() {
  const user = await fetchCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/admin";
    return;
  }
  if (user.role !== "admin") {
    window.location.href = "/workspace";
    return;
  }

  document.querySelector("#admin-name").textContent = user.username;
  document.querySelector("#admin-title").textContent = `管理员工作台 · ${user.username}`;

  const summary = (await api("/api/v1/admin/summary")).data;
  document.querySelector("#metric-users").textContent = `${summary.counts.users}`;
  document.querySelector("#metric-admins").textContent = `${summary.counts.admins}`;
  document.querySelector("#metric-sessions").textContent = `${summary.counts.active_sessions}`;
  document.querySelector("#metric-projects").textContent = `${summary.counts.projects}`;
  document.querySelector("#metric-backtests").textContent = `${summary.counts.backtests}`;
  document.querySelector("#metric-running").textContent = `${summary.counts.running_tasks}`;
  document.querySelector("#admin-headline").textContent =
    summary.counts.failed_tasks ? "关注失败任务与数据风险" : "平台运行平稳";

  renderDistributionPanels(summary);
  renderGovernanceNotes(summary.governance_notes || []);
  renderRecentTasks(summary.recent_tasks || []);
  renderSnapshots(summary.snapshot_states || []);

  const loadUsers = async () => {
    const users = (await api("/api/v1/admin/users")).data.items || [];
    renderUsers(users, user.user_id);
    bindRoleActions(loadUsers);
  };

  await loadUsers();
  setStatus(`管理后台已刷新，当前管理员：${user.username}。`);
}

document.querySelector("#logout-btn").addEventListener("click", async () => {
  try {
    await logout();
    window.location.href = "/";
  } catch (error) {
    setStatus(error.message);
  }
});

loadAdminConsole().catch((error) => setStatus(error.message));
