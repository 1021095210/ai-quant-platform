import { activateNav, api, handle, setStatus } from "/assets/shared.js";

activateNav("/rules");

const nodes = {
  defaultRules: document.querySelector("#default-rules"),
  resetDefaultRulesBtn: document.querySelector("#reset-default-rules-btn"),
  saveDefaultRulesBtn: document.querySelector("#save-default-rules-btn"),
  glossaryLibrary: document.querySelector("#glossary-library"),
  term: document.querySelector("#glossary-term"),
  meaning: document.querySelector("#glossary-meaning"),
  example: document.querySelector("#glossary-example"),
  saveGlossaryBtn: document.querySelector("#save-glossary-btn"),
};

const state = {
  defaultRulesDirty: false,
};

function syncRulesActionState() {
  const glossaryReady = Boolean(nodes.term.value.trim() && nodes.meaning.value.trim());
  nodes.saveGlossaryBtn.disabled = !glossaryReady;
  nodes.saveGlossaryBtn.className = glossaryReady ? "btn primary" : "btn disabled";

  nodes.saveDefaultRulesBtn.disabled = !state.defaultRulesDirty;
  nodes.saveDefaultRulesBtn.className = state.defaultRulesDirty ? "btn primary" : "btn disabled";
  nodes.resetDefaultRulesBtn.className = state.defaultRulesDirty ? "btn secondary" : "btn ghost";
}

function markDefaultRulesDirty() {
  state.defaultRulesDirty = true;
  syncRulesActionState();
}

async function loadPage() {
  const [rulesPayload, glossaryPayload] = await Promise.all([
    api("/api/v1/rules/defaults"),
    api("/api/v1/rules/glossary"),
  ]);
  renderRules(rulesPayload.data.items);
  renderGlossary(glossaryPayload.data.items);
  state.defaultRulesDirty = false;
  syncRulesActionState();
  setStatus("规则模块已加载。");
}

function renderRules(items) {
  if (!items.length) {
    nodes.defaultRules.textContent = "暂无默认规则。";
    return;
  }
  nodes.defaultRules.innerHTML = items
    .map(
      (section, index) => `
        <details class="accordion-item rule-group-card" data-rule-section="${section.section_id}" ${index === 0 ? "open" : ""}>
          <summary class="rule-group-summary">
            <div>
              <div class="rule-group-kicker">默认规则分组</div>
              <div class="rule-group-title">${section.section}</div>
            </div>
            <div class="rule-group-meta">共 ${(section.items || []).length} 项</div>
          </summary>
          <div class="accordion-content rule-group-body">
            <label class="field">
              <span>分组名称</span>
              <input data-section-name value="${section.section}" />
            </label>
            <div class="rule-list" data-rule-items>
              ${(section.items || [])
                .map((item, indexRule) => renderRuleItem(section.section_id, item, indexRule))
                .join("")}
            </div>
            <div class="inline-actions" style="margin-top: 12px">
              <button type="button" class="btn ghost" data-add-rule-item="${section.section_id}">新增规则项</button>
            </div>
          </div>
        </details>
      `,
    )
    .join("");

  nodes.defaultRules.querySelectorAll("[data-add-rule-item]").forEach((button) => {
    button.addEventListener("click", () => {
      const sectionNode = button.closest("[data-rule-section]");
      const itemContainer = sectionNode.querySelector("[data-rule-items]");
      const nextIndex = itemContainer.querySelectorAll("[data-rule-item]").length;
      itemContainer.insertAdjacentHTML(
        "beforeend",
        renderRuleItem(button.dataset.addRuleItem, { title: "", description: "" }, nextIndex),
      );
      bindRuleItemRemoveActions();
      bindRuleEditActions();
      markDefaultRulesDirty();
    });
  });
  bindRuleEditActions();
}

function renderRuleItem(sectionId, item, index) {
  return `
                  <div class="rule-item stack" data-rule-item="${sectionId}_${index}">
                    <label class="field">
                      <span>规则标题</span>
                      <input data-rule-title value="${item.title || ""}" />
                    </label>
                    <label class="field">
                      <span>规则说明</span>
                      <textarea data-rule-description>${item.description || ""}</textarea>
                    </label>
                    <div class="inline-actions">
                      <button type="button" class="btn ghost" data-remove-rule-item>删除这一项</button>
                    </div>
                  </div>
                `;
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
  nodes.term.value = "";
  nodes.meaning.value = "";
  nodes.example.value = "";
  syncRulesActionState();
  setStatus("术语解释已保存，策略工坊现在会把它当成 AI 的补充语义。");
}

function collectDefaultRules() {
  return Array.from(nodes.defaultRules.querySelectorAll("[data-rule-section]")).map((sectionNode) => ({
    section_id: sectionNode.dataset.ruleSection,
    section: sectionNode.querySelector("[data-section-name]").value,
    items: Array.from(sectionNode.querySelectorAll("[data-rule-item]")).map((itemNode) => ({
      title: itemNode.querySelector("[data-rule-title]").value,
      description: itemNode.querySelector("[data-rule-description]").value,
    })),
  }));
}

async function saveDefaultRules() {
  setStatus("正在保存默认规则...");
  const payload = await api("/api/v1/rules/defaults", {
    method: "PUT",
    body: JSON.stringify({
      items: collectDefaultRules(),
    }),
  });
  renderRules(payload.data.items);
  bindRuleItemRemoveActions();
  state.defaultRulesDirty = false;
  syncRulesActionState();
  setStatus(`默认规则已保存，更新人：${payload.data.updated_by}。`);
}

async function resetDefaultRules() {
  setStatus("正在恢复平台默认规则...");
  const payload = await api("/api/v1/rules/defaults/reset", {
    method: "POST",
  });
  renderRules(payload.data.items);
  bindRuleItemRemoveActions();
  state.defaultRulesDirty = false;
  syncRulesActionState();
  setStatus(`平台默认规则已恢复，更新人：${payload.data.updated_by}。`);
}

function bindRuleItemRemoveActions() {
  nodes.defaultRules.querySelectorAll("[data-remove-rule-item]").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest("[data-rule-item]").remove();
      markDefaultRulesDirty();
    });
  });
}

function bindRuleEditActions() {
  nodes.defaultRules.querySelectorAll("[data-section-name], [data-rule-title], [data-rule-description]").forEach((node) => {
    node.addEventListener("input", markDefaultRulesDirty);
  });
}

document.querySelector("#save-glossary-btn").addEventListener("click", handle(saveGlossaryTerm));
nodes.resetDefaultRulesBtn.addEventListener("click", handle(resetDefaultRules));
nodes.saveDefaultRulesBtn.addEventListener("click", handle(saveDefaultRules));
nodes.term.addEventListener("input", syncRulesActionState);
nodes.meaning.addEventListener("input", syncRulesActionState);
nodes.example.addEventListener("input", syncRulesActionState);

loadPage()
  .then(() => bindRuleItemRemoveActions())
  .catch((error) => setStatus(error.message));
