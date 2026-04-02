import { activateNav, api, handle, pollTask, setStatus } from "/assets/shared.js";

activateNav("/replay");

const state = {
  uploadId: "",
  replayReady: false,
  sourceMode: "csv",
  manualTrades: [],
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
  replayButton: document.querySelector("#run-replay-btn"),
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
  Object.entries(nodes.sourcePanels).forEach(([key, panel]) => {
    panel.hidden = key !== mode;
  });
  nodes.sourceModeButtons.forEach((button) => {
    const isActive = button.id === `source-mode-${mode}`;
    button.classList.toggle("secondary", isActive);
    button.classList.toggle("ghost", !isActive);
  });
  nodes.uploadButton.hidden = mode !== "csv";
  nodes.uploadScreenshotButton.hidden = mode !== "screenshot";
  nodes.uploadManualButton.hidden = mode !== "manual";
}

function syncReplayActionState(options = {}) {
  const uploadBusy = Boolean(options.uploadBusy);
  const replayBusy = Boolean(options.replayBusy);

  nodes.uploadButton.disabled = uploadBusy;
  nodes.uploadButton.textContent = uploadBusy ? "正在解析..." : "上传并解析";
  nodes.uploadScreenshotButton.disabled = uploadBusy;
  nodes.uploadScreenshotButton.textContent = uploadBusy ? "正在登记..." : "登记截图并生成记录";
  nodes.uploadManualButton.disabled = uploadBusy;
  nodes.uploadManualButton.textContent = uploadBusy ? "正在提交..." : "提交手动记录";

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
  });
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
