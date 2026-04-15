import {
  activateNav,
  api,
  clearInlineStatus,
  fetchLlmProfiles,
  getSelectedVersion,
  handle,
  populateLlmProfileSelect,
  pretty,
  registerBackgroundTask,
  setSelectedVersion,
  setStatus,
  setInlineStatus,
  subscribeBackgroundTasks,
} from "/assets/shared.js";

activateNav("/strategy");

const state = {
  strategySpec: null,
  strategyPython: "",
  platformCapabilities: [],
  generationDecision: null,
  clarificationAnswers: {},
  structuredSpec: null,
  hardValidation: null,
  generationPipeline: [],
  fieldMapping: [],
  clarificationRound: null,
  taskCenterItems: [],
};

const nodes = {
  prompt: document.querySelector("#strategy-prompt"),
  inlineStatus: document.querySelector("#strategy-inline-status"),
  marketScope: document.querySelector("#strategy-market-scope"),
  market: document.querySelector("#strategy-market"),
  assetType: document.querySelector("#strategy-asset-type"),
  timeframe: document.querySelector("#strategy-timeframe"),
  timeframeOptions: document.querySelectorAll('input[name="strategy-timeframes"]'),
  llmProfile: document.querySelector("#strategy-llm-profile"),
  versionLabel: document.querySelector("#project-version-label"),
  title: document.querySelector("#project-title"),
  teachingMode: document.querySelector("#teaching-mode-toggle"),
  summary: document.querySelector("#strategy-summary"),
  ambiguities: document.querySelector("#strategy-ambiguities"),
  python: document.querySelector("#strategy-python-output"),
  spec: document.querySelector("#strategy-spec-output"),
  currentVersion: document.querySelector("#current-version"),
  saveProjectButton: document.querySelector("#save-project-btn"),
  goBacktestsLink: document.querySelector("#go-backtests-link"),
  customIndicatorLibrary: document.querySelector("#custom-indicator-library"),
  glossaryPreview: document.querySelector("#glossary-preview"),
  capabilitySummary: document.querySelector("#strategy-capability-summary"),
  capabilityMatrix: document.querySelector("#strategy-capability-matrix"),
  generationDecision: document.querySelector("#strategy-generation-decision"),
  understandingCard: document.querySelector("#strategy-understanding-card"),
  questions: document.querySelector("#strategy-questions"),
  unsupportedItems: document.querySelector("#strategy-unsupported-items"),
  applyClarificationsButton: document.querySelector("#apply-clarifications-btn"),
  clarificationProgress: document.querySelector("#strategy-clarification-progress"),
  clarificationAnswered: document.querySelector("#strategy-clarification-answered"),
  naturalLanguageView: document.querySelector("#strategy-natural-language-view"),
  structuredSpecView: document.querySelector("#strategy-structured-spec-view"),
  hardValidationView: document.querySelector("#strategy-hard-validation-view"),
  generationPipelineView: document.querySelector("#strategy-generation-pipeline-view"),
  fieldMappingView: document.querySelector("#strategy-field-mapping-view"),
  taskCenter: document.querySelector("#strategy-task-center"),
  refreshTasksButton: document.querySelector("#strategy-refresh-tasks-btn"),
};

let pendingGenerationTaskId = null;

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
  syncStrategyCapabilityState();
}

function syncStrategyActionState() {
  const canGenerateFollowup = Boolean(state.strategySpec && state.strategyPython);
  const canSave = Boolean(
    canGenerateFollowup && state.generationDecision && state.generationDecision.allow_save,
  );
  const canGoBacktests = Boolean(
    canGenerateFollowup &&
      state.generationDecision &&
      state.generationDecision.allow_backtest_handoff,
  );
  nodes.saveProjectButton.disabled = !canSave;
  nodes.saveProjectButton.className = canSave ? "btn primary" : "btn disabled";
  nodes.goBacktestsLink.className = canGoBacktests ? "btn primary" : "btn disabled";
  nodes.goBacktestsLink.setAttribute("aria-disabled", canGoBacktests ? "false" : "true");
  const canApplyClarifications = Boolean(
    state.generationDecision?.status === "needs_confirmation",
  );
  nodes.applyClarificationsButton.disabled = !canApplyClarifications;
  nodes.applyClarificationsButton.className = canApplyClarifications
    ? "btn secondary"
    : "btn secondary disabled";
}

