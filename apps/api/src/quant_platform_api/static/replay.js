import { activateNav, api, handle, pollTask, setStatus } from "/assets/shared.js";

activateNav("/replay");

const state = {
  uploadId: "",
  replayReady: false,
  sourceMode: "csv",
  manualTrades: [],
  objectiveVersions: [],
  selectedObjective: "sharpe_max",
};

const SOURCE_MODE_META = {
  csv: {
    title: "CSV 导入",
    intro: "适合直接上传券商导出的 CSV，或把 CSV 内容粘贴进来后再解析。",
    steps: [
      "上传 CSV 文件或直接粘贴 CSV 文本。",
      "检查字段是否完整，再点击上传并解析。",
      "解析结果出来后，再运行 AI 复盘。",
    ],
  },
  screenshot: {
    title: "成交截图",
    intro: "适合只拿到券商成交截图、聊天记录截图或软件成交明细截图时使用。当前需要你同时补齐关键字段，平台先按结构化记录复盘。",
    steps: [
      "先上传成交截图，再补齐标的、时间和盈亏。",
      "确认截图对应的市场和方向没有填错。",
      "生成结构化记录后，再运行 AI 复盘。",
    ],
  },
  manual: {
    title: "手动录入",
    intro: "适合没有交割单文件时，直接逐笔补录，或者把交易计划、群聊记录、复盘笔记整段贴进来让平台智能识别。",
    steps: [
      "先选择市场，然后粘贴长文字智能识别，或逐笔手动补录。",
      "确认自动识别或手动加入的记录没有明显错误。",
      "确认记录列表无误后，再提交并运行 AI 复盘。",
    ],
  },
};

const nodes = {
  file: document.querySelector("#trade-file"),
  csvText: document.querySelector("#trade-csv-text"),
  screenshotFile: document.querySelector("#trade-screenshot-file"),
  screenshotMarket: document.querySelector("#trade-screenshot-market"),
  screenshotSymbol: document.querySelector("#trade-screenshot-symbol"),
  screenshotSide: document.querySelector("#trade-screenshot-side"),
  screenshotPnl: document.querySelector("#trade-screenshot-pnl"),
  screenshotEntry: document.querySelector("#trade-screenshot-entry"),
  screenshotExit: document.querySelector("#trade-screenshot-exit"),
  screenshotNotes: document.querySelector("#trade-screenshot-notes"),
  screenshotOcrButton: document.querySelector("#ocr-screenshot-btn"),
  screenshotOcrSummary: document.querySelector("#screenshot-ocr-summary"),
  manualSymbol: document.querySelector("#trade-manual-symbol"),
  manualSide: document.querySelector("#trade-manual-side"),
  manualEntry: document.querySelector("#trade-manual-entry"),
  manualExit: document.querySelector("#trade-manual-exit"),
  manualPnl: document.querySelector("#trade-manual-pnl"),
  manualNotes: document.querySelector("#trade-manual-notes"),
  manualMarket: document.querySelector("#trade-manual-market"),
  manualAdjustment: document.querySelector("#trade-manual-adjustment"),
  manualSmartText: document.querySelector("#trade-manual-smart-text"),
  manualParseSummary: document.querySelector("#trade-manual-parse-summary"),
  manualList: document.querySelector("#manual-trade-list"),
  uploadId: document.querySelector("#current-upload-id"),
  recordsBody: document.querySelector("#replay-records-body"),
  summary: document.querySelector("#replay-summary"),
  overview: document.querySelector("#replay-overview"),
  lossFeatures: document.querySelector("#replay-loss-features"),
  profitFeatures: document.querySelector("#replay-profit-features"),
  objectiveTabs: document.querySelector("#replay-objective-tabs"),
  objectiveDetail: document.querySelector("#replay-objective-detail"),
  counterfactualCases: document.querySelector("#replay-counterfactual-cases"),
  parameterChanges: document.querySelector("#replay-parameter-changes"),
  conditionReplacements: document.querySelector("#replay-condition-replacements"),
  tradeRecords: document.querySelector("#replay-trade-records"),
  rules: document.querySelector("#replay-rules"),
  uploadButton: document.querySelector("#upload-trades-btn"),
  uploadScreenshotButton: document.querySelector("#upload-screenshot-btn"),
  uploadManualButton: document.querySelector("#upload-manual-btn"),
  addManualTradeButton: document.querySelector("#add-manual-trade-btn"),
  parseManualTextButton: document.querySelector("#parse-manual-text-btn"),
  replayButton: document.querySelector("#run-replay-btn"),
  sourceModeTitle: document.querySelector("#source-mode-title"),
  sourceModeIntro: document.querySelector("#source-mode-intro"),
  sourceModeSteps: document.querySelector("#source-mode-steps"),
  sourceModeButtons: document.querySelectorAll(".source-mode-btn"),
  sourcePanels: {
    csv: document.querySelector("#source-panel-csv"),
    screenshot: document.querySelector("#source-panel-screenshot"),
    manual: document.querySelector("#source-panel-manual"),
  },
  replayLookbackDays: document.querySelector("#replay-lookback-days"),
  replayMinuteWindow: document.querySelector("#replay-minute-window"),
  includeMarketContext: document.querySelector("#replay-include-market-context"),
  autoMarketContext: document.querySelector("#replay-auto-market-context"),
  includeMinuteFeatures: document.querySelector("#replay-include-minute-features"),
  includeFundamentals: document.querySelector("#replay-include-fundamentals"),
};

applySourceMode("csv");
renderManualTrades();
syncReplayActionState();

