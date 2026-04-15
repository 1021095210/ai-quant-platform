import {
  activateNav,
  api,
  clearInlineStatus,
  fetchLlmProfiles,
  populateLlmProfileSelect,
  registerBackgroundTask,
  setStatus,
  setInlineStatus,
  subscribeBackgroundTasks,
} from "/assets/shared.js";

activateNav("/assistant");

const state = {
  workflows: [],
  selectedWorkflowId: "market_map",
  history: [],
  taskCenterItems: [],
};

const nodes = {
  workflows: document.querySelector("#assistant-workflows"),
  desks: document.querySelector("#assistant-desks"),
  selectedWorkflow: document.querySelector("#assistant-selected-workflow"),
  depth: document.querySelector("#assistant-depth"),
  market: document.querySelector("#assistant-market"),
  target: document.querySelector("#assistant-target"),
  llmProfile: document.querySelector("#assistant-llm-profile"),
  query: document.querySelector("#assistant-query"),
  runButton: document.querySelector("#assistant-run-btn"),
  summary: document.querySelector("#assistant-summary"),
  riskPanel: document.querySelector("#assistant-risk-panel"),
  conversation: document.querySelector("#assistant-conversation"),
  inlineStatus: document.querySelector("#assistant-inline-status"),
  followupStatus: document.querySelector("#assistant-followup-status"),
  followup: document.querySelector("#assistant-followup"),
  followupButton: document.querySelector("#assistant-followup-btn"),
  taskCenter: document.querySelector("#assistant-task-center"),
  refreshTasksButton: document.querySelector("#assistant-refresh-tasks-btn"),
};

const pendingResearchTasks = new Map();

function syncRunButtonState() {
  const canRun = Boolean(nodes.query.value.trim());
  nodes.runButton.disabled = !canRun;
  nodes.runButton.className = canRun ? "btn primary" : "btn disabled";
}

function syncFollowupButtonState() {
  const canFollowUp = state.history.length > 0 && Boolean(nodes.followup.value.trim());
  nodes.followupButton.disabled = !canFollowUp;
  nodes.followupButton.className = canFollowUp ? "btn primary" : "btn disabled";
}

function selectedWorkflow() {
  return state.workflows.find((item) => item.workflow_id === state.selectedWorkflowId) || state.workflows[0];
}

function updateSelectedWorkflowDisplay() {
  const workflow = selectedWorkflow();
  if (!workflow) {
    nodes.selectedWorkflow.textContent = "尚未选择，默认使用市场地图。";
    return;
  }
  nodes.selectedWorkflow.textContent = `${workflow.title} · ${workflow.best_for}`;
}

function renderWorkflows(items) {
  state.workflows = items;
  updateSelectedWorkflowDisplay();
  if (!items.length) {
    nodes.workflows.textContent = "暂无研究工作流。";
    return;
  }
  nodes.workflows.innerHTML = items
    .map(
      (item) => `
        <button class="mentor-topic-card assistant-workflow-card ${item.workflow_id === state.selectedWorkflowId ? "selected" : ""}" type="button" data-workflow-id="${item.workflow_id}">
          <span class="mentor-topic-kicker">研究模板</span>
          <strong>${item.title}</strong>
          <span>${item.summary}</span>
          <small>${item.best_for}</small>
        </button>
      `,
    )
    .join("");
  nodes.workflows.querySelectorAll("[data-workflow-id]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedWorkflowId = node.dataset.workflowId || "market_map";
      renderWorkflows(state.workflows);
      setStatus("已切换研究工作流，可以开始发起研究任务。");
    });
  });
}

function renderDesks(items) {
  if (!items.length) {
    nodes.desks.textContent = "暂无专家编组。";
    return;
  }
  nodes.desks.className = "assistant-desk-grid";
  nodes.desks.innerHTML = items
    .map(
      (item) => `
        <div class="assistant-desk-card">
          <strong>${item.title}</strong>
          <div class="muted-note">${item.focus}</div>
        </div>
      `,
    )
    .join("");
}

function renderConversation() {
  if (!state.history.length) {
    nodes.conversation.textContent = "先完成一次研究任务后，这里会保留你的任务和助手返回结果。";
    nodes.conversation.className = "mentor-conversation empty-state";
    return;
  }
  nodes.conversation.className = "mentor-conversation";
  nodes.conversation.innerHTML = state.history
    .map(
      (item) => `
        <div class="mentor-message ${item.role === "user" ? "user" : "assistant"}">
          <span class="mentor-message-role">${item.role === "user" ? "你" : "金融助手"}</span>
          <strong>${item.title}</strong>
          <div class="muted-note">${item.content}</div>
        </div>
      `,
    )
    .join("");
}