function renderGenerationDecision(decision) {
  if (!decision) {
    nodes.generationDecision.textContent = "等待生成策略理解结果。";
    return;
  }
  nodes.generationDecision.innerHTML = `
    <div class="capability-status capability-${
      decision.status === "ready"
        ? "supported"
        : decision.status === "semantic_only"
          ? "limited"
          : "unsupported"
    }">
      <strong>${decision.label}</strong>
      <span>${decision.summary}</span>
    </div>
  `;
}

function renderUnderstandingCard(card) {
  if (!card) {
    nodes.understandingCard.textContent = "等待生成结构化理解结果。";
    return;
  }
  const sections = [
    ["理解模式", card.parse_mode === "llm_assisted" ? "AI 候选理解 + 平台规则约束" : "规则 / 语义解析"],
    ["市场", `${card.market_scope_label} / ${card.market}`],
    ["资产类型", card.asset_type],
    ["主周期", card.primary_timeframe_label],
    ["观察周期", (card.timeframe_labels || []).join(" / ") || "未识别"],
    ["数据依赖", (card.data_dependencies || []).join(" / ") || "未识别"],
    ["AI 候选摘要", card.ai_summary || "当前未启用 AI 候选理解或未得到稳定结果"],
    ["AI 模型", card.ai_profile_label || "当前未显式显示"],
    [
      "已补充说明",
      Object.entries(card.clarifications || {})
        .map(([key, value]) => `${key}: ${value}`)
        .join("；") || "无",
    ],
    ["执行假设", (card.execution_assumptions || []).join("；") || "未识别"],
    [
      "入场条件",
      (card.entry_conditions || [])
        .map((item) => `${item.label} ${item.operator} ${String(item.value)}`)
        .join("；") || "未识别",
    ],
    [
      "离场条件",
      (card.exit_conditions || [])
        .map((item) => `${item.label} ${item.operator} ${String(item.value)}`)
        .join("；") || "未识别",
    ],
    [
      "AI 待确认项",
      (card.ai_unresolved_items || [])
        .map((item) => item.title)
        .join("；") || "无",
    ],
    [
      "AI 风险提示",
      (card.ai_risky_items || []).join("；") || "无",
    ],
  ];
  nodes.understandingCard.innerHTML = sections
    .map(
      ([title, detail]) => `
        <div class="list-item">
          <strong>${title}</strong>
          <div class="muted-note">${detail}</div>
        </div>
      `,
    )
    .join("");
}

