const STORAGE_KEYS = {
  selectedVersionId: "quant.selectedVersionId",
  selectedVersionLabel: "quant.selectedVersionLabel",
  selectedProjectTitle: "quant.selectedProjectTitle",
};

export function activateNav(currentPath) {
  document.querySelectorAll("[data-nav]").forEach((node) => {
    node.classList.toggle("active", node.getAttribute("href") === currentPath);
  });
}

export function setStatus(message) {
  const node = document.querySelector("#status-banner");
  if (node) {
    node.textContent = message;
  }
}

export async function api(path, options = {}) {
  try {
    const response = await fetch(path, {
      headers: {
        Accept: "application/json",
        ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(options.headers || {}),
      },
      ...options,
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const message = payload?.detail?.message || payload?.error?.message || "请求失败";
      if (!String(path).includes("/api/v1/client-errors")) {
        reportClientError({
          message,
          category: "api_error",
          requestPath: typeof path === "string" ? path : window.location.pathname,
          details: {
            status: response.status,
            method: options.method || "GET",
          },
        });
      }
      throw new Error(message);
    }

    return response.json();
  } catch (error) {
    if (!String(path).includes("/api/v1/client-errors")) {
      reportClientError({
        message: error.message || "网络请求失败",
        category: "network_error",
        requestPath: typeof path === "string" ? path : window.location.pathname,
        details: {
          method: options.method || "GET",
        },
      });
    }
    throw error;
  }
}

export async function fetchLlmProfiles() {
  const payload = await api("/api/v1/platform/llm-profiles");
  return payload.data || { items: [], defaults: {} };
}

export function populateLlmProfileSelect(selectNode, profilePayload, moduleKey) {
  if (!selectNode) {
    return;
  }
  const items = (profilePayload?.items || []).filter((item) => item.enabled);
  const defaults = profilePayload?.defaults || {};
  const selectedValue = defaults[moduleKey] || "module_default";
  if (!items.length) {
    selectNode.innerHTML = '<option value="module_default">当前无可用 LLM 配置</option>';
    selectNode.disabled = true;
    return;
  }
  selectNode.innerHTML = items
    .map((item) => {
      const suffix = item.model ? ` · ${item.model}` : "";
      return `<option value="${item.profile_id}">${item.label}${suffix}</option>`;
    })
    .join("");
  selectNode.disabled = false;
  if (items.some((item) => item.profile_id === selectedValue)) {
    selectNode.value = selectedValue;
  }
}

export async function fetchCurrentUser() {
  const response = await fetch("/api/v1/auth/me", {
    headers: { Accept: "application/json" },
  });
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error?.message || "无法获取当前用户信息");
  }
  const payload = await response.json();
  return payload.data;
}

export async function logout() {
  await api("/api/v1/auth/logout", { method: "POST" });
}

export function getNextPath(defaultPath = "/workspace") {
  const next = new URLSearchParams(window.location.search).get("next") || defaultPath;
  return next.startsWith("/") ? next : defaultPath;
}

export function pretty(value) {
  return JSON.stringify(value, null, 2);
}

