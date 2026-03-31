const state = {
  generatedStrategy: null,
  currentVersionId: null,
  currentUploadId: null,
};

const nodes = {
  statusBox: document.querySelector("#status-box"),
  projectList: document.querySelector("#project-list"),
  currentVersionId: document.querySelector("#current-version-id"),
  currentUploadId: document.querySelector("#current-upload-id"),
  strategyPrompt: document.querySelector("#strategy-prompt"),
  strategyMarket: document.querySelector("#strategy-market"),
  strategyTimeframe: document.querySelector("#strategy-timeframe"),
  strategyDslOutput: document.querySelector("#strategy-dsl-output"),
  strategySummary: document.querySelector("#strategy-summary"),
  projectTitle: document.querySelector("#project-title"),
  projectSaveResult: document.querySelector("#project-save-result"),
  backtestResult: document.querySelector("#backtest-result"),
  optimizationResult: document.querySelector("#optimization-result"),
  tradeFile: document.querySelector("#trade-file"),
  tradeCsvText: document.querySelector("#trade-csv-text"),
  tradeRecordsResult: document.querySelector("#trade-records-result"),
  replayResult: document.querySelector("#replay-result"),
};

function setStatus(message) {
  nodes.statusBox.textContent = message;
}

function setCurrentVersion(versionId) {
  state.currentVersionId = versionId;
  nodes.currentVersionId.textContent = versionId || "未保存";
}