function renderQuestions(items) {
  if (!items?.length) {
    nodes.questions.textContent = "当前没有待补充问题。";
    return;
  }
  state.clarificationAnswers = Object.fromEntries(
    items.map((item) => [item.id, state.clarificationAnswers[item.id] || ""]),
  );
  nodes.questions.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          ${
            item.round_type === "followup"
              ? `<div class="pill-row" style="margin: 8px 0"><span class="pill">继续追问</span><span class="pill">基于：${item.depends_on_title || item.depends_on || "上一轮补充"}</span></div>`
              : ""
          }
          <div class="muted-note">${item.detail}</div>
          <label class="field" style="margin-top: 10px">
            <span>补充说明</span>
            <input data-question-id="${item.id}" value="${state.clarificationAnswers[item.id] || ""}" placeholder="在这里补充更具体的定义或阈值" />
          </label>
          <div class="pill-row" style="margin-top: 10px">
            ${(item.suggested_choices || []).map((choice) => `<button type="button" class="pill strategy-choice-pill" data-question-id="${item.id}" data-choice="${choice}">${choice}</button>`).join("")}
          </div>
        </div>
      `,
    )
    .join("");
  nodes.questions.querySelectorAll("input[data-question-id]").forEach((node) => {
    node.addEventListener("input", (event) => {
      state.clarificationAnswers[node.dataset.questionId] = event.target.value;
    });
  });
  nodes.questions.querySelectorAll(".strategy-choice-pill").forEach((node) => {
    node.addEventListener("click", () => {
      const questionId = node.dataset.questionId;
      const choice = node.dataset.choice || "";
      state.clarificationAnswers[questionId] = choice;
      const input = nodes.questions.querySelector(`input[data-question-id="${questionId}"]`);
      if (input) {
        input.value = choice;
      }
    });
  });
}

function renderClarificationRound(summary) {
  if (!summary) {
    nodes.clarificationProgress.textContent = "等待澄清进度。";
    nodes.clarificationAnswered.textContent = "当前还没有已确认的补充项。";
    return;
  }
  const statusClass =
    summary.status === "completed"
      ? "supported"
      : summary.status === "followup_pending"
        ? "limited"
        : "unsupported";
  nodes.clarificationProgress.innerHTML = `
    <div class="capability-status capability-${statusClass}">
      <strong>${summary.stage_label}</strong>
      <span>${summary.guidance}</span>
    </div>
    <div class="pill-row" style="margin-top: 10px">
      <span class="pill">已确认 ${summary.answered_count || 0} 项</span>
      <span class="pill">待补充 ${summary.pending_count || 0} 项</span>
      ${summary.next_focus ? `<span class="pill">当前重点：${summary.next_focus}</span>` : ""}
    </div>
    <div class="muted-note" style="margin-top: 10px">上下文记忆：${summary.memory_summary || "当前还没有已确认的补充项。"}</div>
  `;
  const answered = summary.answered_items || [];
  const pending = summary.pending_topics || [];
  nodes.clarificationAnswered.innerHTML = answered.length || pending.length
    ? [
        ...(answered.length
          ? answered.map(
              (item) => `
            <div class="list-item">
              <strong>${item.title}</strong>
              <div class="muted-note">${item.answer}</div>
            </div>
          `,
            )
          : []),
        ...(pending.length
          ? pending.map(
              (item) => `
            <div class="list-item">
              <strong>${item.title}</strong>
              <div class="muted-note">${
                item.round_type === "followup"
                  ? `继续追问，基于：${item.depends_on_title || item.depends_on || "上一轮补充"}`
                  : "第一轮待确认项"
              }</div>
            </div>
          `,
            )
          : []),
      ].join("")
    : "当前还没有已确认的补充项。";
}

function renderUnsupportedItems(items) {
  if (!items?.length) {
    nodes.unsupportedItems.textContent = "当前没有识别到不支持项或未来函数风险。";
    return;
  }
  nodes.unsupportedItems.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          <div class="muted-note">${item.detail}</div>
        </div>
      `,
    )
    .join("");
}

function renderNaturalLanguageView() {
  nodes.naturalLanguageView.textContent = nodes.prompt.value.trim() || "等待输入自然语言策略。";
}

