import { activateNav, api, handle, pollTask, setStatus } from "/assets/shared.js";

activateNav("/replay");

const state = {
  uploadId: "",
  replayReady: false,
  sourceMode: "csv",
  manualTrades: [],
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
    intro: "适合没有交割单文件时，直接补录股票代码、买卖日期、方向和盈亏。可以连续录入多笔再一起复盘。",
    steps: [
      "先补一笔交易的标的、时间、方向和盈亏。",
      "点击加入手动记录，重复补录需要复盘的样本。",
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
  manualSymbol: document.querySelector("#trade-manual-symbol"),
  manualSide: document.querySelector("#trade-manual-side"),
  manualEntry: document.querySelector("#trade-manual-entry"),
  manualExit: document.querySelector("#trade-manual-exit"),
  manualPnl: document.querySelector("#trade-manual-pnl"),
  manualNotes: document.querySelector("#trade-manual-notes"),
  manualList: document.querySelector("#manual-trade-list"),
  uploadId: document.querySelector("#current-upload-id"),
  recordsBody: document.querySelector("#replay-records-body"),
  summary: document.querySelector("#replay-summary"),
  rules: document.querySelector("#replay-rules"),
  uploadButton: document.querySelector("#upload-trades-btn"),
  uploadScreenshotButton: document.querySelector("#upload-screenshot-btn"),
  uploadManualButton: document.querySelector("#upload-manual-btn"),
  addManualTradeButton: document.querySelector("#add-manual-trade-btn"),
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
      records: state.manualTrades.map(({ notes, ...item }) => item),
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
              <div class="muted-note">盈亏 ${item.pnl} · ${item.notes || "无补充说明"}</div>
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
    }),
  });
  const result = await pollTask(created.data.status_url);
  nodes.summary.textContent = result.summary || "暂无总结。";
  nodes.rules.innerHTML = (result.suggestion_rules || [])
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          <div class="muted-note">${item.description || "无描述"}</div>
          <pre class="result-box light" style="margin-top:12px">${JSON.stringify(item.dsl_patch, null, 2)}</pre>
        </div>
      `,
    )
    .join("");
  syncReplayActionState();
  setStatus("AI 复盘完成。");
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

  nodes.uploadManualButton.disabled = uploadBusy || !manualUploadReady;
  nodes.uploadManualButton.className =
    manualUploadReady && !uploadBusy ? "btn primary" : "btn disabled";
  nodes.uploadManualButton.textContent = uploadBusy ? "正在提交..." : "提交手动记录";
  nodes.uploadManualButton.title = manualUploadReady
    ? "当前手动记录已准备好，可以提交并生成解析结果。"
    : "请先至少加入一笔手动记录。";

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
