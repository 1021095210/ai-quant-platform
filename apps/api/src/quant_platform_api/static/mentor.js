import {
  activateNav,
  api,
  setStatus,
} from "/assets/shared.js?v=20260402c";

activateNav("/mentor");

const state = {
  history: [],
};

const nodes = {
  topicList: document.querySelector("#mentor-topic-list"),
  question: document.querySelector("#mentor-question"),
  level: document.querySelector("#mentor-level"),
  marketScope: document.querySelector("#mentor-market-scope"),
  askButton: document.querySelector("#mentor-ask-btn"),
  answer: document.querySelector("#mentor-answer"),
  actions: document.querySelector("#mentor-actions"),
  conversation: document.querySelector("#mentor-conversation"),
  followup: document.querySelector("#mentor-followup"),
  followupButton: document.querySelector("#mentor-followup-btn"),
};

function syncAskButtonState() {
  const canAsk = Boolean(nodes.question.value.trim());
  nodes.askButton.disabled = !canAsk;
  nodes.askButton.className = canAsk ? "btn primary" : "btn disabled";
}

function syncFollowupButtonState() {
  const canFollowUp = state.history.length > 0 && Boolean(nodes.followup.value.trim());
  nodes.followupButton.disabled = !canFollowUp;
  nodes.followupButton.className = canFollowUp ? "btn primary" : "btn disabled";
}

function renderTopics(items) {
  if (!items.length) {
    nodes.topicList.textContent = "暂无导师起步问题。";
    return;
  }
  nodes.topicList.innerHTML = items
    .map(
      (item) => `
        <button class="mentor-topic-card" type="button" data-prompt="${item.prompt}">
          <span class="mentor-topic-kicker">推荐起点</span>
          <strong>${item.title}</strong>
          <span>${item.summary}</span>
        </button>
      `,
    )
    .join("");

  nodes.topicList.querySelectorAll("[data-prompt]").forEach((node) => {
    node.addEventListener("click", () => {
      nodes.question.value = node.dataset.prompt || "";
      syncAskButtonState();
      nodes.question.focus();
      setStatus("已填入导师示例问题，可以直接提问。");
    });
  });
}

function renderAnswer(payload) {
  nodes.answer.innerHTML = `
    <div class="list-item mentor-answer-card">
      <strong>${payload.headline}</strong>
      <div class="muted-note">当前模式：${payload.answer_mode_label || "平台导师兜底"}</div>
      <div class="muted-note">${payload.answer}</div>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>为什么这件事重要</strong>
      <div class="muted-note">${payload.why_it_matters}</div>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>市场提醒</strong>
      <div class="muted-note">${payload.risk_note}</div>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>相关概念</strong>
      <div class="mentor-glossary">
        ${payload.glossary
          .map(
            (item) => `
              <div class="mentor-glossary-item">
                <span>${item.term}</span>
                <small>${item.meaning}</small>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;

  nodes.actions.innerHTML = `
    <div class="list-item mentor-answer-card">
      <strong>请按这个顺序继续</strong>
      <ol class="mentor-step-list">
        ${payload.action_plan.map((item) => `<li>${item}</li>`).join("")}
      </ol>
    </div>
    <div class="list-item mentor-answer-card">
      <strong>直接去这些模块</strong>
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

function renderConversation() {
  if (!state.history.length) {
    nodes.conversation.textContent = "先完成一次提问后，这里会保留你和导师的对话。";
    nodes.conversation.className = "mentor-conversation empty-state";
    return;
  }

  nodes.conversation.className = "mentor-conversation";
  nodes.conversation.innerHTML = state.history
    .map(
      (item) => `
        <div class="mentor-message ${item.role === "user" ? "user" : "assistant"}">
          <span class="mentor-message-role">${item.role === "user" ? "你" : "金融导师"}</span>
          <strong>${item.title || (item.role === "user" ? "提问" : "回答")}</strong>
          <div class="muted-note">${item.content}</div>
        </div>
      `,
    )
    .join("");
}

function appendConversationTurn(role, content, title = "") {
  state.history.push({ role, content, title });
  renderConversation();
  syncFollowupButtonState();
}

async function loadTopics() {
  const payload = await api("/api/v1/mentor/topics");
  renderTopics(payload.data.items || []);
}

async function askMentor(question, options = {}) {
  const { isFollowUp = false } = options;
  setStatus(isFollowUp ? "金融导师正在补充解释..." : "金融导师正在整理建议...");
  const payload = await api("/api/v1/mentor/ask", {
    method: "POST",
    body: JSON.stringify({
      question,
      experience_level: nodes.level.value,
      market_scope: nodes.marketScope.value,
      current_module: "mentor",
      conversation_history: state.history.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    }),
  });
  const data = payload.data;
  appendConversationTurn("user", question, isFollowUp ? "继续追问" : "首次提问");
  appendConversationTurn("assistant", `${data.headline}\n${data.answer}`, "导师回复");
  renderAnswer(data);
  if (!isFollowUp) {
    nodes.followup.focus();
  }
  setStatus(isFollowUp ? "导师补充解释已生成。" : "导师建议已生成。");
}

nodes.question.addEventListener("input", syncAskButtonState);
nodes.followup.addEventListener("input", syncFollowupButtonState);

nodes.askButton.addEventListener("click", async () => {
  try {
    state.history = [];
    renderConversation();
    await askMentor(nodes.question.value.trim(), { isFollowUp: false });
    nodes.followup.value = "";
    syncFollowupButtonState();
  } catch (error) {
    setStatus(error.message);
  }
});

nodes.followupButton.addEventListener("click", async () => {
  try {
    const question = nodes.followup.value.trim();
    if (!question) {
      return;
    }
    await askMentor(question, { isFollowUp: true });
    nodes.followup.value = "";
    syncFollowupButtonState();
  } catch (error) {
    setStatus(error.message);
  }
});

renderConversation();
syncAskButtonState();
syncFollowupButtonState();
loadTopics().catch((error) => setStatus(error.message));