function renderStructuredSpecView(spec) {
  if (!spec) {
    nodes.structuredSpecView.textContent = "等待生成结构化规格。";
    return;
  }
  const aiHints = spec.ai_structured_hints || {};
  const aiFieldTargets = (spec.ai_field_targets || [])
    .map((item) => `${item.label}：${item.reason}`)
    .join("；");
  const aiValueTargets = (spec.ai_value_targets || [])
    .map(
      (item) =>
        `${item.label}：${(item.suggested_values || []).join(" / ")}${item.reason ? `（${item.reason}）` : ""}`,
    )
    .join("；");
  const sections = [
    ["市场", `${spec.market_scope_label} / ${spec.market}`],
    ["资产类型", spec.asset_type],
    ["分析模式", spec.analysis_mode === "multi_timeframe" ? "混合周期" : "单周期"],
    ["主周期", spec.primary_timeframe_label],
    ["观察周期", (spec.observation_timeframe_labels || []).join(" / ") || "无"],
    ["入场规则数", String(spec.entry_rule_count || 0)],
    ["入场上下文", String(spec.entry_context_count || 0)],
    ["离场规则数", String(spec.exit_rule_count || 0)],
    ["离场上下文", String(spec.exit_context_count || 0)],
    [
      "仓位与持仓",
      Object.entries(spec.position || {})
        .map(([key, value]) => `${key}: ${String(value)}`)
        .join("；") || "无",
    ],
    ["执行假设", (spec.execution_assumptions || []).join("；") || "无"],
    ["澄清上下文记忆", spec.clarification_memory || "当前无已确认补充项"],
    ["AI 候选摘要", spec.ai_candidate_summary || "当前无 AI 候选摘要"],
    ["AI 模型", spec.ai_profile_label || "当前未显式显示"],
    ["AI 市场理解", aiHints.market_scope_hint || "当前无"],
    ["AI 周期提示", (aiHints.timeframe_hints || []).join(" / ") || "当前无"],
    ["AI 数据依赖", (aiHints.data_dependencies || []).join("；") || "当前无"],
    ["AI 入场意图", (aiHints.entry_intent || []).join("；") || "当前无"],
    ["AI 过滤意图", (aiHints.filter_intent || []).join("；") || "当前无"],
    ["AI 离场意图", (aiHints.exit_intent || []).join("；") || "当前无"],
    ["AI 风控意图", (aiHints.risk_controls || []).join("；") || "当前无"],
    ["AI 仓位意图", aiHints.position_intent || "当前无"],
    ["AI 执行时序意图", aiHints.execution_timing_intent || "当前无"],
    ["AI 执行假设", (aiHints.execution_assumptions || []).join("；") || "当前无"],
    ["AI 建议优先核对字段", aiFieldTargets || "当前无"],
    ["AI 建议优先确认值域", aiValueTargets || "当前无"],
    ["AI 待确认项", (spec.ai_unresolved_items || []).join("；") || "无"],
    [
      "待补充项",
      (spec.open_questions || []).join("；") || "当前无待补充项",
    ],
  ];
  nodes.structuredSpecView.innerHTML = sections
    .map(
      ([title, detail]) => `
        <div class="list-item">
          <strong>${title}</strong>
          <div class="muted-note">${detail}</div>
        </div>
      `,
    )
    .join("");
}

function renderHardValidationView(validation) {
  if (!validation) {
    nodes.hardValidationView.textContent = "等待生成平台校验结果。";
    return;
  }
  nodes.hardValidationView.innerHTML = (validation.checks || [])
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          <div class="pill-row" style="margin: 8px 0">
            <span class="pill">${
              item.status === "pass"
                ? "通过"
                : item.status === "warn"
                  ? "需确认"
                  : "拒绝"
            }</span>
          </div>
          <div class="muted-note">${item.detail}</div>
        </div>
      `,
    )
    .join("");
}

function renderGenerationPipelineView(items) {
  if (!items?.length) {
    nodes.generationPipelineView.textContent = "等待生成链路结果。";
    return;
  }
  nodes.generationPipelineView.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.title}</strong>
          <div class="pill-row" style="margin: 8px 0">
            <span class="pill">${
              item.status === "pass"
                ? "通过"
                : item.status === "warn"
                  ? "需确认"
                  : "拒绝"
            }</span>
          </div>
          <div class="muted-note">${item.summary}</div>
          <div class="muted-note" style="margin-top: 6px">${item.detail}</div>
        </div>
      `,
    )
    .join("");
}

function renderFieldMappingView(items) {
  if (!items?.length) {
    nodes.fieldMappingView.textContent = "等待生成字段级对照。";
    return;
  }
  nodes.fieldMappingView.innerHTML = items
    .map(
      (item) => `
        <div class="list-item">
          <strong>${item.label}</strong>
          <div class="muted-note">用户表达：${item.user_expression || "无"}</div>
          <div class="muted-note">结构化规格：${item.structured_value || "无"}</div>
          <div class="muted-note">DSL 路径：${item.dsl_path || "无"}</div>
          <div class="muted-note">Python 映射：${item.python_mapping || "无"}</div>
          <pre class="result-box light" style="margin-top: 10px">DSL片段
${item.dsl_snippet || "无"}</pre>
          <pre class="result-box light" style="margin-top: 10px">Python片段
${item.python_snippet || "无"}</pre>
        </div>
      `,
    )
    .join("");
}

function getCapabilityBase(marketScope) {
  return (
    state.platformCapabilities.find((item) => item.market_scope === marketScope) || {
      market_scope: marketScope,
      market_scope_label: marketScope,
      strategy_label: "可生成并保存策略语义",
      backtest_label: "当前暂不开放真实回测",
      replay_label: "复盘支持有限",
      data_label: "数据接入尚未开放",
      backtest_status: "unsupported",
      notes: [],
    }
  );
}

