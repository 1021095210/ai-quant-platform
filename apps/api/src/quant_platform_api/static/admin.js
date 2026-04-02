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

function roleBadge(role) {
  return `<span class="badge ${role === "admin" ? "admin" : ""}">${role}</span>`;
}

function statusBadge(status) {
  const badgeClass = status === "active" ? "" : "admin";
  const label = status === "active" ? "active" : "suspended";
  return `<span class="badge ${badgeClass}">${label}</span>`;
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
            <div>${roleBadge(item.role)} ${statusBadge(item.status)}</div>
            <div class="muted-note">${formatDateTime(item.created_at)} 创建</div>
            <div class="muted-note">${item.status_reason || "无停用说明"}</div>
          </td>
          <td>
            <div class="muted-note">项目 ${item.project_count} / 回测 ${item.backtest_count} / 复盘 ${item.replay_count}</div>
            <div class="muted-note">优化 ${item.optimization_count} / 运行中 ${item.running_task_count}</div>
            <div class="muted-note">失败任务 ${item.failed_task_count}</div>
          </td>
          <td>
            <div class="muted-note">活跃会话 ${item.active_sessions}</div>
            <div class="muted-note">24h 失败登录 ${item.failed_login_count_24h}</div>
            <div class="muted-note">最近登录 ${formatDateTime(item.last_login_at)}</div>
            <div class="muted-note">最近失败 ${formatDateTime(item.last_failed_login_at)}</div>
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
                保存角色
              </button>
            </div>
            <div class="role-editor" style="margin-top: 8px;">
              <select class="role-select" data-status-select="${item.user_id}">
                <option value="active" ${item.status === "active" ? "selected" : ""}>启用</option>
                <option value="suspended" ${item.status !== "active" ? "selected" : ""}>停用</option>
              </select>
              <button
                class="btn secondary"
                type="button"
                data-status-save="${item.user_id}"
                ${item.user_id === currentUserId ? "disabled" : ""}
              >
                保存状态
              </button>
            </div>
            <input
              class="input"
              type="text"
              data-status-reason="${item.user_id}"
              value="${item.status_reason || ""}"
              placeholder="停用说明 / 恢复备注"
              style="margin-top: 8px;"
            />
            <div class="role-editor" style="margin-top: 8px;">
              <input
                class="input"
                type="password"
                data-password-input="${item.user_id}"
                placeholder="输入新密码"
              />
              <button class="btn ghost" type="button" data-password-reset="${item.user_id}">
                重置密码
              </button>
            </div>
            ${
              item.user_id === currentUserId
                ? '<div class="muted-note">当前登录管理员不可在此页停用自己或修改自己的角色。</div>'
                : ""
            }
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

function renderAuditLogs(items) {
  const node = document.querySelector("#admin-audit-logs");
  if (!items.length) {
    node.textContent = "暂无审计日志。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.summary}</strong>
          <div class="muted-note">${item.actor_username} → ${item.target_username || "系统对象"}</div>
          <div class="muted-note">${formatDateTime(item.created_at)} · ${item.action}</div>
        </div>
      `,
    )
    .join("");
}

function renderSecurityEvents(items) {
  const node = document.querySelector("#admin-security-events");
  if (!items.length) {
    node.textContent = "暂无安全事件。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.username} · ${item.event_type} · ${item.outcome}</strong>
          <div class="muted-note">${item.reason || "无补充说明"} ${item.ip_address ? `· ${item.ip_address}` : ""}</div>
          <div class="muted-note">${formatDateTime(item.created_at)}</div>
        </div>
      `,
    )
    .join("");
}

function renderAppLogs(items) {
  const node = document.querySelector("#admin-app-logs");
  if (!items.length) {
    node.textContent = "暂无应用报错记录。";
    return;
  }
  node.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.message}</strong>
          <div class="muted-note">${item.source} / ${item.category} / ${item.level}</div>
          <div class="muted-note">${item.request_path || "无请求路径"} · ${item.username || "匿名用户"}${item.workspace_id ? ` · ${item.workspace_id}` : ""}</div>
          <div class="muted-note">${formatDateTime(item.created_at)}</div>
        </div>
      `,
    )
    .join("");
}

function bindUserActions(loadAll, currentUserId) {
  document.querySelectorAll("[data-role-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const userId = button.getAttribute("data-role-save");
      if (userId === currentUserId) {
        return;
      }
      const select = document.querySelector(`[data-role-select="${userId}"]`);
      try {
        await api(`/api/v1/admin/users/${userId}/role`, {
          method: "PUT",
          body: JSON.stringify({ role: select.value }),
        });
        setStatus("用户角色已更新。");
        await loadAll();
      } catch (error) {
        setStatus(error.message);
      }
    });
  });

  document.querySelectorAll("[data-status-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const userId = button.getAttribute("data-status-save");
      if (userId === currentUserId) {
        return;
      }
      const statusSelect = document.querySelector(`[data-status-select="${userId}"]`);
      const reasonInput = document.querySelector(`[data-status-reason="${userId}"]`);
      try {
        await api(`/api/v1/admin/users/${userId}/status`, {
          method: "PUT",
          body: JSON.stringify({
            status: statusSelect.value,
            reason: reasonInput.value || null,
          }),
        });
        setStatus("用户状态已更新。");
        await loadAll();
      } catch (error) {
        setStatus(error.message);
      }
    });
  });

  document.querySelectorAll("[data-password-reset]").forEach((button) => {
    button.addEventListener("click", async () => {
      const userId = button.getAttribute("data-password-reset");
      const input = document.querySelector(`[data-password-input="${userId}"]`);
      if (!input.value) {
        setStatus("请先输入新密码。");
        return;
      }
      try {
        await api(`/api/v1/admin/users/${userId}/reset-password`, {
          method: "POST",
          body: JSON.stringify({ new_password: input.value }),
        });
        input.value = "";
        setStatus("密码已重置，并已清理该用户会话。");
        await loadAll();
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

  const loadAll = async () => {
    const summary = (await api("/api/v1/admin/summary")).data;
    const users = (await api("/api/v1/admin/users")).data.items || [];
    const auditLogs = (await api("/api/v1/admin/audit-logs")).data.items || [];
    const securityEvents = (await api("/api/v1/admin/security-events")).data.items || [];
    const appLogs = (await api("/api/v1/admin/app-logs")).data.items || [];

    document.querySelector("#metric-users").textContent = `${summary.counts.users}`;
    document.querySelector("#metric-admins").textContent = `${summary.counts.admins}`;
    document.querySelector("#metric-suspended").textContent = `${summary.counts.suspended_users}`;
    document.querySelector("#metric-sessions").textContent = `${summary.counts.active_sessions}`;
    document.querySelector("#metric-projects").textContent = `${summary.counts.projects}`;
    document.querySelector("#metric-backtests").textContent = `${summary.counts.backtests}`;
    document.querySelector("#metric-running").textContent = `${summary.counts.running_tasks}`;
    document.querySelector("#metric-failed-logins").textContent = `${summary.counts.failed_logins_24h}`;
    document.querySelector("#metric-app-errors").textContent = `${summary.counts.app_errors_24h}`;
    document.querySelector("#admin-headline").textContent =
      summary.counts.failed_tasks || summary.counts.failed_logins_24h || summary.counts.suspended_users || summary.counts.app_errors_24h
        ? "关注账户安全、失败任务与真实用户报错"
        : "平台运行平稳";

    renderDistributionPanels(summary);
    renderGovernanceNotes(summary.governance_notes || []);
    renderRecentTasks(summary.recent_tasks || []);
    renderSnapshots(summary.snapshot_states || []);
    renderUsers(users, user.user_id);
    renderAuditLogs(auditLogs);
    renderSecurityEvents(securityEvents);
    renderAppLogs(appLogs);
    bindUserActions(loadAll, user.user_id);
  };

  await loadAll();
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