async function uploadTrades() {
  syncReplayActionState({ uploadBusy: true });
  setStatus("正在上传并解析交割单...");
  const file = nodes.file.files[0];
  const formData = new FormData();
  if (file) {
    formData.append("file", file);
  } else {
    formData.append("file", new Blob([nodes.csvText.value], { type: "text/csv" }), "trades.csv");
  }
  const uploadPayload = await api("/api/v1/trades/uploads", {
    method: "POST",
    body: formData,
  });
  state.uploadId = uploadPayload.data.upload_id;
  nodes.uploadId.textContent = state.uploadId;

  await api(`/api/v1/trades/uploads/${state.uploadId}/parse`, {
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

  const recordsPayload = await api(`/api/v1/trades/uploads/${state.uploadId}/records`);
  renderRecords(recordsPayload.data.items);
  state.replayReady = true;
  syncReplayActionState();
  setStatus("交割单解析完成。");
}

async function uploadScreenshotTrade() {
  syncReplayActionState({ uploadBusy: true });
  setStatus("正在登记成交截图并生成结构化记录...");
  const file = nodes.screenshotFile.files[0];
  if (!file) {
    throw new Error("请先选择成交截图。");
  }
  if (!nodes.screenshotSymbol.value.trim()) {
    throw new Error("请先填写标的代码。");
  }
  if (!nodes.screenshotEntry.value) {
    throw new Error("请先填写买入日期时间。");
  }
  const formData = new FormData();
  formData.append("file", file);
  formData.append("market", nodes.screenshotMarket.value);
  formData.append("symbol", nodes.screenshotSymbol.value.trim());
  formData.append("side", nodes.screenshotSide.value);
  formData.append("pnl", nodes.screenshotPnl.value || "0");
  formData.append("entry_time", toIsoTimestamp(nodes.screenshotEntry.value));
  formData.append("exit_time", nodes.screenshotExit.value ? toIsoTimestamp(nodes.screenshotExit.value) : "");
  formData.append("source_notes", nodes.screenshotNotes.value.trim());
  const uploadPayload = await api("/api/v1/trades/uploads/screenshot", {
    method: "POST",
    body: formData,
  });
  state.uploadId = uploadPayload.data.upload_id;
  nodes.uploadId.textContent = state.uploadId;
  const recordsPayload = await api(`/api/v1/trades/uploads/${state.uploadId}/records`);
  renderRecords(recordsPayload.data.items);
  state.replayReady = true;
  syncReplayActionState();
  setStatus("成交截图已登记，结构化记录已生成。");
}

async function recognizeScreenshotTrade() {
  syncReplayActionState({ uploadBusy: true });
  const file = nodes.screenshotFile.files[0];
  if (!file) {
    throw new Error("请先选择成交截图。");
  }
  setStatus("正在识别截图中的日期、代码和方向...");
  const formData = new FormData();
  formData.append("file", file);
  formData.append("market", nodes.screenshotMarket.value);
  const payload = await api("/api/v1/trades/uploads/screenshot/ocr", {
    method: "POST",
    body: formData,
  });
  const data = payload.data;
  if (data.suggested_symbol) {
    nodes.screenshotSymbol.value = data.suggested_symbol;
  }
  if (data.suggested_side) {
    nodes.screenshotSide.value = data.suggested_side;
  }
  if (data.suggested_entry_time) {
    nodes.screenshotEntry.value = toLocalInputValue(data.suggested_entry_time);
  }
  if (data.suggested_exit_time) {
    nodes.screenshotExit.value = toLocalInputValue(data.suggested_exit_time);
  }
  if (typeof data.suggested_pnl === "number") {
    nodes.screenshotPnl.value = String(data.suggested_pnl);
  }
  if (data.suggested_notes) {
    nodes.screenshotNotes.value = data.suggested_notes;
  }
  nodes.screenshotOcrSummary.textContent = [
    data.raw_text ? `识别文字：\n${data.raw_text}` : "",
    data.suggested_symbol ? `建议代码：${data.suggested_symbol}` : "",
    data.detected_trade_date ? `识别日期：${data.detected_trade_date}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
  syncReplayActionState();
  setStatus("截图 OCR 识别完成，请确认识别结果后再登记成交记录。");
}

async function uploadManualTrades() {
  syncReplayActionState({ uploadBusy: true });
  if (!state.manualTrades.length) {
    throw new Error("请先加入至少一笔手动记录。");
  }
  setStatus("正在提交手动记录...");
  const uploadPayload = await api("/api/v1/trades/uploads/manual", {
    method: "POST",
    body: JSON.stringify({
      source_type: "manual",
      source_file_name: "manual-entry.json",
      source_notes: state.manualTrades.map((item) => item.notes).filter(Boolean).join("；"),
      market: nodes.manualMarket.value,
      records: state.manualTrades,
    }),
  });
  state.uploadId = uploadPayload.data.upload_id;
  nodes.uploadId.textContent = state.uploadId;
  const recordsPayload = await api(`/api/v1/trades/uploads/${state.uploadId}/records`);
  renderRecords(recordsPayload.data.items);
  state.replayReady = true;
  syncReplayActionState();
  setStatus("手动记录已提交，可以直接运行 AI 复盘。");
}

async function parseManualText() {
  syncReplayActionState({ uploadBusy: true });
  if (!nodes.manualSmartText.value.trim()) {
    throw new Error("请先输入需要识别的长文字内容。");
  }
  setStatus("正在识别长文字中的股票代码、日期和买卖规则。大批量文本会按日期块逐组处理，请稍等...");
  const payload = await api("/api/v1/trades/uploads/manual/parse-text", {
    method: "POST",
    body: JSON.stringify({
      text: nodes.manualSmartText.value,
      market: nodes.manualMarket.value,
      adjustment_mode: nodes.manualAdjustment.value,
    }),
  });
  const items = payload.data.records || [];
  state.manualTrades.push(...items.map((item) => ({
    symbol: item.symbol,
    side: item.side,
    entry_time: item.entry_time,
    exit_time: item.exit_time,
    pnl: item.pnl,
    entry_price: item.entry_price,
    exit_price: item.exit_price,
    notes: item.notes || "来源：长文字智能识别",
  })));
  renderManualTrades();
  renderManualParseSummary(payload.data);
  syncReplayActionState();
  setStatus(payload.data.summary || "长文字智能识别完成，已加入手动记录。");
}

function renderManualParseSummary(result) {
  const groups = result.group_summaries || [];
  const aiReview = result.ai_review || {};
  const warningLines = (aiReview.warnings || []).map((item) => `- ${item}`);
  if (!groups.length) {
    nodes.manualParseSummary.textContent = [
      result.summary || "长文字智能识别完成，已加入手动记录。",
      aiReview.mode_label ? `解析方式：${aiReview.mode_label}` : "",
      ...warningLines,
    ]
      .filter(Boolean)
      .join("\n");
    return;
  }
  const lines = [
    result.summary || "长文字智能识别完成。",
    aiReview.mode_label ? `解析方式：${aiReview.mode_label}` : "",
    `共识别 ${result.group_count || groups.length} 个日期块，加入 ${result.record_count || 0} 笔记录。`,
    "",
    ...groups.map(
      (group, index) =>
        `${index + 1}. ${group.trade_date} · ${group.record_count} 笔\n` +
        `买入规则：${group.entry_rule}\n` +
        `卖出规则：${group.exit_rule}\n` +
        `标的：${(group.symbols || []).join("、")}`,
    ),
    ...(warningLines.length ? ["", "需要你重点确认：", ...warningLines] : []),
  ];
  nodes.manualParseSummary.textContent = lines.join("\n");
}

function renderRecords(items) {
  nodes.recordsBody.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <tr>
              <td>${item.symbol}</td>
              <td>${item.side}</td>
              <td>${item.entry_time.slice(0, 10)}</td>
              <td>${item.exit_time ? item.exit_time.slice(0, 10) : "-"}</td>
              <td class="${item.pnl >= 0 ? "positive" : "negative"}">${item.pnl}</td>
            </tr>
          `,
        )
        .join("")
    : '<tr><td colspan="5" class="empty-state">暂无解析结果。</td></tr>';
}

function renderManualTrades() {
  nodes.manualList.innerHTML = state.manualTrades.length
    ? state.manualTrades
        .map(
          (item, index) => `
            <div class="list-item compact-item">
              <strong>${item.symbol} · ${item.side === "short" ? "反向 / 做空" : "买入后卖出 / 做多"}</strong>
              <div class="muted-note">买入 ${item.entry_time.slice(0, 16).replace("T", " ")} · 卖出 ${item.exit_time ? item.exit_time.slice(0, 16).replace("T", " ") : "未填写"}</div>
              <div class="muted-note">买入价 ${item.entry_price ?? "-"} · 卖出价 ${item.exit_price ?? "-"} · 盈亏 ${item.pnl}</div>
              <div class="muted-note">${item.notes || "无补充说明"}</div>
              <button class="btn ghost manual-remove-btn" type="button" data-manual-index="${index}">删除</button>
            </div>
          `,
        )
        .join("")
    : "尚未加入手动记录。";
  nodes.manualList.querySelectorAll("[data-manual-index]").forEach((node) => {
    node.addEventListener("click", () => {
      state.manualTrades.splice(Number(node.dataset.manualIndex), 1);
      renderManualTrades();
      syncReplayActionState();
    });
  });
}

function addManualTrade() {
  if (!nodes.manualSymbol.value.trim()) {
    throw new Error("请先填写标的代码。");
  }
  if (!nodes.manualEntry.value) {
    throw new Error("请先填写买入日期时间。");
  }
  state.manualTrades.push({
    symbol: nodes.manualSymbol.value.trim(),
    side: nodes.manualSide.value,
    entry_time: toIsoTimestamp(nodes.manualEntry.value),
    exit_time: nodes.manualExit.value ? toIsoTimestamp(nodes.manualExit.value) : null,
    pnl: Number(nodes.manualPnl.value || 0),
    notes: nodes.manualNotes.value.trim(),
  });
  nodes.manualSymbol.value = "";
  nodes.manualEntry.value = "";
  nodes.manualExit.value = "";
  nodes.manualPnl.value = "0";
  nodes.manualNotes.value = "";
  renderManualTrades();
  syncReplayActionState();
  setStatus("手动记录已加入列表，可继续补录或直接提交。");
}

async function runReplay() {
  if (!state.uploadId) {
    throw new Error("请先上传并解析交割单。");
  }
  syncReplayActionState({ replayBusy: true });
  setStatus("正在运行 AI 复盘...");
  const created = await api("/api/v1/replays/analyses", {
    method: "POST",
    body: JSON.stringify({
      upload_id: state.uploadId,
      focus_dimensions: ["side_performance", "holding_time"],
      custom_prompt: "结合中国股票和 ETF 交易特性总结问题",
      analysis_options: {
        lookback_days: Number(nodes.replayLookbackDays.value || 5),
        minute_window_minutes: Number(nodes.replayMinuteWindow.value || 60),
        include_market_context: nodes.includeMarketContext.checked,
        auto_market_context: nodes.autoMarketContext.checked,
        include_minute_features: nodes.includeMinuteFeatures.checked,
        include_fundamentals: nodes.includeFundamentals.checked,
      },
    }),
  });
  const result = await pollTask(created.data.status_url);
  state.objectiveVersions = result.objective_versions || [];
  const defaultObjective =
    state.objectiveVersions.find((item) => item.is_default)?.objective || "sharpe_max";
  state.selectedObjective = defaultObjective;
  nodes.summary.textContent = result.concise_summary || result.summary || "暂无总结。";
  renderReplayOverview(result.overview || {});
  renderReplayFeatureList(nodes.lossFeatures, result.loss_features || [], "尚未提取亏损特征。");
  renderReplayFeatureList(nodes.profitFeatures, result.profit_features || [], "尚未提取盈利特征。");
  renderReplayObjectiveTabs();
  renderReplayObjectiveDetail();
  renderReplayCounterfactualCases(
    result.counterfactual_cases || [],
    result.counterfactual_template_summary || [],
  );
  renderReplayParameterChanges(result.parameter_changes || []);
  renderReplayConditionReplacements(result.condition_replacements || []);
  renderReplayRules(result.suggestion_rules || []);
  renderReplayTradeRecords(result.trade_records || []);
  syncReplayActionState();
  setStatus("AI 复盘完成。");
}

function renderReplayOverview(overview) {
  const scope = overview.analysis_scope || {};
  const items = [
    ["样本交易数", overview.trade_count],
    ["胜率", overview.win_rate_pct != null ? `${overview.win_rate_pct}%` : "-"],
    ["总盈亏", overview.total_pnl != null ? overview.total_pnl : "-"],
    ["平均盈利", overview.avg_win != null ? overview.avg_win : "-"],
    ["平均亏损", overview.avg_loss != null ? overview.avg_loss : "-"],
    ["默认目标", overview.default_objective_label || "-"],
    ["分析维度", (scope.labels || []).join(" / ") || "-"],
    ["日线回看窗口", scope.lookback_days ? `前 ${scope.lookback_days} 个交易日` : "-"],
    ["分钟级观察窗口", scope.minute_window_minutes ? `前 ${scope.minute_window_minutes} 分钟` : "-"],
    ["分钟级特征状态", replayAnalysisStatusLabel(scope.minute_feature_status)],
    ["基本面复盘状态", replayAnalysisStatusLabel(scope.fundamental_status)],
  ];
  nodes.overview.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="list-item compact-item">
          <strong>${label}</strong>
          <div class="muted-note">${value ?? "-"}</div>
        </div>
      `,
    )
    .join("");
}

function replayAnalysisStatusLabel(value) {
  if (value === "pending") {
    return "已开启，等待接入真实数据";
  }
  if (value === "ready") {
    return "已接入";
  }
  if (value === "unavailable") {
    return "当前无真实数据可用";
  }
  if (value === "disabled") {
    return "未开启";
  }
  return value || "-";
}

function renderReplayFeatureList(container, items, emptyText) {
  container.innerHTML = items.length
    ? items
        .map(
          (item, index) => `
            <div class="list-item compact-item">
              <strong>Top ${index + 1} · ${item.title}</strong>
              <div class="muted-note">${item.detail || "无说明"}</div>
              <div class="muted-note">命中 / 支持度：${formatPercent(item.support)}</div>
            </div>
          `,
        )
        .join("")
    : emptyText;
}

function renderReplayObjectiveTabs() {
  nodes.objectiveTabs.innerHTML = state.objectiveVersions.length
    ? state.objectiveVersions
        .map(
          (item) => `
            <button
              class="btn ${item.objective === state.selectedObjective ? "secondary active" : "ghost"} replay-objective-btn"
              type="button"
              data-objective="${item.objective}"
            >
              ${item.label}
            </button>
          `,
        )
        .join("")
    : "";
  nodes.objectiveTabs.querySelectorAll("[data-objective]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedObjective = node.dataset.objective;
      renderReplayObjectiveTabs();
      renderReplayObjectiveDetail();
    });
  });
}

function renderReplayObjectiveDetail() {
  if (!state.objectiveVersions.length) {
    nodes.objectiveDetail.innerHTML = "尚未生成优化目标版本。";
    return;
  }
  const current =
    state.objectiveVersions.find((item) => item.objective === state.selectedObjective) ||
    state.objectiveVersions[0];
  const curvePoints = current.equity_curve || [];
  const maxEquity = curvePoints.reduce(
    (acc, item) => Math.max(acc, Number(item.equity || 0)),
    0,
  );
  const minEquity = curvePoints.reduce(
    (acc, item) => Math.min(acc, Number(item.equity || 0)),
    0,
  );
  const range = Math.max(maxEquity - minEquity, 1);
  const polyline = curvePoints
    .map((item, index) => {
      const x = curvePoints.length > 1 ? (index / (curvePoints.length - 1)) * 100 : 0;
      const y = 100 - ((Number(item.equity || 0) - minEquity) / range) * 100;
      return `${x},${y}`;
    })
    .join(" ");
  nodes.objectiveDetail.innerHTML = `
    <div class="list-item">
      <strong>${current.label}</strong>
      <div class="muted-note">${current.summary || "暂无说明"}</div>
      <div class="muted-note">${current.comparison_note || ""}</div>
      <div class="muted-note" style="margin-top:8px;">核心调整：${(current.key_adjustments || []).join("；") || "暂无"}</div>
      ${renderReplayObjectiveMetrics(current.metrics || {}, current.baseline_metrics || {})}
      ${renderReplayParameterStability(current.search_summary?.parameter_stability || {})}
      ${renderReplayObjectiveCounterfactual(current.objective_counterfactual || {})}
      ${renderReplayTradeSetChanges(current.trade_set_changes || {})}
      <div class="result-box light" style="margin-top:12px;">
        <strong>收益曲线</strong>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:100%;height:140px;display:block;margin-top:10px;">
          <polyline fill="none" stroke="#0f766e" stroke-width="2.5" points="${polyline}" />
        </svg>
      </div>
      <div class="table-wrap" style="margin-top:12px;">
        <table>
          <thead>
            <tr>
              <th>标的</th>
              <th>买入时间</th>
              <th>卖出时间</th>
              <th>买入价</th>
              <th>卖出价</th>
              <th>持仓时长</th>
              <th>盈亏比例</th>
            </tr>
          </thead>
          <tbody>
            ${renderReplayTradeRows(current.trade_records || [])}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderReplayObjectiveCounterfactual(summary) {
  if (!summary || Object.keys(summary).length === 0) {
    return "";
  }
  const focusedCases = summary.focused_cases || summary.cases || [];
  const allCases = summary.cases || [];
  const extraCaseCount = Math.max((summary.total_case_count || allCases.length) - focusedCases.length, 0);
  const searchLinked = summary.search_linked_summary || {};
  const searchLinkedCases = searchLinked.focused_cases || [];
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>这套版本对 Top 亏损单的影响</strong>
      <div class="muted-note" style="margin-top:6px;">${summary.summary || "暂无说明"}</div>
      <div class="muted-note">
        对照 ${summary.considered_count ?? 0} 笔 · 改善 ${summary.improved_count ?? 0} 笔 ·
        过滤 ${summary.skipped_count ?? 0} 笔 · 变差 ${summary.worsened_count ?? 0} 笔
      </div>
      ${
        focusedCases.length
          ? `
            <div class="list" style="margin-top:12px;">
              ${focusedCases
                .map(
                  (item) => `
                    <div class="list-item compact-item">
                      <strong>${item.symbol}</strong>
                      <div class="muted-note">${item.summary || "暂无说明"}</div>
                      <div class="muted-note">
                        原始盈亏 ${item.original_pnl} · 反事实盈亏 ${item.counterfactual_pnl} · 变化 ${formatSignedValue(item.pnl_delta)}
                      </div>
                    </div>
                  `,
                )
                .join("")}
            </div>
          `
          : ""
      }
      ${
        extraCaseCount > 0
          ? `
            <details class="result-box light" style="margin-top:12px;">
              <summary>查看全部逐笔反事实明细（另有 ${extraCaseCount} 笔）</summary>
              <div class="list" style="margin-top:12px; max-height: 320px; overflow: auto;">
                ${allCases
                  .map(
                    (item) => `
                      <div class="list-item compact-item">
                        <strong>${item.symbol}</strong>
                        <div class="muted-note">${item.summary || "暂无说明"}</div>
                        <div class="muted-note">
                          原始盈亏 ${item.original_pnl} · 反事实盈亏 ${item.counterfactual_pnl} · 变化 ${formatSignedValue(item.pnl_delta)}
                        </div>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </details>
          `
          : ""
      }
      ${
        searchLinkedCases.length
          ? `
            <div class="result-box light" style="margin-top:12px;">
              <strong>全样本亏损单的参数候选联动</strong>
              <div class="muted-note" style="margin-top:6px;">${searchLinked.summary || "暂无说明"}</div>
              <div class="muted-note">
                对照 ${searchLinked.considered_count ?? 0} 笔 · 改善 ${searchLinked.improved_count ?? 0} 笔 ·
                过滤 ${searchLinked.skipped_count ?? 0} 笔 · 变差 ${searchLinked.worsened_count ?? 0} 笔
              </div>
              <div class="muted-note">
                平均每笔扫描候选 ${searchLinked.candidate_scan_coverage?.candidate_count_per_trade_avg ?? 0} 个 ·
                当前扫描候选 ${searchLinked.candidate_scan_coverage?.focused_candidate_count ?? 0} 个版本 ·
                候选池总量 ${searchLinked.candidate_scan_coverage?.total_candidate_pool_count ?? 0} 个版本
              </div>
              ${
                (searchLinked.winning_candidate_summary || []).length
                  ? `
                    <div class="result-box light" style="margin-top:12px;">
                      <strong>全样本赢家候选摘要</strong>
                      <div class="list" style="margin-top:10px;">
                        ${searchLinked.winning_candidate_summary
                          .map(
                            (item) => `
                              <div class="list-item compact-item">
                                <strong>${item.candidate_label}</strong>
                                <div class="muted-note">命中 ${item.hit_count} 笔 · 覆盖率 ${(item.coverage_ratio ?? 0) * 100}% · 改善 ${item.improved_count} 笔 · 过滤 ${item.skipped_count} 笔 · 变差 ${item.worsened_count} 笔</div>
                                <div class="muted-note">平均盈亏变化 ${formatSignedValue(item.avg_pnl_delta)} · 关键参数 ${((item.parameter_focus || []).map((entry) => `${entry.parameter}（${entry.count}次）`).join("；")) || "暂无"}</div>
                                <div class="muted-note">主要胜出环境 ${((item.dominant_regimes || []).map((entry) => `${formatReplayRegime(entry.regime)}（${entry.count}次）`).join("；")) || "暂无"}</div>
                              </div>
                            `,
                          )
                          .join("")}
                      </div>
                    </div>
                  `
                  : ""
              }
              ${
                (searchLinked.regime_attribution || []).length
                  ? `
                    <div class="result-box light" style="margin-top:12px;">
                      <strong>市场状态归因</strong>
                      <div class="list" style="margin-top:10px;">
                        ${searchLinked.regime_attribution
                          .map(
                            (item) => `
                              <div class="list-item compact-item">
                                <strong>${formatReplayRegime(item.regime)}</strong>
                                <div class="muted-note">命中 ${item.hit_count} 笔 · 覆盖率 ${(item.coverage_ratio ?? 0) * 100}% · 改善 ${item.improved_count} 笔 · 过滤 ${item.skipped_count} 笔 · 变差 ${item.worsened_count} 笔</div>
                                <div class="muted-note">平均盈亏变化 ${formatSignedValue(item.avg_pnl_delta)}</div>
                              </div>
                            `,
                          )
                          .join("")}
                      </div>
                    </div>
                  `
                  : ""
              }
              ${
                searchLinked.candidate_decisiveness?.summary
                  ? `
                    <div class="result-box light" style="margin-top:12px;">
                      <strong>候选胜出稳健度</strong>
                      <div class="muted-note" style="margin-top:6px;">${searchLinked.candidate_decisiveness.summary}</div>
                      <div class="muted-note">
                        平均胜出差值 ${formatSignedValue(searchLinked.candidate_decisiveness.avg_gap ?? 0)} ·
                        险胜 ${searchLinked.candidate_decisiveness.narrow_win_count ?? 0} 笔（${((searchLinked.candidate_decisiveness.narrow_win_ratio ?? 0) * 100).toFixed(0)}%） ·
                        明显胜出 ${searchLinked.candidate_decisiveness.clear_win_count ?? 0} 笔（${((searchLinked.candidate_decisiveness.clear_win_ratio ?? 0) * 100).toFixed(0)}%）
                      </div>
                    </div>
                  `
                  : ""
              }
              ${
                (searchLinked.parameter_attribution || []).length
                  ? `
                    <div class="result-box light" style="margin-top:12px;">
                      <strong>全样本参数归因摘要</strong>
                      <div class="list" style="margin-top:10px;">
                        ${searchLinked.parameter_attribution
                          .map(
                            (item) => `
                              <div class="list-item compact-item">
                                <strong>${item.parameter}</strong>
                                <div class="muted-note">命中 ${item.hit_count} 笔 · 改善 ${item.improved_count} 笔 · 过滤 ${item.skipped_count} 笔 · 变差 ${item.worsened_count} 笔</div>
                                <div class="muted-note">平均盈亏变化 ${formatSignedValue(item.avg_pnl_delta)} · 常见取值 ${((item.top_values || []).map((value) => `${value.value}（${value.count}次）`).join("；")) || "暂无"}</div>
                              </div>
                            `,
                          )
                          .join("")}
                      </div>
                    </div>
                  `
                  : ""
              }
              <div class="list" style="margin-top:10px;">
                ${searchLinkedCases
                  .map(
                    (item) => `
                      <div class="list-item compact-item">
                        <strong>${item.symbol}</strong>
                        <div class="muted-note">${item.candidate_label} · 评分 ${item.candidate_score ?? "-"}</div>
                        <div class="muted-note">${item.summary || "暂无说明"}</div>
                        <div class="muted-note">原始盈亏 ${item.original_pnl} · 候选结果 ${item.counterfactual_pnl} · 变化 ${formatSignedValue(item.pnl_delta)}</div>
                        <div class="muted-note">关键参数：${renderReplayPatchFocus(item.focus || {})}</div>
                        ${
                          (item.candidate_options || []).length
                            ? `
                              <details style="margin-top:8px;">
                                <summary>查看这笔交易的候选版本对比</summary>
                                <div class="list" style="margin-top:10px;">
                                  ${item.candidate_options
                                    .map(
                                      (option) => `
                                        <div class="list-item compact-item">
                                          <strong>${option.candidate_label}</strong>
                                          <div class="muted-note">评分 ${option.candidate_score ?? "-"} · 结果 ${option.result_type === "skipped" ? "不成交 / 被过滤" : "真实重放"}</div>
                                          <div class="muted-note">候选结果 ${option.counterfactual_pnl} · 变化 ${formatSignedValue(option.pnl_delta)}</div>
                                          <div class="muted-note">关键参数：${renderReplayPatchFocus(option.focus || {})}</div>
                                        </div>
                                      `,
                                    )
                                    .join("")}
                                </div>
                              </details>
                            `
                            : ""
                        }
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </div>
          `
          : ""
      }
    </div>
  `;
}

function formatReplayRegime(value) {
  if (value === "trend") {
    return "趋势环境";
  }
  if (value === "range") {
    return "震荡环境";
  }
  if (value === "unknown") {
    return "环境未识别";
  }
  return value || "环境未识别";
}

function renderReplayParameterStability(stability) {
  if (!stability || Object.keys(stability).length === 0) {
    return "";
  }
  const topCandidates = stability.top_candidates || [];
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>参数稳定性</strong>
      <div class="muted-note" style="margin-top:6px;">${stability.label || "暂无稳定性结论"}</div>
      <div class="muted-note">${stability.summary || ""}</div>
      <div class="muted-note">接近当前最优的候选版本：${stability.near_best_count ?? 0} 组</div>
      ${renderReplayNeighborCandidates(stability.neighbor_candidates || [])}
      ${renderReplayNeighborBands(stability.neighbor_bands || [])}
      ${renderReplayParameterSensitivity(stability.sensitivity_axes || [])}
      ${renderReplayParameterHeatmaps(stability.heatmap_axes || [])}
      ${renderReplayParameterPairHeatmaps(stability.heatmap_pairs || [])}
      ${
        topCandidates.length
          ? `
            <div class="list" style="margin-top:12px;">
              ${topCandidates
                .map(
                  (item, index) => `
                    <div class="list-item compact-item">
                      <strong>候选 ${index + 1}</strong>
                      <div class="muted-note">评分 ${item.score} · 交易数 ${item.trade_count} · 胜率 ${item.win_rate_pct}% · 回撤 ${item.max_drawdown_pct}% · 夏普近似 ${item.sharpe_like}</div>
                      <div class="muted-note">关键参数：${renderReplayPatchFocus(item.focus || {})}</div>
                    </div>
                  `,
                )
                .join("")}
            </div>
          `
          : ""
      }
      ${renderReplayRollingWindows(stability.rolling_windows || [], "滚动窗口稳定性")}
      ${renderReplayRollingWindows(stability.market_regime_windows || [], "市场状态稳定性")}
    </div>
  `;
}

function renderReplayParameterPairHeatmaps(items) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>二维参数热力图</strong>
      ${items
        .map(
          (item) => `
            <div class="muted-note" style="margin-top:8px;">纵轴 ${item.y_label} · 横轴 ${item.x_label}</div>
            <div style="overflow:auto; margin-top:10px;">
              <table>
                <thead>
                  <tr>
                    <th>${item.y_label} \\ ${item.x_label}</th>
                    ${(item.x_values || []).map((value) => `<th>${value}</th>`).join("")}
                  </tr>
                </thead>
                <tbody>
                  ${(item.matrix || [])
                    .map(
                      (row) => `
                        <tr>
                          <th>${row.y_value}</th>
                          ${(row.cells || [])
                            .map((cell) => {
                              if (cell.avg_score == null) {
                                return `<td>-</td>`;
                              }
                              const alpha = 0.12 + Math.max(0, Math.min(1, Number(cell.intensity || 0))) * 0.48;
                              return `<td style="background:rgba(15,118,110,${alpha});">${cell.avg_score}<br><span style="font-size:11px;color:#4b5563;">n=${cell.count}</span></td>`;
                            })
                            .join("")}
                        </tr>
                      `,
                    )
                    .join("")}
                </tbody>
              </table>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderReplayNeighborCandidates(items) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>邻域候选对照</strong>
      <div class="list" style="margin-top:10px;">
        ${items
          .map(
            (item, index) => `
              <div class="list-item compact-item">
                <strong>邻域 ${index + 1}</strong>
                <div class="muted-note">评分 ${item.score} · 与最优差值 ${formatSignedValue(item.score_delta)} · 交易数 ${item.trade_count}</div>
                <div class="muted-note">胜率 ${item.win_rate_pct}% · 回撤 ${item.max_drawdown_pct}% · 夏普近似 ${item.sharpe_like}</div>
                <div class="muted-note">关键参数：${renderReplayPatchFocus(item.focus || {})}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderReplayNeighborBands(items) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>邻域敏感性分层</strong>
      <div class="grid-3" style="margin-top:10px;">
        ${items
          .map(
            (item) => `
              <div class="result-box light">
                <strong>${item.label}</strong>
                <div class="muted-note" style="margin-top:6px;">候选数 ${item.count}</div>
                <div class="muted-note">平均分差 ${formatSignedValue(item.avg_score_delta)}</div>
                <div class="muted-note">最佳分差 ${formatSignedValue(item.best_score_delta)} · 最弱分差 ${formatSignedValue(item.worst_score_delta)}</div>
                <div class="muted-note">平均交易数 ${item.avg_trade_count}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderReplayParameterSensitivity(items) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>参数敏感性</strong>
      <div class="list" style="margin-top:10px;">
        ${items
          .map(
            (item) => `
              <div class="list-item compact-item">
                <strong>${item.label}</strong>
                <div class="muted-note">最优值 ${item.best_value} · 分差 ${item.score_spread} · ${item.sensitivity}</div>
                <div class="muted-note">
                  ${((item.values || [])
                    .map((value) => `${value.value}（均分 ${value.avg_score}，样本 ${value.count}）`)
                    .join("；")) || "暂无参数分层摘要"}
                </div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderReplayParameterHeatmaps(items) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>参数热力图摘要</strong>
      <div class="list" style="margin-top:10px;">
        ${items
          .map(
            (item) => `
              <div class="list-item compact-item">
                <strong>${item.label}</strong>
                <div class="muted-note">最优值 ${item.best_value}</div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
                  ${(item.values || [])
                    .map((value) => {
                      const alpha = 0.18 + Math.max(0, Math.min(1, Number(value.intensity || 0))) * 0.42;
                      return `
                        <span style="padding:6px 10px;border-radius:999px;background:rgba(15,118,110,${alpha});color:#083344;font-size:12px;">
                          ${value.value} · ${value.avg_score}
                        </span>
                      `;
                    })
                    .join("")}
                </div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderReplayPatchFocus(focus) {
  const entries = Object.entries(focus || {});
  if (!entries.length) {
    return "暂无关键参数摘要";
  }
  return entries.map(([key, value]) => `${key}=${value}`).join("；");
}

function renderReplayRollingWindows(items, title) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>${title}</strong>
      <div class="list" style="margin-top:10px;">
        ${items
          .map(
            (item) => `
              <div class="list-item compact-item">
                <strong>${item.label}</strong>
                <div class="muted-note">${item.date_range ? `${item.date_range} · ` : ""}交易数 ${item.trade_count}</div>
                <div class="muted-note">胜率 ${item.win_rate_pct}% · 回撤 ${item.max_drawdown_pct}% · 夏普近似 ${item.sharpe_like}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderReplayTradeSetChanges(changes) {
  if (!changes || Object.keys(changes).length === 0) {
    return "";
  }
  const style = changes.style_exposure || {};
  const removedLosses = changes.removed_losses || [];
  const removedProfits = changes.removed_profits || [];
  return `
    <div class="result-box light" style="margin-top:12px;">
      <strong>交易集合变化分析</strong>
      <div class="muted-note" style="margin-top:6px;">${changes.summary || "暂无变化说明"}</div>
      <div class="grid-2" style="margin-top:12px;">
        <div class="result-box light">
          <strong>交易频率变化</strong>
          <div class="muted-note" style="margin-top:6px;">原样本：${changes.baseline_trade_count ?? 0} 笔</div>
          <div class="muted-note">当前版本：${changes.current_trade_count ?? 0} 笔</div>
          <div class="muted-note">变化：${formatSignedInteger(changes.trade_frequency_delta)}</div>
        </div>
        <div class="result-box light">
          <strong>风格暴露变化</strong>
          <div class="muted-note" style="margin-top:6px;">平均持仓：${style.baseline_avg_holding_minutes ?? 0} 分钟 → ${style.current_avg_holding_minutes ?? 0} 分钟</div>
          <div class="muted-note">做多占比：${style.baseline_long_share_pct ?? 0}% → ${style.current_long_share_pct ?? 0}%</div>
        </div>
      </div>
      <div class="grid-2" style="margin-top:12px;">
        <div class="result-box light">
          <strong>被过滤掉的亏损单</strong>
          <div class="muted-note" style="margin-top:6px;">共 ${changes.removed_loss_count ?? 0} 笔，默认展示前 5 笔</div>
          ${renderReplayTradeSetChangeList(removedLosses, "当前没有被过滤掉的亏损单。")}
        </div>
        <div class="result-box light">
          <strong>被错杀的盈利单</strong>
          <div class="muted-note" style="margin-top:6px;">共 ${changes.removed_profit_count ?? 0} 笔，默认展示前 5 笔</div>
          ${renderReplayTradeSetChangeList(removedProfits, "当前没有被错杀的盈利单。")}
        </div>
      </div>
      <div class="muted-note" style="margin-top:12px;">
        ${(changes.limitations || []).join(" ")}
      </div>
    </div>
  `;
}

function renderReplayTradeSetChangeList(items, emptyText) {
  return items.length
    ? `
      <div class="list" style="margin-top:10px;">
        ${items
          .map(
            (item) => `
              <div class="list-item compact-item">
                <strong>${item.symbol}</strong>
                <div class="muted-note">${formatTime(item.entry_time)} → ${formatTime(item.exit_time)}</div>
                <div class="muted-note">
                  持仓 ${item.holding_label || "-"} · 盈亏 ${item.pnl_pct != null ? `${item.pnl_pct}%` : "-"}
                </div>
              </div>
            `,
          )
          .join("")}
      </div>
    `
    : `<div class="muted-note" style="margin-top:10px;">${emptyText}</div>`;
}

function renderReplayObjectiveMetrics(metrics, baselineMetrics) {
  const items = [
    ["交易数", metrics.trade_count, baselineMetrics.trade_count],
    ["总盈亏", metrics.total_pnl, baselineMetrics.total_pnl],
    ["胜率", metrics.win_rate_pct != null ? `${metrics.win_rate_pct}%` : "-", baselineMetrics.win_rate_pct != null ? `${baselineMetrics.win_rate_pct}%` : "-"],
    ["样本回撤", metrics.max_drawdown_pct != null ? `${metrics.max_drawdown_pct}%` : "-", baselineMetrics.max_drawdown_pct != null ? `${baselineMetrics.max_drawdown_pct}%` : "-"],
    ["样本夏普近似", metrics.sharpe_like ?? "-", baselineMetrics.sharpe_like ?? "-"],
  ];
  return `
    <div class="grid-2" style="margin-top:12px;">
      ${items
        .map(
          ([label, value, baseline]) => `
            <div class="result-box light">
              <strong>${label}</strong>
              <div class="muted-note" style="margin-top:6px;">当前版本：${value ?? "-"}</div>
              <div class="muted-note">原样本：${baseline ?? "-"}</div>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderReplayParameterChanges(items) {
  nodes.parameterChanges.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <div class="list-item compact-item">
              <strong>${item.parameter}</strong>
              <div class="muted-note">旧值：${item.old_value} → 新值：${item.new_value}</div>
              <div class="muted-note">${item.reason || "无说明"}</div>
            </div>
          `,
        )
        .join("")
    : "尚未生成参数改动列表。";
}

function renderReplayCounterfactualCases(items, templateSummary) {
  const summaryHtml = templateSummary?.length
    ? `
      <div class="result-box light" style="margin-bottom:12px;">
        <strong>反事实模板命中摘要</strong>
        <div class="list" style="margin-top:10px;">
          ${templateSummary
            .map(
              (item) => `
                <div class="list-item compact-item">
                  <strong>${item.title}</strong>
                  <div class="muted-note">样本 ${item.sample_count} · 改善 ${item.improved_count} · 过滤 ${item.skipped_count} · 变差 ${item.worsened_count}</div>
                  <div class="muted-note">被推荐为优先路径 ${item.best_choice_count} 次 · 平均盈亏变化 ${formatSignedValue(item.avg_pnl_improvement)}</div>
                  <div class="muted-note">关联参数：${renderReplayPatchFocus(item.focus || {})}</div>
                  <div class="muted-note">${item.attribution_summary || ""}</div>
                  ${
                    (item.linked_axes || []).length
                      ? `<div class="muted-note">关联热力图轴：${item.linked_axes
                          .map((axis) => `${axis.label}（最优值 ${axis.best_value}${axis.in_pair_heatmap ? "，已进入二维热力图" : ""}）`)
                          .join("；")}</div>`
                      : ""
                  }
                </div>
              `,
            )
            .join("")}
        </div>
      </div>
    `
    : "";
  nodes.counterfactualCases.innerHTML =
    summaryHtml +
    (items.length
      ? items
          .map(
          (item) => `
            <details class="list-item">
              <summary>
                <strong>Top ${item.rank} · ${item.symbol}</strong>
                <span class="muted-note" style="margin-left:8px;">${item.summary || ""}</span>
              </summary>
              <div class="result-box light" style="margin-top:12px;">
                <strong>原始路径</strong>
                <div class="muted-note" style="margin-top:6px;">
                  买入 ${formatTime(item.original_trade?.entry_time)} · 卖出 ${formatTime(item.original_trade?.exit_time)}
                </div>
                <div class="muted-note">
                  买入价 ${item.original_trade?.entry_price ?? "-"} · 卖出价 ${item.original_trade?.exit_price ?? "-"} ·
                  持仓 ${item.original_trade?.holding_label || "-"} ·
                  盈亏 ${item.original_trade?.pnl_pct != null ? `${item.original_trade?.pnl_pct}%` : "-"}
                </div>
              </div>
              <div class="list" style="margin-top:12px;">
                ${(item.alternatives || [])
                  .map(
                    (alternative) => `
                      <div class="list-item compact-item">
                        <strong>${alternative.title}</strong>
                        <div class="muted-note">${alternative.summary || "无说明"}</div>
                        <div class="muted-note">
                          结果：${alternative.result_type === "skipped" ? "不成交 / 被过滤" : "真实重放"}
                          · 盈亏变化 ${formatSignedValue(alternative.comparison?.pnl_delta)}
                        </div>
                        ${
                          alternative.trade_record
                            ? `
                              <div class="muted-note">
                                买入 ${formatTime(alternative.trade_record.entry_time)} · 卖出 ${formatTime(alternative.trade_record.exit_time)}
                              </div>
                              <div class="muted-note">
                                买入价 ${alternative.trade_record.entry_price ?? "-"} · 卖出价 ${alternative.trade_record.exit_price ?? "-"} ·
                                持仓 ${alternative.trade_record.holding_label || "-"} ·
                                盈亏 ${alternative.trade_record.pnl_pct != null ? `${alternative.trade_record.pnl_pct}%` : "-"}
                              </div>
                            `
                            : `<div class="muted-note">这条替代路径会直接过滤掉这笔交易。</div>`
                        }
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </details>
          `,
          )
          .join("")
      : "尚未生成单笔反事实复盘。");
}

function renderReplayConditionReplacements(items) {
  nodes.conditionReplacements.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <div class="list-item compact-item">
              <strong>${item.reason || "条件替换"}</strong>
              <div class="muted-note">原条件：${item.from}</div>
              <div class="muted-note">推荐替换：${item.to}</div>
            </div>
          `,
        )
        .join("")
    : "尚未生成条件替换建议。";
}

function renderReplayRules(items) {
  nodes.rules.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <div class="list-item">
              <strong>${item.title}</strong>
              <div class="muted-note">${item.description || "无描述"}</div>
              <pre class="result-box light" style="margin-top:12px">${JSON.stringify(item.dsl_patch, null, 2)}</pre>
            </div>
          `,
        )
        .join("")
    : "尚未生成建议规则。";
}

function renderReplayTradeRecords(items) {
  nodes.tradeRecords.innerHTML = items.length
    ? `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>标的</th>
              <th>买入时间</th>
              <th>卖出时间</th>
              <th>买入价</th>
              <th>卖出价</th>
              <th>持仓时长</th>
              <th>盈亏比例</th>
            </tr>
          </thead>
          <tbody>${renderReplayTradeRows(items)}</tbody>
        </table>
      </div>
    `
    : "尚未生成成交记录对照。";
}

function renderReplayTradeRows(items) {
  return items.length
    ? items
        .map(
          (item) => `
            <tr>
              <td>${item.symbol}</td>
              <td>${formatTime(item.entry_time)}</td>
              <td>${formatTime(item.exit_time)}</td>
              <td>${item.entry_price ?? "-"}</td>
              <td>${item.exit_price ?? "-"}</td>
              <td>${item.holding_label || "-"}</td>
              <td class="${Number(item.pnl || 0) >= 0 ? "positive" : "negative"}">${item.pnl_pct != null ? `${item.pnl_pct}%` : "-"}</td>
            </tr>
          `,
        )
        .join("")
    : '<tr><td colspan="7" class="empty-state">暂无成交记录。</td></tr>';
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  return value.replace("T", " ").replace("Z", "").slice(0, 16);
}

function formatPercent(value) {
  if (typeof value !== "number") {
    return "-";
  }
  return `${Math.round(value * 100)}%`;
}

function formatSignedValue(value) {
  if (typeof value !== "number") {
    return "-";
  }
  const normalized = Math.round(value * 100) / 100;
  return normalized > 0 ? `+${normalized}` : `${normalized}`;
}

function formatSignedInteger(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value > 0 ? `+${value}` : `${value}`;
}

function applySourceMode(mode) {
  state.sourceMode = mode;
  const modeMeta = SOURCE_MODE_META[mode] || SOURCE_MODE_META.csv;
  Object.entries(nodes.sourcePanels).forEach(([key, panel]) => {
    panel.hidden = key !== mode;
  });
  nodes.sourceModeTitle.textContent = modeMeta.title;
  nodes.sourceModeIntro.textContent = modeMeta.intro;
  nodes.sourceModeSteps.innerHTML = modeMeta.steps.map((item) => `<li>${item}</li>`).join("");
  nodes.sourceModeButtons.forEach((button) => {
    const isActive = button.id === `source-mode-${mode}`;
    button.classList.toggle("secondary", isActive);
    button.classList.toggle("ghost", !isActive);
    button.classList.toggle("active", isActive);
  });
}

function syncReplayActionState(options = {}) {
  const uploadBusy = Boolean(options.uploadBusy);
  const replayBusy = Boolean(options.replayBusy);
  const csvReady = Boolean(nodes.file.files[0] || nodes.csvText.value.trim());
  const screenshotReady = Boolean(
    nodes.screenshotFile.files[0] &&
      nodes.screenshotSymbol.value.trim() &&
      nodes.screenshotEntry.value,
  );
  const screenshotOcrReady = Boolean(nodes.screenshotFile.files[0]);
  const manualTextReady = Boolean(nodes.manualSmartText.value.trim());
  const manualDraftReady = Boolean(nodes.manualSymbol.value.trim() && nodes.manualEntry.value);
  const manualUploadReady = Boolean(state.manualTrades.length);

  nodes.addManualTradeButton.disabled = !manualDraftReady || uploadBusy;
  nodes.addManualTradeButton.className =
    manualDraftReady && !uploadBusy ? "btn primary" : "btn disabled";

  nodes.uploadButton.disabled = uploadBusy || !csvReady;
  nodes.uploadButton.className = csvReady && !uploadBusy ? "btn primary" : "btn disabled";
  nodes.uploadButton.textContent = uploadBusy ? "正在解析..." : "上传并解析";
  nodes.uploadButton.title = csvReady
    ? "当前 CSV 内容已准备好，可以上传并解析。"
    : "请先选择 CSV 文件或粘贴 CSV 文本。";

  nodes.uploadScreenshotButton.disabled = uploadBusy || !screenshotReady;
  nodes.uploadScreenshotButton.className =
    screenshotReady && !uploadBusy ? "btn primary" : "btn disabled";
  nodes.uploadScreenshotButton.textContent = uploadBusy ? "正在登记..." : "登记截图并生成记录";
  nodes.uploadScreenshotButton.title = screenshotReady
    ? "截图和关键字段已齐备，可以登记并生成记录。"
    : "请先补齐截图、标的代码和买入日期时间。";

  nodes.screenshotOcrButton.disabled = uploadBusy || !screenshotOcrReady;
  nodes.screenshotOcrButton.className =
    screenshotOcrReady && !uploadBusy ? "btn secondary" : "btn disabled";
  nodes.screenshotOcrButton.textContent = uploadBusy ? "正在识别..." : "智能识别截图内容";
  nodes.screenshotOcrButton.title = screenshotOcrReady
    ? "先用 OCR 读取截图里的日期、股票代码和方向，再人工确认。"
    : "请先上传一张成交截图。";

  nodes.uploadManualButton.disabled = uploadBusy || !manualUploadReady;
  nodes.uploadManualButton.className =
    manualUploadReady && !uploadBusy ? "btn primary" : "btn disabled";
  nodes.uploadManualButton.textContent = uploadBusy ? "正在提交..." : "提交手动记录";
  nodes.uploadManualButton.title = manualUploadReady
    ? "当前手动记录已准备好，可以提交并生成解析结果。"
    : "请先至少加入一笔手动记录。";

  nodes.parseManualTextButton.disabled = uploadBusy || !manualTextReady;
  nodes.parseManualTextButton.className =
    manualTextReady && !uploadBusy ? "btn primary" : "btn disabled";
  nodes.parseManualTextButton.textContent = uploadBusy ? "正在识别..." : "智能识别并加入记录";
  nodes.parseManualTextButton.title = manualTextReady
    ? "当前文字内容已准备好，可以识别日期、股票代码和买卖规则。"
    : "请先输入包含日期、股票代码或买卖规则的长文字。";

  const replayReady = state.replayReady && !uploadBusy;
  nodes.replayButton.disabled = !replayReady || replayBusy;
  nodes.replayButton.classList.toggle("primary", replayReady && !replayBusy);
  nodes.replayButton.classList.toggle("secondary", !replayReady && !replayBusy);
  nodes.replayButton.classList.toggle("disabled", !replayReady || replayBusy);
  nodes.replayButton.textContent = replayBusy ? "正在复盘..." : "运行 AI 复盘";
  nodes.replayButton.title = replayReady
    ? "交割单已解析完成，可以开始运行 AI 复盘。"
    : "请先上传并解析交割单，再运行 AI 复盘。";
}

function toIsoTimestamp(value) {
  return `${value}:00Z`.replace(" ", "T");
}

function toLocalInputValue(value) {
  if (!value) {
    return "";
  }
  return value.replace("Z", "").replace("+00:00", "").slice(0, 16);
}

document.querySelector("#upload-trades-btn").addEventListener(
  "click",
  handle(async () => {
    try {
      await uploadTrades();
    } finally {
      syncReplayActionState();
    }
  }),
);

document.querySelector("#upload-screenshot-btn").addEventListener(
  "click",
  handle(async () => {
    try {
      await uploadScreenshotTrade();
    } finally {
      syncReplayActionState();
    }
  }),
);

document.querySelector("#ocr-screenshot-btn").addEventListener(
  "click",
  handle(async () => {
    try {
      await recognizeScreenshotTrade();
    } finally {
      syncReplayActionState();
    }
  }),
);

document.querySelector("#upload-manual-btn").addEventListener(
  "click",
  handle(async () => {
    try {
      await uploadManualTrades();
    } finally {
      syncReplayActionState();
    }
  }),
);

document.querySelector("#add-manual-trade-btn").addEventListener("click", handle(addManualTrade));
document.querySelector("#parse-manual-text-btn").addEventListener(
  "click",
  handle(async () => {
    try {
      await parseManualText();
    } finally {
      syncReplayActionState();
    }
  }),
);

nodes.sourceModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applySourceMode(button.id.replace("source-mode-", ""));
    syncReplayActionState();
  });
});

[
  nodes.file,
  nodes.csvText,
  nodes.screenshotFile,
  nodes.screenshotMarket,
  nodes.screenshotSymbol,
  nodes.screenshotEntry,
  nodes.screenshotExit,
  nodes.screenshotPnl,
  nodes.screenshotNotes,
  nodes.manualSymbol,
  nodes.manualEntry,
  nodes.manualExit,
  nodes.manualPnl,
  nodes.manualNotes,
  nodes.manualSmartText,
].forEach((node) => {
  node.addEventListener("input", () => syncReplayActionState());
  node.addEventListener("change", () => syncReplayActionState());
});

document.querySelector("#run-replay-btn").addEventListener(
  "click",
  handle(async () => {
    try {
      await runReplay();
    } finally {
      syncReplayActionState();
    }
  }),
);