function summarizeSelectedCapability() {
  const marketScope = nodes.marketScope.value;
  const selectedTimeframes = getSelectedTimeframes();
  const primaryTimeframe = nodes.timeframe.value;
  const base = getCapabilityBase(marketScope);
  const isLimited =
    marketScope === "cn_equity" &&
    (primaryTimeframe !== "1d" || selectedTimeframes.length > 1);
  const backtestLabel =
    marketScope !== "cn_equity"
      ? base.backtest_label
      : isLimited
        ? "仅支持日线兼容层回测"
        : "可直接运行真实日线回测";
  const warning =
    marketScope !== "cn_equity"
      ? `${base.market_scope_label} 当前仅支持策略语义与规则研究，回测中心会阻止发起真实回测。`
      : isLimited
        ? "当前策略包含非日线或混合周期条件。保存与研究语义正常，但真实回测仍按日线兼容层执行。"
        : "当前组合处于平台真实回测主链路内，可直接进入回测中心验证。";
  return {
    ...base,
    timeframes: selectedTimeframes,
    primaryTimeframe,
    backtest_mode_label: backtestLabel,
    backtest_warning: warning,
    requiresCompatibilityNotice: isLimited,
  };
}

function renderCapabilitySummary(summary) {
  const noteItems = [
    `策略生成：${summary.strategy_label}`,
    `真实回测：${summary.backtest_mode_label}`,
    `交易复盘：${summary.replay_label}`,
    `数据链路：${summary.data_label}`,
  ];
  const detail = summary.requiresCompatibilityNotice
    ? `当前选择的是 ${summary.market_scope_label} / ${summary.timeframes.join(" / ")}，需要按“日线兼容层”理解回测结果。`
    : `当前选择的是 ${summary.market_scope_label} / ${summary.timeframes.join(" / ")}。`;
  nodes.capabilitySummary.innerHTML = `
    <div class="capability-status capability-${summary.backtest_status}">
      <strong>${summary.market_scope_label}</strong>
      <span>${summary.backtest_mode_label}</span>
    </div>
    <div class="muted-note">${detail}</div>
    <div class="muted-note">${summary.backtest_warning}</div>
    <div class="pill-row" style="margin-top: 12px">
      ${noteItems.map((item) => `<span class="pill">${item}</span>`).join("")}
    </div>
  `;
}

function renderCapabilityMatrix() {
  if (!state.platformCapabilities.length) {
    nodes.capabilityMatrix.textContent = "当前无法读取市场支持状态。";
    return;
  }
  nodes.capabilityMatrix.innerHTML = state.platformCapabilities
    .map(
      (item) => `
        <div class="capability-row">
          <div>
            <strong>${item.market_scope_label}</strong>
            <div class="muted-note">${item.strategy_label}</div>
          </div>
          <div class="capability-tags">
            <span class="capability-chip capability-${item.backtest_status}">回测：${item.backtest_label}</span>
            <span class="capability-chip capability-${item.replay_status}">复盘：${item.replay_label}</span>
            <span class="capability-chip capability-${item.data_status}">数据：${item.data_label}</span>
          </div>
        </div>
      `,
    )
    .join("");
}

function syncStrategyCapabilityState(summary = summarizeSelectedCapability()) {
  renderCapabilitySummary(summary);
  renderCapabilityMatrix();
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
    nodes.taskCenter.textContent = "还没有后台策略生成任务。";
    nodes.taskCenter.className = "list empty-state bounded-scroll bounded-scroll-lg";
    return;
  }
  nodes.taskCenter.className = "list bounded-scroll bounded-scroll-lg";
  nodes.taskCenter.innerHTML = state.taskCenterItems
    .map(
      (item) => `
        <div class="list-item compact-item">
          <strong>策略生成 · ${formatTaskStatus(item.status)}</strong>
          <div class="muted-note">${item.prompt || "未记录策略描述"}</div>
          <div class="muted-note">${item.market || "-"} · ${item.timeframe || "-"} · ${item.market_scope || "-"}</div>
          <div class="muted-note">${item.decision_label || "等待生成"}${item.decision_summary ? ` · ${item.decision_summary}` : ""}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="btn ghost strategy-open-task-btn" type="button" data-task-id="${item.generation_id}" ${item.status === "succeeded" ? "" : "disabled"}>打开结果</button>
          </div>
        </div>
      `,
    )
    .join("");
  nodes.taskCenter.querySelectorAll(".strategy-open-task-btn").forEach((node) => {
    node.addEventListener("click", async () => {
      const taskId = node.dataset.taskId;
      if (!taskId) {
        return;
      }
      try {
        const payload = await api(`/api/v1/strategies/generations/${taskId}`);
        applyGeneratedStrategy(payload.data);
        setStatus("已重新打开后台策略生成结果。");
      } catch (error) {
        setStatus(error.message);
      }
    });
  });
}

