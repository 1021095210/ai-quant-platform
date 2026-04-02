import { activateNav, api, handle, pretty, setStatus } from "/assets/shared.js";

activateNav("/indicators");

const state = {
  generatedIndicator: null,
};

const nodes = {
  builtin: document.querySelector("#builtin-indicators"),
  prompt: document.querySelector("#custom-indicator-prompt"),
  summary: document.querySelector("#custom-indicator-summary"),
  name: document.querySelector("#custom-indicator-name"),
  formula: document.querySelector("#custom-indicator-formula"),
  code: document.querySelector("#custom-indicator-code"),
  usage: document.querySelector("#custom-indicator-usage"),
  library: document.querySelector("#custom-indicator-library"),
  saveButton: document.querySelector("#save-custom-indicator-btn"),
};

function syncIndicatorActionState() {
  const ready = Boolean(state.generatedIndicator);
  nodes.saveButton.disabled = !ready;
  nodes.saveButton.className = ready ? "btn primary" : "btn disabled";
}

async function loadPage() {
  const [builtinPayload, customPayload] = await Promise.all([
    api("/api/v1/indicators/builtin"),
    api("/api/v1/indicators/custom"),
  ]);
  renderBuiltin(builtinPayload.data.items);
  renderLibrary(customPayload.data.items);
  setStatus("指标模块已加载。");
}

function renderBuiltin(items) {
  if (!items.length) {
    nodes.builtin.textContent = "暂无传统指标。";
    return;
  }
  nodes.builtin.innerHTML = items
    .map(
      (item) => `
        <details class="accordion-item">
          <summary>
            <span>${item.title}</span>
            <span class="muted-note">${item.indicator_key}</span>
          </summary>
          <div class="accordion-content">
            <p>${item.summary}</p>
            <div class="pill-row">
              ${Object.entries(item.default_params || {})
                .map(([key, value]) => `<span class="pill">${key}: ${value}</span>`)
                .join("")}
            </div>
            <div class="detail-block">
              <h4>公式</h4>
              <pre class="result-box light">${item.formula_text}</pre>
            </div>
            <div class="detail-block">
              <h4>Python 代码</h4>
              <pre class="code-block">${item.python_code}</pre>
            </div>
            <div class="detail-block">
              <h4>使用建议</h4>
              <pre class="result-box light">${item.usage_hint}</pre>
            </div>
          </div>
        </details>
      `,
    )
    .join("");
}

function renderLibrary(items) {
  if (!items.length) {
    nodes.library.textContent = "自定义指标库为空。";
    return;
  }
  nodes.library.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.name}</strong>
          <div class="muted-note">${item.summary}</div>
          <div class="pill-row" style="margin-top:10px">
            ${(item.tags || []).map((tag) => `<span class="pill">${tag}</span>`).join("")}
          </div>
          <pre class="result-box light" style="margin-top:12px">${item.formula_text}</pre>
          <pre class="code-block" style="margin-top:12px">${item.python_code}</pre>
        </div>
      `,
    )
    .join("");
}

async function generateIndicator() {
  setStatus("正在生成自定义指标...");
  const payload = await api("/api/v1/indicators/custom/generate", {
    method: "POST",
    body: JSON.stringify({ prompt: nodes.prompt.value }),
  });
  state.generatedIndicator = payload.data;
  nodes.summary.textContent = payload.data.summary;
  nodes.name.value = payload.data.name;
  nodes.formula.value = payload.data.formula_text;
  nodes.code.value = payload.data.python_code;
  nodes.usage.value = payload.data.usage_hint;
  syncIndicatorActionState();
  setStatus("自定义指标草稿已生成，可以保存到指标库。");
}

async function saveIndicator() {
  if (!state.generatedIndicator) {
    throw new Error("请先生成自定义指标。");
  }
  setStatus("正在保存自定义指标...");
  await api("/api/v1/indicators/custom", {
    method: "POST",
    body: JSON.stringify({
      name: nodes.name.value,
      natural_language_prompt: nodes.prompt.value,
      summary: state.generatedIndicator.summary,
      formula_text: nodes.formula.value,
      python_code: nodes.code.value,
      usage_hint: nodes.usage.value,
      tags: state.generatedIndicator.tags || [],
    }),
  });
  const libraryPayload = await api("/api/v1/indicators/custom");
  renderLibrary(libraryPayload.data.items);
  syncIndicatorActionState();
  setStatus("自定义指标已保存，策略工坊现在可以通过指标名称直接调用它。");
}

document
  .querySelector("#generate-custom-indicator-btn")
  .addEventListener("click", handle(generateIndicator));
document
  .querySelector("#save-custom-indicator-btn")
  .addEventListener("click", handle(saveIndicator));

syncIndicatorActionState();
loadPage().catch((error) => {
  setStatus(error.message);
  nodes.summary.textContent = pretty({ error: error.message });
});
