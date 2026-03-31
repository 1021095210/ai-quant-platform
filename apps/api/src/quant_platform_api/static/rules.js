import { activateNav, api, handle, setStatus } from "/assets/shared.js";

activateNav("/rules");

const nodes = {
  defaultRules: document.querySelector("#default-rules"),
  glossaryLibrary: document.querySelector("#glossary-library"),
  term: document.querySelector("#glossary-term"),
  meaning: document.querySelector("#glossary-meaning"),
  example: document.querySelector("#glossary-example"),
};

async function loadPage() {
  const [rulesPayload, glossaryPayload] = await Promise.all([
    api("/api/v1/rules/defaults"),
    api("/api/v1/rules/glossary"),
  ]);
  renderRules(rulesPayload.data.items);
  renderGlossary(glossaryPayload.data.items);
  setStatus("规则模块已加载。");
}

function renderRules(items) {
  if (!items.length) {
    nodes.defaultRules.textContent = "暂无默认规则。";
    return;
  }
  nodes.defaultRules.innerHTML = items
    .map(
      (section) => `
        <div class="list-item">
          <strong>${section.section}</strong>
          <div class="rule-list">
            ${(section.items || [])
              .map(
                (item) => `
                  <div class="rule-item">
                    <h4>${item.title}</h4>
                    <p>${item.description}</p>
                  </div>
                `,
              )
              .join("")}
          </div>
        </div>
      `,
    )
    .join("");
}

function renderGlossary(items) {
  if (!items.length) {
    nodes.glossaryLibrary.textContent = "术语库为空。";
    return;
  }
  nodes.glossaryLibrary.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.term}</strong>
          <div class="muted-note">${item.source === "custom" ? "自定义术语" : "默认术语"}</div>
          <p>${item.meaning}</p>
          ${item.example ? `<pre class="result-box light">${item.example}</pre>` : ""}
        </div>
      `,
    )
    .join("");
}

async function saveGlossaryTerm() {
  setStatus("正在保存术语解释...");
  await api("/api/v1/rules/glossary", {
    method: "POST",
    body: JSON.stringify({
      term: nodes.term.value,
      meaning: nodes.meaning.value,
      example: nodes.example.value,
    }),
  });
  const glossaryPayload = await api("/api/v1/rules/glossary");
  renderGlossary(glossaryPayload.data.items);
  setStatus("术语解释已保存，策略工坊现在会把它当成 AI 的补充语义。");
}

document.querySelector("#save-glossary-btn").addEventListener("click", handle(saveGlossaryTerm));

loadPage().catch((error) => setStatus(error.message));