async function loadTaskCenter() {
  const payload = await api("/api/v1/strategies/generations");
  state.taskCenterItems = payload.data.items || [];
  renderTaskCenter();
}

async function generateStrategy() {
  const clarificationAnswers = Object.fromEntries(
    Object.entries(state.clarificationAnswers).filter(([, value]) => String(value || "").trim()),
  );
  const created = await api("/api/v1/strategies/generations", {
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
      clarification_answers: clarificationAnswers,
      llm_profile: nodes.llmProfile.value || "module_default",
    }),
  });
  pendingGenerationTaskId = created.data.task_id;
  registerBackgroundTask({
    task_id: created.data.task_id,
    status_url: created.data.status_url,
    label: "策略生成任务",
    module: "strategy",
    queued_message: "策略生成已转入后台，你可以先去其他模块继续操作。",
    success_message: "策略生成已完成。",
    failure_message: "策略生成失败。",
  });
  setInlineStatus(nodes.inlineStatus, "策略生成已转入后台。", "running");
  setStatus("正在后台生成 Python 策略...");
  loadTaskCenter().catch(() => {});
}

function applyGeneratedStrategy(data) {
  state.strategySpec = data.strategy_dsl;
  state.strategyPython = data.strategy_python;
  state.generationDecision = data.generation_decision;
  state.structuredSpec = data.structured_spec;
  state.hardValidation = data.hard_validation;
  state.generationPipeline = data.generation_pipeline || [];
  state.fieldMapping = data.field_mapping || [];
  state.clarificationRound = data.clarification_round || null;
  nodes.summary.textContent = data.human_summary;
  nodes.python.textContent = data.strategy_python;
  nodes.spec.textContent = pretty(data.strategy_dsl);
  renderNaturalLanguageView();
  renderGenerationDecision(data.generation_decision);
  renderUnderstandingCard(data.understanding_card);
  renderStructuredSpecView(data.structured_spec);
  renderHardValidationView(data.hard_validation);
  renderGenerationPipelineView(data.generation_pipeline);
  renderFieldMappingView(data.field_mapping);
  renderClarificationRound(data.clarification_round);
  renderQuestions(data.questions_for_user);
  renderUnsupportedItems(data.unsupported_items);
  nodes.ambiguities.innerHTML = data.ambiguities.length
      ? data.ambiguities.map((item) => `<span class="pill">${item}</span>`).join("")
      : '<span class="pill">无额外歧义</span>';
  if (data.matched_custom_indicators?.length) {
    nodes.ambiguities.innerHTML += data.matched_custom_indicators
      .map((item) => `<span class="pill">已调用指标：${item.name}</span>`)
      .join("");
  }
  if (data.matched_terms?.length) {
    nodes.ambiguities.innerHTML += data.matched_terms
      .map((item) => `<span class="pill">术语已识别：${item.term}</span>`)
      .join("");
  }
  if (data.capability_summary) {
    renderCapabilitySummary({
      ...data.capability_summary,
      requiresCompatibilityNotice:
        data.capability_summary.requires_compatibility_notice || false,
    });
  }
  if (data.generation_decision?.summary) {
    document.querySelector("#status-banner").textContent = data.generation_decision.summary;
  }
  syncStrategyActionState();
  setInlineStatus(nodes.inlineStatus, "策略生成完成。", "success");
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
      version_label: nodes.versionLabel.value,
      natural_language_prompt: nodes.prompt.value,
      strategy_dsl: state.strategySpec,
      strategy_python: state.strategyPython,
    }),
  });
  setSelectedVersion(
    payload.data.version_id,
    nodes.title.value,
    payload.data.version_label || nodes.versionLabel.value,
  );
  nodes.versionLabel.value = payload.data.version_label || nodes.versionLabel.value;
  nodes.currentVersion.textContent = `系统版本ID：${payload.data.version_id}`;
  syncStrategyActionState();
  setStatus("项目已保存，当前可以去回测中心继续回测。");
}

