import { activateNav, api, handle, pollTask, setStatus } from "/assets/shared.js";

activateNav("/replay");

const state = {
  uploadId: "",
  replayReady: false,
};

const nodes = {
  file: document.querySelector("#trade-file"),
  csvText: document.querySelector("#trade-csv-text"),
  uploadId: document.querySelector("#current-upload-id"),
  recordsBody: document.querySelector("#replay-records-body"),
  summary: document.querySelector("#replay-summary"),
  rules: document.querySelector("#replay-rules"),
  uploadButton: document.querySelector("#upload-trades-btn"),
  replayButton: document.querySelector("#run-replay-btn"),
};

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

function syncReplayActionState(options = {}) {
  const uploadBusy = Boolean(options.uploadBusy);
  const replayBusy = Boolean(options.replayBusy);

  nodes.uploadButton.disabled = uploadBusy;
  nodes.uploadButton.textContent = uploadBusy ? "正在解析..." : "上传并解析";

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
