import {
  activateNav,
  api,
  getSelectedVersion,
  handle,
  pretty,
  setSelectedVersion,
  setStatus,
} from "/assets/shared.js";

activateNav("/strategy");

const state = {
  strategySpec: null,
  strategyPython: "",
};

const nodes = {
  prompt: document.querySelector("#strategy-prompt"),
  marketScope: document.querySelector("#strategy-market-scope"),
  market: document.querySelector("#strategy-market"),
  assetType: document.querySelector("#strategy-asset-type"),
  timeframe: document.querySelector("#strategy-timeframe"),
  timeframeOptions: document.querySelectorAll('input[name="strategy-timeframes"]'),
  title: document.querySelector("#project-title"),
  teachingMode: document.querySelector("#teaching-mode-toggle"),
  summary: document.querySelector("#strategy-summary"),
  ambiguities: document.querySelector("#strategy-ambiguities"),
  python: document.querySelector("#strategy-python-output"),
  spec: document.querySelector("#strategy-spec-output"),
  currentVersion: document.querySelector("#current-version"),
  currentTitle: document.querySelector("#current-title"),
  customIndicatorLibrary: document.querySelector("#custom-indicator-library"),
  glossaryPreview: document.querySelector("#glossary-preview"),
};

const MARKET_PRESETS = {
  cn_equity: { symbol: "600519.SH", assetType: "stock" },
  us_equity: { symbol: "AAPL", assetType: "stock" },
  crypto: { symbol: "BTCUSDT", assetType: "crypto" },
  london_gold: { symbol: "XAUUSD", assetType: "commodity" },
};

function getSelectedTimeframes() {
  const selected = Array.from(nodes.timeframeOptions)
    .filter((item) => item.checked)
    .map((item) => item.value);
  if (!selected.includes(nodes.timeframe.value)) {
    selected.unshift(nodes.timeframe.value);
  }
  return [...new Set(selected)];
}

function syncTimeframeSelection() {
  const primary = nodes.timeframe.value;
  const matching = Array.from(nodes.timeframeOptions).find((item) => item.value === primary);
  if (matching) {
    matching.checked = true;
  }
}

function applyMarketPreset() {
  const preset = MARKET_PRESETS[nodes.marketScope.value];
  if (!preset) {
    return;
  }
  nodes.market.value = preset.symbol;
  nodes.assetType.value = preset.assetType;
}

async function generateStrategy() {
  setStatus("正在生成 Python 策略...");
  const payload = await api("/api/v1/strategies/generate", {
    method: "POST",
    body: JSON.stringify({
      prompt: nodes.prompt.value,
      market_scope: nodes.marketScope.value,
      market: nodes.market.value,
      timeframe: nodes.timeframe.value,
      timeframes: getSelectedTimeframes(),
      asset_type: nodes.assetType.value,
      preferences: { side: "long" },
      teaching_mode: nodes.teachingMode.checked,
    }),
  });
  state.strategySpec = payload.data.strategy_dsl;
  state.strategyPython = payload.data.strategy_python;
  nodes.summary.textContent = payload.data.human_summary;
  nodes.python.textContent = payload.data.strategy_python;
  nodes.spec.textContent = pretty(payload.data.strategy_dsl);
  nodes.ambiguities.innerHTML = payload.data.ambiguities.length
      ? payload.data.ambiguities.map((item) => `<span class="pill">${item}</span>`).join("")
      : '<span class="pill">无额外歧义</span>';
  if (payload.data.matched_custom_indicators?.length) {
    nodes.ambiguities.innerHTML += payload.data.matched_custom_indicators
      .map((item) => `<span class="pill">已调用指标：${item.name}</span>`)
      .join("");
  }
  if (payload.data.matched_terms?.length) {
    nodes.ambiguities.innerHTML += payload.data.matched_terms
      .map((item) => `<span class="pill">术语已识别：${item.term}</span>`)
      .join("");
  }
  setStatus("策略生成完成。");
}

async function saveProject() {
  if (!state.strategySpec) {
    throw new Error("请先生成策略。");
  }
  setStatus("正在保存策略项目...");
  const payload = await api("/api/v1/strategies/projects", {
    method: "POST",
    body: JSON.stringify({
      title: nodes.title.value,
      natural_language_prompt: nodes.prompt.value,
      strategy_dsl: state.strategySpec,
      strategy_python: state.strategyPython,
    }),
  });
  setSelectedVersion(payload.data.version_id, nodes.title.value);
  nodes.currentVersion.textContent = payload.data.version_id;
  nodes.currentTitle.textContent = nodes.title.value;
  setStatus("项目已保存，现在可以去回测中心运行回测。");
}

function restoreSelection() {
  const { versionId, title } = getSelectedVersion();
  if (versionId) {
    nodes.currentVersion.textContent = versionId;
  }
  if (title) {
    nodes.currentTitle.textContent = title;
  }
}

async function loadKnowledgePreview() {
  const [indicatorPayload, glossaryPayload] = await Promise.all([
    api("/api/v1/indicators/custom"),
    api("/api/v1/rules/glossary"),
  ]);
  const indicators = indicatorPayload.data.items;
  const glossary = glossaryPayload.data.items.slice(0, 8);

  nodes.customIndicatorLibrary.innerHTML = indicators.length
    ? indicators
        .map(
          (item) => `
            <div class="list-item">
              <strong>${item.name}</strong>
              <div class="muted-note">${item.summary}</div>
              <div class="muted-note">在提示词里直接写出这个指标名称即可调用。</div>
            </div>
          `,
        )
        .join("")
    : "当前还没有自定义指标，先去指标设置页生成一个。";

  nodes.glossaryPreview.innerHTML = glossary.length
    ? glossary
        .map(
          (item) => `<span class="pill" title="${item.meaning}">${item.term}</span>`,
        )
        .join("")
    : '<span class="pill">暂无术语，去规则模块补充</span>';
}

document
  .querySelector("#generate-strategy-btn")
  .addEventListener("click", handle(generateStrategy));
document
  .querySelector("#save-project-btn")
  .addEventListener("click", handle(saveProject));
nodes.timeframe.addEventListener("change", syncTimeframeSelection);
nodes.marketScope.addEventListener("change", applyMarketPreset);

restoreSelection();
syncTimeframeSelection();
loadKnowledgePreview().catch((error) => setStatus(error.message));