async function applyClarifications() {
  if (state.generationDecision?.status !== "needs_confirmation") {
    return;
  }
  await generateStrategy();
}

function restoreSelection() {
  const { versionId, versionLabel, title } = getSelectedVersion();
  if (versionId) {
    nodes.currentVersion.textContent = `系统版本ID：${versionId}`;
  }
  if (title) {
    nodes.title.value = title;
  }
  if (versionLabel) {
    nodes.versionLabel.value = versionLabel;
  }
}

async function loadKnowledgePreview() {
  const [indicatorPayload, glossaryPayload, capabilityPayload, llmProfilePayload] = await Promise.all([
    api("/api/v1/indicators/custom"),
    api("/api/v1/rules/glossary"),
    api("/api/v1/platform/capabilities"),
    fetchLlmProfiles(),
  ]);
  const indicators = indicatorPayload.data.items;
  const glossary = glossaryPayload.data.items.slice(0, 8);
  state.platformCapabilities = capabilityPayload.data.items || [];

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
  populateLlmProfileSelect(nodes.llmProfile, llmProfilePayload, "strategy");
  syncStrategyCapabilityState();
}

document
  .querySelector("#generate-strategy-btn")
  .addEventListener("click", handle(generateStrategy));
document
  .querySelector("#save-project-btn")
  .addEventListener("click", handle(saveProject));
nodes.applyClarificationsButton.addEventListener("click", handle(applyClarifications));
nodes.goBacktestsLink.addEventListener("click", (event) => {
  if (nodes.goBacktestsLink.getAttribute("aria-disabled") === "true") {
    event.preventDefault();
  }
});
nodes.timeframe.addEventListener("change", syncTimeframeSelection);
nodes.timeframe.addEventListener("change", () => syncStrategyCapabilityState());
nodes.marketScope.addEventListener("change", applyMarketPreset);
nodes.prompt.addEventListener("input", renderNaturalLanguageView);
nodes.timeframeOptions.forEach((node) =>
  node.addEventListener("change", () => syncStrategyCapabilityState()),
);

restoreSelection();
syncTimeframeSelection();
renderGenerationDecision(null);
renderUnderstandingCard(null);
renderNaturalLanguageView();
renderStructuredSpecView(null);
renderHardValidationView(null);
renderGenerationPipelineView([]);
renderFieldMappingView([]);
renderClarificationRound(null);
renderQuestions([]);
renderUnsupportedItems([]);
syncStrategyActionState();
loadKnowledgePreview().catch((error) => setStatus(error.message));
nodes.refreshTasksButton.addEventListener("click", () => {
  loadTaskCenter().catch((error) => setStatus(error.message));
});
subscribeBackgroundTasks((task) => {
  if (task.module !== "strategy" || task.task_id !== pendingGenerationTaskId) {
    return;
  }
  if (task.status === "succeeded" && task.data) {
    applyGeneratedStrategy(task.data);
    loadTaskCenter().catch(() => {});
    pendingGenerationTaskId = null;
    return;
  }
  if (["failed", "canceled"].includes(task.status)) {
    setInlineStatus(nodes.inlineStatus, task.data?.error?.message || task.error_message || "策略生成失败。", "error");
    setStatus(task.data?.error?.message || task.error_message || "策略生成失败。");
    loadTaskCenter().catch(() => {});
    pendingGenerationTaskId = null;
  }
});
clearInlineStatus(nodes.inlineStatus, "等待你描述策略想法。生成任务会在后台完成，并在完成后提醒你。");
loadTaskCenter().catch((error) => setStatus(error.message));
