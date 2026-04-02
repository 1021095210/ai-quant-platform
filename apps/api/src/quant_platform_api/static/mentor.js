import {
  activateNav,
  api,
  setStatus,
} from "/assets/shared.js";

activateNav("/mentor");

const nodes = {
  topicList: document.querySelector("#mentor-topic-list"),
  question: document.querySelector("#mentor-question"),
  level: document.querySelector("#mentor-level"),
  marketScope: document.querySelector("#mentor-market-scope"),
  askButton: document.querySelector("#mentor-ask-btn"),
  answer: document.querySelector("#mentor-answer"),
  actions: document.querySelector("#mentor-actions"),
};

function syncAskButtonState() {
  const canAsk = Boolean(nodes.question.value.trim());
  nodes.askButton.disabled = !canAsk;
  nodes.askButton.className = canAsk ? "btn primary" : "btn disabled";
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

async function loadTopics() {
  const payload = await api("/api/v1/mentor/topics");
  renderTopics(payload.data.items || []);
}

async function askMentor() {
  setStatus("金融导师正在整理建议...");
  const payload = await api("/api/v1/mentor/ask", {
    method: "POST",
    body: JSON.stringify({
      question: nodes.question.value,
      experience_level: nodes.level.value,
      market_scope: nodes.marketScope.value,
      current_module: "mentor",
    }),
  });
  renderAnswer(payload.data);
  setStatus("导师建议已生成。");
}

nodes.question.addEventListener("input", syncAskButtonState);
nodes.askButton.addEventListener("click", async () => {
  try {
    await askMentor();
  } catch (error) {
    setStatus(error.message);
  }
});

syncAskButtonState();
loadTopics().catch((error) => setStatus(error.message));