function formatTaskStatus(status) {
  if (status === "succeeded") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "running") {
    return "生成中";
  }
  if (status === "queued") {
    return "排队中";
  }
  if (status === "canceled") {
    return "已取消";
  }
  return status || "未知";
}

function renderTaskCenter() {
  if (!state.taskCenterItems.length) {
    nodes.taskCenter.textContent = "还没有后台研究任务。";
    nodes.taskCenter.className = "list empty-state";
    return;
  }
  nodes.taskCenter.className = "list";
  nodes.taskCenter.innerHTML = state.taskCenterItems
    .map(
      (item) => `
        <div class="list-item compact-item">
          <strong>${item.workflow_title || "研究任务"} · ${formatTaskStatus(item.status)}</strong>
          <div class="muted-note">${item.query || "未记录问题"}</div>
          <div class="muted-note">标的 ${item.target_symbol || "-"} · 市场 ${item.market_scope || "-"} · 结果来源 ${item.answer_source || "-"}${item.confidence_label ? ` · 研究置信度 ${item.confidence_label}` : ""}</div>
          <div class="muted-note">${item.summary || "结果生成后会在这里显示摘要。"} </div>
          <div class="actions" style="margin-top:10px;">
            <button class="btn ghost assistant-open-task-btn" type="button" data-task-id="${item.research_task_id}" ${item.status === "succeeded" ? "" : "disabled"}>打开结果</button>
          </div>
        </div>
      `,
    )
    .join("");
  nodes.taskCenter.querySelectorAll(".assistant-open-task-btn").forEach((node) => {
    node.addEventListener("click", async () => {
      const taskId = node.dataset.taskId;
      if (!taskId) {
        return;
      }
      try {
        const payload = await api(`/api/v1/assistant/research-tasks/${taskId}`);
        hydrateResearchResult(payload.data);
        setStatus("已重新打开后台研究结果。");
      } catch (error) {
        setStatus(error.message);
      }
    });
  });
}

function appendConversation(role, title, content) {
  state.history.push({ role, title, content });
  renderConversation();
  syncFollowupButtonState();
}

function hydrateResearchResult(payload) {
  if (payload.query) {
    nodes.query.value = payload.query;
  }
  if (payload.market_scope) {
    nodes.market.value = payload.market_scope;
  }
  if (payload.target_symbol) {
    nodes.target.value = payload.target_symbol;
  }
  if (payload.workflow_id) {
    state.selectedWorkflowId = payload.workflow_id;
    updateSelectedWorkflowDisplay();
    renderWorkflows(state.workflows);
  }
  state.history = [
    { role: "user", title: "研究任务", content: payload.query || "已加载历史研究任务" },
    { role: "assistant", title: "研究结果", content: `${payload.workflow_title || "研究结果"}\n${payload.executive_summary || payload.summary || ""}`.trim() },
  ];
  renderConversation();
  renderResearch(payload);
}

async function loadTaskCenter() {
  const payload = await api("/api/v1/assistant/research-tasks");
  state.taskCenterItems = payload.data.items || [];
  renderTaskCenter();
}