function setCurrentUpload(uploadId) {
  state.currentUploadId = uploadId;
  nodes.currentUploadId.textContent = uploadId || "未上传";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
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

async function pollTask(url) {
  for (let index = 0; index < 20; index += 1) {
    const payload = await api(url);
    const data = payload.data;
    if (["completed", "failed", "cancelled"].includes(data.status)) {
      return data;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("任务轮询超时");
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function refreshProjects() {
  const payload = await api("/api/v1/strategies/projects");
  const items = payload.data.items;
  if (!items.length) {
    nodes.projectList.textContent = "还没有项目，先生成并保存一个策略。";
    return;
  }

  nodes.projectList.innerHTML = items
    .map(
      (item) => `
        <div class="project-item">
          <strong>${item.title}</strong>
          <div>版本: ${item.version_id}</div>
          <div>市场: ${item.strategy_dsl.market} / ${item.strategy_dsl.timeframe}</div>
        </div>
      `,
    )
    .join("");
}

async function generateStrategy() {
  setStatus("正在生成策略...");
  const payload = await api("/api/v1/strategies/generate", {
    method: "POST",
    body: JSON.stringify({
      prompt: nodes.strategyPrompt.value,
      market: nodes.strategyMarket.value,
      timeframe: nodes.strategyTimeframe.value,
      preferences: { side: "long" },
    }),
  });
  state.generatedStrategy = payload.data.strategy_dsl;
  nodes.strategyDslOutput.value = pretty(payload.data.strategy_dsl);
  nodes.strategySummary.textContent = payload.data.human_summary;
  setStatus("策略生成完成。");
}

async function saveProject() {
  if (!state.generatedStrategy) {
    throw new Error("请先生成策略。");
  }
  setStatus("正在保存项目...");
  const payload = await api("/api/v1/strategies/projects", {
    method: "POST",
    body: JSON.stringify({
      title: nodes.projectTitle.value,
      natural_language_prompt: nodes.strategyPrompt.value,
      strategy_dsl: state.generatedStrategy,
    }),
  });
  setCurrentVersion(payload.data.version_id);
  nodes.projectSaveResult.textContent = pretty(payload.data);
  await refreshProjects();
  setStatus("项目保存完成。");
}

function buildDataset() {
  return {
    market: nodes.strategyMarket.value,
    timeframe: nodes.strategyTimeframe.value,
    from: new Date(document.querySelector("#backtest-from").value).toISOString(),
    to: new Date(document.querySelector("#backtest-to").value).toISOString(),
  };
}

function buildExecutionContract() {
  return {
    initial_capital: 100000,
    fee_bps: 10,
    slippage_bps: 5,
    fill_price_rule: "next_bar_open",
    intrabar_match_policy: "no_intrabar_fill",
    calendar: "crypto_24_7",
    timezone: "UTC",
    adjustment_mode: "raw",
  };
}

async function runBacktest() {
  if (!state.currentVersionId) {
    throw new Error("请先保存策略项目。");
  }
  setStatus("正在创建回测任务...");
  const created = await api("/api/v1/backtests/runs", {
    method: "POST",
    body: JSON.stringify({
      strategy_version_id: state.currentVersionId,
      dataset: buildDataset(),
      execution_contract: buildExecutionContract(),
      data_snapshot: {
        dataset_snapshot_ref: `${nodes.strategyMarket.value}_${nodes.strategyTimeframe.value}_demo_v1`,
      },
    }),
  });
  const result = await pollTask(created.data.status_url);
  nodes.backtestResult.textContent = pretty(result);
  setStatus("回测完成。");
}

async function runOptimization() {
  if (!state.currentVersionId) {
    throw new Error("请先保存策略项目。");
  }
  setStatus("正在运行参数优化...");
  const created = await api("/api/v1/optimization-jobs", {
    method: "POST",
    body: JSON.stringify({
      strategy_version_id: state.currentVersionId,
      search_space: {
        "entry.all[0].params.fast": [3, 5, 8],
        "entry.all[0].params.slow": [15, 20, 30],
      },
      objective: "profit_factor",
      dataset: buildDataset(),
      data_snapshot: {
        dataset_snapshot_ref: `${nodes.strategyMarket.value}_${nodes.strategyTimeframe.value}_demo_v1`,
      },
      execution_contract: buildExecutionContract(),
    }),
  });
  const result = await pollTask(created.data.status_url);
  nodes.optimizationResult.textContent = pretty(result);
  setStatus("参数优化完成。");
}

async function uploadTrades() {
  setStatus("正在上传交割单...");
  const formData = new FormData();
  const file = nodes.tradeFile.files[0];
  if (file) {
    formData.append("file", file);
  } else {
    const blob = new Blob([nodes.tradeCsvText.value], { type: "text/csv" });
    formData.append("file", blob, "trades.csv");
  }

  const uploaded = await api("/api/v1/trades/uploads", {
    method: "POST",
    body: formData,
  });
  setCurrentUpload(uploaded.data.upload_id);

  const parsed = await api(`/api/v1/trades/uploads/${uploaded.data.upload_id}/parse`, {
    method: "POST",
    body: JSON.stringify({
      column_mapping: {
        symbol: "symbol",
        side: "side",
        entry_time: "entry_time",
        exit_time: "exit_time",
        pnl: "pnl",
      },
    }),
  });
  const records = await api(`/api/v1/trades/uploads/${uploaded.data.upload_id}/records`);
  nodes.tradeRecordsResult.textContent = `${pretty(parsed.data)}\n\n${pretty(records.data.items)}`;
  setStatus("交割单解析完成。");
}

async function runReplay() {
  if (!state.currentUploadId) {
    throw new Error("请先上传并解析交割单。");
  }
  setStatus("正在运行 AI 复盘...");
  const created = await api("/api/v1/replays/analyses", {
    method: "POST",
    body: JSON.stringify({
      upload_id: state.currentUploadId,
      focus_dimensions: ["volume_structure", "moving_average_structure"],
      custom_prompt: "重点分析量价关系和均线位置",
    }),
  });
  const result = await pollTask(created.data.status_url);
  nodes.replayResult.textContent = pretty(result);
  setStatus("AI 复盘完成。");
}

function bindEvents() {
  document
    .querySelector("#generate-strategy-btn")
    .addEventListener("click", () => handle(generateStrategy));
  document
    .querySelector("#save-project-btn")
    .addEventListener("click", () => handle(saveProject));
  document
    .querySelector("#run-backtest-btn")
    .addEventListener("click", () => handle(runBacktest));
  document
    .querySelector("#run-optimization-btn")
    .addEventListener("click", () => handle(runOptimization));
  document
    .querySelector("#upload-trades-btn")
    .addEventListener("click", () => handle(uploadTrades));
  document
    .querySelector("#run-replay-btn")
    .addEventListener("click", () => handle(runReplay));
  document
    .querySelector("#refresh-projects-btn")
    .addEventListener("click", () => handle(refreshProjects));
}

async function handle(fn) {
  try {
    await fn();
  } catch (error) {
    setStatus(error.message);
  }
}

bindEvents();
handle(refreshProjects);