export async function pollTask(url) {
  for (let index = 0; index < 30; index += 1) {
    const payload = await api(url);
    const data = payload.data;
    if (["succeeded", "failed", "canceled"].includes(data.status)) {
      return data;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("任务轮询超时");
}

export function setSelectedVersion(versionId, title = "", versionLabel = "") {
  localStorage.setItem(STORAGE_KEYS.selectedVersionId, versionId || "");
  localStorage.setItem(STORAGE_KEYS.selectedVersionLabel, versionLabel || "");
  localStorage.setItem(STORAGE_KEYS.selectedProjectTitle, title || "");
}

export function getSelectedVersion() {
  return {
    versionId: localStorage.getItem(STORAGE_KEYS.selectedVersionId) || "",
    versionLabel: localStorage.getItem(STORAGE_KEYS.selectedVersionLabel) || "",
    title: localStorage.getItem(STORAGE_KEYS.selectedProjectTitle) || "",
  };
}

export function formatDateTime(value) {
  if (!value) {
    return "时间未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function renderMetricCards(container, metrics) {
  const items = [
    ["累计收益", `${metrics.total_return_pct ?? 0}%`],
    ["最大回撤", `${metrics.max_drawdown_pct ?? 0}%`],
    ["胜率", `${metrics.win_rate_pct ?? 0}%`],
    ["盈亏比", `${metrics.profit_factor ?? 0}`],
    ["交易次数", `${metrics.trade_count ?? 0}`],
    ["期末净值", `${metrics.final_equity ?? 0}`],
    ["平均单笔收益", `${metrics.avg_trade_return_pct ?? 0}%`],
  ];
  container.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="card muted">
          <span class="mini-label">${label}</span>
          <strong class="metric-value">${value}</strong>
        </div>
      `,
    )
    .join("");
}

export function renderSparkline(container, points) {
  if (!points.length) {
    container.innerHTML = '<div class="empty-state" style="padding:24px">暂无净值曲线。</div>';
    return;
  }

  const width = 640;
  const height = 220;
  const values = points.map((item) => item.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const gap = max - min || 1;
  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  const firstEquity = Number(firstPoint.equity || 0);
  const lastEquity = Number(lastPoint.equity || 0);
  const returnPct = firstEquity ? (((lastEquity - firstEquity) / firstEquity) * 100).toFixed(2) : "0.00";
  const coordinates = points
    .map((item, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((item.equity - min) / gap) * (height - 24) - 12;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  container.innerHTML = `
    <div class="sparkline-summary">
      <div>
        <span class="mini-label">曲线区间</span>
        <strong>${firstPoint.ts} → ${lastPoint.ts}</strong>
      </div>
      <div>
        <span class="mini-label">区间收益</span>
        <strong class="${Number(returnPct) >= 0 ? "positive" : "negative"}">${Number(returnPct) >= 0 ? "+" : ""}${returnPct}%</strong>
      </div>
      <div>
        <span class="mini-label">净值范围</span>
        <strong>${min.toFixed(2)} ~ ${max.toFixed(2)}</strong>
      </div>
    </div>
    <div class="sparkline-frame">
      <div class="sparkline-y-axis">
        <span>${max.toFixed(2)}</span>
        <span>${((max + min) / 2).toFixed(2)}</span>
        <span>${min.toFixed(2)}</span>
      </div>
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" width="100%" height="${height}">
        <defs>
          <linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stop-color="rgba(36,99,235,0.34)" />
            <stop offset="100%" stop-color="rgba(36,99,235,0.02)" />
          </linearGradient>
        </defs>
        <polyline fill="none" stroke="#2463eb" stroke-width="4" points="${coordinates}" />
      </svg>
    </div>
    <div class="sparkline-x-axis">
      <span>${firstPoint.ts}</span>
      <span>${lastPoint.ts}</span>
    </div>
  `;
}

export function handle(action) {
  return async () => {
    try {
      await action();
    } catch (error) {
      setStatus(error.message);
    }
  };
}

export function reportClientError({
  message,
  category = "client_error",
  requestPath = window.location.pathname,
  details = {},
}) {
  if (!message || requestPath === "/api/v1/client-errors") {
    return;
  }
  fetch("/api/v1/client-errors", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    keepalive: true,
    body: JSON.stringify({
      message,
      source: "web",
      category,
      request_path: requestPath,
      details: {
        ...details,
        user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "unknown",
      },
    }),
  }).catch(() => {});
}

if (
  typeof window !== "undefined"
  && typeof window.addEventListener === "function"
  && !window.__quantClientErrorReporterInstalled
) {
  window.__quantClientErrorReporterInstalled = true;
  window.addEventListener("error", (event) => {
    reportClientError({
      message: event.message || "页面脚本异常",
      category: "client_runtime_error",
      requestPath: window.location.pathname,
      details: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      },
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason?.message || String(event.reason || "promise rejected");
    reportClientError({
      message: reason,
      category: "client_promise_rejection",
      requestPath: window.location.pathname,
    });
  });
}