function renderResearch(payload) {
  const evidence = payload.evidence_bundle || {};
  const priceSnapshot = evidence.price_snapshot || null;
  const valuationSnapshot = evidence.valuation_snapshot || null;
  const qualitySnapshot = evidence.financial_quality_snapshot || null;
  const eventEvidence = evidence.event_evidence || { items: [] };
  const evidenceWarnings = Array.isArray(evidence.warnings) ? evidence.warnings : [];
  const evidenceRefs = Array.isArray(payload.evidence_refs) ? payload.evidence_refs : [];
  const reportSections = Array.isArray(payload.report_sections) ? payload.report_sections : [];
  nodes.summary.innerHTML = `
    <div class="list-item mentor-answer-card">
      <strong>${payload.workflow_title}</strong>
      <div class="muted-note">当前模式：${payload.answer_mode_label || "平台研究模板"}${payload.llm_profile_label ? ` · ${payload.llm_profile_label}` : ""}${payload.confidence_label ? ` · 研究置信度 ${payload.confidence_label}` : ""}</div>
      <div class="muted-note">${payload.executive_summary}</div>
      ${payload.evidence_gap_note ? `<div class="muted-note" style="margin-top:8px;">证据边界：${payload.evidence_gap_note}</div>` : ""}
    </div>
    <div class="list-item mentor-answer-card">
      <strong>长报告</strong>
      <div class="assistant-desk-results">
        ${
          reportSections.length
            ? reportSections
                .map(
                  (item) => `
                    <div class="assistant-desk-result">
                      <span>${item.title}</span>
                      <strong>${item.summary}</strong>
                      ${
                        Array.isArray(item.bullets) && item.bullets.length
                          ? `<ul class="mentor-step-list">${item.bullets.map((bullet) => `<li>${bullet}</li>`).join("")}</ul>`
                          : ""
                      }
                    </div>
                  `,
                )
                .join("")
            : '<div class="assistant-desk-result"><span>暂无长报告</span><strong>当前没有可展开的长报告段落。</strong></div>'
        }
      </div>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>专家拆解</strong>
      <div class="assistant-desk-results">
        ${payload.desk_briefs
          .map(
            (item) => `
              <div class="assistant-desk-result">
                <span>${item.desk}</span>
                <strong>${item.title}</strong>
                <div class="muted-note">${item.summary}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>平台证据包</strong>
      <div class="muted-note">状态：${evidence.status || "unavailable"}${payload.target_symbol ? ` · 标的 ${payload.target_symbol}` : ""}</div>
      <div class="assistant-desk-results">
        <div class="assistant-desk-result">
          <span>价格快照</span>
          <strong>${priceSnapshot ? `${priceSnapshot.trade_date} 收盘 ${priceSnapshot.close}` : "暂无"}</strong>
          <div class="muted-note">${priceSnapshot ? `日涨跌 ${priceSnapshot.day_change_pct}% · 20日 ${priceSnapshot.return_20d_pct}% · 60日 ${priceSnapshot.return_60d_pct}% · 来源 ${priceSnapshot.provider || "-"}` : "当前没有可用的内部行情证据。"} </div>
        </div>
        <div class="assistant-desk-result">
          <span>估值快照</span>
          <strong>${valuationSnapshot ? `PE(TTM) ${valuationSnapshot.pe_ttm ?? "-"} · PB ${valuationSnapshot.pb ?? "-"}` : "暂无"}</strong>
          <div class="muted-note">${valuationSnapshot ? `总市值 ${valuationSnapshot.total_mv ?? "-"} · 流通市值 ${valuationSnapshot.circ_mv ?? "-"} · 来源 ${valuationSnapshot.provider || "-"}` : "当前没有可用的估值快照。"} </div>
        </div>
        <div class="assistant-desk-result">
          <span>财务质量</span>
          <strong>${qualitySnapshot ? `ROE ${qualitySnapshot.roe ?? "-"} · 毛利率 ${qualitySnapshot.grossprofit_margin ?? "-"}` : "暂无"}</strong>
          <div class="muted-note">${qualitySnapshot ? `ROA ${qualitySnapshot.roa ?? "-"} · 营业利润同比 ${qualitySnapshot.op_yoy ?? "-"} · 来源 ${qualitySnapshot.provider || "-"}` : "当前没有可用的财务质量快照。"} </div>
        </div>
        <div class="assistant-desk-result">
          <span>近端事件与公告</span>
          <strong>${eventEvidence.items?.length ? `已收录 ${eventEvidence.items.length} 条线索` : "暂无"}</strong>
          <div class="muted-note">${
            eventEvidence.items?.length
              ? eventEvidence.items
                  .slice(0, 3)
                  .map((item) => `${item.title}｜${item.source}${item.as_of ? `｜${item.as_of}` : ""}`)
                  .join("<br>")
              : "当前模型链路未提供近端事件检索结果，或暂无可确认线索。"
          }</div>
        </div>
      </div>
      ${evidenceWarnings.length ? `<div class="muted-note" style="margin-top:10px;">${evidenceWarnings.map((item) => `- ${item}`).join("<br>")}</div>` : ""}
      ${
        evidenceRefs.length
          ? `<div class="muted-note" style="margin-top:10px;">${evidenceRefs
              .map((item) => `- ${item.label}｜${item.source}${item.as_of ? `｜${item.as_of}` : ""}｜${item.detail}`)
              .join("<br>")}</div>`
          : ""
      }
    </div>
  `;

  nodes.riskPanel.innerHTML = `
    <div class="list-item mentor-answer-card">
      <strong>多空分歧</strong>
      <div class="assistant-debate-list">
        ${payload.debate
          .map(
            (item) => `
              <div class="assistant-debate-item">
                <span>${item.side}</span>
                <div class="muted-note">${item.view}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>风险核对</strong>
      <ul class="mentor-step-list">
        ${payload.risk_checklist.map((item) => `<li>${item}</li>`).join("")}
      </ul>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>本轮交付物</strong>
      <ul class="mentor-step-list">
        ${payload.deliverables.map((item) => `<li>${item}</li>`).join("")}
      </ul>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>建议下一步</strong>
      <ol class="mentor-step-list">
        ${payload.next_actions.map((item) => `<li>${item}</li>`).join("")}
      </ol>
      <div class="mentor-module-links">
        ${payload.related_modules
          .map(
            (item) => `
              <a class="mentor-module-link" href="${item.path}">
                <span>${item.label}</span>
                <small>${item.reason}</small>
              </a>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

async function runAssistant(query, isFollowUp = false) {
  const workflow = selectedWorkflow();
  const created = await api("/api/v1/assistant/research-tasks", {
    method: "POST",
    body: JSON.stringify({
      query,
      workflow_id: workflow?.workflow_id || "market_map",
      target_symbol: nodes.target.value.trim(),
      market_scope: nodes.market.value,
      research_depth: nodes.depth.value,
      current_module: "assistant",
      llm_profile: nodes.llmProfile.value || "module_default",
      conversation_history: state.history.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    }),
  });
  appendConversation("user", isFollowUp ? "继续深化" : "研究任务", query);
  pendingResearchTasks.set(created.data.task_id, { query, isFollowUp });
  registerBackgroundTask({
    task_id: created.data.task_id,
    status_url: created.data.status_url,
    label: isFollowUp ? "金融助手继续深化研究" : "金融助手研究任务",
    module: "assistant",
    queued_message: isFollowUp
      ? "继续深化研究已转入后台，你可以先去使用其他模块。"
      : "研究任务已转入后台，你可以先去使用其他模块。",
    success_message: isFollowUp ? "金融助手补充研究已完成。" : "金融助手研究已完成。",
    failure_message: isFollowUp ? "金融助手继续深化研究失败。" : "金融助手研究失败。",
  });
  setInlineStatus(
    isFollowUp ? nodes.followupStatus : nodes.inlineStatus,
    isFollowUp ? "继续深化研究已转入后台生成。" : "研究任务已转入后台生成。",
    "running",
  );
  setStatus(isFollowUp ? "金融助手正在后台深化研究..." : "金融助手正在后台组织多专家研究...");
}

async function loadAssistant() {
  const [payload, llmProfiles] = await Promise.all([
    api("/api/v1/assistant/workflows"),
    fetchLlmProfiles(),
  ]);
  renderWorkflows(payload.data.items || []);
  renderDesks(payload.data.desks || []);
  populateLlmProfileSelect(nodes.llmProfile, llmProfiles, "assistant");
}

nodes.query.addEventListener("input", syncRunButtonState);
nodes.followup.addEventListener("input", syncFollowupButtonState);

nodes.runButton.addEventListener("click", async () => {
  try {
    state.history = [];
    renderConversation();
    await runAssistant(nodes.query.value.trim(), false);
    nodes.followup.value = "";
    syncFollowupButtonState();
  } catch (error) {
    setStatus(error.message);
  }
});

nodes.followupButton.addEventListener("click", async () => {
  try {
    const query = nodes.followup.value.trim();
    if (!query) {
      return;
    }
    await runAssistant(query, true);
    nodes.followup.value = "";
    syncFollowupButtonState();
  } catch (error) {
    setStatus(error.message);
  }
});

subscribeBackgroundTasks((task) => {
  if (task.module !== "assistant" || !pendingResearchTasks.has(task.task_id)) {
    return;
  }
  const meta = pendingResearchTasks.get(task.task_id);
  if (!meta) {
    return;
  }
  if (task.status === "succeeded" && task.data) {
    appendConversation("assistant", "研究结果", `${task.data.workflow_title}\n${task.data.executive_summary}`);
    renderResearch(task.data);
    loadTaskCenter().catch(() => {});
    setInlineStatus(
      meta.isFollowUp ? nodes.followupStatus : nodes.inlineStatus,
      meta.isFollowUp ? "继续深化研究已完成。" : "研究任务已完成。",
      "success",
    );
    setStatus(meta.isFollowUp ? "金融助手已补充更深入的研究结果。" : "金融助手已生成研究结果。");
    pendingResearchTasks.delete(task.task_id);
    return;
  }
  if (["failed", "canceled"].includes(task.status)) {
    setInlineStatus(
      meta.isFollowUp ? nodes.followupStatus : nodes.inlineStatus,
      task.data?.error?.message || task.error_message || "后台研究任务失败。",
      "error",
    );
    setStatus(task.data?.error?.message || task.error_message || "后台研究任务失败。");
    pendingResearchTasks.delete(task.task_id);
    loadTaskCenter().catch(() => {});
  }
});

renderConversation();
syncRunButtonState();
syncFollowupButtonState();
clearInlineStatus(nodes.inlineStatus, "等待你发起研究任务。");
clearInlineStatus(nodes.followupStatus, "继续细化也会转入后台处理，完成后会自动提醒你。");
nodes.refreshTasksButton?.addEventListener("click", () => {
  loadTaskCenter()
    .then(() => setStatus("后台研究任务列表已刷新。"))
    .catch((error) => setStatus(error.message));
});
Promise.all([loadAssistant(), loadTaskCenter()]).catch((error) => setStatus(error.message));
