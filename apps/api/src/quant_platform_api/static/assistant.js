import {
  activateNav,
  api,
  setStatus,
} from "/assets/shared.js";

activateNav("/assistant");

const state = {
  workflows: [],
  selectedWorkflowId: "market_map",
  history: [],
};

const nodes = {
  workflows: document.querySelector("#assistant-workflows"),
  desks: document.querySelector("#assistant-desks"),
  selectedWorkflow: document.querySelector("#assistant-selected-workflow"),
  depth: document.querySelector("#assistant-depth"),
  market: document.querySelector("#assistant-market"),
  target: document.querySelector("#assistant-target"),
  query: document.querySelector("#assistant-query"),
  runButton: document.querySelector("#assistant-run-btn"),
  summary: document.querySelector("#assistant-summary"),
  riskPanel: document.querySelector("#assistant-risk-panel"),
  conversation: document.querySelector("#assistant-conversation"),
  followup: document.querySelector("#assistant-followup"),
  followupButton: document.querySelector("#assistant-followup-btn"),
};

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

function appendConversation(role, title, content) {
  state.history.push({ role, title, content });
  renderConversation();
  syncFollowupButtonState();
}

function renderResearch(payload) {
  nodes.summary.innerHTML = `
    <div class="list-item mentor-answer-card">
      <strong>${payload.workflow_title}</strong>
      <div class="muted-note">当前模式：${payload.answer_mode_label || "平台研究模板"}</div>
      <div class="muted-note">${payload.executive_summary}</div>
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
  setStatus(isFollowUp ? "金融助手正在深化研究..." : "金融助手正在组织多专家研究...");
  const payload = await api("/api/v1/assistant/analyze", {
    method: "POST",
    body: JSON.stringify({
      query,
      workflow_id: workflow?.workflow_id || "market_map",
      target_symbol: nodes.target.value.trim(),
      market_scope: nodes.market.value,
      research_depth: nodes.depth.value,
      current_module: "assistant",
      conversation_history: state.history.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    }),
  });
  const data = payload.data;
  appendConversation("user", isFollowUp ? "继续深化" : "研究任务", query);
  appendConversation("assistant", "研究结果", `${data.workflow_title}\n${data.executive_summary}`);
  renderResearch(data);
  setStatus(isFollowUp ? "金融助手已补充更深入的研究结果。" : "金融助手已生成研究结果。");
}

async function loadAssistant() {
  const payload = await api("/api/v1/assistant/workflows");
  renderWorkflows(payload.data.items || []);
  renderDesks(payload.data.desks || []);
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

renderConversation();
syncRunButtonState();
syncFollowupButtonState();
loadAssistant().catch((error) => setStatus(error.message));
