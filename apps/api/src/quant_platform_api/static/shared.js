const STORAGE_KEYS = {
  selectedVersionId: "quant.selectedVersionId",
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
    throw new Error(payload?.detail?.message || payload?.error?.message || "请求失败");
  }

  return response.json();
}

export function pretty(value) {
  return JSON.stringify(value, null, 2);
}

export async function pollTask(url) {
  for (let index = 0; index < 30; index += 1) {
    const payload = await api(url);
    const data = payload.data;
    if (["completed", "failed", "cancelled"].includes(data.status)) {
      return data;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("任务轮询超时");
}

export function setSelectedVersion(versionId, title = "") {
  localStorage.setItem(STORAGE_KEYS.selectedVersionId, versionId || "");
  localStorage.setItem(STORAGE_KEYS.selectedProjectTitle, title || "");
}

export function getSelectedVersion() {
  return {
    versionId: localStorage.getItem(STORAGE_KEYS.selectedVersionId) || "",
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
    ["Profit Factor", `${metrics.profit_factor ?? 0}`],
    ["交易次数", `${metrics.trade_count ?? 0}`],
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
  const coordinates = points
    .map((item, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((item.equity - min) / gap) * (height - 24) - 12;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" width="100%" height="${height}">
      <defs>
        <linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="rgba(36,99,235,0.34)" />
          <stop offset="100%" stop-color="rgba(36,99,235,0.02)" />
        </linearGradient>
      </defs>
      <polyline fill="none" stroke="#2463eb" stroke-width="4" points="${coordinates}" />
    </svg>
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
